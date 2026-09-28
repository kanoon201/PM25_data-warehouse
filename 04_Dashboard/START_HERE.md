# เริ่มตรงนี้ — เปิด Dashboard ใน 3 คำสั่ง

โฟลเดอร์นี้มีโปรแกรมครบแล้ว ส่วนคลังข้อมูลอยู่ที่ `03_Data_Warehouse/dw.duckdb` ไม่ต้องดาวน์โหลดข้อมูลเพิ่ม

## macOS / Linux

```bash
cd 04_Dashboard
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## Windows (PowerShell)

```powershell
cd 04_Dashboard
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
```

เบราว์เซอร์จะเปิดเองที่ `http://localhost:8501`
ถ้าไม่เปิด ให้พิมพ์ที่อยู่นั้นในเบราว์เซอร์เอง

**หยุดโปรแกรม:** กด `Ctrl + C` ในหน้าต่างคำสั่ง

---

## มีอะไรในโฟลเดอร์นี้

| ไฟล์ | คืออะไร |
|---|---|
| `app.py` | หน้าจอ Dashboard — ตัวกรอง 22 กราฟ 8 แท็บ |
| `queries.py` | SQL ทั้งหมด แยกไว้ต่างหากเพื่อให้ตรวจตรรกะได้ง่าย |
| `../03_Data_Warehouse/dw.duckdb` | คลังข้อมูล 84 MB — 2 Fact + 6 Dimension + 1 Aggregate (อยู่คนละโฟลเดอร์ `app.py` หาเจอเอง) |
| `requirements.txt` | รายการแพ็กเกจที่ต้องติดตั้ง |
| `README.md` | คู่มือฉบับเต็ม — โครงสร้างตาราง กับดักที่ต้องระวัง query ตัวอย่าง |

## ต้องใช้อะไรบ้าง

**Python 3.9 ขึ้นไป** อย่างเดียว (ทดสอบบน 3.13)
ไม่ต้องติดตั้งฐานข้อมูล ไม่ต้องต่ออินเทอร์เน็ตขณะใช้งาน
ยกเว้นแผนที่ในแท็บ BQ3 ที่ต้องใช้เน็ตโหลดพื้นหลังแผนที่ — ถ้าไม่มีเน็ตจะแสดงเป็นตารางแทนโดยอัตโนมัติ

## ถ้าติดปัญหา

| อาการ | วิธีแก้ |
|---|---|
| `streamlit: command not found` | ยังไม่ได้ activate venv — รัน `source .venv/bin/activate` ก่อน |
| `ModuleNotFoundError: No module named 'duckdb'` | ยังไม่ได้ `pip install -r requirements.txt` |
| `ไม่พบไฟล์ dw.duckdb` | ต้องมีโฟลเดอร์ `03_Data_Warehouse/` อยู่ระดับเดียวกับ `04_Dashboard/` หรือกำหนด `DW_PATH` ชี้ไปที่ไฟล์เอง |
| พอร์ต 8501 ถูกใช้อยู่ | `streamlit run app.py --server.port 8502` |
| กราฟว่างเปล่า | ตัวกรองใน sidebar แคบเกินไป — กดล้างจังหวัด/ปี ที่เลือกไว้ |

## ตัวเลขไว้ตรวจว่าเปิดถูกไฟล์

เปิดมาแล้ว KPI แถวบนสุดต้องขึ้นแบบนี้ (ตัวกรองค่าเริ่มต้น ปี 2022–2025)

| KPI | ค่าที่ต้องได้ |
|---|---|
| M1 · ครั้งรับบริการ | 15,537,343 |
| M2 · PM2.5 เฉลี่ย | 25.8 |
| M3 · วันเกินมาตรฐานไทย | 6,049 |
| M4 · ต่อประชากรแสนคน | 30,548 |
| ความครบถ้วนข้อมูลฝุ่น | 93.2% |

ถ้าตัวเลขไม่ตรง แปลว่าได้ไฟล์ `dw.duckdb` คนละเวอร์ชัน
