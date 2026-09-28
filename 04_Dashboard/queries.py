"""
queries.py — ชั้นเข้าถึงข้อมูลของ Dashboard

หลักการออกแบบ:
  1. ไฟล์นี้เก็บ SQL ทั้งหมดไว้ที่เดียว  app.py มีหน้าที่แค่วาดกราฟ
  2. เปิด warehouse แบบ read_only=True เสมอ — Dashboard ต้องไม่แก้ข้อมูลได้
  3. ทุกฟังก์ชันคืน pandas DataFrame เพื่อส่งต่อให้ Plotly ได้ทันที

ข้อควรระวังสำคัญเกี่ยวกับ AGG_PM25_DISEASE_MONTHLY:
  grain ของตารางคือ จังหวัด × เดือน × กลุ่มโรค  ดังนั้นคอลัมน์ฝั่งฝุ่น
  (avg_pm25, exceedance_days_th, days_with_data, ...) จะ **ซ้ำทุกกลุ่มโรค**
  ในจังหวัด-เดือนเดียวกัน  ถ้า SUM() หรือ AVG() ตรง ๆ ข้ามกลุ่มโรคจะได้ค่าเกินจริง 13 เท่า
  ทุก query ในไฟล์นี้จึงยุบเป็นระดับจังหวัด-เดือนด้วย MAX() ก่อนเสมอ (CTE ชื่อ pm)
"""
from __future__ import annotations

import os
from pathlib import Path

import duckdb
import pandas as pd

# ─────────────────────────────────────────────────────────────────────
# ค่าคงที่เชิงธุรกิจ (ตรงกับ 02_ETL/config.py)
# ─────────────────────────────────────────────────────────────────────
LOCAL_TZ = "Asia/Bangkok"   # ตรงกับ 02_ETL/config.py
THAI_STANDARD_PM25 = 37.5   # มาตรฐานไทย ค่าเฉลี่ย 24 ชม. (µg/m³)
WHO_GUIDELINE_PM25 = 15.0   # เกณฑ์แนะนำ WHO 2021
MIN_DAYS_FOR_ANALYSIS = 20  # จังหวัด-เดือนต้องมีข้อมูลฝุ่นอย่างน้อยกี่วันจึงนำมาวิเคราะห์

REGION_ORDER = [
    "ภาคเหนือ", "ภาคตะวันออกเฉียงเหนือ", "ภาคกลาง",
    "ภาคตะวันออก", "ภาคตะวันตก", "ภาคใต้",
]


# ─────────────────────────────────────────────────────────────────────
# การเชื่อมต่อ
# ─────────────────────────────────────────────────────────────────────
def find_warehouse() -> Path:
    """หา dw.duckdb — รองรับทั้งกรณีอยู่ในโครงสร้างโปรเจกต์เต็ม
    และกรณีเพื่อนร่วมกลุ่มได้รับมาแค่ไฟล์ dw.duckdb ไฟล์เดียว"""
    if os.environ.get("DW_PATH"):
        return Path(os.environ["DW_PATH"]).expanduser().resolve()

    here = Path(__file__).resolve().parent
    candidates = [
        here.parent / "03_Data_Warehouse" / "dw.duckdb",  # โครงสร้างโปรเจกต์เต็ม
        here / "dw.duckdb",                               # วางไว้ข้าง app.py
        here / "03_Data_Warehouse" / "dw.duckdb",
        Path.cwd() / "dw.duckdb",
    ]
    for c in candidates:
        if c.exists():
            return c
    raise FileNotFoundError(
        "ไม่พบไฟล์ dw.duckdb\n"
        "วางไฟล์ไว้ข้าง app.py หรือกำหนดตัวแปรสภาพแวดล้อม DW_PATH\n"
        "ตำแหน่งที่ค้นหา:\n  " + "\n  ".join(str(c) for c in candidates)
    )


def connect() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(find_warehouse()), read_only=True)


# ─────────────────────────────────────────────────────────────────────
# ตัวช่วยสร้าง SQL
# ─────────────────────────────────────────────────────────────────────
def _q(v) -> str:
    """ใส่ single quote และ escape ให้ค่า string"""
    return "'" + str(v).replace("'", "''") + "'"


def _in_clause(col: str, values) -> str:
    """สร้าง `col IN (...)` — ถ้ารายการว่างแปลว่า 'ทั้งหมด' คืน TRUE"""
    values = list(values or [])
    if not values:
        return "TRUE"
    return f"{col} IN ({', '.join(_q(v) for v in values)})"


def _int_in_clause(col: str, values) -> str:
    values = list(values or [])
    if not values:
        return "TRUE"
    return f"{col} IN ({', '.join(str(int(v)) for v in values)})"


class Filters:
    """ตัวกรองที่ผู้ใช้เลือกจาก sidebar

    provinces / disease_keys ที่เป็นลิสต์ว่าง = ไม่กรอง (เลือกทั้งหมด)

    หมายเหตุขอบเขต: AGG_PM25_DISEASE_MONTHLY ถูกสร้างด้วยเงื่อนไข
    `WHERE p.has_air_data` (ดู 02_ETL/05_load/build_aggregate.py) จึงมีเฉพาะ
    51 จังหวัดที่มีสถานีตรวจวัดฝุ่น — ตรงกับขอบเขตที่ BQ3 ระบุไว้
    ข้อมูลผู้ป่วยครบ 77 จังหวัดยังอยู่ใน FACT_DISEASE_MONTHLY แต่ไม่มีค่า PM2.5 ให้เทียบ
    """

    def __init__(self, year_min: int, year_max: int,
                 provinces=None, disease_keys=None):
        self.year_min = int(year_min)
        self.year_max = int(year_max)
        self.provinces = list(provinces or [])
        self.disease_keys = list(disease_keys or [])

    # ให้ st.cache_data แคชได้ — ต้องแปลงเป็น tuple ที่ hash ได้
    def key(self):
        return (self.year_min, self.year_max,
                tuple(self.provinces), tuple(self.disease_keys))

    def __repr__(self):
        return f"Filters{self.key()}"

    # ---- ชิ้นส่วน WHERE ----
    @property
    def where_year(self) -> str:
        return f"dm.year BETWEEN {self.year_min} AND {self.year_max}"

    @property
    def where_province(self) -> str:
        return _in_clause("p.province_name_th", self.provinces)

    @property
    def where_disease(self) -> str:
        return _int_in_clause("g.disease_key", self.disease_keys)


def base_cte(f: Filters, apply_disease_filter: bool = True) -> str:
    """CTE ตั้งต้นที่ทุก query ใช้ร่วมกัน

    คืน SQL ที่ประกาศ CTE 3 ตัว:
      base — AGG join กับ dimension ทั้งหมด กรองตาม sidebar แล้ว
      pm   — ยุบ base เป็นระดับจังหวัด-เดือน (แก้ปัญหาคอลัมน์ฝุ่นซ้ำทุกกลุ่มโรค)
      vis  — ยอดผู้ป่วยระดับจังหวัด-เดือน ตามกลุ่มโรคที่เลือก
    """
    disease_where = f.where_disease if apply_disease_filter else "TRUE"
    return f"""
WITH dm AS (
    -- DIM_DATE เป็น grain รายวัน ต้องยุบเป็นรายเดือนก่อนใช้กับ AGG
    SELECT DISTINCT month_key, year, month, month_name_th, is_haze_season
    FROM DIM_DATE
),
base AS (
    SELECT a.month_key, a.province_key, a.disease_key,
           a.visit_count, a.visits_per_100k,
           a.avg_pm25, a.max_pm25,
           a.exceedance_days_th, a.exceedance_days_who,
           a.days_with_data, a.avg_stations_per_day,
           a.avg_pm25_lag1, a.avg_pm25_lag2,
           p.province_name_th, p.region_th, p.population,
           g.disease_group_id, g.disease_sub_group_id, g.disease_name_en,
           g.disease_group_name_th, g.is_respiratory,
           dm.year, dm.month, dm.month_name_th, dm.is_haze_season
    FROM AGG_PM25_DISEASE_MONTHLY a
    JOIN DIM_PROVINCE      p USING (province_key)
    JOIN DIM_DISEASE_GROUP g USING (disease_key)
    JOIN dm                  USING (month_key)
    WHERE {f.where_year}
      AND {f.where_province}
),
pm AS (
    -- ยุบให้เหลือ 1 แถวต่อจังหวัด-เดือน  ใช้ MAX เพราะค่าซ้ำกันทุกกลุ่มโรคอยู่แล้ว
    SELECT province_key, month_key, province_name_th, region_th, population,
           year, month, month_name_th, is_haze_season,
           MAX(avg_pm25)             AS avg_pm25,
           MAX(max_pm25)             AS max_pm25,
           MAX(exceedance_days_th)   AS exceedance_days_th,
           MAX(exceedance_days_who)  AS exceedance_days_who,
           MAX(days_with_data)       AS days_with_data,
           MAX(avg_stations_per_day) AS avg_stations_per_day,
           MAX(avg_pm25_lag1)        AS avg_pm25_lag1,
           MAX(avg_pm25_lag2)        AS avg_pm25_lag2
    FROM base
    GROUP BY 1,2,3,4,5,6,7,8,9
),
vis AS (
    -- ยอดผู้ป่วยของกลุ่มโรคที่เลือก ระดับจังหวัด-เดือน
    SELECT province_key, month_key, SUM(visit_count) AS visits
    FROM base b
    JOIN DIM_DISEASE_GROUP g USING (disease_key)
    WHERE {disease_where}
    GROUP BY 1,2
)
"""


# ─────────────────────────────────────────────────────────────────────
# ตัวเลือกของ filter
# ─────────────────────────────────────────────────────────────────────
def filter_options(con) -> dict:
    years = con.execute("""
        SELECT MIN(year), MAX(year) FROM DIM_DATE
        WHERE month_key IN (SELECT DISTINCT month_key FROM AGG_PM25_DISEASE_MONTHLY)
    """).fetchone()

    provinces = con.execute("""
        SELECT province_name_th, region_th, has_air_data, population
        FROM DIM_PROVINCE ORDER BY region_th, province_name_th
    """).df()

    diseases = con.execute("""
        SELECT disease_key, disease_group_id, disease_sub_group_id,
               disease_name_en, disease_group_name_th, is_respiratory
        FROM DIM_DISEASE_GROUP ORDER BY disease_key
    """).df()

    return {"year_min": years[0], "year_max": years[1],
            "provinces": provinces, "diseases": diseases}


# ─────────────────────────────────────────────────────────────────────
# 1) KPI สรุปหัวหน้าจอ
# ─────────────────────────────────────────────────────────────────────
def kpis(con, f: Filters) -> dict:
    sql = base_cte(f) + f"""
    SELECT
        (SELECT ROUND(AVG(avg_pm25), 2) FROM pm
          WHERE avg_pm25 IS NOT NULL AND days_with_data >= {MIN_DAYS_FOR_ANALYSIS})  AS avg_pm25,
        (SELECT SUM(exceedance_days_th) FROM pm)                                      AS exc_days_th,
        (SELECT SUM(days_with_data)     FROM pm)                                      AS days_with_data,
        (SELECT SUM(visits)             FROM vis)                                     AS visits,
        (SELECT SUM(population) FROM (SELECT DISTINCT province_key, population FROM pm)) AS population,
        (SELECT COUNT(DISTINCT province_key) FROM pm)                                  AS n_provinces,
        (SELECT COUNT(*) FROM pm
          WHERE avg_pm25 IS NOT NULL AND days_with_data >= {MIN_DAYS_FOR_ANALYSIS})   AS n_analyzable
    """
    row = con.execute(sql).df().iloc[0].to_dict()

    visits = float(row["visits"] or 0)
    pop = float(row["population"] or 0)
    row["visits_per_100k"] = round(visits * 100_000 / pop, 1) if pop else None

    exc = float(row["exc_days_th"] or 0)
    days = float(row["days_with_data"] or 0)
    row["exceedance_pct"] = round(exc * 100 / days, 1) if days else None
    return row


# ─────────────────────────────────────────────────────────────────────
# 2) BQ1 — อนุกรมเวลา PM2.5 เทียบผู้ป่วย
# ─────────────────────────────────────────────────────────────────────
def monthly_trend(con, f: Filters) -> pd.DataFrame:
    sql = base_cte(f) + f"""
    SELECT pm.month_key,
           MAKE_DATE(pm.year, pm.month, 1)                    AS month_date,
           ROUND(AVG(pm.avg_pm25), 2)                         AS avg_pm25,
           SUM(vis.visits)                                    AS visits,
           SUM(pm.exceedance_days_th)                         AS exceedance_days_th,
           COUNT(DISTINCT pm.province_key)                    AS n_provinces
    FROM pm
    LEFT JOIN vis USING (province_key, month_key)
    WHERE pm.days_with_data >= {MIN_DAYS_FOR_ANALYSIS}
    GROUP BY 1, 2
    ORDER BY 1
    """
    return con.execute(sql).df()


# ─────────────────────────────────────────────────────────────────────
# 3) BQ1 — สหสัมพันธ์ที่ lag 0/1/2 เดือน
# ─────────────────────────────────────────────────────────────────────
def correlation_lags(con, f: Filters) -> pd.DataFrame:
    """คำนวณ 2 แบบ:
      r_raw       — สหสัมพันธ์ดิบ (สูงเกินจริงเพราะฤดูกาลผลักทั้งสองตัวแปรพร้อมกัน)
      r_deseason  — หักค่าเฉลี่ยของ 'จังหวัด × เดือนปฏิทิน' ออกก่อน
                    เพื่อลบผลฤดูกาลและความต่างระดับระหว่างจังหวัด
    """
    sql = base_cte(f) + f"""
    , pv AS (
        SELECT pm.province_key, pm.month, pm.avg_pm25, pm.avg_pm25_lag1, pm.avg_pm25_lag2,
               vis.visits
        FROM pm JOIN vis USING (province_key, month_key)
        WHERE pm.avg_pm25 IS NOT NULL
          AND pm.days_with_data >= {MIN_DAYS_FOR_ANALYSIS}
    ),
    resid AS (
        SELECT *,
               avg_pm25      - AVG(avg_pm25)      OVER w AS pm0_r,
               avg_pm25_lag1 - AVG(avg_pm25_lag1) OVER w AS pm1_r,
               avg_pm25_lag2 - AVG(avg_pm25_lag2) OVER w AS pm2_r,
               visits        - AVG(visits)        OVER w AS vis_r
        FROM pv
        WINDOW w AS (PARTITION BY province_key, month)
    )
    SELECT 0 AS lag_months,
           ROUND(corr(avg_pm25, visits), 3) AS r_raw,
           ROUND(corr(pm0_r,    vis_r),  3) AS r_deseason,
           COUNT(*) AS n
      FROM resid WHERE pm0_r IS NOT NULL
    UNION ALL
    SELECT 1,
           ROUND(corr(avg_pm25_lag1, visits), 3),
           ROUND(corr(pm1_r,         vis_r),  3),
           COUNT(*)
      FROM resid WHERE pm1_r IS NOT NULL
    UNION ALL
    SELECT 2,
           ROUND(corr(avg_pm25_lag2, visits), 3),
           ROUND(corr(pm2_r,         vis_r),  3),
           COUNT(*)
      FROM resid WHERE pm2_r IS NOT NULL
    ORDER BY 1
    """
    return con.execute(sql).df()


def correlation_by_region(con, f: Filters) -> pd.DataFrame:
    """แยกสหสัมพันธ์รายภาค — ค่าเฉลี่ยทั้งประเทศใกล้ 0 แต่ซ่อนความต่างรายภาคไว้"""
    sql = base_cte(f) + f"""
    , pv AS (
        SELECT pm.province_key, pm.region_th, pm.month, pm.avg_pm25, vis.visits
        FROM pm JOIN vis USING (province_key, month_key)
        WHERE pm.avg_pm25 IS NOT NULL
          AND pm.days_with_data >= {MIN_DAYS_FOR_ANALYSIS}
    ),
    resid AS (
        SELECT *,
               avg_pm25 - AVG(avg_pm25) OVER w AS pm_r,
               visits   - AVG(visits)   OVER w AS vis_r
        FROM pv WINDOW w AS (PARTITION BY province_key, month)
    )
    SELECT region_th,
           ROUND(corr(pm_r, vis_r), 3)    AS r_deseason,
           COUNT(*)                        AS n,
           COUNT(DISTINCT province_key)    AS n_provinces
    FROM resid
    GROUP BY 1
    HAVING COUNT(*) >= 24          -- ต้องมีอย่างน้อย 24 จังหวัด-เดือนจึงจะพอเชื่อถือ
    ORDER BY r_deseason DESC
    """
    return con.execute(sql).df()


# ─────────────────────────────────────────────────────────────────────
# 4) BQ2 — ฤดูกาล
# ─────────────────────────────────────────────────────────────────────
def seasonality(con, f: Filters) -> pd.DataFrame:
    sql = base_cte(f) + f"""
    SELECT pm.month,
           ANY_VALUE(pm.month_name_th)              AS month_name_th,
           ROUND(AVG(pm.avg_pm25), 2)               AS avg_pm25,
           ROUND(AVG(vis.visits), 0)                AS avg_visits,
           ROUND(AVG(pm.exceedance_days_th), 1)     AS avg_exceedance_days,
           BOOL_OR(pm.is_haze_season)               AS is_haze_season
    FROM pm
    LEFT JOIN vis USING (province_key, month_key)
    WHERE pm.days_with_data >= {MIN_DAYS_FOR_ANALYSIS}
    GROUP BY 1
    ORDER BY 1
    """
    return con.execute(sql).df()


# ─────────────────────────────────────────────────────────────────────
# 5) BQ3 — เปรียบเทียบเชิงพื้นที่
# ─────────────────────────────────────────────────────────────────────
def province_ranking(con, f: Filters) -> pd.DataFrame:
    sql = base_cte(f) + f"""
    SELECT pm.province_name_th, pm.region_th, pm.population,
           ROUND(AVG(pm.avg_pm25), 2)                              AS avg_pm25,
           SUM(pm.exceedance_days_th)                              AS exceedance_days_th,
           SUM(pm.days_with_data)                                  AS days_with_data,
           SUM(vis.visits)                                         AS visits,
           ROUND(SUM(vis.visits) * 100000.0 / ANY_VALUE(pm.population), 0) AS visits_per_100k
    FROM pm
    JOIN vis USING (province_key, month_key)
    WHERE pm.avg_pm25 IS NOT NULL
      AND pm.days_with_data >= {MIN_DAYS_FOR_ANALYSIS}
    GROUP BY 1, 2, 3
    HAVING COUNT(*) >= 6      -- ต้องมีอย่างน้อย 6 เดือนที่ข้อมูลครบ
    ORDER BY visits_per_100k DESC
    """
    return con.execute(sql).df()


def station_map(con, f: Filters) -> pd.DataFrame:
    """ค่าฝุ่นเฉลี่ยรายสถานี พร้อมพิกัด — ใช้วาดแผนที่"""
    sql = f"""
    SELECT s.station_name, s.locality, s.lat, s.lon,
           s.pollution_source_type, p.province_name_th, p.region_th,
           ROUND(AVG(fa.avg_pm25), 2)                                   AS avg_pm25,
           SUM(fa.is_exceedance_th)                                     AS exceedance_days_th,
           COUNT(*)                                                     AS n_days,
           ROUND(SUM(fa.is_exceedance_th) * 100.0 / COUNT(*), 1)        AS exceedance_pct
    FROM FACT_AIR_QUALITY_DAILY fa
    JOIN DIM_STATION  s USING (station_key)
    JOIN DIM_PROVINCE p ON p.province_key = fa.province_key
    JOIN DIM_DATE     d USING (date_key)
    WHERE d.year BETWEEN {f.year_min} AND {f.year_max}
      AND {_in_clause('p.province_name_th', f.provinces)}
    GROUP BY 1,2,3,4,5,6,7
    ORDER BY avg_pm25 DESC
    """
    return con.execute(sql).df()


# ─────────────────────────────────────────────────────────────────────
# 6) BQ4 — กลุ่มโรคย่อยไหนผันผวนตามฝุ่นมากสุด
# ─────────────────────────────────────────────────────────────────────
def disease_subgroup_analysis(con, f: Filters) -> pd.DataFrame:
    """ไม่ใช้ filter กลุ่มโรคจาก sidebar — ต้องเทียบทุกกลุ่มถึงจะตอบ BQ4 ได้
    รวมกลุ่มควบคุม (ตา / ผิวหนัง / หัวใจ) ไว้ด้วยเพื่อแยกผลของฝุ่นออกจากผลฤดูกาล"""
    sql = base_cte(f, apply_disease_filter=False) + f"""
    , dv AS (
        SELECT b.disease_key, b.disease_group_id, b.disease_name_en,
               b.disease_group_name_th, b.is_respiratory,
               b.province_key, b.month_key, b.month,
               b.visit_count, pm.avg_pm25
        FROM base b
        JOIN pm USING (province_key, month_key)
        WHERE pm.avg_pm25 IS NOT NULL
          AND pm.days_with_data >= {MIN_DAYS_FOR_ANALYSIS}
    ),
    resid AS (
        SELECT *,
               avg_pm25    - AVG(avg_pm25)    OVER w AS pm_r,
               visit_count - AVG(visit_count) OVER w AS vis_r
        FROM dv WINDOW w AS (PARTITION BY disease_key, province_key, month)
    )
    SELECT disease_key,
           ANY_VALUE(disease_name_en)                                   AS disease_name_en,
           ANY_VALUE(disease_group_name_th)                             AS disease_group_name_th,
           ANY_VALUE(is_respiratory)                                    AS is_respiratory,
           SUM(visit_count)                                             AS visits,
           ROUND(corr(pm_r, vis_r), 3)                                  AS r_deseason,
           COUNT(*)                                                     AS n
    FROM resid
    GROUP BY 1
    HAVING SUM(visit_count) > 0
    ORDER BY r_deseason DESC NULLS LAST
    """
    return con.execute(sql).df()


# ─────────────────────────────────────────────────────────────────────
# 7) BQ5 — สภาพอากาศกับความรุนแรงของฝุ่น (grain รายวัน)
# ─────────────────────────────────────────────────────────────────────
def weather_vs_pm25(con, f: Filters, by: str = "humidity_band") -> pd.DataFrame:
    sql = f"""
    SELECT w.{by}                                            AS band,
           ROUND(AVG(fa.avg_pm25), 2)                        AS avg_pm25,
           COUNT(*)                                          AS n_days,
           ROUND(SUM(fa.is_exceedance_th) * 100.0 / COUNT(*), 1) AS exceedance_pct
    FROM FACT_AIR_QUALITY_DAILY fa
    JOIN DIM_WEATHER  w USING (weather_key)
    JOIN DIM_DATE     d USING (date_key)
    JOIN DIM_PROVINCE p ON p.province_key = fa.province_key
    WHERE d.year BETWEEN {f.year_min} AND {f.year_max}
      AND {_in_clause('p.province_name_th', f.provinces)}
    GROUP BY 1
    ORDER BY avg_pm25 DESC
    """
    return con.execute(sql).df()


def weather_heatmap(con, f: Filters) -> pd.DataFrame:
    """ตารางไขว้ ความชื้น × ความเร็วลม — หัวใจของ BQ5"""
    sql = f"""
    SELECT w.humidity_band, w.wind_band,
           ROUND(AVG(fa.avg_pm25), 1) AS avg_pm25,
           COUNT(*)                   AS n_days
    FROM FACT_AIR_QUALITY_DAILY fa
    JOIN DIM_WEATHER  w USING (weather_key)
    JOIN DIM_DATE     d USING (date_key)
    JOIN DIM_PROVINCE p ON p.province_key = fa.province_key
    WHERE d.year BETWEEN {f.year_min} AND {f.year_max}
      AND {_in_clause('p.province_name_th', f.provinces)}
    GROUP BY 1, 2
    HAVING COUNT(*) >= 30
    """
    return con.execute(sql).df()


# ─────────────────────────────────────────────────────────────────────
# 8) BQ6 — แนวโน้มระยะยาว
# ─────────────────────────────────────────────────────────────────────
def yearly_trend(con, f: Filters) -> pd.DataFrame:
    sql = base_cte(f) + f"""
    SELECT pm.year,
           ROUND(AVG(pm.avg_pm25), 2)                                     AS avg_pm25,
           SUM(pm.exceedance_days_th)                                     AS exceedance_days_th,
           SUM(pm.days_with_data)                                         AS days_with_data,
           ROUND(SUM(pm.exceedance_days_th) * 100.0 / SUM(pm.days_with_data), 1) AS exceedance_pct,
           SUM(vis.visits)                                                AS visits,
           COUNT(DISTINCT pm.province_key)                                AS n_provinces
    FROM pm
    LEFT JOIN vis USING (province_key, month_key)
    WHERE pm.days_with_data >= {MIN_DAYS_FOR_ANALYSIS}
    GROUP BY 1
    ORDER BY 1
    """
    return con.execute(sql).df()


# ─────────────────────────────────────────────────────────────────────
# 9) BQ7 — หาเกณฑ์ที่ภาระผู้ป่วยเริ่มกระโดด
# ─────────────────────────────────────────────────────────────────────
def pm25_bands(con, f: Filters) -> pd.DataFrame:
    sql = base_cte(f) + f"""
    , banded AS (
        SELECT CASE
                 WHEN pm.avg_pm25 <  {WHO_GUIDELINE_PM25} THEN '1) < 15 (ผ่านเกณฑ์ WHO)'
                 WHEN pm.avg_pm25 <  25                    THEN '2) 15–25'
                 WHEN pm.avg_pm25 <  {THAI_STANDARD_PM25}  THEN '3) 25–37.5'
                 ELSE                                            '4) > 37.5 (เกินมาตรฐานไทย)'
               END                       AS pm_band,
               pm.avg_pm25, vis.visits
        FROM pm JOIN vis USING (province_key, month_key)
        WHERE pm.avg_pm25 IS NOT NULL
          AND pm.days_with_data >= {MIN_DAYS_FOR_ANALYSIS}
    )
    SELECT pm_band,
           COUNT(*)                    AS n_province_months,
           ROUND(AVG(avg_pm25), 1)     AS avg_pm25,
           ROUND(AVG(visits), 0)       AS avg_visits,
           ROUND(MEDIAN(visits), 0)    AS median_visits
    FROM banded
    GROUP BY 1
    ORDER BY 1
    """
    return con.execute(sql).df()


def excess_visit_ratio(con, f: Filters) -> pd.DataFrame:
    """M5 — เดือนฝุ่นสูงมีผู้ป่วยมากกว่าเดือนฝุ่นต่ำกี่เท่า (เทียบภายในจังหวัดเดียวกัน)"""
    sql = base_cte(f) + f"""
    , pv AS (
        SELECT pm.province_name_th, pm.region_th, pm.avg_pm25, vis.visits
        FROM pm JOIN vis USING (province_key, month_key)
        WHERE pm.avg_pm25 IS NOT NULL
          AND pm.days_with_data >= {MIN_DAYS_FOR_ANALYSIS}
    )
    SELECT province_name_th, region_th,
           ROUND(AVG(visits) FILTER (WHERE avg_pm25 >  {THAI_STANDARD_PM25}), 0) AS visits_high_pm,
           ROUND(AVG(visits) FILTER (WHERE avg_pm25 <= {WHO_GUIDELINE_PM25}), 0) AS visits_low_pm,
           ROUND(AVG(visits) FILTER (WHERE avg_pm25 >  {THAI_STANDARD_PM25})
               / NULLIF(AVG(visits) FILTER (WHERE avg_pm25 <= {WHO_GUIDELINE_PM25}), 0), 2)
                                                                                  AS excess_ratio,
           COUNT(*) FILTER (WHERE avg_pm25 >  {THAI_STANDARD_PM25})                AS n_high,
           COUNT(*) FILTER (WHERE avg_pm25 <= {WHO_GUIDELINE_PM25})                AS n_low
    FROM pv
    GROUP BY 1, 2
    HAVING n_high >= 3 AND n_low >= 3   -- ต้องมีทั้งเดือนฝุ่นสูงและต่ำอย่างละ 3 เดือนขึ้นไป
    ORDER BY excess_ratio DESC
    """
    return con.execute(sql).df()


# ─────────────────────────────────────────────────────────────────────
# 10) M6 — คุณภาพ/ความครบถ้วนของข้อมูล
# ─────────────────────────────────────────────────────────────────────
def coverage_matrix(con, f: Filters) -> pd.DataFrame:
    """ตารางไขว้ จังหวัด × เดือน แสดงจำนวนวันที่มีข้อมูลฝุ่น — ทำให้ 'ช่องว่างของข้อมูล' มองเห็นได้"""
    sql = base_cte(f) + """
    SELECT province_name_th,
           MAKE_DATE(year, month, 1)   AS month_date,
           MAX(days_with_data)         AS days_with_data
    FROM pm
    GROUP BY 1, 2
    ORDER BY 1, 2
    """
    return con.execute(sql).df()


def warehouse_summary(con) -> pd.DataFrame:
    rows = con.execute("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'main' ORDER BY table_name
    """).fetchall()
    out = []
    for (t,) in rows:
        n = con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
        kind = ("Fact" if t.startswith("FACT_") else
                "Dimension" if t.startswith("DIM_") else
                "Aggregate" if t.startswith("AGG_") else "Staging")
        out.append({"ตาราง": t, "ประเภท": kind, "จำนวนแถว": n})
    return pd.DataFrame(out).sort_values(
        ["ประเภท", "ตาราง"],
        key=lambda s: s.map({"Fact": 0, "Dimension": 1, "Aggregate": 2, "Staging": 3}).fillna(9)
        if s.name == "ประเภท" else s,
    )


def data_quality_notes(con, f: Filters) -> dict:
    """ตัวเลขที่ใช้เตือนผู้ใช้ว่าอย่าอ่านกราฟเกินกว่าที่ข้อมูลรองรับ"""
    sql = base_cte(f) + f"""
    SELECT COUNT(*)                                                          AS n_province_months,
           COUNT(*) FILTER (WHERE avg_pm25 IS NULL)                          AS n_no_pm,
           COUNT(*) FILTER (WHERE avg_pm25 IS NOT NULL
                              AND days_with_data < {MIN_DAYS_FOR_ANALYSIS})  AS n_thin_pm,
           ROUND(AVG(avg_stations_per_day), 2)                               AS avg_stations
    FROM pm
    """
    return con.execute(sql).df().iloc[0].to_dict()


# ═════════════════════════════════════════════════════════════════════
# ส่วนที่เพิ่มเพื่อตอบ Business Questions ตามเอกสาร Business Requirements.pdf
# ═════════════════════════════════════════════════════════════════════

# CTE จับคู่จังหวัดกับประเภทแหล่งกำเนิดฝุ่น
# ตรวจแล้วพบว่า **ทุกจังหวัดมีสถานีประเภทเดียวกันทั้งหมด** (ไม่มีจังหวัดที่ผสมหลายประเภท)
# จึงใช้ ANY_VALUE ได้โดยไม่เสียความหมาย
PROVINCE_SOURCE_CTE = """
    ps AS (
        SELECT province_key,
               ANY_VALUE(pollution_source_type) AS source_type,
               COUNT(*)                         AS n_stations
        FROM DIM_STATION
        GROUP BY 1
    )
"""


# ─────────────────────────────────────────────────────────────────────
# BQ2 (PDF) — ฤดูฝุ่น ธ.ค.–เม.ย. ต่างจากช่วงอื่นเพียงใด
# ─────────────────────────────────────────────────────────────────────
def haze_season_comparison(con, f: Filters) -> pd.DataFrame:
    sql = base_cte(f) + f"""
    SELECT CASE WHEN pm.is_haze_season THEN 'ฤดูฝุ่น (ธ.ค.–เม.ย.)'
                ELSE 'นอกฤดูฝุ่น (พ.ค.–พ.ย.)' END          AS season,
           COUNT(*)                                          AS n_province_months,
           ROUND(AVG(pm.avg_pm25), 2)                        AS avg_pm25,
           ROUND(MAX(pm.avg_pm25), 2)                        AS max_pm25,
           SUM(pm.exceedance_days_th)                        AS exceedance_days_th,
           SUM(pm.days_with_data)                            AS days_with_data,
           ROUND(SUM(pm.exceedance_days_th) * 100.0
                 / NULLIF(SUM(pm.days_with_data), 0), 1)     AS exceedance_pct,
           ROUND(AVG(vis.visits), 0)                         AS avg_visits
    FROM pm
    LEFT JOIN vis USING (province_key, month_key)
    WHERE pm.avg_pm25 IS NOT NULL
      AND pm.days_with_data >= {MIN_DAYS_FOR_ANALYSIS}
    GROUP BY 1
    ORDER BY avg_pm25 DESC
    """
    return con.execute(sql).df()


def haze_by_region(con, f: Filters) -> pd.DataFrame:
    """ฤดูฝุ่นรุนแรงต่างกันแค่ไหนในแต่ละภาค — ผู้ใช้คือเขตสุขภาพที่ต้องวางแผนคนละแบบ"""
    sql = base_cte(f) + f"""
    SELECT pm.region_th,
           ROUND(AVG(pm.avg_pm25) FILTER (WHERE pm.is_haze_season), 2)       AS pm25_haze,
           ROUND(AVG(pm.avg_pm25) FILTER (WHERE NOT pm.is_haze_season), 2)   AS pm25_non_haze,
           ROUND(AVG(pm.avg_pm25) FILTER (WHERE pm.is_haze_season)
               / NULLIF(AVG(pm.avg_pm25) FILTER (WHERE NOT pm.is_haze_season), 0), 2)
                                                                              AS ratio,
           COUNT(DISTINCT pm.province_key)                                    AS n_provinces
    FROM pm
    WHERE pm.avg_pm25 IS NOT NULL
      AND pm.days_with_data >= {MIN_DAYS_FOR_ANALYSIS}
    GROUP BY 1
    HAVING pm25_haze IS NOT NULL AND pm25_non_haze IS NOT NULL
    ORDER BY ratio DESC
    """
    return con.execute(sql).df()


# ─────────────────────────────────────────────────────────────────────
# BQ3 (PDF) — แหล่งกำเนิดฝุ่นแบบใดสัมพันธ์กับผู้ป่วยมากที่สุด
# ─────────────────────────────────────────────────────────────────────
def source_type_analysis(con, f: Filters) -> pd.DataFrame:
    sql = base_cte(f) + f"""
    , {PROVINCE_SOURCE_CTE}
    , pv AS (
        SELECT ps.source_type, pm.province_key, pm.month, pm.avg_pm25,
               pm.exceedance_days_th, pm.days_with_data, pm.population,
               vis.visits
        FROM pm
        JOIN vis USING (province_key, month_key)
        JOIN ps  USING (province_key)
        WHERE pm.avg_pm25 IS NOT NULL
          AND pm.days_with_data >= {MIN_DAYS_FOR_ANALYSIS}
    ),
    resid AS (
        SELECT *,
               avg_pm25 - AVG(avg_pm25) OVER w AS pm_r,
               visits   - AVG(visits)   OVER w AS vis_r
        FROM pv WINDOW w AS (PARTITION BY province_key, month)
    )
    , prov_pop AS (
        -- ประชากรต้องนับจังหวัดละครั้งเดียว ห้ามให้ซ้ำตามจำนวนเดือน
        SELECT DISTINCT province_key, source_type, population FROM pv
    )
    SELECT r.source_type,
           COUNT(DISTINCT r.province_key)                                     AS n_provinces,
           COUNT(*)                                                           AS n_province_months,
           ROUND(AVG(r.avg_pm25), 2)                                          AS avg_pm25,
           ROUND(SUM(r.exceedance_days_th) * 100.0
                 / NULLIF(SUM(r.days_with_data), 0), 1)                       AS exceedance_pct,
           SUM(r.visits)                                                      AS visits,
           ROUND(SUM(r.visits) * 100000.0
                 / NULLIF((SELECT SUM(population) FROM prov_pop pp
                            WHERE pp.source_type = r.source_type), 0), 0)     AS visits_per_100k,
           ROUND(corr(r.pm_r, r.vis_r), 3)                                    AS r_deseason
    FROM resid r
    GROUP BY 1
    ORDER BY r_deseason DESC NULLS LAST
    """
    return con.execute(sql).df()


def source_type_by_region(con, f: Filters) -> pd.DataFrame:
    """ตารางไขว้ ภาค × แหล่งกำเนิดฝุ่น — ตอบครึ่งหลังของ BQ3 ว่าภูมิภาคใดเสี่ยงสูงสุด"""
    sql = base_cte(f) + f"""
    , {PROVINCE_SOURCE_CTE}
    SELECT pm.region_th, ps.source_type,
           COUNT(DISTINCT pm.province_key)                                 AS n_provinces,
           ROUND(AVG(pm.avg_pm25), 1)                                      AS avg_pm25,
           ROUND(SUM(pm.exceedance_days_th) * 100.0
                 / NULLIF(SUM(pm.days_with_data), 0), 1)                   AS exceedance_pct
    FROM pm
    JOIN ps USING (province_key)
    WHERE pm.avg_pm25 IS NOT NULL
      AND pm.days_with_data >= {MIN_DAYS_FOR_ANALYSIS}
    GROUP BY 1, 2
    ORDER BY avg_pm25 DESC
    """
    return con.execute(sql).df()


# ─────────────────────────────────────────────────────────────────────
# BQ4 (PDF) — กลุ่มควบคุม: ช่วงฝุ่นสูงเทียบฝุ่นต่ำ
# ─────────────────────────────────────────────────────────────────────
def control_group_high_low(con, f: Filters) -> pd.DataFrame:
    """คำถามจาก PDF: "ผู้ป่วยทางเดินหายใจเพิ่มขึ้นชัดกว่ากลุ่มควบคุมจริงหรือไม่"

    วิธี: เทียบ **ภายในจังหวัดเดียวกัน** ก่อน แล้วจึงหาค่ากลางข้ามจังหวัด
    ถ้าเทียบรวมทุกจังหวัดพร้อมกันจะเจอ Simpson's paradox — จังหวัดที่ฝุ่นสูง
    บังเอิญเป็นจังหวัดเล็ก ยอดผู้ป่วยจึงต่ำด้วยเหตุผลที่ไม่เกี่ยวกับฝุ่นเลย
    """
    sql = base_cte(f, apply_disease_filter=False) + f"""
    , dv AS (
        SELECT b.disease_key, b.province_key, b.visit_count, pm.avg_pm25
        FROM base b
        JOIN pm USING (province_key, month_key)
        WHERE pm.avg_pm25 IS NOT NULL
          AND pm.days_with_data >= {MIN_DAYS_FOR_ANALYSIS}
    ),
    per_prov AS (
        SELECT disease_key, province_key,
               AVG(visit_count) FILTER (WHERE avg_pm25 >  {THAI_STANDARD_PM25}) AS v_high,
               AVG(visit_count) FILTER (WHERE avg_pm25 <= {WHO_GUIDELINE_PM25}) AS v_low,
               COUNT(*) FILTER (WHERE avg_pm25 >  {THAI_STANDARD_PM25})          AS n_high,
               COUNT(*) FILTER (WHERE avg_pm25 <= {WHO_GUIDELINE_PM25})          AS n_low
        FROM dv
        GROUP BY 1, 2
    )
    SELECT g.disease_key,
           g.disease_name_en, g.disease_group_name_th, g.is_respiratory,
           ROUND(MEDIAN(pp.v_high / NULLIF(pp.v_low, 0)), 3)  AS ratio_median,
           ROUND(AVG(pp.v_high / NULLIF(pp.v_low, 0)), 3)     AS ratio_mean,
           COUNT(*) FILTER (WHERE pp.v_high > pp.v_low)        AS n_prov_increase,
           COUNT(*)                                            AS n_provinces
    FROM per_prov pp
    JOIN DIM_DISEASE_GROUP g USING (disease_key)
    WHERE pp.n_high >= 3 AND pp.n_low >= 3      -- ต้องมีทั้งเดือนฝุ่นสูงและต่ำอย่างละ ≥ 3
    GROUP BY 1, 2, 3, 4
    HAVING COUNT(*) >= 5                         -- ต้องเทียบได้อย่างน้อย 5 จังหวัด
    ORDER BY ratio_median DESC
    """
    return con.execute(sql).df()


# ─────────────────────────────────────────────────────────────────────
# BQ7 (PDF) — drill-down จังหวัด → โรงพยาบาล → กลุ่มโรค
# ─────────────────────────────────────────────────────────────────────
def province_risk(con, f: Filters) -> pd.DataFrame:
    """ชั้นที่ 1 ของ drill-down — จัดอันดับจังหวัดด้วยคะแนนความเสี่ยงรวม

    คะแนนความเสี่ยง = ค่าเฉลี่ยของอันดับเปอร์เซ็นไทล์ 2 ด้าน
    (สัดส่วนวันฝุ่นเกินมาตรฐาน + อัตราป่วยต่อประชากรแสนคน)
    ใช้อันดับเปอร์เซ็นไทล์เพราะสองตัวคนละหน่วย บวกกันตรง ๆ ไม่ได้
    """
    sql = base_cte(f) + f"""
    , {PROVINCE_SOURCE_CTE}
    , agg AS (
        SELECT pm.province_name_th, pm.region_th, ps.source_type, ps.n_stations,
               ROUND(AVG(pm.avg_pm25), 2)                                  AS avg_pm25,
               SUM(pm.exceedance_days_th)                                  AS exceedance_days_th,
               SUM(pm.days_with_data)                                      AS days_with_data,
               ROUND(SUM(pm.exceedance_days_th) * 100.0
                     / NULLIF(SUM(pm.days_with_data), 0), 1)               AS exceedance_pct,
               SUM(vis.visits)                                             AS visits,
               ROUND(SUM(vis.visits) * 100000.0
                     / NULLIF(ANY_VALUE(pm.population), 0), 0)             AS visits_per_100k,
               COUNT(*)                                                    AS n_months
        FROM pm
        JOIN vis USING (province_key, month_key)
        JOIN ps  USING (province_key)
        WHERE pm.avg_pm25 IS NOT NULL
          AND pm.days_with_data >= {MIN_DAYS_FOR_ANALYSIS}
        GROUP BY 1, 2, 3, 4
        HAVING COUNT(*) >= 6
    )
    SELECT *,
           ROUND((PERCENT_RANK() OVER (ORDER BY exceedance_pct)
                + PERCENT_RANK() OVER (ORDER BY visits_per_100k)) / 2, 3)  AS risk_score
    FROM agg
    ORDER BY risk_score DESC
    """
    return con.execute(sql).df()


def hospital_ranking(con, f: Filters, province_name: str = "", top_n: int = 25) -> pd.DataFrame:
    """ชั้นที่ 2 — โรงพยาบาลในจังหวัดที่เลือก

    หมายเหตุ: DIM_HOSPITAL ไม่มีชื่อโรงพยาบาล (ต้นทาง HDC ให้มาแค่ hospcode)
    จึงแสดงเป็นรหัส + อำเภอ ซึ่งระบุตัวได้จริงในทางปฏิบัติ
    """
    provs = [province_name] if province_name else f.provinces
    sql = f"""
    WITH dm AS (SELECT DISTINCT month_key, year, is_haze_season FROM DIM_DATE)
    SELECT h.hospcode, h.district_name_th, p.province_name_th,
           SUM(fd.visit_count)                                              AS visits,
           SUM(fd.visit_count) FILTER (WHERE dm.is_haze_season)             AS visits_haze,
           SUM(fd.visit_count) FILTER (WHERE NOT dm.is_haze_season)         AS visits_non_haze,
           COUNT(DISTINCT fd.month_key) FILTER (WHERE dm.is_haze_season)    AS n_haze_months,
           COUNT(DISTINCT fd.month_key) FILTER (WHERE NOT dm.is_haze_season) AS n_non_months,
           ROUND(
               (SUM(fd.visit_count) FILTER (WHERE dm.is_haze_season)
                 / NULLIF(COUNT(DISTINCT fd.month_key) FILTER (WHERE dm.is_haze_season), 0))
             / NULLIF(SUM(fd.visit_count) FILTER (WHERE NOT dm.is_haze_season)
                 / NULLIF(COUNT(DISTINCT fd.month_key) FILTER (WHERE NOT dm.is_haze_season), 0), 0)
           , 2)                                                             AS haze_ratio
    FROM FACT_DISEASE_MONTHLY fd
    JOIN DIM_HOSPITAL      h USING (hospital_key)
    JOIN DIM_PROVINCE      p ON p.province_key = fd.province_key
    JOIN DIM_DISEASE_GROUP g USING (disease_key)
    JOIN dm                  USING (month_key)
    WHERE dm.year BETWEEN {f.year_min} AND {f.year_max}
      AND {_in_clause('p.province_name_th', provs)}
      AND {f.where_disease}
    GROUP BY 1, 2, 3
    ORDER BY visits DESC
    LIMIT {int(top_n)}
    """
    return con.execute(sql).df()


def hospital_disease_breakdown(con, f: Filters, hospcode) -> pd.DataFrame:
    """ชั้นที่ 3 — กลุ่มโรคของโรงพยาบาลที่เลือก แยกฤดูฝุ่น/นอกฤดู"""
    sql = f"""
    WITH dm AS (SELECT DISTINCT month_key, year, is_haze_season FROM DIM_DATE)
    SELECT g.disease_name_en, g.disease_group_name_th, g.is_respiratory,
           SUM(fd.visit_count)                                              AS visits,
           ROUND(AVG(fd.visit_count) FILTER (WHERE dm.is_haze_season), 1)   AS avg_haze,
           ROUND(AVG(fd.visit_count) FILTER (WHERE NOT dm.is_haze_season), 1) AS avg_non_haze,
           ROUND(AVG(fd.visit_count) FILTER (WHERE dm.is_haze_season)
               / NULLIF(AVG(fd.visit_count) FILTER (WHERE NOT dm.is_haze_season), 0), 2)
                                                                             AS haze_ratio
    FROM FACT_DISEASE_MONTHLY fd
    JOIN DIM_HOSPITAL      h USING (hospital_key)
    JOIN DIM_DISEASE_GROUP g USING (disease_key)
    JOIN dm                  USING (month_key)
    WHERE dm.year BETWEEN {f.year_min} AND {f.year_max}
      AND h.hospcode = {_q(hospcode)}
    GROUP BY 1, 2, 3
    ORDER BY visits DESC
    """
    return con.execute(sql).df()


def hospital_monthly(con, f: Filters, hospcode) -> pd.DataFrame:
    """อนุกรมเวลาของโรงพยาบาลเดียว เทียบกับ PM2.5 ของจังหวัดที่โรงพยาบาลนั้นตั้งอยู่"""
    sql = f"""
    WITH dm AS (SELECT DISTINCT month_key, year, month FROM DIM_DATE),
    h AS (SELECT hospital_key, province_key FROM DIM_HOSPITAL WHERE hospcode = {_q(hospcode)}),
    v AS (
        SELECT fd.month_key, SUM(fd.visit_count) AS visits
        FROM FACT_DISEASE_MONTHLY fd
        JOIN h USING (hospital_key)
        JOIN DIM_DISEASE_GROUP g USING (disease_key)
        WHERE {f.where_disease}
        GROUP BY 1
    ),
    pmv AS (
        SELECT a.month_key, MAX(a.avg_pm25) AS avg_pm25, MAX(a.days_with_data) AS days_with_data
        FROM AGG_PM25_DISEASE_MONTHLY a
        WHERE a.province_key = (SELECT province_key FROM h LIMIT 1)
        GROUP BY 1
    )
    SELECT dm.year, dm.month, MAKE_DATE(dm.year, dm.month, 1) AS month_date,
           v.visits, pmv.avg_pm25, pmv.days_with_data
    FROM v
    JOIN dm USING (month_key)
    LEFT JOIN pmv USING (month_key)
    WHERE dm.year BETWEEN {f.year_min} AND {f.year_max}
    ORDER BY month_date
    """
    return con.execute(sql).df()


# ─────────────────────────────────────────────────────────────────────
# หมายเหตุคุณภาพข้อมูลตาม PDF — ต้องแสดง coverage_ratio กำกับ Measure หลัก
# ─────────────────────────────────────────────────────────────────────
def coverage_stats(con, f: Filters) -> dict:
    """coverage_ratio = สัดส่วนชั่วโมงที่วัดได้ต่อวัน

    ข้อควรรู้: FACT_AIR_QUALITY_DAILY เก็บเฉพาะวันที่วัดได้ ≥ 18 จาก 24 ชม.
    (MIN_READINGS_PER_DAY) ค่าต่ำสุดในตารางจึงเป็น 0.75 เสมอ
    ส่วนวันที่ข้อมูลไม่ครบถูกคัดทิ้งตั้งแต่ขั้น Clean — นับจำนวนจาก stg_measurements
    """
    row = con.execute(f"""
    SELECT ROUND(AVG(fa.coverage_ratio), 3)                                    AS avg_coverage,
           ROUND(MIN(fa.coverage_ratio), 3)                                    AS min_coverage,
           COUNT(*)                                                            AS n_station_days,
           COUNT(*) FILTER (WHERE fa.coverage_ratio = 1.0)                     AS n_full_days,
           ROUND(COUNT(*) FILTER (WHERE fa.coverage_ratio = 1.0) * 100.0
                 / COUNT(*), 1)                                                AS pct_full
    FROM FACT_AIR_QUALITY_DAILY fa
    JOIN DIM_DATE     d USING (date_key)
    JOIN DIM_PROVINCE p ON p.province_key = fa.province_key
    WHERE d.year BETWEEN {f.year_min} AND {f.year_max}
      AND {_in_clause('p.province_name_th', f.provinces)}
    """).df().iloc[0].to_dict()

    dropped = con.execute("""
        WITH raw AS (
            SELECT location_id,
                CAST(strftime(datetime, '%Y-%m-%d') AS DATE) AS d,
                COUNT(*) AS n
            FROM stg_measurements
            WHERE parameter = 'pm25' AND value IS NOT NULL
            GROUP BY 1, 2
        )
        SELECT COUNT(*) AS raw_station_days,
            COUNT(*) FILTER (WHERE n < 18) AS dropped_station_days,
            ROUND(
                COUNT(*) FILTER (WHERE n < 18) * 100.0 / COUNT(*),
                1
            ) AS pct_dropped
        FROM raw
    """).df().iloc[0].to_dict()
    row.update(dropped)
    return row


def coverage_by_province(con, f: Filters) -> pd.DataFrame:
    sql = f"""
    SELECT p.province_name_th, p.region_th,
           ROUND(AVG(fa.coverage_ratio), 3)  AS avg_coverage,
           COUNT(*)                          AS n_station_days,
           ROUND(AVG(fa.n_readings), 1)      AS avg_readings_per_day
    FROM FACT_AIR_QUALITY_DAILY fa
    JOIN DIM_DATE     d USING (date_key)
    JOIN DIM_PROVINCE p ON p.province_key = fa.province_key
    WHERE d.year BETWEEN {f.year_min} AND {f.year_max}
      AND {_in_clause('p.province_name_th', f.provinces)}
    GROUP BY 1, 2
    ORDER BY avg_coverage
    """
    return con.execute(sql).df()
