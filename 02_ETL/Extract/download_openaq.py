"""
download_openaq.py — ดึงข้อมูล PM2.5 ย้อนหลังจาก OpenAQ S3

ใช้งาน:
    python 02_ETL/download_openaq.py            # โหลดจริง
    python 02_ETL/download_openaq.py --estimate # ประเมินขนาดก่อน ไม่โหลด

คุณสมบัติ:
  - ไม่ต้องใช้ API key (S3 เป็น public bucket)
  - ข้ามไฟล์ที่โหลดแล้ว → รันซ้ำได้ / Incremental Load
  - เน็ตหลุดกลางทางรันใหม่ได้ โหลดต่อจากจุดเดิม
  - บันทึก manifest ไว้ตรวจสอบภายหลัง
"""
import sys
import json
import time

import boto3
from botocore import UNSIGNED
from botocore.config import Config
from botocore.exceptions import ClientError
from concurrent.futures import ThreadPoolExecutor, as_completed

# ให้ import config.py จากโฟลเดอร์แม่ (02_ETL) ได้ แม้สคริปต์จะอยู่ในโฟลเดอร์ย่อย
import sys
from pathlib import Path as _Path
sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

from config import (
    SELECTED_STATIONS, ARCHIVE_YEARS as YEARS, MEAS_DIR, RAW_DIR,
    BUCKET, PREFIX, MAX_WORKERS,
)

s3 = boto3.client(
    "s3",
    config=Config(
        signature_version=UNSIGNED,          # public bucket ไม่ต้อง auth
        max_pool_connections=MAX_WORKERS * 2,
        retries={"max_attempts": 5, "mode": "adaptive"},
    ),
)


def list_objects(location_id: int, year: int):
    """คืน list ของ (key, size) ทุกไฟล์ของสถานี+ปีนั้นบน S3"""
    paginator = s3.get_paginator("list_objects_v2")
    prefix = f"{PREFIX}/locationid={location_id}/year={year}/"
    out = []
    for page in paginator.paginate(Bucket=BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            out.append((obj["Key"], obj["Size"]))
    return out


def local_path(key: str):
    """แปลง S3 key เป็น path บนเครื่อง โดยคงโครงสร้าง hive partition ไว้"""
    return MEAS_DIR / key.replace(f"{PREFIX}/", "")


def fetch(key: str) -> str:
    """โหลด 1 ไฟล์ คืนสถานะ skip / ok / fail"""
    dest = local_path(key)
    if dest.exists() and dest.stat().st_size > 0:
        return "skip"
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        s3.download_file(BUCKET, key, str(dest))
        return "ok"
    except ClientError as e:
        print(f"    [error] {key}: {e}")
        dest.unlink(missing_ok=True)   # ลบไฟล์ที่โหลดไม่สมบูรณ์
        return "fail"


def estimate():
    """สำรวจขนาดก่อนโหลดจริง"""
    print(f"{'ID':>7}  {'สถานี':<42} {'ไฟล์':>7} {'ขนาด':>10}")
    print("-" * 72)
    tot_files = tot_bytes = 0
    for loc, name in SELECTED_STATIONS.items():
        n = size = 0
        for y in YEARS:
            for _, sz in list_objects(loc, y):
                n += 1
                size += sz
        print(f"{loc:>7}  {name:<42} {n:>7,} {size/1e6:>8.1f} MB")
        tot_files += n
        tot_bytes += size

    print("-" * 72)
    print(f"รวม {tot_files:,} ไฟล์  {tot_bytes/1e6:.1f} MB")
    mins = tot_files / MAX_WORKERS / 8 / 60
    print(f"ประเมินเวลาโหลด (~{MAX_WORKERS} threads): ประมาณ {mins:.0f} นาที")


def download():
    t0 = time.time()
    manifest = []

    for loc, name in SELECTED_STATIONS.items():
        for year in YEARS:
            objs = list_objects(loc, year)
            if not objs:
                print(f"[{loc}] {name[:34]:<34} {year}: ไม่มีข้อมูลบน S3")
                manifest.append({
                    "location_id": loc, "station_name": name, "year": year,
                    "n_files": 0, "ok": 0, "skip": 0, "fail": 0,
                    "status": "no_data",
                })
                continue

            keys = [k for k, _ in objs]
            stats = {"ok": 0, "skip": 0, "fail": 0}
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
                futures = [pool.submit(fetch, k) for k in keys]
                for f in as_completed(futures):
                    stats[f.result()] += 1

            print(f"[{loc}] {name[:34]:<34} {year}: "
                  f"ทั้งหมด {len(keys):>3} | ใหม่ {stats['ok']:>3} | "
                  f"มีแล้ว {stats['skip']:>3} | พลาด {stats['fail']}")

            manifest.append({
                "location_id": loc, "station_name": name, "year": year,
                "n_files": len(keys), **stats, "status": "ok",
            })

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    with open(RAW_DIR / "download_manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    total = sum(m["n_files"] for m in manifest)
    failed = sum(m["fail"] for m in manifest)
    print(f"\nเสร็จสิ้นใน {(time.time()-t0)/60:.1f} นาที")
    print(f"ไฟล์ทั้งหมด {total:,} | โหลดไม่สำเร็จ {failed}")
    if failed:
        print("มีไฟล์ที่โหลดไม่สำเร็จ — รันสคริปต์นี้ซ้ำอีกครั้งเพื่อลองใหม่")


if __name__ == "__main__":
    if "--estimate" in sys.argv:
        estimate()
    else:
        download()