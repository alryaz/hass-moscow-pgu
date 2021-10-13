__all__ = (
    "DEVICE_INFO_SCHEMA",
    "FSSP_PROFILE_SCHEMA",
    "ENTITY_CONFIG_SCHEMA",
    "EXTRA_DATA_SCHEMA",
    "API_CONFIGURATION_SCHEMA",
    "CONFIG_ENTRY_SCHEMA",
    "CONFIG_SCHEMA",
)

from typing import Any, Final, Iterable, List, Mapping, Optional

import voluptuous as vol
from homeassistant.const import CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME, CONF_VERIFY_SSL
from homeassistant.helpers import config_validation as cv

from .api import (
    DEFAULT_APP_VERSION,
    DEFAULT_DEVICE_AGENT,
    DEFAULT_DEVICE_OS,
    DEFAULT_TOKEN,
    DEFAULT_USER_AGENT,
)
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
    CONF_SERIES,
    CONF_TOKEN,
    CONF_TRACK_FSSP_PROFILES,
    CONF_USER_AGENT,
    DOMAIN,
)
from .util import (
    generate_guid,
    load_platforms_base_classes,
)

#################################################################################
# Extra data configuration
#################################################################################

FSSP_PROFILE_SCHEMA: Final = vol.Schema(
    {
        vol.Required(CONF_FIRST_NAME): cv.string,
        vol.Required(CONF_LAST_NAME): cv.string,
        vol.Optional(CONF_MIDDLE_NAME): cv.string,
        vol.Required(CONF_BIRTH_DATE): cv.date,
    }
)
DRIVING_LICENSE_SCHEMA: Final = vol.Schema(
    {
        vol.Required(CONF_SERIES): cv.string,
        vol.Optional(CONF_ISSUE_DATE): cv.date,
    }
)
DRIVING_LICENSE_VALIDATOR: Final = vol.Any(
    vol.All(cv.string, lambda x: {CONF_SERIES: x}, DRIVING_LICENSE_SCHEMA),
    DRIVING_LICENSE_SCHEMA,
)

EXTRA_DATA_SCHEMA: Final = vol.Schema(
    {
        vol.Optional(
            CONF_DRIVING_LICENSES,
            default=lambda: [],
        ): vol.All(cv.ensure_list, [DRIVING_LICENSE_VALIDATOR]),
        vol.Optional(
            CONF_TRACK_FSSP_PROFILES,
            default=lambda: [],
        ): vol.All(cv.ensure_list, [FSSP_PROFILE_SCHEMA]),
    },
    extra=vol.ALLOW_EXTRA,
)

#################################################################################
# API configuration
#################################################################################

DEVICE_INFO_SCHEMA: Final = vol.Schema(
    {
        vol.Optional(CONF_APP_VERSION, default=DEFAULT_APP_VERSION): cv.string,
        vol.Optional(CONF_DEVICE_OS, default=DEFAULT_DEVICE_OS): cv.string,
        vol.Optional(CONF_DEVICE_AGENT, default=DEFAULT_DEVICE_AGENT): cv.string,
        vol.Optional(CONF_USER_AGENT, default=DEFAULT_USER_AGENT): cv.string,
        vol.Optional(CONF_GUID, default=generate_guid): cv.string,
    }
)

API_CONFIGURATION_SCHEMA: Final = vol.Schema(
    {
        vol.Optional(
            CONF_DEVICE_INFO,
            default=lambda: DEVICE_INFO_SCHEMA({}),
        ): DEVICE_INFO_SCHEMA,
        vol.Optional(
            CONF_TOKEN,
            default=DEFAULT_TOKEN,
        ): cv.string,
        vol.Optional(
            CONF_VERIFY_SSL,
            default=True,
        ): cv.boolean,
    },
    extra=vol.ALLOW_EXTRA,
)

#################################################################################
# Entity configuration
#################################################################################


_NAME_FORMATS_SCHEMA: Optional[vol.Schema] = None


def _lazy_name_formats_schema(value: Mapping[str, Any]):
    global _NAME_FORMATS_SCHEMA
    if _NAME_FORMATS_SCHEMA is not None:
        return _NAME_FORMATS_SCHEMA(value)

    platforms = load_platforms_base_classes()
    _NAME_FORMATS_SCHEMA = vol.Schema(
        {
            vol.Optional(cls.CONFIG_KEY, default=cls.DEFAULT_NAME_FORMAT): cv.string
            for base_cls in platforms.values()
            for cls in base_cls.__subclasses__()
        }
    )

    return _NAME_FORMATS_SCHEMA(value)


_SCAN_INTERVALS_SCHEMA: Optional[vol.Schema] = None


def _lazy_scan_intervals_schema(value: Any):
    global _SCAN_INTERVALS_SCHEMA
    if _SCAN_INTERVALS_SCHEMA is not None:
        return _SCAN_INTERVALS_SCHEMA(value)

    platforms = load_platforms_base_classes()
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

    _SCAN_INTERVALS_SCHEMA = vol.Any(single_schema, mapping_schema)

    return _SCAN_INTERVALS_SCHEMA(value)


_FILTER_SCHEMA: Optional[vol.Schema] = None


def _validate_only_asterisk(value: Iterable[str]) -> List[str]:
    items = set(value)
    if not items:
        return []


_BOOLEAN_EQUALITY_VALIDATOR: Final = vol.All(
    cv.boolean,
    vol.Any(
        vol.All(vol.Equal(True), lambda x: ["*"]),
        vol.All(vol.Equal(False), lambda x: []),
    ),
)

_SINGULAR_FILTER_VALIDATOR: Final = vol.Any(
    _BOOLEAN_EQUALITY_VALIDATOR,
    vol.All(
        cv.ensure_list,
        [cv.string],
        vol.Coerce(set),
        vol.Any(
            vol.All(vol.Equal(set("*")), lambda x: ["*"]),
            vol.All(vol.Equal(set()), lambda x: []),
        ),
    ),
    msg="Filter only accepts boolean values or asterisks",
)

_MULTIPLE_FILTER_VALIDATOR: Final = vol.Any(
    _BOOLEAN_EQUALITY_VALIDATOR,
    vol.All(
        cv.ensure_list,
        [cv.string],
        vol.Coerce(set),
        vol.Coerce(list),
    ),
    msg="Filter only accepts boolean values, asterisks or strings",
)


def _lazy_filter_schema(value: Any):
    global _FILTER_SCHEMA
    if _FILTER_SCHEMA is not None:
        return _FILTER_SCHEMA(value)

    platforms = load_platforms_base_classes()

    _FILTER_SCHEMA = vol.Schema(
        {
            vol.Optional(cls.CONFIG_KEY, default=lambda: ["*"]): (
                _SINGULAR_FILTER_VALIDATOR if cls.SINGULAR_FILTER else _MULTIPLE_FILTER_VALIDATOR
            )
            for base_cls in platforms.values()
            for cls in base_cls.__subclasses__()
        }
    )

    return _FILTER_SCHEMA(value)


ENTITY_CONFIG_SCHEMA: Final = vol.Schema(
    {
        vol.Optional(
            CONF_NAME_FORMAT,
            default=lambda: _lazy_name_formats_schema({}),
        ): _lazy_name_formats_schema,
        vol.Optional(
            CONF_SCAN_INTERVAL,
            default=lambda: _lazy_scan_intervals_schema({}),
        ): _lazy_scan_intervals_schema,
        vol.Optional(
            CONF_FILTER,
            default=lambda: _lazy_filter_schema({}),
        ): _lazy_filter_schema,
    },
    extra=vol.ALLOW_EXTRA,
)

#################################################################################
# Configuration entry validator
#################################################################################

CONFIG_ENTRY_SCHEMA: Final = vol.Schema(
    {
        **ENTITY_CONFIG_SCHEMA.schema,
        **API_CONFIGURATION_SCHEMA.schema,
        **EXTRA_DATA_SCHEMA.schema,
        vol.Required(CONF_USERNAME): cv.string,
        vol.Required(CONF_PASSWORD): cv.string,
    },
    extra=vol.PREVENT_EXTRA,
)

#################################################################################
# YAML configuration validator
#################################################################################

CONFIG_SCHEMA: Final = vol.Schema(
    {
        vol.Optional(DOMAIN): vol.Any(
            vol.Equal({}),
            vol.All(
                cv.ensure_list,
                [CONFIG_ENTRY_SCHEMA],
            ),
        )
    },
    extra=vol.ALLOW_EXTRA,
)
