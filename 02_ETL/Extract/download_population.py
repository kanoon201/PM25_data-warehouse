"""
download_population.py — ดึงจำนวนประชากรรายจังหวัดจากกรมการปกครอง (BORA)

ใช้งาน:
    python 02_ETL/01_extract/download_population.py

ทำไมต้องดึงจาก BORA ไม่ใช่ data.go.th:
    data.go.th มีชุดข้อมูล "จำนวนประชากรในประเทศไทย แยกตามพื้นที่" ซึ่งเป็นชุดเดียวกัน
    และระบุว่าอัปเดตอัตโนมัติรายเดือน แต่ตรวจแล้วพบว่าไฟล์ค้างอยู่ที่ พ.ศ. 2563 (ค.ศ. 2020)
    ซึ่งเก่ากว่าช่วงวิเคราะห์ 2022-2025 จึงต้องดึงจาก BORA ซึ่งเป็นต้นทางจริง

รูปแบบไฟล์ต้นทาง (pipe-delimited ไม่มี header):
    YYMM|CC-CODE|CC-DESC|RCODE|...|MALE|FEMALE|TOTAL|HOUSE|
    6712|10|กรุงเทพมหานคร|0| |...|2,544,400|2,910,620|5,455,020|3,304,462|

ผลลัพธ์ใน 01_Raw_Data/Population/:
    stat_c65.txt … stat_c68.txt          ไฟล์ดิบ (เก็บไว้ตามข้อกำหนดของโจทย์)
    population_by_province.csv           77 จังหวัด ปีฐาน — ใช้โดย build_star_schema.py
    population_by_province_all_years.csv ทุกปีในช่วงวิเคราะห์ เผื่อวิเคราะห์รายปี
"""
import time

import requests
import pandas as pd

# ให้ import config.py จากโฟลเดอร์แม่ (02_ETL) ได้ แม้สคริปต์จะอยู่ในโฟลเดอร์ย่อย
import sys
from pathlib import Path as _Path
sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

from config import (
    POPULATION_DIR, POPULATION_FILE, POPULATION_ALL_YEARS,
    POPULATION_URL, POPULATION_BASE_YEAR, BE_OFFSET, YEARS,
)

# ชื่อคอลัมน์ของไฟล์ BORA (ไฟล์ไม่มี header ต้องกำหนดเอง)
COLS = ["YYMM", "CC_CODE", "CC_DESC", "RCODE", "RDESC", "CCAATT", "CCAATT_D",
        "CCAATTMM", "CCAATTMM_D", "MALE", "FEMALE", "TOTAL", "HOUSE"]

MAX_RETRIES = 3
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://stat.bora.dopa.go.th/new_stat/webPage/statByYear.php",
}


def fetch_year(year_ce):
    """ดึงไฟล์ประชากรของปี ค.ศ. ที่ระบุ — คืน path ของไฟล์ดิบ"""
    yy = str(year_ce + BE_OFFSET)[-2:]      # 2024 → พ.ศ. 2567 → "67"
    dest = POPULATION_DIR / f"stat_c{yy}.txt"

    if dest.exists():
        print(f"  [{year_ce}] ใช้ไฟล์ที่ดึงไว้แล้ว: {dest.name}")
        return dest

    url = POPULATION_URL.format(yy=yy)
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.get(url, timeout=120, headers=HEADERS)
        except requests.exceptions.RequestException as e:
            if attempt == MAX_RETRIES:
                print(f"  [{year_ce}] เชื่อมต่อไม่ได้: {type(e).__name__}")
                return None
            print(f"  [{year_ce}] {type(e).__name__} — รอ 30 วินาทีแล้วลองใหม่")
            time.sleep(30)
            continue

        if r.status_code != 200 or len(r.content) < 3000:
            print(f"  [{year_ce}] ดึงไม่สำเร็จ HTTP {r.status_code} "
                  f"({len(r.content):,} bytes)")
            return None

        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(r.content)
        print(f"  [{year_ce}] ดึงสำเร็จ {len(r.content):,} bytes → {dest.name}")
        return dest
    return None


def parse(path, year_ce):
    """แปลงไฟล์ดิบเป็น DataFrame ระดับจังหวัด"""
    df = pd.read_csv(path, sep="|", header=None, names=COLS + ["_end"],
                     dtype=str, encoding="utf-8-sig").drop(columns=["_end"])
    df["year_ce"] = year_ce
    df["province_code"] = pd.to_numeric(df["CC_CODE"], errors="coerce")
    # TOTAL มีเครื่องหมายจุลภาคคั่นหลักพัน ต้องตัดออกก่อนแปลงเป็นตัวเลข
    df["population"] = pd.to_numeric(
        df["TOTAL"].str.replace(",", "", regex=False), errors="coerce")
    # ตัดคำว่า "จังหวัด" นำหน้าออก ให้ตรงกับชื่อในไฟล์ HDC
    df["province_name_th"] = (df["CC_DESC"].str.strip()
                              .str.replace(r"^จังหวัด", "", regex=True).str.strip())
    # province_code = 0 คือแถว "ทั่วประเทศ" ไม่ใช่จังหวัด
    return df[df["province_code"] > 0].dropna(subset=["population"])


def main():
    POPULATION_DIR.mkdir(parents=True, exist_ok=True)
    print(f"ดึงข้อมูลประชากรปี {min(YEARS)}-{max(YEARS)} จากกรมการปกครอง (BORA)")

    frames, failed = [], []
    for year in YEARS:
        path = fetch_year(year)
        if path is None:
            failed.append(year)
            continue
        frames.append(parse(path, year))

    if not frames:
        raise SystemExit("ดึงข้อมูลประชากรไม่ได้เลย")

    df = pd.concat(frames, ignore_index=True)
    df["province_code"] = df["province_code"].astype(int)

    # ---------- ตรวจคุณภาพ ----------
    print("\n=== ตรวจคุณภาพ ===")
    print(f"  แถวทั้งหมด        : {len(df):,}")
    print(f"  จังหวัดไม่ซ้ำ      : {df['province_code'].nunique()} (ต้องเป็น 77)")
    print(f"  ปีที่ได้           : {sorted(df['year_ce'].unique())}")
    per_year = df.groupby("year_ce")["population"].agg(["count", "sum"])
    print("\n  ประชากรรวมรายปี:")
    for y, r in per_year.iterrows():
        print(f"    {y}  {int(r['count'])} จังหวัด  {int(r['sum']):,} คน")

    if df["province_code"].nunique() != 77:
        print(f"\n  [เตือน] ได้ {df['province_code'].nunique()} จังหวัด ไม่ใช่ 77")

    # ---------- เขียนไฟล์ ----------
    base = df[df["year_ce"] == POPULATION_BASE_YEAR]
    if base.empty:
        raise SystemExit(
            f"ไม่มีข้อมูลปีฐาน {POPULATION_BASE_YEAR} "
            f"— แก้ POPULATION_BASE_YEAR ใน config.py"
        )
    base = (base[["province_code", "province_name_th", "population"]]
            .sort_values("province_code"))
    base.to_csv(POPULATION_FILE, index=False)
    print(f"\nเขียน {POPULATION_FILE.name}: {len(base)} จังหวัด "
          f"(ปีฐาน {POPULATION_BASE_YEAR})")

    (df[["year_ce", "province_code", "province_name_th", "population"]]
     .sort_values(["year_ce", "province_code"])
     .to_csv(POPULATION_ALL_YEARS, index=False))
    print(f"เขียน {POPULATION_ALL_YEARS.name}: {len(df):,} แถว")

    if failed:
        print(f"\n[ล้มเหลว] ดึงไม่ได้ {len(failed)} ปี: {failed}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
