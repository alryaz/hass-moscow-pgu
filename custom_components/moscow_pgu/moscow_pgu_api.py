#!/usr/bin/env python3
# PYTHON_ARGCOMPLETE_OK
"""Moscow PGU API"""
import asyncio
import logging
import uuid
from abc import ABC
from datetime import date, datetime, time, timedelta
from enum import IntEnum
from functools import wraps
from time import time as timestamp
from typing import Optional, Dict, Mapping, Any, List, Hashable, Callable, Union, Type, Tuple, Collection, TypeVar, \
    Set, Iterable

import aiohttp
import attr
from json import loads, JSONDecodeError

_LOGGER = logging.getLogger(__name__)

TResponse = TypeVar('TResponse', bound='ResponseDataClass')


def datetime_from_russian(datetime_str: str):
    parts = datetime_str.split(' ')
    if len(parts) > 2:
        raise ValueError('datetime consists of more than 2 parts')
    date_ = date_from_russian(parts[0])
    if len(parts) > 1:
        time_ = time.fromisoformat(parts[1])
        return datetime.combine(date_, time_)
    return datetime(year=date_.year, month=date_.month, day=date_.day)


def date_from_russian(date_str: str):
    parts = date_str.split('.')
    if len(parts) > 3:
        raise ValueError('date consists of more than 3 parts')
    return date.today().replace(**dict(zip(('day', 'month', 'year'), map(int, parts))))


def float_russian(float_str: str):
    if isinstance(float_str, str):
        return float(float_str.replace('.', '').replace(',', '.'))
    return float(float_str)


def get_none(m: Mapping[str, Any], k: str, converter_if_value: Optional[Callable[[Any], Any]] = None,
             default: Any = None):
    v = m.get(k)
    if not v:
        return default
    if converter_if_value is not None:
        return converter_if_value(v)
    return v


def last_day_of_month(date_obj: date):
    if date_obj.month == 12:
        return date_obj.replace(day=31)
    return date_obj.replace(month=date_obj.month+1, day=1) - timedelta(days=1)


def explode_periods(
        periods: str,
        sep_segments: str,
        sep_ranges: str,
        sep_numbers: str
) -> Set[Tuple[timedelta, timedelta]]:
    """
    Explode periods string.
    :param periods: Periods string
    :param sep_segments: Separation of periods
    :param sep_ranges: Separator of period range
    :param sep_numbers: Separator of numbers (minutes from hours)
    :return: Set of period tuples
    """
    period_parts = periods.split(sep_segments)
    periods = []

    for period_part in period_parts:
        first_period, last_period = map(lambda x: tuple(map(int, x.split(sep_numbers))), period_part.split(sep_ranges))
        first_period = timedelta(hours=first_period[0], minutes=first_period[1])
        last_period = timedelta(hours=last_period[0], minutes=last_period[1])

        if last_period < first_period:
            periods.append((first_period, timedelta(days=1)))
            periods.append((timedelta(), last_period))
        else:
            periods.append((first_period, last_period))

    return set(periods)


_COMMANDLINE_ARGS: Dict[str, Tuple[Callable, Dict[str, Tuple[Callable[[Any], Any], bool, Any]]]] = {}


def _commandline_args(__command_name: Union[Callable[['API'], Any], Optional[str]] = None,
                      **kwargs: Union[Tuple[Callable[[Any], Any], bool], Tuple[Callable[[Any], Any], bool, Any], Callable[[Any], Any]]):
    def _decorator(api_method: Callable):
        key = __command_name if isinstance(__command_name, str) else api_method.__name__
        arguments = {}
        for cmd_arg, cmd_type in kwargs.items():
            if isinstance(cmd_type, tuple):
                if len(cmd_type) > 2:
                    cmd_type = (cmd_type[0], cmd_type[1], cmd_type[2])
                elif len(cmd_type) == 2:
                    cmd_type = (*cmd_type, None)
                elif len(cmd_type) == 1:
                    cmd_type = (*cmd_type, True, None)
                else:
                    raise ValueError('invalid cmd type')
            else:
                cmd_type = (cmd_type, True, None)

            arguments[cmd_arg] = cmd_type

        _COMMANDLINE_ARGS[key] = (api_method, arguments)

        return api_method

    if callable(__command_name):
        return _decorator(__command_name)

    return _decorator


@attr.s(slots=True, kw_only=True, auto_attribs=True)
class ResponseDataClass:
    api: Optional['API'] = None

    @staticmethod
    def method_requires_api(method: Callable):
        @wraps(method)
        def _internal(self: ResponseDataClass, *args, **kwargs):
            if self.api is None:
                raise AttributeError('API is unavailable for current object')
            return method(self, *args, **kwargs)

        return _internal

    @classmethod
    def from_response_dict(cls, response_dict: Mapping[str, Any],
                           api: Optional['API'] = None, **kwargs) -> 'ResponseDataClass':
        raise NotImplementedError


@attr.s(slots=True, kw_only=True, auto_attribs=True)
class ResponseDataClassWithID(ResponseDataClass, ABC):
    id: Any = None


@attr.s(slots=True, kw_only=True, auto_attribs=True)
class DrivingLicense(ResponseDataClass):
    number: Optional[str] = None
    issue_date: Optional[date] = None

    @classmethod
    def from_response_dict(cls, response_dict: Mapping[str, Any], api: Optional['API'] = None, **kwargs) -> 'DrivingLicense':
        return cls(
            api=api,
            number=get_none(response_dict, 'drive_license'),
            issue_date=get_none(response_dict, 'drive_issue_date', date_from_russian),
        )

    @ResponseDataClass.method_requires_api
    async def get_offenses(self, session: Optional[aiohttp.ClientSession] = None) -> List['Offense']:
        return await self.api.get_driving_license_offenses(self.number, session=session)


@attr.s(slots=True, kw_only=True, auto_attribs=True)
class Profile(ResponseDataClass):
    first_name: Optional[str] = None
    middle_name: Optional[str] = None
    last_name: Optional[str] = None
    birth_date: Optional[date] = None
    email: Optional[str] = None
    phone_number: Optional[str] = None
    email_confirmed: Optional[bool] = None
    snils: Optional[str] = None
    driving_license: Optional[DrivingLicense] = None

    @property
    def full_name(self) -> Optional[str]:
        parts = filter(lambda x: bool(x), [
            self.last_name,
            self.first_name,
            self.middle_name
        ])
        if parts:
            return ' '.join(map(str, parts))

    @classmethod
    def from_response_dict(cls, response_dict: Mapping[str, Any], api: Optional['API'] = None, **kwargs) -> 'Profile':
        birth_date = get_none(response_dict, 'birthdate', date_from_russian)

        driving_license = None
        if 'drive_license' in response_dict:
            driving_license = DrivingLicense.from_response_dict(response_dict, api=api, **kwargs)

        return cls(
            api=api,
            first_name=get_none(response_dict, 'firstname', lambda x: str(x).strip()),
            middle_name=get_none(response_dict, 'middlename', lambda x: str(x).strip()),
            last_name=get_none(response_dict, 'lastname', lambda x: str(x).strip()),
            birth_date=birth_date,
            email=get_none(response_dict, 'email'),
            phone_number=get_none(response_dict, 'msisdn'),
            email_confirmed=get_none(response_dict, 'email_confirmed'),
            snils=get_none(response_dict, 'snils'),
            driving_license=driving_license,
        )

    @ResponseDataClass.method_requires_api
    async def get_fssp_detailed(self, session: Optional[aiohttp.ClientSession] = None) -> List['FSSPDebt']:
        return await self.api.get_fssp_detailed(
            first_name=self.first_name,
            last_name=self.last_name,
            middle_name=self.middle_name,
            birth_date=self.birth_date,
            session=session,
        )


@attr.s(slots=True, kw_only=True, auto_attribs=True)
class WaterIndication(ResponseDataClass):
    counter_id: Optional[int] = None
    period: Optional[date] = None
    indication: Optional[float] = None

    @classmethod
    def from_response_dict(cls, response_dict: Mapping[str, Any], api: Optional['API'] = None,
                           counter_id: Optional[int] = None, **kwargs) -> 'WaterIndication':
        return cls(
            api=api,
            counter_id=counter_id,
            period=get_none(response_dict, 'period', lambda x: date.fromisoformat(x.split('+')[0])),
            indication=get_none(response_dict, 'indication', float),
        )


class WaterCounterType(IntEnum):
    UNKNOWN = -1
    COLD = 1
    HOT = 2

    @classmethod
    def _missing_(cls, value):
        return cls.UNKNOWN


@attr.s(slots=True, kw_only=True, auto_attribs=True)
class WaterCounter(ResponseDataClassWithID):
    id: Optional[int] = None
    flat_id: Optional[int] = None
    type: Optional[WaterCounterType] = None
    code: Optional[int] = None
    checkup_date: Optional[date] = None
    indications: Optional[List[WaterIndication]]

    @classmethod
    def from_response_dict(cls, response_dict: Mapping[str, Any], api: Optional['API'] = None,
                           flat_id: Optional[int] = None, **kwargs) -> 'WaterCounter':
        water_counter_id = get_none(response_dict, 'counterId', int)

        indications = get_none(response_dict, 'indications')
        if indications:
            indications = [
                WaterIndication.from_response_dict(
                    indication,
                    api=api,
                    counter_id=water_counter_id,
                    flat_id=flat_id,
                    **kwargs
                )
                for indication in indications
            ]

        checkup_date = get_none(response_dict, 'checkup')
        if checkup_date:
            checkup_date = date.fromisoformat(checkup_date.split('+')[0])

        return cls(
            api=api,
            id=water_counter_id,
            flat_id=flat_id,
            type=get_none(response_dict, 'type', lambda x: WaterCounterType(int(x))),
            code=get_none(response_dict, 'num', str),
            checkup_date=checkup_date,
            indications=indications,
        )

    @property
    def last_indication(self) -> Optional[WaterIndication]:
        if self.indications:
            iterator = iter(self.indications)
            last_indication = next(iterator)
            for indication in iterator:
                if indication.period > last_indication.period:
                    last_indication = indication
                elif indication.period == last_indication.period and indication.indication > last_indication.indication:
                    last_indication = indication

            return last_indication

    @ResponseDataClass.method_requires_api
    async def push_water_counter_indication(self, indication: Union[int, float]) -> None:
        return await self.api.push_water_counter_indication(self.flat_id, self.id, indication)


@attr.s(slots=True, kw_only=True, auto_attribs=True)
class Flat(ResponseDataClassWithID):
    id: Optional[int] = None
    name: Optional[str] = None
    address: Optional[str] = None
    flat_number: Optional[str] = None
    unom: Optional[str] = None
    unad: Optional[str] = None
    epd_account: Optional[str] = None
    electric_account: Optional[str] = None
    electric_device: Optional[str] = None
    intercom: Optional[str] = None
    floor: Optional[str] = None
    entrance_number: Optional[str] = None
    phone_number: Optional[str] = None

    @classmethod
    def from_response_dict(cls, response_dict: Mapping[str, Any], api: Optional['API'] = None, **kwargs) -> 'Flat':
        return cls(
            api=api,
            id=get_none(response_dict, 'flat_id', int),
            name=get_none(response_dict, 'name'),
            address=get_none(response_dict, 'address'),
            flat_number=get_none(response_dict, 'flat_number'),
            unom=get_none(response_dict, 'unom'),
            unad=get_none(response_dict, 'unad'),
            epd_account=get_none(response_dict, 'paycode'),
            electric_account=get_none(response_dict, 'electro_account'),
            electric_device=get_none(response_dict, 'electro_device'),
            intercom=get_none(response_dict, 'intercom'),
            floor=get_none(response_dict, 'floor'),
            entrance_number=get_none(response_dict, 'entrance_number')
        )

    @property
    def flat_id(self) -> Optional[int]:
        return self.id

    @flat_id.setter
    def flat_id(self, value: int) -> None:
        self.id = value

    @ResponseDataClass.method_requires_api
    async def get_water_counters(self, session: Optional[aiohttp.ClientSession] = None) -> List[WaterCounter]:
        assert self.id is not None, "id attribute is empty"
        return await self.api.get_water_counters(self.id, session=session)

    @ResponseDataClass.method_requires_api
    async def push_water_counter_indications(self, indications: Mapping[int, Union[int, float]], session: Optional[aiohttp.ClientSession] = None) -> None:
        assert self.id is not None, "id attribute is empty"
        return await self.api.push_water_counter_indications(self.id, indications, session=session)

    @ResponseDataClass.method_requires_api
    async def push_water_counter_indication(self, counter_id: int, indication: Union[int, float], session: Optional[aiohttp.ClientSession] = None) -> None:
        assert self.id is not None, "id attribute is empty"
        return await self.api.push_water_counter_indication(self.id, counter_id, indication, session=session)

    @ResponseDataClass.method_requires_api
    async def get_epds(self, begin: Optional[date] = None, end: Optional[date] = None, session: Optional[aiohttp.ClientSession] = None) -> List['EPD']:
        assert self.id is not None, "id attribute is empty"
        return await self.api.get_flat_epds(self.id, begin=begin, end=end, session=session)

    @ResponseDataClass.method_requires_api
    async def get_electric_balance(self, session: Optional[aiohttp.ClientSession] = None) -> 'ElectricBalance':
        assert self.electric_account, "electric account attribute is empty"
        assert self.electric_device, "electric device attribute is empty"
        return await self.api.get_electric_balance(flat_id=self.id, session=session)

    @ResponseDataClass.method_requires_api
    async def get_electric_counter_info(self, session: Optional[aiohttp.ClientSession] = None) -> 'ElectricCounterInfo':
        assert self.electric_account, "electric account attribute is empty"
        assert self.electric_device, "electric account attribute is empty"
        return await self.api.get_electric_counter_info(flat_id=self.id, session=session)

    @ResponseDataClass.method_requires_api
    async def push_electric_indications(
            self,
            indication_t1: Union[float, Iterable[float]],
            indication_t2: Optional[float] = None,
            indication_t3: Optional[float] = None,
            perform_checks: bool = True,
            session: Optional[aiohttp.ClientSession] = None
    ) -> None:
        assert self.id is not None, "id attribute is empty"
        return await self.api.push_electric_indications(
            flat_id=self.id,
            indication_t1=indication_t1,
            indication_t2=indication_t2,
            indication_t3=indication_t3,
            perform_checks=perform_checks,
            session=session,
        )



@attr.s(slots=True, kw_only=True, auto_attribs=True)
class Vehicle(ResponseDataClassWithID):
    id: Optional[str] = None
    name: Optional[str] = None
    license_plate: Optional[str] = None
    certificate_series: Optional[str] = None
    is_evacuated: Optional[bool] = None

    @classmethod
    def from_response_dict(cls, response_dict: Mapping[str, Any], api: Optional['API'] = None, **kwargs) -> 'Vehicle':
        return cls(
            api=api,
            id=get_none(response_dict, 'vehicle_id'),
            name=get_none(response_dict, 'name'),
            license_plate=get_none(response_dict, 'vehicle_number'),
            certificate_series=get_none(response_dict, 'sts_number'),
            is_evacuated=get_none(response_dict, 'is_evacuated'),
        )

    @ResponseDataClass.method_requires_api
    async def get_offenses(self, session: Optional[aiohttp.ClientSession] = None):
        if not self.certificate_series:
            raise ValueError('cannot fetch offenses on vehicle without certificate series')
        return await self.api.get_vehicle_offenses(self.certificate_series, session=session)


@attr.s(slots=True, kw_only=True, auto_attribs=True)
class Patient(ResponseDataClassWithID):
    id: Optional[int] = None
    number: Optional[str] = None
    birth_date: Optional[date] = None
    first_name: Optional[str] = None
    middle_name: Optional[str] = None
    last_name: Optional[str] = None

    @classmethod
    def from_response_dict(cls, response_dict: Mapping[str, Any], api: Optional['API'] = None, **kwargs) -> 'Patient':
        birth_date = get_none(response_dict, 'birthdate')
        if birth_date is not None:
            birth_date = date_from_russian(birth_date)

        return cls(
            api=api,
            id=get_none(response_dict, 'id'),
            birth_date=birth_date,
            first_name=get_none(response_dict, 'firstname'),
            middle_name=get_none(response_dict, 'middlename'),
            last_name=get_none(response_dict, 'lastname'),
        )


@attr.s(slots=True, kw_only=True, auto_attribs=True)
class Pet(ResponseDataClassWithID):
    id: Optional[str] = None
    name: Optional[str] = None
    species_id: Optional[str] = None
    species: Optional[str] = None
    breed_id: Optional[str] = None
    breed: Optional[str] = None
    birth_date: Optional[date] = None
    chip_number: Optional[str] = None
    gender: Optional[str] = None

    @classmethod
    def from_response_dict(cls, response_dict: Mapping[str, Any], api: Optional['API'] = None, **kwargs) -> 'Pet':
        birth_date = get_none(response_dict, 'birthdate', date_from_russian)

        return cls(
            api=api,
            id=get_none(response_dict, 'pet_id'),
            name=get_none(response_dict, 'name'),
            species_id=get_none(response_dict, 'species_id'),
            breed_id=get_none(response_dict, 'breed_id'),
            species=get_none(response_dict, 'species'),
            breed=get_none(response_dict, 'breed'),
            birth_date=birth_date,
            gender=get_none(response_dict, 'gender'),
            chip_number=get_none(response_dict, 'chip_number'),
        )


@attr.s(slots=True, kw_only=True, auto_attribs=True)
class Offense(ResponseDataClassWithID):
    id: Optional[str] = None
    date_issued: Optional[date] = None
    date_committed: Optional[date] = None
    time_committed: Optional[time] = None
    article_title: Optional[str] = None
    location: Optional[str] = None
    penalty: Optional[float] = None
    status: Optional[int] = None
    status_rnip: Optional[int] = None
    discount_date: Optional[date] = None
    police_unit_code: Optional[str] = None
    police_unit_name: Optional[str] = None
    document_type: Optional[str] = None
    document_series: Optional[str] = None
    photo_url: Optional[str] = None
    unpaid_amount: Optional[float] = None
    status_text: Optional[str] = None

    @property
    def datetime_committed(self) -> Optional[datetime]:
        if self.date_committed and self.time_committed:
            return datetime.combine(self.date_committed, self.time_committed)
        elif self.date_committed:
            return datetime(
                year=self.date_committed.year,
                month=self.date_committed.month,
                day=self.date_committed.day
            )

    @classmethod
    def from_response_dict(cls, response_dict: Mapping[str, Any], api: Optional['API'] = None, **kwargs) -> 'Offense':
        date_issued = get_none(response_dict, 'act_date', date_from_russian)

        time_committed = None
        datetime_committed = get_none(response_dict, 'offense_date_with_time', datetime_from_russian)
        if datetime_from_russian is not None:
            time_committed = datetime_committed.time()

        date_committed = get_none(response_dict, 'offense_date', date_from_russian)
        if date_committed is not None:
            if datetime_committed is not None and datetime_committed.date() != date_committed:
                _LOGGER.warning('Datetime committed differs from explicit commit date')
        elif datetime_committed is not None:
            date_committed = datetime_committed.date()

        discount_date = get_none(response_dict, 'discount_date', date_from_russian)

        return cls(
            api=api,
            id=get_none(response_dict, 'offense_series'),
            date_issued=date_issued,
            time_committed=time_committed,
            article_title=get_none(response_dict, 'offense_article_title'),
            date_committed=date_committed,
            location=get_none(response_dict, 'offense_place'),
            penalty=get_none(response_dict, 'full_price'),
            status=get_none(response_dict, 'offense_status'),
            status_rnip=get_none(response_dict, 'offense_rnip_status'),
            discount_date=discount_date,
            police_unit_code=get_none(response_dict, 'police_unit_code'),
            police_unit_name=get_none(response_dict, 'police_unit_name'),
            document_type=get_none(response_dict, 'document_type'),
            document_series=get_none(response_dict, 'document_series'),
            photo_url=get_none(response_dict, 'photo_link'),
            unpaid_amount=get_none(response_dict, 'amount_to_pay', float_russian),
            status_text=get_none(response_dict, 'status'),
        )


@attr.s(slots=True, kw_only=True, auto_attribs=True)
class EPD(ResponseDataClassWithID):
    id: Optional[str] = None
    insurance_amount: Optional[float] = None
    period: Optional[date] = None
    type: Optional[str] = None
    payment_amount: Optional[float] = None
    payment_date: Optional[date] = None
    payment_status: Optional[str] = None
    initiator: Optional[str] = None
    create_datetime: Optional[datetime] = None
    penalty_amount: Optional[float] = None
    amount: Optional[float] = None
    amount_with_insurance: Optional[float] = None

    @classmethod
    def from_response_dict(cls, response_dict: Mapping[str, Any], api: Optional['API'] = None, **kwargs) -> 'EPD':
        amount = get_none(response_dict, 'amount', float_russian)
        insurance_amount = get_none(response_dict, 'insurance_amount', float_russian)
        amount_with_insurance = get_none(response_dict, 'amount_with_insurance', float_russian)

        if amount_with_insurance is None and amount is not None and insurance_amount is not None:
            amount_with_insurance = amount + insurance_amount

        return cls(
            api=api,
            id=get_none(response_dict, 'uin'),
            insurance_amount=insurance_amount,
            period=get_none(response_dict, 'period', date_from_russian),
            type=get_none(response_dict, 'epd_type'),
            payment_amount=get_none(response_dict, 'payment_amount', float_russian),
            payment_date=get_none(response_dict, 'payment_date', date_from_russian),
            payment_status=get_none(response_dict, 'payment_status'),
            initiator=get_none(response_dict, 'initiator'),
            create_datetime=get_none(response_dict, 'create_date', datetime_from_russian),
            penalty_amount=get_none(response_dict, 'penalty_amount', float_russian),
            amount=amount,
            amount_with_insurance=amount_with_insurance,
        )

    @property
    def unpaid_amount(self) -> Optional[float]:
        amount = self.amount_with_insurance or self.amount
        if amount is not None:
            paid = self.payment_amount or 0
            return amount - paid


@attr.s(slots=True, kw_only=True, auto_attribs=True)
class FSSPDebt(ResponseDataClassWithID):
    enterpreneur_id: Optional[int] = None
    description: Optional[str] = None
    total_amount: Optional[float] = None
    unpaid_amount: Optional[float] = None
    unload_date: Optional[datetime] = None
    unload_status: Optional[str] = None
    birth_date: Optional[date] = None
    first_name: Optional[str] = None
    middle_name: Optional[str] = None
    last_name: Optional[str] = None
    # Detailed-only
    id: Optional[int] = None
    kladr_main_name: Optional[str] = None
    kladr_street_name: Optional[str] = None
    unpaid_enterpreneur_amount: Optional[float] = None
    unpaid_bailiff_amount: Optional[float] = None
    rise_date: Optional[date] = None
    osp_system_site_id: Optional[int] = None
    bailiff_name: Optional[str] = None
    bailiff_phone: Optional[str] = None

    @property
    def paid(self) -> Optional[float]:
        if self.total_amount is not None and self.unpaid_amount is not None:
            # @TODO: this might be incorrect...
            return self.total_amount - self.unpaid_amount

    @classmethod
    def from_response_dict(cls, response_dict: Mapping[str, Any], api: Optional['API'] = None, **kwargs) -> 'FSSPDebt':
        birth_date = get_none(response_dict, 'birthdate')
        if birth_date is not None:
            birth_date = date_from_russian(birth_date)

        unload_date = get_none(response_dict, 'unload_date')
        if unload_date is not None:
            unload_date = datetime(
                year=int(unload_date[0:4]),
                month=int(unload_date[4:6]),
                day=int(unload_date[6:8]),
                hour=int(unload_date[8:10]),
                minute=int(unload_date[10:12]),
                second=int(unload_date[12:14])
            )

        rise_date = get_none(response_dict, 'ip_risedate')
        if rise_date is not None:
            rise_date = date(
                year=int(rise_date[0:4]),
                month=int(rise_date[4:6]),
                day=int(rise_date[6:8])
            )

        return cls(
            api=api,
            enterpreneur_id=get_none(response_dict, 'ip_id'),
            description=get_none(response_dict, 'id_debttext'),
            total_amount=get_none(response_dict, 'id_debtsum',
                                  converter_if_value=float_russian, default=0.0),
            unpaid_amount=get_none(response_dict, 'ip_debt_rest_total',
                                   converter_if_value=float_russian, default=0.0),
            unload_date=unload_date,
            unload_status=get_none(response_dict, 'unload_status'),
            first_name=get_none(response_dict, 'firstname'),
            middle_name=get_none(response_dict, 'middlename'),
            last_name=get_none(response_dict, 'lastname'),
            birth_date=birth_date,
            # Detailed only
            id=get_none(response_dict, 'id_number'),
            kladr_main_name=get_none(response_dict, 'kladr_main_name'),
            kladr_street_name=get_none(response_dict, 'kladr_street_name'),
            rise_date=rise_date,
            unpaid_enterpreneur_amount=get_none(response_dict, 'ip_debt_rest_ip', float_russian, default=0.0),
            unpaid_bailiff_amount=get_none(response_dict, 'ip_debt_rest_fine', float_russian, default=0.0),
            osp_system_site_id=get_none(response_dict, 'osp_system_site_id'),
            bailiff_name=get_none(response_dict, 'ip_exec_prist_name'),
            bailiff_phone=get_none(response_dict, 'spi_tel'),
        )

    @ResponseDataClass.method_requires_api
    async def get_detailed(self, session: Optional[aiohttp.ClientSession] = None):
        return await self.api.get_fssp_detailed(
            first_name=self.first_name,
            last_name=self.last_name,
            middle_name=self.middle_name,
            birth_date=self.birth_date,
            session=session,
        )


@attr.s(slots=True, kw_only=True, auto_attribs=True)
class ElectricIndication(ResponseDataClass):
    tariff: Optional[str] = None
    zone_name: Optional[str] = None
    indication: Optional[float] = None
    periods: Optional[List[Tuple[timedelta, timedelta]]] = None

    @classmethod
    def from_response_dict(cls, response_dict: Mapping[str, Any], api: Optional['API'] = None, **kwargs) -> 'ElectricIndication':
        periods = get_none(response_dict, 'time_period', default=[])
        if periods:
            periods = explode_periods(periods, sep_segments=', ', sep_ranges=' - ', sep_numbers='-')

        return cls(
            api=api,
            tariff=get_none(response_dict, 'code'),
            zone_name=get_none(response_dict, 'zone_name', converter_if_value=lambda x: str(x).rstrip(':')),
            indication=get_none(response_dict, 'indication', float_russian),
            periods=periods
        )


@attr.s(slots=True, kw_only=True, auto_attribs=True)
class ElectricBalance(ResponseDataClass):
    flat_id: Optional[int] = None
    balance_amount: Optional[float] = None
    submit_begin_date: Optional[date] = None
    submit_end_date: Optional[date] = None
    settlement_date: Optional[date] = None
    debt_amount: Optional[float] = None
    payments_amount: Optional[float] = None
    transfer_amount: Optional[float] = None
    charges_amount: Optional[float] = None
    returns_amount: Optional[float] = None
    indications: Optional[List[ElectricIndication]] = None
    balance_message: Optional[str] = None

    @classmethod
    def from_response_dict(cls, response_dict: Mapping[str, Any], api: Optional['API'] = None,
                           flat_id: Optional[int] = None, **kwargs) -> 'ElectricBalance':
        indications = get_none(response_dict, 'indications', default=[])
        if indications:
            indications = [
                indication_dict if isinstance(indication_dict, ElectricIndication)
                else ElectricIndication.from_response_dict(indication_dict, api=api, flat_id=flat_id, **kwargs)
                for indication_dict in indications
            ]

        return cls(
            api=api,
            flat_id=flat_id,
            balance_amount=get_none(response_dict, 'balance_amount', float_russian, default=0.0),
            submit_begin_date=get_none(response_dict, 'begin_date', date_from_russian),
            submit_end_date=get_none(response_dict, 'end_date', date_from_russian),
            settlement_date=get_none(response_dict, 'settlement_date', date_from_russian),
            payments_amount=get_none(response_dict, 'payments_amount', float_russian, default=0.0),
            returns_amount=get_none(response_dict, 'returns_amount', float_russian, default=0.0),
            charges_amount=get_none(response_dict, 'charges_amount', float_russian, default=0.0),
            transfer_amount=get_none(response_dict, 'transfer_amount', float_russian, default=0.0),
            debt_amount=get_none(response_dict, 'debt_amount', float_russian, default=0.0),
            indications=indications,
            balance_message=get_none(response_dict, 'balance_message', str),
        )


@attr.s(slots=True, kw_only=True, auto_attribs=True)
class ElectricCounterZone(ResponseDataClass):
    name: Optional[str] = None
    periods: Optional[Tuple[Tuple[timedelta, timedelta]]] = None
    cost: Optional[float] = None

    @classmethod
    def from_response_dict(cls, response_dict: Mapping[str, Any], api: Optional['API'] = None, **kwargs) -> 'ElectricCounterZone':
        periods = get_none(response_dict, 'time_period', converter_if_value=str)
        if periods:
            periods = explode_periods(periods, sep_segments='; ', sep_ranges='-', sep_numbers='.')

        return cls(
            api=api,
            name=get_none(response_dict, 'name', str),
            periods=periods,
            cost=get_none(response_dict, 'tarif', float_russian),
        )

    def is_timestamp_in_zone(self, ts: Union[int, datetime, timedelta]) -> bool:
        assert self.periods is not None, "periods are not set on init"
        if isinstance(ts, int):
            ts = datetime.fromtimestamp(ts)
        if isinstance(ts, datetime):
            ts = timedelta(minutes=ts.minute, hours=ts.hour, seconds=ts.second, microseconds=ts.microsecond)

        for period_start, period_end in self.periods:
            if period_start <= ts < period_end:
                return True

        return False


@attr.s(slots=True, kw_only=True, auto_attribs=True)
class ElectricCounterInfo(ResponseDataClass):
    flat_id: Optional[int] = None
    type: Optional[str] = None
    zones: Optional[Tuple[ElectricCounterZone]] = None

    @classmethod
    def from_response_dict(cls, response_dict: Mapping[str, Any], api: Optional['API'] = None,
                           flat_id: Optional[int] = None, **kwargs) -> 'ElectricCounterInfo':
        zones = get_none(response_dict, 'zone_info', default=[])
        if zones:
            zones = [
                ElectricCounterZone.from_response_dict(zone_info, api=api, flat_id=flat_id, **kwargs)
                for zone_info in zones
            ]

        return cls(
            api=api,
            flat_id=flat_id,
            type=get_none(response_dict, 'registration_type'),
            zones=zones,
        )

    def get_period_zone(self, ts: Union[int, datetime, timedelta]) -> Optional[ElectricCounterZone]:
        assert self.zones is not None, "zones are not set on init"

        if isinstance(ts, int):
            ts = datetime.fromtimestamp(ts)
        if isinstance(ts, datetime):
            ts = timedelta(minutes=ts.minute, hours=ts.hour, seconds=ts.second, microseconds=ts.microsecond)

        for zone in self.zones:
            if zone.is_timestamp_in_zone(ts):
                return zone


@attr.s(slots=True, kw_only=True, auto_attribs=True)
class ElectricIndicationsStatus(ResponseDataClass):
    flat_id: Optional[int] = None
    check_code: Optional[int] = None
    check_message: Optional[int] = None
    counter_state: Optional[str] = None
    counter_verification_date: Optional[date] = None
    counter_whole_part_length: Optional[int] = None
    counter_decimal_part_length: Optional[int] = None

    @classmethod
    def from_response_dict(cls, response_dict: Mapping[str, Any], api: Optional['API'] = None,
                           flat_id: Optional[int] = None, **kwargs) -> 'ElectricIndicationsStatus':
        check_result = get_none(response_dict, "check_result") or {}
        counter_info = get_none(response_dict, "counter_info")

        return cls(
            api=api,
            flat_id=flat_id,
            check_code=get_none(check_result, "code", int),
            check_message=get_none(check_result, "message"),
            counter_state=get_none(counter_info, "state"),
            counter_verification_date=get_none(counter_info, "verification_date"),
            counter_whole_part_length=get_none(counter_info, "capacity", lambda x: int(str(x).split('.')[0])),
            counter_decimal_part_length=get_none(counter_info, "capacity", lambda x: int(str(x).split('.')[1])),
        )


class API:
    BASE_EMP_URL = "https://emp.mos.ru"

    __slots__ = ('username', 'password', 'cookies', 'app_version', 'device_os',
                 'device_agent', 'user_agent', 'token', 'guid', 'cache_lifetime',
                 '__cache', '__futures', '_session_id')

    def __init__(
            self,
            username: str,
            password: str,
            app_version: str = '3.10.0.19 (122)',
            device_os: str = 'Android',
            device_agent: str = 'Android 11 (SDK 30) Xiaomi sagit (MI 6)',
            user_agent: str = 'okhttp/4.9.0',
            token: str = '887033d0649e62a84f80433e823526a1',
            guid: Optional[str] = None,
            cache_lifetime: float = 3600
    ):
        self.username = username
        self.password = password
        self.cookies = aiohttp.CookieJar()

        self.app_version = app_version
        self.device_os = device_os
        self.device_agent = device_agent
        self.user_agent = user_agent
        self.token = token
        self.guid = guid or str(uuid.uuid4()).replace('-', '')

        self.cache_lifetime = cache_lifetime
        self.__cache = {}
        self.__futures: Dict[Tuple[str, Any], asyncio.Future] = {}
        self._session_id = None

    @property
    def session_id(self) -> Optional[str]:
        return self._session_id

    @property
    def device_info(self) -> Dict[str, str]:
        return {
            'guid': self.guid,
            'user_agent': self.device_os,
            'mobile': self.device_agent,
            'app_version': self.app_version
        }

    async def uncached_request(self, sub_url: str, json: Optional[Mapping[str, Any]] = None,
                               session: Optional[aiohttp.ClientSession] = None) -> Any:
        if session is None:
            async with aiohttp.ClientSession(cookie_jar=self.cookies) as session:
                return await self.uncached_request(sub_url, json, session=session)

        json_data = {
            'info': {
                **self.device_info,
                'object_id': '',
                'session_id': self._session_id,
            },
            'auth': {
                'session_id': self._session_id,
            }
        }

        if json is not None:
            json_data.update(json)

        params = {'token': self.token}
        full_url = self.BASE_EMP_URL + '/' + sub_url.strip('/')
        postfix = '&'.join(map(lambda x: '%s=%s' % x, params.items()))

        _LOGGER.debug('---> %s?%s (%s) %s', full_url, postfix, 'POST', json_data)
        async with session.post(
                full_url,
                params=params,
                json=json_data
        ) as request:
            response_text = await request.text()

            _LOGGER.debug('<--- %s?%s (%s) [%s] %s', full_url, postfix, 'POST', request.status, response_text)

            try:
                response = loads(response_text)
            except JSONDecodeError as e:
                raise ErrorResponseException('Could not decode JSON response: %s' % (e,))

        if response.get('errorCode', 0) != 0:
            raise ErrorResponseException('Response error',
                                         response['errorCode'],
                                         response.get('errorMessage', 'no message'))

        try:
            return response['result']
        except KeyError:
            raise ErrorResponseException('Response does not contain a `result` key')

    async def request(self, sub_url: str, json: Optional[Mapping[str, Any]] = None,
                      session: Optional[aiohttp.ClientSession] = None, cache_key: Hashable = None) -> Any:
        cache_disabled = cache_key is None and json is not None
        cache_save_time = timestamp()
        cache_idx = (sub_url, cache_key)

        if not cache_disabled:
            if cache_idx in self.__cache:
                created_at, result = self.__cache[cache_idx]

                if timestamp() - created_at > self.cache_lifetime:
                    _LOGGER.debug('Cache expired on %s / %s', sub_url, cache_key)
                    del self.__cache[cache_idx]
                else:
                    _LOGGER.debug('Cache hit on %s / %s', sub_url, cache_key)
                    return result

            if cache_idx in self.__futures:
                return await self.__futures[cache_idx].result()

            loop = asyncio.get_running_loop()
            self.__futures[cache_idx] = loop.create_future()

        try:
            result = await self.uncached_request(sub_url, json=json, session=session)
        except Exception as e:
            if cache_idx:
                self.__futures[cache_idx].set_exception(e)
            raise

        if not cache_disabled:
            _LOGGER.debug('Saved cache on %s / %s', sub_url, cache_key)
            self.__cache[cache_idx] = (cache_save_time, result)
            self.__futures[cache_idx].set_result(result)
            del self.__futures[cache_idx]

        return result

    def clear_cache(self, sub_url: Optional[Union[Hashable, Iterable[Hashable]]] = None,
                    cache_key: Optional[Union[Hashable, Iterable[Hashable]]] = None) -> None:
        if not (sub_url is None or isinstance(sub_url, (str, bytes, bytearray))) and isinstance(sub_url, Iterable):
            for in_sub_url in sub_url:
                self.clear_cache(sub_url=in_sub_url, cache_key=cache_key)

        if not (cache_key is None or isinstance(cache_key, (str, bytes, bytearray))) and isinstance(cache_key, Iterable):
            for in_cache_key in cache_key:
                self.clear_cache(sub_url=sub_url, cache_key=in_cache_key)

        if sub_url is None and cache_key is None:
            self.__cache.clear()

        else:
            cache_indices = list(self.__cache.keys())
            if sub_url is None:
                for ex_sub_url, ex_cache_key in cache_indices:
                    if cache_key == cache_key:
                        del self.__cache[(ex_sub_url, ex_cache_key)]

            elif cache_key is None:
                for ex_sub_url, ex_cache_key in cache_indices:
                    if ex_sub_url == sub_url:
                        del self.__cache[(ex_sub_url, ex_cache_key)]

            else:
                for ex_sub_url, ex_cache_key in cache_indices:
                    if ex_sub_url == sub_url and ex_cache_key == cache_key:
                        del self.__cache[(ex_sub_url, ex_cache_key)]

    # API response helpers
    def _response_data_list(
            self,
            __as_cls: Type[TResponse],
            __result: Union[List[Mapping[str, Any]], Mapping[str, Any]],
            __key: Optional[str] = None,
            **kwargs
    ) -> List[TResponse]:
        if __key is not None:
            __result = (__result or {}).get(__key)
        return list(map(lambda x: self._response_data_single(__as_cls, x, **kwargs), __result or []))
    
    def _response_data_single(
            self,
            __as_cls: Type[TResponse],
            __result: Mapping[str, Any],
            __key: Optional[str] = None,
            **kwargs
    ) -> Optional[TResponse]:
        if __key is not None:
            __result = (__result or {}).get(__key)
        if __result:
            return __as_cls.from_response_dict(__result, api=self, **kwargs)

    # Basic API
    @_commandline_args
    async def authenticate(self, session: Optional[aiohttp.ClientSession] = None) -> None:
        self._session_id = None
        try:
            result = await self.uncached_request('v1.0/auth/virtualLogin', {
                'auth': {
                    'guid': self.guid,
                    'login': self.username,
                    'password': self.password,
                },
                'device_info': self.device_info,
            }, session=session)

        except ErrorResponseException as e:
            raise AuthenticationException(*e.args)

        self._session_id = result['session_id']

    @_commandline_args
    async def get_profile(self, session: Optional[aiohttp.ClientSession] = None) -> Optional[Profile]:
        result = await self.request('v1.0/profile/get', session=session)
        return self._response_data_single(Profile, result, 'profile')

    # Flats-related API
    @_commandline_args
    async def get_flats(self, session: Optional[aiohttp.ClientSession] = None) -> List[Flat]:
        result = await self.request('v1.0/flat/get', session=session)
        return self._response_data_list(Flat, result)

    @_commandline_args(flat_id=int)
    async def get_water_counters(
            self,
            flat_id: int,
            session: Optional[aiohttp.ClientSession] = None
    ) -> List[WaterCounter]:
        result = await self.request(
            'v1.2/widget/waterCountersGet',
            json={
                'flat_id': flat_id,
                'is_widget': True,
            },
            cache_key=flat_id,
            session=session
        )
        return self._response_data_list(WaterCounter, result, 'counters', flat_id=flat_id)

    async def push_water_counter_indications(
            self,
            flat_id: int,
            indications: Mapping[int, Union[int, float]],
            session: Optional[aiohttp.ClientSession] = None
    ) -> None:
        if not indications:
            raise ValueError('cannot push empty indications')
        if not flat_id:
            raise ValueError('cannot use empty flat_id')

        period = date.today().isoformat()
        await self.uncached_request('v1.0/watercounters/addValues', {
            'flat_id': flat_id,
            'counters_data': [
                {
                    'counter_id': counter_id,
                    'period': period,
                    'indication': int(indication)
                }
                for counter_id, indication in indications.items()
            ]
        }, session=session)
        self.clear_cache('v1.0/widget/waterCountersGet', cache_key=flat_id)

    @_commandline_args(flat_id=int, counter_id=int, indication=float)
    async def push_water_counter_indication(
            self,
            flat_id: int,
            counter_id: int,
            indication: Union[int, float],
            session: Optional[aiohttp.ClientSession] = None
    ) -> None:
        return await self.push_water_counter_indications(flat_id, {counter_id: indication}, session=session)

    # Vehicles-related API
    @_commandline_args
    async def get_vehicles_v1(self, session: Optional[aiohttp.ClientSession] = None) -> List[Vehicle]:
        result = await self.request('v1.0/transport/get', session=session)
        return self._response_data_list(Vehicle, result)

    @_commandline_args
    async def get_vehicles_v2(self, session: Optional[aiohttp.ClientSession] = None) -> List[Vehicle]:
        result = await self.request('v1.2/widget/transportGetInfoByCitizen', session=session)
        return self._response_data_list(Vehicle, result, 'vehicles')

    @_commandline_args
    async def get_vehicles(self, session: Optional[aiohttp.ClientSession] = None) -> List[Vehicle]:
        try:
            return await self.get_vehicles_v2(session=session)
        except MoscowPGUException:
            return await self.get_vehicles_v1(session=session)

    @_commandline_args(driving_license=str)
    async def get_driving_license_offenses(self, driving_license: str,
                                           session: Optional[aiohttp.ClientSession] = None) -> List[Offense]:
        result = await self.request(
            'v1.2/widget/offenceGetOffence',
            json={'drive_license': driving_license, 'is_widget': True},
            session=session,
            cache_key=driving_license
        )
        return self._response_data_list(Offense, result)

    @_commandline_args(certificate_series=str)
    async def get_vehicle_offenses(self, certificate_series: str,
                                   session: Optional[aiohttp.ClientSession] = None) -> List[Offense]:
        result = await self.request(
            'v1.2/widget/offenceGetOffence',
            json={'sts_number': certificate_series, 'is_widget': True},
            session=session,
            cache_key=certificate_series
        )
        return self._response_data_list(Offense, result)

    # Pets-related API
    @_commandline_args
    async def get_pets(self, session: Optional[aiohttp.ClientSession] = None) -> List[Pet]:
        result = await self.request('v1.0/pet/get', session=session)
        return self._response_data_list(Pet, result)

    # Medicine-related API
    @_commandline_args
    async def get_patients(self, session: Optional[aiohttp.ClientSession] = None) -> List[Patient]:
        result = await self.request('v1.1/patient/get', session=session)
        return self._response_data_list(Patient, result)

    # Electro API
    @_commandline_args(flat_id=int)
    async def get_electric_balance(self, flat_id: int, session: Optional[aiohttp.ClientSession] = None) -> ElectricBalance:
        """
        Get current balance for given flat.
        :type flat_id: Flat identifier (`Flat.id`)
        :type session: (optional) HTTP session
        :return:
        """
        result = await self.request(
            'v1.1/electrocounters/getBalance',
            json={'flat_id': flat_id},
            cache_key=flat_id,
            session=session,
        )
        return self._response_data_single(ElectricBalance, result, flat_id=flat_id)

    @_commandline_args(flat_id=int)
    async def get_electric_last_indications(self, flat_id: int, session: Optional[aiohttp.ClientSession] = None) -> List[ElectricIndication]:
        """
        Get last indications for electric meters.
        :type flat_id: Flat identifier (`Flat.id`)
        :type session: (optional) HTTP session
        :return: List of last electric indications
        """
        result = await self.request(
            'v1.1/electrocounters/getLastIndications',
            json={'flat_id': flat_id},
            cache_key=flat_id,
            session=session,
        )
        return self._response_data_list(ElectricIndication, result, 'indications', flat_id=flat_id)

    @_commandline_args(flat_id=int)
    async def get_electric_counter_info(self, flat_id: int, session: Optional[aiohttp.ClientSession] = None) -> ElectricCounterInfo:
        """
        Get information about electric meter.
        :type flat_id: Flat identifier (`Flat.id`)
        :type session: (optional) HTTP session
        :return: Electric counter information
        """
        result = await self.request(
            'v1.1/electrocounters/getCounterInfo',
            json={'flat_id': flat_id},
            cache_key=flat_id,
            session=session
        )
        return self._response_data_single(ElectricCounterInfo, result, flat_id=flat_id)

    @_commandline_args(flat_id=int)
    async def get_electric_indications_status(self, flat_id: int, session: Optional[aiohttp.ClientSession] = None) -> ElectricIndicationsStatus:
        """
        I
        :param flat_id:
        :param session:
        :return: Indications check result
        """
        result = await self.request(
            'v1.1/electrocounters/checkAddIndication',
            json={'flat_id': flat_id},
            cache_key=flat_id,
            session=session
        )
        return self._response_data_single(ElectricIndicationsStatus, result, flat_id=flat_id)

    @_commandline_args(flat_id=int,
                       indication_t1=float,
                       indication_t2=(float, False),
                       indication_t3=(float, False),
                       perform_checks=(bool, False, True))
    async def push_electric_indications(
            self,
            flat_id: int,
            indication_t1: Union[float, Iterable[float]],
            indication_t2: Optional[float] = None,
            indication_t3: Optional[float] = None,
            perform_checks: bool = True,
            session: Optional[aiohttp.ClientSession] = None
    ) -> None:
        """
        Push electric indications for given flat ID.
        :param flat_id: Flat ID
        :param indication_t1: First indication | Iterable object containing indications
        :param indication_t2: Second indication
        :param indication_t3: Third indication
        :param perform_checks: Perform preliminary checks whether submission is possible
        :param session: Client session
        """
        json_data = {}

        if isinstance(indication_t1, Iterable):
            if not (indication_t2 is None and indication_t3 is None):
                raise ValueError('conflicting parameters provided')

            for i, indication in enumerate(indication_t1, start=1):
                json_data['indication_T%d' % (i,)] = float(indication)

        else:
            json_data['indication_T1'] = float(indication_t1)

            if indication_t2 is not None:
                json_data['indication_T2'] = float(indication_t2)

            if indication_t3 is not None:
                json_data['indication_T3'] = float(indication_t3)

        if perform_checks:
            # Check 1: Whether submission period is active
            check_result = await self.get_electric_indications_status(flat_id=flat_id, session=session)
            if check_result.check_code:
                raise ErrorResponseException(check_result.check_code, check_result.check_message)

            # Check 2: Whether indications count equals to available indications count
            check_result = await self.get_electric_counter_info(flat_id=flat_id, session=session)
            if not check_result.zones:
                raise ErrorResponseException(-1, 'Zones are not available')
            if len(check_result.zones) != len(json_data):
                raise ErrorResponseException(-1, 'Invalid zones count')

            # Check 3: Wheter no new indications are less than previous indications
            check_result = await self.get_electric_last_indications(flat_id=flat_id)
            if check_result:
                for last_indication in check_result:
                    if last_indication.indication is None:
                        continue

                    new_value = json_data['indication_' + last_indication.zone_name]
                    if new_value < last_indication.indication:
                        raise ErrorResponseException(-1, f'New indication ({new_value}) in zone '
                                                         f'"{last_indication.zone_name}" is '
                                                         f'less than existing indication '
                                                         f'({last_indication.indication})')

        json_data['flat_id'] = flat_id

        result = await self.uncached_request(
            'v1.1/electrocounters/addIndication',
            json=json_data,
            session=session
        )
        self.clear_cache([
            'v1.1/electrocounters/getLastIndications',
            'v1.1/electrocounters/getCounterInfo',
            'v1.1/electrocounters/getBalance',
        ], cache_key=flat_id)

        return result

    # Federal judges API
    @_commandline_args
    async def get_fssp_short(self, session: Optional[aiohttp.ClientSession] = None) -> List[FSSPDebt]:
        result = await self.request('v1.3/widget/fsspData', session=session)
        return self._response_data_list(FSSPDebt, result)

    @_commandline_args(first_name=str,
                       last_name=str,
                       middle_name=(str, False),
                       birth_date=(lambda x: date.fromisoformat(str(x)), True))
    async def get_fssp_detailed(
            self,
            first_name: str,
            last_name: str,
            middle_name: Optional[str],
            birth_date: date,
            session: Optional[aiohttp.ClientSession] = None
    ) -> List[FSSPDebt]:
        result = await self.request('v1.1/fssp/search', json={
            "firstname": first_name,
            "lastname": last_name,
            "middlename": middle_name,
            "birthdate": birth_date.strftime('%d.%m.%Y'),
        }, session=session)
        result = [{
            **r,
            "firstname": first_name,
            "lastname": last_name,
            "middlename": middle_name,
            "birthdate": birth_date.strftime('%d.%m.%Y'),
        } for r in result]
        return self._response_data_list(FSSPDebt, result)

    @_commandline_args
    async def get_profile_fssp_detailed(self, session: Optional[aiohttp.ClientSession] = None) -> List[FSSPDebt]:
        result = await self.get_profile(session=session)
        return await result.get_fssp_detailed(session=session)

    @_commandline_args(flat_id=int,
                       begin=(lambda x: date.fromisoformat(x), True),
                       end=(lambda x: date.fromisoformat(x), False))
    async def get_flat_epds(self, flat_id: int, begin: date, end: Optional[date] = None,
                            session: Optional[aiohttp.ClientSession] = None) -> List[EPD]:
        if begin is not None:
            if end is None:
                end = last_day_of_month(begin)
        elif end is not None:
            if end.month == 1:
                begin = end.replace(year=end.year-1, month=12)
            else:
                begin = end.replace(month=end.month-1)

        json_params = {'flat_id': flat_id}
        if begin and end:
            json_params.update({'begin_period': begin.strftime('%d.%m.%Y'), 'end_period': end.strftime('%d.%m.%Y')})

        result = await self.request('v1.2/epd/get', json_params, session=session, cache_key=(flat_id, begin, end))

        return self._response_data_list(EPD, result)


class MoscowPGUException(Exception):
    pass


class ErrorResponseException(MoscowPGUException):
    pass


class AuthenticationException(ErrorResponseException):
    pass


async def command_line_main():
    import sys
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('-u', '--username', required=True)
    parser.add_argument('-p', '--password', required=True)
    parser.add_argument('--json', action='store_true', default=False, help='Output in JSON format')
    parser.add_argument("-v", "--verbose", dest="verbosity", action="count", default=0,
                        help="Verbosity (between 1-4 occurrences with more leading to more "
                             "verbose logging). CRITICAL=0, ERROR=1, WARN=2, INFO=3, "
                             "DEBUG=4")

    log_levels = {
        0: logging.CRITICAL,
        1: logging.ERROR,
        2: logging.WARN,
        3: logging.INFO,
        4: logging.DEBUG,
    }

    subparsers = parser.add_subparsers(title='available commands', dest='method', required=True)

    for cmd_name, (cmd_method, cmd_args) in _COMMANDLINE_ARGS.items():
        cmd_parser = subparsers.add_parser(cmd_name, help=getattr(cmd_method, '__doc__', None))

        for arg_name, (arg_type, arg_required, cmd_default) in cmd_args.items():
            arg = '--' + arg_name

            if arg_type == bool:
                if cmd_default:
                    action = 'store_false'
                    cmd_default = True
                else:
                    action = 'store_true'
                    cmd_default = False

                cmd_parser.add_argument(arg, required=arg_required, action=action, default=cmd_default)

            elif arg_required:
                cmd_parser.add_argument(arg, type=arg_type, required=True)

            elif cmd_default is not None:
                cmd_parser.add_argument(arg, type=arg_type, default=cmd_default)

            else:
                cmd_parser.add_argument(arg, type=arg_type)

    try:
        # noinspection PyUnresolvedReferences
        import argcomplete
    except ImportError:
        pass
    else:
        argcomplete.autocomplete(parser)

    args = parser.parse_args()
    config = _COMMANDLINE_ARGS[args.method]
    method = config[0]
    kwargs = dict(map(lambda x: (x, getattr(args, x)), config[1].keys()))

    logging.basicConfig(level=log_levels[min(args.verbosity, max(log_levels.keys()))])

    try:
        api = API(username=args.username, password=args.password)

        if args.method != 'authenticate':
            await api.authenticate()

        result = await method(api, **kwargs)

    except MoscowPGUException as e:
        print("Error encountered: %s" % (e,), file=sys.stderr)
        sys.exit(1)

    else:
        if result is None:
            if getattr(method, '__annotations__', {}).get('return') in [type(None), None]:
                print('OK')
            else:
                print('Not found', file=sys.stderr)
                sys.exit(1)
        else:
            if isinstance(result, ResponseDataClass):
                # noinspection PyUnusedLocal
                def attr_filter(a: attr.Attribute, v: Any):
                    return not isinstance(v, API)
                result = attr.asdict(result, filter=attr_filter, recurse=True)

            elif isinstance(result, Collection) and all(map(lambda x: isinstance(x, ResponseDataClass), result)):
                result = list(map(lambda x: attr.asdict(x, filter=lambda a, v: not isinstance(v, API)), result))

            if args.json:
                import json

                def converter(x):
                    if isinstance(x, timedelta):
                        if x.microseconds == 0:
                            return int(x.total_seconds())
                        return x.total_seconds()
                    return str(x)

                print(json.dumps(result, indent=4, sort_keys=False, ensure_ascii=False, default=converter))

            else:
                from pprint import pprint
                pprint(result)

        sys.exit(0)


def command_line_sync_main():
    _loop = asyncio.get_event_loop()
    _loop.run_until_complete(command_line_main())
    _loop.close()


if __name__ == '__main__':
    command_line_sync_main()
