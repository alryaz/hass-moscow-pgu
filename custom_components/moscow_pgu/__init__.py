import hashlib
import logging
from datetime import timedelta
from typing import Callable, Dict, Optional, TypeVar, MutableMapping, Mapping, Hashable

import voluptuous as vol
from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
from homeassistant.config_entries import ConfigEntry, SOURCE_IMPORT
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD, CONF_SCAN_INTERVAL
from homeassistant.core import callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import HomeAssistantType, ConfigType

from custom_components.moscow_pgu.moscow_pgu_api import API, MoscowPGUException

_LOGGER = logging.getLogger(__name__)

DOMAIN = 'moscow_pgu'

DATA_CONFIG = DOMAIN + '_config'
DATA_UPDATERS = DOMAIN + '_updaters'
DATA_ENTITIES = DOMAIN + '_entities'

CONF_DEVICE_INFO = 'device_info'
CONF_APP_VERSION = 'app_version'
CONF_DEVICE_OS = 'device_os'
CONF_DEVICE_AGENT = 'device_agent'
CONF_USER_AGENT = 'user_agent'
CONF_TOKEN = 'token'
CONF_GUID = 'guid'
CONF_WATER_COUNTERS = 'water_counters'
CONF_OFFENSES = 'offenses'
CONF_FSSP_DEBTS = 'fssp_debts'
CONF_PROFILE = 'profile'
CONF_VEHICLES = 'vehicles'
CONF_FIRST_NAME = 'first_name'
CONF_LAST_NAME = 'last_name'
CONF_MIDDLE_NAME = 'middle_name'
CONF_BIRTH_DATE = 'birth_date'
CONF_TRACK_FSSP_PROFILES = 'track_fssp_profiles'
CONF_DRIVING_LICENSES = 'driving_licenses'
CONF_NAME_FORMAT = 'name_format'
CONF_NUMBER = 'number'
CONF_ISSUE_DATE = 'issue_date'
CONF_FLATS = 'flats'
CONF_ELECTRIC_COUNTERS = 'electric_counters'

DEFAULT_SCAN_INTERVAL_WATER_COUNTERS = timedelta(days=1)
DEFAULT_SCAN_INTERVAL_FSSP_DEBTS = timedelta(days=1)
DEFAULT_SCAN_INTERVAL_PROFILE = timedelta(hours=2)
DEFAULT_SCAN_INTERVAL_VEHICLES = timedelta(hours=2)
DEFAULT_SCAN_INTERVAL_FLATS = timedelta(days=1)
DEFAULT_SCAN_INTERVAL_DRIVING_LICENSES = timedelta(hours=2)
DEFAULT_SCAN_INTERVAL_ELECTRIC_COUNTERS = timedelta(days=1)

DEFAULT_NAME_FORMAT_WATER_COUNTERS = '{type} Water Counter {identifier}'
DEFAULT_NAME_FORMAT_FSSP_DEBTS = 'FSSP Debts - {identifier}'
DEFAULT_NAME_FORMAT_PROFILE = 'Profile {identifier}'
DEFAULT_NAME_FORMAT_VEHICLES = 'Vehicle {identifier}'
DEFAULT_NAME_FORMAT_FLATS = 'Flat {identifier}'
DEFAULT_NAME_FORMAT_DRIVING_LICENSES = 'Driving License {identifier}'
DEFAULT_NAME_ELECTRIC_COUNTERS = 'Electric Counter {identifier}'

MIN_SCAN_INTERVAL = timedelta(minutes=1)

DEVICE_INFO_SCHEMA = vol.Schema({
    vol.Optional(CONF_APP_VERSION): cv.string,
    vol.Optional(CONF_DEVICE_OS): cv.string,
    vol.Optional(CONF_DEVICE_AGENT): cv.string,
    vol.Optional(CONF_USER_AGENT): cv.string,
    vol.Optional(CONF_GUID): cv.string,
})

positive_clamped_time_period = vol.All(
    cv.positive_time_period,
    vol.Range(min=MIN_SCAN_INTERVAL, min_included=True)
)

SENSOR_CONFIGURATION_KEYS = (CONF_WATER_COUNTERS, CONF_FSSP_DEBTS, CONF_PROFILE, CONF_VEHICLES,
                             CONF_FLATS, CONF_DRIVING_LICENSES)

_OPTIONAL_SENSOR_CONFIGURATION_KEYS = map(vol.Optional, SENSOR_CONFIGURATION_KEYS)

SCAN_INTERVAL_SCHEMA = vol.Schema(dict.fromkeys(_OPTIONAL_SENSOR_CONFIGURATION_KEYS, positive_clamped_time_period))

NAME_FORMATS_SCHEMA = vol.Schema(dict.fromkeys(_OPTIONAL_SENSOR_CONFIGURATION_KEYS, cv.string))

FSSP_PROFILE_SCHEMA = vol.Schema({
    vol.Required(CONF_FIRST_NAME): cv.string,
    vol.Required(CONF_LAST_NAME): cv.string,
    vol.Optional(CONF_MIDDLE_NAME): cv.string,
    vol.Required(CONF_BIRTH_DATE): cv.date,
})

DRIVING_LICENSE_SCHEMA = vol.Schema({
    vol.Required(CONF_NUMBER): cv.string,
    vol.Optional(CONF_ISSUE_DATE): cv.date,
})

OPTIONAL_ENTRY_SCHEMA = vol.Schema({
    vol.Optional(CONF_DEVICE_INFO): DEVICE_INFO_SCHEMA,
    vol.Optional(CONF_DRIVING_LICENSES): vol.All(cv.ensure_list, vol.Length(min=1), [
        vol.Optional(cv.string, lambda x: {CONF_NUMBER: x}),
        DRIVING_LICENSE_SCHEMA
    ]),
    vol.Optional(CONF_TRACK_FSSP_PROFILES): vol.All(
        cv.ensure_list,
        vol.Length(min=1),
        [FSSP_PROFILE_SCHEMA]
    ),
    vol.Optional(CONF_NAME_FORMAT): NAME_FORMATS_SCHEMA,
    vol.Optional(CONF_SCAN_INTERVAL):
        vol.Any(
            vol.All(
                positive_clamped_time_period,
                lambda x: {
                    str(key): x
                    for key in SCAN_INTERVAL_SCHEMA.schema.keys()
                }
            ),
            SCAN_INTERVAL_SCHEMA
        ),
}, extra=vol.ALLOW_EXTRA)

CONFIG_SCHEMA = vol.Schema({
    DOMAIN: vol.All(cv.ensure_list, [OPTIONAL_ENTRY_SCHEMA.extend({
        vol.Required(CONF_USERNAME): cv.string,
        vol.Required(CONF_PASSWORD): cv.string,
    }, extra=vol.PREVENT_EXTRA)])
}, extra=vol.ALLOW_EXTRA)


TMutableMapping = TypeVar('TMutableMapping', bound=MutableMapping)


def recursive_mapping_update(d: TMutableMapping, u: Mapping, filter_: Optional[Callable[[Hashable], bool]] = None) -> TMutableMapping:
    """
    Recursive mutable mapping updates.
    Borrowed from: https://stackoverflow.com/a/3233356
    :param d: Target mapping (mutable)
    :param u: Source mapping (any)
    :param filter_: (optional) Filter keys (`True` result carries keys from target to source)
    :return: Target mapping (mutable)
    """
    for k, v in u.items():
        if not (filter_ is None or filter_(k)):
            continue
        if isinstance(v, Mapping):
            d[k] = recursive_mapping_update(d.get(k, {}), v)
        else:
            d[k] = v
    return d


def extract_config(hass: HomeAssistantType, config_entry: ConfigEntry):
    """
    Exctact configuration for integration.
    :param hass: Home Assistant object
    :param config_entry: Configuration entry
    :return: Configuration dictionary
    """
    username = config_entry.data[CONF_USERNAME]

    if config_entry.source == SOURCE_IMPORT:
        return {**hass.data[DATA_CONFIG][username]}

    config = OPTIONAL_ENTRY_SCHEMA({**config_entry.data})

    if config_entry.options:
        options = OPTIONAL_ENTRY_SCHEMA({**config_entry.options})
        recursive_mapping_update(config, options, filter_=(CONF_USERNAME, CONF_PASSWORD).__contains__)

    return config


@callback
def find_existing_entry(hass: HomeAssistantType, username: str) -> Optional[ConfigEntry]:
    existing_entries = hass.config_entries.async_entries(DOMAIN)
    for config_entry in existing_entries:
        if config_entry.data[CONF_USERNAME] == username:
            return config_entry


async def async_setup(hass: HomeAssistantType, config: ConfigType) -> bool:
    domain_config = config.get(DOMAIN)
    if not domain_config:
        return True

    domain_data = {}
    hass.data[DOMAIN] = domain_data

    yaml_config = {}
    hass.data[DATA_CONFIG] = yaml_config

    for user_cfg in domain_config:
        username = user_cfg[CONF_USERNAME]

        _LOGGER.debug('User "%s" entry from YAML', username)

        existing_entry = find_existing_entry(hass, username)
        if existing_entry:
            if existing_entry.source == SOURCE_IMPORT:
                yaml_config[username] = user_cfg
                _LOGGER.debug('Skipping existing import binding for "%s"', username)
            else:
                _LOGGER.warning('YAML config for user %s is overridden by another config entry!', username)
            continue

        yaml_config[username] = user_cfg
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": SOURCE_IMPORT},
                data={CONF_USERNAME: username}
            )
        )

    if yaml_config:
        _LOGGER.debug('YAML usernames: %s', '"' + '", "'.join(yaml_config.keys()) + '"')
    else:
        _LOGGER.debug('No configuration added from YAML')

    return True


async def async_setup_entry(hass: HomeAssistantType, config_entry: ConfigEntry) -> bool:
    username = config_entry.data[CONF_USERNAME]
    yaml_config = hass.data.get(DATA_CONFIG)

    if config_entry.source == SOURCE_IMPORT and not (yaml_config and username in yaml_config):
        _LOGGER.info('Removing entry %s after removal from YAML configuration.' % config_entry.entry_id)
        hass.async_create_task(
            hass.config_entries.async_remove(config_entry.entry_id)
        )
        return False

    config = extract_config(hass, config_entry)

    device_info = None

    if config_entry.options:
        device_info = config_entry.options.get(CONF_DEVICE_INFO)

    if device_info is None:
        device_info = config.get(CONF_DEVICE_INFO)
    else:
        device_info = DEVICE_INFO_SCHEMA(device_info)

    _LOGGER.debug('Setting up config entry for user "%s"' % username)

    try:
        password = config[CONF_PASSWORD]
        additional_args = {} if device_info is None else {
            arg: device_info[conf]
            for arg, conf in {'app_version': CONF_APP_VERSION,
                              'device_os': CONF_DEVICE_OS,
                              'device_agent': CONF_DEVICE_AGENT,
                              'user_agent': CONF_USER_AGENT,
                              'guid': CONF_GUID}.items()
            if conf in device_info
        }

        # WARNING: Cache lifetime is updated at runtime

        if not additional_args.get('guid'):
            # @TODO: this can be randomly generated?
            hash_str = 'homeassistant&' + username + '&' + password
            additional_args['guid'] = hashlib.md5(hash_str.encode('utf-8')).hexdigest().lower()

        _LOGGER.debug('Authenticating with user "%s", args: %s',
                      username, additional_args)

        api = API(
            username=username,
            password=config[CONF_PASSWORD],
            **additional_args
        )
        await api.authenticate()

        _LOGGER.debug('Authentication successful for user "%s"', username)

    except MoscowPGUException as e:
        raise ConfigEntryNotReady('Error occurred while authenticating: %s', e)

    hass.data.setdefault(DOMAIN, {})[username] = api

    hass.async_create_task(
        hass.config_entries.async_forward_entry_setup(
            config_entry,
            SENSOR_DOMAIN
        )
    )

    return True


async def async_unload_entry(hass: HomeAssistantType, config_entry: ConfigEntry) -> bool:
    username = config_entry.data[CONF_USERNAME]

    if DATA_CONFIG in hass.data and username in hass.data[DOMAIN]:
        # noinspection PyUnusedLocal
        api_object: API = hass.data[DOMAIN].pop(username)
        # @TODO: do something with it?

    if DATA_UPDATERS in hass.data and config_entry.entry_id in hass.data[DATA_UPDATERS]:
        updaters: Dict[str, Callable] = hass.data[DATA_UPDATERS].pop(config_entry.entry_id)
        for cancel_callback in updaters.values():
            cancel_callback()

    hass.async_create_task(
        hass.config_entries.async_forward_entry_unload(
            config_entry,
            SENSOR_DOMAIN
        )
    )

    return True
