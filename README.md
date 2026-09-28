# PM2.5 and Respiratory Disease — Mini Data Warehouse & Analytics Dashboard

Does airborne PM2.5 track respiratory-disease hospital visits across Thailand?

This project builds a dimensional data warehouse from five independent public sources
(2022–2025), joins air-quality readings to hospital visit records, and serves the result
through an analytics dashboard aimed at hospital-management decision making.

**The honest answer turned out to be no** — see [Findings](#findings).

Built for the Data Mining course at Kasetsart University.

---

## What is interesting here

- **Two datasets that do not naturally join.** Air quality arrives at *station × hour*;
  patient records arrive at *hospital × year* with months spread across columns. The entire
  design follows from finding the one grain where both are valid: **province × month**.
- **Five heterogeneous sources**, including 81,788 gzipped hourly files on S3, a government
  API that returns Buddhist-era years, and a fixed-width census text file.
- **Data quality is handled in the open, not hidden.** Every ETL stage prints a before/after
  quality report, and the dashboard shows coverage ratios next to every headline number.
- **A grain-inflation bug caught after it reached the written report** — see
  [The bug worth reading about](#the-bug-worth-reading-about).
- **A null result reported as a null result**, with an explanation of what actually drives
  the seasonality instead.

---

## Architecture

```
01_Raw_Data/     five sources, as downloaded          (not in this repo — see Data)
02_ETL/          Extract → Clean → Transform → Integrate → Load
03_Data_Warehouse/  dw.duckdb, 20 tables              (not in this repo — rebuild it)
04_Dashboard/    Streamlit app: app.py + queries.py
```

The pipeline runs in five ordered stages, each reading only what the previous stage wrote:

| Stage | Writes | Notes |
|---|---|---|
| **Extract** | raw files | S3 download, HDC API, Open-Meteo API, census scrape |
| **Clean** | `stg_*` | dedupe, calendar conversion, range clipping, coverage filtering |
| **Transform** | `DIM_*` | conformed date, province, station, hospital, disease, weather |
| **Integrate** | `FACT_*` | station-day air facts; hospital-month-disease visit facts |
| **Load** | `AGG_*` | the province × month aggregate the dashboard reads |

Every script uses `CREATE OR REPLACE TABLE` and reads all settings from `02_ETL/config.py`,
so the pipeline is **idempotent** — dropping a station from the config and re-running removes
it from the warehouse rather than leaving stale rows behind.

### Star schema

**Facts**

| Table | Rows | Grain |
|---|---:|---|
| `FACT_AIR_QUALITY_DAILY` | 35,316 | station × day |
| `FACT_DISEASE_MONTHLY` | 1,751,728 | hospital × month × disease group |

**Aggregate**

| Table | Rows | Grain |
|---|---:|---|
| `AGG_PM25_DISEASE_MONTHLY` | 29,333 | province × month × disease group |

**Dimensions** — `DIM_DATE` (3,652) · `DIM_PROVINCE` (77) · `DIM_STATION` (54) ·
`DIM_HOSPITAL` (11,609) · `DIM_DISEASE_GROUP` (13, of which 7 respiratory) ·
`DIM_WEATHER` (50)

`DIM_DATE` and `DIM_PROVINCE` are the conformed dimensions that bridge the two facts.

---

## Data sources

| Source | What | Why it was awkward |
|---|---|---|
| **OpenAQ** (AWS S3 Open Data) | hourly PM2.5, 54 stations | 81,788 `.csv.gz` files, Hive-partitioned by station/year/month, timestamps in UTC |
| **MOPH HDC API** | patient visits per hospital per year | months live in columns `m1`–`m12` and need unpivoting; years are Buddhist era |
| **Open-Meteo API** | daily weather | nested JSON per station |
| **Air4Thai** | regional air JSON | used to characterise pollution sources |
| **Dept. of Provincial Administration** | province population | fixed-width `.txt` |

### Data-quality defects found and fixed

| Defect | Handling |
|---|---|
| Duplicate patient rows per `hospcode + year + disease group` | keep the latest `date_com` |
| Buddhist vs. Gregorian calendars | convert with `BE_OFFSET = 543` |
| Negative / implausible PM2.5 and visit counts | drop or clip to a validity range |
| Days with fewer than 18 hourly readings | excluded; `coverage_ratio` retained on every row |
| UTC timestamps vs. local analysis | `SET TimeZone = 'Asia/Bangkok'`, never a manual `+7h` offset |
| Province names spelled differently in all five sources | mapped to a single `province_key` |

---

## Findings

At province × month, **PM2.5 does not correlate meaningfully with respiratory visit rates.**

- r = **−0.021** at lag 0; **−0.076** at lag 1–2 months
- The ratio of respiratory to control-group visits stays flat at **1.26–1.32** across every
  pollution level
- Respiratory visits **peak in September**, the cleanest-air month of the year

The most plausible explanation is that influenza and RSV seasonality dominates the signal at
this grain. A monthly province-level average also smooths away the short exposure spikes that
the health literature associates with respiratory effects, so this result argues for a finer
grain rather than against an effect existing at all.

Restricting to province-months with at least 20 days of air data (915 of 1,982) flips the
correlation to **+0.108** — still negligible, but it is why every reported correlation in this
project states which basis it uses.

---

## The bug worth reading about

`AGG_PM25_DISEASE_MONTHLY` has grain province × month × **disease group**, which means every
air-side measure (`avg_pm25`, `exceedance_days_th`, `days_with_data`, …) is repeated
identically once per disease row of the same province-month.

A naive `SUM(exceedance_days_th)` therefore returned **72,498** exceedance days against a true
**6,049**. The repeat factor is not a constant 13 — it is however many disease groups reported
that month, which varies between 7 and 13 — so the inflation is not a clean multiple that
stands out on inspection. It had already reached a regional table in the written report
(24,613 claimed for the North against a true 2,061) before it was caught.

The fix is to collapse to province-month with `MAX()` before aggregating, which is safe
precisely because the repeated values are identical. The full specification of key uniqueness,
per-measure additivity, and NULL semantics is in
[`docs/AGG_Grain_Definition.md`](docs/AGG_Grain_Definition.md).

Two related traps documented in the same place:

- **Never `SUM(is_exceedance_th)` from `FACT_AIR_QUALITY_DAILY`.** Bangkok has 3 stations, so
  summing counts station-days rather than days.
- **Station-day and province-day bases give different totals** (6,491 vs. 6,049). Either is
  defensible alone; a table mixing the two is wrong even when both columns look plausible.

---

## Running the dashboard

The warehouse file is not in this repo (87 MB), so build it first — see below — or point the
app at an existing copy with `DW_PATH`.

```bash
cd 04_Dashboard
pip install -r requirements.txt
streamlit run app.py              # → http://localhost:8501
```

```bash
DW_PATH=/path/to/dw.duckdb streamlit run app.py    # use a warehouse elsewhere
```

The dashboard has 22 Plotly charts across 8 tabs, one per business question plus a dedicated
Data Quality tab. `queries.py` holds every SQL statement and returns DataFrames; `app.py` only
builds filters and renders.

## Rebuilding the warehouse

```bash
pip install -r 02_ETL/requirements.txt

# 1. Extract
python 02_ETL/Extract/download_openaq.py
python 02_ETL/Extract/download_weather.py
python 02_ETL/Extract/download_population.py
python 02_ETL/Extract/api_request_patient.py
python 02_ETL/Extract/api_request_dim_area.py
python 02_ETL/Extract/get_stations.py        # needs OPENAQ_API_KEY

# 2. Clean
python 02_ETL/Clean/clean_disease_extract.py
python 02_ETL/Clean/clean_disease.py
python 02_ETL/Clean/clean_openaq.py
python 02_ETL/Clean/clean_weather.py
python 02_ETL/Clean/clean_population.py
python 02_ETL/Clean/clean_air4thai.py

# 3–5. Transform → Integrate → Load
python 02_ETL/Transform/build_dimensions.py
python 02_ETL/Integrate/build_facts.py
python 02_ETL/Load/build_aggregate.py
```

Stages must run in this order; each reads what the previous one wrote. Scope — analysis years,
the 54 stations, the PM2.5 validity range, `MIN_READINGS_PER_DAY = 18`, the Thai (37.5 µg/m³)
and WHO (15.0 µg/m³) thresholds — is configured in `02_ETL/config.py` only.

Set `OPENAQ_API_KEY` in a `.env` file at the project root before running `get_stations.py`.

> **Note:** the patient data in HDC is revised over time. A fresh extract will not reproduce the
> exact figures quoted above, which come from the August 2026 pull.

## Data

Raw data is not committed — it is roughly 850 MB across 82,000+ files, and it is all publicly
re-downloadable with the Extract scripts. Sources: [OpenAQ](https://openaq.org) (AWS Open
Data), MOPH HDC, [Open-Meteo](https://open-meteo.com), Air4Thai, and the Department of
Provincial Administration.

---

## Tech

Python 3.13 · DuckDB · pandas · Streamlit · Plotly · boto3 (S3) · requests

## Credits

Group project for the Data Mining course, Kasetsart University, 2026, built by a team of
three. **My contribution: the ETL pipeline (`02_ETL/`) and the dashboard (`04_Dashboard/`).**
The written report and presentation were produced by the team and are not included here.
