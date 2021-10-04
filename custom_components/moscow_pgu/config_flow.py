from typing import Any, Dict, Final, List, Mapping, Optional

import voluptuous as vol
from homeassistant.config_entries import (
    CONN_CLASS_CLOUD_POLL,
    ConfigEntry,
    ConfigFlow,
    OptionsFlow,
    SOURCE_IMPORT,
)
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, CONF_VERIFY_SSL
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from custom_components.moscow_pgu import DEVICE_INFO_SCHEMA, DOMAIN
from custom_components.moscow_pgu.api import API, AuthenticationException, MoscowPGUException
from custom_components.moscow_pgu.util import (
    async_authenticate_api_object,
    async_save_session,
    extract_config,
)


class MoscowPGUConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION: Final[int] = 1
    CONNECTION_CLASS: Final[str] = CONN_CLASS_CLOUD_POLL

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._save_config: Optional[Dict[str, Any]] = None
        self._save_options: Optional[Dict[str, Any]] = None
        self._entity_config_keys: Optional[List[str]] = None

    def _check_entry_exists(self, username: str):
        current_entries = self._async_current_entries()

        for config_entry in current_entries:
            if config_entry.data.get(CONF_USERNAME) == username:
                return True

        return False

    async def async_step_user(self, user_input: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        errors = {}

        if user_input:
            username = user_input[CONF_USERNAME]
            if self._check_entry_exists(username):
                return self.async_abort(reason="already_exists")

            errors = await self._async_test_config(user_input)
            if not errors:
                return self._async_save_config(user_input)

        else:
            user_input = {}

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_USERNAME, default=user_input.get(CONF_USERNAME, "")
                    ): cv.string,
                    vol.Required(CONF_PASSWORD): cv.string,
                    **DEVICE_INFO_SCHEMA.schema,
                    vol.Optional(
                        CONF_VERIFY_SSL, default=user_input.get(CONF_VERIFY_SSL, True)
                    ): cv.boolean,
                }
            ),
            errors=errors,
        )

    async def async_step_import(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        if not user_input:
            return self.async_abort(reason="empty_config")

        username = user_input[CONF_USERNAME]

        if self._check_entry_exists(username):
            return self.async_abort(reason="already_exists")

        return self._async_save_config({CONF_USERNAME: username})

    async def _async_test_config(self, config: Mapping[str, Any]) -> Optional[Dict[str, str]]:
        api = API(**config)

        try:
            await async_authenticate_api_object(self.hass, api)
            await async_save_session(self.hass, api.username, api.session_id)

        except AuthenticationException:
            return {"base": "invalid_credentials"}

        except MoscowPGUException:
            return {"base": "api_error"}

        finally:
            await api.close_session()

    def _async_save_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        username = config[CONF_USERNAME]

        if self._check_entry_exists(username):
            return self.async_abort(reason="already_exists")

        return self.async_create_entry(title=username, data=config)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return MoscowPGUOptionsFlow(config_entry)


class MoscowPGUOptionsFlow(OptionsFlow):
    def __init__(self, config_entry: ConfigEntry):
        self._config_entry = config_entry
        self._filter_statuses: Optional[Mapping[str, bool]] = None

    async def async_step_init(self, user_input: Optional[ConfigType] = None) -> Dict[str, Any]:
        config_entry = self._config_entry
        if config_entry.source == SOURCE_IMPORT:
            return self.async_abort(reason="yaml_not_supported")

        if user_input:
            return self.async_create_entry(
                title="",
                data={
                    CONF_VERIFY_SSL: user_input[CONF_VERIFY_SSL],
                    **{str(key): user_input[str(key)] for key in DEVICE_INFO_SCHEMA.schema.keys()},
                },
            )

        config = extract_config(self.hass, self._config_entry)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    **{
                        vol.Optional(str(key), default=config[str(key)]): validator
                        for key, validator in DEVICE_INFO_SCHEMA.schema.items()
                    },
                    vol.Optional(CONF_VERIFY_SSL, default=config[CONF_VERIFY_SSL]): cv.boolean,
                }
            ),
            errors={},
        )
