import asyncio
import json
import logging
import os
from typing import Dict, Final, Mapping, Optional, TYPE_CHECKING, Tuple, Type

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.typing import HomeAssistantType

from .api import API, MoscowPGUException, Profile, ResponseError
from .const import DATA_SESSION_LOCK, DOMAIN, SUPPORTED_PLATFORMS

if TYPE_CHECKING:
    from ._base import MoscowPGUEntity

_LOGGER: Final = logging.getLogger(__name__)


@callback
def async_get_lock(hass: HomeAssistantType):
    session_lock = hass.data.get(DATA_SESSION_LOCK)
    if session_lock is None:
        session_lock = asyncio.Lock()
        hass.data[DATA_SESSION_LOCK] = session_lock
    return session_lock


def read_sessions_file(hass: HomeAssistantType) -> Tuple[Dict[str, str], str]:
    filename = hass.config.path(os.path.join(".storage", DOMAIN + ".sessions"))
    contents = {}
    if os.path.isfile(filename):
        with open(filename, "rt") as f:
            try:
                contents = json.load(f)
            except json.JSONDecodeError:
                pass
    return contents, filename


async def async_load_session(hass: HomeAssistantType, username: str) -> Optional[str]:
    def load_session_from_json() -> Optional[str]:
        contents, _ = read_sessions_file(hass)
        return contents.get(username)

    async with async_get_lock(hass):
        return load_session_from_json()


async def async_save_session(hass: HomeAssistantType, username: str, session_id: str) -> None:
    def save_session_to_json() -> None:
        contents, filename = read_sessions_file(hass)
        contents[username] = session_id
        with open(filename, "w") as f:
            json.dump(contents, f)

    async with async_get_lock(hass):
        save_session_to_json()


async def async_authenticate_api_object(
    hass: HomeAssistantType,
    api: API,
    skip_session: bool = False,
) -> "Profile":
    username = api.username
    if api.session_id is None or skip_session:
        _LOGGER.debug('Authenticating with user "%s"', username)

        try:
            await api.authenticate()
        except ResponseError as exc:
            if exc.error_code == 502:
                raise

        _LOGGER.debug('Authentication successful for user "%s"', username)

        await async_save_session(hass, username, api.session_id)

        _LOGGER.debug('Saved session for user "%s"', username)

    else:
        _LOGGER.debug('Loaded session for user "%s"', username)

    try:
        return await api.get_profile()
    except MoscowPGUException as e:
        if (isinstance(e, ResponseError) and e.error_code == 502) or skip_session:
            raise
        return await async_authenticate_api_object(hass, api, True)


def generate_guid():
    from uuid import uuid4

    return uuid4().hex


@callback
def find_existing_entry(hass: HomeAssistantType, username: str) -> Optional[ConfigEntry]:
    existing_entries = hass.config_entries.async_entries(DOMAIN)
    for config_entry in existing_entries:
        if config_entry.data[CONF_USERNAME] == username:
            return config_entry


def load_platforms_base_classes() -> Mapping[str, Type["MoscowPGUEntity"]]:
    return {
        platform: __import__(
            f"custom_components.{DOMAIN}." + platform, globals(), locals(), ("BASE_CLASS",)
        ).BASE_CLASS
        for platform in SUPPORTED_PLATFORMS
    }
