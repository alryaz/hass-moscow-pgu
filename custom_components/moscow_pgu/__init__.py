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
    CONF_DRIVING_LICENSES,
    CONF_FILTER,
    CONF_GUID,
    CONF_NAME_FORMAT,
    CONF_TOKEN,
    CONF_TRACK_FSSP_PROFILES,
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
    entry_id = config_entry.entry_id
    yaml_config = hass.data.get(DATA_YAML_CONFIG)

    if config_entry.source == SOURCE_IMPORT:
        if not (yaml_config and username in yaml_config):
            _LOGGER.info(
                f"[{username}] Removing entry {entry_id} " f"after removal from YAML configuration"
            )
            hass.async_create_task(hass.config_entries.async_remove(entry_id))
            return False
        final_config = yaml_config[username]
    else:
        from ._schemas import CONFIG_ENTRY_SCHEMA

        final_config = CONFIG_ENTRY_SCHEMA({**config_entry.data, **config_entry.options})

    _LOGGER.debug(f"[{username}] Setting up config entry")

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
            _LOGGER.error(f"[{username}] Could not set up config entry: {repr(e)}")
            raise ConfigEntryNotReady(str(e))

    except BaseException:
        await api_object.close_session()
        raise

    # Create holder for api object; save api object
    hass.data.setdefault(DOMAIN, {})[entry_id] = api_object

    # Create holder for final configuration; save final config
    hass.data.setdefault(DATA_FINAL_CONFIG, {})[entry_id] = final_config

    # Create holder for entities
    hass.data.setdefault(DATA_ENTITIES, {})[entry_id] = {}

    # Create holder for data updaters
    hass.data.setdefault(DATA_UPDATERS, {})[entry_id] = {}

    for platform in SUPPORTED_PLATFORMS:
        hass.async_create_task(
            hass.config_entries.async_forward_entry_setup(
                config_entry,
                platform,
            )
        )

    # Create update listener
    update_listener = config_entry.add_update_listener(async_reload_entry)

    # Create holder for entry update listeners cancellator; save entry update listener cancellator
    hass.data.setdefault(DATA_UPDATE_LISTENERS, {})[entry_id] = update_listener

    return True


async def async_reload_entry(
    hass: HomeAssistantType,
    config_entry: ConfigEntry,
) -> None:
    """Reload Moscow PGU entry"""
    _LOGGER.info(f"[{config_entry.data[CONF_USERNAME]}] Reloading configuration entry")
    await hass.config_entries.async_reload(config_entry.entry_id)


async def async_migrate_entry(hass: HomeAssistantType, config_entry: ConfigEntry) -> bool:
    from .config_flow import MoscowPGUConfigFlow

    current_version = config_entry.version
    username = config_entry.data[CONF_USERNAME]
    _LOGGER.debug(
        f"[{username}] "
        f"Migrating entry {config_entry.entry_id} "
        f"from version {current_version} to {MoscowPGUConfigFlow.VERSION}"
    )

    new_data = {**config_entry.data}
    new_options = {**config_entry.options}

    from ._schemas import DEVICE_INFO_SCHEMA

    device_info = {}
    for src in (new_data, new_options):
        device_info.update(src.get(CONF_DEVICE_INFO) or {})
        for key in DEVICE_INFO_SCHEMA.schema.keys():
            str_key = str(key)
            try:
                device_info[str_key] = src[str_key]
            except KeyError:
                pass
            else:
                _LOGGER.debug(f"[{username}] Removing leftover device info key {str_key}")
                del src[str_key]

        if not src.get(CONF_TOKEN, DEFAULT_TOKEN):
            _LOGGER.debug(f"[{username}] Removing empty token")
            del src[CONF_TOKEN]

        for key in (CONF_FILTER, CONF_NAME_FORMAT):
            if key in src:
                _LOGGER.debug(f"[{username}] Removed obsolete {key} from configuration")
                del src[key]

    if CONF_USERNAME in new_options:
        _LOGGER.debug(f"[{username}] Removing username from options")
        del src[CONF_USERNAME]

    config_entry.version = MoscowPGUConfigFlow.VERSION
    hass.config_entries.async_update_entry(
        config_entry,
        data=new_data,
        options=new_options,
    )

    _LOGGER.debug(f"[{username}] Configuration entry migrated!")

    return True


async def async_unload_entry(hass: HomeAssistantType, config_entry: ConfigEntry) -> bool:
    username = config_entry.data[CONF_USERNAME]
    _LOGGER.debug(f"[{username}] Unloading configuration entry")

    try:
        api_object = hass.data[DOMAIN].pop(config_entry.entry_id)
    except KeyError:
        _LOGGER.warning(f"[{username}] API object not detected. Did the entry load correctly?")
    else:
        await api_object.close_session()

    try:
        updaters: Dict[str, Callable] = hass.data[DATA_UPDATERS].pop(config_entry.entry_id)
    except KeyError:
        _LOGGER.warning(f"[{username}] Updaters holder not detected. Did the entry load correctly?")
    else:
        for cancel_callback in updaters.values():
            cancel_callback()

    try:
        cancel_listener = hass.data[DATA_UPDATE_LISTENERS].pop(config_entry.entry_id)
    except KeyError:
        _LOGGER.warning(f"[{username}] No update listener detected. Did the entry load correctly?")
    else:
        cancel_listener()

    await asyncio.gather(
        *(
            hass.config_entries.async_forward_entry_unload(config_entry, platform)
            for platform in SUPPORTED_PLATFORMS
        )
    )

    return True
