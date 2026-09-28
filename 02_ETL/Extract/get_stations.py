import os, requests, pandas as pd
from dotenv import load_dotenv

# ให้ import config.py จากโฟลเดอร์แม่ (02_ETL) ได้ แม้สคริปต์จะอยู่ในโฟลเดอร์ย่อย
import sys
from pathlib import Path as _Path
sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

from config import ROOT, RAW_DIR

load_dotenv(ROOT / ".env")
API_KEY = os.getenv("OPENAQ_API_KEY")
if not API_KEY:
    raise RuntimeError("ไม่พบ OPENAQ_API_KEY — ตรวจสอบไฟล์ .env ที่ root ของโปรเจกต์")

r = requests.get(
    "https://api.openaq.org/v3/locations",
    params={"iso": "TH", "parameters_id": 2, "limit": 1000},
    headers={"X-API-Key": API_KEY},
    timeout=60,
)
r.raise_for_status()

df = pd.json_normalize(r.json()["results"])
df = df[["id", "name", "locality",
         "coordinates.latitude", "coordinates.longitude",
         "datetimeFirst.local", "datetimeLast.local"]]
df.columns = ["location_id", "station_name", "locality",
              "lat", "lon", "first_data", "last_data"]
df["first_year"] = pd.to_datetime(df["first_data"], utc=True,
                                  errors="coerce").dt.year

RAW_DIR.mkdir(parents=True, exist_ok=True)
out_path = RAW_DIR / "th_stations_all.csv"
df.to_csv(out_path, index=False)

print(f"พบ {len(df)} สถานีในไทย → บันทึกที่ {out_path}")
print(df.sort_values("first_year").head(20).to_string())