__all__ = (
    "DOMAIN",
    "CONFIG_SCHEMA",
    "async_setup_entry",
    "async_setup",
    "async_authenticate_api_object",
    "async_unload_entry",
)

import asyncio
import logging
from typing import Callable, Dict, TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry, SOURCE_IMPORT
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.typing import ConfigType, HomeAssistantType

from ._schemas import CONFIG_SCHEMA
from .api import (
    API,
    DEFAULT_APP_VERSION,
    DEFAULT_DEVICE_AGENT,
    DEFAULT_DEVICE_OS,
    DEFAULT_TOKEN,
    DEFAULT_USER_AGENT,
    MoscowPGUException,
    Profile,
)
from .const import (
    CONF_APP_VERSION,
    CONF_DEVICE_AGENT,
    CONF_DEVICE_INFO,
    CONF_DEVICE_OS,
    CONF_GUID,
    CONF_TOKEN,
    CONF_USER_AGENT,
    DATA_ENTITIES,
    DATA_FINAL_CONFIG,
    DATA_UPDATERS,
    DATA_UPDATE_LISTENERS,
    DATA_YAML_CONFIG,
    DOMAIN,
    SUPPORTED_PLATFORMS,
)
from .util import (
    async_authenticate_api_object,
    async_load_session,
    find_existing_entry,
    generate_guid,
)

if TYPE_CHECKING:
    from ._base import MoscowPGUEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistantType, config: ConfigType) -> bool:
    domain_config = config.get(DOMAIN)
    if not domain_config:
        return True

    domain_data = {}
    hass.data[DOMAIN] = domain_data

    yaml_config = {}
    hass.data[DATA_YAML_CONFIG] = yaml_config

    for user_cfg in domain_config:
        username = user_cfg[CONF_USERNAME]

        _LOGGER.debug('User "%s" entry from YAML', username)

        existing_entry = find_existing_entry(hass, username)
        if existing_entry:
            if existing_entry.source == SOURCE_IMPORT:
                yaml_config[username] = user_cfg
                _LOGGER.debug('Skipping existing import binding for "%s"', username)
            else:
                _LOGGER.warning(
                    "YAML config for user %s is overridden by another config entry!", username
                )
            continue

        yaml_config[username] = user_cfg
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN, context={"source": SOURCE_IMPORT}, data={CONF_USERNAME: username}
            )
        )

    if yaml_config:
        _LOGGER.debug("YAML usernames: %s", '"' + '", "'.join(yaml_config.keys()) + '"')
    else:
        _LOGGER.debug("No configuration added from YAML")

    return True


async def async_setup_entry(hass: HomeAssistantType, config_entry: ConfigEntry) -> bool:
    username = config_entry.data[CONF_USERNAME]
    yaml_config = hass.data.get(DATA_YAML_CONFIG)

    if config_entry.source == SOURCE_IMPORT:
        if not (yaml_config and username in yaml_config):
            _LOGGER.info(
                "Removing entry %s after removal from YAML configuration." % config_entry.entry_id
            )
            hass.async_create_task(hass.config_entries.async_remove(config_entry.entry_id))
            return False
        final_config = {**config_entry.data}
    else:
        from ._schemas import CONFIG_ENTRY_SCHEMA

        final_config = CONFIG_ENTRY_SCHEMA({**config_entry.data, **config_entry.options})

    _LOGGER.debug('Setting up config entry for user "%s"' % username)

    from ._base import MoscowPGUEntity

    session_id = await async_load_session(hass, username)

    device_info = final_config[CONF_DEVICE_INFO]
    api_object = API(
        username=username,
        password=final_config[CONF_PASSWORD],
        session_id=session_id,
        cache_lifetime=MoscowPGUEntity.MIN_SCAN_INTERVAL.total_seconds(),
        token=final_config[CONF_TOKEN],
        app_version=device_info[CONF_APP_VERSION],
        device_os=device_info[CONF_DEVICE_OS],
        device_agent=device_info[CONF_DEVICE_AGENT],
        user_agent=device_info[CONF_USER_AGENT],
        guid=device_info[CONF_GUID],
    )

    try:
        try:
            await async_authenticate_api_object(hass, api_object)

        except MoscowPGUException as e:
            raise ConfigEntryNotReady("Error occurred while authenticating: %s", e)
    except BaseException:
        await api_object.close_session()
        raise

    entry_id = config_entry.entry_id

    hass.data.setdefault(DOMAIN, {})[username] = api_object
    hass.data.setdefault(DATA_FINAL_CONFIG, {})[entry_id] = final_config
    hass.data.setdefault(DATA_ENTITIES, {})[entry_id] = {}

    for platform in SUPPORTED_PLATFORMS:
        hass.async_create_task(
            hass.config_entries.async_forward_entry_setup(
                config_entry,
                platform,
            )
        )

    update_listener = config_entry.add_update_listener(async_reload_entry)
    hass.data.setdefault(DATA_UPDATE_LISTENERS, {})[entry_id] = update_listener

    return True


async def async_reload_entry(
    hass: HomeAssistantType,
    config_entry: ConfigEntry,
) -> None:
    """Reload Moscow PGU entry"""
    _LOGGER.info("Reloading configuration entry")
    await hass.config_entries.async_reload(config_entry.entry_id)


async def async_migrate_entry(hass: HomeAssistantType, config_entry: ConfigEntry) -> bool:
    from .config_flow import MoscowPGUConfigFlow

    current_version = config_entry.version
    _LOGGER.debug(f"Migrating entry {config_entry.entry_id} from version {current_version}")

    if current_version < 2:
        if config_entry.source != SOURCE_IMPORT:
            new_data = {**config_entry.data}
            new_options = {**config_entry.options}

            from ._schemas import DEVICE_INFO_SCHEMA

            for src in (new_data, new_options):
                device_info = {}
                for key in DEVICE_INFO_SCHEMA.schema.keys():
                    str_key = str(key)
                    try:
                        device_info[str_key] = src.pop(str_key)
                    except KeyError:
                        pass
                src[CONF_DEVICE_INFO] = DEVICE_INFO_SCHEMA(device_info)

            config_entry.data = new_data
            config_entry.options = new_options

        config_entry.version = 2

    return True


async def async_unload_entry(hass: HomeAssistantType, config_entry: ConfigEntry) -> bool:
    username = config_entry.data[CONF_USERNAME]

    if DATA_YAML_CONFIG in hass.data and username in hass.data[DOMAIN]:
        # noinspection PyUnusedLocal
        api_object: API = hass.data[DOMAIN].pop(username)
        await api_object.close_session()

    if DATA_UPDATERS in hass.data and config_entry.entry_id in hass.data[DATA_UPDATERS]:
        updaters: Dict[str, Callable] = hass.data[DATA_UPDATERS].pop(config_entry.entry_id)
        for cancel_callback in updaters.values():
            cancel_callback()

    cancel_listener = hass.data[DATA_UPDATE_LISTENERS].pop(config_entry.entry_id)
    cancel_listener()

    await asyncio.gather(
        *(
            hass.config_entries.async_forward_entry_unload(config_entry, domain)
            for domain in SUPPORTED_PLATFORMS
        )
    )

    return True
