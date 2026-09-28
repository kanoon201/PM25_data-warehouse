"""
clean_disease_extract.py — ขั้น EXTRACT + CLEAN: โหลดข้อมูลผู้ป่วยจาก HDC และทำความสะอาด

ใช้งาน:
    python 02_ETL/Clean/clean_disease_extract.py

ปัญหาคุณภาพข้อมูลที่สคริปต์นี้แก้:
    1. แถวซ้ำ — ยึดการส่งครั้งล่าสุด (date_com ล่าสุด)
    2. ปีเป็น พ.ศ. — แปลง + สร้าง year_ce (ค.ศ.)
    3. areacode รูปแบบผิด — ระบุและรายงาน
    4. ค่าติดลบในผู้ป่วย — clip เป็น 0
    5. ตัดคอลัมน์ที่ไม่ใช้ (ip, flag_sent)
    6. สร้าง district_code จาก areacode — ขั้นถัดไปต้องใช้ตอนสร้าง DIM_HOSPITAL

ผลลัพธ์:
    disease_monthly_wide_clean.csv — WIDE format (m1-m12) พร้อมใช้โดยสคริปต์ถัดไป

หมายเหตุ: ถ้ามีไฟล์ผลลัพธ์เดิมอยู่แล้ว สคริปต์จะเขียนลงไฟล์ *_NEW.csv แทน
เพื่อไม่ให้ทับไฟล์ที่ dw.duckdb ถูกสร้างมาจาก — ถ้าตั้งใจทับจริงให้รันด้วย --overwrite
"""

import sys
from pathlib import Path

# Import config จากโฟลเดอร์แม่ (02_ETL)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# config.py ใช้ชื่อ DISEASE_MAP / DISEASE_FILE — ตั้ง alias ให้ตรงกับที่สคริปต์นี้เรียกใช้
from config import (
    DISEASE_RAW_FILE,
    DISEASE_MAP as DISEASE_DIM,
    DISEASE_FILE as DISEASE_WIDE_CLEAN,
)

import pandas as pd
import numpy as np
from datetime import datetime

# ========== LOGGING ==========
pd.set_option('display.max_columns', None)

log_lines = []
def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    log_lines.append(line)


# ========== EXTRACT ==========
def main():
    log("=== EXTRACT ===")

    if not DISEASE_RAW_FILE.exists():
        raise FileNotFoundError(f"ไม่พบไฟล์: {DISEASE_RAW_FILE}")
    log(f"ไฟล์ต้นทาง: {DISEASE_RAW_FILE}")

    if not DISEASE_DIM.exists():
        log(f"[เตือน] ไม่พบไฟล์: {DISEASE_DIM}")
        DISEASE_DIM_AVAILABLE = False
    else:
        log(f"ไฟล์ mapping: {DISEASE_DIM}")
        DISEASE_DIM_AVAILABLE = True

    # โหลดข้อมูล
    raw = pd.read_csv(DISEASE_RAW_FILE, dtype={"date_com": str})
    log(f"โหลดข้อมูล: {len(raw):,} แถว × {raw.shape[1]} คอลัมน์")
    log(f"ปีที่มี (b_year): {sorted(raw['b_year'].unique())}")


    # ========== CLEAN ==========
    log("\n=== CLEAN ===")

    dq_log = []
    df = raw.copy()
    month_cols = [f"m{i}" for i in range(1, 13)]

    # 1) ตัดคอลัมน์ที่ไม่ใช้
    cols_dropped = []
    if "ip" in df.columns:
        df = df.drop(columns=["ip"])
        cols_dropped.append("ip")
    if "flag_sent" in df.columns:
        df = df.drop(columns=["flag_sent"])
        cols_dropped.append("flag_sent")

    if cols_dropped:
        log(f"ตัดคอลัมน์: {', '.join(cols_dropped)}")


    # 2) ตรวจสอบ NaN/Null
    log("\n--- ตรวจสอบ NaN/Null ---")
    null_counts = df.isnull().sum()
    cols_with_null = null_counts[null_counts > 0]
    if len(cols_with_null) > 0:
        log(f"พบ null ใน {len(cols_with_null)} คอลัมน์:")
        for col, cnt in cols_with_null.items():
            pct = cnt/len(df)*100
            log(f"  '{col}': {cnt:,} แถว ({pct:.2f}%)")
            dq_log.append(f"Missing '{col}': {cnt} ({pct:.1f}%)")
    else:
        log("ไม่พบ null ในคอลัมน์ใด")


    # 3) ตรวจสอบค่าว่าง (empty string)
    log("\n--- ตรวจสอบค่าว่าง (empty string) ---")
    text_cols = df.select_dtypes(include="object").columns
    for col in text_cols:
        empty_count = (df[col].astype(str).str.strip() == "").sum()
        if empty_count > 0:
            log(f"  '{col}': {empty_count:,} ค่าว่าง")


    # 4) ตรวจสอบและแก้ไขแถวซ้ำ
    log("\n--- ตรวจสอบแถวซ้ำ ---")
    dup_key = ["hospcode", "b_year", "disease_group_id", "disease_sub_group_id"]

    all_dups = df[df.duplicated(subset=dup_key, keep=False)].sort_values(dup_key)
    total_dup_rows = len(all_dups)

    check_cols = dup_key + month_cols
    identical_rows = all_dups.duplicated(subset=check_cols, keep=False).sum()
    diff_rows = all_dups[~all_dups.duplicated(subset=check_cols, keep=False)]

    log(f"แถวที่ key ซ้ำกัน: {total_dup_rows}")
    if total_dup_rows > 0:
        log(f"  - ข้อมูล m1-m12 เหมือนกันเป๊ะ: {identical_rows}")
        log(f"  - ข้อมูล m1-m12 ต่างกัน (ต้องเลือกล่าสุด): {len(diff_rows)}")

    dq_log.append(f"Duplicate rows (key match): {total_dup_rows}")
    dq_log.append(f"Duplicate rows with different values: {len(diff_rows)}")

    # ลบแถวซ้ำ เก็บแถวที่ date_com ล่าสุด
    n_before = len(df)
    df = df.sort_values("date_com").drop_duplicates(subset=dup_key, keep="last")
    n_after = len(df)
    log(f"ลบแถวซ้ำ: {n_before - n_after:,} แถว (เก็บแถวที่ date_com ล่าสุด)")


    # 5) ตรวจสอบ areacode
    log("\n--- ตรวจสอบ areacode ---")
    df["areacode"] = df["areacode"].astype(str)
    invalid_area = df[~df["areacode"].str.match(r"^\d{8}$", na=False)]
    log(f"areacode รูปแบบผิด: {len(invalid_area)} แถว")
    dq_log.append(f"Invalid areacode format: {len(invalid_area)}")

    if len(invalid_area) > 0:
        dash_pattern = invalid_area[invalid_area["areacode"].str.endswith("-", na=False)]
        nu_pattern = invalid_area[invalid_area["areacode"].str.endswith("nu", na=False)]
        other_pattern = invalid_area[
            ~invalid_area["areacode"].str.endswith("-", na=False) &
            ~invalid_area["areacode"].str.endswith("nu", na=False)
        ]
        log(f"  - ลงท้ายด้วย '-': {len(dash_pattern)}")
        log(f"  - ลงท้ายด้วย 'nu': {len(nu_pattern)}")
        log(f"  - รูปแบบอื่น: {len(other_pattern)}")

        dq_log.append(f"Invalid areacode - ends with '-': {len(dash_pattern)}")
        dq_log.append(f"Invalid areacode - ends with 'nu': {len(nu_pattern)}")
        dq_log.append(f"Invalid areacode - other: {len(other_pattern)}")


    # 6) ตรวจสอบค่าติดลบใน m1-m12
    log("\n--- ตรวจสอบค่าติดลบ ---")
    neg_mask = (df[month_cols] < 0).any(axis=1)
    if neg_mask.sum() > 0:
        log(f"พบค่าติดลบ: {neg_mask.sum()} แถว -> clip เป็น 0")
        df[month_cols] = df[month_cols].clip(lower=0)
        dq_log.append(f"Negative patient count: {neg_mask.sum()}")
    else:
        log("ไม่พบค่าติดลบใน m1-m12")


    # 7) แปลง b_year -> year_ce
    log("\n--- แปลงปี ---")
    df["year_ce"] = df["b_year"].astype(int) - 543
    log(f"สร้าง year_ce = b_year - 543")
    log(f"  ตัวอย่าง: {df['b_year'].iloc[0]} -> {df['year_ce'].iloc[0]}")

    # ถ้ามี _year_be ให้เทียบกับ b_year
    if "_year_be" in df.columns:
        mismatch_years = (df["b_year"].astype(str) != df["_year_be"].astype(str)).sum()
        if mismatch_years == 0:
            log(f"เช็ค b_year vs _year_be: ตรงกันทั้งหมด -> ตัด '_year_be' ทิ้ง")
            df = df.drop(columns=["_year_be"])
            dq_log.append("b_year vs _year_be: identical, dropped _year_be")
        else:
            log(f"เช็ค b_year vs _year_be: พบ mismatch {mismatch_years} แถว -> เก็บทั้ง 2 คอลัมน์")
            dq_log.append(f"b_year vs _year_be: mismatch in {mismatch_years} rows")


    # 8) ตรวจสอบ _province_code ตรงกับ areacode 2 หลักแรกไหม
    log("\n--- ตรวจสอบ _province_code vs areacode ---")
    valid_area = df[df["areacode"].str.match(r"^\d{8}$", na=False)].copy()
    valid_area["province_from_areacode"] = valid_area["areacode"].str[:2]
    mismatch = valid_area[valid_area["province_from_areacode"] != valid_area["_province_code"].astype(str)]

    log(f"ไม่ตรงกัน: {len(mismatch)} แถว จาก {len(valid_area):,} แถวที่ areacode valid")
    dq_log.append(f"_province_code vs areacode mismatch: {len(mismatch)}")


    # 9) ตรวจสอบ disease group mapping
    if DISEASE_DIM_AVAILABLE:
        log("\n--- ตรวจสอบ disease group mapping ---")
        dim_disease = pd.read_csv(DISEASE_DIM)
        valid_pairs = set(zip(dim_disease["disease_group_id"], dim_disease["disease_sub_group_id"]))
        df_pairs = list(zip(df["disease_group_id"], df["disease_sub_group_id"]))
        n_orphan = sum(p not in valid_pairs for p in df_pairs)
        log(f"Orphan disease group/sub_group: {n_orphan} แถว")
        dq_log.append(f"Orphan group/sub_group: {n_orphan}")
    else:
        log("\n[ข้าม] ตรวจสอบ disease group mapping (ไม่มีไฟล์ dim_disease)")


    # 10) สร้าง district_code — clean_disease.py และ build_dimensions.py ต้องใช้
    #     ตอนสร้าง DIM_HOSPITAL ถ้าไม่มีคอลัมน์นี้ ขั้นถัดไปจะพัง
    #     areacode 8 หลัก = จังหวัด 2 + อำเภอ 2 + ตำบล 2 + หมู่บ้าน 2
    log("\n--- สร้าง district_code ---")
    df["district_code"] = df["areacode"].astype(str).str.slice(2, 4)
    n_bad = int((df["district_code"].str.len() != 2).sum())
    log(f"district_code = areacode[2:4] · ผิดรูปแบบ {n_bad} แถว")
    dq_log.append(f"district_code ผิดรูปแบบ: {n_bad}")


    # ========== SAVE OUTPUT ==========
    log("\n=== SAVE OUTPUT ===")

    # เรียงคอลัมน์ให้ตรงกับไฟล์ที่ขั้นถัดไปคาดหวัง
    expected = ["id", "hospcode", "areacode", "date_com", "b_year",
                "disease_group_id", "disease_sub_group_id",
                "m1", "m2", "m3", "m4", "m5", "m6",
                "m7", "m8", "m9", "m10", "m11", "m12",
                "_province_code", "_province_name", "district_code", "year_ce"]
    missing = [c for c in expected if c not in df.columns]
    if missing:
        raise SystemExit(f"[หยุด] คอลัมน์ที่ขั้นถัดไปต้องใช้หายไป: {missing}")
    df = df[expected + [c for c in df.columns if c not in expected]]

    # สร้างโฟลเดอร์ถ้ายังไม่มี
    DISEASE_WIDE_CLEAN.parent.mkdir(parents=True, exist_ok=True)

    # ไฟล์เดิมคือไฟล์ที่ dw.duckdb ถูกสร้างมาจริง ส่วนไฟล์ดิบใน monthly/ เป็นข้อมูล
    # ที่ดึงจาก HDC ทีหลัง (จำนวนแถวไม่เท่ากัน) การเขียนทับจะทำให้ตัวเลขทุกตัว
    # ในรายงานเปลี่ยน จึงต้องสั่ง --overwrite เองเท่านั้น
    out_path = DISEASE_WIDE_CLEAN
    if out_path.exists() and "--overwrite" not in sys.argv:
        out_path = out_path.with_name(out_path.stem + "_NEW.csv")
        log(f"[ป้องกัน] มีไฟล์เดิมอยู่แล้ว — เขียนลง {out_path.name} แทน")
        log("          ถ้าตั้งใจจะเขียนทับไฟล์เดิมจริง ให้รันด้วย --overwrite")

    # บันทึกข้อมูล
    df.to_csv(out_path, index=False)
    log(f"✓ บันทึกไฟล์: {out_path}")
    log(f"  ขนาด: {len(df):,} แถว × {df.shape[1]} คอลัมน์")
    log(f"  ขนาดไฟล์: {out_path.stat().st_size / 1024 / 1024:.1f} MB")


    # ========== สรุป ==========
    log("\n=== สรุป ===")
    log(f"ข้อมูลต้นทาง: {len(raw):,} แถว")
    log(f"ข้อมูลหลังทำความสะอาด: {len(df):,} แถว")
    log(f"ลบออก: {len(raw) - len(df):,} แถว ({(len(raw) - len(df)) / len(raw) * 100:.2f}%)")
    log(f"\nคุณภาพข้อมูล:")
    for line in dq_log:
        log(f"  • {line}")

    log(f"\n✓ สเร็จ! ไฟล์พร้อมสำหรับขั้นถัดไป (clean_disease.py)")


if __name__ == "__main__":
    main()
