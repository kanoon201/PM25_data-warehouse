"""
clean_openaq.py — รวมไฟล์ .csv.gz ของสถานีที่เลือกไว้เข้า DuckDB + ทำความสะอาด + aggregate

ใช้งาน:
    python 02_ETL/02_clean/clean_openaq.py

โหลดเฉพาะสถานีที่ระบุใน config.SELECTED_STATIONS เท่านั้น ไม่ใช่ทุกไฟล์ที่มีในโฟลเดอร์
เพื่อให้ config.py เป็นแหล่งความจริงเพียงแหล่งเดียว — ถ้าตัดสถานีออกจาก config แล้ว
โหลดใหม่ ข้อมูลของสถานีนั้นจะหายจาก warehouse จริง ๆ ไม่ค้างอยู่จากไฟล์เก่า
การกรองด้วยคอลัมน์ partition (locationid) ยังช่วยให้ DuckDB ข้ามโฟลเดอร์ที่ไม่เกี่ยวได้เลย

ผลลัพธ์ใน 03_Data_Warehouse/dw.duckdb:
    stg_measurements  — ข้อมูลดิบทุกแถวของสถานีที่เลือก
    stg_pm25_daily    — PM2.5 รายวัน × สถานี (พร้อมใช้ต่อใน Star Schema)
    stg_pm25_balanced — เฉพาะสถานีที่มีข้อมูลครบทุกปี (ใช้เทียบข้ามปี)
    stg_stations      — ข้อมูลอ้างอิงสถานีทั่วประเทศจาก OpenAQ API
"""
import pandas as pd
import duckdb

# ให้ import config.py จากโฟลเดอร์แม่ (02_ETL) ได้ แม้สคริปต์จะอยู่ในโฟลเดอร์ย่อย
import sys
from pathlib import Path as _Path
sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

from config import (
    MEAS_DIR, DW_DIR, DW_PATH, RAW_DIR, STATIONS_FILE,
    PM25_MIN, PM25_MAX, MIN_READINGS_PER_DAY,
    THAI_STANDARD_PM25, WHO_GUIDELINE_PM25,
    LOCAL_TZ, YEARS, SELECTED_STATIONS,
)

# datetime เป็น TIMESTAMPTZ อยู่แล้ว → แปลงโซนเวลาแล้วค่อยตัดเป็นวันที่
# ห้ามบวก INTERVAL 7 HOUR เพิ่ม จะกลายเป็นเลื่อนซ้ำ ทำให้ค่าช่วง 17:00-23:59
# ถูกนับไปอยู่วันถัดไป
LOCAL_DATE = f"CAST(datetime AT TIME ZONE '{LOCAL_TZ}' AS DATE)"


def main():
    # ---------- 0) ตรวจความสอดคล้องระหว่าง config กับไฟล์ที่มีจริง ----------
    # ทำก่อนโหลด เพื่อไม่ให้ได้ warehouse ที่ขาดสถานีไปเงียบ ๆ
    selected = sorted(SELECTED_STATIONS)
    on_disk = {
        int(p.name.split("=")[1])
        for p in MEAS_DIR.glob("locationid=*") if p.is_dir()
    }
    missing = [s for s in selected if s not in on_disk]
    orphan = sorted(on_disk - set(selected))

    files = sum(1 for s in selected
                for _ in (MEAS_DIR / f"locationid={s}").rglob("*.csv.gz"))
    if not files:
        raise SystemExit(
            f"ไม่พบไฟล์ .csv.gz ของสถานีที่เลือกใน {MEAS_DIR}\n"
            "→ รัน python 02_ETL/01_extract/download_openaq.py ก่อน"
        )
    print(f"สถานีใน config: {len(selected)}  |  ไฟล์ดิบของสถานีเหล่านั้น: {files:,} ไฟล์")

    if missing:
        print(f"\n[เตือน] {len(missing)} สถานีใน config ยังไม่มีไฟล์ดิบ "
              f"— จะไม่ปรากฏใน warehouse")
        print(f"        {missing}")
        print("        → รัน download_openaq.py เพื่อโหลดให้ครบ")
    if orphan:
        print(f"\n[ข้าม] พบไฟล์ของอีก {len(orphan)} สถานีที่ไม่ได้อยู่ใน config "
              f"— จะไม่ถูกโหลด")
        print(f"       {orphan[:10]}{' ...' if len(orphan) > 10 else ''}")

    DW_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DW_PATH))
    # ตรึงโซนเวลาของ session ไม่ให้ผลลัพธ์เปลี่ยนตามเครื่องที่รัน
    con.execute(f"SET TimeZone = '{LOCAL_TZ}';")

    # ---------- 1) EXTRACT: อ่านเฉพาะสถานีที่เลือก ----------
    # hive_partitioning ดึง locationid / year / month จากชื่อโฟลเดอร์มาเป็นคอลัมน์
    # union_by_name จำเป็นเพราะ OpenAQ เคยเปลี่ยนโครงสร้างคอลัมน์ระหว่างปี
    # กรองด้วย locationid (คอลัมน์ partition) ไม่ใช่ location_id เพราะ DuckDB
    # ตัดโฟลเดอร์ที่ไม่เข้าเงื่อนไขทิ้งได้ก่อนเปิดอ่านไฟล์ — เร็วกว่ามากเมื่อมี 80,000+ ไฟล์
    id_list = ", ".join(str(s) for s in selected)
    con.execute(f"""
        CREATE OR REPLACE TABLE stg_measurements AS
        SELECT * FROM read_csv_auto(
            '{MEAS_DIR}/**/*.csv.gz',
            hive_partitioning = true,
            union_by_name     = true,
            ignore_errors     = true
        )
        WHERE locationid IN ({id_list});
    """)
    n_raw = con.execute("SELECT COUNT(*) FROM stg_measurements").fetchone()[0]
    print(f"โหลดเข้า stg_measurements: {n_raw:,} แถว\n")
    print("คอลัมน์ที่ได้:")
    print(con.execute("DESCRIBE stg_measurements").df().to_string(index=False))

    # ---------- 2) ตรวจคุณภาพก่อนทำความสะอาด (ใส่ในรายงานได้) ----------
    print("\n=== ปัญหาคุณภาพข้อมูลที่ตรวจพบ ===")
    dq = con.execute(f"""
        SELECT
            COUNT(*)                                             AS total_rows,
            COUNT(*) FILTER (WHERE value IS NULL)                AS null_values,
            COUNT(*) FILTER (WHERE value < {PM25_MIN})           AS negative_values,
            COUNT(*) FILTER (WHERE value > {PM25_MAX})           AS impossible_values,
            COUNT(*) FILTER (WHERE parameter = 'pm25')           AS pm25_rows,
            COUNT(*) FILTER (WHERE parameter = 'pm25' AND value = 0) AS pm25_zero_values
        FROM stg_measurements;
    """).df()
    print(dq.to_string(index=False))

    # ช่วงเวลาจริงของแต่ละพารามิเตอร์ — pm25 เริ่มช้ากว่า pm10 หลายปี
    print("\nช่วงเวลาที่มีข้อมูลจริงของแต่ละพารามิเตอร์:")
    print(con.execute(f"""
        SELECT parameter,
               any_value(units)              AS units,
               MIN({LOCAL_DATE})             AS first_date,
               MAX({LOCAL_DATE})             AS last_date,
               COUNT(*)                      AS rows
        FROM stg_measurements GROUP BY 1 ORDER BY 1;
    """).df().to_string(index=False))

    dup = con.execute("""
        SELECT COUNT(*) AS duplicate_rows FROM (
            SELECT location_id, datetime, parameter, COUNT(*) AS c
            FROM stg_measurements
            GROUP BY 1,2,3 HAVING COUNT(*) > 1
        );
    """).fetchone()[0]
    print(f"แถวซ้ำ (สถานี+เวลา+พารามิเตอร์เดียวกัน): {dup:,}")

    # ---------- 3) CLEAN + TRANSFORM: aggregate เป็นรายวัน ----------
    # ลำดับ: กรองช่วงค่า → แปลงเป็นวันที่ท้องถิ่น → กรองความครบของชั่วโมง → ตัดช่วงปี
    con.execute(f"""
        CREATE OR REPLACE TABLE stg_pm25_daily AS
        SELECT
            location_id,
            {LOCAL_DATE}                  AS measure_date,
            ROUND(AVG(value), 2)          AS avg_pm25,
            ROUND(MAX(value), 2)          AS max_pm25,
            ROUND(MIN(value), 2)          AS min_pm25,
            COUNT(*)                      AS n_readings,
            ROUND(COUNT(*) / 24.0, 3)     AS coverage_ratio,
            CASE WHEN AVG(value) > {THAI_STANDARD_PM25} THEN 1 ELSE 0 END AS is_exceedance_th,
            CASE WHEN AVG(value) > {WHO_GUIDELINE_PM25} THEN 1 ELSE 0 END AS is_exceedance_who
        FROM stg_measurements
        WHERE parameter = 'pm25'
          AND value IS NOT NULL
          AND value BETWEEN {PM25_MIN} AND {PM25_MAX}
        GROUP BY 1, 2
        HAVING COUNT(*) >= {MIN_READINGS_PER_DAY}
           AND EXTRACT(year FROM {LOCAL_DATE}) BETWEEN {min(YEARS)} AND {max(YEARS)};
    """)
    n_daily = con.execute("SELECT COUNT(*) FROM stg_pm25_daily").fetchone()[0]
    print(f"\nสร้าง stg_pm25_daily: {n_daily:,} แถว (สถานี × วัน) "
          f"ช่วงปี {min(YEARS)}-{max(YEARS)}")

    # วัน-สถานีที่ถูกตัดทิ้งเพราะชั่วโมงไม่ครบ — ต้องรายงานไว้ ไม่ใช่ซ่อน
    print("\n=== ความครบถ้วนของข้อมูล (ก่อน/หลังกรองชั่วโมง) ===")
    print(con.execute(f"""
        WITH raw_days AS (
            SELECT location_id, {LOCAL_DATE} AS d, COUNT(*) AS n
            FROM stg_measurements
            WHERE parameter = 'pm25' AND value IS NOT NULL
              AND value BETWEEN {PM25_MIN} AND {PM25_MAX}
              AND EXTRACT(year FROM {LOCAL_DATE}) BETWEEN {min(YEARS)} AND {max(YEARS)}
            GROUP BY 1, 2
        )
        SELECT location_id,
               COUNT(*)                                        AS days_with_any_data,
               COUNT(*) FILTER (WHERE n >= {MIN_READINGS_PER_DAY}) AS days_kept,
               COUNT(*) FILTER (WHERE n <  {MIN_READINGS_PER_DAY}) AS days_dropped,
               DATE_DIFF('day', MIN(d), MAX(d)) + 1             AS calendar_days,
               ROUND(100.0 * COUNT(*) FILTER (WHERE n >= {MIN_READINGS_PER_DAY})
                     / (DATE_DIFF('day', MIN(d), MAX(d)) + 1), 1) AS pct_of_calendar
        FROM raw_days GROUP BY 1 ORDER BY 1;
    """).df().to_string(index=False))

    # ---------- 4) เฉพาะสถานีที่มีข้อมูลครบทุกปี ----------
    con.execute(f"""
        CREATE OR REPLACE TABLE stg_pm25_balanced AS
        WITH complete AS (
            SELECT location_id
            FROM stg_pm25_daily
            GROUP BY location_id
            HAVING COUNT(DISTINCT EXTRACT(year FROM measure_date)) = {len(YEARS)}
        )
        SELECT d.* FROM stg_pm25_daily d JOIN complete c USING (location_id);
    """)
    n_bal = con.execute("SELECT COUNT(*) FROM stg_pm25_balanced").fetchone()[0]
    n_sta = con.execute(
        "SELECT COUNT(DISTINCT location_id) FROM stg_pm25_balanced").fetchone()[0]
    print(f"\nสร้าง stg_pm25_balanced: {n_bal:,} แถว จาก {n_sta} สถานีที่ข้อมูลครบทุกปี")
    if n_bal == 0:
        print("[เตือน] stg_pm25_balanced ว่างเปล่า — ตรวจว่า YEARS ใน config.py "
              "ตรงกับช่วงที่มีข้อมูล pm25 จริงหรือไม่")

    # ---------- 5) VALIDATE หลัง Load ----------
    print("\n=== สรุปรายปี (ใช้ตรวจความสมเหตุสมผล) ===")
    summary = con.execute(f"""
        SELECT
            EXTRACT(year FROM measure_date)   AS yr,
            COUNT(DISTINCT location_id)       AS stations,
            COUNT(*)                          AS station_days,
            ROUND(AVG(avg_pm25), 1)           AS mean_pm25,
            ROUND(MAX(max_pm25), 1)           AS peak_pm25,
            SUM(is_exceedance_th)             AS exceed_days_th
        FROM stg_pm25_daily
        GROUP BY 1 ORDER BY 1;
    """).df()
    print(summary.to_string(index=False))
    summary.to_csv(RAW_DIR / "validation_yearly_summary.csv", index=False)

    print("\n=== ค่าเฉลี่ยรายเดือน (ควรเห็นพีคช่วง ม.ค.-มี.ค.) ===")
    print(con.execute("""
        SELECT EXTRACT(month FROM measure_date) AS mth,
               ROUND(AVG(avg_pm25), 1) AS mean_pm25
        FROM stg_pm25_daily GROUP BY 1 ORDER BY 1;
    """).df().to_string(index=False))

    # เตือนถ้าค่าผิดปกติ
    overall = con.execute(
        "SELECT AVG(avg_pm25) FROM stg_pm25_daily").fetchone()[0]
    if not (10 <= overall <= 60):
        print(f"\n[เตือน] ค่าเฉลี่ยรวม {overall:.1f} µg/m³ อยู่นอกช่วงที่คาด (10-60) "
              "ตรวจสอบหน่วยวัดและการ aggregate")

    # ---------- 6) ข้อมูลอ้างอิงสถานี (มาจาก OpenAQ API แหล่งเดียวกัน) ----------
    # โหลดเข้า staging เพื่อให้ 03_transform/ อ่านจาก warehouse อย่างเดียว
    # ไม่ต้องผูกกับ path ของไฟล์ดิบ
    con.execute(f"""
        CREATE OR REPLACE TABLE stg_stations AS
        SELECT
            CAST(location_id AS INTEGER) AS location_id,
            station_name,
            locality,
            CAST(lat AS DOUBLE)          AS lat,
            CAST(lon AS DOUBLE)          AS lon,
            CAST(first_data AS TIMESTAMP WITH TIME ZONE) AS first_data,
            CAST(last_data  AS TIMESTAMP WITH TIME ZONE) AS last_data
        FROM read_csv_auto('{STATIONS_FILE}');
    """)
    n_st = con.execute("SELECT COUNT(*) FROM stg_stations").fetchone()[0]
    n_sel = con.execute(f"""
        SELECT COUNT(*) FROM stg_stations
        WHERE location_id IN ({id_list});
    """).fetchone()[0]
    print(f"\nสร้าง stg_stations: {n_st:,} สถานีทั่วประเทศ "
          f"(อยู่ใน config {n_sel} จาก {len(selected)})")
    if n_sel < len(selected):
        print(f"[เตือน] {len(selected) - n_sel} สถานีใน config ไม่มีใน "
              f"{STATIONS_FILE.name} → DIM_STATION จะขาดสถานีเหล่านั้น")

    con.close()
    print(f"\nบันทึกที่ {DW_PATH}")


if __name__ == "__main__":
    main()