# ARGOS
## Direct Ecowitt GW2000 Integration
### Technical Specification for Codex

**Version:** 1.0 (Draft)

---

# Purpose

The objective of this task is to redesign ARGOS so that the Ecowitt GW2000 gateway becomes a first-class data source.

Instead of periodically downloading observations from the Ecowitt Cloud API, ARGOS shall receive meteorological observations directly from the gateway using the Ecowitt **Customized** service.

This architecture:

- removes unnecessary dependencies on cloud services;
- reduces latency to approximately one minute;
- allows complete ownership of the ingestion pipeline;
- simplifies synchronization;
- enables local processing even without Internet access.

The Ecowitt Cloud API shall remain implemented exclusively as a **secondary data source** used for historical recovery (*backfill*) and consistency verification.

The direct HTTP receiver shall therefore be considered the **primary source of truth**.

---

# Overall architecture

```
                WS90
                 │
          RF proprietary link
                 │
                 ▼
             GW2000A
                 │
     HTTP POST every 60 seconds
                 │
                 ▼
      ARGOS FastAPI Receiver
                 │
      ┌──────────┴──────────┐
      │                     │
      ▼                     ▼
 Raw payload           Normalization
      │                     │
      └──────────┬──────────┘
                 ▼
           PostgreSQL
                 │
      ┌──────────┴──────────┐
      ▼                     ▼
 Dashboard            Analytics
                 │
                 ▼
             Alert engine
```

The Ecowitt Cloud API shall **never** be used as the main acquisition mechanism.

Its only purpose is:

- historical reconstruction;
- verification;
- recovery after outages.

---

# Engineering principles

The implementation shall follow the principles below.

## 1. Raw data preservation

Every message received from the GW2000 shall be preserved exactly as transmitted.

No information shall be discarded.

Unknown fields shall never generate exceptions.

Every payload shall remain available for future reprocessing.

---

## 2. Strong separation of responsibilities

The project shall clearly separate:

- HTTP transport
- validation
- parsing
- unit conversion
- persistence
- analytics
- visualization

No module shall perform more than one responsibility.

---

## 3. Forward compatibility

Future Ecowitt sensors shall work without requiring changes to the HTTP endpoint.

Adding support for a new sensor shall require modifications only inside the parser and normalization layer.

---

## 4. Fail-safe ingestion

Receiving observations shall never stop because a single field cannot be parsed.

Individual field failures shall be logged while preserving the remainder of the observation.

---

## 5. Reproducibility

A clean clone of the repository shall be executable using only:

```bash
uv sync
uv run alembic upgrade head
uv run uvicorn argos.main:app
```

No manual installation steps shall be required.

---

# Mandatory technology stack

The implementation shall use:

- Python ≥ 3.12
- uv
- pyproject.toml
- FastAPI
- Uvicorn
- SQLAlchemy 2.x
- Alembic
- Pydantic v2
- PostgreSQL (production)
- SQLite (development)
- Docker
- Docker Compose
- Ruff
- mypy
- pytest
- GitHub Actions

The project shall not use requirements.txt as the primary dependency definition.

---

# Repository structure

The repository shall follow approximately this structure.

```
src/
    argos/
        api/
        config/
        database/
        models/
        parsers/
        repositories/
        schemas/
        services/
        utils/
        cli.py
        main.py

tests/

alembic/

docker/

Dockerfile

docker-compose.yml

README.md

pyproject.toml

.env.example
```

Each package shall have a single responsibility.

Business logic shall never appear inside FastAPI route handlers.

---

# Required development workflow

Every feature shall follow the same workflow.

1. Inspect existing implementation.

2. Describe the proposed changes.

3. Implement incrementally.

4. Execute:

```bash
uv run pytest
```

5. Execute:

```bash
uv run ruff check .
```

6. Execute:

```bash
uv run mypy src
```

7. Only after all tests succeed continue to the next feature.

No feature shall be considered complete unless tests are passing.

---

# Runtime configuration

Configuration shall rely exclusively on environment variables.

Mandatory variables:

```env
APP_ENV=development

DATABASE_URL=sqlite:///./var/argos.db

LOCAL_TIMEZONE=Europe/Madrid

LOG_LEVEL=INFO

ECOWITT_INGEST_TOKEN=<random token>

ECOWITT_CAPTURE_RAW=false

ECOWITT_EXPECTED_INTERVAL_SECONDS=60

ECOWITT_OFFLINE_AFTER_SECONDS=180
```

The application shall refuse to start if the ingestion token is missing.

---

# Data flow

Incoming observation:

```
GW2000

↓

FastAPI

↓

Authentication

↓

Validation

↓

Raw payload persistence

↓

Parser

↓

Normalization

↓

Database

↓

Dashboard
```

At no point shall the original payload be modified.

Normalized observations shall always reference the corresponding raw payload.

---

# Design philosophy

ARGOS shall be developed as an extensible scientific platform rather than merely a weather logger.

The architecture shall therefore prioritize:

- reproducibility;
- maintainability;
- traceability;
- extensibility;
- observability;
- scientific reproducibility.

Future sensor families (soil moisture, PM sensors, lightning detectors, CO₂ sensors, leaf wetness sensors, LoRa devices, irrigation controllers and third-party instrumentation) shall integrate without redesigning the ingestion architecture.

# PART 2 — Database Design

## Database philosophy

The database shall distinguish between:

1. raw observations;
2. normalized observations;
3. gateway metadata;
4. ingestion metadata;
5. system metadata.

The objective is to guarantee complete traceability.

No normalized record shall exist without its corresponding raw payload.

Likewise, every normalized observation shall preserve the identifier of the raw report from which it originated.

---

# Entity relationship overview

```

GW2000

↓

ecowitt_raw_reports

↓

weather_observations

↓

daily_statistics
monthly_statistics
annual_statistics

```

Additional tables:

```

gateways

unknown_fields

ingestion_events

data_gaps

```

---

# Table: gateways

Purpose:

Store every Ecowitt gateway known by ARGOS.

Columns

```
id

uuid

name

mac_address

station_type

firmware_version

hardware_version

first_seen_at

last_seen_at

enabled

metadata_json

created_at

updated_at
```

Constraints

```
mac_address UNIQUE
```

Indexes

```
mac_address

last_seen_at
```

---

# Table: ecowitt_raw_reports

Purpose

Store the original payload exactly as transmitted.

Columns

```
id

gateway_id

received_at_utc

device_timestamp_utc

http_method

source_ip

content_type

payload_json

payload_hash

headers_json

query_string

processing_time_ms

parser_version

created_at
```

Constraints

```
FOREIGN KEY gateway_id

UNIQUE(payload_hash)
```

Indexes

```
gateway_id

received_at_utc

device_timestamp_utc
```

The payload shall always remain immutable.

No UPDATE operations shall modify previously received payloads.

---

# Table: weather_observations

Purpose

Store normalized meteorological variables.

Columns

```
id

gateway_id

raw_report_id

observed_at_utc

received_at_utc

indoor_temperature_c

indoor_humidity_pct

outdoor_temperature_c

outdoor_humidity_pct

dew_point_c

feels_like_c

vpd_kpa

absolute_pressure_hpa

relative_pressure_hpa

wind_direction_deg

wind_speed_ms

wind_gust_ms

daily_max_gust_ms

solar_radiation_wm2

uv_index

rain_rate_mm_h

rain_event_mm

rain_hour_mm

rain_day_mm

rain_week_mm

rain_month_mm

rain_year_mm

piezo_rain_mm

battery_voltage

signal_dbm

created_at
```

All meteorological fields shall accept NULL.

Never invent missing values.

---

# Table: unknown_fields

Purpose

Automatically catalogue every previously unseen Ecowitt field.

Columns

```
id

field_name

sample_value

occurrence_count

first_seen_at

last_seen_at

normalized_mapping

notes
```

Whenever a new field appears:

increase occurrence_count

update last_seen_at

keep the first sample value

No exception shall be generated.

---

# Table: ingestion_events

Purpose

Audit the ingestion pipeline.

Columns

```
id

gateway_id

raw_report_id

event_type

severity

message

processing_time_ms

created_at
```

Possible event types

```
REPORT_RECEIVED

UNKNOWN_FIELD

INVALID_VALUE

DUPLICATE

AUTH_FAILURE

PARSER_WARNING

BACKFILL

```

---

# Table: data_gaps

Purpose

Detect missing observations.

Columns

```
id

gateway_id

gap_start

gap_end

expected_reports

received_reports

resolved

resolution_method

created_at

resolved_at
```

Possible resolution methods

```
BACKFILL

MANUAL

IGNORED

UNKNOWN
```

---

# Referential integrity

Every observation shall reference:

```
gateway

↓

raw_report

↓

normalized observation
```

Deleting raw payloads shall not be allowed.

Cascade delete shall therefore never remove historical observations.

---

# Duplicate detection

Duplicates shall be detected using:

```
SHA256(

gateway

+

device timestamp

+

normalized payload

)
```

Two identical payloads shall never generate two observations.

Instead:

```
HTTP 200

duplicate=true
```

shall be returned.

---

# Time management

Internally

Always UTC.

Presentation layer

Europe/Madrid.

No naive datetime objects shall exist inside the database.

Timezone conversions shall only occur inside the visualization layer.

---

# Payload versioning

Every parser shall expose:

```
PARSER_VERSION
```

The version shall be stored together with every raw payload.

Future parser improvements shall therefore never invalidate historical data.

---

# Database migrations

Alembic shall manage every schema modification.

Schema changes shall never require manual SQL.

Every migration must be reversible whenever technically feasible.

---

# Repository pattern

FastAPI routes shall never communicate directly with SQLAlchemy.

Instead:

```
API

↓

Service

↓

Repository

↓

Database
```

Repositories shall encapsulate every SQL operation.

---

# Performance requirements

The database shall comfortably support:

- one observation every minute
- several years of history
- multiple gateways
- additional sensor families

Target:

More than 10 million observations without architectural redesign.

---

# Future extensibility

The schema shall anticipate future support for:

- soil moisture sensors

- leaf wetness sensors

- PM2.5 sensors

- PM10 sensors

- CO₂ sensors

- lightning detectors

- LoRa gateways

- irrigation controllers

without requiring structural redesign of the ingestion pipeline.

# PART 3 — Ecowitt Parser, Field Mapping and Unit Conversion

## Parser objective

The Ecowitt parser shall convert an arbitrary incoming gateway payload into:

1. an immutable raw representation;
2. a normalized observation;
3. a list of parser warnings;
4. a catalogue update for unknown fields.

The parser shall be tolerant by design.

A malformed or unsupported individual field shall not invalidate the complete observation.

The parser shall never assume that every GW2000 firmware version emits exactly the same field names.

The implementation must be driven by real payloads captured from the gateway.

---

# Parser input

The parser shall accept:

```python
Mapping[str, str | int | float | None]
```

Possible sources:

- form-encoded HTTP body;
- query parameters;
- JSON used in tests;
- imported cloud API records;
- replayed raw payloads.

The parser must normalize input keys before matching them.

Recommended key normalization:

```python
normalized_key = raw_key.strip()
```

Do not automatically lowercase keys before storing the raw payload.

For mapping purposes, case-insensitive comparison may be used where necessary.

The original field name must remain preserved.

---

# Parser output

Create a typed result object similar to:

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class EcowittParseResult:
    observed_at_utc: datetime
    normalized_values: dict[str, Any]
    unknown_fields: dict[str, Any]
    warnings: list[str]
    station_type: str | None
    gateway_identifier: str | None
    parser_version: str
```

The parser shall not persist data directly.

Persistence belongs to the ingestion service and repository layers.

---

# Parser version

Define a parser version constant:

```python
PARSER_VERSION = "1.0.0"
```

Store it with each raw report.

Whenever field mappings, aliases or conversion behaviour change materially, increment the parser version.

This allows historical payloads to be reprocessed reproducibly.

---

# Numeric parsing

Implement a safe numeric conversion helper.

Example:

```python
from decimal import Decimal, InvalidOperation


def parse_decimal(value: object) -> Decimal | None:
    if value is None:
        return None

    if isinstance(value, str):
        value = value.strip()
        if value == "":
            return None

    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
```

Requirements:

- empty strings return `None`;
- invalid strings return `None`;
- parser warnings record invalid values;
- no exception propagates to the route handler;
- do not silently replace invalid values with zero.

---

# Boolean parsing

Some future integrations may emit Boolean-like fields.

Support:

```text
true
false
1
0
yes
no
on
off
```

Unknown Boolean representations shall return `None`.

---

# Timestamp parsing

The field most commonly expected for device time is:

```text
dateutc
```

The implementation shall accept, at minimum:

```text
YYYY-MM-DD HH:MM:SS
YYYY-MM-DD+HH:MM:SS
YYYY-MM-DDTHH:MM:SS
YYYY-MM-DDTHH:MM:SSZ
```

The parser shall:

1. treat the Ecowitt `dateutc` field as UTC;
2. attach UTC explicitly;
3. never interpret it using the server local timezone;
4. preserve the original timestamp string;
5. fall back to `received_at_utc` if parsing fails.

Example:

```python
from datetime import UTC, datetime


def parse_ecowitt_datetime(
    value: str | None,
    fallback: datetime,
) -> tuple[datetime, str | None]:
    if not value:
        return fallback, "missing dateutc"

    normalized = value.strip().replace("+", " ")

    formats = (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
    )

    for fmt in formats:
        try:
            parsed = datetime.strptime(normalized, fmt)
            return parsed.replace(tzinfo=UTC), None
        except ValueError:
            continue

    return fallback, f"invalid dateutc: {value!r}"
```

The exact accepted formats may be extended after capturing real gateway payloads.

---

# Unit conversion module

All unit conversions shall be placed in:

```text
src/argos/services/ecowitt_units.py
```

The parser shall not contain inline conversion constants.

Implement pure functions with unit tests.

---

# Temperature conversion

Ecowitt commonly transmits temperature in degrees Fahrenheit.

Formula:

```python
def fahrenheit_to_celsius(value_f: float) -> float:
    return (value_f - 32.0) * 5.0 / 9.0
```

Store normalized values in degrees Celsius.

Recommended database precision:

```text
0.01 °C
```

Do not round inside the conversion function unless required for serialization.

---

# Pressure conversion

Ecowitt commonly transmits pressure in inches of mercury.

Formula:

```python
def inhg_to_hpa(value_inhg: float) -> float:
    return value_inhg * 33.8638866667
```

Store normalized pressure in hectopascals.

Recommended database precision:

```text
0.01 hPa
```

---

# Wind conversion

Ecowitt commonly transmits wind speed in miles per hour.

Formula:

```python
def mph_to_mps(value_mph: float) -> float:
    return value_mph * 0.44704
```

Store normalized wind speed in metres per second.

Recommended database precision:

```text
0.001 m/s
```

---

# Rain conversion

Ecowitt commonly transmits precipitation in inches.

Formula:

```python
def inches_to_mm(value_in: float) -> float:
    return value_in * 25.4
```

Store normalized precipitation in millimetres.

Recommended database precision:

```text
0.001 mm
```

---

# Solar radiation

The expected Ecowitt field is commonly:

```text
solarradiation
```

Assume units:

```text
W/m²
```

Do not transform unless evidence from a real payload indicates otherwise.

Validate that values are numeric and non-negative.

Do not clamp high values automatically.

---

# UV index

Expected field:

```text
uv
```

Store as a dimensionless numeric value.

Do not force integer conversion because some firmware versions may report decimal values.

---

# Relative humidity

Expected fields may include:

```text
humidity
humidityin
humidity1
humidity2
...
```

Store values as percentage.

Validation rule:

```text
0 ≤ humidity ≤ 100
```

If outside this interval:

- preserve the raw value;
- set the normalized value to `NULL`, unless a later design decision says otherwise;
- add a parser warning.

Do not clamp values to the valid range.

---

# Wind direction

Expected field:

```text
winddir
```

Store in degrees clockwise from geographic north.

Validation rule:

```text
0 ≤ direction ≤ 360
```

Prefer normalizing `360` to `0` only if that behaviour is documented and tested.

Otherwise preserve the original numeric value.

---

# Vapour pressure deficit

Possible field:

```text
vpd
```

Do not assume the unit without verification from a real payload or Ecowitt protocol documentation.

Initial implementation strategy:

- preserve the raw value;
- map it to normalized `vpd_kpa` only after confirming the unit;
- document the confirmation source;
- add a test using a real anonymized payload.

Until confirmed, `vpd` must remain available in the raw payload and may be listed in the field catalogue.

---

# Indoor gateway fields

Recognize, when present:

```text
tempinf
humidityin
baromrelin
baromabsin
```

Proposed mappings:

```text
tempinf       → indoor_temperature_c
humidityin    → indoor_humidity_pct
baromrelin    → relative_pressure_hpa
baromabsin    → absolute_pressure_hpa
```

Apply the appropriate unit conversions.

---

# Outdoor temperature and humidity

Recognize, when present:

```text
tempf
humidity
```

Proposed mappings:

```text
tempf      → outdoor_temperature_c
humidity   → outdoor_humidity_pct
```

---

# Derived temperature fields

Potential fields:

```text
dewptf
feelslike
feelsLike
windchillf
heatindexf
```

Implement aliases.

Proposed mappings:

```text
dewptf       → dew_point_c
feelslike    → feels_like_c
feelsLike    → feels_like_c
windchillf   → wind_chill_c
heatindexf   → heat_index_c
```

Do not calculate these values independently if the gateway already sends them.

If ARGOS later calculates them, store them separately from device-reported values or record their derivation method.

---

# Wind fields

Recognize, when present:

```text
winddir
windspeedmph
windgustmph
maxdailygust
maxdailygustmph
```

Proposed mappings:

```text
winddir           → wind_direction_deg
windspeedmph      → wind_speed_ms
windgustmph       → wind_gust_ms
maxdailygust      → wind_max_daily_ms
maxdailygustmph   → wind_max_daily_ms
```

Because field names may vary, implement a configurable alias registry.

---

# Rainfall fields

Recognize the following common names when present:

```text
rainratein
eventrainin
hourlyrainin
dailyrainin
24hourrainin
weeklyrainin
monthlyrainin
yearlyrainin
totalrainin
```

Proposed mappings:

```text
rainratein      → rain_rate_mm_h
eventrainin     → rain_event_mm
hourlyrainin    → rain_hour_mm
dailyrainin     → rain_day_mm
24hourrainin    → rain_24h_mm
weeklyrainin    → rain_week_mm
monthlyrainin   → rain_month_mm
yearlyrainin    → rain_year_mm
totalrainin     → rain_total_mm
```

Every inch-based field shall be converted to millimetres.

Do not infer missing rain accumulations from other periods during ingestion.

---

# Piezoelectric rainfall fields

The WS90 uses a piezoelectric rain sensor.

Field names may differ from traditional tipping-bucket rain gauges.

Therefore:

1. preserve every field containing:
   - `rain`;
   - `piezo`;
   - `p_rain`;
   - other observed variants;

2. do not assume the mapping until a real payload is captured;

3. add aliases only after verification;

4. create tests from the actual anonymized payload.

Possible observed variants must be treated as provisional, not definitive.

The code must clearly distinguish:

```text
verified mappings
```

from:

```text
provisional aliases
```

---

# Device and gateway identification fields

Recognize, when present:

```text
PASSKEY
stationtype
model
runtime
freq
mac
macaddress
gateway
```

Potential mappings:

```text
stationtype  → gateway model and firmware hint
model        → model
runtime      → gateway runtime metadata
freq         → radio frequency metadata
mac          → gateway MAC
macaddress   → gateway MAC
```

Do not assume `PASSKEY` is a secret chosen by the user.

Treat it as sensitive identifying metadata and redact it from logs and diagnostic responses.

Preserve only a redacted or hashed representation where appropriate.

---

# Battery fields

Recognize possible battery field patterns:

```text
wh90batt
ws90batt
soilbatt1
soilbatt2
...
leafbatt1
pm25batt1
co2_batt
```

The unit and meaning may vary by sensor family.

Do not normalize all battery fields into a single generic unit without verification.

For the WS90:

- preserve the raw field;
- map to `ws90_battery` only after confirming whether the value represents volts, a status code or another scale;
- document the verified interpretation.

---

# Signal strength fields

Possible fields may include:

```text
wh90_sig
ws90_sig
wh90_rssi
ws90_rssi
```

Do not assume every signal field is measured in dBm.

Ecowitt may expose:

- an ordinal signal level;
- bars;
- an RSSI-like code;
- a true dBm value.

Therefore:

```text
ws90_signal_dbm
```

must only be populated when the payload is verified to contain dBm.

Otherwise use a more generic field such as:

```text
ws90_signal_raw
```

or preserve it only in the raw payload.

This distinction is important because the Ecowitt application may display dBm even when the custom HTTP payload uses another representation.

---

# Multi-channel temperature and humidity sensors

Support field patterns:

```text
temp1f
temp2f
...
temp8f

humidity1
humidity2
...
humidity8
```

Do not add one fixed database column for every possible future channel unless the existing architecture already requires it.

Preferred approach:

- preserve all fields in the raw report;
- normalize known channels into a generic sensor observation model;
- associate channel number, sensor type and gateway.

A future generic table may be:

```text
sensor_measurements
```

with fields:

```text
id
gateway_id
raw_report_id
sensor_family
channel
variable
value
unit
observed_at_utc
metadata_json
```

The initial meteorological table may still contain the principal WS90 variables.

---

# Soil moisture sensors

Support field patterns:

```text
soilmoisture1
soilmoisture2
...
soilmoisture16
```

Possible related battery fields:

```text
soilbatt1
soilbatt2
...
soilbatt16
```

Store soil moisture initially as a percentage-like reported value only after verifying the protocol semantics.

Do not interpret it directly as volumetric water content unless the sensor documentation confirms that meaning.

ARGOS must distinguish between:

```text
raw sensor scale
```

and:

```text
calibrated volumetric water content
```

These are not equivalent.

Future calibration metadata should include:

```text
sensor serial number
soil type
installation depth
calibration equation
calibration date
location
```

---

# Air quality sensors

Support possible field patterns:

```text
pm25_ch1
pm25_ch2
...
pm25_ch8

pm10_ch1
pm10_ch2
...
pm10_ch8
```

Possible related fields:

```text
pm25_avg_24h_ch1
pm10_avg_24h_ch1
```

Do not assume units without verification, although they are commonly mass concentration units.

Store raw values and map only verified fields.

---

# Lightning detector fields

Possible fields:

```text
lightning
lightning_num
lightning_time
lightning_distance
```

Do not assume whether:

```text
lightning
```

means distance, count or event state.

Use real payload evidence.

Potential normalized variables:

```text
lightning_distance_km
lightning_count
last_lightning_at_utc
```

---

# CO₂ sensors

Possible fields:

```text
co2
co2_24h
co2_batt
```

Potential mapping:

```text
co2       → co2_ppm
co2_24h   → co2_24h_ppm
```

Only activate this mapping after protocol confirmation.

---

# Leaf wetness sensors

Support possible patterns:

```text
leafwetness1
leafwetness2
...
leafbatt1
leafbatt2
...
```

Do not assume the wetness scale corresponds directly to percentage.

Store raw values until calibration and semantics are confirmed.

---

# Alias registry

Implement aliases in one explicit structure.

Example:

```python
FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "feels_like_f": (
        "feelslike",
        "feelsLike",
    ),
    "wind_max_daily_mph": (
        "maxdailygust",
        "maxdailygustmph",
    ),
    "ws90_battery_raw": (
        "wh90batt",
        "ws90batt",
    ),
}
```

Do not scatter aliases across multiple parser functions.

Each normalized variable shall have one authoritative alias definition.

---

# Verified and provisional mappings

Maintain two registries:

```python
VERIFIED_FIELD_MAPPINGS
PROVISIONAL_FIELD_MAPPINGS
```

A mapping becomes verified only when supported by at least one of:

1. an official Ecowitt protocol document;
2. an official Ecowitt implementation example;
3. a real payload captured from this GW2000 and cross-checked against the application;
4. a controlled test where a known environmental change produces the expected field response.

Provisional mappings must not silently populate scientifically interpreted fields unless explicitly enabled.

---

# Unknown field handling

For every input field not recognized:

1. preserve it in `payload_json`;
2. add it to `unknown_fields`;
3. update `ecowitt_field_catalog`;
4. store:
   - field name;
   - first-seen timestamp;
   - last-seen timestamp;
   - occurrence count;
   - sample value;
5. log it only the first time or at a controlled rate.

Do not log one warning per unknown field per minute indefinitely.

---

# Validation philosophy

Validation shall distinguish between:

```text
syntactic validity
```

and:

```text
scientific plausibility
```

Example:

```text
temperature = 70 °C
```

may be syntactically valid but scientifically suspicious.

The ingestion pipeline should still preserve the value.

Recommended behaviour:

- store the raw value;
- normalize if conversion is valid;
- attach a quality-control flag;
- do not discard automatically.

---

# Quality flags

Prepare a generic quality flag system.

Possible flags:

```text
OK
MISSING
INVALID_FORMAT
OUT_OF_RANGE
SUSPECT
DUPLICATE
BACKFILLED
DEVICE_TIME_INVALID
UNKNOWN_UNIT
UNVERIFIED_MAPPING
```

Do not hard-code quality logic into route handlers.

Quality control belongs to a dedicated service.

---

# Range checks

Initial conservative checks may include:

```text
relative humidity: 0–100 %
wind direction: 0–360°
UV index: ≥ 0
solar radiation: ≥ 0 W/m²
rain accumulation: ≥ 0 mm
wind speed: ≥ 0 m/s
pressure: positive
```

Temperature range checks must be broad enough not to reject extreme but valid conditions.

Range limits shall be configurable.

---

# Reprocessing raw data

Implement a command that can reparse historical raw payloads.

Example:

```bash
uv run argos ecowitt reprocess \
  --from 2026-07-01T00:00:00Z \
  --to 2026-07-31T23:59:59Z \
  --parser-version 1.1.0
```

Requirements:

- raw payloads remain immutable;
- normalized observations may be regenerated;
- reprocessing shall be idempotent;
- the parser version used shall be recorded;
- previous normalized versions must either be archived or replaced transactionally according to a documented policy.

---

# Real payload capture workflow

Before finalizing mappings:

1. enable raw capture;
2. configure the GW2000 Customized service;
3. receive at least 20 consecutive messages;
4. anonymize identifying values;
5. save one representative fixture;
6. compare fields against:
   - Ecowitt application values;
   - WS View Plus values;
   - sensor management screen;
7. classify each field as:
   - verified;
   - provisional;
   - unknown;
8. update tests accordingly.

Required fixture:

```text
tests/fixtures/ecowitt_gw2000a_v3_3_2_ws90.json
```

The implementation shall not claim complete field support before this step is completed.

---

# Minimum parser tests

Create tests for:

1. valid outdoor temperature conversion;
2. valid pressure conversion;
3. valid wind conversion;
4. valid rain conversion;
5. empty numeric field;
6. invalid numeric field;
7. missing `dateutc`;
8. invalid `dateutc`;
9. unknown field preservation;
10. case-variant alias;
11. duplicate aliases present simultaneously;
12. humidity outside 0–100;
13. negative rain value;
14. unsupported battery field;
15. unverified VPD unit;
16. WS90 field aliases;
17. preservation of the complete original payload;
18. parser version storage;
19. deterministic normalized output;
20. reprocessing idempotency.

---

# Acceptance criteria for the parser

The parser shall be considered complete when:

- no unknown field causes ingestion failure;
- all verified unit conversions pass tests;
- original values remain preserved;
- invalid fields produce warnings instead of crashes;
- timestamps are stored in UTC;
- aliases are centralized;
- real GW2000 payloads are covered by fixtures;
- unverified fields are not presented as scientifically confirmed;
- historical raw payloads can be reprocessed;
- parser output is deterministic.

# PART 4 — HTTP API, Authentication, Security and Ingestion Workflow

## API objective

The HTTP API shall provide a stable and minimal interface for receiving Ecowitt gateway observations and inspecting ingestion status.

The API must prioritize:

- reliability;
- low latency;
- deterministic behaviour;
- compatibility with the GW2000;
- safe handling of malformed requests;
- minimal exposure of internal implementation details.

The Ecowitt gateway endpoint is machine-to-machine infrastructure. It is not a general public API and should therefore remain narrow in scope.

---

# Main ingestion endpoint

Implement:

```http
POST /api/v1/ecowitt/upload/{ingest_token}
```

Temporarily support:

```http
GET /api/v1/ecowitt/upload/{ingest_token}
```

The GET variant is included only for compatibility testing and defensive support.

The preferred and documented method shall be POST.

---

# Accepted content types

The endpoint shall accept:

```text
application/x-www-form-urlencoded
```

This is the primary expected format.

It shall also accept:

```text
application/json
```

for manual tests and automated integration tests.

Query parameters may also be accepted for compatibility.

Unsupported content types shall return:

```http
415 Unsupported Media Type
```

unless a compatibility mode is explicitly enabled.

---

# Request parsing order

The endpoint shall process input using this order:

1. authenticate the URL token;
2. verify request size;
3. identify content type;
4. parse form, JSON or query parameters;
5. merge compatible parameter sources;
6. preserve the original request metadata;
7. invoke the ingestion service;
8. return a compact response.

Do not perform database writes before authentication succeeds.

---

# Payload source precedence

If the same field appears in several locations, define explicit precedence.

Recommended order:

```text
JSON body
form body
query string
```

Alternatively, reject ambiguous duplicate sources if the values differ.

The chosen policy must be documented and tested.

A safer approach is:

- merge all sources;
- if the same key appears with different values, preserve all raw sources;
- mark the report with an ambiguity warning;
- apply one deterministic precedence rule for normalization.

---

# Successful response

A successfully accepted report shall return:

```json
{
  "status": "ok",
  "accepted": true,
  "duplicate": false,
  "observation_id": 123
}
```

HTTP status:

```http
200 OK
```

A duplicate shall also return `200 OK`:

```json
{
  "status": "ok",
  "accepted": true,
  "duplicate": true,
  "observation_id": 123
}
```

The gateway must not be encouraged to retry valid duplicate messages unnecessarily.

---

# Response constraints

Responses to the GW2000 shall be:

- small;
- fast;
- deterministic;
- JSON encoded;
- free from internal stack traces;
- free from secrets;
- stable across releases.

Target response time under normal load:

```text
< 250 ms
```

Preferred target:

```text
< 100 ms
```

The implementation should prioritize persistence of the raw payload before expensive downstream work.

---

# Authentication model

The endpoint shall use a long random token embedded in the route:

```text
/api/v1/ecowitt/upload/{ingest_token}
```

Environment variable:

```env
ECOWITT_INGEST_TOKEN=replace-with-a-long-random-token
```

Generate the token with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

The token shall contain sufficient entropy.

Minimum recommended entropy:

```text
256 bits
```

---

# Token comparison

Use constant-time comparison.

Example:

```python
import secrets


def token_is_valid(received: str, expected: str) -> bool:
    return secrets.compare_digest(received, expected)
```

Do not compare tokens with a simple `==` when avoidable.

---

# Invalid token response

For an invalid token, return either:

```http
404 Not Found
```

or:

```http
403 Forbidden
```

Using `404` is preferable because it reveals less about the endpoint.

Example response:

```json
{
  "detail": "Not found"
}
```

Do not indicate whether the route exists but the token is incorrect.

Do not log the full invalid token.

---

# Token redaction

In logs, represent the token only as:

```text
prefix...suffix
```

or as a short cryptographic fingerprint.

Example:

```python
token_fingerprint = sha256(token.encode()).hexdigest()[:12]
```

Never log:

- full route paths containing the token;
- raw request URLs;
- reverse-proxy access logs without redaction.

The reverse proxy must also be configured to avoid exposing the token in ordinary access logs.

---

# Alternative future authentication

Prepare the architecture so that future versions may support:

- per-gateway tokens;
- rotating tokens;
- source IP allowlists;
- HMAC signatures;
- mTLS through an edge proxy;
- VPN-only ingestion.

Do not implement these unless needed.

The first version shall remain compatible with the actual capabilities of the GW2000.

---

# Maximum request size

Implement:

```env
ECOWITT_MAX_BODY_BYTES=65536
```

Default:

```text
64 KiB
```

Reject larger payloads with:

```http
413 Payload Too Large
```

The request body limit must be enforced before fully loading an arbitrarily large body into memory.

---

# Maximum field count

Add a configurable maximum number of fields.

Example:

```env
ECOWITT_MAX_FIELDS=512
```

If exceeded:

- preserve no partial observation;
- log a compact warning;
- return a controlled error.

Recommended status:

```http
422 Unprocessable Entity
```

or:

```http
413 Payload Too Large
```

Document the choice.

---

# Maximum field-name length

Recommended limit:

```text
128 characters
```

Fields exceeding the limit shall not be used as normalized keys.

They may be preserved only in a safe diagnostic representation if technically reasonable.

Do not permit field names to become SQL identifiers, file paths or log format strings.

---

# Maximum value length

Recommended default:

```text
4096 characters per field
```

Longer values shall be:

- rejected;
- truncated only in logs;
- never silently normalized.

The raw storage policy must be explicit.

---

# Rate limiting

Expected gateway behaviour:

```text
1 request every 60 seconds
```

Recommended per-source limit:

```text
20 requests per minute
```

This allows:

- retries;
- setup testing;
- burst tolerance.

Rate limiting must not block legitimate development testing unexpectedly.

Configuration:

```env
ECOWITT_RATE_LIMIT_PER_MINUTE=20
```

For production, rate limiting may be implemented:

- in the reverse proxy;
- in the application;
- or both.

Prefer the reverse proxy for coarse network limits and application logic for gateway-specific limits.

---

# Source IP handling

Record the apparent source IP.

If running behind a trusted reverse proxy, honor forwarding headers only from trusted proxies.

Do not trust arbitrary:

```text
X-Forwarded-For
```

headers from the public Internet.

Configuration should define trusted proxy addresses.

Example:

```env
TRUSTED_PROXY_CIDRS=127.0.0.1/32,10.0.0.0/8
```

---

# Timeout policy

The ingestion route shall have a bounded processing time.

Recommended application timeout:

```text
5 seconds
```

Normal requests should complete much faster.

Database operations must not hang indefinitely.

Configure:

- database connection timeout;
- reverse-proxy request timeout;
- application processing timeout.

---

# Error isolation

A failure in:

- one field;
- one conversion;
- one alias;
- one optional table update;

must not necessarily invalidate the full report.

Distinguish between:

```text
fatal ingestion errors
```

and:

```text
field-level warnings
```

Fatal errors include:

- invalid token;
- unreadable body;
- database unavailable before raw persistence;
- payload too large;
- unsupported content type.

Field-level warnings include:

- invalid temperature;
- unknown unit;
- unknown field;
- malformed optional timestamp.

---

# Error response model

Use a consistent response format:

```json
{
  "status": "error",
  "accepted": false,
  "code": "PAYLOAD_TOO_LARGE",
  "detail": "Request body exceeds the configured limit."
}
```

Do not expose:

- stack traces;
- SQL statements;
- environment variables;
- filesystem paths;
- tokens;
- database URLs.

---

# Idempotency

The endpoint shall be idempotent with respect to duplicate payloads.

If the same report is received several times:

- return `200 OK`;
- do not create repeated normalized observations;
- update duplicate counters;
- optionally update last-seen gateway metadata.

The duplicate decision belongs to the ingestion service, not the route handler.

---

# Route handler responsibilities

The FastAPI route handler shall do only the following:

1. validate token;
2. enforce transport-level limits;
3. extract request data;
4. create a transport metadata object;
5. call the ingestion service;
6. serialize the result.

It shall not:

- convert units;
- execute direct SQL;
- determine field aliases;
- calculate statistics;
- detect gaps;
- perform cloud backfill.

---

# Suggested request metadata schema

Create a schema similar to:

```python
from datetime import datetime
from pydantic import BaseModel


class IngestionRequestMetadata(BaseModel):
    received_at_utc: datetime
    http_method: str
    content_type: str | None
    source_ip: str | None
    user_agent: str | None
    query_string: str | None
    headers: dict[str, str]
```

Sensitive headers shall be filtered before persistence.

---

# Suggested ingestion result schema

```python
from pydantic import BaseModel


class EcowittIngestionResult(BaseModel):
    accepted: bool
    duplicate: bool
    raw_report_id: int | None
    observation_id: int | None
    warnings_count: int
    gateway_name: str | None
```

---

# Transaction strategy

Recommended sequence:

```text
BEGIN TRANSACTION

1. identify gateway
2. calculate payload hash
3. check duplicate
4. insert raw report
5. parse payload
6. insert normalized observation
7. update gateway last_seen_at
8. update unknown-field catalogue
9. insert ingestion events

COMMIT
```

If normalization fails unexpectedly after raw persistence, choose one documented policy.

Preferred policy:

- retain the raw report;
- mark parsing status as failed;
- commit the raw report and error event;
- allow later reprocessing.

This may require separating raw persistence and normalization into carefully managed transactions.

---

# Raw-first persistence

Scientific traceability favors preserving raw data even when normalization fails.

Therefore, recommended behaviour:

1. authenticate;
2. validate transport constraints;
3. persist raw report;
4. attempt normalization;
5. store normalized data if possible;
6. store parser error state if not.

The raw record should include:

```text
ingestion_status
```

Possible values:

```text
RECEIVED
PARSED
PARTIAL
FAILED
DUPLICATE
```

---

# Background processing

The first implementation may process parsing synchronously because the expected load is extremely low.

However, structure the code so parsing can later move to:

- an internal queue;
- Celery;
- Dramatiq;
- RQ;
- a database-backed worker;
- another message system.

Do not introduce a distributed queue in version 1 unless there is a demonstrated need.

---

# Health endpoint

Implement:

```http
GET /health
```

Basic response:

```json
{
  "status": "ok"
}
```

This endpoint shall not expose internal details.

---

# Readiness endpoint

Implement:

```http
GET /ready
```

Response when ready:

```json
{
  "status": "ready",
  "database": "ok",
  "migrations": "ok"
}
```

Return a non-2xx code if the application cannot accept ingestion traffic.

---

# Liveness endpoint

Optionally implement:

```http
GET /live
```

This endpoint shall indicate only that the process is alive.

It must not perform expensive database queries.

---

# Ecowitt status endpoint

Implement:

```http
GET /api/v1/ecowitt/status
```

Example response:

```json
{
  "gateway": "finca-gw2000",
  "model": "GW2000A",
  "firmware_version": "3.3.2",
  "last_report_at": "2026-07-10T09:42:00Z",
  "seconds_since_last_report": 34,
  "expected_interval_seconds": 60,
  "offline_after_seconds": 180,
  "online": true,
  "reports_last_24h": 1438,
  "duplicate_reports_last_24h": 0,
  "parser_errors_last_24h": 0
}
```

---

# Online/offline criterion

Configuration:

```env
ECOWITT_EXPECTED_INTERVAL_SECONDS=60
ECOWITT_OFFLINE_AFTER_SECONDS=180
```

The gateway shall be considered online if:

```text
current UTC time - last valid report time ≤ offline threshold
```

Do not use the device timestamp for this status calculation.

Use the server reception timestamp.

---

# Latest normalized observation endpoint

Implement:

```http
GET /api/v1/ecowitt/latest
```

Example response:

```json
{
  "gateway": "finca-gw2000",
  "observed_at_utc": "2026-07-10T09:42:00Z",
  "received_at_utc": "2026-07-10T09:42:03Z",
  "outdoor_temperature_c": 28.4,
  "outdoor_humidity_pct": 31,
  "relative_pressure_hpa": 993.5,
  "wind_speed_ms": 1.9,
  "wind_gust_ms": 2.7,
  "wind_direction_deg": 357,
  "solar_radiation_wm2": 502.2,
  "uv_index": 4,
  "rain_rate_mm_h": 0.0,
  "quality_flags": []
}
```

Fields not available shall be `null`.

---

# Latest raw report endpoint

Implement:

```http
GET /api/v1/ecowitt/raw/latest
```

This endpoint must redact sensitive information.

Redact at least:

```text
PASSKEY
token
password
secret
key
authorization
cookie
```

Example:

```json
{
  "received_at_utc": "...",
  "stationtype": "GW2000A_V3.3.2",
  "payload": {
    "PASSKEY": "***REDACTED***",
    "tempf": "83.12",
    "humidity": "31"
  }
}
```

Consider restricting this endpoint to authenticated administrative users in production.

---

# Field catalogue endpoint

Implement:

```http
GET /api/v1/ecowitt/fields
```

Return:

- field name;
- verified/provisional/unknown status;
- first seen;
- last seen;
- occurrence count;
- normalized mapping;
- sample value, safely truncated.

Support filters:

```text
status
field_name
seen_after
```

---

# Administrative reprocessing endpoint

Do not expose raw reprocessing publicly in the first version.

Prefer a CLI command.

If later exposed by API, require strong administrative authentication.

---

# API versioning

All Ecowitt data routes shall live under:

```text
/api/v1/
```

Breaking changes require a new version.

Do not silently change response semantics.

---

# OpenAPI documentation

FastAPI shall generate OpenAPI documentation.

For production:

- ingestion routes may be hidden from public interactive documentation if desired;
- administrative routes may require authentication;
- example payloads must use fake tokens and anonymized gateway data.

Never include the real ingestion token in OpenAPI examples.

---

# CORS policy

The ingestion endpoint does not require browser access.

Do not enable permissive CORS globally.

For the dashboard, configure only the exact required origins.

Avoid:

```text
Access-Control-Allow-Origin: *
```

in production unless justified.

---

# Reverse proxy

Recommended production arrangement:

```text
GW2000
  ↓
Caddy or Nginx
  ↓
FastAPI/Uvicorn
```

The reverse proxy shall manage:

- public port binding;
- request size limits;
- rate limiting;
- access logging;
- optional TLS termination;
- security headers for dashboard pages.

The reverse proxy logs must redact the token-bearing route.

---

# HTTP and HTTPS compatibility

Do not assume the GW2000 supports arbitrary HTTPS configurations.

The implementation process shall verify:

1. whether the Customized service supports HTTPS;
2. whether it validates certificates;
3. whether it accepts non-standard ports;
4. whether hostname resolution works correctly;
5. whether it follows redirects.

Do not use redirects for ingestion unless experimentally verified.

Recommended first controlled test:

```text
HTTP over local network
```

Then evaluate secure remote deployment options.

---

# Local-network deployment

For local testing:

```text
GW2000 and ARGOS computer on the same LAN
```

Run:

```bash
uv run uvicorn argos.main:app \
  --host 0.0.0.0 \
  --port 8080
```

Configure WS View Plus:

```text
Customized: enabled
Protocol: Ecowitt
Server IP / Hostname: 192.168.1.50
Path: /api/v1/ecowitt/upload/TOKEN
Port: 8080
Upload interval: 60 seconds
```

Do not include:

```text
http://
```

inside the hostname field unless the application explicitly requires it.

---

# Firewall documentation

The README shall include instructions for allowing TCP port `8080`.

## Linux with UFW

```bash
sudo ufw allow from 192.168.1.0/24 to any port 8080 proto tcp
```

Use the actual local subnet.

## Windows Defender Firewall

Document how to create an inbound TCP rule for port `8080`, preferably restricted to the private network profile.

## macOS

Document how to allow the Python/Uvicorn process or chosen port through the firewall.

---

# Manual ingestion test

Provide:

```bash
curl -X POST \
  "http://127.0.0.1:8080/api/v1/ecowitt/upload/TEST_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  --data-urlencode "stationtype=GW2000A_V3.3.2" \
  --data-urlencode "dateutc=2026-07-10 08:31:00" \
  --data-urlencode "tempf=83.12" \
  --data-urlencode "humidity=31"
```

Expected response:

```json
{
  "status": "ok",
  "accepted": true,
  "duplicate": false,
  "observation_id": 1
}
```

---

# Security tests

Create tests for:

1. valid token;
2. invalid token;
3. missing token;
4. oversized request body;
5. excessive field count;
6. unsupported content type;
7. malformed form body;
8. malformed JSON;
9. source IP spoofing attempt;
10. rate limit exceeded;
11. token absent from logs;
12. redaction of `PASSKEY`;
13. deterministic error response;
14. absence of stack traces;
15. duplicate request idempotency.

---

# Acceptance criteria for the API layer

The API layer shall be considered complete when:

- the GW2000 can send reports successfully;
- valid reports return `200 OK`;
- duplicates return `200 OK` without duplication;
- invalid tokens reveal no useful information;
- payload size limits are enforced;
- malformed fields do not crash the application;
- internal errors are not exposed;
- the latest observation can be queried;
- gateway online status is accurate;
- sensitive fields are redacted;
- route handlers contain no business logic;
- tests cover transport and security behaviour.

# PART 5 — Persistence, Duplicate Handling, Logging and Observability

## Persistence strategy

ARGOS shall preserve raw data first and normalize second.

Recommended flow:

```text
Receive request
→ authenticate
→ calculate payload hash
→ detect duplicate
→ store raw report
→ parse and normalize
→ store normalized observation
→ update gateway status
→ update field catalogue
→ record warnings or errors
```

A parsing error must not cause loss of the raw report.

---

## Transaction policy

Use database transactions for each ingestion attempt.

Preferred behaviour:

- raw report stored successfully;
- normalization attempted;
- normalized observation stored if valid;
- parser warnings stored separately;
- gateway `last_seen_at` updated;
- transaction committed.

If normalization fails unexpectedly:

- preserve the raw report;
- mark it as `FAILED` or `PARTIAL`;
- store the error event;
- allow later reprocessing.

---

## Duplicate detection

Calculate a stable SHA-256 hash from:

```text
gateway identifier
+
device timestamp
+
canonicalized payload
```

Canonicalization must:

- sort keys;
- serialize deterministically;
- preserve values without scientific reinterpretation.

Example:

```python
import hashlib
import json


def build_payload_hash(
    gateway_id: str,
    device_timestamp: str | None,
    payload: dict[str, object],
) -> str:
    canonical = json.dumps(
        {
            "gateway": gateway_id,
            "device_timestamp": device_timestamp,
            "payload": payload,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
```

Create a unique database constraint on the final hash.

---

## Duplicate behaviour

When a duplicate arrives:

- do not insert a second raw report;
- do not insert a second normalized observation;
- return `200 OK`;
- increment a duplicate counter;
- optionally update gateway `last_seen_at`.

Response:

```json
{
  "status": "ok",
  "accepted": true,
  "duplicate": true
}
```

Two records from the same minute are not duplicates if their payload differs.

---

## Database repositories

Create repository classes or functions for:

```text
GatewayRepository
RawReportRepository
WeatherObservationRepository
FieldCatalogRepository
IngestionEventRepository
DataGapRepository
```

FastAPI routes must never issue SQL directly.

---

## Gateway updates

For every accepted report:

- identify the gateway;
- create it if unknown and allowed;
- update `last_seen_at`;
- update model or firmware metadata when new information appears;
- do not overwrite verified metadata with empty values.

Gateway MAC normalization should remove separators and standardize case internally.

---

## Raw report immutability

Raw reports must be append-only.

Do not provide ordinary update operations for:

```text
payload_json
payload_hash
received_at_utc
device_timestamp_utc
```

Corrections belong in normalized data or reprocessing metadata, never in the original payload.

---

## Normalized observation persistence

Every normalized observation shall reference:

```text
raw_report_id
gateway_id
parser_version
observed_at_utc
received_at_utc
```

All meteorological variables must remain nullable.

Do not substitute missing values with:

```text
0
-999
NaN strings
```

Use database `NULL`.

---

## Reprocessing policy

Provide a CLI command:

```bash
uv run argos ecowitt reprocess
```

It shall support:

```text
--from
--to
--gateway
--parser-version
--dry-run
```

Reprocessing must:

- read immutable raw reports;
- rerun the selected parser version;
- update or replace normalized observations transactionally;
- avoid creating duplicates;
- produce a summary.

---

## Logging

Use structured logging.

Recommended fields:

```text
event
gateway
raw_report_id
observation_id
received_at
observed_at
field_count
duplicate
warnings_count
processing_ms
```

Example:

```text
event=ecowitt_report_received
gateway=finca-gw2000
field_count=27
duplicate=false
warnings_count=1
processing_ms=18
```

Do not log the full payload at INFO level.

---

## Sensitive-field redaction

Always redact keys matching or containing:

```text
PASSKEY
password
token
secret
key
authorization
cookie
```

Apply redaction recursively to nested objects.

Use the same redaction utility for:

- logs;
- diagnostic endpoints;
- saved captures;
- error reports.

---

## Log levels

Recommended use:

```text
DEBUG   detailed sanitized payload diagnostics
INFO    successful ingestion summaries
WARNING invalid fields, unknown mappings, duplicates if relevant
ERROR   database failures, parser crashes, persistence failures
CRITICAL application cannot continue
```

Unknown fields should not produce one warning every minute. Log only:

- first appearance;
- periodic summaries;
- mapping-status changes.

---

## Metrics

Expose or internally track at least:

```text
reports_received_total
reports_accepted_total
reports_rejected_total
duplicate_reports_total
parser_warnings_total
parser_errors_total
unknown_fields_total
last_report_timestamp
ingestion_duration_seconds
```

Optional endpoint:

```http
GET /metrics
```

Prometheus support is desirable but not mandatory in the first version.

---

## Health monitoring

The application shall distinguish:

```text
process alive
database ready
gateway online
```

These are different states.

A healthy application may still report the gateway as offline.

---

## Gateway online status

Use server reception time, not device time.

Configuration:

```env
ECOWITT_EXPECTED_INTERVAL_SECONDS=60
ECOWITT_OFFLINE_AFTER_SECONDS=180
```

Rule:

```text
online = now_utc - last_received_at <= offline_after_seconds
```

---

## Data-gap detection

Detect relevant gaps using reception timestamps.

For an expected 60-second interval:

- tolerate jitter;
- do not demand exact minute alignment;
- open a gap after more than 3 missed intervals;
- close it when reports resume.

Store:

```text
gap_start
gap_end
expected_reports
received_reports
status
resolution_method
```

Possible status values:

```text
OPEN
RESOLVED
IGNORED
BACKFILL_PENDING
```

---

## Backfill integration

The Ecowitt Cloud API remains a secondary source.

Backfill shall:

1. detect a gap;
2. request missing historical data;
3. normalize it through a separate adapter;
4. mark observations as `BACKFILLED`;
5. avoid duplicates against direct gateway data;
6. preserve the cloud-source payload separately.

Direct GW2000 ingestion remains primary.

---

## Operational diagnostics

Provide a concise diagnostic command:

```bash
uv run argos ecowitt status
```

It should report:

```text
gateway
last report
online/offline
reports in last 24 h
duplicates
parser errors
unknown fields
open gaps
```

Also provide:

```bash
uv run argos ecowitt list-unknown-fields
```

---

## Raw capture mode

Configuration:

```env
ECOWITT_CAPTURE_RAW=true
```

When enabled:

- save only a bounded number of captures;
- sanitize sensitive values;
- use timestamped JSON filenames;
- store under:

```text
var/captures/ecowitt/
```

Add the directory to `.gitignore`.

Default maximum:

```env
ECOWITT_CAPTURE_LIMIT=20
```

---

## Retention

Initial policy:

- raw reports: retain indefinitely;
- normalized observations: retain indefinitely;
- debug capture files: delete after validation;
- logs: rotate;
- metrics: retain according to deployment environment.

Do not implement automatic deletion of scientific observations without explicit configuration.

---

## Backup

Document a basic backup procedure.

For SQLite:

```bash
sqlite3 var/argos.db ".backup var/backups/argos-$(date +%F).db"
```

For PostgreSQL:

```bash
pg_dump "$DATABASE_URL" > argos-backup.sql
```

Backups should include:

- raw reports;
- normalized observations;
- gateways;
- field catalogue;
- gap records.

---

## Performance

At one report per minute:

```text
525,600 reports per year per gateway
```

The design must support several years without redesign.

Create indexes on:

```text
gateway_id
received_at_utc
observed_at_utc
payload_hash
last_seen_at
```

Avoid unnecessary full-table scans in status and dashboard queries.

---

## Tests

Create tests for:

1. successful transaction;
2. raw persistence followed by normalized persistence;
3. parser failure with raw report retained;
4. duplicate hash detection;
5. same timestamp with different payload;
6. gateway metadata update;
7. redaction;
8. structured logging;
9. gap opening;
10. gap closing;
11. backfilled observation deduplication;
12. reprocessing idempotency;
13. database rollback on fatal failure;
14. unknown-field catalogue update.

---

## Acceptance criteria

This part is complete when:

- raw reports are immutable;
- normalized records reference raw reports;
- duplicates are idempotent;
- parser failures do not destroy raw data;
- logs are structured and sanitized;
- gateway status is computed correctly;
- gaps are detected;
- backfilled records are distinguishable;
- reprocessing works;
- tests cover persistence and failure cases.


# PART 6 — Dashboard, Analytics, Deployment and Future Evolution

## General philosophy

ARGOS shall not be a simple weather station viewer.

It shall evolve into a scientific environmental monitoring platform capable of integrating meteorological observations, soil sensors, irrigation systems, remote sensing products and future instrumentation.

The dashboard is therefore a visualization layer over a well-designed data model rather than the core of the application.

---

# Dashboard architecture

Use a layered architecture.

```
Database

↓

Repositories

↓

Analytics Services

↓

REST API

↓

Frontend

↓

User
```

The frontend shall never communicate directly with the database.

All business logic shall remain inside the backend.

---

# Dashboard organization

The web interface shall initially contain the following sections.

## Home

Current environmental conditions.

Display:

- gateway status
- last update
- outdoor temperature
- humidity
- pressure
- wind
- solar radiation
- UV
- rainfall
- gateway health

---

## Daily analysis

Interactive plots for the selected day.

Variables:

- temperature
- humidity
- pressure
- wind
- solar radiation
- UV
- rainfall

Functions:

- zoom
- pan
- export CSV
- export PNG

---

## Weekly analysis

Display:

daily minimum

daily maximum

daily mean

daily accumulated rainfall

daily maximum gust

---

## Monthly analysis

Interactive statistics.

Examples:

- monthly rainfall
- average temperature
- wind roses
- solar energy received
- sunshine evolution

---

## Annual analysis

Display:

annual summaries

monthly climatology

annual rainfall

temperature anomalies

wind statistics

solar radiation totals

---

## Trends

Long-term plots.

Support:

30 days

90 days

180 days

1 year

custom interval

---

## Raw data

Administrative page.

Display:

- raw payload
- normalized observation
- parser warnings
- unknown fields
- gateway metadata

Useful for debugging parser changes.

---

## System

Technical dashboard.

Display:

gateway online/offline

database status

last report

duplicates

parser warnings

processing time

open data gaps

software versions

---

# Charts

Preferred library:

Plotly.

Requirements:

interactive

responsive

high-quality exports

dark mode support

No server-side image generation is required initially.

---

# Time handling

Users shall always see local time.

Internally:

UTC.

Presentation:

Europe/Madrid.

Every graph shall clearly indicate:

timezone

aggregation interval

sampling frequency

---

# Aggregation services

Do not compute statistics inside SQL queries whenever business rules become complex.

Instead create services such as:

```
DailyStatisticsService

WeeklyStatisticsService

MonthlyStatisticsService

AnnualStatisticsService
```

These services shall encapsulate scientific calculations.

---

# Statistical products

Initially compute:

minimum

maximum

mean

median

standard deviation

accumulated rainfall

maximum gust

average pressure

average humidity

daily solar energy

The implementation shall allow future derived products.

---

# Wind products

Future versions shall include:

wind rose

prevailing direction

gust histogram

wind-speed distribution

These calculations shall be isolated from ingestion.

---

# Solar products

Future services may calculate:

daily irradiation

monthly irradiation

clear-sky comparison

solar anomalies

photoperiod

Do not couple these calculations to the parser.

---

# Rainfall products

Support:

hourly accumulation

daily accumulation

monthly accumulation

annual accumulation

rain event identification

dry periods

Maximum event duration shall remain configurable.

---

# Data quality visualization

Display quality flags.

Examples:

missing values

backfilled observations

parser warnings

suspect observations

Unknown fields shall not appear in ordinary user plots.

---

# Export functionality

Support:

CSV

Excel

JSON

PNG

PDF (future)

Exports shall preserve:

timezone

units

metadata

generation timestamp

---

# User interface

The interface shall be responsive.

Support:

desktop

tablet

mobile

Scientific usability shall take precedence over decorative appearance.

---

# Configuration pages

Administrative pages should include:

registered gateways

parser version

environment configuration

capture mode

unknown fields

gap status

system health

These pages should eventually require authentication.

---

# Future authentication

Prepare for:

local administrator

read-only user

API key

OAuth/OpenID

Do not implement complex authentication in version 1.

---

# Deployment strategy

Three deployment scenarios shall be supported.

---

## Scenario A

Development workstation.

```
GW2000

↓

Developer computer

↓

SQLite

↓

Dashboard
```

---

## Scenario B

Farm server.

```
GW2000

↓

Mini-PC / Raspberry Pi

↓

PostgreSQL

↓

Dashboard

↓

Cloud synchronization
```

This is the preferred long-term architecture.

---

## Scenario C

Public cloud.

```
GW2000

↓

Internet

↓

Reverse proxy

↓

FastAPI

↓

PostgreSQL

↓

Dashboard
```

Suitable for remote monitoring.

---

# Docker

Provide:

Dockerfile

docker-compose.yml

Recommended services:

FastAPI

PostgreSQL

Adminer (optional)

Prometheus (future)

Grafana (future)

---

# Reverse proxy

Recommended:

Caddy

or

Nginx.

Responsibilities:

TLS

compression

logging

rate limiting

reverse proxy

---

# HTTPS

Prefer HTTPS for Internet deployments.

For local LAN development, HTTP is acceptable.

Do not assume the GW2000 supports every HTTPS configuration.

Verify experimentally before documenting.

---

# Backup strategy

Daily database backup.

Weekly off-site backup.

Monthly integrity verification.

Document restoration procedures.

---

# Scalability

The architecture shall support:

multiple gateways

multiple farms

multiple users

multiple sensor families

without redesign.

Gateway identity shall therefore be a first-class concept.

---

# Future sensor integration

The system shall accommodate:

Ecowitt soil moisture sensors

leaf wetness sensors

CO₂ sensors

PM sensors

lightning detectors

LoRa sensors

Modbus devices

custom scientific instrumentation

No future sensor shall require rewriting the ingestion architecture.

---

# Irrigation integration

Future versions may incorporate:

soil moisture

valve status

flow meters

tank level

pump status

irrigation schedules

The irrigation subsystem shall remain logically independent from meteorological ingestion.

ARGOS should **recommend** irrigation but never autonomously irrigate unless explicitly configured.

---

# Alert engine

Future alert types:

gateway offline

missing observations

heavy rainfall

strong wind

high temperature

low battery

sensor failure

tank nearly empty

Alerts shall be rule-based and configurable.

---

# Machine learning

The architecture should permit future predictive models:

evapotranspiration

irrigation recommendation

sensor anomaly detection

equipment failure prediction

forecast bias correction

No ML implementation is required in version 1.

---

# API evolution

All new functionality shall remain backward compatible whenever possible.

Breaking API changes require:

```
/api/v2/
```

Do not silently modify existing endpoints.

---

# Documentation

The repository README shall include:

project architecture

installation

development workflow

deployment

GW2000 configuration

dashboard overview

backup procedures

troubleshooting

common parser issues

future roadmap

---

# Acceptance criteria

This part is complete when:

- dashboard architecture is clearly separated from ingestion;
- statistics are generated through dedicated services;
- deployment supports development, local server and cloud;
- Docker deployment works;
- exports are supported;
- future sensor families fit the existing architecture;
- irrigation remains modular;
- the roadmap is documented.

# PART 7 — Testing, Documentation, Quality Assurance and Acceptance Criteria

# Testing philosophy

Scientific software must be reproducible.

Every feature implemented in ARGOS shall be accompanied by automated tests.

The objective is not merely to obtain high code coverage, but to ensure that future modifications do not alter scientific behaviour unexpectedly.

---

# Test hierarchy

The project shall contain four levels of testing.

## Unit tests

Validate isolated functions.

Examples:

- unit conversions
- timestamp parsing
- duplicate detection
- field aliases
- quality flags
- parser warnings

These tests must execute in milliseconds.

---

## Integration tests

Validate interactions between components.

Examples:

- HTTP endpoint → parser
- parser → database
- database → dashboard API
- duplicate handling
- gateway registration

Integration tests shall use an isolated temporary database.

---

## End-to-end tests

Simulate the complete ingestion workflow.

Example:

```
GW2000 payload

↓

HTTP endpoint

↓

Parser

↓

Database

↓

REST API

↓

Dashboard response
```

A successful test proves that the complete ingestion chain works correctly.

---

## Regression tests

Every bug fixed shall generate a regression test.

The objective is to ensure the bug never reappears.

---

# Fixtures

Create realistic fixtures.

Suggested directory:

```
tests/
    fixtures/
        ecowitt/
```

Examples:

```
gw2000_ws90_nominal.json

gw2000_missing_fields.json

gw2000_unknown_fields.json

gw2000_duplicate.json

gw2000_invalid_timestamp.json

gw2000_parser_failure.json
```

All fixtures shall be anonymized.

---

# Test coverage

Coverage should focus on critical code.

Priority order:

1. parser
2. unit conversions
3. duplicate detection
4. persistence
5. REST API
6. dashboard services

Target coverage:

```
>90%
```

Parser coverage should approach 100%.

---

# Continuous Integration

Every Pull Request shall execute automatically:

```bash
uv sync

uv run ruff check .

uv run mypy src

uv run pytest
```

No merge shall occur unless all checks succeed.

---

# Static analysis

Mandatory tools:

Ruff

mypy

Black (optional if Ruff formatting is adopted)

The codebase should remain free from:

unused imports

dead code

implicit Any

shadowed variables

unsafe casts

---

# Performance tests

Measure:

parser execution time

database insertion time

HTTP latency

Expected workload:

1 report every 60 seconds.

Although the load is low, efficient implementation is encouraged.

---

# Failure simulations

Create tests for:

database unavailable

invalid payload

unknown sensor

duplicate report

gateway offline

network interruption

parser exception

The application should fail gracefully.

---

# Logging tests

Verify:

PASSKEY never appears in logs

tokens are redacted

structured logging format

correct log level

parser warnings recorded

---

# Documentation

The repository shall contain:

README.md

CHANGELOG.md

CONTRIBUTING.md

LICENSE

docs/

The documentation shall be sufficient for another developer to deploy ARGOS without external guidance.

---

# README contents

Include:

project overview

architecture diagram

installation

development

database migrations

GW2000 configuration

Customized configuration

API endpoints

dashboard

backup

troubleshooting

roadmap

---

# Code documentation

Every public module shall contain:

module docstring

Every public function shall include:

purpose

arguments

return values

exceptions

Avoid redundant comments.

Prefer expressive code over excessive commenting.

---

# Versioning

Use Semantic Versioning.

Examples:

```
1.0.0

1.1.0

2.0.0
```

Breaking API changes require a major version increment.

---

# Release checklist

Before every release verify:

✓ tests passing

✓ migrations applied

✓ documentation updated

✓ parser version recorded

✓ CHANGELOG updated

✓ Docker image builds

✓ dashboard functional

✓ ingestion verified using a real payload

---

# Acceptance criteria

The implementation shall be considered complete when:

- ARGOS receives data directly from the GW2000 using Customized.
- Raw payloads are preserved immutably.
- Normalized observations are stored correctly.
- Duplicate reports are ignored safely.
- Unknown fields are preserved.
- Scientific units are converted correctly.
- The dashboard displays live observations.
- Gateway status is reported accurately.
- Historical backfill through the Ecowitt Cloud API remains available.
- The full project passes Ruff, mypy and pytest.
- A clean clone can be deployed following only the repository documentation.

# PART 8 — Appendix, Roadmap and Final Recommendations

# A. Initial GW2000 Configuration

Once ARGOS is running, configure the GW2000 through **WS View Plus**.

Weather Services

```
Customized
```

Configuration:

```
Enable: Yes

Protocol Type:
Ecowitt

Server Hostname:
<ARGOS_HOST>

Port:
8080

Path:
/api/v1/ecowitt/upload/<ECOWITT_INGEST_TOKEN>

Upload Interval:
60 seconds
```

Do **not** configure:

- Weather Underground
- WeatherCloud
- WOW
- Station ID
- Station Key

The GW2000 should send observations exclusively to ARGOS.

---

# B. Local development

Recommended architecture:

```
GW2000
      │
      ▼
Home WiFi
      │
      ▼
Development computer
      │
      ▼
FastAPI
      │
      ▼
SQLite
      │
      ▼
Dashboard
```

Launch:

```bash
uv sync

uv run alembic upgrade head

uv run uvicorn argos.main:app \
    --host 0.0.0.0 \
    --port 8080
```

---

# C. Production deployment

Preferred long-term deployment:

```
WS90
   │
GW2000
   │
Home WiFi
   │
Mini-PC / Raspberry Pi
   │
FastAPI
   │
PostgreSQL
   │
Dashboard
   │
Reverse Proxy
   │
HTTPS
```

Advantages:

- autonomous operation
- local data acquisition
- low latency
- Internet optional
- full historical archive

---

# D. Cloud backfill

The Ecowitt Cloud API shall **never** be considered the primary acquisition source.

Its only purposes are:

- recovering missing observations
- historical imports
- consistency checks
- disaster recovery

Suggested workflow:

```
Gap detected

↓

Cloud API

↓

Temporary parser

↓

Normalization

↓

Database

↓

Observation marked as BACKFILLED
```

Every backfilled observation shall be distinguishable from direct gateway observations.

---

# E. Future sensor roadmap

The architecture shall support future integration of:

## Ecowitt

- soil moisture sensors
- leaf wetness sensors
- PM2.5
- PM10
- CO₂
- lightning detector
- additional temperature channels

## Irrigation

- flow meters
- pressure sensors
- tank level sensors
- valve controllers
- pump monitoring

## LoRa

Future LoRa gateways shall reuse the same ingestion philosophy:

```
LoRa device

↓

Gateway

↓

Adapter

↓

Normalization

↓

Database
```

The HTTP ingestion architecture developed for Ecowitt should become the reference implementation for all future data sources.

---

# F. ARGOS philosophy

ARGOS is **not** intended to be merely a weather-station logger.

It shall evolve into an integrated environmental observation platform.

Core design principles:

- modularity
- traceability
- scientific reproducibility
- extensibility
- reliability
- maintainability

Every observation must remain reproducible from the original raw payload.

---

# G. Long-term modules

The architecture should naturally accommodate future modules such as:

```
Meteorology

↓

Soil

↓

Irrigation

↓

Remote sensing

↓

Satellite products

↓

Crop monitoring

↓

Forecasts

↓

Artificial Intelligence

↓

Decision Support
```

These modules shall share:

- authentication
- database
- metadata
- dashboard framework

while remaining logically independent.

---

# H. Suggested repository roadmap

Recommended milestones.

## Milestone 1

Direct Ecowitt ingestion

- FastAPI
- parser
- database
- dashboard
- tests

---

## Milestone 2

Cloud synchronization

- Ecowitt API
- backfill
- gap recovery

---

## Milestone 3

Scientific analytics

- daily summaries
- monthly summaries
- climatology
- anomaly detection

---

## Milestone 4

Agricultural monitoring

- soil moisture
- irrigation
- evapotranspiration
- water balance

---

## Milestone 5

Decision support

- irrigation recommendation
- drought alerts
- frost alerts
- heat stress
- AI-assisted interpretation

---

# I. Final acceptance checklist

Before considering the project complete, verify:

- [ ] Repository builds from a clean clone.
- [ ] `uv sync` completes successfully.
- [ ] Database migrations execute correctly.
- [ ] FastAPI starts without warnings.
- [ ] GW2000 communicates successfully using Customized.
- [ ] Raw payloads are stored.
- [ ] Normalized observations are generated.
- [ ] Duplicate reports are handled correctly.
- [ ] Unknown fields are catalogued.
- [ ] Dashboard displays live data.
- [ ] Gateway online/offline detection works.
- [ ] Historical backfill is operational.
- [ ] Ruff passes.
- [ ] mypy passes.
- [ ] pytest passes.
- [ ] Docker deployment works.
- [ ] Documentation is complete.

---

# J. Definition of Done

The implementation shall be considered complete when ARGOS satisfies the following conditions:

1. The GW2000 sends observations directly to ARGOS using the Ecowitt Customized service.

2. Every observation is preserved as an immutable raw payload.

3. Every supported field is normalized into scientifically meaningful SI units.

4. Unknown fields are preserved and catalogued automatically.

5. Duplicate reports do not generate duplicate observations.

6. Gateway health can be monitored in real time.

7. Historical observations can be reconstructed through the Ecowitt Cloud API when necessary.

8. The system can be extended to new sensors without redesigning the ingestion architecture.

9. The complete project is reproducible from a clean clone.

10. The repository contains sufficient automated tests and documentation for another developer to continue the project without additional guidance.

---

# End of Specification

This document defines the reference implementation for direct Ecowitt integration within ARGOS.

The **Customized** service is the primary ingestion mechanism.

The **Ecowitt Cloud API** remains available exclusively for historical recovery (*backfill*) and validation.

All future environmental data sources integrated into ARGOS should follow the same architectural principles established in this specification.