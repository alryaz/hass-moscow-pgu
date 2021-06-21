"""Predefined values for Moscow PGU integration"""
from typing import Final

DEVICE_CLASS_PGU_INDICATIONS: Final = "pgu_indications"

UNIT_CURRENCY_RUSSIAN_ROUBLES: Final = "RUB"

ATTR_ADDRESS: Final = "address"
ATTR_AMOUNT: Final = "amount"
ATTR_AMOUNT_WITH_INSURANCE: Final = "amount_with_insurance"
ATTR_ARTICLE_TITLE: Final = "article_title"
ATTR_BAILIFF_NAME: Final = "bailiff_name"
ATTR_BAILIFF_PHONE: Final = "bailiff_phone"
ATTR_BALANCE_MESSAGE: Final = "balance_message"
ATTR_BIRTH_DATE: Final = "birth_date"
ATTR_CERTIFICATE_SERIES: Final = "certificate_series"
ATTR_CHARGES_AMOUNT: Final = "charges_amount"
ATTR_CHECKUP_DATE: Final = "checkup_date"
ATTR_CLASS: Final = "class"
ATTR_CODES: Final = "codes"
ATTR_COMMITTED_AT: Final = "committed_at"
ATTR_COUNTER_ID: Final = "counter_id"
ATTR_COUNTER_IDS: Final = "counter_ids"
ATTR_CREATE_DATETIME: Final = "create_datetime"
ATTR_DEBTS: Final = "debts"
ATTR_DEBT_AMOUNT: Final = "debt_amount"
ATTR_DECIMAL_PART_LENGTH: Final = "decimal_part_length"
ATTR_DESCRIPTION: Final = "desciption"
ATTR_DEVICE: Final = "device"
ATTR_DISCOUNT_DATE: Final = "discount_date"
ATTR_DOCUMENT_SERIES: Final = "document_series"
ATTR_DOCUMENT_TYPE: Final = "document_type"
ATTR_DRIVING_LICENSE_ISSUE_DATE: Final = "driving_license_issue_date"
ATTR_DRIVING_LICENSE_NUMBER: Final = "driving_license_number"
ATTR_DRY_RUN: Final = "dry_run"
ATTR_EMAIL: Final = "email"
ATTR_EMAIL_CONFIRMED: Final = "email_confirmed"
ATTR_ENTERPRENEUR_ID: Final = "enterpreneur_id"
ATTR_ENTRANCE_NUMBER: Final = "entrance_number"
ATTR_EPDS: Final = "epds"
ATTR_EPD_ACCOUNT: Final = "epd_account"
ATTR_FIRST_NAME: Final = "first_name"
ATTR_FLAT_ID: Final = "flat_id"
ATTR_FLAT_NUMBER: Final = "flat_number"
ATTR_FLOOR: Final = "floor"
ATTR_FORCE: Final = "force"
ATTR_INDICATION: Final = "indication"
ATTR_INDICATIONS: Final = "indications"
ATTR_INITIATOR: Final = "initiator"
ATTR_INSURANCE_AMOUNT: Final = "insurance_amount"
ATTR_INTERCOM: Final = "intercom"
ATTR_ISSUE_DATE: Final = "issue_date"
ATTR_IS_AT_SCHOOL: Final = "is_at_school"
ATTR_IS_EVACUATED: Final = "is_evacuated"
ATTR_KLADR_MAIN_NAME: Final = "kladr_main_name"
ATTR_KLADR_STREET_NAME: Final = "kladr_street_name"
ATTR_LAST_INDICATION_PERIOD: Final = "last_indication_period"
ATTR_LAST_INDICATION_VALUE: Final = "last_indication_value"
ATTR_LAST_NAME: Final = "last_name"
ATTR_LAST_UPDATE_DATE: Final = "last_update_date"
ATTR_LICENSE_PLATE: Final = "license_plate"
ATTR_LOCATION: Final = "location"
ATTR_MIDDLE_NAME: Final = "middle_name"
ATTR_NUMBER: Final = "number"
ATTR_OFFENSES: Final = "offenses"
ATTR_ORIGINAL_INDICATIONS: Final = "original_indications"
ATTR_PAYMENTS_AMOUNT: Final = "payments_amount"
ATTR_PAYMENT_AMOUNT: Final = "payment_amount"
ATTR_PAYMENT_DATE: Final = "payment_date"
ATTR_PAYMENT_STATUS: Final = "payment_status"
ATTR_PAY_LIMIT: Final = "pay_limit"
ATTR_PENALTY: Final = "penalty"
ATTR_PENALTY_AMOUNT: Final = "penalty_amount"
ATTR_PERIOD: Final = "period"
ATTR_PERIODS: Final = "periods"
ATTR_PHONE_NUMBER: Final = "phone_number"
ATTR_PHOTO_URL: Final = "photo_url"
ATTR_POLICE_UNIT_CODE: Final = "police_unit_code"
ATTR_POLICE_UNIT_NAME: Final = "police_unit_name"
ATTR_REASON: Final = "reason"
ATTR_RETURNS_AMOUNT: Final = "returns_amount"
ATTR_RISE_DATE: Final = "rise_date"
ATTR_SCHOOL: Final = "school"
ATTR_SERVICE_TYPE: Final = "service_type"
ATTR_SETTLEMENT_DATE: Final = "settlement_date"
ATTR_STATUS: Final = "status"
ATTR_STATUS_RNIP: Final = "status_rnip"
ATTR_STATUS_TEXT: Final = "status_text"
ATTR_SUBMIT_AVAILABLE: Final = "submit_available"
ATTR_SUBMIT_BEGIN_DATE: Final = "submit_begin_date"
ATTR_SUBMIT_END_DATE: Final = "submit_end_date"
ATTR_SUCCESS: Final = "success"
ATTR_TARIFF: Final = "tariff"
ATTR_TOTAL: Final = "total"
ATTR_TRANSFER_AMOUNT: Final = "transfer_amount"
ATTR_TYPE: Final = "type"
ATTR_TYPES: Final = "types"
ATTR_UNLOAD_DATE: Final = "unload_date"
ATTR_UNLOAD_STATUS: Final = "unload_status"
ATTR_UNPAID_AMOUNT: Final = "unpaid_amount"
ATTR_UNPAID_BAILIFF: Final = "unpaid_bailiff"
ATTR_UNPAID_ENTERPRENEUR: Final = "unpaid_enterpreneur"
ATTR_WHOLE_PART_LENGTH: Final = "whole_part_length"
ATTR_ZONES: Final = "zones"
ATTR_ZONE_NAME: Final = "zone_name"

TYPE_ELECTRIC: Final = "electric"
TYPE_WATER: Final = "water"

DOMAIN: Final = "moscow_pgu"

DATA_CONFIG: Final = DOMAIN + "_config"
DATA_ENTITIES: Final = DOMAIN + "_entities"
DATA_SESSION_LOCK: Final = DOMAIN + "_session_lock"
DATA_UPDATERS: Final = DOMAIN + "_updaters"

CONF_APP_VERSION: Final = "app_version"
CONF_BIRTH_DATE: Final = "birth_date"
CONF_DEVICE_AGENT: Final = "device_agent"
CONF_DEVICE_INFO: Final = "device_info"
CONF_DEVICE_OS: Final = "device_os"
CONF_DRIVING_LICENSES: Final = "driving_licenses"
CONF_FIRST_NAME: Final = "first_name"
CONF_GUID: Final = "guid"
CONF_ISSUE_DATE: Final = "issue_date"
CONF_LAST_NAME: Final = "last_name"
CONF_MIDDLE_NAME: Final = "middle_name"
CONF_NAME_FORMAT: Final = "name_format"
CONF_NUMBER: Final = "number"
CONF_SERIES: Final = "series"
CONF_TOKEN: Final = "token"
CONF_TRACK_FSSP_PROFILES: Final = "track_fssp_profiles"
CONF_USER_AGENT: Final = "user_agent"

SUPPORTED_PLATFORMS: Final = ("sensor",)  # "binary_sensor")  # This will be changed later

EVENT_FORMAT_INDICATIONS_PUSH: Final = DOMAIN + "_%s_indications_push"
