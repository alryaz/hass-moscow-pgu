from typing import Optional, Dict, Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD
from homeassistant.helpers import config_validation as cv

from custom_components.moscow_pgu import DOMAIN, DEVICE_INFO_SCHEMA
from custom_components.moscow_pgu.api import AuthenticationException, MoscowPGUException, API
from custom_components.moscow_pgu.const import CONF_DEVICE_INFO
from custom_components.moscow_pgu.util import async_save_session, async_authenticate_api_object


@config_entries.HANDLERS.register(DOMAIN)
class MoscowPGUConfigFlow(config_entries.ConfigFlow):
    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._user_schema: Optional[vol.Schema] = None

        self._save_config: Optional[Dict[str, Any]] = None
        self._save_options: Optional[Dict[str, Any]] = None

    async def _check_entry_exists(self, username: str):
        current_entries = self._async_current_entries()

        for config_entry in current_entries:
            if config_entry.data.get(CONF_USERNAME) == username:
                return True

        return False

    async def async_step_user(self, user_input: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if self._user_schema is None:
            self._user_schema = vol.Schema(
                {
                    vol.Required(CONF_USERNAME): cv.string,
                    vol.Required(CONF_PASSWORD): cv.string,
                    vol.Optional(CONF_DEVICE_INFO, default=False): cv.boolean,
                }
            )

        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=self._user_schema)

        username = user_input[CONF_USERNAME]
        if await self._check_entry_exists(username):
            return self.async_abort(reason="already_exists")

        device_info_show = user_input.pop(CONF_DEVICE_INFO)
        self._save_config = {**user_input}

        if device_info_show:
            return await self.async_step_device_info()

        errors = await self._async_test_config()
        if errors:
            return self.async_show_form(
                step_id="user", data_schema=self._user_schema, errors=errors
            )

        return await self._async_save_config()

    async def async_step_device_info(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        if user_input is None:
            return self.async_show_form(step_id="device_info", data_schema=DEVICE_INFO_SCHEMA)

        self._save_config[CONF_DEVICE_INFO] = user_input

        errors = await self._async_test_config()
        if errors:
            return self.async_show_form(
                step_id="device_info", data_schema=DEVICE_INFO_SCHEMA, errors=errors
            )

        return await self._async_save_config()

    async def async_step_import(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        if user_input is None:
            return self.async_abort(reason="empty_config")

        self._save_config = user_input

        return await self._async_save_config()

    def _create_api_object(self) -> API:
        arguments = {**self._save_config}

        if CONF_DEVICE_INFO in arguments:
            device_info = arguments.pop(CONF_DEVICE_INFO)
            arguments.update(device_info)

        return API(**arguments)

    async def _async_test_config(self) -> Optional[Dict[str, str]]:
        try:
            async with self._create_api_object() as api:
                await async_authenticate_api_object(self.hass, api)

        except AuthenticationException:
            return {"base": "invalid_credentials"}

        except MoscowPGUException:
            return {"base": "api_error"}

        else:
            await async_save_session(self.hass, api.username, api.session_id)

    async def _async_save_config(self):
        username = self._save_config[CONF_USERNAME]

        if await self._check_entry_exists(username):
            return self.async_abort(reason="already_exists")

        return self.async_create_entry(title=username, data=self._save_config)
