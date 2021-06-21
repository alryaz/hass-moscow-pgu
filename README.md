
[<img src="https://raw.githubusercontent.com/alryaz/hass-moscow-pgu/main/images/header.png" height="100">](https://www.mos.ru/uslugi/)
# _Московские Госуслуги_ для HomeAssistant
> Предоставление информации о текущем состоянии ваших аккаунтов в Госуслуги Москвы.
> - Передача показаний по счётчикам ЖКХ (вода, электричество)
> - Проверка штрафов ГИБДД (по номеру В/У и СТС)
> - Проверка штрафов ФССП

>[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)
>[![Лицензия](https://img.shields.io/badge/%D0%9B%D0%B8%D1%86%D0%B5%D0%BD%D0%B7%D0%B8%D1%8F-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
>[![Поддержка](https://img.shields.io/badge/%D0%9F%D0%BE%D0%B4%D0%B4%D0%B5%D1%80%D0%B6%D0%B8%D0%B2%D0%B0%D0%B5%D1%82%D1%81%D1%8F%3F-%D0%B4%D0%B0-green.svg)](https://github.com/alryaz/hass-moscow-pgu/graphs/commit-activity)
>
>[![Пожертвование Yandex](https://img.shields.io/badge/%D0%9F%D0%BE%D0%B6%D0%B5%D1%80%D1%82%D0%B2%D0%BE%D0%B2%D0%B0%D0%BD%D0%B8%D0%B5-Yandex-red.svg)](https://money.yandex.ru/to/410012369233217)
>[![Пожертвование PayPal](https://img.shields.io/badge/%D0%9F%D0%BE%D0%B6%D0%B5%D1%80%D1%82%D0%B2%D0%BE%D0%B2%D0%B0%D0%BD%D0%B8%D0%B5-Paypal-blueviolet.svg)](https://www.paypal.me/alryaz)

Данная интеграция предоставляет возможность системе HomeAssistant опрашивать API Портала Московских Госуслуг.

## Скриншоты

(Возможно увеличить, нажав на картинку и перейдя по ссылке)

<details>
  <summary><b>Автомобиль без штрафов</b></summary>  
  <img src="https://raw.githubusercontent.com/alryaz/hass-moscow-pgu/main/images/vehicle_without_offenses.png" alt="Автомобиль без штрафов">
</details>

<details>
  <summary><b>Водительское удостоверение со штрафами</b></summary>  
  <img src="https://raw.githubusercontent.com/alryaz/hass-moscow-pgu/main/images/driving_license_with_offenses.png" alt="Водительское удостоверение со штрафами">
</details>

<details>
  <summary><b>Счётчик холодной воды</b></summary>  
  <img src="https://raw.githubusercontent.com/alryaz/hass-moscow-pgu/main/images/cold_water_meter.png" alt="Счётчик холодной воды">
</details>

<details>
  <summary><b>Передача показаний</b></summary>  
  <img src="https://raw.githubusercontent.com/alryaz/hass-moscow-pgu/main/images/push_indication_service.png" alt="Передача показаний">
</details>

<details>
  <summary><b>Школьный дневник</b></summary>  
  <img src="https://raw.githubusercontent.com/alryaz/hass-moscow-pgu/main/images/push_indication_service.png" alt="Школьный дневник">
</details>


<hr>

## Установка

### Посредством HACS

1. Откройте HACS (через `Extensions` в боковой панели)
1. Добавьте новый произвольный репозиторий:
   1. Выберите `Integration` (`Интеграция`) в качестве типа репозитория
   1. Введите ссылку на репозиторий: `https://github.com/alryaz/hass-moscow-pgu`
   1. Нажмите кнопку `Add` (`Добавить`)
   1. Дождитесь добавления репозитория (занимает до 10 секунд)
   1. Теперь вы должны видеть доступную интеграцию `Moscow PGU (Госуслуги Москвы)` в списке новых интеграций.
1. Нажмите кнопку `Install` чтобы увидеть доступные версии
1. Установите последнюю версию нажатием кнопки `Install`
1. Перезапустите HomeAssistant

_Примечание:_ Не рекомендуется устанавливать ветку `main`. Она используется исключительно для разработки. 

<hr>

### Вручную

Клонируйте репозиторий во временный каталог, затем создайте каталог `custom_components` внутри папки конфигурации
вашего HomeAssistant (если она еще не существует). Затем переместите папку `moscow_pgu` из папки `custom_components` 
репозитория в папку `custom_components` внутри папки конфигурации HomeAssistant.
Пример (при условии, что конфигурация HomeAssistant доступна по адресу `/mnt/homeassistant/config`) для Unix-систем:
```
git clone https://github.com/alryaz/hass-moscow-pgu.git hass-moscow-pgu
mkdir -p /mnt/homeassistant/config/custom_components
mv hass-moscow-pgu/custom_components/moscow_pgu /mnt/homeassistant/config/custom_components
```

<hr>

## Конфигурация

### Через интерфейс HomeAssistant

1. Откройте `Настройки` -> `Интеграции`
1. Нажмите внизу справа страницы кнопку с плюсом
1. Введите в поле поиска `Moscow PGU` или `Госуслуги Москвы`
   1. Если по какой-то причине интеграция не была найдена, убедитесь, что HomeAssistant был перезапущен после
        установки интеграции.
1. Выберите первый результат из списка
1. Введите данные вашей учётной записи для ЛК _"Госуслуги Москвы"_
1. Нажмите кнопку `Продолжить`
1. Через несколько секунд начнётся обновление; проверяйте список ваших объектов на наличие
   объектов, чьи названия начинаются на `MES`.

<hr>

### Через `configuration.yaml`

#### Базовая конфигурация

Для настройки данной интеграции потребуются данные авторизации в ЛК Госуслуги Москвы.  
`username` - Имя пользователя (телефон / адрес эл. почты)  
`password` - Пароль
```yaml
moscow_pgu:
  username: !secret moscow_pgu_username
  password: !secret moscow_pgu_password
```

#### Несколько пользователей

Возможно добавить несколько пользователей.
Для этого вводите данные, используя пример ниже:
```yaml
moscow_pgu:
    # First account
  - username: !secret first_moscow_pgu_username
    password: !secret first_moscow_pgu_password

    # Second account
  - username: !secret second_moscow_pgu_username
    password: !secret second_moscow_pgu_password

    # Third account
  - username: !secret third_moscow_pgu_username
    password: !secret third_moscow_pgu_password 
```

#### Изменение интервалов обновления

Частота обновления данных (`scan_interval`) по умолчанию: для каждой функции по-разному
```yaml
moscow_pgu:
  ...
  # Интервал обновления данных
  scan_interval:
    hours: 6
    seconds: 3
    minutes: 1
    ...

  # ... также возможно задать секундами
  scan_interval: 21600

  # ... также возможно задать для определённых функций
  # Неупомянутые функции будут принимать их значения по умолчанию
  scan_interval:
    water_counters:
      days: 1
    fssp_debts: 3600
    profile:
      hours: 6
      minutes: 30
```

#### Конфигурация по умолчанию


```yaml
moscow_pgu:
- device_info:
    app_version: 3.10.0.19 (122)
    device_agent: Android 11 (SDK 30) Xiaomi sagit (MI 6)
    device_os: Android
    guid: ''
    user_agent: okhttp/4.9.0
  driving_licenses: []
  name_format:
    children: Child - {identifier}
    diaries: Diary - {identifier}
    driving_licenses: Driving license {identifier}
    electric_counters: Electric Counter {identifier}
    flats: Flat - {identifier}
    fssp_debts: FSSP Debts - {identifier}
    profile: Profile - {identifier}
    vehicles: Vehicle {identifier}
    water_counters: '{type} Water Counter - {identifier}'
  scan_interval:
    children:
      hours: 1
    diaries:
      hours: 1
    driving_licenses:
      hours: 2
    electric_counters:
      hours: 24
    flats:
      hours: 24
    fssp_debts:
      hours: 24
    profile:
      hours: 24
    vehicles:
      hours: 2
    water_counters:
      hours: 24
  token: null
  track_fssp_profiles: []

```

<hr>

## Использование

Ниже представлены примеры использования доступных сенсоров.

### Счётчик водоснабжения (`sensor.*_water_counter_*`)
- **Конфигурационный ключ:** `water_counters`  
- **Частота обновления по умолчанию:** 86400 секунд  
- **Минимальная частота обновления:** 30 секунд  
- **Формат названия объекта по умолчанию:** _{type} Water Counter - {identifier}_  


Значение объекта равно последним показаниям счётчика.

#### Атрибуты

_Список может быть не полон. Некоторые атрибуты появляются в момент получения ответа от сервера._

| Атрибут | Тип(ы) | Значение |
| --- | --- | --- |
| `id` | `int` | Идентификатор счётчика |
| `code` | `str` | Номер счётчика |
| `type` | `str` | Тип счётчика (горячое = `hot`, холодное = `cold`) |
| `flat_id` | `int` | Идентификатор квартиры |
| `checkup_date` | `str` | Дата поверки |
| `last_indication_value` | `float` | Значение последнего переданного показания |
| `last_indication_period` | `str` | Период последней передачи показаний |



<hr>

### Ребёнок (`sensor.child_*`)
- **Конфигурационный ключ:** `children`  
- **Частота обновления по умолчанию:** 3600 секунд  
- **Минимальная частота обновления:** 30 секунд  
- **Формат названия объекта по умолчанию:** _Child - {identifier}_  


Общая информация о ребёнке + если ребёнок находится сейчас в школе.

#### Атрибуты

_Список может быть не полон. Некоторые атрибуты появляются в момент получения ответа от сервера._

| Атрибут | Тип(ы) | Значение |
| --- | --- | --- |
| `school` | `str` | Школа, в которой учится |
| `last_name` | `str` | Фамилия ребёнка |
| `pay_limit` | `float` | Ограничение по оплате |
| `first_name` | `str` | Имя ребёнка |
| `middle_name` | `str` | Отчество ребёнка |
| `is_at_school` | `bool` | Находится ли ребёнок в школе |
| `last_update_date` | `NoneType`/`date` | Последнее обновление состояния |



<hr>

### Транспортное средство (`sensor.vehicle_*`)
- **Конфигурационный ключ:** `vehicles`  
- **Частота обновления по умолчанию:** 7200 секунд  
- **Минимальная частота обновления:** 30 секунд  
- **Формат названия объекта по умолчанию:** _Vehicle {identifier}_  


Значение объекта равно:
- _если указан номер СТС в ЛК_, сумме всех штрафов на автомобиль;
- _иначе_, значение `unknown` (_"неизв."_).

#### Атрибуты

_Список может быть не полон. Некоторые атрибуты появляются в момент получения ответа от сервера._

| Атрибут | Тип(ы) | Значение |
| --- | --- | --- |
| `id` | `str` | Идентификатор |
| `is_evacuated` | `bool` | Статус эвакуации |
| `license_plate` | `str` | Государственный регистрационный номер |
| `certificate_series` | `NoneType`/`str` | Номер СТС |



<hr>

### Взыскания ФССП (`sensor.fssp_debts_*`)
- **Конфигурационный ключ:** `fssp_debts`  
- **Частота обновления по умолчанию:** 86400 секунд  
- **Минимальная частота обновления:** 30 секунд  
- **Формат названия объекта по умолчанию:** _FSSP Debts - {identifier}_  


Значение объекта равно сумме всех неуплаченных взысканий.

#### Атрибуты

_Список может быть не полон. Некоторые атрибуты появляются в момент получения ответа от сервера._

| Атрибут | Тип(ы) | Значение |
| --- | --- | --- |
| `last_name` | `str` | Фамилия (запрашивающего) |
| `birth_date` | `str` | Дата рождения (запрашивающего) |
| `first_name` | `str` | Имя (запрашивающего) |
| `middle_name` | `str` | Отчество (запрашивающего) |




<hr>

### Школьный дневник (`sensor.diary_*`)
- **Конфигурационный ключ:** `diaries`  
- **Частота обновления по умолчанию:** 3600 секунд  
- **Минимальная частота обновления:** 30 секунд  
- **Формат названия объекта по умолчанию:** _Diary - {identifier}_  


Перечень оценок ученика в школе.

Состояние объекта равно минимальной оценке из списка доступных.
Оценки по предметам указаны в виде атрибутов объекта (названия на русском языке).

#### Атрибуты

_Список может быть не полон. Некоторые атрибуты появляются в момент получения ответа от сервера._

| Атрибут | Тип(ы) | Значение |
| --- | --- | --- |
| `*` | `float` | Оценка по предмету |



<hr>

### Ребёнок (`sensor.child_*`)
- **Конфигурационный ключ:** `children`  
- **Частота обновления по умолчанию:** 3600 секунд  
- **Минимальная частота обновления:** 30 секунд  
- **Формат названия объекта по умолчанию:** _Child - {identifier}_  


Общая информация о ребёнке + если ребёнок находится сейчас в школе.

#### Атрибуты

_Список может быть не полон. Некоторые атрибуты появляются в момент получения ответа от сервера._

| Атрибут | Тип(ы) | Значение |
| --- | --- | --- |
| `school` | `str` | Школа, в которой учится |
| `last_name` | `str` | Фамилия ребёнка |
| `pay_limit` | `float` | Ограничение по оплате |
| `first_name` | `str` | Имя ребёнка |
| `middle_name` | `str` | Отчество ребёнка |
| `is_at_school` | `bool` | Находится ли ребёнок в школе |
| `last_update_date` | `NoneType`/`date` | Последнее обновление состояния |


<hr>

### Профиль (`sensor.profile_*`)
- **Конфигурационный ключ:** `profile`  
- **Частота обновления по умолчанию:** 86400 секунд  
- **Минимальная частота обновления:** 30 секунд  
- **Формат названия объекта по умолчанию:** _Profile - {identifier}_  

> @ TODO @

#### Атрибуты

_Список может быть не полон. Некоторые атрибуты появляются в момент получения ответа от сервера._

| Атрибут | Тип(ы) | Значение |
| --- | --- | --- |
| `email` | `str` | Адрес электронной почты |
| `last_name` | `str` | Фамилия |
| `birth_date` | `str` | Дата рождения |
| `first_name` | `str` | Имя |
| `middle_name` | `str` | Отчество |
| `phone_number` | `str` | Номер телефона |
| `email_confirmed` | `str` (`bool`) | Статус подтверждения адреса электронной почты |
| `driving_license_number` | `NoneType`/`str` | Номер водительского удостоверения |
| `driving_license_issue_date` | `NoneType`/`str` | Дата выдачи водительского удостоверения |


<hr>

### Счётчик электроэнергии (`sensor.electric_counter_*`)
- **Конфигурационный ключ:** `electric_counters`  
- **Частота обновления по умолчанию:** 86400 секунд  
- **Минимальная частота обновления:** 30 секунд  
- **Формат названия объекта по умолчанию:** _Electric Counter {identifier}_  

> @ TODO @

#### Атрибуты

_Список может быть не полон. Некоторые атрибуты появляются в момент получения ответа от сервера._

| Атрибут | Тип(ы) | Значение |
| --- | --- | --- |
| `type` | `str` | Тип счётчика |
| `state` | `str` | Текущее состояние счётчика |
| `status` | `str` | Коментарий к состоянию передачи показаний |
| `flat_id` | `int` | Идентификатор |
| `debt_amount` | `float` | Сумма задолжености |
| `checkup_date` | `str` | Дата поверки |
| `charges_amount` | `float` | Сумма начислений |
| `returns_amount` | `float` | Сумма возвратов |
| `balance_message` | `str` | Коментарий к балансу |
| `payments_amount` | `float` | Сумма учтённых платежей |
| `settlement_date` | `str` (`date`) | ... |
| `submit_end_date` | `str` (`date`) | Дата начала периода передачи показаний |
| `transfer_amount` | `float` | ... |
| `submit_available` | `bool` | Доступность передачи показаний |
| `submit_begin_date` | `str` (`date`) | Дата начала периода передачи показаний |
| `whole_part_length` | `int` | Длина целой части (кол-во цифр) |
| `decimal_part_length` | `int` | Точность счётчика |
| `indications.t1.tariff` | `str` | Тариф зоны T1 |
| `indications.t1.zone_name` | `str` | Название зоны Т1 |
| `indications.t1.indication` | `float` | Показание по зоне Т1 |
| `indications.t2.tariff` | `str` | Тариф зоны T2 |
| `indications.t2.zone_name` | `str` | Название зоны Т1 |
| `indications.t2.indication` | `float` | Показание по зоне Т2 |
| `indications.t3.tariff` | `str` | Тариф зоны T2 |
| `indications.t3.zone_name` | `str` | Название зоны Т1 |
| `indications.t3.indication` | `float` | Показание по тарифной зоне Т3 |



<hr>

## Службы

### <a name="service_push_indications"></a>Передача показаний &mdash; `moscow_pgu.push_indications`

Компонент позволяет запускать службу `moscow_pgu.push_indications` с параметрами:

| Раздел   | Параметр       | Описание                  | Значения                             |
| -------- | -------------- | ------------------------- | ------------------------------------ |
| `data`   | `indications` | Показание | Число / Числа через запятую / Список |
| `data`   | `service_type` | Тип показаний | `electric`, `water` <sup>1</sup> |
| `data`   | `force` | Игнорировать проверки | `true` / `false` (опционально) |
| `data`   | `dry_run` | Сухой прогон <sup>2</sup> | `true` / `false` (опционально) |
| `target` | `entity_id` | Какой счётчик обновить | Объект счётчика |

_<sup>1</sup> Требуется только для объектов квартиры._<br>
_<sup>2</sup> Не передаёт показания, а только симулирует попытку._

Данная служба применима к:
- Счётчик электроэнергии (`sensor.electric_counter_*`)
- Счётчик водоснабжения (`sensor.*_water_counter_*`)

Данная служба автоматически определяет попытку передать показание меньшее, чем имеющееся
количество показаний. Проверку передачи возможно отключить, _**ОДНАКО ДЕЛАТЬ ЭТО НАСТОЯТЕЛЬНО 
НЕ РЕКОМЕНДУЕТСЯ**_ в связи с возможными отрицательными последствиями.

Ниже указан пример вызова службы:
```yaml
service: moscow_pgu.push_indications
data:
  indication: 205
target:
  entity_id: sensor.hot_water_counter_123541
```
