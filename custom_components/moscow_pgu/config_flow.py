from typing import Any, Callable, Dict, Final, List, Mapping, MutableMapping, Optional

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

from ._schemas import CONFIG_ENTRY_SCHEMA, DEVICE_INFO_SCHEMA
from .api import API, AuthenticationException, MoscowPGUException
from .const import (
    CONF_APP_VERSION,
    CONF_BIRTH_DATE,
    CONF_DEVICE_AGENT,
    CONF_DEVICE_INFO,
    CONF_DEVICE_OS,
    CONF_DRIVING_LICENSES,
    CONF_FIRST_NAME,
    CONF_GUID,
    CONF_ISSUE_DATE,
    CONF_LAST_NAME,
    CONF_MIDDLE_NAME,
    CONF_SERIES,
    CONF_TRACK_FSSP_PROFILES,
    CONF_USER_AGENT,
    DOMAIN,
)
from .util import async_authenticate_api_object, async_save_session


class MoscowPGUConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION: Final[int] = 4
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
            try:
                username = API.prepare_username(user_input[CONF_USERNAME])
            except (TypeError, ValueError, LookupError):
                errors[CONF_USERNAME] = "invalid_credentials"
            else:
                if self._check_entry_exists(username):
                    return self.async_abort(reason="already_exists")
                user_input[CONF_USERNAME] = username

                api = API(
                    username=username,
                    password=user_input[CONF_PASSWORD],
                    app_version=user_input[CONF_APP_VERSION],
                    device_os=user_input[CONF_DEVICE_OS],
                    device_agent=user_input[CONF_DEVICE_AGENT],
                    user_agent=user_input[CONF_USER_AGENT],
                    guid=user_input[CONF_GUID],
                )

                try:
                    await async_authenticate_api_object(self.hass, api)
                    await async_save_session(self.hass, api.username, api.session_id)

                except AuthenticationException:
                    errors["base"] = "invalid_credentials"

                except MoscowPGUException:
                    errors["base"] = "api_error"

                finally:
                    await api.close_session()

                if not errors:
                    user_input[CONF_DEVICE_INFO] = {
                        key: user_input.pop(key)
                        for key in map(str, DEVICE_INFO_SCHEMA.schema.keys())
                    }
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

    def _async_save_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        username = config[CONF_USERNAME]

        if self._check_entry_exists(username):
            return self.async_abort(reason="already_exists")

        if "@" not in username:
            username = (
                f"+{username[0]} ({username[1:4]}) {username[4:7]}-{username[7:9]}-{username[9:11]}"
            )

        return self.async_create_entry(title=username, data=config)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return MoscowPGUOptionsFlow(config_entry)


class MoscowPGUOptionsFlow(OptionsFlow):
    def __init__(self, config_entry: ConfigEntry):
        self._config_entry = config_entry
        self._filter_statuses: Optional[Mapping[str, bool]] = None
        self._base_config: Mapping[str, Any] = CONFIG_ENTRY_SCHEMA(
            {**config_entry.data, **config_entry.options}
        )

    @staticmethod
    def _handle_vol_exc(exc: vol.Invalid, errors: MutableMapping[str, str]) -> None:
        if isinstance(exc, vol.MultipleInvalid):
            for sub_exc in exc.errors:
                errors[sub_exc.path[0]] = "invalid_input"
        else:
            errors[exc.path[0]] = "invalid_input"

    def _handle_list_input(
        self,
        user_input: ConfigType,
        save_data: ConfigType,
        errors: MutableMapping[str, str],
        key: str,
        new_data: Dict[str, Any],
        validator: Callable[[Dict[str, Any]], Any],
    ) -> None:
        all_objects = list(self._base_config[key])

        remove_profiles = user_input.get("remove_" + key)
        if remove_profiles:
            remove_profile_indices = tuple(map(int, remove_profiles))
            all_objects = [x for i, x in enumerate(all_objects) if i not in remove_profile_indices]

        if new_data is not None:
            try:
                validator(new_data)
            except vol.Invalid as exc:
                self._handle_vol_exc(exc, errors)
            else:
                all_objects.append(new_data)

        if all_objects:
            save_data[key] = all_objects
        else:
            save_data.pop(key, None)

    def _merge_fssp_profiles(
        self, schema_dict: MutableMapping[vol.Marker, Any], user_input: Mapping[str, Any]
    ) -> None:
        for key in (CONF_LAST_NAME, CONF_FIRST_NAME, CONF_MIDDLE_NAME, CONF_BIRTH_DATE):
            schema_dict[vol.Optional(key, default=user_input.get(key) or "")] = cv.string

        fssp_profiles = self._base_config[CONF_TRACK_FSSP_PROFILES]
        if fssp_profiles:
            schema_dict[vol.Optional("remove_" + CONF_TRACK_FSSP_PROFILES)] = cv.multi_select(
                {
                    str(i): " ".join(
                        filter(
                            bool,
                            (
                                fssp_profile[CONF_LAST_NAME],
                                fssp_profile[CONF_FIRST_NAME],
                                fssp_profile.get(CONF_MIDDLE_NAME),
                                "(" + fssp_profile[CONF_BIRTH_DATE].isoformat() + ")",
                            ),
                        )
                    )
                    for i, fssp_profile in enumerate(fssp_profiles)
                }
            )

    def _handle_fssp_profiles(
        self, user_input: ConfigType, save_data: ConfigType, errors: MutableMapping[str, str]
    ) -> None:
        fssp_profile = None
        first_name = user_input[CONF_FIRST_NAME].strip()
        last_name = user_input[CONF_LAST_NAME].strip()
        birth_date = user_input[CONF_BIRTH_DATE].strip()

        if first_name and last_name and birth_date:
            fssp_profile = {
                CONF_FIRST_NAME: first_name,
                CONF_LAST_NAME: last_name,
                CONF_BIRTH_DATE: birth_date,
            }
            middle_name = (user_input.get(CONF_MIDDLE_NAME) or "").strip()
            if middle_name:
                fssp_profile[CONF_MIDDLE_NAME] = middle_name

        from ._schemas import FSSP_PROFILE_SCHEMA

        self._handle_list_input(
            user_input,
            save_data,
            errors,
            CONF_TRACK_FSSP_PROFILES,
            fssp_profile,
            FSSP_PROFILE_SCHEMA,
        )

    def _merge_driving_licenses(
        self, schema_dict: MutableMapping[vol.Marker, Any], user_input: Mapping[str, Any]
    ) -> None:
        schema_dict[
            vol.Optional(CONF_SERIES, default=user_input.get(CONF_SERIES) or "")
        ] = cv.string
        schema_dict[
            vol.Optional(CONF_ISSUE_DATE, default=user_input.get(CONF_ISSUE_DATE) or "")
        ] = cv.string

        driving_licenses = self._base_config[CONF_DRIVING_LICENSES]
        if driving_licenses:
            schema_dict[vol.Optional("remove_" + CONF_DRIVING_LICENSES)] = cv.multi_select(
                {
                    str(i): driving_license[CONF_SERIES]
                    + (
                        " - " + driving_license[CONF_ISSUE_DATE]
                        if driving_license.get(CONF_ISSUE_DATE)
                        else ""
                    )
                    for i, driving_license in enumerate(driving_licenses)
                }
            )

    def _handle_driving_licenses(
        self, user_input: ConfigType, save_data: ConfigType, errors: MutableMapping[str, str]
    ) -> None:

        driving_license = None
        series = user_input[CONF_SERIES].strip()

        if series:
            driving_license = {CONF_SERIES: series}
            issue_date = (user_input.get(CONF_ISSUE_DATE) or "").strip()
            if issue_date:
                driving_license[CONF_ISSUE_DATE] = issue_date

        from ._schemas import DRIVING_LICENSE_SCHEMA

        self._handle_list_input(
            user_input,
            save_data,
            errors,
            CONF_DRIVING_LICENSES,
            driving_license,
            DRIVING_LICENSE_SCHEMA,
        )

    def _merge_connection(
        self, schema_dict: MutableMapping[vol.Marker, Any], user_input: Mapping[str, Any]
    ) -> None:
        schema_dict[vol.Optional(CONF_PASSWORD, default="")] = cv.string

        device_info_config = self._base_config[CONF_DEVICE_INFO]
        for key, validator in DEVICE_INFO_SCHEMA.schema.items():
            str_key = str(key)
            value = user_input[str_key] if user_input else device_info_config[str_key]
            schema_dict[vol.Optional(str_key, default=value)] = validator

        schema_dict[
            vol.Optional(CONF_VERIFY_SSL, default=self._base_config[CONF_VERIFY_SSL])
        ] = cv.boolean

    def _handle_connection(
        self, user_input: ConfigType, save_data: ConfigType, errors: MutableMapping[str, str]
    ) -> None:
        save_data[CONF_VERIFY_SSL] = user_input[CONF_VERIFY_SSL]

        from ._schemas import DEVICE_INFO_SCHEMA

        device_info = {str(key): user_input[str(key)] for key in DEVICE_INFO_SCHEMA.schema.keys()}

        password = user_input.get(CONF_PASSWORD)
        if password:
            password = password.strip()
            if password:
                save_data[CONF_PASSWORD] = password.strip()

        try:
            device_info = DEVICE_INFO_SCHEMA(device_info)
        except vol.Invalid as exc:
            self._handle_vol_exc(exc, errors)
        else:
            save_data[CONF_DEVICE_INFO] = device_info

    async def async_step_init(self, user_input: Optional[ConfigType] = None) -> Dict[str, Any]:
        config_entry = self._config_entry
        if config_entry.source == SOURCE_IMPORT:
            return self.async_abort(reason="yaml_not_supported")

        errors = {}

        if user_input:
            save_data = {**self._config_entry.options}

            self._handle_fssp_profiles(user_input, save_data, errors)
            self._handle_driving_licenses(user_input, save_data, errors)
            self._handle_connection(user_input, save_data, errors)

            if not errors:
                return self.async_create_entry(
                    title="",
                    data=save_data,
                )
        else:
            user_input = {}

        schema_dict = {}
        self._merge_fssp_profiles(schema_dict, user_input)
        self._merge_driving_licenses(schema_dict, user_input)
        self._merge_connection(schema_dict, user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(schema_dict),
            errors=errors,
        )
