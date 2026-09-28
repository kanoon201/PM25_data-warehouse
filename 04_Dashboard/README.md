# คู่มือใช้งาน `dw.duckdb` สำหรับทำ Dashboard

เอกสารนี้สำหรับคนที่ได้รับ **ไฟล์ `dw.duckdb` เพียงไฟล์เดียว** และต้องทำ Dashboard
ไม่ต้องมีไฟล์ดิบ ไม่ต้องรัน ETL — ข้อมูลทั้งหมดอยู่ในไฟล์นี้แล้ว

**โครงการ:** วิเคราะห์ความสัมพันธ์ระหว่างฝุ่น PM2.5 กับผู้ป่วยโรคระบบทางเดินหายใจ
**ขอบเขต:** ปี 2022–2025 · 51 จังหวัดที่มีสถานีวัดฝุ่น (54 สถานี) · ผู้ป่วยครบ 77 จังหวัด (11,609 โรงพยาบาล)

---

## 1. ติดตั้ง (ครั้งเดียว)

```bash
pip install duckdb pandas streamlit plotly
```

แค่ 4 ตัวนี้พอ **ไม่ต้องใช้ `requirements.txt` ของ ETL** ซึ่งมี 23 แพ็กเกจ
(awscli, boto3, requests …) ที่เป็นของขั้นดาวน์โหลดข้อมูล ไม่เกี่ยวกับการอ่าน warehouse

---

## 2. เปิดไฟล์

```python
import duckdb

con = duckdb.connect("dw.duckdb", read_only=True)
con.execute("SET TimeZone='Asia/Bangkok'")
```

**สองบรรทัดนี้สำคัญมาก**

| | ทำไม |
|---|---|
| `read_only=True` | ถ้าไม่ใส่ เปิดหลายแท็บหรือหลายคนพร้อมกันจะล็อกไฟล์ และเสี่ยงเขียนทับข้อมูล |
| `SET TimeZone` | ถ้าไม่ใส่ ค่าที่ได้จะเปลี่ยนตามโซนเวลาของเครื่องที่รัน ทำให้ผลไม่ตรงกัน |

---

## 3. สำรวจก่อนใช้

```python
con.execute("SHOW TABLES").df()                        # มี 20 ตาราง
con.execute("DESCRIBE AGG_PM25_DISEASE_MONTHLY").df()  # ดูคอลัมน์
con.execute("SELECT * FROM DIM_PROVINCE LIMIT 5").df()
```

หรือดูเร็ว ๆ ใน terminal โดยไม่ต้องเขียน Python:

```bash
duckdb dw.duckdb -readonly
```

---

## 4. ตารางที่ต้องรู้ — เริ่มที่ 3 ตัวนี้พอ

### ⭐ `AGG_PM25_DISEASE_MONTHLY` — เริ่มที่นี่

**29,333 แถว** · grain = 1 จังหวัด × 1 เดือน × 1 กลุ่มโรคย่อย

เป็นตารางเดียวที่**ฝุ่นกับผู้ป่วยอยู่แถวเดียวกันแล้ว** ไม่ต้อง join เอง

| คอลัมน์ | ความหมาย |
|---|---|
| `month_key` | เดือน รูปแบบ `YYYYMM` เช่น `202403` |
| `province_key`, `disease_key` | FK ไป dimension |
| `visit_count` | จำนวนครั้งรับบริการ |
| `visits_per_100k` | **อัตราต่อประชากรแสนคน — ใช้ตัวนี้เวลาเทียบข้ามจังหวัด** |
| `avg_pm25`, `max_pm25` | ระดับฝุ่นของจังหวัดในเดือนนั้น |
| `exceedance_days_th` / `_who` | จำนวนวันเกินมาตรฐานไทย (37.5) / WHO (15) |
| `days_with_data` | **มีข้อมูลฝุ่นกี่วันในเดือนนั้น — ใช้กรองคุณภาพ** |
| `avg_pm25_lag1`, `avg_pm25_lag2` | ค่าฝุ่นของ 1 และ 2 เดือนก่อนหน้า (ใช้วิเคราะห์ lag) |
| `avg_stations_per_day` | เฉลี่ยมีกี่สถานีรายงานต่อวัน |

### `FACT_AIR_QUALITY_DAILY` — เมื่อต้องการรายวัน

**35,316 แถว** · grain = 1 สถานี × 1 วัน

ใช้ตอบคำถามเรื่องสภาพอากาศ เพราะความชื้น/ลม/ฝนเปลี่ยนทุกวัน ข้อมูลรายเดือนตอบไม่ได้

### `FACT_DISEASE_MONTHLY` — เมื่อต้องเจาะระดับโรงพยาบาล

**1,751,728 แถว** · grain = 1 โรงพยาบาล × 1 เดือน × 1 กลุ่มโรคย่อย

ใช้ทำ drill-down จังหวัด → โรงพยาบาล → กลุ่มโรค

### Dimension 6 ตาราง

| ตาราง | แถว | คอลัมน์ที่ใช้บ่อย |
|---|---|---|
| `DIM_DATE` | 3,652 | `month_name_th`, `season_th`, `is_haze_season`, `year_be` |
| `DIM_PROVINCE` | 77 | `province_name_th/en`, `region_th`, `population`, `has_air_data` |
| `DIM_STATION` | 54 | `station_name`, `pollution_source_type` |
| `DIM_HOSPITAL` | 11,609 | `hospcode`, `district_name_th/en` |
| `DIM_DISEASE_GROUP` | 13 | `disease_name_en`, `is_respiratory`, `related_icd10_example` |
| `DIM_WEATHER` | 50 | `temp_band`, `humidity_band`, `wind_band`, `has_rain` |

---

## 5. ⚠️ กับดัก 5 ข้อ — อ่านก่อนเขียนกราฟ

### ห้าม `SUM(avg_pm25)`
เป็นค่าเฉลี่ย ต้องใช้ `AVG()` เท่านั้น การบวกค่าเฉลี่ยไม่มีความหมายทางสถิติ

### ห้าม `SUM(is_exceedance_th)` จาก `FACT_AIR_QUALITY_DAILY`
กรุงเทพฯ มี 3 สถานี สมุทรสาครมี 2 สถานี ถ้า SUM ตรง ๆ จะ**นับซ้ำ** —
เคยได้ 46 วันเกินมาตรฐานในเดือนที่มี 31 วัน ซึ่งเป็นไปไม่ได้

✅ ให้ใช้ `exceedance_days_th` จาก `AGG_PM25_DISEASE_MONTHLY` ที่คำนวณถูกแล้ว

### 🔴 ห้าม `SUM(exceedance_days_th)` จาก `AGG_PM25_DISEASE_MONTHLY` ตรง ๆ เช่นกัน
กับดักที่พลาดง่ายที่สุด — grain ของ `AGG` คือ **จังหวัด × เดือน × กลุ่มโรค**
คอลัมน์ฝั่งฝุ่นทุกตัว (`avg_pm25`, `exceedance_days_th`, `days_with_data`,
`avg_pm25_lag1/2`, `max_pm25`) จึงถูก**เขียนซ้ำเหมือนกัน 13 แถว** ในจังหวัด-เดือนเดียวกัน

```sql
-- กรุงเทพฯ ม.ค. 2567: exceedance_days_th = 15 ปรากฏ 13 แถว (กลุ่มโรคละแถว)
SELECT disease_key, exceedance_days_th FROM AGG_PM25_DISEASE_MONTHLY
WHERE month_key = 202401 AND province_key = 1;
```

❌ `SUM(exceedance_days_th)` → 195 วัน ในเดือนที่มี 31 วัน (**เกินจริง 13 เท่า**)
`AVG(avg_pm25)` ไม่พังเพราะค่าเท่ากันหมด แต่ `SUM` ของอะไรก็ตามฝั่งฝุ่นพังทั้งหมด

✅ ต้องยุบเป็นระดับจังหวัด-เดือนก่อนเสมอ:
```sql
WITH pm AS (
    SELECT province_key, month_key,
           MAX(avg_pm25)           AS avg_pm25,
           MAX(exceedance_days_th) AS exceedance_days_th,
           MAX(days_with_data)     AS days_with_data
    FROM AGG_PM25_DISEASE_MONTHLY
    GROUP BY 1, 2                    -- MAX ได้เพราะค่าซ้ำกันอยู่แล้ว
)
SELECT SUM(exceedance_days_th) FROM pm;
```
ดูตัวอย่างที่ทำถูกแล้วได้ใน `queries.py` → CTE ชื่อ `pm` ในฟังก์ชัน `base_cte()`

### กรอง `days_with_data >= 20`
เดือนที่มีข้อมูลฝุ่นไม่ถึง 20 วันไม่ควรนำมาเปรียบเทียบ
จาก 1,982 จังหวัด-เดือน มีเพียง **915** ที่ผ่านเกณฑ์นี้

### ใช้ `visits_per_100k` ไม่ใช่ `visit_count` เวลาเทียบข้ามจังหวัด
นครราชสีมามีประชากร 2.6 ล้านคน ระนองมี 1.9 แสนคน — ยอดดิบไม่มีความหมาย

---

## 6. Query ตัวอย่างที่รันได้ทันที

**ก) ฝุ่นเฉลี่ยรายเดือน 12 เดือน**
```sql
SELECT d.month, d.month_name_th, ROUND(AVG(f.avg_pm25),1) AS pm25
FROM FACT_AIR_QUALITY_DAILY f
JOIN DIM_DATE d USING (date_key)
GROUP BY 1,2 ORDER BY 1;
```
ผลที่ควรได้: พีคเดือน มี.ค. **36.3** ต่ำสุดเดือน ก.ย. **11.4**

**ข) เทียบจังหวัด — อัตราผู้ป่วยต่อแสนคน**
```sql
SELECT p.province_name_th, p.region_th,
       ROUND(SUM(a.visits_per_100k),0) AS rate,
       ROUND(AVG(a.avg_pm25),1) AS pm25
FROM AGG_PM25_DISEASE_MONTHLY a
JOIN DIM_PROVINCE p USING (province_key)
JOIN DIM_DISEASE_GROUP d USING (disease_key)
WHERE d.is_respiratory
GROUP BY 1,2 ORDER BY 3 DESC;
```

**ค) สภาพอากาศกับระดับฝุ่น (ต้องใช้ fact รายวัน)**
```sql
SELECT w.humidity_band, COUNT(*) AS n_days,
       ROUND(AVG(f.avg_pm25),1) AS pm25
FROM FACT_AIR_QUALITY_DAILY f
JOIN DIM_WEATHER w USING (weather_key)
GROUP BY 1 ORDER BY 3 DESC;
```
ผลที่ควรได้: แห้ง <60% → **45.3** · ชื้น >75% → **15.9**

**ง) ฤดูฝุ่นเทียบช่วงอื่น**
```sql
SELECT d.is_haze_season, COUNT(*) AS n_days,
       ROUND(AVG(f.avg_pm25),1) AS pm25
FROM FACT_AIR_QUALITY_DAILY f
JOIN DIM_DATE d USING (date_key)
GROUP BY 1;
```
ผลที่ควรได้: ฤดูฝุ่น **33.7** เทียบช่วงอื่น **15.5**

**จ) Drill-down จังหวัด → โรงพยาบาล → กลุ่มโรค**
```sql
SELECT h.hospcode, h.district_name_th, dg.disease_name_en,
       SUM(f.visit_count) AS visits
FROM FACT_DISEASE_MONTHLY f
JOIN DIM_HOSPITAL h USING (hospital_key)
JOIN DIM_DISEASE_GROUP dg USING (disease_key)
JOIN DIM_PROVINCE p ON p.province_key = f.province_key
WHERE p.province_name_th = 'เชียงใหม่' AND dg.is_respiratory
GROUP BY 1,2,3 ORDER BY 4 DESC LIMIT 20;
```

**ฉ) เทียบกลุ่มควบคุม — ต้องใช้ค่าเฉลี่ยไม่ใช่ผลรวม**
```sql
WITH b AS (
  SELECT dg.disease_group_name_th AS grp, a.province_key, a.month_key,
         ANY_VALUE(a.avg_pm25) AS pm, SUM(a.visit_count) AS v
  FROM AGG_PM25_DISEASE_MONTHLY a
  JOIN DIM_DISEASE_GROUP dg USING (disease_key)
  WHERE a.days_with_data >= 20
  GROUP BY 1,2,3
)
SELECT grp,
       ROUND(AVG(v) FILTER (WHERE pm > 37.5),0) AS ฝุ่นสูง,
       ROUND(AVG(v) FILTER (WHERE pm <= 15),0)  AS ฝุ่นต่ำ
FROM b GROUP BY 1;
```
⚠️ ต้องใช้ `AVG` ไม่ใช่ `SUM` เพราะเดือนฝุ่นสูงมีจำนวนน้อยกว่าเดือนฝุ่นต่ำ (164 vs 233)
ถ้าใช้ `SUM` จะสรุปผิดว่าฝุ่นสูงมีผู้ป่วยน้อยกว่า

---

## 7. Dashboard พร้อมใช้งาน

โครงการมี Dashboard เขียนเสร็จแล้ว ไม่ต้องเขียนใหม่ — มี 2 ไฟล์

| ไฟล์ | หน้าที่ |
|---|---|
| `app.py` | ส่วนติดต่อผู้ใช้ ตัวกรอง และการวาดกราฟ 14 รูป |
| `queries.py` | SQL ทั้งหมด แยกออกมาเพื่อให้ตรวจตรรกะการคำนวณได้โดยไม่ต้องอ่านโค้ด UI |

### วิธีรัน

```bash
pip install -r requirements.txt
streamlit run app.py
```

เปิดที่ `http://localhost:8501`

**ถ้ามีแค่ไฟล์ `dw.duckdb`** วางไว้ในโฟลเดอร์เดียวกับ `app.py` ได้เลย —
`queries.find_warehouse()` จะค้นหาให้เอง 4 ตำแหน่ง หรือกำหนดเองด้วย

```bash
DW_PATH=/path/to/dw.duckdb streamlit run app.py
```

### สิ่งที่อยู่ในนั้น

**แท็บ 1–7 ตรงกับ Business Questions ข้อ 1–7 ใน `Business Requirements.pdf` หัวข้อ 1.3 ตามลำดับ**

| แท็บ | คำถามใน PDF | กราฟ |
|---|---|---|
| BQ1 ความสัมพันธ์ | PM2.5 รายเดือนสัมพันธ์กับผู้ป่วยอย่างไร | ① อนุกรมเวลา 2 แกน ② สหสัมพันธ์รายภาค |
| BQ2 ฤดูกาล & ฤดูฝุ่น | ฤดูฝุ่น ธ.ค.–เม.ย. ต่างจากช่วงอื่นเพียงใด | ③ รายเดือน (ไฮไลต์ฤดูฝุ่น) ④ ฤดูฝุ่น vs นอกฤดู ⑤ อัตราส่วนรายภาค |
| BQ3 แหล่งกำเนิดฝุ่น | แหล่งกำเนิดใดสัมพันธ์กับผู้ป่วยสุด ภาคใดเสี่ยงสุด | ⑥ ความรุนแรงตามแหล่งกำเนิด ⑦ สหสัมพันธ์ตามแหล่งกำเนิด ⑧ heatmap ภาค × แหล่งกำเนิด ⑨ แผนที่ 54 สถานี |
| BQ4 กลุ่มควบคุม | ทางเดินหายใจเพิ่มชัดกว่ากลุ่มควบคุมจริงไหม | ⑩ อัตราส่วนฝุ่นสูง÷ฝุ่นต่ำ ⑪ สหสัมพันธ์รายกลุ่มโรค |
| BQ5 สภาพอากาศ | ลม ความชื้น ฝน แบบใดฝุ่นสูงสุด | ⑫ heatmap ความชื้น × ลม ⑬ แยกตามปัจจัย |
| BQ6 ระยะหน่วง | ผู้ป่วยตามหลังฝุ่นกี่เดือน | ⑭ สหสัมพันธ์ lag 0–2 เดือน ⑮ แนวโน้มรายปี |
| BQ7 Drill-down | โรงพยาบาลใดควรได้ทรัพยากรเพิ่ม | ⑯ อันดับความเสี่ยงจังหวัด ⑰ scatter 2 แกน ⑱ โรงพยาบาลในจังหวัด ⑲ กลุ่มโรคของ รพ. ⑳ รายเดือนของ รพ. |
| ✅ คุณภาพข้อมูล | เชื่อถือได้แค่ไหน | ㉑ coverage รายจังหวัด ㉒ heatmap ความครบถ้วน |

**Measure ทั้ง 5 ตัวในหัวข้อ 1.4 ของ PDF** — M1–M4 อยู่บน KPI แถวบน (เห็นทุกแท็บ)
ส่วน M5 Lagged PM2.5 อยู่ในแท็บ BQ6 ซึ่งเป็นคำถามที่ใช้ measure นั้นโดยตรง
และ `coverage_ratio` แสดงเป็น KPI ตัวที่ 5 ตาม "หมายเหตุคุณภาพข้อมูล" ท้ายหัวข้อ 1.4

**ตัวกรอง** — ช่วงปี · ภาค · จังหวัด · กลุ่มโรคย่อย (มีผลกับทุกแท็บพร้อมกัน)
บวก drill-down 2 ชั้นในแท็บ BQ7 (เลือกจังหวัด → เลือกโรงพยาบาล)

### ข้อควรรู้ 2 ข้อถ้าจะแก้โค้ด

1. **`base_cte()` ใน `queries.py` คือหัวใจ** — ประกาศ CTE 3 ตัว (`base`, `pm`, `vis`)
   ที่ยุบ grain ให้ถูกต้องแล้ว ถ้าเพิ่ม query ใหม่ให้ต่อยอดจากตรงนี้ อย่าเขียน SQL
   ยิงตรงไปที่ `AGG_PM25_DISEASE_MONTHLY` เพราะจะตกกับดักข้อ 3 ในหัวข้อ 5
2. **`st.cache_data` สร้างกุญแจแคชจากชื่อเต็มของฟังก์ชัน** — ห้ามประกาศฟังก์ชันที่ติด
   `@st.cache_data` ไว้ข้างในเดคอเรเตอร์หรือลูป เพราะทุกตัวจะได้ `__qualname__`
   เหมือนกันแล้วใช้แคชร่วมกันจนคืนผลผิดตาราง (บั๊กนี้เคยเกิดจริงตอนพัฒนา)
   ในโค้ดจึงมีฟังก์ชันแคชตัวเดียวคือ `_run(fn_name, key, args)` แล้วส่งชื่อ query เป็นพารามิเตอร์

---

## 8. สิ่งที่ข้อกำหนดของวิชาบังคับ

| ต้องมี | จำนวนขั้นต่ำ | ที่ทำได้ | อยู่ที่ |
|---|---|---|---|
| KPI สรุป Business Performance | 3 | **4** | แถวบนสุด ทุกแท็บเห็นเหมือนกัน |
| กราฟ | 5 | **14** | ทั้ง 8 แท็บ |
| กราฟตามช่วงเวลา | 1 | **3** | ① อนุกรมเวลารายเดือน ③ รายเดือนเฉลี่ย ⑪ รายปี |
| กราฟเปรียบเทียบ | 1 | **6** | ② รายภาค ④ อันดับจังหวัด ⑦ รายกลุ่มโรค ⑩ รายปัจจัยอากาศ ⑫ ตามช่วงฝุ่น ⑬ รายจังหวัด |
| Filter / Interactive Control | 2 | **4** | ช่วงปี · ภาค · จังหวัด · กลุ่มโรค (+ ตัวเลือกปัจจัยในแท็บ BQ5) |
| Insight + ข้อเสนอแนะ | 5 | **8** | กล่องสรุปท้ายแต่ละแท็บ |

**ทุกกราฟต้องตอบ Business Question ที่กำหนดไว้** และภาพในรายงานต้องอ่านชื่อกราฟ แกน
และตัวเลขออกได้ชัดเจน

💡 **แนะนำ:** แสดง `days_with_data` หรือจำนวน n กำกับทุกกราฟ เพราะข้อมูลมีช่วงขาดจริง
(ขอนแก่นมีเดือนที่ใช้ได้เพียง 6 จาก 48 เดือน) การแสดงความโปร่งใสนี้ได้คะแนนพิเศษ

---

## 9. ตัวเลขไว้ตรวจว่าต่อไฟล์ถูกตัว

ถ้า query แล้วได้เลขตรงนี้ แปลว่าใช้ไฟล์ถูกและเขียน SQL ถูก

| ตรวจ | ค่าที่ควรได้ |
|---|---|
| จำนวนตารางทั้งหมด | 20 |
| `SELECT COUNT(*) FROM AGG_PM25_DISEASE_MONTHLY` | 29,333 |
| `SELECT COUNT(*) FROM FACT_AIR_QUALITY_DAILY` | 35,316 |
| `SELECT COUNT(*) FROM DIM_STATION` | 54 |
| `SELECT SUM(visit_count) FROM FACT_DISEASE_MONTHLY` | 45,330,136 |
| PM2.5 เฉลี่ยทั้งหมด | 24.8 µg/m³ |

---

## 10. ถ้าติดปัญหา

| อาการ | สาเหตุ / วิธีแก้ |
|---|---|
| `IO Error: database is locked` | ลืมใส่ `read_only=True` หรือเปิดค้างไว้อีกหน้าต่าง |
| ตัวเลขไม่ตรงกับเพื่อน | ลืม `SET TimeZone='Asia/Bangkok'` |
| จำนวนวันเกินมาตรฐานมากผิดปกติ | ใช้ `SUM(is_exceedance_th)` จาก fact — ให้ใช้จาก `AGG` แทน |
| กราฟเทียบจังหวัดดูแปลก | ใช้ `visit_count` แทน `visits_per_100k` |
| บางจังหวัดข้อมูลหาย | ปกติ — ดู `days_with_data` ประกอบ ไม่ใช่ทุกเดือนมีข้อมูลฝุ่นครบ |

---

*ไฟล์ `dw.duckdb` มี 20 ตาราง 87 MB ผ่านการตรวจสอบความถูกต้อง 21 ข้อ
(referential integrity, grain uniqueness, reconciliation, ความสมเหตุสมผลเชิงกายภาพ)
รายละเอียดการออกแบบทั้งหมดอยู่ใน `Star_Schema_Design.md`*
