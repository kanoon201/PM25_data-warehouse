"""
clean_weather.py — นำข้อมูลสภาพอากาศรายวัน (Open-Meteo API) เข้า staging

ใช้งาน:
    python 02_ETL/02_clean/clean_weather.py

ข้อมูลนี้มี measure_date + location_id ตรงกับ stg_pm25_daily อยู่แล้ว จึง join ได้ทันที
ใช้ตอบ BQ5 (ปัจจัยอากาศที่ทำให้ฝุ่นรุนแรง) และใช้สร้าง DIM_WEATHER

ผลลัพธ์ใน dw.duckdb:
    stg_weather_daily — สถานี × วัน
"""
import duckdb

# ให้ import config.py จากโฟลเดอร์แม่ (02_ETL) ได้ แม้สคริปต์จะอยู่ในโฟลเดอร์ย่อย
import sys
from pathlib import Path as _Path
sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

from config import DW_PATH, WEATHER_FILE, YEARS, LOCAL_TZ


def main():
    if not WEATHER_FILE.exists():
        raise SystemExit(
            f"ไม่พบไฟล์ {WEATHER_FILE}\n"
            "→ รัน python 02_ETL/01_extract/download_weather.py ก่อน"
        )

    con = duckdb.connect(str(DW_PATH))
    con.execute(f"SET TimeZone = '{LOCAL_TZ}';")

    con.execute(f"""
        CREATE OR REPLACE TABLE stg_weather_daily AS
        SELECT
            location_id,
            CAST(measure_date AS DATE)   AS measure_date,
            station_name,
            elevation_m,
            temperature_2m_mean          AS temp_mean,
            temperature_2m_max           AS temp_max,
            temperature_2m_min           AS temp_min,
            relative_humidity_2m_mean    AS humidity_mean,
            wind_speed_10m_max           AS wind_max,
            wind_speed_10m_mean          AS wind_mean,
            wind_direction_10m_dominant  AS wind_direction,
            precipitation_sum            AS precipitation,
            precipitation_hours,
            surface_pressure_mean        AS pressure,
            cloud_cover_mean             AS cloud_cover,
            shortwave_radiation_sum      AS radiation
        FROM read_csv_auto('{WEATHER_FILE}')
        WHERE EXTRACT(year FROM CAST(measure_date AS DATE))
              BETWEEN {min(YEARS)} AND {max(YEARS)};
    """)

    n = con.execute("SELECT COUNT(*) FROM stg_weather_daily").fetchone()[0]
    print(f"สร้าง stg_weather_daily: {n:,} แถว (สถานี × วัน) "
          f"ช่วงปี {min(YEARS)}-{max(YEARS)}")

    print("\n=== ตรวจความครบถ้วนและความสมเหตุสมผล ===")
    print(con.execute("""
        SELECT
            COUNT(DISTINCT location_id)              AS stations,
            MIN(measure_date)                        AS first_date,
            MAX(measure_date)                        AS last_date,
            COUNT(*) FILTER (WHERE temp_mean IS NULL)     AS null_temp,
            COUNT(*) FILTER (WHERE humidity_mean IS NULL) AS null_humidity,
            ROUND(AVG(temp_mean), 1)                 AS avg_temp,
            ROUND(AVG(humidity_mean), 1)             AS avg_humidity
        FROM stg_weather_daily;
    """).df().to_string(index=False))

    # อุณหภูมิเฉลี่ยของไทยควรอยู่ราว 25-30°C ถ้าหลุดช่วงนี้แปลว่าหน่วยผิด
    avg_t = con.execute("SELECT AVG(temp_mean) FROM stg_weather_daily").fetchone()[0]
    if not (20 <= avg_t <= 35):
        print(f"\n[เตือน] อุณหภูมิเฉลี่ย {avg_t:.1f}°C อยู่นอกช่วงที่คาด (20-35) "
              "ตรวจสอบหน่วยวัด")

    con.close()
    print(f"\nบันทึกที่ {DW_PATH}")


if __name__ == "__main__":
    main()
