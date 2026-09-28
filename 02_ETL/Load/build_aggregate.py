"""
build_aggregate.py — ขั้น LOAD: สร้างตารางสุดท้ายที่ Dashboard ใช้งาน

ใช้งาน:
    python 02_ETL/05_load/build_aggregate.py
    (ต้องรัน 04_integrate/build_facts.py ก่อน)

ขั้นตอนนี้คือ "Load" ตามกระบวนการ Extract → Clean → Transform → Integrate → Load
คือการโหลดผลลัพธ์สุดท้ายในรูปแบบที่ผู้ใช้ปลายทางเรียกใช้ได้ทันที

AGG_PM25_DISEASE_MONTHLY เป็นตารางเดียวที่ข้อมูลฝุ่นกับผู้ป่วยอยู่แถวเดียวกัน
เพราะ fact ทั้งสองมี grain ต่างกัน (สถานี×วัน กับ โรงพยาบาล×เดือน)
จึงต้องยกฝุ่นขึ้นมาที่ระดับจังหวัด×เดือนก่อนจึงเทียบกันได้

การรวมทำ 2 ขั้น: สถานี×วัน → จังหวัด×วัน → จังหวัด×เดือน
ห้ามข้ามขั้น เพราะจังหวัดที่มีหลายสถานี (กทม. 3 สถานี) จะทำให้นับวันซ้ำ

ผลลัพธ์: AGG_PM25_DISEASE_MONTHLY
"""
import duckdb

# ให้ import config.py จากโฟลเดอร์แม่ (02_ETL) ได้ แม้สคริปต์จะอยู่ในโฟลเดอร์ย่อย
import sys
from pathlib import Path as _Path
sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

from config import DW_PATH, LOCAL_TZ, THAI_STANDARD_PM25, WHO_GUIDELINE_PM25


def build_aggregate(con):
    """AGG_PM25_DISEASE_MONTHLY — ตารางที่ Dashboard ใช้ตอบ BQ1, BQ3, BQ4, BQ7"""
    con.execute(f"""
        CREATE OR REPLACE TABLE AGG_PM25_DISEASE_MONTHLY AS
        WITH prov_day AS (
            -- ขั้นที่ 1: ยุบหลายสถานีในจังหวัดเดียวกันให้เหลือ 1 ค่าต่อ 1 วัน
            -- จำเป็นเพราะ กทม. มี 3 สถานี สมุทรสาคร 2 สถานี ถ้าข้ามขั้นนี้
            -- COUNT(*) จะนับ station-day ทำให้ "จำนวนวัน" เกินจำนวนวันจริงในเดือน
            SELECT
                f.province_key,
                f.date_key,
                AVG(f.avg_pm25)                  AS day_pm25,
                MAX(f.max_pm25)                  AS day_max_pm25,
                COUNT(DISTINCT f.station_key)    AS n_stations
            FROM FACT_AIR_QUALITY_DAILY f
            GROUP BY 1, 2
        ),
        pm AS (
            -- ขั้นที่ 2: รวมระดับจังหวัด-วัน ขึ้นเป็นจังหวัด-เดือน
            -- exceedance นับจากค่าเฉลี่ยของ "ทั้งจังหวัด" ในวันนั้น ไม่ใช่ผลบวกรายสถานี
            SELECT
                pd.province_key,
                d.month_key,
                d.full_date - INTERVAL (d.day - 1) DAY AS month_date,
                ROUND(AVG(pd.day_pm25), 2)      AS avg_pm25,
                ROUND(MAX(pd.day_max_pm25), 2)  AS max_pm25,
                COUNT(*) FILTER (WHERE pd.day_pm25 > {THAI_STANDARD_PM25}) AS exceedance_days_th,
                COUNT(*) FILTER (WHERE pd.day_pm25 > {WHO_GUIDELINE_PM25}) AS exceedance_days_who,
                COUNT(*)                        AS days_with_data,
                ROUND(AVG(pd.n_stations), 1)    AS avg_stations_per_day
            FROM prov_day pd
            JOIN DIM_DATE d USING (date_key)
            GROUP BY 1, 2, 3
        ),
        dis AS (
            SELECT province_key, month_key, disease_key,
                   SUM(visit_count) AS visit_count
            FROM FACT_DISEASE_MONTHLY
            GROUP BY 1, 2, 3
        )
        SELECT
            dis.month_key,
            dis.province_key,
            dis.disease_key,
            dis.visit_count,
            CASE WHEN p.population > 0
                 THEN ROUND(dis.visit_count * 100000.0 / p.population, 2)
            END                                     AS visits_per_100k,
            pm.avg_pm25,
            pm.max_pm25,
            pm.exceedance_days_th,
            pm.exceedance_days_who,
            pm.days_with_data,
            pm.avg_stations_per_day,
            lag1.avg_pm25                           AS avg_pm25_lag1,
            lag2.avg_pm25                           AS avg_pm25_lag2
        FROM dis
        JOIN DIM_PROVINCE p USING (province_key)
        LEFT JOIN pm   ON pm.province_key   = dis.province_key
                      AND pm.month_key      = dis.month_key
        -- lag คำนวณด้วยวันที่จริง ไม่ใช่ month_key - 1 (จะพังตอนข้ามปี 202201 → 202200)
        LEFT JOIN pm lag1 ON lag1.province_key = dis.province_key
                         AND lag1.month_date   = pm.month_date - INTERVAL 1 MONTH
        LEFT JOIN pm lag2 ON lag2.province_key = dis.province_key
                         AND lag2.month_date   = pm.month_date - INTERVAL 2 MONTH
        WHERE p.has_air_data;   -- ตารางนี้ใช้เฉพาะจังหวัดที่มีทั้งฝุ่นและผู้ป่วย
    """)




def main():
    con = duckdb.connect(str(DW_PATH))
    con.execute(f"SET TimeZone = '{LOCAL_TZ}';")

    steps = [
        ("AGG_PM25_DISEASE_MONTHLY", build_aggregate),
    ]

    print("=== LOAD: สร้าง Aggregate Table สำหรับ Dashboard ===")
    for name, fn in steps:
        fn(con)
        n = con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        print(f"  {name:<28} {n:>12,} แถว")

    con.close()
    print(f"\nบันทึกที่ {DW_PATH}")


if __name__ == "__main__":
    main()
