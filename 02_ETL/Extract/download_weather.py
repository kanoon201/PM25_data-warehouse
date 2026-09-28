"""
download_weather.py — ดึงข้อมูลสภาพอากาศย้อนหลังจาก Open-Meteo Historical Weather API

ใช้งาน:
    python 02_ETL/download_weather.py --test    # ทดสอบ 1 สถานี 1 เดือน
    python 02_ETL/download_weather.py           # ดึงจริง 2016-2025 ทุกสถานี

คุณสมบัติ:
  - ไม่ต้องใช้ API key
  - เก็บ JSON ดิบไว้ใน 01_Raw_Data ตามข้อกำหนดของโจทย์
  - ข้ามไฟล์ที่ดึงแล้ว → รันซ้ำได้
  - ดึงทั้งรายวันและรายชั่วโมง (รายชั่วโมงใช้ join กับ PM2.5 รายชั่วโมงได้)
"""
import sys
import time
import json

import requests
import pandas as pd

# ให้ import config.py จากโฟลเดอร์แม่ (02_ETL) ได้ แม้สคริปต์จะอยู่ในโฟลเดอร์ย่อย
import sys
from pathlib import Path as _Path
sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

from config import RAW_DIR, SELECTED_STATIONS

BASE_URL = "https://archive-api.open-meteo.com/v1/archive"
OUT_DIR = RAW_DIR / "Weather"

START_DATE = "2016-01-01"
END_DATE = "2025-12-31"

# ตัวแปรรายวัน — เลือกเฉพาะที่เกี่ยวกับการสะสม/กระจายตัวของฝุ่น
DAILY_VARS = [
    "temperature_2m_mean",
    "temperature_2m_max",
    "temperature_2m_min",
    "relative_humidity_2m_mean",
    "wind_speed_10m_max",
    "wind_speed_10m_mean",
    "wind_direction_10m_dominant",
    "precipitation_sum",
    "precipitation_hours",
    "surface_pressure_mean",
    "cloud_cover_mean",
    "shortwave_radiation_sum",
]

# ตัวแปรรายชั่วโมง — ใช้เมื่อต้องการ join กับ PM2.5 รายชั่วโมง
HOURLY_VARS = [
    "temperature_2m",
    "relative_humidity_2m",
    "wind_speed_10m",
    "wind_direction_10m",
    "precipitation",
    "surface_pressure",
    "boundary_layer_height",   # ความสูงชั้นผสม — ตัวแปรสำคัญที่สุดต่อการสะสมฝุ่น
]


def fetch_station(lat, lon, location_id, station_name,
                  start, end, mode="daily"):
    """ดึงข้อมูล 1 สถานี — คืน DataFrame"""
    raw_path = OUT_DIR / "raw" / f"weather_{mode}_{location_id}.json"

    if raw_path.exists():
        print(f"    ใช้ไฟล์ที่ดึงไว้แล้ว: {raw_path.name}")
        data = json.loads(raw_path.read_text(encoding="utf-8"))
    else:
        params = {
            "latitude": lat,
            "longitude": lon,
            "start_date": start,
            "end_date": end,
            "timezone": "Asia/Bangkok",   # สำคัญ! ไม่ใส่จะได้ UTC
        }
        if mode == "daily":
            params["daily"] = ",".join(DAILY_VARS)
        else:
            params["hourly"] = ",".join(HOURLY_VARS)

        r = requests.get(BASE_URL, params=params, timeout=300)
        if r.status_code != 200:
            print(f"    [error {r.status_code}] {r.text[:300]}")
            return None

        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_text(r.text, encoding="utf-8")
        data = r.json()

    if mode not in data:
        print(f"    [error] response ไม่มี key '{mode}': {list(data.keys())}")
        return None

    df = pd.DataFrame(data[mode])
    df = df.rename(columns={"time": "measure_date" if mode == "daily" else "measure_time"})
    df["location_id"] = location_id
    df["station_name"] = station_name
    df["elevation_m"] = data.get("elevation")
    return df


def main(test_mode=False, mode="daily"):
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    stations = pd.read_csv(RAW_DIR / "th_stations_all.csv")
    stations = stations[stations["location_id"].isin(SELECTED_STATIONS)]
    if stations.empty:
        raise SystemExit("ไม่พบสถานีที่เลือกใน th_stations_all.csv")

    start, end = (START_DATE, END_DATE)
    if test_mode:
        stations = stations.head(1)
        start, end = "2024-01-01", "2024-01-31"

    frames = []
    for _, s in stations.iterrows():
        loc_id = int(s["location_id"])
        name = str(s["station_name"])
        print(f"[{loc_id}] {name[:40]}")
        print(f"    พิกัด {s['lat']:.4f}, {s['lon']:.4f}")

        df = fetch_station(s["lat"], s["lon"], loc_id, name, start, end, mode)
        if df is None:
            continue

        print(f"    ได้ {len(df):,} แถว")
        frames.append(df)
        time.sleep(1)          # มารยาทต่อ public API

    if not frames:
        raise SystemExit("ดึงข้อมูลไม่ได้เลย")

    out = pd.concat(frames, ignore_index=True)
    suffix = "_test" if test_mode else ""
    path = OUT_DIR / f"weather_{mode}{suffix}.csv"
    out.to_csv(path, index=False)

    print(f"\nรวม {len(out):,} แถว → {path}")
    date_col = "measure_date" if mode == "daily" else "measure_time"
    print(f"ช่วงเวลา: {out[date_col].min()} ถึง {out[date_col].max()}")

    print("\n=== ค่าที่ขาดหาย (Missing Values) ===")
    miss = out.isna().sum()
    miss = miss[miss > 0]
    if len(miss):
        for col, n in miss.items():
            print(f"  {col:<32} {n:>7,} ({n/len(out)*100:.2f}%)")
    else:
        print("  ไม่มีค่าขาดหาย (ERA5 reanalysis เติมเต็มทุกช่วงเวลา)")

    if mode == "daily":
        print("\n=== สถิติเบื้องต้น (ตรวจความสมเหตุสมผล) ===")
        cols = ["temperature_2m_mean", "relative_humidity_2m_mean",
                "wind_speed_10m_max", "precipitation_sum"]
        cols = [c for c in cols if c in out.columns]
        print(out[cols].describe().round(2).to_string())
        print("\nค่าที่ควรได้สำหรับไทย: อุณหภูมิเฉลี่ย 25-30°C | "
              "ความชื้น 60-80% | ฝนรวมทั้งปี 1,000-2,000 mm")


if __name__ == "__main__":
    mode = "hourly" if "--hourly" in sys.argv else "daily"
    main(test_mode="--test" in sys.argv, mode=mode)