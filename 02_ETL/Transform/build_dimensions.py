"""
build_dimensions.py — ขั้น TRANSFORM: แปลง staging เป็น Dimension Tables

ใช้งาน:
    python 02_ETL/03_transform/build_dimensions.py

ขั้นตอนนี้คือ "Transform" ตามกระบวนการ Extract → Clean → Transform → Integrate → Load
หน้าที่คือแปลงข้อมูลดิบที่สะอาดแล้วให้เป็น dimension ที่พร้อมใช้ ได้แก่
    - สร้าง Surrogate Key ด้วย ROW_NUMBER() เรียงตาม natural key (deterministic)
    - คำนวณ attribute ที่ต้นทางไม่มี เช่น region_th, season_th, is_haze_season,
      ปี พ.ศ., การจัด bin สภาพอากาศ, ประเภทแหล่งกำเนิดมลพิษ
    - จัดการ SCD Type 1 บน areacode ของโรงพยาบาล

อ่านจากตาราง stg_* ใน warehouse อย่างเดียว ไม่แตะไฟล์ดิบ

ผลลัพธ์: DIM_DATE, DIM_PROVINCE, DIM_STATION, DIM_HOSPITAL,
         DIM_DISEASE_GROUP, DIM_WEATHER
"""
import duckdb

# ให้ import config.py จากโฟลเดอร์แม่ (02_ETL) ได้ แม้สคริปต์จะอยู่ในโฟลเดอร์ย่อย
import sys
from pathlib import Path as _Path
sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

from config import (
    DW_PATH,
    STATION_SOURCE_TYPE, STATION_PROVINCE,
    ARCHIVE_YEARS, LOCAL_TZ,
)


def sql_map(mapping, key_type="INTEGER"):
    """แปลง dict ของ Python ให้เป็น CASE WHEN ของ SQL"""
    whens = "\n".join(
        f"            WHEN {k} THEN '{v}'" for k, v in mapping.items())
    return f"CASE CAST(location_id AS {key_type})\n{whens}\n            ELSE NULL END"


def build_dim_date(con):
    """DIM_DATE — ครอบคลุมทั้งช่วง archive เพื่อรองรับการขยายขอบเขตในอนาคต"""
    start, end = f"{min(ARCHIVE_YEARS)}-01-01", f"{max(ARCHIVE_YEARS) + 1}-12-31"
    con.execute(f"""
        CREATE OR REPLACE TABLE DIM_DATE AS
        SELECT
            CAST(strftime(d, '%Y%m%d') AS INTEGER)      AS date_key,
            d                                           AS full_date,
            EXTRACT(year  FROM d)                       AS year,
            EXTRACT(year  FROM d) + 543                 AS year_be,
            EXTRACT(quarter FROM d)                     AS quarter,
            EXTRACT(month FROM d)                       AS month,
            EXTRACT(day   FROM d)                       AS day,
            CAST(strftime(d, '%Y%m') AS INTEGER)        AS month_key,
            CASE EXTRACT(month FROM d)
                WHEN 1 THEN 'มกราคม'    WHEN 2 THEN 'กุมภาพันธ์' WHEN 3 THEN 'มีนาคม'
                WHEN 4 THEN 'เมษายน'    WHEN 5 THEN 'พฤษภาคม'   WHEN 6 THEN 'มิถุนายน'
                WHEN 7 THEN 'กรกฎาคม'   WHEN 8 THEN 'สิงหาคม'   WHEN 9 THEN 'กันยายน'
                WHEN 10 THEN 'ตุลาคม'   WHEN 11 THEN 'พฤศจิกายน' ELSE 'ธันวาคม'
            END                                         AS month_name_th,
            CASE
                WHEN EXTRACT(month FROM d) IN (11, 12, 1, 2)   THEN 'ฤดูหนาว'
                WHEN EXTRACT(month FROM d) IN (3, 4, 5)        THEN 'ฤดูร้อน'
                ELSE 'ฤดูฝน'
            END                                         AS season_th,
            -- ช่วงฝุ่นสูงของไทย ธ.ค.-เม.ย. ใช้เป็น filter หลักบน Dashboard
            EXTRACT(month FROM d) IN (12, 1, 2, 3, 4)   AS is_haze_season
        FROM (SELECT UNNEST(generate_series(DATE '{start}', DATE '{end}',
                                            INTERVAL 1 DAY)) AS d);
    """)


def build_dim_province(con):
    """DIM_PROVINCE — 77 จังหวัดจาก HDC + ธงว่าจังหวัดใดมีสถานีวัดฝุ่น"""
    # อ่านจาก staging ไม่ใช่ไฟล์ดิบ — ถ้ายังไม่ได้รัน clean_population.py
    # ให้ population เป็น NULL แล้วเตือน (ไม่ล้มทั้ง pipeline เพราะเป็นข้อมูลเสริม)
    has_pop = con.execute("""
        SELECT COUNT(*) FROM duckdb_tables() WHERE table_name = 'stg_population'
    """).fetchone()[0]
    if has_pop:
        pop_cte = "SELECT province_code, population FROM stg_population"
        n_pop = con.execute("SELECT COUNT(*) FROM stg_population").fetchone()[0]
        print(f"  ใช้ stg_population: {n_pop} จังหวัด")
    else:
        pop_cte = "SELECT NULL::INTEGER AS province_code, NULL::BIGINT AS population WHERE FALSE"
        print("  [เตือน] ไม่พบ stg_population → DIM_PROVINCE.population = NULL")
        print("          รัน 02_clean/clean_population.py แล้วสร้าง schema ใหม่")

    stations = ", ".join(f"'{p}'" for p in set(STATION_PROVINCE.values()))
    con.execute(f"""
        CREATE OR REPLACE TABLE DIM_PROVINCE AS
        WITH provinces AS (
            SELECT DISTINCT province_code, province_name AS province_name_th
            FROM stg_disease_monthly
        ),
        pop AS ({pop_cte}),
        area AS (
            -- ชื่อจังหวัดภาษาอังกฤษ — dim_area มีระดับอำเภอ ต้องยุบเป็นจังหวัดก่อน
            SELECT province_code, any_value(province_name_en) AS province_name_en
            FROM stg_area GROUP BY 1
        )
        SELECT
            ROW_NUMBER() OVER (ORDER BY p.province_code)  AS province_key,
            p.province_code,
            p.province_name_th,
            area.province_name_en,
            CASE
                WHEN p.province_code BETWEEN 10 AND 19 THEN 'ภาคกลาง'
                WHEN p.province_code BETWEEN 20 AND 27 THEN 'ภาคตะวันออก'
                WHEN p.province_code BETWEEN 30 AND 49 THEN 'ภาคตะวันออกเฉียงเหนือ'
                WHEN p.province_code BETWEEN 50 AND 58 THEN 'ภาคเหนือ'
                WHEN p.province_code BETWEEN 60 AND 61 THEN 'ภาคกลาง'
                WHEN p.province_code BETWEEN 62 AND 67 THEN 'ภาคเหนือ'
                WHEN p.province_code IN (70, 71, 76, 77) THEN 'ภาคตะวันตก'
                WHEN p.province_code BETWEEN 72 AND 75 THEN 'ภาคกลาง'
                WHEN p.province_code BETWEEN 80 AND 96 THEN 'ภาคใต้'
                ELSE 'ไม่ระบุ'
            END                                          AS region_th,
            pop.population,
            p.province_name_th IN ({stations})            AS has_air_data
        FROM provinces p
        LEFT JOIN pop  USING (province_code)
        LEFT JOIN area USING (province_code);
    """)


def build_dim_station(con):
    """DIM_STATION — 8 สถานีที่เลือก พร้อมประเภทแหล่งกำเนิดมลพิษ"""
    con.execute(f"""
        CREATE OR REPLACE TABLE DIM_STATION AS
        WITH base AS (
            SELECT
                CAST(location_id AS INTEGER) AS location_id,
                station_name,
                locality,
                lat, lon
            FROM stg_stations
            WHERE CAST(location_id AS INTEGER) IN
                  ({', '.join(str(k) for k in STATION_SOURCE_TYPE)})
        ),
        enriched AS (
            SELECT
                b.*,
                {sql_map(STATION_SOURCE_TYPE)} AS pollution_source_type,
                {sql_map(STATION_PROVINCE)}    AS province_name_th,
                (SELECT AVG(elevation_m) FROM stg_weather_daily w
                  WHERE w.location_id = b.location_id) AS elevation_m
            FROM base b
        )
        SELECT
            ROW_NUMBER() OVER (ORDER BY e.location_id) AS station_key,
            e.location_id,
            e.station_name,
            e.locality,
            p.province_key,
            e.province_name_th,
            e.lat, e.lon, e.elevation_m,
            e.pollution_source_type,
            -- จับคู่กับสถานี Air4Thai ที่ใกล้ที่สุดภายในรัศมี ~0.05 องศา (~5 กม.)
            (SELECT a.air4thai_station_id FROM stg_air4thai_stations a
              WHERE abs(a.lat - e.lat) < 0.05 AND abs(a.lon - e.lon) < 0.05
              ORDER BY (a.lat - e.lat) * (a.lat - e.lat)
                     + (a.lon - e.lon) * (a.lon - e.lon)
              LIMIT 1)                                 AS air4thai_station_id
        FROM enriched e
        LEFT JOIN DIM_PROVINCE p ON p.province_name_th = e.province_name_th;
    """)


def build_dim_hospital(con):
    """DIM_HOSPITAL — SCD Type 1: areacode เปลี่ยนข้ามปี ใช้ค่าจากปีล่าสุด"""
    con.execute("""
        CREATE OR REPLACE TABLE DIM_HOSPITAL AS
        WITH latest AS (
            -- 271 hospcodes มี areacode หลายค่า → เลือกค่าจากปีล่าสุด (SCD Type 1)
            SELECT hospcode, areacode, areacode_is_valid, province_code, district_code,
                   ROW_NUMBER() OVER (PARTITION BY hospcode
                                      ORDER BY year_ce DESC, month_no DESC) AS rn
            FROM stg_disease_monthly
        )
        SELECT
            ROW_NUMBER() OVER (ORDER BY l.hospcode) AS hospital_key,
            l.hospcode,
            l.areacode,
            l.areacode_is_valid,
            p.province_key,
            l.district_code,
            a.district_name_th,
            a.district_name_en
        FROM latest l
        JOIN DIM_PROVINCE p USING (province_code)
        LEFT JOIN stg_area a
               ON a.province_code = l.province_code
              AND a.district_code = LPAD(CAST(l.district_code AS VARCHAR), 2, '0')
        WHERE l.rn = 1;
    """)


def build_dim_disease_group(con):
    """DIM_DISEASE_GROUP — เก็บคอลัมน์ confidence ไว้แสดงความโปร่งใสของ mapping"""
    con.execute("""
        CREATE OR REPLACE TABLE DIM_DISEASE_GROUP AS
        WITH used AS (
            -- เอาเฉพาะกลุ่มโรคที่มีอยู่จริงใน fact (กลุ่ม 5 ถูกตัดไปแล้วตอน load)
            SELECT DISTINCT disease_group_id, disease_sub_group_id
            FROM stg_disease_monthly
        )
        SELECT
            ROW_NUMBER() OVER (ORDER BY u.disease_group_id,
                                        u.disease_sub_group_id) AS disease_key,
            u.disease_group_id,
            u.disease_sub_group_id,
            m.disease_name_en,
            m.disease_group_name_th,
            m.related_icd10_example,
            m.confidence,
            u.disease_group_id = 1 AS is_respiratory
        FROM used u
        LEFT JOIN stg_disease_map m
               ON m.disease_group_id     = u.disease_group_id
              AND m.disease_sub_group_id = u.disease_sub_group_id;
    """)


def build_dim_weather(con):
    """DIM_WEATHER — จัด bin สภาพอากาศเป็นกลุ่มที่สื่อความหมายกับผู้ใช้"""
    con.execute("""
        CREATE OR REPLACE TABLE DIM_WEATHER AS
        WITH banded AS (
            SELECT DISTINCT
                CASE WHEN temp_mean     < 25 THEN 'เย็น (<25°C)'
                     WHEN temp_mean     < 30 THEN 'ปกติ (25-30°C)'
                     ELSE 'ร้อน (>30°C)'          END AS temp_band,
                CASE WHEN humidity_mean < 60 THEN 'แห้ง (<60%)'
                     WHEN humidity_mean < 75 THEN 'ปกติ (60-75%)'
                     ELSE 'ชื้น (>75%)'            END AS humidity_band,
                CASE WHEN wind_mean     < 10 THEN 'ลมสงบ (<10 km/h)'
                     WHEN wind_mean     < 20 THEN 'ลมปกติ (10-20 km/h)'
                     ELSE 'ลมแรง (>20 km/h)'       END AS wind_band,
                precipitation > 0                      AS has_rain
            FROM stg_weather_daily
        )
        SELECT
            ROW_NUMBER() OVER (ORDER BY temp_band, humidity_band,
                                        wind_band, has_rain) AS weather_key,
            temp_band, humidity_band, wind_band, has_rain
        FROM banded;
    """)




def main():
    con = duckdb.connect(str(DW_PATH))
    con.execute(f"SET TimeZone = '{LOCAL_TZ}';")

    steps = [
        ("DIM_DATE", build_dim_date),
        ("DIM_PROVINCE", build_dim_province),
        ("DIM_STATION", build_dim_station),
        ("DIM_HOSPITAL", build_dim_hospital),
        ("DIM_DISEASE_GROUP", build_dim_disease_group),
        ("DIM_WEATHER", build_dim_weather),
    ]

    print("=== TRANSFORM: สร้าง Dimension Tables ===")
    for name, fn in steps:
        fn(con)
        n = con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        print(f"  {name:<28} {n:>12,} แถว")

    con.close()
    print(f"\nบันทึกที่ {DW_PATH}")


if __name__ == "__main__":
    main()
