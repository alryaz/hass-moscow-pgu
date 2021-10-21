import asyncio
import logging
from abc import ABC, abstractmethod
from datetime import date, datetime, time, timedelta
from typing import (
    Any,
    Callable,
    ClassVar,
    Collection,
    Dict,
    Final,
    Generic,
    Iterable,
    List,
    Mapping,
    Optional,
    Tuple,
    Type,
    TypeVar,
    Union,
)

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ATTRIBUTION,
    ATTR_DEVICE_CLASS,
    CONF_SCAN_INTERVAL,
)
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import ConfigType, HomeAssistantType
from homeassistant.util import as_local, utcnow

from .api import API
from .const import (
    CONF_FILTER,
    CONF_NAME_FORMAT,
    CONF_ROOT_UPDATE_INTERVAL,
    DATA_ENTITIES,
    DATA_FINAL_CONFIG,
    DATA_UPDATERS,
    DOMAIN,
)
from .util import all_subclasses

_T = TypeVar("_T")

_LOGGER = logging.getLogger(__name__)


class NameFormatDict(dict):
    def __missing__(self, key):
        return "{" + str(key) + "}"


class MoscowPGUEntity(Entity, ABC):
    _LOGGER: ClassVar[logging.Logger] = _LOGGER

    CONFIG_KEY: ClassVar[str] = NotImplemented
    DEFAULT_NAME_FORMAT: ClassVar[str] = NotImplemented
    DEFAULT_SCAN_INTERVAL: ClassVar[timedelta] = timedelta(hours=1)
    MIN_SCAN_INTERVAL: ClassVar[timedelta] = timedelta(seconds=30)
    SINGULAR_FILTER: ClassVar[bool] = False

    @classmethod
    @abstractmethod
    async def async_refresh_entities(
        cls,
        hass: HomeAssistantType,
        async_add_entities: Callable[[List["MoscowPGUEntity"], bool], Any],
        config_entry: ConfigEntry,
        config: ConfigType,
        api: "API",
        leftover_entities: List["MoscowPGUEntity"],
        name_format: str,
        scan_interval: timedelta,
        filter_values: Collection[str],
        is_blacklist: bool,
    ) -> Iterable["MoscowPGUEntity"]:
        raise NotImplementedError

    def __init__(self, config_entry_id: str, name_format: str, scan_interval: timedelta) -> None:
        assert name_format, "name format is empty"
        assert scan_interval, "scan interval is empty"

        self._entity_updater = None

        self.config_entry_id: Final[str] = config_entry_id

        self._scan_interval: timedelta = self.DEFAULT_SCAN_INTERVAL
        self._name_format: str = self.DEFAULT_NAME_FORMAT

        self.name_format = name_format
        self.scan_interval = scan_interval

    @property
    def scan_interval(self):
        return self._scan_interval

    @scan_interval.setter
    def scan_interval(self, value: Optional[Union[timedelta, int, float]]) -> None:
        if value is None:
            value = self.DEFAULT_SCAN_INTERVAL

        elif isinstance(value, (int, float)):
            value = timedelta(seconds=value)

        if value < self.MIN_SCAN_INTERVAL:
            self._LOGGER.warning(
                f"Attempted to set scan interval lower than "
                f"minimum ({value} < {self.MIN_SCAN_INTERVAL})"
            )
            value = self.MIN_SCAN_INTERVAL

        updater_restart = self._entity_updater and self._scan_interval != value
        self._scan_interval = value
        if updater_restart:
            self.updater_restart()

    @property
    def name_format(self) -> str:
        return self._name_format

    @name_format.setter
    def name_format(self, value: Optional[str]) -> None:
        self._name_format = value or self.DEFAULT_NAME_FORMAT

    @property
    def log_prefix(self) -> str:
        return f"[{self.config_entry_id[-6:]}][{self.unique_id}] "

    #################################################################################
    # Updater handling
    #################################################################################

    def updater_stop(self) -> None:
        if self._entity_updater is not None:
            self._LOGGER.debug(self.log_prefix + "Stopping updater")
            self._entity_updater()
            self._entity_updater = None

    def updater_restart(self) -> None:
        log_prefix = self.log_prefix
        scan_interval = self.scan_interval

        self.updater_stop()

        async def _update_entity(*_):
            nonlocal self
            self._LOGGER.debug(log_prefix + f"Executing updater on interval")
            await self.async_update_ha_state(force_refresh=True)

        self._LOGGER.debug(
            log_prefix + f"Starting updater "
            f"(interval: {scan_interval.total_seconds()} seconds, "
            f"next call: {as_local(utcnow()) + scan_interval})"
        )
        self._entity_updater = async_track_time_interval(
            self.hass,
            _update_entity,
            scan_interval,
        )

    async def updater_execute(self) -> None:
        self.updater_stop()
        try:
            await self.async_update_ha_state(force_refresh=True)
        finally:
            self.updater_restart()

    @property
    def entity_updater(self):
        return self._entity_updater

    #################################################################################
    # HA-specific code
    #################################################################################

    @property
    def should_poll(self) -> bool:
        return False

    async def async_added_to_hass(self) -> None:
        cls_entities = self.hass.data[DATA_ENTITIES][self.config_entry_id].setdefault(
            self.CONFIG_KEY, []
        )

        self._LOGGER.debug(self.log_prefix + "Adding to internal registry")
        cls_entities.append(self)

        # Start updater once everything is complete
        self.updater_restart()

    async def async_will_remove_from_hass(self) -> None:
        # Stop updater firstmost
        self._LOGGER.debug(self.log_prefix + "Will remove from internal registry")
        self.updater_stop()

        cls_entities = self.hass.data[DATA_ENTITIES][self.config_entry_id].get(self.CONFIG_KEY)

        if cls_entities and self in cls_entities:
            cls_entities.remove(self)

    @property
    def device_state_attributes(self) -> Optional[Dict[str, Any]]:
        _device_state_attributes = self.sensor_related_attributes or {}
        _device_state_attributes.setdefault(ATTR_ATTRIBUTION, "Data provided by Moscow PGU")

        if "api" in _device_state_attributes:
            del _device_state_attributes["api"]

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
        name_format_values = NameFormatDict(
            {
                key: ("" if value is None else value)
                for key, value in self.name_format_values.items()
            }
        )
        return self.name_format.format_map(name_format_values)

    @property
    def unique_id(self) -> str:
        raise NotImplementedError

    @property
    def name_format_values(self) -> Mapping[str, Any]:
        raise NotImplementedError

    async def async_update(self) -> None:
        raise NotImplementedError


_TSource = TypeVar("_TSource")


class MoscowPGUIterAddOrUpdateEntity(MoscowPGUEntity, ABC, Generic[_TSource]):
    ITER_COMPARE_ATTRIBUTES: ClassVar[Collection[str]] = ()
    ITER_IGNORE_ATTRIBUTES: ClassVar[Collection[str]] = ()

    ITER_CHECK_NONE: ClassVar[bool] = False
    ITER_CHECKER: ClassVar[Callable[[Iterable[bool]], bool]] = all
    ITER_REFRESH_AFTER: ClassVar[bool] = False

    def __init__(self, *args, source: _TSource, **kwargs) -> None:
        self.check_source_valid(source)
        super().__init__(*args, **kwargs)
        self.source = source

    @classmethod
    def check_source_valid(cls, source: _TSource) -> None:
        if not source:
            raise TypeError("source is empty")

        # # @TODO: this check might not be necessary
        # if not cls.ITER_CHECKER(bool(getattr(source, key)) for key in cls.ITER_COMPARE_ATTRIBUTES):
        #     raise ValueError("one of the attributes is missing or empty")

    @classmethod
    @abstractmethod
    async def async_get_objects_for_update(
        cls,
        hass: HomeAssistantType,
        config_entry: ConfigEntry,
        config: ConfigType,
        api: "API",
        filter_values: Collection[str] = (),
        is_blacklist: bool = True,
    ) -> Iterable[_TSource]:
        raise NotImplementedError

    @classmethod
    async def async_refresh_entities(
        cls,
        hass: HomeAssistantType,
        async_add_entities: Callable[[List["MoscowPGUEntity"], bool], Any],
        config_entry: ConfigEntry,
        config: ConfigType,
        api: "API",
        leftover_entities: List["MoscowPGUIterAddOrUpdateEntity"],
        name_format: str,
        scan_interval: timedelta,
        filter_values: Collection[str],
        is_blacklist: bool,
    ):
        objs = await cls.async_get_objects_for_update(
            hass, config_entry, config, api, filter_values, is_blacklist
        )

        entry_id = config_entry.entry_id
        cmp_attrs = cls.ITER_COMPARE_ATTRIBUTES
        entities = []
        check_none_attrs = (
            set(cls.ITER_COMPARE_ATTRIBUTES).difference(cls.ITER_IGNORE_ATTRIBUTES)
            if cls.ITER_CHECK_NONE
            else None
        )
        for obj in objs:
            if check_none_attrs and any(
                not getattr(obj, cmp_attr) for cmp_attr in check_none_attrs
            ):
                continue

            entity = None

            for existing_entity in leftover_entities:
                source = existing_entity.source
                if source is None:
                    continue

                if not cmp_attrs or cls.ITER_CHECKER(
                    getattr(source, cmp_attr) == getattr(obj, cmp_attr) for cmp_attr in cmp_attrs
                ):
                    entity = existing_entity
                    break

            if entity is None:
                entities.append(cls(entry_id, name_format, scan_interval, source=obj))

            else:
                leftover_entities.remove(entity)
                if entity.enabled:
                    entity.name_format = name_format
                    entity.scan_interval = scan_interval
                    entity.source = obj

                    entity.async_schedule_update_ha_state(force_refresh=cls.ITER_REFRESH_AFTER)

        if entities:
            async_add_entities(entities, cls.ITER_REFRESH_AFTER)

        return entities


def make_platform_setup(base_cls: Type[MoscowPGUEntity], logger: logging.Logger = _LOGGER):
    entity_classes = all_subclasses(base_cls)

    for cls in entity_classes:
        if cls._LOGGER is _LOGGER:
            cls._LOGGER = logger

    async def async_setup_entry(
        hass: HomeAssistantType, config_entry: ConfigEntry, async_add_entities
    ) -> bool:
        entry_id = config_entry.entry_id
        try:
            final_config = hass.data[DATA_FINAL_CONFIG][entry_id]
        except KeyError:
            raise ConfigEntryNotReady("Final configuration not yet injected")

        platform = entity_platform.async_get_current_platform()
        domain = platform.domain

        # Prepare necessary arguments
        api: API = hass.data[DOMAIN][entry_id]
        all_existing_entities: Dict[str, List[MoscowPGUEntity]] = hass.data[DATA_ENTITIES][entry_id]

        log_prefix = f"[{entry_id[-6:]}] "

        async def _perform_root_update(*args):
            logger.debug(log_prefix + f"Performing {'scheduled ' if args else ''}root update")
            update_cls = []
            update_tasks = []
            leftover_map = {}
            for entity_cls in entity_classes:
                config_key = entity_cls.CONFIG_KEY

                entity_cls_filter = final_config[CONF_FILTER][config_key]
                if not entity_cls_filter:
                    # Effectively means entity is disabled
                    logger.debug(log_prefix + f"{entity_cls.__name__} entities are disabled")
                    continue

                leftover_entities = list(all_existing_entities.setdefault(config_key, []))
                leftover_map[entity_cls] = leftover_entities

                entity_cls_filter = set(entity_cls_filter)

                try:
                    entity_cls_filter.remove("*")
                except KeyError:
                    is_blacklist = False
                else:
                    is_blacklist = True

                name_format = final_config[CONF_NAME_FORMAT][entity_cls.CONFIG_KEY]
                scan_interval = final_config[CONF_SCAN_INTERVAL][entity_cls.CONFIG_KEY]

                update_cls.append(entity_cls)
                update_tasks.append(
                    entity_cls.async_refresh_entities(
                        hass,
                        async_add_entities,
                        config_entry,
                        final_config,
                        api,
                        leftover_entities,
                        name_format,
                        scan_interval,
                        entity_cls_filter,
                        is_blacklist,
                    )
                )

            tasks = []

            update_results: Tuple[Iterable[MoscowPGUEntity], ...] = await asyncio.gather(
                *update_tasks, return_exceptions=True
            )

            for entity_cls, results in zip(update_cls, update_results):
                if isinstance(results, BaseException):
                    logger.error(
                        log_prefix + f"Error on {entity_cls.__name__} refresh: {repr(results)}"
                    )
                    continue

                leftover_entities = leftover_map[entity_cls]
                for entity in all_existing_entities[entity_cls.CONFIG_KEY]:
                    if entity in leftover_entities:
                        tasks.append(hass.async_create_task(entity.async_remove()))

            if tasks:
                await asyncio.wait(tasks)

        try:
            await _perform_root_update()
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            logger.error(log_prefix + f"Error performing refresh: {exc}")

        root_update_interval = final_config[CONF_ROOT_UPDATE_INTERVAL]
        logger.debug(
            log_prefix + f"Scheduling {domain} platform refresh (interval: {root_update_interval})"
        )
        hass.data[DATA_UPDATERS][domain] = async_track_time_interval(
            hass, _perform_root_update, root_update_interval
        )

        logger.debug(log_prefix + f"Finished component setup")
        return True

    return async_setup_entry


def dt_to_str(dt: Optional[Union[date, time, datetime]]) -> Optional[str]:
    """Optional date to string helper"""
    if dt is not None:
        return dt.isoformat()
