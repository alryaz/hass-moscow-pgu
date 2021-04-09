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
from typing import Optional, Dict, Mapping, Any, List, Hashable, Callable, Union, Type, Tuple, Collection, TypeVar

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


_COMMANDLINE_ARGS: Dict[str, Tuple[Callable, Dict[str, Tuple[Callable[[Any], Any], bool]]]] = {}


def _commandline_args(__command_name: Union[Callable[['API'], Any], Optional[str]] = None, **kwargs: Union[Tuple[Callable[[Any], Any], bool], Callable[[Any], Any]]):
    def _decorator(api_method: Callable):
        _COMMANDLINE_ARGS[__command_name if isinstance(__command_name, str) else api_method.__name__] = (
            api_method,
            {
                cmd_arg: cmd_type if isinstance(cmd_type, tuple) else (cmd_type, True)
                for cmd_arg, cmd_type in kwargs.items()
            }
        )
        return api_method

    if callable(__command_name):
        return _decorator(__command_name)

    return _decorator


@attr.s(kw_only=True, auto_attribs=True)
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
    def from_api_response_dict(cls, api: 'API', response_dict: Mapping[str, Any], *args, **kwargs):
        obj = cls.from_response_dict(response_dict, *args, **kwargs)
        obj.api = api
        return obj

    @classmethod
    def from_response_dict(cls, response_dict: Mapping[str, Any]) -> 'ResponseDataClass':
        raise NotImplementedError


@attr.s(kw_only=True, auto_attribs=True)
class ResponseDataClassWithID(ResponseDataClass, ABC):
    id: Any = None


@attr.s(kw_only=True, auto_attribs=True)
class Profile(ResponseDataClass):
    first_name: Optional[str] = None
    middle_name: Optional[str] = None
    last_name: Optional[str] = None
    birth_date: Optional[date] = None
    email: Optional[str] = None
    phone_number: Optional[str] = None
    email_confirmed: Optional[bool] = None
    driving_license_number: Optional[str] = None
    snils: Optional[str] = None
    driving_license_issue_date: Optional[date] = None

    @classmethod
    def from_response_dict(cls, response_dict: Mapping[str, Any]) -> 'Profile':
        birth_date = get_none(response_dict, 'birthdate', date_from_russian)

        driving_license_issue_date = get_none(response_dict, 'drive_issue_date')
        if driving_license_issue_date:
            driving_license_issue_date = date_from_russian(driving_license_issue_date)

        return cls(
            first_name=get_none(response_dict, 'firstname'),
            middle_name=get_none(response_dict, 'middlename'),
            last_name=get_none(response_dict, 'lastname'),
            birth_date=birth_date,
            email=get_none(response_dict, 'email'),
            phone_number=get_none(response_dict, 'msisdn'),
            email_confirmed=get_none(response_dict, 'email_confirmed'),
            snils=get_none(response_dict, 'snils'),
            driving_license_issue_date=driving_license_issue_date,
            driving_license_number=get_none(response_dict, 'drive_license'),
        )

    @ResponseDataClass.method_requires_api
    async def get_driving_license_offenses(self, session: Optional[aiohttp.ClientSession] = None) -> List['Offense']:
        if self.driving_license_number is None:
            raise ValueError('driving license number is empty or not set')
        return await self.api.get_driving_license_offenses(self.driving_license_number, session=session)

    @ResponseDataClass.method_requires_api
    async def get_fssp_detailed(self, session: Optional[aiohttp.ClientSession] = None) -> List['FSSPDebt']:
        return await self.api.get_fssp_detailed(
            first_name=self.first_name,
            last_name=self.last_name,
            middle_name=self.middle_name,
            birth_date=self.birth_date,
            session=session,
        )


@attr.s(kw_only=True, auto_attribs=True)
class WaterIndication(ResponseDataClass):
    counter_id: Optional[int] = None
    period: Optional[date] = None
    indication: Optional[float] = None

    @classmethod
    def from_response_dict(cls, response_dict: Mapping[str, Any], counter_id: Optional[int] = None) -> 'ResponseDataClass':
        return cls(
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


@attr.s(kw_only=True, auto_attribs=True)
class WaterCounter(ResponseDataClassWithID):
    id: Optional[int] = None
    flat_id: Optional[int] = None
    type: Optional[WaterCounterType] = None
    code: Optional[int] = None
    checkup_date: Optional[date] = None
    indications: Optional[List[WaterIndication]]

    @classmethod
    def from_response_dict(cls, response_dict: Mapping[str, Any], flat_id: Optional[int] = None) -> 'WaterCounter':
        water_counter_id = get_none(response_dict, 'counterId', int)
        indications = get_none(response_dict, 'indications',
                               lambda x: WaterIndication.from_response_dict(x, counter_id=water_counter_id))
        return cls(
            id=water_counter_id,
            flat_id=flat_id,
            type=get_none(response_dict, 'type', lambda x: WaterCounterType(int(x))),
            code=get_none(response_dict, 'num', str),
            checkup_date=get_none(response_dict, 'checkup', lambda x: date.fromisoformat(x.split('+')[0])),
            indications=indications,
        )

    @classmethod
    def from_api_response_dict(cls, api: 'API', response_dict: Mapping[str, Any], *args, **kwargs):
        indications = None
        if 'indications' in response_dict:
            response_dict = dict(response_dict)
            indications = response_dict.pop('indications')

        result: WaterCounter = super().from_api_response_dict(api, response_dict, *args, **kwargs)

        if indications:
            water_counter_id = get_none(response_dict, 'counterId', int)
            result.indications = [
                WaterIndication.from_api_response_dict(result.api, indication, counter_id=water_counter_id)
                for indication in indications
            ]

        return result

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


@attr.s(kw_only=True, auto_attribs=True)
class Flat(ResponseDataClassWithID):
    id: Optional[str] = None
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
    def from_response_dict(cls, response_dict: Mapping[str, Any]):
        return cls(
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

    @ResponseDataClass.method_requires_api
    async def get_water_counters(self, session: Optional[aiohttp.ClientSession] = None) -> List[WaterCounter]:
        return await self.api.get_water_counters(self.id, session=session)

    @ResponseDataClass.method_requires_api
    async def push_water_counter_indications(self, indications: Mapping[int, Union[int, float]], session: Optional[aiohttp.ClientSession] = None) -> None:
        return await self.api.push_water_counter_indications(self.id, indications, session=session)

    @ResponseDataClass.method_requires_api
    async def push_water_counter_indication(self, counter_id: int, indication: Union[int, float], session: Optional[aiohttp.ClientSession] = None) -> None:
        return await self.api.push_water_counter_indication(self.id, counter_id, indication, session=session)

    @ResponseDataClass.method_requires_api
    async def get_epds(self, begin: Optional[date] = None, end: Optional[date] = None, session: Optional[aiohttp.ClientSession] = None):
        return await self.api.get_flat_epds(self.id, begin=begin, end=end, session=session)


@attr.s(kw_only=True, auto_attribs=True)
class Vehicle(ResponseDataClassWithID):
    id: Optional[str] = None
    name: Optional[str] = None
    license_plate: Optional[str] = None
    certificate_series: Optional[str] = None
    is_evacuated: Optional[bool] = None

    @classmethod
    def from_response_dict(cls, response_dict: Mapping[str, Any]):
        return cls(
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
        return self.api.get_vehicle_offenses(self.certificate_series, session=session)


@attr.s(kw_only=True, auto_attribs=True)
class Patient(ResponseDataClassWithID):
    id: Optional[int] = None
    number: Optional[str] = None
    birth_date: Optional[date] = None
    first_name: Optional[str] = None
    middle_name: Optional[str] = None
    last_name: Optional[str] = None

    @classmethod
    def from_response_dict(cls, response_dict: Mapping[str, Any]):
        birth_date = get_none(response_dict, 'birthdate')
        if birth_date is not None:
            birth_date = date_from_russian(birth_date)

        return cls(
            id=get_none(response_dict, 'id'),
            birth_date=birth_date,
            first_name=get_none(response_dict, 'firstname'),
            middle_name=get_none(response_dict, 'middlename'),
            last_name=get_none(response_dict, 'lastname'),
        )


@attr.s(kw_only=True, auto_attribs=True)
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
    def from_response_dict(cls, response_dict: Mapping[str, Any]):
        birth_date = get_none(response_dict, 'birthdate', date_from_russian)

        return cls(
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


@attr.s(kw_only=True, auto_attribs=True)
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
    def from_response_dict(cls, response_dict: Mapping[str, Any]):
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


@attr.s(kw_only=True, auto_attribs=True)
class EPD(ResponseDataClass):
    uin: Optional[str] = None
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
    def from_response_dict(cls, response_dict: Mapping[str, Any]):
        amount = get_none(response_dict, 'amount')
        insurance_amount = get_none(response_dict, 'insurance_amount', float_russian)
        amount_with_insurance = get_none(response_dict, 'amount_with_insurance')

        if amount_with_insurance is None and amount is not None and insurance_amount is not None:
            amount_with_insurance = amount + insurance_amount

        return cls(
            uin=get_none(response_dict, 'uin'),
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
    def total(self) -> Optional[float]:
        amount = self.amount_with_insurance or self.amount
        if amount is not None:
            paid = self.payment_amount or 0
            return amount - paid


@attr.s(kw_only=True, auto_attribs=True)
class FSSPDebt(ResponseDataClassWithID):
    enterpreneur_id: Optional[int] = None
    description: Optional[str] = None
    total: Optional[float] = None
    unpaid: Optional[float] = None
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
    unpaid_enterpreneur: Optional[float] = None
    unpaid_bailiff: Optional[float] = None
    rise_date: Optional[date] = None
    osp_system_site_id: Optional[int] = None
    bailiff_name: Optional[str] = None
    bailiff_phone: Optional[str] = None

    @property
    def paid(self) -> Optional[float]:
        if self.total is not None and self.unpaid is not None:
            # @TODO: this might be incorrect...
            return self.total - self.unpaid

    @classmethod
    def from_response_dict(cls, response_dict: Mapping[str, Any]):
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
            enterpreneur_id=get_none(response_dict, 'ip_id'),
            description=get_none(response_dict, 'id_debttext'),
            total=get_none(response_dict, 'id_debtsum',
                           converter_if_value=float_russian, default=0.0),
            unpaid=get_none(response_dict, 'ip_debt_rest_total',
                            converter_if_value=float_russian, default=0.0),
            unload_date=unload_date,
            unload_status=get_none(response_dict, 'unload_status'),
            first_name=get_none(response_dict, 'firstname'),
            middle_name=get_none(response_dict, 'middlename'),
            last_name=get_none(response_dict, 'lastname'),
            birth_date=birth_date,

            id=get_none(response_dict, 'id_number'),
            kladr_main_name=get_none(response_dict, 'kladr_main_name'),
            kladr_street_name=get_none(response_dict, 'kladr_street_name'),
            rise_date=rise_date,
            unpaid_enterpreneur=get_none(response_dict, 'ip_debt_rest_ip', float_russian, default=0.0),
            unpaid_bailiff=get_none(response_dict, 'ip_debt_rest_fine', float_russian, default=0.0),
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


class API:
    BASE_EMP_URL = "https://emp.mos.ru"

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

        if not cache_disabled and (sub_url, cache_key) in self.__cache:
            created_at, result = self.__cache[(sub_url, cache_key)]
            if timestamp() - created_at > self.cache_lifetime:
                _LOGGER.debug('Cache expired on %s / %s', sub_url, cache_key)
                del self.__cache[(sub_url, cache_key)]
            else:
                _LOGGER.debug('Cache hit on %s / %s', sub_url, cache_key)
                return result

        result = await self.uncached_request(sub_url, json=json, session=session)

        if not cache_disabled:
            _LOGGER.debug('Saved cache on %s / %s', sub_url, cache_key)
            self.__cache[(sub_url, cache_key)] = (cache_save_time, result)

        return result

    def clear_cache(self, sub_url: Optional[str] = None, cache_key: Optional[str] = None):
        if sub_url is None and cache_key is None:
            self.__cache.clear()
        else:
            cache_indices = list(self.__cache.keys())
            for ex_sub_url, ex_cache_key in cache_indices:
                if (sub_url is None or ex_sub_url == sub_url) and (cache_key is None or ex_cache_key == cache_key):
                    _LOGGER.debug('Cleared cache index %s / %s', ex_sub_url, ex_cache_key)
                    del self.__cache[(ex_sub_url, ex_cache_key)]

    # API response helpers
    def _response_data_list(
            self,
            as_cls: Type[TResponse],
            result: Union[List[Mapping[str, Any]], Mapping[str, Any]],
            key: Optional[str] = None,
            **kwargs
    ) -> List[TResponse]:
        if key is not None:
            result = (result or {}).get(key)
        return list(map(lambda x: as_cls.from_api_response_dict(self, x, **kwargs), result or []))

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
    async def get_profile(self, session: Optional[aiohttp.ClientSession] = None) -> Profile:
        result = await self.request('v1.0/profile/get', session=session)
        return Profile.from_api_response_dict(self, result.get('profile', {}))

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
        result = await self.request('v1.2/widget/waterCountersGet', json={
            'flat_id': flat_id,
            'is_widget': True,
        }, session=session)
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
        self.clear_cache('v1.0/widget/waterCountersGet')

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

        for arg, (arg_type, arg_required) in cmd_args.items():
            cmd_parser.add_argument('--' + arg, type=arg_type, required=arg_required)

    try:
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
                result = attr.asdict(result, filter=lambda a, v: not isinstance(v, API))

            elif isinstance(result, Collection) and all(map(lambda x: isinstance(x, ResponseDataClass), result)):
                result = list(map(lambda x: attr.asdict(x, filter=lambda a, v: not isinstance(v, API)), result))

            if args.json:
                import json
                print(json.dumps(result, indent=4, sort_keys=False, ensure_ascii=False, default=str))

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
