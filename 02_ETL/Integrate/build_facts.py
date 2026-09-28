"""
build_facts.py — ขั้น INTEGRATE: เชื่อมข้อมูล 5 แหล่งเข้าด้วยกันเป็น Fact Tables

ใช้งาน:
    python 02_ETL/04_integrate/build_facts.py
    (ต้องรัน 03_transform/build_dimensions.py ก่อน)

ขั้นตอนนี้คือ "Integrate" ตามกระบวนการ Extract → Clean → Transform → Integrate → Load
เป็นจุดที่ข้อมูลจากคนละแหล่งมาบรรจบกันจริง โดยแทน Natural Key ของแต่ละระบบต้นทาง
ด้วย Surrogate Key ของ warehouse

    FACT_AIR_QUALITY_DAILY  ← OpenAQ (ฝุ่น) + Open-Meteo (อากาศ) + OpenAQ API (สถานี)
    FACT_DISEASE_MONTHLY    ← HDC (ผู้ป่วย) + dim_area (พื้นที่) + BORA (ประชากรผ่าน DIM_PROVINCE)

DIM_DATE และ DIM_PROVINCE เป็น conformed dimension ที่ fact ทั้งสองใช้ร่วมกัน
จึงเป็นสะพานเดียวที่ทำให้เทียบข้อมูลฝุ่นกับผู้ป่วยได้

ผลลัพธ์: FACT_AIR_QUALITY_DAILY, FACT_DISEASE_MONTHLY
"""
import duckdb

# ให้ import config.py จากโฟลเดอร์แม่ (02_ETL) ได้ แม้สคริปต์จะอยู่ในโฟลเดอร์ย่อย
import sys
from pathlib import Path as _Path
sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

from config import DW_PATH, LOCAL_TZ


def build_fact_air_quality(con):
    """FACT_AIR_QUALITY_DAILY — grain: 1 สถานี × 1 วัน"""
    con.execute("""
        CREATE OR REPLACE TABLE FACT_AIR_QUALITY_DAILY AS
        WITH w AS (
            SELECT
                location_id, measure_date,
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
            ROW_NUMBER() OVER (ORDER BY d.location_id, d.measure_date) AS air_quality_key,
            CAST(strftime(d.measure_date, '%Y%m%d') AS INTEGER) AS date_key,
            s.station_key,
            s.province_key,
            dw.weather_key,
            d.avg_pm25, d.max_pm25, d.min_pm25,
            d.n_readings, d.coverage_ratio,
            d.is_exceedance_th, d.is_exceedance_who
        FROM stg_pm25_daily d
        JOIN DIM_STATION s USING (location_id)
        LEFT JOIN w ON w.location_id = d.location_id
                   AND w.measure_date = d.measure_date
        LEFT JOIN DIM_WEATHER dw
               ON dw.temp_band     = w.temp_band
              AND dw.humidity_band = w.humidity_band
              AND dw.wind_band     = w.wind_band
              AND dw.has_rain      = w.has_rain;
    """)


def build_fact_disease(con):
    """FACT_DISEASE_MONTHLY — grain: 1 รพ. × 1 เดือน × 1 กลุ่มโรคย่อย"""
    con.execute("""
        CREATE OR REPLACE TABLE FACT_DISEASE_MONTHLY AS
        SELECT
            ROW_NUMBER() OVER (ORDER BY f.hospcode, f.month_key,
                                        f.disease_group_id,
                                        f.disease_sub_group_id) AS disease_fact_key,
            -- fact รายเดือนชี้ไปที่วันที่ 1 ของเดือนใน DIM_DATE (conformed)
            CAST(strftime(f.month_date, '%Y%m%d') AS INTEGER) AS date_key,
            f.month_key,
            h.hospital_key,
            p.province_key,
            dg.disease_key,
            f.visit_count
        FROM stg_disease_monthly f
        JOIN DIM_HOSPITAL      h  ON h.hospcode = f.hospcode
        JOIN DIM_PROVINCE      p  ON p.province_code = f.province_code
        JOIN DIM_DISEASE_GROUP dg ON dg.disease_group_id     = f.disease_group_id
                                 AND dg.disease_sub_group_id = f.disease_sub_group_id;
    """)




def main():
    con = duckdb.connect(str(DW_PATH))
    con.execute(f"SET TimeZone = '{LOCAL_TZ}';")

    steps = [
        ("FACT_AIR_QUALITY_DAILY", build_fact_air_quality),
        ("FACT_DISEASE_MONTHLY", build_fact_disease),
    ]

    print("=== INTEGRATE: เชื่อมหลายแหล่งเป็น Fact Tables ===")
    for name, fn in steps:
        fn(con)
        n = con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        print(f"  {name:<28} {n:>12,} แถว")

    con.close()
    print(f"\nบันทึกที่ {DW_PATH}")


if __name__ == "__main__":
    main()
