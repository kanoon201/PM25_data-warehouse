import boto3, pandas as pd
from botocore import UNSIGNED
from botocore.config import Config

# ให้ import config.py จากโฟลเดอร์แม่ (02_ETL) ได้ แม้สคริปต์จะอยู่ในโฟลเดอร์ย่อย
import sys
from pathlib import Path as _Path
sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

from config import BUCKET, PREFIX, RAW_DIR

s3 = boto3.client("s3", config=Config(signature_version=UNSIGNED))

def available_years(location_id):
    """คืนรายการปีที่สถานีนี้มีข้อมูลบน S3"""
    prefix = f"{PREFIX}/locationid={location_id}/"
    resp = s3.list_objects_v2(Bucket=BUCKET, Prefix=prefix, Delimiter="/")
    years = []
    for p in resp.get("CommonPrefixes", []):
        # p["Prefix"] = "records/csv.gz/locationid=2178/year=2020/"
        years.append(int(p["Prefix"].rstrip("/").split("=")[-1]))
    return sorted(years)

stations_path = RAW_DIR / "th_stations_all.csv"
if not stations_path.exists():
    raise SystemExit(
        f"ไม่พบ {stations_path}\n"
        "→ รัน python 02_ETL/get_stations.py ก่อน"
    )
stations = pd.read_csv(stations_path)

rows = []
for _, s in stations.head(50).iterrows():          # ลองสำรวจ 50 สถานีแรกก่อน
    yrs = available_years(s["location_id"])
    if yrs:
        rows.append({
            "location_id": s["location_id"],
            "station_name": s["station_name"],
            "locality": s["locality"],
            "years": yrs,
            "n_years": len(yrs),
            "from": min(yrs), "to": max(yrs),
        })

survey = pd.DataFrame(rows).sort_values("n_years", ascending=False)
out_path = RAW_DIR / "station_year_survey.csv"
survey.to_csv(out_path, index=False)
print(survey.to_string())
print(f"\nบันทึกที่ {out_path}")