"""
clean_population.py — นำข้อมูลประชากรรายจังหวัด (กรมการปกครอง) เข้า staging

ใช้งาน:
    python 02_ETL/02_clean/clean_population.py
    (ต้องรัน 01_extract/download_population.py ก่อน)

ข้อมูลนี้จำเป็นสำหรับ Measure M4 (ผู้ป่วยต่อประชากรแสนคน) และ BQ3/BQ7
ซึ่งเป็นตัวเลขเดียวที่ทำให้เปรียบเทียบข้ามจังหวัดได้อย่างเป็นธรรม —
นครราชสีมามีประชากรมากกว่าสมุทรสงครามหลายเท่า การเทียบด้วยยอดผู้ป่วยดิบจึงไม่มีความหมาย

ผลลัพธ์ใน dw.duckdb:
    stg_population            — 77 จังหวัด ปีฐาน (ใช้เติม DIM_PROVINCE.population)
    stg_population_all_years  — ทุกปีในช่วงวิเคราะห์ เผื่อวิเคราะห์แนวโน้มรายปี
"""
import duckdb

# ให้ import config.py จากโฟลเดอร์แม่ (02_ETL) ได้ แม้สคริปต์จะอยู่ในโฟลเดอร์ย่อย
import sys
from pathlib import Path as _Path
sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

from config import (
    DW_PATH, POPULATION_FILE, POPULATION_ALL_YEARS,
    POPULATION_BASE_YEAR, LOCAL_TZ, YEARS,
)


def main():
    if not POPULATION_FILE.exists():
        # ไม่ล้ม pipeline — ข้อมูลประชากรเป็นตัวเสริม ไม่ใช่แกนหลักของ warehouse
        # แต่ต้องเตือนให้ชัด เพราะ M4/BQ3/BQ7 จะใช้งานไม่ได้
        print(f"[เตือน] ไม่พบ {POPULATION_FILE}")
        print("        → รัน python 02_ETL/01_extract/download_population.py ก่อน")
        print("        DIM_PROVINCE.population จะเป็น NULL และ M4/BQ3/BQ7 ใช้ไม่ได้")
        return

    con = duckdb.connect(str(DW_PATH))
    con.execute(f"SET TimeZone = '{LOCAL_TZ}';")

    # ---------- 1) ปีฐาน — ใช้เติม DIM_PROVINCE ----------
    con.execute(f"""
        CREATE OR REPLACE TABLE stg_population AS
        SELECT
            CAST(province_code AS INTEGER) AS province_code,
            province_name_th,
            CAST(population AS BIGINT)     AS population,
            {POPULATION_BASE_YEAR}         AS year_ce
        FROM read_csv_auto('{POPULATION_FILE}');
    """)
    n = con.execute("SELECT COUNT(*) FROM stg_population").fetchone()[0]
    total = con.execute("SELECT SUM(population) FROM stg_population").fetchone()[0]
    print(f"สร้าง stg_population: {n} จังหวัด "
          f"(ปีฐาน {POPULATION_BASE_YEAR}, รวม {total:,} คน)")

    # ---------- 2) ทุกปี — เผื่อวิเคราะห์แนวโน้ม ----------
    if POPULATION_ALL_YEARS.exists():
        con.execute(f"""
            CREATE OR REPLACE TABLE stg_population_all_years AS
            SELECT
                CAST(year_ce AS INTEGER)       AS year_ce,
                CAST(province_code AS INTEGER) AS province_code,
                province_name_th,
                CAST(population AS BIGINT)     AS population
            FROM read_csv_auto('{POPULATION_ALL_YEARS}')
            WHERE CAST(year_ce AS INTEGER) BETWEEN {min(YEARS)} AND {max(YEARS)};
        """)
        n_all = con.execute(
            "SELECT COUNT(*) FROM stg_population_all_years").fetchone()[0]
        print(f"สร้าง stg_population_all_years: {n_all} แถว "
              f"({min(YEARS)}-{max(YEARS)})")

    # ---------- 3) ตรวจคุณภาพ ----------
    print("\n=== ตรวจคุณภาพข้อมูลประชากร ===")
    dq = con.execute("""
        SELECT
            COUNT(*)                                        AS provinces,
            COUNT(*) FILTER (WHERE population IS NULL)      AS null_population,
            COUNT(*) FILTER (WHERE population <= 0)         AS invalid_population,
            MIN(population)                                 AS min_pop,
            MAX(population)                                 AS max_pop,
            SUM(population)                                 AS total_pop
        FROM stg_population;
    """).df()
    print(dq.to_string(index=False))

    if n != 77:
        print(f"\n[เตือน] ได้ {n} จังหวัด ไม่ใช่ 77 — ตรวจไฟล์ต้นทาง")

    # ประชากรไทยอยู่ราว 65-67 ล้านคน ถ้าหลุดช่วงนี้แปลว่าอ่านไฟล์ผิด
    if not (60_000_000 <= total <= 70_000_000):
        print(f"\n[เตือน] ประชากรรวม {total:,} อยู่นอกช่วงที่คาด (60-70 ล้าน)")

    # ---------- 4) ตรวจว่าจับคู่กับข้อมูลผู้ป่วยได้ครบ ----------
    # ถ้า province_code ไม่ตรงกัน DIM_PROVINCE.population จะเป็น NULL แบบเงียบ ๆ
    unmatched = con.execute("""
        SELECT COUNT(*) FROM (
            SELECT DISTINCT province_code FROM stg_disease_monthly
        ) d
        LEFT JOIN stg_population p USING (province_code)
        WHERE p.province_code IS NULL;
    """).fetchone()[0]
    print(f"\nจังหวัดในข้อมูลผู้ป่วยที่จับคู่ประชากรไม่ได้: {unmatched}")
    if unmatched:
        print(con.execute("""
            SELECT DISTINCT d.province_code, d.province_name
            FROM stg_disease_monthly d
            LEFT JOIN stg_population p ON p.province_code = d.province_code
            WHERE p.province_code IS NULL ORDER BY 1;
        """).df().to_string(index=False))

    print("\n=== 5 จังหวัดที่ประชากรมากที่สุด ===")
    print(con.execute("""
        SELECT province_name_th, population FROM stg_population
        ORDER BY population DESC LIMIT 5;
    """).df().to_string(index=False))

    con.close()
    print(f"\nบันทึกที่ {DW_PATH}")


if __name__ == "__main__":
    main()
