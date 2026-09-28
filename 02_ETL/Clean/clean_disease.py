"""
clean_disease.py — นำข้อมูลผู้ป่วยจาก HDC กระทรวงสาธารณสุขเข้า staging

ใช้งาน:
    python 02_ETL/02_clean/clean_disease.py

ปัญหาคุณภาพข้อมูลที่สคริปต์นี้แก้:
    1. แถวซ้ำ 12,045 แถว (ปี 2567 และ 2569) → แก้ด้วยกฎ "ยึดการส่งครั้งล่าสุด"
       ถ้าไม่แก้ ยอดผู้ป่วยรวมจะเกินจริง 875,502 ครั้ง (1.3%)
       แถวซ้ำมี 2 แบบ ซึ่งต้องใช้กฎเดียวกันจัดการทั้งคู่:
         (ก) ส่งซ้ำค่าเดิมเป๊ะ ๆ — เช่น hospcode 28213 ส่ง 16 ธ.ค. แล้วส่งซ้ำ 17 ธ.ค.
         (ข) ส่งแก้ไขด้วยค่าใหม่ — เช่น hospcode 04182 ส่ง 08:49 (m1=10) แล้วแก้เป็น
             11:02 (m1=3) ซึ่ง DISTINCT จับไม่ได้เพราะค่าต่างกัน
       ทั้งสองแบบแยกกันด้วยคอลัมน์ date_com (เวลาที่ส่งข้อมูล) จึงเลือกแถวที่ date_com
       ใหม่ที่สุดของแต่ละ (รพ. × ปี × กลุ่มโรคย่อย) ตามหลักที่การส่งครั้งหลังแทนที่ครั้งก่อน
    2. ปีเป็น พ.ศ. ขณะที่ข้อมูลฝุ่นเป็น ค.ศ. → ลบ 543
    3. โครงสร้าง wide (m1-m12) → unpivot เป็นแถวรายเดือน
    4. ปี 2569 มีข้อมูลไม่ครบ (m8 บางส่วน, m9-m12 เป็น 0) → ตัดออกด้วยการกรองช่วงปี
    5. กลุ่มโรค 5 ยังยืนยัน mapping ไม่ได้ → ไม่นำเข้า

ผลลัพธ์ใน dw.duckdb:
    stg_disease_monthly — โรงพยาบาล × เดือน × กลุ่มโรคย่อย (เฉพาะที่มีผู้ป่วย > 0)
    stg_disease_map     — ตารางอ้างอิงชื่อกลุ่มโรค
"""
import duckdb

# ให้ import config.py จากโฟลเดอร์แม่ (02_ETL) ได้ แม้สคริปต์จะอยู่ในโฟลเดอร์ย่อย
import sys
from pathlib import Path as _Path
sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

from config import (
    DW_PATH, DISEASE_FILE, DISEASE_RAW_FILE, DISEASE_MAP, DISEASE_AREA,
    BE_OFFSET, EXCLUDED_DISEASE_GROUPS, YEARS, LOCAL_TZ,
)


def main():
    if not DISEASE_FILE.exists():
        raise SystemExit(f"ไม่พบไฟล์ {DISEASE_FILE}")

    con = duckdb.connect(str(DW_PATH))
    con.execute(f"SET TimeZone = '{LOCAL_TZ}';")

    # ---------- 1) EXTRACT: ใช้ไฟล์ที่ทำความสะอาดแล้ว ----------
    con.execute(f"""
        CREATE OR REPLACE TEMP VIEW raw_disease AS
        SELECT * FROM read_csv_auto('{DISEASE_FILE}', union_by_name = true);
    """)
    n_raw = con.execute("SELECT COUNT(*) FROM raw_disease").fetchone()[0]
    print(f"อ่านไฟล์ผู้ป่วย (clean): {n_raw:,} แถว")

    # ---------- 2) รายงานว่าการทำความสะอาดแก้อะไรไปบ้าง ----------
    # เทียบกับไฟล์ดิบเดิม เพื่อให้หลักฐานเรื่องคุณภาพข้อมูลยังอยู่ในผลรัน
    # (ข้อกำหนดต้องการให้แสดงว่าตรวจพบปัญหาอะไรและแก้อย่างไร)
    if DISEASE_RAW_FILE.exists():
        print("\n=== เทียบไฟล์ดิบกับไฟล์ที่ทำความสะอาดแล้ว ===")
        months = " + ".join(f"m{i}" for i in range(1, 13))
        print(con.execute(f"""
            WITH r AS (SELECT * FROM read_csv_auto('{DISEASE_RAW_FILE}', union_by_name = true))
            SELECT
                (SELECT COUNT(*) FROM r)                          AS ดิบ_แถว,
                (SELECT COUNT(*) FROM raw_disease)                AS clean_แถว,
                (SELECT COUNT(*) FROM r)
                  - (SELECT COUNT(*) FROM raw_disease)            AS ตัดออก,
                (SELECT COUNT(*) - COUNT(DISTINCT (hospcode, b_year,
                    disease_group_id, disease_sub_group_id)) FROM r) AS ดิบ_แถวซ้ำ,
                (SELECT COUNT(*) - COUNT(DISTINCT (hospcode, b_year,
                    disease_group_id, disease_sub_group_id)) FROM raw_disease) AS clean_แถวซ้ำ
        """).df().to_string(index=False))

    print("\n=== ปัญหาคุณภาพข้อมูลที่ยังเหลือในไฟล์ clean ===")
    dq = con.execute("""
        SELECT
            COUNT(*)                                    AS total_rows,
            COUNT(*) - COUNT(DISTINCT (hospcode, b_year,
                       disease_group_id, disease_sub_group_id)) AS duplicate_rows,
            COUNT(DISTINCT hospcode)                    AS hospitals,
            COUNT(DISTINCT _province_name)              AS provinces,
            COUNT(*) FILTER (WHERE TRY_CAST(areacode AS BIGINT) IS NULL) AS invalid_areacode
        FROM raw_disease;
    """).df()
    print(dq.to_string(index=False))

    # ไฟล์ clean มีคอลัมน์ year_ce มาให้แล้ว — ตรวจว่าตรงกับ b_year - 543 จริง
    mismatch = con.execute(f"""
        SELECT COUNT(*) FROM raw_disease WHERE year_ce <> b_year - {BE_OFFSET};
    """).fetchone()[0]
    print(f"\nyear_ce ที่ไม่ตรงกับ b_year - {BE_OFFSET}: {mismatch:,} แถว"
          f"{' ✅' if mismatch == 0 else ' [เตือน] ตรวจไฟล์ต้นทาง'}")

    # ---------- 3) CLEAN + TRANSFORM ----------
    # ไฟล์ clean แก้แถวซ้ำมาแล้ว แต่คง QUALIFY ไว้เป็นตาข่ายกันพลาด
    # เผื่อวันหนึ่งเปลี่ยนกลับไปใช้ไฟล์ดิบ หรือไฟล์ clean มีปัญหา
    # (ต้องทำ "ก่อน" unpivot มิฉะนั้นจะ dedupe ผิดระดับ)
    # ถ้าไม่มีกลุ่มที่ต้องตัด ให้เงื่อนไขเป็น TRUE เพราะ SQL ไม่ยอมรับ NOT IN ()
    if EXCLUDED_DISEASE_GROUPS:
        ids = ", ".join(str(g) for g in EXCLUDED_DISEASE_GROUPS)
        exclude_clause = f"disease_group_id NOT IN ({ids})"
        print(f"\nตัดกลุ่มโรคออกจากการวิเคราะห์: {EXCLUDED_DISEASE_GROUPS}")
    else:
        exclude_clause = "TRUE"
        print("\nนำเข้าครบทุกกลุ่มโรค (ไม่มีกลุ่มที่ถูกตัดออก)")
    con.execute(f"""
        CREATE OR REPLACE TABLE stg_disease_monthly AS
        WITH deduped AS (
            SELECT * FROM raw_disease
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY hospcode, b_year, disease_group_id, disease_sub_group_id
                ORDER BY date_com DESC) = 1
        ),
        unpivoted AS (
            SELECT
                hospcode,
                areacode,
                _province_code AS province_code,
                _province_name AS province_name,
                district_code,
                b_year         AS year_be,
                b_year - {BE_OFFSET} AS year_ce,
                CAST(REPLACE(month_col, 'm', '') AS INTEGER) AS month_no,
                disease_group_id,
                disease_sub_group_id,
                visit_count
            FROM deduped
            UNPIVOT (visit_count FOR month_col IN ({', '.join(f'm{i}' for i in range(1, 13))}))
        )
        SELECT
            hospcode,
            areacode,
            TRY_CAST(areacode AS BIGINT) IS NOT NULL AS areacode_is_valid,
            province_code,
            province_name,
            district_code,
            year_be,
            year_ce,
            month_no,
            MAKE_DATE(year_ce, month_no, 1)              AS month_date,
            year_ce * 100 + month_no                     AS month_key,
            disease_group_id,
            disease_sub_group_id,
            visit_count
        FROM unpivoted
        WHERE year_ce BETWEEN {min(YEARS)} AND {max(YEARS)}
          AND {exclude_clause}
          AND visit_count > 0;
    """)

    n_out = con.execute("SELECT COUNT(*) FROM stg_disease_monthly").fetchone()[0]
    total = con.execute(
        "SELECT SUM(visit_count) FROM stg_disease_monthly").fetchone()[0]
    print(f"\nสร้าง stg_disease_monthly: {n_out:,} แถว "
          f"(รวม {total:,.0f} ครั้งการรับบริการ)")

    # ---------- 3.5) ตารางอ้างอิงพื้นที่ (จังหวัด + อำเภอ ไทย/อังกฤษ) ----------
    if DISEASE_AREA.exists():
        con.execute(f"""
            CREATE OR REPLACE TABLE stg_area AS
            SELECT
                CAST(province_code AS INTEGER) AS province_code,
                province_name_th,
                province_name_en,
                LPAD(CAST(district_code AS VARCHAR), 2, '0') AS district_code,
                district_name_th,
                district_name_en
            FROM read_csv_auto('{DISEASE_AREA}');
        """)
        n_area = con.execute("SELECT COUNT(*) FROM stg_area").fetchone()[0]
        n_prov = con.execute(
            "SELECT COUNT(DISTINCT province_code) FROM stg_area").fetchone()[0]
        print(f"สร้าง stg_area: {n_area:,} แถว ({n_prov} จังหวัด)")
    else:
        print(f"[เตือน] ไม่พบ {DISEASE_AREA.name} → DIM_PROVINCE จะไม่มีชื่ออังกฤษ")

    # ---------- 4) ตารางอ้างอิงกลุ่มโรค ----------
    con.execute(f"""
        CREATE OR REPLACE TABLE stg_disease_map AS
        SELECT * FROM read_csv_auto('{DISEASE_MAP}');
    """)
    n_map = con.execute("SELECT COUNT(*) FROM stg_disease_map").fetchone()[0]
    print(f"สร้าง stg_disease_map: {n_map} กลุ่มโรค")

    # ---------- 5) VALIDATE หลัง Load ----------
    print("\n=== สรุปรายปี (ตรวจความสมเหตุสมผล) ===")
    print(con.execute("""
        SELECT year_ce,
               COUNT(*)                  AS fact_rows,
               COUNT(DISTINCT hospcode)  AS hospitals,
               SUM(visit_count)          AS visits
        FROM stg_disease_monthly GROUP BY 1 ORDER BY 1;
    """).df().to_string(index=False))

    print("\n=== ผู้ป่วยกลุ่มทางเดินหายใจรายเดือน (ควรสูงช่วง ม.ค.-เม.ย.) ===")
    print(con.execute("""
        SELECT month_no, SUM(visit_count) AS visits
        FROM stg_disease_monthly WHERE disease_group_id = 1
        GROUP BY 1 ORDER BY 1;
    """).df().to_string(index=False))

    # เตือนถ้าจังหวัด-ปีไหนหายไป (ลำปาง 2024 หายจริง ต้องเห็นตรงนี้)
    print("\n=== จังหวัด-ปีที่ไม่มีข้อมูล (ต้องรายงานใน Dashboard ว่า 'ไม่มีข้อมูล') ===")
    missing = con.execute(f"""
        WITH all_combos AS (
            SELECT p.province_name, y.year_ce
            FROM (SELECT DISTINCT province_name FROM stg_disease_monthly) p
            CROSS JOIN (SELECT UNNEST(range({min(YEARS)}, {max(YEARS) + 1})) AS year_ce) y
        )
        SELECT a.province_name, a.year_ce
        FROM all_combos a
        LEFT JOIN (SELECT DISTINCT province_name, year_ce FROM stg_disease_monthly) d
               ON a.province_name = d.province_name AND a.year_ce = d.year_ce
        WHERE d.province_name IS NULL
        ORDER BY 1, 2;
    """).df()
    print(missing.to_string(index=False) if len(missing) else "ไม่มี — ทุกจังหวัดมีข้อมูลครบทุกปี")

    con.close()
    print(f"\nบันทึกที่ {DW_PATH}")


if __name__ == "__main__":
    main()
