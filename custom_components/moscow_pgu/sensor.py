import asyncio
import logging
from datetime import timedelta, date, time, datetime
from typing import Type, Mapping, Optional, List, Any, Dict, Union, Callable, Coroutine, Tuple

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, SOURCE_IMPORT
from homeassistant.const import CONF_SCAN_INTERVAL, CONF_USERNAME, ATTR_ID, ATTR_CODE, STATE_UNKNOWN, STATE_OK, \
    ATTR_ATTRIBUTION, ATTR_DEVICE_CLASS
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import HomeAssistantType, StateType

from custom_components.moscow_pgu import API, DATA_UPDATERS, DATA_CONFIG, DOMAIN, DEFAULT_SCAN_INTERVAL_WATER_COUNTERS, \
    CONF_WATER_COUNTERS, DATA_ENTITIES, CONF_PROFILE, DEFAULT_SCAN_INTERVAL_PROFILE, CONF_VEHICLES, \
    DEFAULT_SCAN_INTERVAL_VEHICLES
from custom_components.moscow_pgu.moscow_pgu_api import WaterCounter, MoscowPGUException, Profile, Offense, Vehicle, \
    ResponseDataClassWithID

_LOGGER = logging.getLogger(__name__)

_SensorType = 'MoscowPGUSensor'


ATTR_TYPE = 'type'
ATTR_FLAT_ID = 'flat_id'
ATTR_INDICATIONS = 'indications'
ATTR_LAST_INDICATION = 'last_indication'
ATTR_CHECKUP_DATE = 'checkup_date'
ATTR_PERIOD = 'period'
ATTR_INDICATION = 'indication'
ATTR_FIRST_NAME = 'first_name'
ATTR_LAST_NAME = 'last_name'
ATTR_MIDDLE_NAME = 'middle_name'
ATTR_BIRTH_DATE = 'birth_date'
ATTR_PHONE_NUMBER = 'phone_number'
ATTR_EMAIL = 'email'
ATTR_EMAIL_CONFIRMED = 'email_confirmed'
ATTR_DRIVING_LICENSE_NUMBER = 'driving_license_number'
ATTR_DRIVING_LICENSE_ISSUE_DATE = 'driving_license_issue_date'
ATTR_ISSUE_DATE = 'issue_date'
ATTR_COMMITTED_AT = 'committed_at'
ATTR_ARTICLE_TITLE = 'article_title'
ATTR_LOCATION = 'location'
ATTR_PENALTY = 'penalty'
ATTR_STATUS = 'status'
ATTR_STATUS_RNIP = 'status_rnip'
ATTR_DISCOUNT_DATE = 'discount_date'
ATTR_POLICE_UNIT_CODE = 'police_unit_code'
ATTR_POLICE_UNIT_NAME = 'police_unit_name'
ATTR_PHOTO_URL = 'photo_url'
ATTR_UNPAID_AMOUNT = 'unpaid_amount'
ATTR_STATUS_TEXT = 'status_text'
ATTR_DOCUMENT_TYPE = 'document_type'
ATTR_DOCUMENT_SERIES = 'document_series'
ATTR_OFFENSES = 'offenses'
ATTR_NUMBER = 'number'
ATTR_LAST_OFFENSE = 'last_offense'
ATTR_LICENSE_PLATE = 'license_plate'
ATTR_CERTIFICATE_SERIES = 'certificate_series'
ATTR_FORCE = 'force'


SERVICE_PUSH_INDICATION = 'push_indication'
SERVICE_PUSH_INDICATION_SCHEMA = {
    vol.Required(ATTR_INDICATION): cv.positive_float,
    vol.Optional(ATTR_FORCE, default=False): cv.boolean,
}


def create_entity_updater(
        hass: HomeAssistantType,
        config_entry: ConfigEntry,
        updater: Callable[[List[_SensorType]], Coroutine[Any, Any, Any]],
        scan_interval: timedelta,
        entity_cls: Type[_SensorType]
) -> Callable[[], Any]:
    """Create updater with given time interval for entity class"""
    entry_id = config_entry.entry_id

    updaters = hass.data.setdefault(DATA_UPDATERS, {}).setdefault(entry_id, {})
    if entity_cls in updaters:
        _LOGGER.debug('Existing updater for %s encountered, removing', entity_cls.__name__)
        updaters.pop(entity_cls)()

    async def _async_update_entities(*_):
        entities = hass.data.get(DATA_ENTITIES, {}).get(entry_id, {}).get(entity_cls, [])
        if not entities:
            _LOGGER.debug('No %s entities to update, skipping...', entity_cls.__name__)
            return

        _LOGGER.debug('Running %s entity updater', entity_cls.__name__)

        try:
            await updater(entities)

        except MoscowPGUException as e:
            _LOGGER.error('API error encountered: %s', e)
        except Exception as e:
            _LOGGER.exception('Error encountered: %s', e)

    cancel_callback = async_track_time_interval(hass, _async_update_entities, scan_interval)
    setattr(cancel_callback, 'force_update', _async_update_entities)

    updaters[entity_cls] = cancel_callback

    return cancel_callback


async def _async_create_id_entities(
        hass: HomeAssistantType,
        from_objects: List[ResponseDataClassWithID],
        with_cls: Type['MoscowPGUSensor'],
        with_attr: str,
        with_entities: Optional[List['MoscowPGUSensor']],
        async_add_entities: Optional[Callable[[List['MoscowPGUSensor']], Any]] = None
) -> Tuple[List['MoscowPGUSensor'], List['MoscowPGUSensor']]:
    obj_ids = list(map(lambda x: x.id, from_objects))
    existing_entities = []
    tasks = []
    for entity in with_entities:
        if getattr(entity, with_attr).id not in obj_ids:
            tasks.append(hass.async_create_task(entity.async_remove()))
        else:
            existing_entities.append(entity)

    new_entities = []
    for obj in from_objects:
        entity = None
        for existing_entity in existing_entities:
            if getattr(existing_entity, with_attr).id == obj.id:
                entity = existing_entity
                break

        if entity is None:
            # noinspection PyArgumentList
            entity = with_cls(obj)
            new_entities.append(entity)
        else:
            setattr(entity, with_attr, obj)
            if async_add_entities is not None:
                entity.async_schedule_update_ha_state()

    if tasks:
        await asyncio.wait(tasks)

    if async_add_entities is not None and new_entities:
        async_add_entities(new_entities)

    return new_entities, existing_entities


async def async_setup_water_counters(
        hass: HomeAssistantType,
        config_entry: ConfigEntry,
        async_add_devices: Callable,
        api: API,
        scan_interval: Optional[Union[timedelta, Mapping[str, timedelta]]] = None,
        session: Optional[aiohttp.ClientSession] = None,
) -> None:
    if isinstance(scan_interval, Mapping):
        scan_interval = scan_interval.get(CONF_WATER_COUNTERS)

    if scan_interval is None:
        scan_interval = DEFAULT_SCAN_INTERVAL_WATER_COUNTERS

    async def _entity_updater(entities: List[MoscowPGUWaterCounterSensor]):
        flats = await api.get_flats(session=session)

        water_counters = []
        for flat in flats:
            water_counters.extend(await flat.get_water_counters())

        await _async_create_id_entities(
            hass=hass,
            from_objects=water_counters,
            with_cls=MoscowPGUWaterCounterSensor,
            with_attr='water_counter',
            with_entities=entities,
            async_add_entities=async_add_devices,
        )

    # Perform initial update
    await _entity_updater([])

    create_entity_updater(hass, config_entry, _entity_updater, scan_interval, MoscowPGUWaterCounterSensor)

    # Register water counter-related services
    platform = entity_platform.current_platform.get()

    platform.async_register_entity_service(
        SERVICE_PUSH_INDICATION,
        SERVICE_PUSH_INDICATION_SCHEMA,
        "async_push_indication"
    )


async def async_setup_profile(
        hass: HomeAssistantType,
        config_entry: ConfigEntry,
        async_add_devices: Callable,
        api: API,
        scan_interval: Optional[Union[timedelta, Mapping[str, timedelta]]] = None,
        session: Optional[aiohttp.ClientSession] = None
) -> None:
    if isinstance(scan_interval, Mapping):
        scan_interval = scan_interval.get(CONF_PROFILE)

    if scan_interval is None:
        scan_interval = DEFAULT_SCAN_INTERVAL_PROFILE

    async def _entity_updater(entities: List[MoscowPGUProfileSensor]):
        profile = await api.get_profile(session=session)

        new_entities = []
        tasks = []
        driving_license_offenses = None
        if profile.driving_license_number:
            for i in range(1, 2):
                try:
                    driving_license_offenses = await profile.get_driving_license_offenses()
                    break
                except MoscowPGUException:
                    _LOGGER.warning('Could not fetch driving license offenses, attempt %d', i)

            driving_license_entities: List[MoscowPGUDrivingLicenseSensor] = hass.data\
                .get(DATA_ENTITIES, {})\
                .get(config_entry.entry_id, {})\
                .get(MoscowPGUDrivingLicenseSensor, [])

            driving_license_entity = None
            for entity in driving_license_entities:
                if entity.profile.driving_license_number == profile.driving_license_number:
                    driving_license_entity = entity
                else:
                    tasks.append(hass.async_create_task(entity.async_remove()))

            if driving_license_entity:
                if driving_license_offenses is not None:
                    driving_license_entity.offenses = driving_license_offenses
                    driving_license_entity.async_schedule_update_ha_state()

            else:
                driving_license_entity = MoscowPGUDrivingLicenseSensor(profile, offenses=driving_license_offenses)
                new_entities.append(driving_license_entity)

        if tasks:
            await asyncio.wait(tasks)

        if entities:
            entity = entities[0]
            entity.profile = profile
            entity.async_schedule_update_ha_state()
        else:
            entity = MoscowPGUProfileSensor(profile)
            new_entities.append(entity)

        if new_entities:
            async_add_devices(new_entities)

    # Perform initial update
    await _entity_updater([])

    create_entity_updater(hass, config_entry, _entity_updater, scan_interval, MoscowPGUProfileSensor)


async def async_setup_vehicles(
        hass: HomeAssistantType,
        config_entry: ConfigEntry,
        async_add_devices: Callable,
        api: API,
        scan_interval: Optional[Union[timedelta, Mapping[str, timedelta]]] = None,
        session: Optional[aiohttp.ClientSession] = None,
) -> None:
    if isinstance(scan_interval, Mapping):
        scan_interval = scan_interval.get(CONF_VEHICLES)

    if scan_interval is None:
        scan_interval = DEFAULT_SCAN_INTERVAL_VEHICLES

    async def _entity_updater(entities: List[MoscowPGUVehicleSensor]):
        vehicles = await api.get_vehicles(session=session)

        new_entities, existing_entities = await _async_create_id_entities(
            hass=hass,
            from_objects=vehicles,
            with_cls=MoscowPGUVehicleSensor,
            with_attr='vehicle',
            with_entities=entities,
        )

        if new_entities or existing_entities:
            fetch_entities = []
            fetch_tasks = []

            for vehicle in [*new_entities, *existing_entities]:
                vehicle: MoscowPGUVehicleSensor
                if vehicle.vehicle.certificate_series:
                    fetch_entities.append(vehicle)
                    fetch_tasks.append(hass.async_create_task(vehicle.vehicle.get_offenses()))

            await asyncio.wait(fetch_tasks, return_when=asyncio.ALL_COMPLETED)

            for entity, task in zip(fetch_entities, fetch_tasks):
                try:
                    entity.offenses = await task.result()
                except MoscowPGUException as task_exc:
                    _LOGGER.error('Error while fetching offenses for vehicle "%s": %s', entity, task_exc)

            if new_entities:
                async_add_devices(new_entities)

            if existing_entities:
                for entity in existing_entities:
                    entity.async_schedule_update_ha_state()

    # Perform initial update
    await _entity_updater([])

    create_entity_updater(hass, config_entry, _entity_updater, scan_interval, MoscowPGUVehicleSensor)


async def async_setup_fssp_debts(
        hass: HomeAssistantType,
        config_entry: ConfigEntry,
        async_add_devices: Callable,
        api: API,
        scan_interval: Optional[Union[timedelta, Mapping[str, timedelta]]] = None,
        session: Optional[aiohttp.ClientSession] = None
) -> None:
    # @TODO
    pass


async def async_setup_entry(hass: HomeAssistantType, config_entry: ConfigEntry, async_add_devices) -> None:
    user_cfg = {**config_entry.data}
    username = user_cfg[CONF_USERNAME]

    _LOGGER.debug('Setting up entry for username "%s" from sensors', username)

    if config_entry.source == SOURCE_IMPORT:
        user_cfg = hass.data[DATA_CONFIG].get(username)
        scan_interval = user_cfg.get(CONF_SCAN_INTERVAL)

    elif config_entry.options and CONF_SCAN_INTERVAL in config_entry.options:
        scan_interval = config_entry.options[CONF_SCAN_INTERVAL]

        if isinstance(scan_interval, Mapping):
            scan_interval = dict(map(lambda x: (x[0], None if x[1] is None else timedelta(seconds=x[1])), scan_interval))
        elif isinstance(scan_interval, (int, float)):
            scan_interval = timedelta(seconds=scan_interval)

    else:
        scan_interval = user_cfg.get(CONF_SCAN_INTERVAL)

    api_object: API = hass.data[DOMAIN][username]

    for func in [async_setup_profile, async_setup_water_counters, async_setup_vehicles]:
        try:
            await func(hass, config_entry, async_add_devices, api_object, scan_interval)
        except MoscowPGUException as e:
            _LOGGER.exception('Could not set up %s: %s', func.__name__.replace('async_setup_', '').replace('_', ' '), e)

    _LOGGER.debug('Finished sensor component setup for user "%s"', username)


def dt_to_str(dt: Optional[Union[date, time, datetime]]) -> Optional[str]:
    if dt is not None:
        return dt.isoformat()


def offense_to_attributes(offense: Offense, with_document: bool = True):
    attrs = {
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
        attrs.update({
            ATTR_DOCUMENT_TYPE: offense.document_type,
            ATTR_DOCUMENT_SERIES: offense.document_series,
        })

    return attrs


class MoscowPGUSensor(Entity):
    @property
    def should_poll(self) -> bool:
        return False

    async def async_added_to_hass(self) -> None:
        entities = self.hass.data\
            .setdefault(DATA_ENTITIES, {})\
            .setdefault(self.registry_entry.config_entry_id, {})\
            .setdefault(self.__class__, [])

        if self not in entities:
            # @TODO: this might not be required
            _LOGGER.debug('Adding "%s" entity to %s / %s registry',
                          self, self.registry_entry.config_entry_id, self.__class__.__name__)
            entities.append(self)

    async def async_will_remove_from_hass(self) -> None:
        entities = self.hass.data \
            .setdefault(DATA_ENTITIES, {}) \
            .setdefault(self.registry_entry.config_entry_id, {}) \
            .setdefault(self.__class__, [])

        if self in entities:
            # @TODO: this might not be required
            _LOGGER.debug('Will remove "%s" entity from %s / %s registry',
                          self, self.registry_entry.config_entry_id, self.__class__.__name__)
            entities.remove(self)

    @property
    def device_state_attributes(self) -> Optional[Dict[str, Any]]:
        _device_state_attributes = self._device_state_attributes or {}
        _device_state_attributes.setdefault(ATTR_ATTRIBUTION, 'Data provided by Moscow PGU')

        if ATTR_DEVICE_CLASS not in _device_state_attributes:
            device_class = self.device_class
            if device_class is not None:
                _device_state_attributes[ATTR_DEVICE_CLASS] = device_class

        return _device_state_attributes

    @property
    def _device_state_attributes(self) -> Optional[Dict[str, Any]]:
        return None


class MoscowPGUWaterCounterSensor(MoscowPGUSensor):
    def __init__(self, water_counter: WaterCounter):
        if not water_counter.id:
            raise ValueError('cannot create water counter sensor without water counter ID')
        if not water_counter.flat_id:
            raise ValueError('cannot create water counter sensor without flat ID')

        self.water_counter = water_counter

    @property
    def device_class(self) -> str:
        return 'meter'

    @property
    def icon(self) -> Optional[str]:
        return 'mdi:counter'

    @property
    def name(self) -> Optional[str]:
        water_counter_type = self.water_counter.type
        water_counter_text = water_counter_type.name.title() + ' ' if water_counter_type else ''

        water_counter_text += 'Water Counter'

        water_counter_code = self.water_counter.code
        water_counter_text += ' ' + str(water_counter_code) if water_counter_code else ''
        return water_counter_text

    @property
    def unique_id(self) -> Optional[str]:
        return f'sensor_water_counter_{self.water_counter.flat_id}_{self.water_counter.id}'

    @property
    def unit_of_measurement(self) -> Optional[str]:
        return 'm\u00b3'

    @property
    def state(self) -> StateType:
        last_indication = self.water_counter.last_indication

        if last_indication:
            current_month_start = date.today().replace(day=1)
            if last_indication.period >= current_month_start:
                return last_indication.indication

        return STATE_UNKNOWN

    @property
    def _device_state_attributes(self) -> Optional[Dict[str, Any]]:
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
            last_indication = {
                ATTR_PERIOD: last_indication.period.isoformat(),
                ATTR_INDICATION: last_indication.indication,
            }

        return {
            ATTR_ID: self.water_counter.id,
            ATTR_CODE: self.water_counter.code,
            ATTR_TYPE: water_counter_type,
            ATTR_INDICATIONS: indications,
            ATTR_LAST_INDICATION: last_indication,
            ATTR_CHECKUP_DATE: dt_to_str(self.water_counter.checkup_date),
            ATTR_FLAT_ID: self.water_counter.flat_id,
        }

    async def async_push_indication(self, indication: float, force: bool = False) -> bool:
        last_indication = self.water_counter.last_indication

        if not (force or last_indication is None or last_indication.indication is None):
            if indication <= last_indication.indication:
                _LOGGER.error('New indication is less than or equal to old indication value (%s <= %s)',
                              indication, last_indication.indication)
                return False

        try:
            await self.water_counter.push_water_counter_indication(indication)
            _LOGGER.debug('Succesfully pushed indication %s for [%s]', indication, self.entity_id)
            updater = self.hass.data.get(DATA_UPDATERS, {}).get(self.registry_entry.config_entry_id, {}).get(self.__class__)
            if updater is not None:
                self.hass.async_create_task(updater.force_update())
            else:
                _LOGGER.warning('Updater is not available! Please, report this to the developer.')
            return True

        except MoscowPGUException as e:
            _LOGGER.error('Error occurred: %s', e)
            return False


class MoscowPGUProfileSensor(MoscowPGUSensor):
    def __init__(self, profile: Profile):
        if profile.phone_number is None:
            raise ValueError('profile cannot be added without a phone number')
        self.profile = profile

    @property
    def name(self) -> Optional[str]:
        return f'Profile {self.profile.phone_number}'

    @property
    def unique_id(self) -> Optional[str]:
        return f'sensor_profile_{self.profile.phone_number}'

    @property
    def icon(self) -> Optional[str]:
        return 'mdi:account'

    @property
    def state(self) -> str:
        return STATE_OK

    @property
    def _device_state_attributes(self) -> Optional[Dict[str, Any]]:
        return {
            ATTR_FIRST_NAME: self.profile.first_name,
            ATTR_LAST_NAME: self.profile.last_name,
            ATTR_MIDDLE_NAME: self.profile.middle_name,
            ATTR_BIRTH_DATE: dt_to_str(self.profile.birth_date),
            ATTR_PHONE_NUMBER: self.profile.phone_number,
            ATTR_EMAIL: self.profile.email,
            ATTR_EMAIL_CONFIRMED: self.profile.email_confirmed,
            ATTR_DRIVING_LICENSE_NUMBER: self.profile.driving_license_number,
            ATTR_DRIVING_LICENSE_ISSUE_DATE: dt_to_str(self.profile.driving_license_issue_date),
        }


class MoscowPGUDrivingLicenseSensor(MoscowPGUSensor):
    def __init__(self, profile: Profile, offenses: Optional[List[Offense]] = None):
        if profile.driving_license_number is None:
            raise ValueError('driving license cannot be added without a driving license number')
        self.profile = profile
        self.offenses = offenses or []

    @property
    def name(self) -> Optional[str]:
        return f'Driving License {self.profile.driving_license_number}'

    @property
    def unique_id(self) -> Optional[str]:
        return f'sensor_driving_license_{self.profile.driving_license_number}'

    @property
    def icon(self) -> Optional[str]:
        return 'mdi:card-account-details'

    @property
    def state(self) -> float:
        return sum(map(lambda x: x.unpaid_amount or 0, self.offenses or []))

    @property
    def unit_of_measurement(self) -> Optional[str]:
        return 'RUB'

    @property
    def _device_state_attributes(self) -> Optional[Dict[str, Any]]:
        last_offense = None
        offenses = self.offenses
        if offenses:
            offenses = [
                offense_to_attributes(offense, with_document=False)
                for offense in sorted(offenses, key=lambda x: x.date_issued or date.min, reverse=True)
            ]
            last_offense = next(iter(offenses))

        return {
            ATTR_NUMBER: self.profile.driving_license_number,
            ATTR_ISSUE_DATE: dt_to_str(self.profile.driving_license_issue_date),
            ATTR_LAST_OFFENSE: last_offense,
            ATTR_OFFENSES: offenses,
        }


class MoscowPGUVehicleSensor(MoscowPGUSensor):
    def __init__(self, vehicle: Vehicle, offenses: Optional[List[Offense]] = None):
        if not vehicle.id:
            raise ValueError('transport cannot be added without ID')
        self.vehicle = vehicle
        self.offenses = offenses or []

    @property
    def name(self) -> Optional[str]:
        return f'Vehicle {self.vehicle.license_plate or self.vehicle.certificate_series or self.vehicle.id}'

    @property
    def unique_id(self) -> Optional[str]:
        return f'sensor_vehicle_{self.vehicle.id}'

    @property
    def icon(self) -> Optional[str]:
        return 'mdi:car'

    @property
    def state(self) -> Union[str, float]:
        if self.vehicle.certificate_series:
            return sum(map(lambda x: x.unpaid_amount or 0, self.offenses or []))
        return STATE_UNKNOWN

    @property
    def unit_of_measurement(self) -> Optional[str]:
        return 'RUB' if self.vehicle.certificate_series else None

    @property
    def _device_state_attributes(self) -> Optional[Dict[str, Any]]:
        attrs = {
            ATTR_ID: self.vehicle.id,
            ATTR_LICENSE_PLATE: self.vehicle.license_plate,
            ATTR_CERTIFICATE_SERIES: self.vehicle.certificate_series,
        }

        if self.vehicle.certificate_series:
            last_offense = None
            offenses = self.offenses
            if offenses:
                offenses = [
                    offense_to_attributes(offense, with_document=False)
                    for offense in offenses
                ]
                last_offense = next(iter(offenses))

            attrs[ATTR_LAST_OFFENSE] = last_offense
            attrs[ATTR_OFFENSES] = self.offenses

        return attrs


class MoscowPGUFSSPDebtsSensor(MoscowPGUSensor):
    pass
