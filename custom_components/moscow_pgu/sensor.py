__all__ = (
    "BASE_CLASS",
    "async_setup_entry",
    "MoscowPGUWaterCounterSensor",
    "MoscowPGUFSSPDebtsSensor",
    "MoscowPGUChildSensor",
    "MoscowPGUVehicleSensor",
    "MoscowPGUDiarySensor",
    "MoscowPGUFlatSensor",
    "MoscowPGUElectricCounterSensor",
    "MoscowPGUProfileSensor",
    "MoscowPGUDrivingLicenseSensor",
    "MoscowPGUSensor",
)

import asyncio
import hashlib
import itertools
import logging
from abc import ABC, abstractmethod
from datetime import date, time, timedelta
from typing import (
    Any,
    ClassVar,
    Collection,
    Dict,
    Generic,
    Iterable,
    List,
    Mapping,
    Optional,
    Sequence,
    SupportsFloat,
    Tuple,
    TypeVar,
    Union,
)

import attr
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_CODE, ATTR_ID, ATTR_NAME, ATTR_STATE, STATE_OK, STATE_UNKNOWN
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType, HomeAssistantType, StateType

from ._base import (
    MoscowPGUIterAddOrUpdateEntity,
    dt_to_str,
    make_platform_setup,
)
from ._base_submit import MoscowPGUSubmittableEntity
from .api import (
    API,
    Child,
    DiaryWidget,
    DrivingLicense,
    EPD,
    ElectricAccount,
    ElectricBalance,
    ElectricCounterInfo,
    ElectricIndicationsStatus,
    ElectricPayment,
    FSSPDebt,
    Flat,
    MoscowPGUException,
    Offense,
    Profile,
    ResponseError,
    SubjectAttestationMark,
    Vehicle,
    WaterCounter,
)
from .const import *

_LOGGER = logging.getLogger(__name__)

_T = TypeVar("_T")


class MoscowPGUSensor(MoscowPGUIterAddOrUpdateEntity[_T], ABC, Generic[_T]):
    """Base for Moscow PGU sensors"""


class MoscowPGUFSSPDebtsSensor(MoscowPGUSensor[Profile]):
    """FSSP debts"""

    #################################################################################
    # Component-specific code
    #################################################################################

    CONFIG_KEY: ClassVar[str] = "fssp_debts"
    DEFAULT_NAME_FORMAT: ClassVar[str] = "FSSP Debts - {identifier}"
    DEFAULT_SCAN_INTERVAL: ClassVar[timedelta] = timedelta(days=1)
    SINGULAR_FILTER: ClassVar[bool] = True

    NAME_RU: ClassVar[str] = "Взыскания ФССП"
    NAME_EN: ClassVar[str] = "FSSP Debts"

    ITER_COMPARE_ATTRIBUTES = ("first_name", "last_name", "middle_name", "birth_date")
    ITER_IGNORE_ATTRIBUTES = ("middle_name",)
    ITER_CHECK_NONE = False
    ITER_REFRESH_AFTER = True

    def __init__(self, *args, fssp_debts: Iterable[FSSPDebt] = (), **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fssp_debts = list(fssp_debts)

    @classmethod
    async def async_get_objects_for_update(
        cls,
        hass: HomeAssistantType,
        config_entry: ConfigEntry,
        config: ConfigType,
        api: "API",
        filter_values: Collection[str] = (),
        is_blacklist: bool = True,
    ) -> List[Profile]:
        profiles = [await api.get_profile()]
        additional_config = config.get(CONF_TRACK_FSSP_PROFILES, [])

        for additional_profile in additional_config:
            if not additional_profile:
                continue
            birth_date = additional_profile.get(CONF_ISSUE_DATE)

            if not (birth_date is None or isinstance(birth_date, date)):
                birth_date = cv.date(birth_date)

            for profile in profiles:
                if (
                    profile.first_name == additional_profile[CONF_FIRST_NAME]
                    and profile.last_name == additional_profile[CONF_LAST_NAME]
                    and profile.middle_name == additional_profile.get(CONF_MIDDLE_NAME)
                    and profile.birth_date == birth_date
                ):
                    _LOGGER.warning(
                        'FSSP debts profile ("%s (%s)") duplication detected',
                        profile.full_name,
                        profile.birth_date,
                    )
                    continue

            profiles.append(
                Profile(
                    api=api,
                    first_name=additional_profile[CONF_FIRST_NAME],
                    last_name=additional_profile[CONF_LAST_NAME],
                    middle_name=additional_profile.get(CONF_MIDDLE_NAME),
                    birth_date=additional_profile[CONF_BIRTH_DATE],
                )
            )

        return profiles

    @property
    def name_format_values(self) -> Mapping[str, Any]:
        source = self.source
        return {
            **attr.asdict(source, recurse=False),
            "identifier": source.full_name,
        }

    @property
    def sensor_related_attributes(self) -> Optional[Dict[str, Any]]:
        source = self.source
        return {
            ATTR_FIRST_NAME: source.first_name,
            ATTR_LAST_NAME: source.last_name,
            ATTR_MIDDLE_NAME: source.middle_name,
            ATTR_BIRTH_DATE: dt_to_str(source.birth_date),
            ATTR_DEBTS: [
                {
                    ATTR_ID: fssp_debt.id,
                    ATTR_ENTERPRENEUR_ID: fssp_debt.enterpreneur_id,
                    ATTR_DESCRIPTION: fssp_debt.description,
                    ATTR_RISE_DATE: dt_to_str(fssp_debt.rise_date),
                    ATTR_TOTAL: fssp_debt.total_amount,
                    ATTR_UNPAID_ENTERPRENEUR: fssp_debt.unpaid_enterpreneur_amount,
                    ATTR_UNPAID_BAILIFF: fssp_debt.unpaid_bailiff_amount,
                    ATTR_UNLOAD_DATE: dt_to_str(fssp_debt.unload_date),
                    ATTR_UNLOAD_STATUS: fssp_debt.unload_status,
                    ATTR_KLADR_MAIN_NAME: fssp_debt.kladr_main_name,
                    ATTR_KLADR_STREET_NAME: fssp_debt.kladr_street_name,
                    ATTR_BAILIFF_NAME: fssp_debt.bailiff_name,
                    ATTR_BAILIFF_PHONE: fssp_debt.bailiff_phone,
                }
                for fssp_debt in self.fssp_debts
            ],
        }

    #################################################################################
    # HA-specific code
    #################################################################################

    async def async_update(self) -> None:
        fssp_debts = await self.source.get_fssp_detailed()

        self.fssp_debts.clear()
        self.fssp_debts.extend(fssp_debts)

    @property
    def icon(self) -> Optional[str]:
        return "mdi:gavel"

    @property
    def unit_of_measurement(self) -> Optional[str]:
        return UNIT_CURRENCY_RUSSIAN_ROUBLES

    @property
    def state(self) -> float:
        return -sum(map(lambda x: x.unpaid_amount or 0, self.fssp_debts))

    @property
    def unique_id(self) -> Optional[str]:
        hashkey = hashlib.md5(
            (self.source.full_name + self.source.birth_date.strftime("%Y-%m-%d")).encode("utf-8")
        ).hexdigest()

        return f"sensor_fssp_debt_{hashkey}"


class MoscowPGUProfileSensor(MoscowPGUSensor[Profile]):
    """Profile sensor"""

    #################################################################################
    # Component-specific code
    #################################################################################

    CONFIG_KEY: ClassVar[str] = "profile"
    DEFAULT_NAME_FORMAT: ClassVar[str] = "Profile - {identifier}"
    DEFAULT_SCAN_INTERVAL: ClassVar[timedelta] = timedelta(days=1)
    SINGULAR_FILTER: ClassVar[bool] = True

    NAME_RU: ClassVar[str] = "Профиль"
    NAME_EN: ClassVar[str] = "Profile"

    ITER_COMPARE_ATTRIBUTES = ("phone_number", "email")
    ITER_CHECK_NONE = True
    ITER_REFRESH_AFTER = False
    ITER_CHECKER = any

    def __init__(self, *args, source: Profile, **kwargs):
        assert source.phone_number, "init profile yields an empty phone number"
        super().__init__(*args, source=source, **kwargs)

    @classmethod
    async def async_get_objects_for_update(
        cls,
        hass: HomeAssistantType,
        config_entry: ConfigEntry,
        config: ConfigType,
        api: "API",
        filter_values: Collection[str] = (),
        is_blacklist: bool = True,
    ) -> List[Profile]:
        return [await api.get_profile()]

    @property
    def name_format_values(self) -> Mapping[str, Any]:
        source = self.source
        return {
            **attr.asdict(source, recurse=False),
            "identifier": source.phone_number,
        }

    @property
    def sensor_related_attributes(self) -> Optional[Dict[str, Any]]:
        profile = self.source

        driving_license_number = None
        driving_license_issue_date = None

        if profile.driving_license:
            driving_license_number = profile.driving_license.series
            driving_license_issue_date = profile.driving_license.issue_date

        return {
            ATTR_FIRST_NAME: profile.first_name,
            ATTR_LAST_NAME: profile.last_name,
            ATTR_MIDDLE_NAME: profile.middle_name,
            ATTR_BIRTH_DATE: dt_to_str(profile.birth_date),
            ATTR_PHONE_NUMBER: profile.phone_number,
            ATTR_EMAIL: profile.email,
            ATTR_EMAIL_CONFIRMED: profile.email_confirmed,
            ATTR_DRIVING_LICENSE_NUMBER: driving_license_number,
            ATTR_DRIVING_LICENSE_ISSUE_DATE: dt_to_str(driving_license_issue_date),
        }

    #################################################################################
    # HA-specific code
    #################################################################################

    async def async_update(self) -> None:
        self.source = await self.source.api.get_profile()

    @property
    def icon(self) -> Optional[str]:
        return "mdi:account"

    @property
    def state(self) -> StateType:
        return STATE_OK

    @property
    def unique_id(self) -> Optional[str]:
        return f"sensor_profile_{self.source.phone_number}"


class MoscowPGUOffensesSensor(MoscowPGUSensor[_T], ABC, Generic[_T]):
    SHOW_OFFENSE_DOCUMENT: ClassVar[bool] = True

    def __init__(self, *args, offenses: Iterable[Offense] = (), **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.offenses = list(offenses)
        self._service_is_offline = False

    @abstractmethod
    async def async_retrieve_offenses(self) -> Iterable[Offense]:
        raise NotImplementedError

    async def async_update(self) -> None:
        try:
            offenses = await self.async_retrieve_offenses()
        except ResponseError as e:
            if e.error_code in (2301, 1):
                _LOGGER.warning(
                    f"Driving license {self.source} couldn't be updated "
                    f"because the offenses service appears to be offline."
                )
                self._service_is_offline = True
                return
            raise

        self._service_is_offline = False
        self.offenses = offenses

    @staticmethod
    def offense_to_attributes(
        offense: Optional[Offense] = None, with_document: bool = True, prefix: Optional[str] = None
    ):
        """Convert `moscow_pgu_api.Offense` object to a dictionary of entity attributes"""
        if offense is None:
            attributes = dict.fromkeys(
                (
                    ATTR_ID,
                    ATTR_ISSUE_DATE,
                    ATTR_COMMITTED_AT,
                    ATTR_ARTICLE_TITLE,
                    ATTR_LOCATION,
                    ATTR_PENALTY,
                    ATTR_STATUS,
                    ATTR_STATUS_RNIP,
                    ATTR_DISCOUNT_DATE,
                    ATTR_POLICE_UNIT_CODE,
                    ATTR_POLICE_UNIT_NAME,
                    ATTR_PHOTO_URL,
                    ATTR_UNPAID_AMOUNT,
                    ATTR_STATUS_TEXT,
                ),
                None,
            )

        else:
            attributes = {
                ATTR_ID: offense.id,
                ATTR_ISSUE_DATE: dt_to_str(offense.date_issued),
                ATTR_COMMITTED_AT: dt_to_str(offense.datetime_committed),
                ATTR_ARTICLE_TITLE: offense.article_title,
                ATTR_LOCATION: offense.location,
                ATTR_PENALTY: offense.penalty,
                ATTR_STATUS: offense.status,
                ATTR_STATUS_RNIP: offense.status_rnip,
                ATTR_DISCOUNT_DATE: dt_to_str(offense.discount_date),
                ATTR_POLICE_UNIT_CODE: offense.police_unit_code,
                ATTR_POLICE_UNIT_NAME: offense.police_unit_name,
                ATTR_PHOTO_URL: offense.photo_url,
                ATTR_UNPAID_AMOUNT: offense.unpaid_amount,
                ATTR_STATUS_TEXT: offense.status_text,
            }

        if with_document:
            if offense is None:
                attributes[ATTR_DOCUMENT_TYPE] = None
                attributes[ATTR_DOCUMENT_SERIES] = None
            else:
                attributes[ATTR_DOCUMENT_TYPE] = offense.document_type
                attributes[ATTR_DOCUMENT_SERIES] = offense.document_series

        if prefix:
            return {prefix + key: value for key, value in attributes.items()}

        return attributes

    @property
    def sensor_related_attributes(self) -> Dict[str, Any]:
        attributes = {
            ATTR_SERVICE_IS_OFFLINE: self._service_is_offline,
        }

        offenses = sorted(
            self.offenses,
            key=lambda x: (x.date_issued or date.min, x.date_committed or date.min),
            reverse=True,
        )

        try:
            last_offense = offenses[0]
        except IndexError:
            last_offense = None

        attributes.update(
            self.offense_to_attributes(last_offense, self.SHOW_OFFENSE_DOCUMENT, "last_offense_")
        )
        attributes[ATTR_OFFENSES] = [
            self.offense_to_attributes(offense, self.SHOW_OFFENSE_DOCUMENT) for offense in offenses
        ]

        return attributes

    @property
    def state(self) -> float:
        return -sum(map(lambda x: x.unpaid_amount or 0, self.offenses))

    @property
    def unit_of_measurement(self) -> Optional[str]:
        return UNIT_CURRENCY_RUSSIAN_ROUBLES


class MoscowPGUVehicleSensor(MoscowPGUOffensesSensor[Vehicle]):
    """Vehicle sensor."""

    #################################################################################
    # Component-specific code
    #################################################################################

    CONFIG_KEY: ClassVar[str] = "vehicles"
    DEFAULT_NAME_FORMAT: ClassVar[str] = "Vehicle - {identifier}"
    DEFAULT_SCAN_INTERVAL: ClassVar[timedelta] = timedelta(hours=2)

    NAME_RU: ClassVar[str] = "Транспортное средство"
    NAME_EN: ClassVar[str] = "Vehicle"

    ITER_COMPARE_ATTRIBUTES = ("id",)
    ITER_CHECK_NONE = False
    ITER_REFRESH_AFTER = True

    @classmethod
    async def async_get_objects_for_update(
        cls,
        hass: HomeAssistantType,
        config_entry: ConfigEntry,
        config: ConfigType,
        api: "API",
        filter_values: Collection[str] = (),
        is_blacklist: bool = True,
    ) -> Iterable[Vehicle]:
        return (
            vehicle
            for vehicle in await api.get_vehicles()
            if (
                vehicle.license_plate in filter_values
                or vehicle.certificate_series in filter_values
            )
            ^ is_blacklist
        )

    @property
    def name_format_values(self) -> Mapping[str, Any]:
        source = self.source
        return {
            **attr.asdict(source, recurse=False),
            "identifier": (source.license_plate or source.certificate_series or source.id),
        }

    @property
    def sensor_related_attributes(self) -> Optional[Dict[str, Any]]:
        source = self.source
        return {
            ATTR_ID: source.id,
            ATTR_LICENSE_PLATE: source.license_plate,
            ATTR_CERTIFICATE_SERIES: source.certificate_series,
            ATTR_IS_EVACUATED: bool(source.is_evacuated),
            **(super().sensor_related_attributes if source.certificate_series else {}),
        }

    async def async_retrieve_offenses(self) -> Iterable[Offense]:
        return await self.source.get_offenses()

    #################################################################################
    # HA-specific code
    #################################################################################

    async def async_update(self) -> None:
        if self.source.certificate_series:
            await super().async_update()

    @property
    def icon(self) -> Optional[str]:
        return "mdi:car"

    @property
    def state(self) -> Union[str, float]:
        return super().state if self.source.certificate_series else STATE_UNKNOWN

    @property
    def unit_of_measurement(self) -> Optional[str]:
        if self.source.certificate_series:
            return super().unit_of_measurement

    @property
    def unique_id(self) -> Optional[str]:
        return f"sensor_vehicle_{self.source.id}"


class MoscowPGUDrivingLicenseSensor(MoscowPGUOffensesSensor[DrivingLicense]):
    """Driving license sensor."""

    #################################################################################
    # Component-specific code
    #################################################################################

    CONFIG_KEY: ClassVar[str] = "driving_licenses"
    DEFAULT_NAME_FORMAT: ClassVar[str] = "Driving License - {identifier}"
    DEFAULT_SCAN_INTERVAL: ClassVar[timedelta] = timedelta(hours=2)
    SINGULAR_FILTER: ClassVar[bool] = True

    NAME_RU: ClassVar[str] = "Водительское удостоверение"
    NAME_EN: ClassVar[str] = "Driving License"

    SHOW_OFFENSE_DOCUMENT = False

    ITER_COMPARE_ATTRIBUTES = ("series",)
    ITER_REFRESH_AFTER = True
    ITER_CHECK_NONE = True

    @classmethod
    async def async_get_objects_for_update(
        cls,
        hass: HomeAssistantType,
        config_entry: ConfigEntry,
        config: ConfigType,
        api: "API",
        filter_values: Collection[str] = (),
        is_blacklist: bool = True,
    ) -> List[DrivingLicense]:
        profile = await api.get_profile()

        driving_licenses = []
        if profile.driving_license:
            driving_licenses.append(profile.driving_license)
        else:
            _LOGGER.error("No driving license on %s", profile)

        for additional_config_item in config[CONF_DRIVING_LICENSES]:
            if not additional_config_item:
                continue
            driving_license_series = additional_config_item[CONF_SERIES]

            for driving_license in driving_licenses:
                if driving_license.series == driving_license_series:
                    _LOGGER.warning(
                        'Driving license number ("%s") duplication detected',
                        driving_license_series,
                    )
                    continue

            driving_license_issue_date = additional_config_item.get(CONF_ISSUE_DATE)

            if not (
                driving_license_issue_date is None or isinstance(driving_license_issue_date, date)
            ):
                driving_license_issue_date = cv.date(driving_license_issue_date)

            driving_licenses.append(
                DrivingLicense(
                    api=profile.api,
                    series=driving_license_series,
                    issue_date=driving_license_issue_date,
                )
            )

        return driving_licenses

    async def async_retrieve_offenses(self) -> Iterable[Offense]:
        return await self.source.get_offenses()

    @property
    def name_format_values(self) -> Mapping[str, Any]:
        return {
            **attr.asdict(self.source, recurse=False),
            "identifier": self.source.series,
        }

    @property
    def sensor_related_attributes(self) -> Dict[str, Any]:
        return {
            ATTR_NUMBER: self.source.series,
            ATTR_ISSUE_DATE: dt_to_str(self.source.issue_date),
            **super().sensor_related_attributes,
        }

    #################################################################################
    # HA-specific code
    #################################################################################

    @property
    def icon(self) -> str:
        return "mdi:card-account-details"

    @property
    def unique_id(self) -> Optional[str]:
        return f"sensor_driving_license_{self.source.series}"


class MoscowPGUElectricCounterSensor(MoscowPGUSubmittableEntity, MoscowPGUSensor[ElectricAccount]):
    """Electric counter sensor."""

    #################################################################################
    # Component-specific code
    #################################################################################

    CONFIG_KEY: ClassVar[str] = "electric_counters"
    DEFAULT_NAME_FORMAT: ClassVar[str] = "Electric Counter - {identifier}"
    DEFAULT_SCAN_INTERVAL: ClassVar[timedelta] = timedelta(days=1)

    NAME_RU: ClassVar[str] = "Счётчик электроэнергии"
    NAME_EN: ClassVar[str] = "Electricity counter"

    ITER_COMPARE_ATTRIBUTES = ("device", "number")
    ITER_CHECK_NONE = False
    ITER_REFRESH_AFTER = True

    service_type: ClassVar[str] = TYPE_ELECTRIC

    def __init__(
        self,
        *args,
        balance: Optional[ElectricBalance] = None,
        counter_info: Optional[ElectricCounterInfo] = None,
        indications_status: Optional[ElectricIndicationsStatus] = None,
        last_payments: Optional[List[ElectricPayment]] = None,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)

        self.balance = balance
        self.counter_info = counter_info
        self.indications_status = indications_status
        self.last_payments = last_payments

        self.__event_listener = None

    @classmethod
    async def async_get_objects_for_update(
        cls,
        hass: HomeAssistantType,
        config_entry: ConfigEntry,
        config: ConfigType,
        api: "API",
        filter_values: Collection[str] = (),
        is_blacklist: bool = True,
    ) -> List[ElectricAccount]:
        flats = await api.get_flats()

        electric_accounts = []
        for flat in flats:
            electric_account = flat.electric_account
            if electric_account is None:
                continue

            device, number = electric_account.device, electric_account.number
            if not (device and number):  # @TODO: it is likely both are required
                continue

            if (
                device and device in filter_values or number and number in filter_values
            ) ^ is_blacklist:
                electric_accounts.append(electric_account)

        return electric_accounts

    @property
    def name_format_values(self) -> Mapping[str, Any]:
        attributes = {}

        electric_account = self.source
        attributes.update(
            {
                "identifier": electric_account.number,
                "account_number": electric_account.number,
                "device_name": electric_account.device,
            }
        )

        balance = self.balance
        if balance:
            attributes.update(attr.asdict(balance, recurse=False))

        return attributes

    @property
    def sensor_related_attributes(self) -> Dict[str, Any]:
        attributes = {ATTR_FLAT_ID: self.source.flat_id}

        if self.indications_status:
            status = self.indications_status

            attributes.update(
                {
                    ATTR_SUBMIT_AVAILABLE: not status.check_code,
                    ATTR_STATUS: status.check_message,
                    ATTR_CHECKUP_DATE: dt_to_str(status.counter_verification_date),
                    ATTR_STATE: status.counter_state,
                    ATTR_WHOLE_PART_LENGTH: status.counter_whole_part_length,
                    ATTR_DECIMAL_PART_LENGTH: status.counter_decimal_part_length,
                }
            )

        zones_data: List[Sequence[Dict[str, Any], Sequence[Sequence[time, time]]]] = []

        if self.balance:
            balance = self.balance

            if balance.indications:
                for indication in balance.indications:
                    if not indication.zone_name:
                        continue

                    zones_data.append(
                        (
                            {
                                ATTR_NAME: indication.zone_name,
                                ATTR_INDICATION: indication.indication,
                                ATTR_ZONE_ID: indication.tariff,
                            },
                            indication.periods,
                        )
                    )

            attributes.update(
                {
                    ATTR_SUBMIT_BEGIN_DATE: dt_to_str(balance.submit_begin_date),
                    ATTR_SUBMIT_END_DATE: dt_to_str(balance.submit_end_date),
                    ATTR_SETTLEMENT_DATE: dt_to_str(balance.settlement_date),
                    ATTR_DEBT_AMOUNT: balance.debt_amount,
                    ATTR_PAYMENTS_AMOUNT: balance.payments_amount,
                    ATTR_TRANSFER_AMOUNT: balance.transfer_amount,
                    ATTR_CHARGES_AMOUNT: balance.charges_amount,
                    ATTR_RETURNS_AMOUNT: balance.returns_amount,
                    ATTR_BALANCE_MESSAGE: balance.balance_message,
                }
            )

            if (
                attributes.get(ATTR_SUBMIT_AVAILABLE, True) is True
                and balance.submit_begin_date
                and balance.submit_end_date
            ):
                attributes[ATTR_SUBMIT_AVAILABLE] = (
                    balance.submit_begin_date <= date.today() <= balance.submit_end_date
                )

        if self.counter_info:
            info = self.counter_info

            attributes[ATTR_TYPE] = info.type

            for zone in info.zones:
                if not zone.name:
                    continue

                zones_data.append(
                    (
                        {
                            ATTR_NAME: zone.name,
                            ATTR_TARIFF: zone.cost,
                        },
                        zone.periods,
                    )
                )

        if self.last_payments:
            payments = {
                payment.payment_date.isoformat(): payment.amount
                for payment in sorted(
                    self.last_payments, key=lambda x: x.payment_date, reverse=True
                )
            }
            last_payment = next(iter(payments.items())) if payments else (None, None)
            attributes[ATTR_LAST_PAYMENT_DATE], attributes[ATTR_LAST_PAYMENT_AMOUNT] = last_payment
            attributes[ATTR_PAYMENTS] = payments

        attributes.setdefault(ATTR_SUBMIT_AVAILABLE, False)

        zones_dict = {}

        zone_expected_attrs = (ATTR_NAME, ATTR_INDICATION, ATTR_ZONE_ID, ATTR_TARIFF)
        period_to_zones: Dict[time, int] = {}
        for zone_data, periods in zones_data:
            lower_name = zone_data[ATTR_NAME].lower()

            if "полупик" in lower_name or "3" in lower_name:
                zone_id = 3
            elif "ноч" in lower_name or "2" in lower_name:
                zone_id = 2
            elif (
                "одно" in lower_name
                or "кругло" in lower_name
                or "пик" in lower_name
                or "1" in lower_name
            ):
                zone_id = 1
            else:
                _LOGGER.warning(f"Unknown zone data: {zone_data}")
                continue
            if zone_id in zones_data:
                for key, value in zone_data:
                    if not zones_dict[zone_id].get(key):
                        zones_dict[zone_id][key] = value
            else:
                zones_dict[zone_id] = zone_data

            for start, _ in periods:
                period_to_zones[start] = zone_id

        for zone_id in sorted(zones_dict.keys()):
            zone_dict = zones_dict[zone_id]
            for key in sorted(set(zone_expected_attrs).union(zone_dict.keys())):
                attributes[f"zone_{zone_id}_{key}"] = zone_dict.get(key)

        attributes[ATTR_PERIODS] = {
            key.isoformat(): period_to_zones[key] for key in sorted(period_to_zones.keys())
        }

        return attributes

    async def async_get_indications_count(
        self, service_type: str, force: bool
    ) -> Optional[Union[int, Tuple[int, int]]]:
        counter_info = self.counter_info
        if not (counter_info or counter_info.zones_count):
            # @TODO: reuse this request
            counter_info = await self.source.get_electric_counter_info()

        zones_count = counter_info.zones_count
        return zones_count or (None if force else 0)

    async def async_get_indications_event_data_dict(
        self, indications: List[Union[str, SupportsFloat]], force: bool, service_type: str
    ) -> Dict[str, Any]:
        electric_account = self.source

        return {
            ATTR_FLAT_ID: electric_account.flat_id,
            ATTR_NUMBER: electric_account.number,
            ATTR_DEVICE: electric_account.device,
            ATTR_INDICATIONS: indications,
        }

    async def _async_push_indications(
        self, indications: List[float], force: bool, service_type: str, dry_run: bool
    ) -> None:
        _LOGGER.info(f"{self.log_prefix}Pushing indications: {indications}")
        if not dry_run:
            await self.source.push_electric_indications(indications, perform_checks=not force)

    #################################################################################
    # HA-specific code
    #################################################################################

    async def async_update(self) -> None:
        electric_account = self.source

        if electric_account.number:
            balance, last_payments = await asyncio.gather(
                electric_account.get_electric_balance(),
                electric_account.get_electric_payments(),
                return_exceptions=True,
            )

            if isinstance(last_payments, BaseException):
                _LOGGER.error(f"Error on last payments update: {last_payments}")
            else:
                self.last_payments = last_payments

            if isinstance(balance, BaseException):
                _LOGGER.error(f"Error on balance update: {balance}")
            else:
                self.balance = balance

        if electric_account.device:
            counter_info, indications_status = await asyncio.gather(
                electric_account.get_electric_counter_info(),
                electric_account.get_electric_indications_status(),
                return_exceptions=True,
            )

            if isinstance(counter_info, BaseException):
                _LOGGER.error(f"Error on counter info update: {counter_info}")
            else:
                self.counter_info = counter_info

            if isinstance(indications_status, BaseException):
                _LOGGER.error(f"Error on indications status update: {indications_status}")
            else:
                self.indications_status = indications_status

    @property
    def icon(self) -> str:
        return "mdi:flash-circle"

    @property
    def unique_id(self) -> Optional[str]:
        return f"sensor_electric_counter_{self.source.number}"

    @property
    def state(self) -> Union[float, str]:
        if self.balance:
            amount = self.balance.balance_amount
            if amount is not None:
                return amount

        return STATE_UNKNOWN

    @property
    def unit_of_measurement(self) -> Optional[str]:
        if self.balance and self.balance.balance_amount is not None:
            return UNIT_CURRENCY_RUSSIAN_ROUBLES

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        self.__event_listener = self.hass.bus.async_listen(
            EVENT_FORMAT_INDICATIONS_PUSH % (TYPE_ELECTRIC,),
            lambda x: self.async_schedule_update_ha_state(force_refresh=True),
            callback(lambda x: (self.source and self.source.device in x.data[ATTR_COUNTER_IDS])),
        )

    async def async_push_indications(
        self,
        indications: List[Union[str, SupportsFloat]],
        force: bool = False,
        service_type: Optional[str] = None,
        dry_run: bool = False,
    ) -> None:
        if self.source.device is None:
            raise MoscowPGUException("Device is not present!")
        await super().async_push_indications(indications, force, service_type, dry_run)

    async def async_will_remove_from_hass(self) -> None:
        if self.__event_listener:
            self.__event_listener()

        await super().async_will_remove_from_hass()


class MoscowPGUWaterCounterSensor(MoscowPGUSubmittableEntity, MoscowPGUSensor[WaterCounter]):
    """Water counter sensor."""

    #################################################################################
    # Component-specific code
    #################################################################################

    service_type: ClassVar[str] = TYPE_WATER

    CONFIG_KEY: ClassVar[str] = "water_counters"
    DEFAULT_NAME_FORMAT: ClassVar[str] = "{type} Water Counter - {identifier}"
    DEFAULT_SCAN_INTERVAL: ClassVar[timedelta] = timedelta(days=1)

    NAME_RU: ClassVar[str] = "Счётчик водоснабжения"
    NAME_EN: ClassVar[str] = "Water counter"

    ITER_COMPARE_ATTRIBUTES = ("id", "flat_id")
    ITER_CHECK_NONE = False
    ITER_REFRESH_AFTER = False

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.__event_listener = None

    @classmethod
    async def async_get_objects_for_update(
        cls,
        hass: HomeAssistantType,
        config_entry: ConfigEntry,
        config: ConfigType,
        api: "API",
        filter_values: Collection[str] = (),
        is_blacklist: bool = True,
    ) -> Iterable[WaterCounter]:
        flats = await api.get_flats()
        flats_with_water = [
            flat
            for flat in flats
            if flat.epd_account
            and (
                (
                    flat.epd_account in filter_values
                    or str(flat.flat_id) in filter_values
                    or flat.name in filter_values
                )
                ^ is_blacklist
            )
        ]

        return itertools.chain(
            *(await asyncio.gather(*(flat.get_water_counters() for flat in flats_with_water)))
        )

    async def async_get_indications_count(
        self, service_type: str, force: bool
    ) -> Optional[Union[int, Tuple[int, int]]]:
        return 1

    async def async_get_indications_event_data_dict(
        self, indications: List[float], force: bool, service_type: str
    ) -> Dict[str, Any]:
        return {
            ATTR_FLAT_ID: self.source.flat_id,
            ATTR_COUNTER_IDS: [self.source.id],
            ATTR_TYPES: [self.source.type.name.lower()],
            ATTR_CODES: [self.source.code],
            ATTR_INDICATIONS: [indications[0]],  # ... redundant (?)
        }

    async def _async_push_indications(
        self, indications: List[float], force: bool, service_type: str, dry_run: bool
    ) -> None:
        indication = indications[0]
        last_indication = self.source.last_indication

        if not (force or last_indication is None or last_indication.indication is None):
            if indication < last_indication.indication:
                raise ValueError(
                    "New indication is less than old indication value (%s <= %s)"
                    % (indication, last_indication.indication)
                )

        _LOGGER.info(
            f"{self.log_prefix}Pushing single indication to " f"{self.source.code}: {indication}",
        )
        if not dry_run:
            await self.source.push_water_counter_indication(indication)

    @property
    def name_format_values(self) -> Mapping[str, Any]:
        return {
            **attr.asdict(self.source, recurse=False),
            "identifier": self.source.code,
            "type": self.source.type.name.title(),
        }

    @property
    def sensor_related_attributes(self) -> Optional[Dict[str, Any]]:
        indications = self.source.indications or {}

        if indications:
            indications = {
                indication.period.isoformat(): indication.indication for indication in indications
            }

        water_counter_type = self.source.type
        if water_counter_type:
            water_counter_type = water_counter_type.name.lower()

        last_indication = self.source.last_indication
        if last_indication is not None:
            last_indication_period = last_indication.period.isoformat()
            last_indication_value = last_indication.indication
        else:
            last_indication_period = None
            last_indication_value = None

        return {
            ATTR_ID: self.source.id,
            ATTR_CODE: self.source.code,
            ATTR_TYPE: water_counter_type,
            ATTR_INDICATIONS: indications,
            ATTR_LAST_INDICATION_PERIOD: last_indication_period,
            ATTR_LAST_INDICATION_VALUE: last_indication_value,
            ATTR_CHECKUP_DATE: dt_to_str(self.source.checkup_date),
            ATTR_FLAT_ID: self.source.flat_id,
        }

    #################################################################################
    # HA-specific code
    #################################################################################

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        self.__event_listener = self.hass.bus.async_listen(
            EVENT_FORMAT_INDICATIONS_PUSH % (self.service_type,),
            lambda x: self.async_schedule_update_ha_state(force_refresh=True),
            callback(lambda x: (self.source.id in x.data[ATTR_COUNTER_IDS])),
        )

    async def async_will_remove_from_hass(self) -> None:
        if self.__event_listener:
            self.__event_listener()

        await super().async_will_remove_from_hass()

    async def async_update(self) -> None:
        water_counters = await self.source.api.get_water_counters(flat_id=self.source.flat_id)
        for water_counter in water_counters:
            if water_counter.id == self.source.id:
                self.source = water_counter
                return

        raise RuntimeError("Could not find water counter entity to update data with")

    @property
    def icon(self) -> Optional[str]:
        return "mdi:counter"

    @property
    def unit_of_measurement(self) -> str:
        return "m\u00b3"

    @property
    def state(self) -> Union[float, str]:
        last_indication = self.source.last_indication

        if last_indication:
            current_month_start = date.today().replace(day=1)
            if last_indication.period >= current_month_start:
                return last_indication.indication

        return STATE_UNKNOWN

    @property
    def unique_id(self) -> Optional[str]:
        return f"sensor_water_counter_{self.source.flat_id}_{self.source.id}"


class MoscowPGUFlatSensor(MoscowPGUSensor[Flat]):
    """Flat entity sensor"""

    #################################################################################
    # Component-specific code
    #################################################################################

    CONFIG_KEY: ClassVar[str] = "flats"
    DEFAULT_NAME_FORMAT: ClassVar[str] = "Flat - {identifier}"
    DEFAULT_SCAN_INTERVAL: ClassVar[timedelta] = timedelta(days=1)

    NAME_RU: ClassVar[str] = "Квартира (ЕПД)"
    NAME_EN: ClassVar[str] = "Flat (EPD)"

    ITER_COMPARE_ATTRIBUTES = ("id",)
    ITER_CHECK_NONE = False
    ITER_REFRESH_AFTER = True

    def __init__(self, *args, epds: Iterable[EPD] = (), **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.epds = list(epds)

    @classmethod
    async def async_get_objects_for_update(
        cls,
        hass: HomeAssistantType,
        config_entry: ConfigEntry,
        config: ConfigType,
        api: "API",
        filter_values: Collection[str] = (),
        is_blacklist: bool = True,
    ) -> Iterable[Flat]:
        return (
            flat
            for flat in await api.get_flats()
            if ((str(flat.flat_id) in filter_values or flat.name in filter_values) ^ is_blacklist)
        )

    @property
    def name_format_values(self) -> Mapping[str, Any]:
        identifier = self.source.name

        if not identifier:
            identifier = self.source.address

            if self.source.flat_number is not None:
                identifier += " " + str(self.source.flat_number)

        return {
            **attr.asdict(self.source, recurse=False),
            "identifier": identifier,
        }

    @staticmethod
    def epd_to_attributes(epd: Optional[EPD], prefix: Optional[str] = None) -> Dict[str, Any]:
        if epd is None:
            attributes = dict.fromkeys(
                (
                    ATTR_ID,
                    ATTR_INSURANCE_AMOUNT,
                    ATTR_PERIOD,
                    ATTR_TYPE,
                    ATTR_PAYMENT_AMOUNT,
                    ATTR_PAYMENT_DATE,
                    ATTR_PAYMENT_STATUS,
                    ATTR_INITIATOR,
                    ATTR_CREATE_DATETIME,
                    ATTR_PENALTY_AMOUNT,
                    ATTR_AMOUNT,
                    ATTR_AMOUNT_WITH_INSURANCE,
                    ATTR_UNPAID_AMOUNT,
                ),
                None,
            )

        else:
            attributes = {
                ATTR_ID: epd.id,
                ATTR_INSURANCE_AMOUNT: epd.insurance_amount,
                ATTR_PERIOD: dt_to_str(epd.period),
                ATTR_TYPE: epd.type,
                ATTR_PAYMENT_AMOUNT: epd.payment_amount,
                ATTR_PAYMENT_DATE: dt_to_str(epd.payment_date),
                ATTR_PAYMENT_STATUS: epd.payment_status,
                ATTR_INITIATOR: epd.initiator,
                ATTR_CREATE_DATETIME: dt_to_str(epd.create_datetime),
                ATTR_PENALTY_AMOUNT: epd.penalty_amount,
                ATTR_AMOUNT: epd.amount,
                ATTR_AMOUNT_WITH_INSURANCE: epd.amount_with_insurance,
                ATTR_UNPAID_AMOUNT: epd.unpaid_amount,
            }

        if prefix:
            return {prefix + key: value for key, value in attributes.items()}

        return attributes

    @property
    def sensor_related_attributes(self) -> Optional[Dict[str, Any]]:
        flat = self.source
        epd_account = flat.epd_account
        attributes = {
            ATTR_ID: flat.id,
            ATTR_NAME: flat.name,
            ATTR_ADDRESS: flat.address,
            ATTR_FLAT_NUMBER: flat.flat_number,
            ATTR_ENTRANCE_NUMBER: flat.entrance_number,
            ATTR_FLOOR: flat.floor,
            ATTR_INTERCOM: flat.intercom,
            ATTR_PHONE_NUMBER: flat.phone_number,
            ATTR_EPD_ACCOUNT: epd_account,
        }

        if epd_account:
            epds = sorted(self.epds, key=lambda x: x.period or date.min, reverse=True)

            try:
                last_epd = epds[0]
            except IndexError:
                last_epd = None

            attributes.update(self.epd_to_attributes(last_epd, "last_epd_"))
            attributes[ATTR_EPDS] = [self.epd_to_attributes(epd) for epd in epds]

        return attributes

    #################################################################################
    # HA-specific code
    #################################################################################

    async def async_update(self) -> None:
        flat = self.source

        if flat.epd_account:
            date_today = date.today()
            shift_months = 3
            if date_today.month <= shift_months:
                date_begin = date_today.replace(
                    day=1, month=12 + date_today.month - shift_months, year=date_today.year - 1
                )
            else:
                date_begin = date_today.replace(
                    day=1,
                    month=date_today.month - shift_months,
                )

            try:
                epds = await flat.api.get_flat_epds(
                    flat_id=flat.id,
                    begin=date_begin,
                    end=date_today,
                )

            except MoscowPGUException as e:
                _LOGGER.error("Could not fetch EPDs: %s", e)
            else:
                self.epds.clear()
                self.epds.extend(epds)

    @property
    def icon(self) -> Optional[str]:
        return "mdi:door"

    @property
    def state(self) -> Union[str, float]:
        if self.source.epd_account:
            return -sum(map(lambda x: x.unpaid_amount or 0, self.epds or []))
        return STATE_UNKNOWN

    @property
    def unit_of_measurement(self) -> Optional[str]:
        if self.source.epd_account:
            return UNIT_CURRENCY_RUSSIAN_ROUBLES

    @property
    def unique_id(self) -> Optional[str]:
        return f"sensor_flat_{self.source.id}"


class MoscowPGUDiarySensor(MoscowPGUSensor[DiaryWidget]):
    """Child diary sensor."""

    #################################################################################
    # Component-specific code
    #################################################################################

    CONFIG_KEY: ClassVar[str] = "diaries"
    DEFAULT_NAME_FORMAT: ClassVar[str] = "Grades - {identifier}"

    NAME_RU: ClassVar[str] = "Школьный дневник"
    NAME_EN: ClassVar[str] = "School Journal"

    ITER_COMPARE_ATTRIBUTES = ("child_alias",)
    ITER_CHECK_NONE = False
    ITER_REFRESH_AFTER = True

    def __init__(
        self, *args, attestation_marks: Iterable[SubjectAttestationMark] = (), **kwargs
    ) -> None:
        super().__init__(*args, **kwargs)
        self.attestation_marks: List[SubjectAttestationMark] = list(attestation_marks)

    @classmethod
    async def async_get_objects_for_update(
        cls,
        hass: HomeAssistantType,
        config_entry: ConfigEntry,
        config: ConfigType,
        api: "API",
        filter_values: Collection[str] = (),
        is_blacklist: bool = True,
    ) -> Iterable[DiaryWidget]:
        return (
            diary
            for diary in await api.async_get_diaries()
            if (
                (diary.title in filter_values or diary.child_first_name in filter_values)
                ^ is_blacklist
            )
        )

    @property
    def name_format_values(self) -> Mapping[str, Any]:
        return {
            **attr.asdict(self.source),
            "identifier": self.source.child_first_name,
        }

    @property
    def sensor_related_attributes(self) -> Optional[Dict[str, Any]]:
        return {
            attestation_mark.subject_name: attestation_mark.average_mark
            for attestation_mark in sorted(self.attestation_marks, key=lambda x: x.subject_name)
        }

    #################################################################################
    # HA-specific code
    #################################################################################

    async def async_update(self) -> None:
        self.attestation_marks = await self.source.async_get_attestation_marks()

    @property
    def state(self) -> StateType:
        attestation_marks = self.attestation_marks
        if len(attestation_marks) == 0:
            return STATE_UNKNOWN
        return min(attestation_mark.average_mark for attestation_mark in attestation_marks)

    @property
    def icon(self) -> str:
        return "mdi:notebook"

    @property
    def unique_id(self) -> str:
        return f"sensor_child_{self.source.child_alias}"


class MoscowPGUChildSensor(MoscowPGUSensor[Child]):
    """Children binary sensor"""

    #################################################################################
    # Component-specific code
    #################################################################################

    CONFIG_KEY: ClassVar[str] = "children"
    DEFAULT_NAME_FORMAT: ClassVar[str] = "Child - {identifier}"
    DEFAULT_SCAN_INTERVAL: ClassVar[timedelta] = timedelta(hours=1, microseconds=1)

    NAME_RU: ClassVar[str] = "Ребёнок"
    NAME_EN: ClassVar[str] = "Child"

    ITER_COMPARE_ATTRIBUTES = ("id",)
    ITER_CHECK_NONE = False
    ITER_REFRESH_AFTER = False

    @classmethod
    async def async_get_objects_for_update(
        cls,
        hass: HomeAssistantType,
        config_entry: ConfigEntry,
        config: ConfigType,
        api: "API",
        filter_values: Collection[str] = (),
        is_blacklist: bool = True,
    ) -> Iterable:
        return (
            child_info
            for child_id, child_info in (await api.get_children_info()).items()
            if ((child_id in filter_values or child_info.name in filter_values) ^ is_blacklist)
        )

    @property
    def name_format_values(self) -> Mapping[str, Any]:
        return {
            **attr.asdict(self.source, recurse=False),
            "identifier": self.source.name,
        }

    @property
    def sensor_related_attributes(self) -> Optional[Dict[str, Any]]:
        child = self.source
        return {
            ATTR_FIRST_NAME: child.name,
            ATTR_LAST_NAME: child.surname,
            ATTR_MIDDLE_NAME: child.patronymic,
            ATTR_SCHOOL: child.school,
            ATTR_CLASS: child.class_,
            ATTR_PAY_LIMIT: child.pay_limit,
            ATTR_LAST_UPDATE_DATE: child.last_update_date,
            ATTR_IS_AT_SCHOOL: bool(child.is_inside_school),
        }

    #################################################################################
    # HA-specific code
    #################################################################################

    async def async_update(self) -> None:
        self.source = await self.source.api.get_child_info(self.source.id)

    @property
    def state(self) -> StateType:
        balance = self.source.balance
        return STATE_UNKNOWN if balance is None else round(balance, 2)

    @property
    def icon(self) -> Optional[str]:
        last_update_date = self.source.last_update_date
        if last_update_date:
            if self.source.is_inside_school:
                return "mdi:schair-school"
            return "mdi:exit-run"
        return "mdi:human-child"

    @property
    def unique_id(self) -> str:
        return f"sensor_child_{self.source.id}"


# Platform setup
BASE_CLASS: Final = MoscowPGUSensor
async_setup_entry: Final = make_platform_setup(BASE_CLASS, logger=_LOGGER)
