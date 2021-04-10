import asyncio
import functools
import hashlib
import logging
from abc import ABC
from datetime import timedelta, date, time, datetime
from typing import Type, Mapping, Optional, List, Any, Dict, Union, Callable, Tuple, Iterable, TypeVar, Set, Awaitable

import attr
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL, CONF_USERNAME, ATTR_ID, ATTR_CODE, STATE_UNKNOWN, STATE_OK, \
    ATTR_ATTRIBUTION, ATTR_DEVICE_CLASS, ATTR_NAME, ATTR_STATE, ATTR_TIME, ATTR_ENTITY_ID
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import HomeAssistantType, StateType, ConfigType
from homeassistant.util.dt import now as dt_now

from custom_components.moscow_pgu import extract_config
from custom_components.moscow_pgu.const import *
from custom_components.moscow_pgu.moscow_pgu_api import API, WaterCounter, MoscowPGUException, Profile, Offense, \
    Vehicle, \
    FSSPDebt, DrivingLicense, Flat, EPD, ElectricBalance, ElectricCounterInfo, WaterCounterType, \
    ElectricIndicationsStatus

_LOGGER = logging.getLogger(__name__)

TSensor = TypeVar('TSensor', bound='MoscowPGUSensor')
DiscoveryReturnType = Tuple[List['MoscowPGUSensor'], List[asyncio.Task]]

try:
    WrappedFType = Callable[[HomeAssistantType, ConfigEntry, ConfigType, ...], Awaitable[DiscoveryReturnType]]
except TypeError:
    WrappedFType = Callable[..., Awaitable[DiscoveryReturnType]]


SERVICE_PUSH_INDICATION = 'push_indication'
SERVICE_PUSH_INDICATION_SCHEMA = {
    vol.Required(ATTR_INDICATIONS): vol.Any(
        vol.All(cv.positive_float, lambda x: [x]),
        vol.All(cv.string, vol.Length(min=1), lambda x: list(map(cv.positive_float, x.strip('[](){}').split(',')))),
        vol.All(cv.ensure_list, vol.Length(min=1), [cv.positive_float]),
    ),
    vol.Optional(ATTR_FORCE, default=False): cv.boolean,
    vol.Optional(ATTR_TYPE): vol.All(cv.string, vol.Lower, vol.In((TYPE_ELECTRIC, TYPE_WATER))),
}


def get_entities(
        hass: HomeAssistantType,
        config_entry_id: Optional[str] = None,
        entities_cls: Optional[Type[TSensor]] = None,
        create: bool = False
) -> Union[
    Dict[str, Dict[Type[TSensor], List[TSensor]]],
    Dict[Type[TSensor], List[TSensor]],
    List[TSensor]
]:
    if create:
        entities = hass.data.setdefault(DATA_ENTITIES, {})
        if config_entry_id is not None:
            entities = entities.setdefault(config_entry_id, {})
            if entities_cls is not None:
                entities = entities.setdefault(entities_cls, [])

    else:
        entities = hass.data.get(DATA_ENTITIES, {})
        if config_entry_id is not None:
            entities = entities.get(config_entry_id, {})
            if entities_cls is not None:
                entities = entities.get(entities_cls, [])

    return entities


class EntityUpdater:
    def __init__(self, hass: HomeAssistantType, scan_interval: timedelta,
                 entities_cls: Type[TSensor], config_entry_id: str):
        self.hass = hass
        self.entities_cls = entities_cls
        self.scan_interval = scan_interval
        self.cancel_callback = None
        self.config_entry_id = config_entry_id

    @property
    def log_prefix(self):
        return '[%s][%s][updater] ' % (self.config_entry_id, self.entities_cls.__name__)

    async def __updater(self, *_, **__):
        _LOGGER.debug(self.log_prefix + 'Running')

        for entity in get_entities(self.hass, self.config_entry_id, self.entities_cls):
            entity.async_schedule_update_ha_state(force_refresh=True)

    def schedule(self):
        _LOGGER.debug(self.log_prefix + 'Scheduling')
        self.cancel_callback = async_track_time_interval(self.hass, self.__updater, self.scan_interval)

    def cancel(self):
        if self.cancel_callback is None:
            _LOGGER.debug(self.log_prefix + 'Attempted to cancel non-running')
            return

        _LOGGER.debug(self.log_prefix + 'Cancelling')
        self.cancel_callback()
        self.cancel_callback = None

    def execute(self, offset_updater: bool = True):
        _LOGGER.debug(self.log_prefix + 'Calling directly')
        self.hass.async_create_task(self.__updater())

        if offset_updater:
            self.cancel()
            self.schedule()

    __call__ = cancel


def wrap_entities_updater(entities_cls: Type[TSensor], interval_key: str, default_interval: Union[timedelta, int]):
    if isinstance(default_interval, int):
        default_interval = timedelta(seconds=default_interval)

    def _decorator(func: WrappedFType):
        @functools.wraps(func)
        async def _internal(hass: HomeAssistantType, config_entry: ConfigEntry, config: ConfigType, *args, **kwargs):
            entities, tasks = await func(hass, config_entry, config, *args, **kwargs)

            all_updaters: Dict[str, Dict[Type[TSensor], EntityUpdater]] = hass.data.setdefault(DATA_UPDATERS, {})
            key = config_entry.entry_id
            scan_interval = config.get(CONF_SCAN_INTERVAL, {}).get(interval_key, default_interval)
            key_updaters = all_updaters.setdefault(key, {})
            existing_updater = key_updaters.get(entities_cls)

            if existing_updater:
                existing_updater.cancel()
                existing_updater.scan_interval = scan_interval
                existing_updater.schedule()

            else:
                existing_updater = EntityUpdater(hass, scan_interval, entities_cls, key)
                existing_updater.schedule()
                key_updaters[entities_cls] = existing_updater

            return entities, tasks

        return _internal

    return _decorator


def dt_to_str(dt: Optional[Union[date, time, datetime]]) -> Optional[str]:
    """Optional date to string helper"""
    if dt is not None:
        return dt.isoformat()


def offense_to_attributes(offense: Offense, with_document: bool = True):
    """Convert `moscow_pgu_api.Offense` object to a dictionary of entity attributes"""
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
        attributes.update({
            ATTR_DOCUMENT_TYPE: offense.document_type,
            ATTR_DOCUMENT_SERIES: offense.document_series,
        })

    return attributes


class NameFormatDict(dict):
    def __missing__(self, key):
        return '{{' + str(key) + '}}'


class MoscowPGUSensor(Entity):
    def __init__(self, name_format: str):
        self.name_format = name_format

    @property
    def log_prefix(self) -> str:
        return '[%s][%s][%s] ' % (
            self.registry_entry.config_entry_id,
            self.__class__.__name__,
            self.unique_id,
        )

    @property
    def should_poll(self) -> bool:
        return False

    async def async_added_to_hass(self) -> None:
        entities = get_entities(self.hass, self.registry_entry.config_entry_id, self.__class__, create=True)

        if self not in entities:
            _LOGGER.debug(self.log_prefix + 'Adding to registry')
            entities.append(self)

    async def async_will_remove_from_hass(self) -> None:
        entities = get_entities(self.hass, self.registry_entry.config_entry_id, self.__class__, create=False)

        if self in entities:
            _LOGGER.debug(self.log_prefix + 'Will remove from registry')
            entities.remove(self)

    @property
    def device_state_attributes(self) -> Optional[Dict[str, Any]]:
        _device_state_attributes = self.sensor_related_attributes or {}
        _device_state_attributes.setdefault(ATTR_ATTRIBUTION, 'Data provided by Moscow PGU')

        if ATTR_DEVICE_CLASS not in _device_state_attributes:
            device_class = self.device_class
            if device_class is not None:
                _device_state_attributes[ATTR_DEVICE_CLASS] = device_class

        return _device_state_attributes

    @property
    def sensor_related_attributes(self) -> Optional[Dict[str, Any]]:
        return None

    @property
    def name(self) -> Optional[str]:
        name_format_values = NameFormatDict({
            key: ('' if value is None else value)
            for key, value in self.name_format_values.items()
        })
        return self.name_format.format_map(name_format_values)

    @property
    def unique_id(self) -> str:
        raise NotImplementedError

    @property
    def name_format_values(self) -> Mapping[str, Any]:
        raise NotImplementedError

    async def async_update(self) -> None:
        raise NotImplementedError


class MoscowPGUDiscoverySensor(MoscowPGUSensor, ABC):
    """Class for sensors that will receive their initial values on discovery"""


class MoscowPGUWaterCounterSensor(MoscowPGUDiscoverySensor):
    def __init__(self, *args, water_counter: WaterCounter, **kwargs):
        if not water_counter.id:
            raise ValueError('cannot create water counter sensor without water counter ID')
        if not water_counter.flat_id:
            raise ValueError('cannot create water counter sensor without flat ID')

        super().__init__(*args, **kwargs)

        self.water_counter = water_counter

    @property
    def icon(self) -> Optional[str]:
        return 'mdi:counter'

    @property
    def unit_of_measurement(self) -> str:
        return 'm\u00b3'

    @property
    def device_class(self) -> Optional[str]:
        return DEVICE_CLASS_PGU_INDICATIONS

    @property
    def state(self) -> Union[float, str]:
        last_indication = self.water_counter.last_indication

        if last_indication:
            current_month_start = date.today().replace(day=1)
            if last_indication.period >= current_month_start:
                return last_indication.indication

        return STATE_UNKNOWN

    @property
    def unique_id(self) -> Optional[str]:
        return f'sensor_water_counter_{self.water_counter.flat_id}_{self.water_counter.id}'

    @property
    def name_format_values(self) -> Mapping[str, Any]:
        return {
            **attr.asdict(self.water_counter, recurse=False),
            'identifier': self.water_counter.code,
            'type': self.water_counter.type.name.title(),
        }

    @property
    def sensor_related_attributes(self) -> Optional[Dict[str, Any]]:
        indications = self.water_counter.indications or {}

        if indications:
            indications = {
                indication.period.isoformat(): indication.indication
                for indication in indications
            }

        water_counter_type = self.water_counter.type
        if water_counter_type:
            water_counter_type = water_counter_type.name.lower()

        last_indication = self.water_counter.last_indication
        if last_indication is not None:
            last_indication_period = last_indication.period.isoformat()
            last_indication_value = last_indication.indication
        else:
            last_indication_period = None
            last_indication_value = None

        return {
            ATTR_ID: self.water_counter.id,
            ATTR_CODE: self.water_counter.code,
            ATTR_TYPE: water_counter_type,
            ATTR_INDICATIONS: indications,
            ATTR_LAST_INDICATION_PERIOD: last_indication_period,
            ATTR_LAST_INDICATION_VALUE: last_indication_value,
            ATTR_CHECKUP_DATE: dt_to_str(self.water_counter.checkup_date),
            ATTR_FLAT_ID: self.water_counter.flat_id,
        }

    async def async_update(self) -> None:
        water_counters = await self.water_counter.api.get_water_counters(flat_id=self.water_counter.flat_id)
        for water_counter in water_counters:
            if water_counter.id == self.water_counter.id:
                self.water_counter = water_counter
                return

        raise RuntimeError('Could not find water counter entity to update data with')

    # noinspection PyIncorrectDocstring
    async def async_push_indications(self, indications: List[float], force: bool = False, **kwargs) -> None:
        """
        Push water indication (single) to given meter.
        :param indications: List of indications (for compatibility; contains single indication)
        :param force: Ignore checks
        :param type: Indications type
        :return:
        """
        indication = None
        try:
            type_ = kwargs.get('type')
            if type_ is not None and type_ != TYPE_WATER:
                raise ValueError('Invalid type selected (expected "%s", got "%s")' % (TYPE_WATER, type_))

            if len(indications) < 1:
                raise ValueError('Insufficient indications provided (expected 1, got 0)')

            if len(indications) > 1:
                raise ValueError('Too many indications provided (expected 1, got %d)' % (len(indications),))

            indication = indications[0]
            last_indication = self.water_counter.last_indication

            if not (force or last_indication is None or last_indication.indication is None):
                if indication <= last_indication.indication:
                    raise ValueError('New indication is less than or equal to old indication value (%s <= %s)' %
                                     (indications, last_indication.indication))

            await self.water_counter.push_water_counter_indication(indication)

            _LOGGER.info('Indication (%s) pushed succesfully to "%s" (flat ID: %s)',
                         indication, self.entity_id, self.water_counter.flat_id)

        except Exception as e:
            self.hass.bus.async_fire(
                event_type=EVENT_WATER_INDICATIONS_PUSH_FAILED,
                event_data={
                    ATTR_TIME: dt_now(),
                    ATTR_FLAT_ID: self.water_counter.flat_id,
                    ATTR_COUNTER_ID: self.water_counter.id,
                    ATTR_TYPE: self.water_counter.type.name.lower(),
                    ATTR_CODE: self.water_counter.code,
                    ATTR_INDICATION: indication,
                    ATTR_REASON: str(e),
                }
            )

            raise

        else:
            self.hass.bus.async_fire(
                event_type=EVENT_WATER_INDICATIONS_PUSHED,
                event_data={
                    ATTR_TIME: dt_now(),
                    ATTR_FLAT_ID: self.water_counter.flat_id,
                    ATTR_COUNTER_ID: self.water_counter.id,
                    ATTR_TYPE: self.water_counter.type.name.lower(),
                    ATTR_CODE: self.water_counter.code,
                    ATTR_INDICATION: indication,
                }
            )


class MoscowPGUProfileSensor(MoscowPGUDiscoverySensor):
    def __init__(self, *args, profile: Profile, **kwargs):
        assert profile.phone_number, 'init profile yields an empty phone number'

        super().__init__(*args, **kwargs)

        self.profile = profile

    @property
    def icon(self) -> Optional[str]:
        return 'mdi:account'

    @property
    def state(self) -> StateType:
        return STATE_OK

    @property
    def unique_id(self) -> Optional[str]:
        return f'sensor_profile_{self.profile.phone_number}'

    @property
    def name_format_values(self) -> Mapping[str, Any]:
        return {
            **attr.asdict(self.profile, recurse=False),
            'identifier': self.profile.phone_number,
        }

    @property
    def sensor_related_attributes(self) -> Optional[Dict[str, Any]]:
        profile = self.profile

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

    async def async_update(self) -> None:
        self.profile = await self.profile.api.get_profile()


class MoscowPGUDrivingLicenseSensor(MoscowPGUSensor):
    def __init__(self, *args, driving_license: DrivingLicense, offenses: Optional[Iterable[Offense]] = None, **kwargs):
        assert driving_license.series is not None, 'init driving license yields no number'

        super().__init__(*args, **kwargs)

        self.driving_license = driving_license
        self.offenses = []

        if offenses is not None:
            self.offenses.extend(offenses)

    @property
    def icon(self) -> str:
        return 'mdi:card-account-details'

    @property
    def state(self) -> float:
        return -sum(map(lambda x: x.unpaid_amount or 0, self.offenses))

    @property
    def unit_of_measurement(self) -> str:
        return UNIT_CURRENCY_RUSSIAN_ROUBLES

    @property
    def unique_id(self) -> Optional[str]:
        return f'sensor_driving_license_{self.driving_license.series}'

    @property
    def name_format_values(self) -> Mapping[str, Any]:
        return {
            **attr.asdict(self.driving_license, recurse=False),
            'identifier': self.driving_license.series,
        }

    @property
    def sensor_related_attributes(self) -> Optional[Dict[str, Any]]:
        if self.offenses:
            offenses = [
                offense_to_attributes(offense, with_document=False)
                for offense in self.offenses
            ]

        else:
            offenses = []

        return {
            ATTR_NUMBER: self.driving_license.series,
            ATTR_ISSUE_DATE: dt_to_str(self.driving_license.issue_date),
            ATTR_OFFENSES: offenses,
        }

    async def async_update(self) -> None:
        offenses = await self.driving_license.get_offenses()
        self.offenses = sorted(offenses, key=lambda x: x.date_issued or date.min, reverse=True)


class MoscowPGUVehicleSensor(MoscowPGUSensor):
    def __init__(self, *args, vehicle: Vehicle, offenses: Optional[Iterable['Offense']] = None, **kwargs):
        assert vehicle.id is not None, "init vehicle yields an empty id"

        super().__init__(*args, **kwargs)

        self.vehicle = vehicle
        self.offenses = []

        if offenses is not None:
            self.offenses.extend(offenses)

    @property
    def icon(self) -> Optional[str]:
        return 'mdi:car'

    @property
    def state(self) -> Union[str, float]:
        if self.vehicle.certificate_series:
            return -sum(map(lambda x: x.unpaid_amount or 0, self.offenses or []))
        return STATE_UNKNOWN

    @property
    def unit_of_measurement(self) -> Optional[str]:
        if self.vehicle.certificate_series:
            return UNIT_CURRENCY_RUSSIAN_ROUBLES

    @property
    def unique_id(self) -> Optional[str]:
        return f'sensor_vehicle_{self.vehicle.id}'

    @property
    def name_format_values(self) -> Mapping[str, Any]:
        return {
            **attr.asdict(self.vehicle, recurse=False),
            'identifier': self.vehicle.license_plate or self.vehicle.certificate_series or self.vehicle.id,
        }

    @property
    def sensor_related_attributes(self) -> Optional[Dict[str, Any]]:
        attributes = {
            ATTR_ID: self.vehicle.id,
            ATTR_LICENSE_PLATE: self.vehicle.license_plate,
            ATTR_CERTIFICATE_SERIES: self.vehicle.certificate_series,
        }

        if self.vehicle.certificate_series:
            if self.offenses:
                offenses = [
                    offense_to_attributes(offense, with_document=False)
                    for offense in self.offenses
                ]
            else:
                offenses = []

            attributes[ATTR_OFFENSES] = offenses

        return attributes

    async def async_update(self) -> None:
        certificate_series = self.vehicle.certificate_series
        if certificate_series:
            try:
                offenses = await self.vehicle.get_offenses()
            except MoscowPGUException as e:
                # do not break update completely, because API is unstable
                _LOGGER.error('Could not update vehicle offenses: %s', e)
            else:
                self.offenses.clear()
                self.offenses.extend(offenses)


class MoscowPGUFSSPDebtsSensor(MoscowPGUSensor):
    def __init__(self, *args, profile: Profile, fssp_debts: Optional[List[FSSPDebt]] = None, **kwargs):
        assert profile.first_name is not None, "init profile yields empty first name"
        assert profile.last_name is not None, "init profile yields empty last name"
        # assert profile.middle_name is not None, "init profile yields empty middle name"
        assert profile.birth_date is not None, "init profile yields empty birth date"

        super().__init__(*args, **kwargs)

        self.profile = profile
        self.fssp_debts = []

        if fssp_debts is not None:
            self.fssp_debts.extend(fssp_debts)

    @property
    def icon(self) -> Optional[str]:
        return 'mdi:gavel'

    @property
    def unit_of_measurement(self) -> Optional[str]:
        return UNIT_CURRENCY_RUSSIAN_ROUBLES

    @property
    def state(self) -> float:
        return -sum(map(lambda x: x.unpaid_amount or 0, self.fssp_debts))

    @property
    def unique_id(self) -> Optional[str]:
        hashkey = hashlib.md5(
            (
                    self.profile.full_name +
                    self.profile.birth_date.strftime('%Y-%m-%d')
            ).encode("utf-8")
        ).hexdigest()

        return f'sensor_fssp_debt_{hashkey}'

    @property
    def name_format_values(self) -> Mapping[str, Any]:
        return {
            **attr.asdict(self.profile, recurse=False),
            'identifier': self.profile.full_name,
        }

    @property
    def sensor_related_attributes(self) -> Optional[Dict[str, Any]]:
        return {
            ATTR_FIRST_NAME: self.profile.first_name,
            ATTR_LAST_NAME: self.profile.last_name,
            ATTR_MIDDLE_NAME: self.profile.middle_name,
            ATTR_BIRTH_DATE: dt_to_str(self.profile.birth_date),
            ATTR_DEBTS: [
                {
                    ATTR_ID: fssp_debt.id,
                    ATTR_ENTERPRENEUR_ID: fssp_debt.enterpreneur_id,
                    ATTR_DESCIPTION: fssp_debt.description,
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
            ]
        }

    async def async_update(self) -> None:
        fssp_debts = await self.profile.get_fssp_detailed()

        self.fssp_debts.clear()
        self.fssp_debts.extend(fssp_debts)


class MoscowPGUFlatSensor(MoscowPGUSensor):
    def __init__(self, *args, flat: Flat, epds: Optional[List[EPD]] = None, **kwargs):
        assert flat.id is not None, "init flat yields empty id"

        super().__init__(*args, **kwargs)

        self.flat = flat
        self.epds = []

        if epds is not None:
            self.epds.extend(epds)

    @property
    def icon(self) -> Optional[str]:
        return 'mdi:door'

    @property
    def state(self) -> Union[str, float]:
        if self.flat.epd_account:
            return -sum(map(lambda x: x.unpaid_amount or 0, self.epds or []))
        return STATE_UNKNOWN

    @property
    def unit_of_measurement(self) -> Optional[str]:
        if self.flat.epd_account:
            return UNIT_CURRENCY_RUSSIAN_ROUBLES

    @property
    def device_class(self) -> Optional[str]:
        return DEVICE_CLASS_PGU_INDICATIONS

    @property
    def unique_id(self) -> Optional[str]:
        return f'sensor_flat_{self.flat.id}'

    @property
    def name_format_values(self) -> Mapping[str, Any]:
        identifier = self.flat.name

        if not identifier:
            identifier = self.flat.address

            if self.flat.flat_number is not None:
                identifier += ' ' + str(self.flat.flat_number)

        return {
            **attr.asdict(self.flat, recurse=False),
            'identifier': identifier,
        }

    @property
    def sensor_related_attributes(self) -> Optional[Dict[str, Any]]:
        flat = self.flat

        attributes = {
            ATTR_ID: flat.id,
            ATTR_NAME: flat.name,
            ATTR_ADDRESS: flat.address,
            ATTR_FLAT_NUMBER: flat.flat_number,
            ATTR_ENTRANCE_NUMBER: flat.entrance_number,
            ATTR_FLOOR: flat.floor,
            ATTR_INTERCOM: flat.intercom,
            ATTR_PHONE_NUMBER: flat.phone_number,
            ATTR_EPD_ACCOUNT: flat.epd_account,
        }

        if flat.epd_account:
            epds = self.epds

            if epds:
                epds = [
                    {
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
                    for epd in sorted(epds, key=lambda x: x.period or date.min, reverse=True)
                ]

            attributes[ATTR_EPDS] = epds

        return attributes

    async def async_update(self) -> None:
        flat = self.flat

        if flat.epd_account:
            date_today = date.today()
            shift_months = 3
            if date_today.month <= shift_months:
                date_begin = date_today.replace(
                    day=1,
                    month=12 + date_today.month - shift_months,
                    year=date_today.year - 1
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
                _LOGGER.error('Could not fetch EPDs: %s', e)
            else:
                self.epds.clear()
                self.epds.extend(epds)

    async def async_push_indications(self, indications: List[float], force: bool = False, **kwargs) -> None:
        type_ = kwargs.get('type')

        try:
            if type_ is None:
                raise ValueError('Type is not provided (expected %s)' % ((TYPE_ELECTRIC, TYPE_WATER),))

            if type_ == TYPE_WATER:
                water_counters = await self.flat.get_water_counters()

                if not (force or water_counters):
                    raise ValueError('Water counters not present for given flat')

                if len(water_counters) != len(indications):
                    raise ValueError('Water counters count not equal to indications count (expected %d, got %d)' %
                                     (len(water_counters), len(indications)))

                if len(water_counters) > 2:
                    raise ValueError('Invalid water counters count for indications (expected %d, got %d)' %
                                     (2, len(water_counters)))

                existing_types = set()
                for water_counter in water_counters:
                    if water_counter.type is None or water_counter.type == WaterCounterType.UNKNOWN:
                        raise ValueError('Water counter "%s" has an unknown or '
                                         'unspecified type (expected %s, got %s)' %
                                         (water_counter.code,
                                          (WaterCounterType.HOT, WaterCounterType.COLD),
                                          water_counter.type))

                    elif water_counter.type in existing_types:
                        raise ValueError('Water counters with same types detected')

                    existing_types.add(water_counter.type)

                if len(water_counters) == 2:
                    if water_counters[0].type == WaterCounterType.COLD:
                        indications = reversed(indications)

                indications_dict = {}

                for indication, water_counter in zip(indications, water_counters):
                    last_indication = water_counter.last_indication
                    if last_indication and last_indication.indication and last_indication.indication > indication:
                        raise ValueError('New indication for %s water counter "%s" (%d) '
                                         'is less than its previous indication (%d)' %
                                         (water_counter.type.name,
                                          water_counter.code,
                                          indication,
                                          last_indication.indication))

                    indications_dict[water_counter.id] = indication

                try:
                    await self.flat.push_water_counter_indications(indications_dict, )

                except Exception as e:
                    _LOGGER.error('Failed to push water indications: %s', e)

                    for water_counter in water_counters:
                        if water_counter.id in indications_dict:
                            self.hass.bus.async_fire(
                                event_type=EVENT_WATER_INDICATIONS_PUSH_FAILED,
                                event_data={
                                    ATTR_TIME: dt_now(),
                                    ATTR_FLAT_ID: water_counter.flat_id,
                                    ATTR_COUNTER_ID: water_counter.id,
                                    ATTR_TYPE: water_counter.type.name.lower() if water_counter.type else None,
                                    ATTR_CODE: water_counter.code,
                                    ATTR_INDICATION: indications_dict[water_counter.id],
                                    ATTR_ENTITY_ID: self.entity_id,
                                    ATTR_REASON: str(e),
                                }
                            )

                    raise

                else:
                    _LOGGER.debug('Pushed water indications successfully')

                    for water_counter in water_counters:
                        if water_counter.id in indications_dict:
                            self.hass.bus.async_fire(
                                event_type=EVENT_WATER_INDICATIONS_PUSHED,
                                event_data={
                                    ATTR_TIME: dt_now(),
                                    ATTR_FLAT_ID: water_counter.flat_id,
                                    ATTR_COUNTER_ID: water_counter.id,
                                    ATTR_TYPE: water_counter.type.name.lower() if water_counter.type else None,
                                    ATTR_CODE: water_counter.code,
                                    ATTR_ENTITY_ID: self.entity_id,
                                    ATTR_INDICATION: indications_dict[water_counter.id],
                                }
                            )

            elif type_ == TYPE_ELECTRIC:
                electric_account = self.flat.electric_account

                if not electric_account.number:
                    raise ValueError('Flat does not have an electric account number set')

                if not electric_account.device:
                    raise ValueError('Flat does not have an electric account device set')

                try:
                    await self.flat.push_electric_indications(indications, )

                except Exception as e:
                    _LOGGER.error('Failed to push electric indications: %s', e)

                    electric_account = self.flat.electric_account

                    self.hass.bus.async_fire(
                        event_type=EVENT_ELECTRIC_INDICATIONS_PUSHED,
                        event_data={
                            ATTR_TIME: dt_now(),
                            ATTR_FLAT_ID: self.flat.flat_id,
                            ATTR_NUMBER: electric_account.number if electric_account else None,
                            ATTR_DEVICE: electric_account.device if electric_account else None,
                            ATTR_INDICATIONS: indications,
                            ATTR_REASON: str(e),
                            ATTR_ENTITY_ID: self.entity_id,
                        }
                    )

                    raise

                else:
                    _LOGGER.debug('Pushed electric indications successfully')

                    self.hass.bus.async_fire(
                        event_type=EVENT_WATER_INDICATIONS_PUSHED,
                        event_data={
                            ATTR_TIME: dt_now(),
                            ATTR_FLAT_ID: self.flat.flat_id,
                            ATTR_NUMBER: electric_account.number if electric_account else None,
                            ATTR_DEVICE: electric_account.device if electric_account else None,
                            ATTR_INDICATIONS: indications,
                            ATTR_ENTITY_ID: self.entity_id,
                        }
                    )

            else:
                raise ValueError('Invalid type provided (expected %s, got "%s")' % ((TYPE_ELECTRIC, TYPE_WATER), type_))

        except Exception as e:
            _LOGGER.error('Failed to push water indications: %s', e)

            self.hass.bus.async_fire(
                event_type=EVENT_FLAT_INDICATIONS_PUSH_FAILED,
                event_data={
                    ATTR_TIME: dt_now(),
                    ATTR_FLAT_ID: self.flat.flat_id,
                    ATTR_INDICATIONS: indications,
                    ATTR_TYPE: type_,
                    ATTR_REASON: str(e),
                }
            )

            raise

        else:
            _LOGGER.debug('Pushed flat indications successfully')

            self.hass.bus.async_fire(
                event_type=EVENT_FLAT_INDICATIONS_PUSHED,
                event_data={
                    ATTR_TIME: dt_now(),
                    ATTR_FLAT_ID: self.flat.flat_id,
                    ATTR_TYPE: type_,
                    ATTR_INDICATIONS: indications,
                }
            )


class MoscowPGUElectricCounterSensor(MoscowPGUSensor):
    def __init__(
            self,
            *args,
            flat: Flat,
            balance: Optional[ElectricBalance] = None,
            counter_info: Optional[ElectricCounterInfo] = None,
            indications_status: Optional[ElectricIndicationsStatus] = None,
            **kwargs
    ):
        assert flat.electric_account is not None, "init flat info data yields empty electric account"
        assert flat.id is not None, "init electric counter info data yields empty flat id"

        super().__init__(*args, **kwargs)

        self.flat = flat
        self.balance = balance
        self.counter_info = counter_info
        self.indications_status = indications_status

    @property
    def icon(self) -> str:
        return 'mdi:flash-circle'
    
    @property
    def unique_id(self) -> Optional[str]:
        return f'sensor_electric_counter_{self.flat.electric_account.number}'
    
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

    @property
    def device_class(self) -> str:
        return DEVICE_CLASS_PGU_INDICATIONS

    @property
    def name_format_values(self) -> Mapping[str, Any]:
        electric_account = self.flat.electric_account
        return {
            **attr.asdict(self.balance),
            'identifier': electric_account.number if electric_account else None,
            'account_number': electric_account.number if electric_account else None,
            'device_name': electric_account.device if electric_account else None,
        }

    @property
    def sensor_related_attributes(self) -> Dict[str, Any]:
        attributes = {ATTR_FLAT_ID: self.flat.id}

        if self.counter_info:
            info = self.counter_info

            zones = {}
            if info.zones:
                for zone in info.zones:
                    if not zone.name:
                        continue

                    periods = []
                    if zone.periods:
                        for period in periods:
                            periods.append(tuple(map(str, period)))

                    zones[zone.name.lower()] = {
                        ATTR_PERIODS: periods,
                        ATTR_TARIFF: periods
                    }

            attributes.update({
                ATTR_TYPE: info.type,
                ATTR_ZONES: zones,
            })

        if self.indications_status:
            status = self.indications_status

            attributes.update({
                ATTR_SUBMIT_AVAILABLE: not status.check_code,
                ATTR_STATUS: status.check_message,
                ATTR_VERIFICATION_DATE: dt_to_str(status.counter_verification_date),
                ATTR_STATE: status.counter_state,
                ATTR_WHOLE_PART_LENGTH: status.counter_whole_part_length,
                ATTR_DECIMAL_PART_LENGTH: status.counter_decimal_part_length,
            })

        if self.balance:
            balance = self.balance

            indications = {}
            if balance.indications:
                for indication in balance.indications:
                    if not indication.zone_name:
                        continue

                    periods = []
                    if indication.periods:
                        for period in indication.periods:
                            periods.append(tuple(map(str, period)))

                    indications[indication.zone_name.lower()] = {
                        ATTR_ZONE_NAME: indication.zone_name,
                        ATTR_INDICATION: indication.indication,
                        ATTR_TARIFF: indication.tariff,
                        ATTR_PERIODS: periods,
                    }
            
            attributes.update({
                ATTR_SUBMIT_BEGIN_DATE: dt_to_str(balance.submit_begin_date),
                ATTR_SUBMIT_END_DATE: dt_to_str(balance.submit_end_date),
                ATTR_SETTLEMENT_DATE: dt_to_str(balance.settlement_date),
                ATTR_DEBT_AMOUNT: balance.debt_amount,
                ATTR_PAYMENTS_AMOUNT: balance.payments_amount,
                ATTR_TRANSFER_AMOUNT: balance.transfer_amount,
                ATTR_CHARGES_AMOUNT: balance.charges_amount,
                ATTR_RETURNS_AMOUNT: balance.returns_amount,
                ATTR_BALANCE_MESSAGE: balance.balance_message,
                ATTR_INDICATIONS: indications,
            })

            if ATTR_SUBMIT_AVAILABLE not in attributes and balance.submit_begin_date and balance.submit_end_date:
                attributes[ATTR_SUBMIT_AVAILABLE] =\
                    balance.submit_begin_date <= date.today() <= balance.submit_end_date

        if ATTR_SUBMIT_AVAILABLE not in attributes:
            attributes[ATTR_SUBMIT_AVAILABLE] = False

        return attributes
    
    async def async_update(self) -> None:
        self.balance, self.counter_info, self.indications_status = await asyncio.gather(
            self.flat.get_electric_balance(),
            self.flat.get_electric_counter_info(),
            self.flat.get_electric_indications_status()
        )

    async def async_push_indications(self, indications: List[float], force: bool = False, **kwargs) -> None:
        type_ = kwargs.get('type')
        electric_account = self.flat.electric_account

        try:
            if type_ is not None and type_ != TYPE_ELECTRIC:
                raise ValueError('Invalid type selected (expected "%s", got "%s")' % (TYPE_ELECTRIC, type_))

            if len(indications) < 1:
                raise ValueError('Insufficient indications provided (expected 1, got 0)')

            if self.counter_info and self.counter_info.zones:
                if len(self.counter_info.zones) != len(indications):
                    raise ValueError('Too many indications provided (expected 1, got %d)' % (len(indications),))

            elif not force:
                raise ValueError('Entity did not receive counter info (cannot enforce check on indications count)')

            await self.flat.push_electric_indications(indications, perform_checks=not force)

        except Exception as e:
            _LOGGER.error('Failed to push electric indications: %s', e)

            self.hass.bus.async_fire(
                event_type=EVENT_ELECTRIC_INDICATIONS_PUSHED,
                event_data={
                    ATTR_TIME: dt_now(),
                    ATTR_FLAT_ID: self.flat.flat_id,
                    ATTR_NUMBER: electric_account.number if electric_account else None,
                    ATTR_DEVICE: electric_account.device if electric_account else None,
                    ATTR_INDICATIONS: indications,
                    ATTR_REASON: str(e),
                }
            )

            raise

        else:
            _LOGGER.debug('Pushed electric indications successfully')

            self.hass.bus.async_fire(
                event_type=EVENT_WATER_INDICATIONS_PUSHED,
                event_data={
                    ATTR_TIME: dt_now(),
                    ATTR_FLAT_ID: self.flat.flat_id,
                    ATTR_NUMBER: electric_account.number if electric_account else None,
                    ATTR_DEVICE: electric_account.device if electric_account else None,
                    ATTR_INDICATIONS: indications,
                }
            )


def get_remove_tasks(hass: HomeAssistantType, entities: Iterable[Entity]) -> List[asyncio.Task]:
    tasks = []

    for entity in entities:
        if entity.hass is None:
            entity.hass = hass
        tasks.append(
            hass.async_create_task(
                entity.async_remove()
            )
        )

    return tasks


@wrap_entities_updater(MoscowPGUFSSPDebtsSensor, CONF_FSSP_DEBTS, DEFAULT_SCAN_INTERVAL_FSSP_DEBTS)
async def async_discover_fssp_debts(hass: HomeAssistantType,
                                    config_entry: ConfigEntry,
                                    config: ConfigType,
                                    existing_entities: Mapping[Type[TSensor], List[TSensor]],
                                    profile: Profile) -> DiscoveryReturnType:
    entities = []
    tasks = []
    name_format = config.get(CONF_NAME_FORMAT, {}).get(CONF_FSSP_DEBTS, DEFAULT_NAME_FORMAT_FSSP_DEBTS)

    fssp_debts_entities: Set[MoscowPGUFSSPDebtsSensor] = set(existing_entities.get(MoscowPGUFSSPDebtsSensor, []))

    profiles = [profile]
    additional_config = config.get(CONF_TRACK_FSSP_PROFILES, [])

    if additional_config:
        for additional_config_item in additional_config:
            birth_date = additional_config_item.get(CONF_ISSUE_DATE)

            if not (birth_date is None or isinstance(birth_date, date)):
                birth_date = cv.date(birth_date)

            for profile in profiles:
                if profile.first_name == additional_config_item[CONF_FIRST_NAME] and \
                        profile.last_name == additional_config_item[CONF_LAST_NAME] and \
                        profile.middle_name == additional_config_item.get(CONF_MIDDLE_NAME) and \
                        profile.birth_date == birth_date:
                    _LOGGER.warning('FSSP debts profile ("%s (%s)") duplication detected',
                                    profile.full_name, profile.birth_date)
                    continue

            profiles.append(
                Profile(
                    api=profile.api,
                    first_name=additional_config_item[CONF_FIRST_NAME],
                    last_name=additional_config_item[CONF_LAST_NAME],
                    middle_name=additional_config_item.get(CONF_MIDDLE_NAME),
                    birth_date=additional_config_item[CONF_BIRTH_DATE]
                )
            )

    for profile in profiles:
        fssp_debts_entity = None

        for entity in fssp_debts_entities:
            fssp_debts_entity_profile = entity.profile
            if entity.profile.first_name == fssp_debts_entity_profile.first_name and \
                    entity.profile.last_name == fssp_debts_entity_profile.last_name and \
                    entity.profile.middle_name == fssp_debts_entity_profile.middle_name and \
                    entity.profile.birth_date == fssp_debts_entity_profile.birth_date:
                fssp_debts_entity = entity
                break

        if fssp_debts_entity is None:
            entities.append(MoscowPGUFSSPDebtsSensor(name_format=name_format, profile=profile))
        else:
            fssp_debts_entities.remove(fssp_debts_entity)
            if fssp_debts_entity.enabled:
                fssp_debts_entity.profile = profile
                fssp_debts_entity.name_format = name_format
                fssp_debts_entity.async_schedule_update_ha_state(force_refresh=True)

    # All non-found entities will get removed
    tasks.extend(get_remove_tasks(hass, fssp_debts_entities))

    return entities, tasks


@wrap_entities_updater(MoscowPGUWaterCounterSensor, CONF_WATER_COUNTERS, DEFAULT_SCAN_INTERVAL_WATER_COUNTERS)
async def async_discover_water_counters(hass: HomeAssistantType,
                                        config_entry: ConfigEntry,
                                        config: ConfigType,
                                        existing_entities: Mapping[Type[TSensor], List[TSensor]],
                                        flats: List[Flat]) -> DiscoveryReturnType:
    entities = []
    tasks = []
    name_format = config.get(CONF_NAME_FORMAT, {}).get(CONF_WATER_COUNTERS, DEFAULT_NAME_FORMAT_WATER_COUNTERS)

    added_entities: Set[MoscowPGUWaterCounterSensor] = set(existing_entities.get(MoscowPGUWaterCounterSensor, []))

    if flats:
        for flat in flats:
            water_counters = await flat.get_water_counters()

            for water_counter in water_counters:
                water_counter_entity = None

                for entity in added_entities:
                    if entity.water_counter.id == water_counter.id:
                        water_counter_entity = entity
                        break

                if water_counter_entity is None:
                    entities.append(
                        MoscowPGUWaterCounterSensor(
                            name_format=name_format,
                            water_counter=water_counter
                        )
                    )

                else:
                    added_entities.remove(water_counter_entity)
                    if water_counter_entity.enabled:
                        water_counter_entity.water_counter = water_counter
                        water_counter_entity.name_format = name_format
                        water_counter_entity.async_schedule_update_ha_state(force_refresh=False)

    tasks.extend(get_remove_tasks(hass, added_entities))

    return entities, tasks


@wrap_entities_updater(MoscowPGUElectricCounterSensor, CONF_ELECTRIC_COUNTERS, DEFAULT_SCAN_INTERVAL_ELECTRIC_COUNTERS)
async def async_discover_electric_counters(hass: HomeAssistantType,
                                           config_entry: ConfigEntry,
                                           config: ConfigType,
                                           existing_entities: Mapping[Type[TSensor], List[TSensor]],
                                           flats: List[Flat]):
    entities = []
    tasks = []
    name_format = config.get(CONF_NAME_FORMAT, {}).get(CONF_ELECTRIC_COUNTERS, DEFAULT_NAME_ELECTRIC_COUNTERS)

    added_entities: Set[MoscowPGUElectricCounterSensor] = set(existing_entities.get(MoscowPGUElectricCounterSensor, []))

    if flats:
        for flat in flats:
            if flat.electric_account is None:
                continue

            electric_counter_entity = None

            for entity in added_entities:
                if entity.flat.electric_account == flat.electric_account:
                    electric_counter_entity = entity
                    break

            if electric_counter_entity is None:
                entities.append(
                    MoscowPGUElectricCounterSensor(
                        name_format=name_format,
                        flat=flat
                    )
                )
            else:
                added_entities.remove(electric_counter_entity)
                if electric_counter_entity.enabled:
                    electric_counter_entity.flat = flat
                    electric_counter_entity.name_format = name_format
                    electric_counter_entity.async_schedule_update_ha_state(force_refresh=True)

    tasks.extend(get_remove_tasks(hass, added_entities))

    return entities, tasks


@wrap_entities_updater(MoscowPGUFlatSensor, CONF_FLATS, DEFAULT_SCAN_INTERVAL_FLATS)
async def async_discover_flats(hass: HomeAssistantType,
                               config_entry: ConfigEntry,
                               config: ConfigType,
                               existing_entities: Mapping[Type[TSensor], List[TSensor]],
                               flats: List[Flat]) -> DiscoveryReturnType:
    entities = []
    tasks = []
    name_format = config.get(CONF_NAME_FORMAT, {}).get(CONF_FLATS, DEFAULT_NAME_FORMAT_FLATS)

    added_entities: Set[MoscowPGUFlatSensor] = set(existing_entities.get(MoscowPGUFlatSensor, []))

    for flat in flats:
        flat_entity = None

        for entity in added_entities:
            if entity.flat.id == flat.id:
                flat_entity = entity
                break

        if flat_entity is None:
            entities.append(
                MoscowPGUFlatSensor(
                    name_format=name_format,
                    flat=flat
                )
            )
        else:
            added_entities.remove(flat_entity)
            if flat_entity.enabled:
                flat_entity.flat = flat
                flat_entity.name_format = name_format
                flat_entity.async_schedule_update_ha_state(force_refresh=True)

    tasks.extend(get_remove_tasks(hass, added_entities))

    return entities, tasks


@wrap_entities_updater(MoscowPGUVehicleSensor, CONF_VEHICLES, DEFAULT_SCAN_INTERVAL_VEHICLES)
async def async_discover_vehicles(hass: HomeAssistantType,
                                  config_entry: ConfigEntry,
                                  config: ConfigType,
                                  existing_entities: Mapping[Type[TSensor], List[TSensor]],
                                  vehicles: List[Vehicle]) -> DiscoveryReturnType:
    entities = []
    tasks = []
    name_format = config.get(CONF_NAME_FORMAT, {}).get(CONF_VEHICLES, DEFAULT_NAME_FORMAT_VEHICLES)

    added_entities: Set[MoscowPGUVehicleSensor] = set(existing_entities.get(MoscowPGUVehicleSensor, []))

    for vehicle in vehicles:
        vehicle_entity = None

        for entity in added_entities:
            if entity.vehicle.id == vehicle.id:
                vehicle_entity = entity
                break

        if vehicle_entity is None:
            entities.append(
                MoscowPGUVehicleSensor(
                    name_format=name_format,
                    vehicle=vehicle,
                )
            )

        else:
            added_entities.remove(vehicle_entity)
            if vehicle_entity.enabled:
                vehicle_entity.vehicle = vehicle
                vehicle_entity.name_format = name_format
                vehicle_entity.async_schedule_update_ha_state(force_refresh=True)

    tasks.extend(get_remove_tasks(hass, added_entities))

    return entities, tasks


@wrap_entities_updater(MoscowPGUDrivingLicenseSensor, CONF_DRIVING_LICENSES, DEFAULT_SCAN_INTERVAL_DRIVING_LICENSES)
async def async_discover_driving_licenses(hass: HomeAssistantType,
                                          config_entry: ConfigEntry,
                                          config: ConfigType,
                                          existing_entities: Mapping[Type[TSensor], List[TSensor]],
                                          profile: Profile) -> DiscoveryReturnType:
    tasks = []
    entities = []
    name_format = config.get(CONF_NAME_FORMAT, {}).get(CONF_DRIVING_LICENSES, DEFAULT_NAME_FORMAT_DRIVING_LICENSES)

    added_entities: Set[MoscowPGUDrivingLicenseSensor] = set(existing_entities.get(MoscowPGUDrivingLicenseSensor, []))

    driving_licenses = []
    if profile.driving_license:
        driving_licenses.append(profile.driving_license)
    else:
        for i in range(10):
            _LOGGER.error('No driving license on %s', profile)

    additional_config = config.get(CONF_DRIVING_LICENSES, [])

    if additional_config:
        for additional_config_item in additional_config:
            driving_license_series = additional_config_item[CONF_SERIES]

            for driving_license in driving_licenses:
                if driving_license.series == driving_license_series:
                    _LOGGER.warning('Driving license number ("%s") duplication detected', driving_license_series)
                    continue

            driving_license_issue_date = additional_config_item.get(CONF_ISSUE_DATE)

            if not (driving_license_issue_date is None or isinstance(driving_license_issue_date, date)):
                driving_license_issue_date = cv.date(driving_license_issue_date)

            driving_licenses.append(
                DrivingLicense(
                    api=profile.api,
                    series=driving_license_series,
                    issue_date=driving_license_issue_date
                )
            )

    for driving_license in driving_licenses:
        driving_license_entity = None

        for entity in added_entities:
            if entity.driving_license.series == driving_license.series:
                driving_license_entity = entity
                break

        if driving_license_entity is None:
            entities.append(MoscowPGUDrivingLicenseSensor(name_format=name_format, driving_license=driving_license))
        else:
            added_entities.remove(driving_license_entity)
            if driving_license_entity.enabled:
                driving_license_entity.driving_license = driving_license
                driving_license_entity.name_format = name_format
                driving_license_entity.async_schedule_update_ha_state(force_refresh=True)

    tasks.extend(get_remove_tasks(hass, added_entities))

    return entities, tasks


@wrap_entities_updater(MoscowPGUProfileSensor, CONF_PROFILE, DEFAULT_SCAN_INTERVAL_PROFILE)
async def async_discover_profile(hass: HomeAssistantType,
                                 config_entry: ConfigEntry,
                                 config: ConfigType,
                                 existing_entities: Mapping[Type[TSensor], List[TSensor]],
                                 profile: Profile) -> DiscoveryReturnType:
    tasks = []
    entities = []
    name_format = config.get(CONF_NAME_FORMAT, {}).get(CONF_PROFILE, DEFAULT_NAME_FORMAT_PROFILE)

    added_entities: List[MoscowPGUProfileSensor] = existing_entities.get(MoscowPGUProfileSensor, [])

    profile_entity = None

    for entity in added_entities:
        if profile_entity is not None:
            # There is a duplicate entity involved (never happened, but still...)
            tasks.append(hass.async_create_task(entity.async_remove()))
            continue

        elif entity.enabled:
            entity.profile = profile
            entity.async_schedule_update_ha_state(force_refresh=False)

        profile_entity = entity

    if profile_entity is None:
        entities.append(MoscowPGUProfileSensor(name_format=name_format, profile=profile))

    return entities, tasks


async def async_discover_entities(hass: HomeAssistantType,
                                  config_entry: ConfigEntry,
                                  config: ConfigType,
                                  existing_entities: Mapping[Type[TSensor], List[TSensor]],
                                  api: API) -> DiscoveryReturnType:
    # Prepare necessary data
    profile, vehicles, flats = await asyncio.gather(api.get_profile(), api.get_vehicles(), api.get_flats())
    common_args = (hass, config_entry, config, existing_entities)

    # Perform parallel discovery tasks
    new_entities_and_tasks_pairs = await asyncio.gather(
        async_discover_profile(*common_args, profile),
        async_discover_driving_licenses(*common_args, profile),
        async_discover_water_counters(*common_args, flats),
        async_discover_vehicles(*common_args, vehicles),
        async_discover_flats(*common_args, flats),
        async_discover_electric_counters(*common_args, flats),
        async_discover_fssp_debts(*common_args, profile)
    )

    # Finalize tasks and add entities
    entities = []
    tasks = []
    for add_new_entities, add_tasks in new_entities_and_tasks_pairs:
        entities.extend(add_new_entities)
        tasks.extend(add_tasks)

    return entities, tasks


async def async_setup_entry(
        hass: HomeAssistantType,
        config_entry: ConfigEntry,
        async_add_devices: Callable[[Iterable['Entity'], bool], None],
):
    config = extract_config(hass, config_entry)
    username = config[CONF_USERNAME]

    # Prepare necessary arguments
    api: API = hass.data[DOMAIN][username]
    existing_entities: Dict[Type[TSensor], List[TSensor]] =\
        get_entities(hass, config_entry.entry_id)

    entities, tasks = \
        await async_discover_entities(hass, config_entry, config, existing_entities, api)
    
    if tasks:
        await asyncio.wait(tasks, return_when=asyncio.ALL_COMPLETED)

    if entities:
        discovery_sensors = []
        regular_sensors = []

        for entity in entities:
            if isinstance(entity, MoscowPGUDiscoverySensor):
                discovery_sensors.append(entity)
            else:
                regular_sensors.append(entity)

        if discovery_sensors:
            async_add_devices(discovery_sensors, False)

        if regular_sensors:
            async_add_devices(regular_sensors, True)

    platform = entity_platform.current_platform.get()

    # Register indication pushing service
    platform.async_register_entity_service(
        SERVICE_PUSH_INDICATION,
        SERVICE_PUSH_INDICATION_SCHEMA,
        "async_push_indications"
    )

    _LOGGER.debug('Finished sensor component setup for user "%s"', username)
