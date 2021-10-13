from typing import Any, Final, Mapping, Optional, TYPE_CHECKING, Type

import voluptuous as vol
from homeassistant.const import CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME, CONF_VERIFY_SSL
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_APP_VERSION,
    CONF_BIRTH_DATE,
    CONF_DEVICE_AGENT,
    CONF_DEVICE_INFO,
    CONF_DEVICE_OS,
    CONF_DRIVING_LICENSES,
    CONF_FILTER,
    CONF_FIRST_NAME,
    CONF_GUID,
    CONF_ISSUE_DATE,
    CONF_LAST_NAME,
    CONF_MIDDLE_NAME,
    CONF_NAME_FORMAT,
    CONF_NUMBER,
    CONF_SERIES,
    CONF_TOKEN,
    CONF_TRACK_FSSP_PROFILES,
    CONF_USER_AGENT,
    DOMAIN,
    SUPPORTED_PLATFORMS,
)
from .api import (
    DEFAULT_APP_VERSION,
    DEFAULT_DEVICE_AGENT,
    DEFAULT_DEVICE_OS,
    DEFAULT_TOKEN,
    DEFAULT_USER_AGENT,
)
from .util import (
    generate_guid,
)

if TYPE_CHECKING:
    from ._base import MoscowPGUEntity

DEVICE_INFO_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_APP_VERSION, default=DEFAULT_APP_VERSION): cv.string,
        vol.Optional(CONF_DEVICE_OS, default=DEFAULT_DEVICE_OS): cv.string,
        vol.Optional(CONF_DEVICE_AGENT, default=DEFAULT_DEVICE_AGENT): cv.string,
        vol.Optional(CONF_USER_AGENT, default=DEFAULT_USER_AGENT): cv.string,
        vol.Optional(CONF_GUID, default=generate_guid): cv.string,
    }
)
FSSP_PROFILE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_FIRST_NAME): cv.string,
        vol.Required(CONF_LAST_NAME): cv.string,
        vol.Optional(CONF_MIDDLE_NAME): cv.string,
        vol.Required(CONF_BIRTH_DATE): cv.date,
    }
)
DRIVING_LICENSE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_SERIES): cv.string,
        vol.Optional(CONF_ISSUE_DATE): cv.date,
    }
)


def lazy_load_platforms_base_class() -> Mapping[str, Type["MoscowPGUEntity"]]:
    return {
        platform: __import__(
            f"custom_components.{DOMAIN}." + platform, globals(), locals(), ("BASE_CLASS",)
        ).BASE_CLASS
        for platform in SUPPORTED_PLATFORMS
    }


NAME_FORMATS_SCHEMA: Optional[vol.Schema] = None


def _lazy_name_formats_schema(value: Mapping[str, Any]):
    global NAME_FORMATS_SCHEMA
    if NAME_FORMATS_SCHEMA is not None:
        return NAME_FORMATS_SCHEMA(value)

    platforms = lazy_load_platforms_base_class()
    NAME_FORMATS_SCHEMA = vol.Schema(
        {
            vol.Optional(cls.CONFIG_KEY, default=cls.DEFAULT_NAME_FORMAT): cv.string
            for base_cls in platforms.values()
            for cls in base_cls.__subclasses__()
        }
    )

    return NAME_FORMATS_SCHEMA(value)


SCAN_INTERVALS_SCHEMA: Optional[vol.Schema] = None


def _lazy_scan_intervals_schema(value: Any):
    global SCAN_INTERVALS_SCHEMA
    if SCAN_INTERVALS_SCHEMA is not None:
        return SCAN_INTERVALS_SCHEMA(value)

    platforms = lazy_load_platforms_base_class()
    mapping_schema_dict = {
        vol.Optional(cls.CONFIG_KEY, default=cls.DEFAULT_SCAN_INTERVAL): vol.All(
            cv.positive_time_period, vol.Clamp(min=cls.MIN_SCAN_INTERVAL)
        )
        for base_cls in platforms.values()
        for cls in base_cls.__subclasses__()
    }
    mapping_schema = vol.Schema(mapping_schema_dict)

    single_schema = vol.All(
        cv.positive_time_period,
        lambda x: dict.fromkeys(mapping_schema_dict.keys(), x),
        mapping_schema,
    )

    SCAN_INTERVALS_SCHEMA = vol.Any(single_schema, mapping_schema)

    return SCAN_INTERVALS_SCHEMA(value)


FILTER_SCHEMA: Optional[vol.Schema] = None


def _lazy_filter_schema(value: Any):
    global FILTER_SCHEMA
    if FILTER_SCHEMA is not None:
        return FILTER_SCHEMA(value)

    platforms = lazy_load_platforms_base_class()

    singular_validator = vol.Any(
        vol.All(vol.Any(vol.Equal(["*"]), vol.Equal(True)), lambda x: ["*"]),
        vol.All(vol.Any(vol.Equal([]), vol.Equal(False)), lambda x: []),
    )

    multiple_validator = vol.Any(
        vol.All(vol.Equal(True), lambda x: ["*"]),
        vol.All(vol.Equal(False), lambda x: []),
        vol.All(cv.ensure_list, [cv.string]),
    )

    FILTER_SCHEMA = vol.Schema(
        {
            vol.Optional(cls.CONFIG_KEY, default=lambda: ["*"]): (
                singular_validator if cls.SINGULAR_FILTER else multiple_validator
            )
            for base_cls in platforms.values()
            for cls in base_cls.__subclasses__()
        }
    )

    return FILTER_SCHEMA(value)


OPTIONAL_ENTRY_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_DEVICE_INFO, default=lambda: DEVICE_INFO_SCHEMA({})): DEVICE_INFO_SCHEMA,
        vol.Optional(CONF_DRIVING_LICENSES, default=None): vol.All(
            cv.ensure_list,
            [vol.Optional(cv.string, lambda x: {CONF_NUMBER: x}), DRIVING_LICENSE_SCHEMA],
        ),
        vol.Optional(CONF_TRACK_FSSP_PROFILES, default=None): vol.All(
            cv.ensure_list, [FSSP_PROFILE_SCHEMA]
        ),
        vol.Optional(
            CONF_NAME_FORMAT, default=lambda: _lazy_name_formats_schema({})
        ): _lazy_name_formats_schema,
        vol.Optional(
            CONF_SCAN_INTERVAL, default=lambda: _lazy_scan_intervals_schema({})
        ): _lazy_scan_intervals_schema,
        vol.Optional(CONF_TOKEN, default=DEFAULT_TOKEN): cv.string,
        vol.Optional(CONF_VERIFY_SSL, default=True): cv.boolean,
    },
    extra=vol.ALLOW_EXTRA,
)
CONFIG_ENTRY_SCHEMA: Final = OPTIONAL_ENTRY_SCHEMA.extend(
    {
        vol.Required(CONF_USERNAME): cv.string,
        vol.Required(CONF_PASSWORD): cv.string,
    },
    extra=vol.PREVENT_EXTRA,
)
CONFIG_SCHEMA: Final = vol.Schema(
    {
        vol.Optional(DOMAIN): vol.Any(
            vol.Equal({}),
            vol.All(
                cv.ensure_list,
                [
                    vol.All(cv.deprecated(CONF_FILTER), CONFIG_ENTRY_SCHEMA),
                ],
            ),
        )
    },
    extra=vol.ALLOW_EXTRA,
)
