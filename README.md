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

[<img alt="Автомобиль без штрафов" src="https://raw.githubusercontent.com/alryaz/hass-moscow-pgu/main/images/vehicle_without_offenses.png" height="240">](https://raw.githubusercontent.com/alryaz/hass-moscow-pgu/main/images/vehicle_without_offenses.png)
[<img alt="Водительское удостоверение со штрафами" src="https://raw.githubusercontent.com/alryaz/hass-moscow-pgu/main/images/driving_license_with_offenses.png" height="240">](https://raw.githubusercontent.com/alryaz/hass-moscow-pgu/main/images/driving_license_with_offenses.png)
[<img alt="Счётчик холодной воды" src="https://raw.githubusercontent.com/alryaz/hass-moscow-pgu/main/images/cold_water_meter.png" height="240">](https://raw.githubusercontent.com/alryaz/hass-moscow-pgu/main/images/cold_water_meter.png)
[<img alt="Передача показаний" src="https://raw.githubusercontent.com/alryaz/hass-moscow-pgu/main/images/push_indication_service.png" height="240">](https://raw.githubusercontent.com/alryaz/hass-moscow-pgu/main/images/push_indication_service.png)


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

## Использование
Ниже представлены примеры использования доступных сенсоров.

### Счётчики воды (`sensor.(cold|hot)_water_counter_*`)
Значение объекта равно последним показаниям счётчика.

| Атрибут                  | Тип               | Описание                                  |
| ------------------------ | ----------------- | ----------------------------------------- |
| `id`                     | `int`             | Внутренний идентификатор счётчика         |
| `code`                   | `str`             | Серийный номер счётчика                   |
| `indications`            | `dict[str,float]` | Зачтённые показания за периоды            |
| `last_indication_period` | `str` (`date`)    | Период последнего переданного показания   |
| `last_indication_value`  | `float`           | Значение последнего переданного показания |
| `checkup_date`           | `str` (`date`)    | Дата поверки счётчика                     |
| `flat_id`                | `int`             | Внутренний идентификатор квартиры         |

### <a name="service_push_indication"></a>Передача показаний &mdash; `moscow_pgu.push_indications`

Компонент позволяет запускать службу `moscow_pgu.push_indications` с параметрами:

| Раздел   | Параметр       | Описание                  | Значения                             |
| -------- | -------------- | ------------------------- | ------------------------------------ |
| `data`   | `indication`   | Показание                 | Число / Числа через запятую / Список |
| `data`   | `service_type` | Тип показаний             | `electric`, `water` <sup>1</sup>     |
| `data`   | `force`        | Игнорировать проверки     | `true` / `false` (опционально)       |
| `data`   | `dry_run`      | Сухой прогон <sup>2</sup> | `true` / `false` (опционально)       |
| `target` | `entity_id`    | Какой счётчик обновить    | Объект счётчика / квартиры           |

_<sup>1</sup> Требуется только для объектов квартиры._<br>
_<sup>2</sup> Не передаёт показания, а только симулирует попытку._

Данная служба автоматически определяет попытку передать показание меньшее, чем имеющееся
количество показаний. Проверку передачи возможно отключить, _**ОДНАКО ДЕЛАТЬ ЭТО НАСТОЯТЕЛЬНО НЕ РЕКОМЕНДУЕТСЯ**_ в связи
с возможными отрицательными последствиями.

Ниже указан пример вызова службы:
```yaml
service: moscow_pgu.push_indications
data:
  indication: 205
target:
  entity_id: sensor.hot_water_counter_123451616
```


### Транспортные средства (`sensor.vehicle_*`)
Значение объекта равно:
- _если указан номер СТС в ЛК_, сумме всех штрафов на автомобиль;
- _иначе_, значение `unknown` (_"неизв."_).

### Взыскания ФССП (`sensor.fssp_debts_*`)
Значение объекта равно сумме всех неуплаченных взысканий.

| Атрибут       | Тип            | Описание      |
| ------------- | -------------- | ------------- |
| `first_name`  | `str`          | Имя           |
| `last_name`   | `str`          | Фамилия       |
| `middle_name` | `str`          | Отчество      |
| `birth_date`  | `str` (`date`) | Дата рождения |
| `debts`       | `list[dict]`   | Список долгов |

#### Параметры объектов списка долгов
| Ключ                  | Тип            | Описание                                    |
| --------------------- | -------------- | ------------------------------------------- |
| `enterpreneur_id`     | `str`          | Внутренний идентификатор предпринимателя    |
| `description`         | `str`          | Описание взыскания                          |
| `rise_date`           | `str` (`date`) | Дата создания взыскания                     |
| `total`               | `float`        | Полная сумма взыскания                      |
| `unpaid_enterpreneur` | `float`        | Неуплаченный долг на предпринимателя        |
| `unpaid_bailiff`      | `float`        | Неуплаченный штраф ФССП                     |
| `unload_date`         | `str` (`date`) | Дата передачи дела в ФССП                   |
| `unload_status`       | `str`          | Состояние передачи дела в ФССП              |
| `kladr_main_name`     | `str`          | Название населённого пункта предпринимателя |
| `kladr_street_name`   | `str`          | Название улицы предпринимателя              |
| `bailiff_name`        | `str`          | Имя судебного пристава по взысканию         |
| `bailiff_phone`       | `str`          | Телефон судебного пристава по взысканию     |
