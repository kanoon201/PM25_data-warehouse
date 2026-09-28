"""
clean_air4thai.py — แตกไฟล์ Nested JSON ของ Air4Thai (กรมควบคุมมลพิษ) เข้า staging

ใช้งาน:
    python 02_ETL/02_clean/clean_air4thai.py

ไฟล์ Air4Thai เป็น nested JSON ซ้อน 3 ชั้น:
    stations[] → AQILast{} → PM25{value, aqi, color_id}
สคริปต์นี้แตกออกเป็นตารางแบน เพื่อใช้เสริม DIM_STATION และเป็นหลักฐาน
การใช้ข้อมูลรูปแบบซับซ้อนกว่า CSV ตามข้อกำหนด

ผลลัพธ์ใน dw.duckdb:
    stg_air4thai_stations — รายชื่อสถานีตรวจวัดทั่วประเทศ พร้อมค่าล่าสุด
"""
import json

import duckdb
import pandas as pd

# ให้ import config.py จากโฟลเดอร์แม่ (02_ETL) ได้ แม้สคริปต์จะอยู่ในโฟลเดอร์ย่อย
import sys
from pathlib import Path as _Path
sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

from config import DW_PATH, AIR4THAI_DIR, LOCAL_TZ


def flatten_station(st, region):
    """แตก nested dict ของสถานีหนึ่งให้เป็น dict แบนชั้นเดียว"""
    aqi_last = st.get("AQILast") or {}

    def param(name, field):
        """ดึงค่าจากชั้นที่ 3 เช่น AQILast.PM25.value — ไม่มีก็คืน None"""
        node = aqi_last.get(name) or {}
        raw = node.get(field)
        if raw in (None, "", "-1"):    # Air4Thai ใช้ -1 แทน "ไม่มีข้อมูล"
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    return {
        "air4thai_station_id": st.get("stationID"),
        "name_th":     st.get("nameTH"),
        "name_en":     st.get("nameEN"),
        "area_th":     st.get("areaTH"),
        "station_type": st.get("stationType"),
        "region_file": region,
        "lat": pd.to_numeric(st.get("lat"), errors="coerce"),
        "lon": pd.to_numeric(st.get("long"), errors="coerce"),
        "last_date": aqi_last.get("date"),
        "last_time": aqi_last.get("time"),
        "pm25_value": param("PM25", "value"),
        "pm25_aqi":   param("PM25", "aqi"),
        "pm10_value": param("PM10", "value"),
        "aqi_overall": param("AQI", "aqi"),
    }


def main():
    files = sorted(AIR4THAI_DIR.glob("*.json"))
    if not files:
        raise SystemExit(f"ไม่พบไฟล์ .json ใน {AIR4THAI_DIR}")

    rows = []
    for f in files:
        with open(f, encoding="utf-8") as fh:
            data = json.load(fh)
        stations = data.get("stations", [])
        print(f"  {f.name:<45} {len(stations):>4} สถานี")
        rows.extend(flatten_station(st, f.stem) for st in stations)

    df = pd.DataFrame(rows)
    print(f"\nแตก nested JSON ได้ทั้งหมด {len(df):,} แถว จาก {len(files)} ไฟล์")

    # ไฟล์ "ทั่วประเทศ" ซ้อนทับกับไฟล์รายภูมิภาค → ต้อง dedupe ด้วย stationID
    before = len(df)
    df = df.sort_values("region_file").drop_duplicates(
        subset="air4thai_station_id", keep="first").reset_index(drop=True)
    print(f"หลัง dedupe ตาม stationID: {len(df):,} สถานี "
          f"(ตัดซ้ำออก {before - len(df):,} แถว — ไฟล์ 'ทั่วประเทศ' ซ้อนกับไฟล์รายภาค)")

    con = duckdb.connect(str(DW_PATH))
    con.execute(f"SET TimeZone = '{LOCAL_TZ}';")
    con.register("air4thai_df", df)
    con.execute("""
        CREATE OR REPLACE TABLE stg_air4thai_stations AS
        SELECT * FROM air4thai_df;
    """)

    print("\n=== ตรวจคุณภาพ ===")
    print(con.execute("""
        SELECT
            COUNT(*)                                     AS stations,
            COUNT(*) FILTER (WHERE lat IS NULL OR lon IS NULL) AS missing_coords,
            COUNT(*) FILTER (WHERE pm25_value IS NULL)   AS missing_pm25,
            ROUND(AVG(pm25_value), 1)                    AS avg_pm25_latest
        FROM stg_air4thai_stations;
    """).df().to_string(index=False))

    con.close()
    print(f"\nบันทึกที่ {DW_PATH}")


if __name__ == "__main__":
    main()
