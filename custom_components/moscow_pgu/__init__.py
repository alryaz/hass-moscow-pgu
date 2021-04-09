import hashlib
import logging
from datetime import timedelta
from typing import Callable, Dict, Optional

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

DEFAULT_SCAN_INTERVAL_WATER_COUNTERS = timedelta(days=1)
DEFAULT_SCAN_INTERVAL_FSSP_DEBTS = timedelta(days=1)
DEFAULT_SCAN_INTERVAL_PROFILE = timedelta(hours=2)
DEFAULT_SCAN_INTERVAL_VEHICLES = timedelta(hours=2)

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

SCAN_INTERVAL_SCHEMA = vol.Schema({
    vol.Optional(CONF_WATER_COUNTERS, default=DEFAULT_SCAN_INTERVAL_WATER_COUNTERS):
        positive_clamped_time_period,
    vol.Optional(CONF_FSSP_DEBTS, default=DEFAULT_SCAN_INTERVAL_FSSP_DEBTS):
        positive_clamped_time_period,
    vol.Optional(CONF_PROFILE, default=DEFAULT_SCAN_INTERVAL_PROFILE):
        positive_clamped_time_period,
    vol.Optional(CONF_VEHICLES, default=DEFAULT_SCAN_INTERVAL_VEHICLES):
        positive_clamped_time_period,
})

FSSP_PROFILE_SCHEMA = vol.Schema({
    vol.Required(CONF_FIRST_NAME): cv.string,
    vol.Required(CONF_LAST_NAME): cv.string,
    vol.Optional(CONF_MIDDLE_NAME): cv.string,
    vol.Required(CONF_BIRTH_DATE): cv.date,
})

CONFIG_SCHEMA = vol.Schema({
    DOMAIN: vol.All(cv.ensure_list, vol.Length(min=1), [{
        vol.Required(CONF_USERNAME): cv.string,
        vol.Required(CONF_PASSWORD): cv.string,
        vol.Optional(CONF_DEVICE_INFO): DEVICE_INFO_SCHEMA,
        vol.Optional(CONF_TRACK_FSSP_PROFILES): vol.All(
            cv.ensure_list,
            vol.Length(min=1),
            [FSSP_PROFILE_SCHEMA]
        ),
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
    }])
}, extra=vol.ALLOW_EXTRA)


@callback
def _find_existing_entry(hass: HomeAssistantType, username: str) -> Optional[ConfigEntry]:
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

        existing_entry = _find_existing_entry(hass, username)
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

    if config_entry.source == SOURCE_IMPORT:
        if not yaml_config or username not in yaml_config:
            _LOGGER.info('Removing entry %s after removal from YAML configuration.' % config_entry.entry_id)
            hass.async_create_task(
                hass.config_entries.async_remove(config_entry.entry_id)
            )
            return False

        data = yaml_config[username]

    else:
        data = config_entry.data

    device_info = None
    scan_interval = None

    if config_entry.options:
        device_info = config_entry.options.get(CONF_DEVICE_INFO)
        scan_interval = config_entry.options.get(CONF_SCAN_INTERVAL)

    if device_info is None:
        device_info = data.get(CONF_DEVICE_INFO)
    else:
        device_info = DEVICE_INFO_SCHEMA(device_info)

    if scan_interval is None:
        scan_interval = data.get(CONF_SCAN_INTERVAL)
        if scan_interval is None:
            scan_interval = SCAN_INTERVAL_SCHEMA({})
    else:
        scan_interval = SCAN_INTERVAL_SCHEMA(scan_interval)

    _LOGGER.debug('Setting up config entry for user "%s"' % username)

    try:
        password = data[CONF_PASSWORD]
        additional_args = {} if device_info is None else {
            arg: device_info[conf]
            for arg, conf in {'app_version': CONF_APP_VERSION,
                              'device_os': CONF_DEVICE_OS,
                              'device_agent': CONF_DEVICE_AGENT,
                              'user_agent': CONF_USER_AGENT,
                              'guid': CONF_GUID}.items()
            if conf in device_info
        }

        if scan_interval is not None:
            additional_args['cache_lifetime'] = \
                (min(scan_interval.values()) - timedelta(seconds=5)).total_seconds()

        if not additional_args.get('guid'):
            # @TODO: this can be randomly generated?
            hash_str = 'homeassistant&' + username + '&' + password
            additional_args['guid'] = hashlib.md5(hash_str.encode('utf-8')).hexdigest().lower()

        _LOGGER.debug('Authenticating with user "%s", args: %s',
                      username, additional_args)

        api = API(
            username=username,
            password=data[CONF_PASSWORD],
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
