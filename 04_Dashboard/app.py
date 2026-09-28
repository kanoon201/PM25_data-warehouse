"""
app.py — Dashboard วิเคราะห์ความสัมพันธ์ระหว่าง PM2.5 กับผู้ป่วยโรคระบบทางเดินหายใจ

รันด้วย:
    streamlit run 04_Dashboard/app.py

โครงสร้างของแผงนี้อ้างอิง **Business Requirements.pdf** โดยตรง:
  · แท็บ 1–7 ตรงกับ Business Questions ข้อ 1–7 ในหัวข้อ 1.3 ของเอกสาร ตามลำดับ
  · KPI แถวบนคือ Measure ข้อ 1–4 ในหัวข้อ 1.4
  · Measure ข้อ 5 (Lagged PM2.5) อยู่ในแท็บ BQ6 ซึ่งเป็นคำถามที่ใช้ measure นั้นโดยตรง
  · coverage_ratio แสดงกำกับตลอด ตาม "หมายเหตุคุณภาพข้อมูล" ท้ายหัวข้อ 1.4

ไฟล์นี้ทำหน้าที่ "วาด" อย่างเดียว SQL ทั้งหมดอยู่ใน queries.py
เพื่อให้ตรวจสอบตรรกะการคำนวณได้ที่เดียวโดยไม่ต้องอ่านโค้ด UI
"""
from __future__ import annotations

import importlib.util

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

import queries as Q

# ═════════════════════════════════════════════════════════════════════
# ตั้งค่าหน้า
# ═════════════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="PM2.5 กับผู้ป่วยทางเดินหายใจ",
    page_icon="🫁",
    layout="wide",
)

PM_COLOR = "#B45309"   # สีน้ำตาลส้ม = ฝุ่น
VIS_COLOR = "#1D4ED8"  # สีน้ำเงิน   = ผู้ป่วย
CTRL_COLOR = "#9CA3AF"  # สีเทา      = กลุ่มควบคุม

SOURCE_COLORS = {
    "การเผาในที่โล่ง": "#DC2626",
    "อุตสาหกรรม": "#7C3AED",
    "จราจร": "#D97706",
    "ผสม (เมือง+เกษตร)": "#0891B2",
}

# เส้นแนวโน้ม OLS ของ Plotly ต้องใช้ statsmodels — ทำให้เป็น dependency ทางเลือก
# เพื่อให้เพื่อนที่ลงแค่ streamlit + plotly + duckdb ก็ยังเปิด Dashboard ได้
HAS_STATSMODELS = importlib.util.find_spec("statsmodels") is not None

PLOT_LAYOUT = dict(
    margin=dict(l=10, r=10, t=50, b=10),
    hovermode="x unified",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
)
BARE_LAYOUT = dict(margin=dict(l=10, r=10, t=50, b=10))


# ═════════════════════════════════════════════════════════════════════
# การเชื่อมต่อและแคช
# ═════════════════════════════════════════════════════════════════════
@st.cache_resource
def get_con():
    return Q.connect()


@st.cache_data(show_spinner=False)
def _opts():
    return Q.filter_options(get_con())


@st.cache_data(show_spinner=False)
def _run(fn_name: str, key: tuple, args: tuple = ()):
    """ตัวรัน query ตัวเดียวที่ถูกแคช

    ต้องมีฟังก์ชันแคชแค่ตัวเดียวและส่ง `fn_name` เป็นพารามิเตอร์
    เพราะ st.cache_data สร้างกุญแจจาก **ชื่อเต็มของฟังก์ชัน** ถ้าประกาศ
    ฟังก์ชันแคชซ้อนในลูป/เดคอเรเตอร์ ทุกตัวจะได้ __qualname__ เหมือนกัน
    แล้ว query คนละตัวจะใช้แคชร่วมกันจนได้ผลลัพธ์ผิดตัว
    """
    return getattr(Q, fn_name)(get_con(), _rebuild(key), *args)


def cached(fn):
    """ครอบ query ให้เรียกด้วย Filters ได้ตรง ๆ
    (Filters ไม่ hashable จึงแปลงเป็น tuple ผ่าน .key() ก่อนส่งเข้าแคช)"""
    def wrapper(f: Q.Filters, *args):
        return _run(fn.__name__, f.key(), tuple(args))

    wrapper.__name__ = fn.__name__
    return wrapper


def _rebuild(key):
    ymin, ymax, provs, dis = key
    return Q.Filters(ymin, ymax, list(provs), list(dis))


q_kpis          = cached(Q.kpis)
q_monthly       = cached(Q.monthly_trend)
q_corr_lags     = cached(Q.correlation_lags)
q_corr_region   = cached(Q.correlation_by_region)
q_season        = cached(Q.seasonality)
q_haze          = cached(Q.haze_season_comparison)
q_haze_region   = cached(Q.haze_by_region)
q_source        = cached(Q.source_type_analysis)
q_source_region = cached(Q.source_type_by_region)
q_stations      = cached(Q.station_map)
q_control       = cached(Q.control_group_high_low)
q_subgroup      = cached(Q.disease_subgroup_analysis)
q_weather       = cached(Q.weather_vs_pm25)
q_heatmap       = cached(Q.weather_heatmap)
q_yearly        = cached(Q.yearly_trend)
q_bands         = cached(Q.pm25_bands)
q_prov_risk     = cached(Q.province_risk)
q_hosp_rank     = cached(Q.hospital_ranking)
q_hosp_disease  = cached(Q.hospital_disease_breakdown)
q_hosp_monthly  = cached(Q.hospital_monthly)
q_coverage      = cached(Q.coverage_matrix)
q_cov_stats     = cached(Q.coverage_stats)
q_cov_prov      = cached(Q.coverage_by_province)
q_dq            = cached(Q.data_quality_notes)


# ═════════════════════════════════════════════════════════════════════
# Sidebar — ตัวกรอง
# ═════════════════════════════════════════════════════════════════════
def build_filters() -> Q.Filters:
    o = _opts()
    st.sidebar.title("🫁 ตัวกรองข้อมูล")

    # ── 1. ช่วงเวลา ──
    ymin, ymax = int(o["year_min"]), int(o["year_max"])
    if ymin == ymax:
        years = (ymin, ymax)
        st.sidebar.caption(f"ข้อมูลมีเฉพาะปี {ymin}")
    else:
        years = st.sidebar.slider(
            "ช่วงปี (ค.ศ.)", ymin, ymax, (ymin, ymax), step=1,
            help=f"เทียบ พ.ศ. {ymin + 543}–{ymax + 543}",
        )

    # ── 2. พื้นที่ ──
    # ขอบเขตคงที่ที่ 51 จังหวัดที่มีสถานีตรวจวัดฝุ่น เพราะ AGG_PM25_DISEASE_MONTHLY
    # ถูกสร้างด้วย WHERE p.has_air_data อยู่แล้ว การเปิดให้เลือก 77 จังหวัดจะเป็น
    # ตัวควบคุมหลอกที่กดแล้วไม่มีอะไรเปลี่ยน
    st.sidebar.markdown("---")
    prov_df = o["provinces"]
    pool = prov_df[prov_df["has_air_data"]]
    n_all, n_air = len(prov_df), len(pool)

    regions = st.sidebar.multiselect(
        "ภาค", [r for r in Q.REGION_ORDER if r in set(pool["region_th"])],
        default=[], placeholder="ทุกภาค",
    )
    if regions:
        pool = pool[pool["region_th"].isin(regions)]

    provinces = st.sidebar.multiselect(
        "จังหวัด", sorted(pool["province_name_th"].tolist()),
        default=[], placeholder=f"ทุกจังหวัด ({len(pool)} จังหวัด)",
    )
    # ถ้าเลือกภาคแต่ไม่เจาะจังหวัด ให้ส่งรายชื่อจังหวัดในภาคนั้นเป็นตัวกรองแทน
    if not provinces and regions:
        provinces = pool["province_name_th"].tolist()

    st.sidebar.caption(
        f"ขอบเขตวิเคราะห์คือ **{n_air} จังหวัด** ที่มีสถานีตรวจวัดฝุ่น "
        f"จากทั้งหมด {n_all} จังหวัด  \n"
        f"อีก {n_all - n_air} จังหวัดมีข้อมูลผู้ป่วยครบใน `FACT_DISEASE_MONTHLY` "
        "แต่ไม่มีค่า PM2.5 ให้เทียบ"
    )

    # ── 3. กลุ่มโรค ──
    st.sidebar.markdown("---")
    dis = o["diseases"]
    resp = dis[dis["is_respiratory"]]
    label_map = {
        f'{r.disease_name_en} (กลุ่มย่อย {r.disease_sub_group_id})': int(r.disease_key)
        for r in resp.itertuples()
    }
    picked = st.sidebar.multiselect(
        "กลุ่มโรคย่อย (ทางเดินหายใจ)", list(label_map),
        default=[], placeholder="ทั้ง 7 กลุ่มย่อย",
        help="ค่าเริ่มต้นคือรวมทุกกลุ่มย่อยของโรคทางเดินหายใจ (disease_group_id = 1)",
    )
    disease_keys = ([label_map[p] for p in picked] if picked
                    else resp["disease_key"].astype(int).tolist())

    f = Q.Filters(years[0], years[1], provinces, disease_keys)

    st.sidebar.markdown("---")
    st.sidebar.caption(
        f"📦 คลังข้อมูล: `{Q.find_warehouse().name}`  \n"
        f"เกณฑ์วิเคราะห์: จังหวัด-เดือนต้องมีข้อมูลฝุ่น ≥ {Q.MIN_DAYS_FOR_ANALYSIS} วัน  \n"
        f"มาตรฐานไทย {Q.THAI_STANDARD_PM25} · WHO {Q.WHO_GUIDELINE_PM25} µg/m³"
    )
    return f


# ═════════════════════════════════════════════════════════════════════
# ส่วนหัว + KPI (Measure 1–4 ตามหัวข้อ 1.4 ของเอกสาร)
# ═════════════════════════════════════════════════════════════════════
def render_header(f: Q.Filters):
    st.title("🫁 PM2.5 กับผู้ป่วยโรคระบบทางเดินหายใจ")
    st.caption(
        "คลังข้อมูลขนาดย่อมเพื่อสนับสนุนการตัดสินใจของผู้บริหารโรงพยาบาล · "
        f"ปี {f.year_min}–{f.year_max} (พ.ศ. {f.year_min + 543}–{f.year_max + 543}) · "
        "แท็บ 1–7 ตรงกับ Business Questions ข้อ 1–7"
    )

    k = q_kpis(f)
    cov = q_cov_stats(f)
    c1, c2, c3, c4, c5 = st.columns(5)

    v = k.get("visits") or 0
    c1.metric("M1 · ครั้งรับบริการ", f"{int(v):,}",
              "กลุ่มโรคทางเดินหายใจ", delta_color="off")

    pm = k.get("avg_pm25")
    if pm is not None:
        c2.metric("M2 · PM2.5 เฉลี่ย", f"{pm:,.1f}",
                  f"{pm - Q.THAI_STANDARD_PM25:+.1f} เทียบมาตรฐานไทย",
                  delta_color="inverse")  # ฝุ่นสูง = แย่ ต้องเป็นสีแดง
    else:
        c2.metric("M2 · PM2.5 เฉลี่ย", "—")

    exc = k.get("exc_days_th") or 0
    c3.metric("M3 · วันเกินมาตรฐานไทย", f"{int(exc):,}",
              f"{k.get('exceedance_pct') or 0:.1f}% ของวันที่มีข้อมูล", delta_color="off")

    vp = k.get("visits_per_100k")
    c4.metric("M4 · ต่อประชากรแสนคน", f"{vp:,.0f}" if vp else "—",
              f"{int(k.get('n_provinces') or 0)} จังหวัด", delta_color="off")

    ac = cov.get("avg_coverage")
    c5.metric("ความครบถ้วนข้อมูลฝุ่น", f"{ac * 100:,.1f}%" if ac else "—",
              f"{int(cov.get('n_station_days') or 0):,} สถานี-วัน", delta_color="off")


# ═════════════════════════════════════════════════════════════════════
# BQ1 — PM2.5 รายเดือนสัมพันธ์กับผู้ป่วยทางเดินหายใจอย่างไร
# ═════════════════════════════════════════════════════════════════════
def tab_bq1(f: Q.Filters):
    st.subheader("BQ1 — ระดับ PM2.5 เฉลี่ยรายเดือนสัมพันธ์กับจำนวนผู้ป่วยอย่างไร")
    st.caption("Measure ที่ใช้: M1 ครั้งรับบริการ · M2 ค่าเฉลี่ย PM2.5")

    df = q_monthly(f)
    if df.empty:
        st.warning("ไม่มีข้อมูลตามตัวกรองที่เลือก")
        return

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Scatter(x=df["month_date"], y=df["avg_pm25"], name="PM2.5 (µg/m³)",
                   line=dict(color=PM_COLOR, width=2.5)),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(x=df["month_date"], y=df["visits"], name="ครั้งรับบริการ",
                   line=dict(color=VIS_COLOR, width=2.5, dash="dot")),
        secondary_y=True,
    )
    fig.add_hline(y=Q.THAI_STANDARD_PM25, line_dash="dash", line_color="red",
                  annotation_text=f"มาตรฐานไทย {Q.THAI_STANDARD_PM25}",
                  annotation_position="top left")
    fig.update_yaxes(title_text="PM2.5 (µg/m³)", secondary_y=False, color=PM_COLOR)
    fig.update_yaxes(title_text="ครั้งรับบริการ", secondary_y=True, color=VIS_COLOR)
    fig.update_layout(title="① PM2.5 เฉลี่ยรายเดือน เทียบจำนวนครั้งรับบริการ",
                      height=430, **PLOT_LAYOUT)
    st.plotly_chart(fig, width="stretch")

    left, right = st.columns(2)
    lags = q_corr_lags(f)
    with left:
        st.markdown("**สหสัมพันธ์ที่ระยะหน่วง 0 เดือน (พร้อมกัน)**")
        row = lags[lags["lag_months"] == 0].iloc[0]
        m1, m2, m3 = st.columns(3)
        m1.metric("r ดิบ", f"{row['r_raw']:.3f}")
        m2.metric("r หลังหักฤดูกาล", f"{row['r_deseason']:.3f}")
        m3.metric("จังหวัด-เดือน", f"{int(row['n']):,}")
        st.caption(
            "**r ดิบ** สูงเกินจริงเพราะฤดูหนาวดันทั้งฝุ่นและไข้หวัดขึ้นพร้อมกัน  \n"
            "**r หลังหักฤดูกาล** หักค่าเฉลี่ยของจังหวัด × เดือนปฏิทินออกก่อน "
            "จึงเหลือเฉพาะความผันผวนที่เกินจากปกติของเดือนนั้น — ตัวเลขนี้คือคำตอบที่เชื่อถือได้  \n"
            "ดูการวิเคราะห์ระยะหน่วง 1–2 เดือนต่อได้ที่แท็บ **BQ6**"
        )

    with right:
        reg = q_corr_region(f)
        if reg.empty:
            st.info("เลือกพื้นที่กว้างขึ้นเพื่อดูการแยกรายภาค")
        else:
            fig2 = px.bar(
                reg, x="r_deseason", y="region_th", orientation="h",
                color="r_deseason", color_continuous_scale="RdBu_r",
                range_color=[-0.5, 0.5], text="r_deseason",
                labels={"r_deseason": "r หลังหักฤดูกาล", "region_th": ""},
                title="② สหสัมพันธ์แยกรายภาค",
            )
            fig2.add_vline(x=0, line_color="black", line_width=1)
            fig2.update_traces(textposition="outside")
            fig2.update_layout(height=360, coloraxis_showscale=False, **BARE_LAYOUT)
            st.plotly_chart(fig2, width="stretch")

    st.info(
        "**คำตอบของ BQ1** — ที่ระดับจังหวัด-เดือน **ไม่พบความสัมพันธ์ที่ชัดเจน** "
        "ค่าเฉลี่ยทั้งประเทศใกล้ 0 ไม่ได้แปลว่าฝุ่นไม่มีผลต่อสุขภาพ "
        "แต่แปลว่า *ข้อมูลระดับจังหวัด-เดือนหยาบเกินกว่าจะจับผลได้* "
        "เพราะงานวิจัยพบผลของ PM2.5 ที่ระยะหน่วง 1–7 **วัน** ซึ่งการเฉลี่ยรายเดือนกลบไปหมด  \n"
        "ที่ใช้งานได้จริงคือกราฟ ② — ค่าเฉลี่ยประเทศที่ใกล้ 0 ซ่อนความต่างรายภาคไว้ "
        "เขตสุขภาพจึงต้องวางแผนคนละแบบ ไม่ใช้ตัวเลขระดับประเทศตัวเดียว"
    )


# ═════════════════════════════════════════════════════════════════════
# BQ2 — ฤดูกาลและฤดูฝุ่น ธ.ค.–เม.ย.
# ═════════════════════════════════════════════════════════════════════
def tab_bq2(f: Q.Filters):
    st.subheader("BQ2 — PM2.5 รายเดือน/ฤดูกาลเป็นอย่างไร ฤดูฝุ่น (ธ.ค.–เม.ย.) ต่างจากช่วงอื่นเพียงใด")
    st.caption("Measure ที่ใช้: M2 ค่าเฉลี่ย PM2.5 · M3 วันเกินมาตรฐาน · ใช้ `is_haze_season` จาก DIM_DATE")

    df = q_season(f)
    if df.empty:
        st.warning("ไม่มีข้อมูลตามตัวกรองที่เลือก")
        return

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Bar(x=df["month_name_th"], y=df["avg_pm25"], name="PM2.5 เฉลี่ย",
               marker_color=[PM_COLOR if h else "#D6D3D1" for h in df["is_haze_season"]]),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(x=df["month_name_th"], y=df["avg_visits"], name="ครั้งรับบริการเฉลี่ย",
                   mode="lines+markers", line=dict(color=VIS_COLOR, width=3)),
        secondary_y=True,
    )
    fig.add_hline(y=Q.THAI_STANDARD_PM25, line_dash="dash", line_color="red", secondary_y=False)
    fig.update_yaxes(title_text="PM2.5 (µg/m³)", secondary_y=False, color=PM_COLOR)
    fig.update_yaxes(title_text="ครั้งรับบริการเฉลี่ย", secondary_y=True, color=VIS_COLOR)
    fig.update_layout(title="③ รูปแบบตามฤดูกาล — แท่งสีเข้มคือเดือนในฤดูฝุ่น (ธ.ค.–เม.ย.)",
                      height=430, **PLOT_LAYOUT)
    st.plotly_chart(fig, width="stretch")

    hz = q_haze(f)
    if len(hz) == 2:
        haze = hz[hz["season"].str.startswith("ฤดูฝุ่น")].iloc[0]
        non = hz[hz["season"].str.startswith("นอก")].iloc[0]

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("PM2.5 ฤดูฝุ่น", f"{haze['avg_pm25']:.1f}",
                  f"{haze['avg_pm25'] / non['avg_pm25']:.1f} เท่าของนอกฤดู", delta_color="inverse")
        c2.metric("PM2.5 นอกฤดูฝุ่น", f"{non['avg_pm25']:.1f}", delta_color="off")
        c3.metric("% วันเกินมาตรฐาน ฤดูฝุ่น", f"{haze['exceedance_pct']:.1f}%",
                  f"นอกฤดู {non['exceedance_pct']:.1f}%", delta_color="inverse")
        c4.metric("ครั้งรับบริการเฉลี่ย ฤดูฝุ่น", f"{haze['avg_visits']:,.0f}",
                  f"นอกฤดู {non['avg_visits']:,.0f}", delta_color="off")

        c5, c6 = st.columns(2)
        with c5:
            long = hz.melt(id_vars="season", value_vars=["avg_pm25", "exceedance_pct"],
                           var_name="metric", value_name="value")
            long["metric"] = long["metric"].map({"avg_pm25": "PM2.5 เฉลี่ย (µg/m³)",
                                                 "exceedance_pct": "% วันเกินมาตรฐาน"})
            fig2 = px.bar(long, x="metric", y="value", color="season", barmode="group",
                          text="value", labels={"metric": "", "value": "", "season": ""},
                          color_discrete_map={"ฤดูฝุ่น (ธ.ค.–เม.ย.)": PM_COLOR,
                                              "นอกฤดูฝุ่น (พ.ค.–พ.ย.)": "#78716C"},
                          title="④ ฤดูฝุ่น เทียบ นอกฤดูฝุ่น")
            fig2.update_traces(textposition="outside")
            fig2.update_layout(height=380, legend=dict(orientation="h", y=1.02, x=1,
                                                       xanchor="right"), **BARE_LAYOUT)
            st.plotly_chart(fig2, width="stretch")

        with c6:
            hr = q_haze_region(f)
            if hr.empty:
                st.info("เลือกพื้นที่กว้างขึ้นเพื่อดูรายภาค")
            else:
                fig3 = px.bar(hr.sort_values("ratio"), x="ratio", y="region_th",
                              orientation="h", text="ratio", color="ratio",
                              color_continuous_scale="YlOrRd",
                              labels={"ratio": "PM2.5 ฤดูฝุ่น ÷ นอกฤดูฝุ่น (เท่า)",
                                      "region_th": ""},
                              title="⑤ ฤดูฝุ่นรุนแรงต่างกันแค่ไหนในแต่ละภาค")
                fig3.add_vline(x=1.0, line_dash="dash", line_color="black")
                fig3.update_traces(textposition="outside")
                fig3.update_layout(height=380, coloraxis_showscale=False, **BARE_LAYOUT)
                st.plotly_chart(fig3, width="stretch")

        st.success(
            f"**คำตอบของ BQ2** — ฤดูฝุ่นต่างจากช่วงอื่นอย่างชัดเจนมากในฝั่งมลพิษ: "
            f"PM2.5 สูงกว่า **{haze['avg_pm25'] / non['avg_pm25']:.1f} เท่า** "
            f"({haze['avg_pm25']:.1f} เทียบ {non['avg_pm25']:.1f} µg/m³) และสัดส่วนวันเกินมาตรฐาน "
            f"ต่างกันถึง **{haze['exceedance_pct'] / max(non['exceedance_pct'], 0.1):.0f} เท่า** "
            f"({haze['exceedance_pct']:.1f}% เทียบ {non['exceedance_pct']:.1f}%)  \n"
            f"แต่ฝั่งภาระผู้ป่วย **แทบไม่ต่างกัน** — {haze['avg_visits']:,.0f} เทียบ "
            f"{non['avg_visits']:,.0f} ครั้งต่อจังหวัด-เดือน ซึ่งเป็นผลที่ต้องรายงานตามจริง "
            "และเป็นเหตุผลว่าทำไม BQ4 ต้องใช้กลุ่มควบคุมมายืนยันอีกชั้น"
        )

    st.dataframe(
        df.rename(columns={
            "month": "เดือน", "month_name_th": "ชื่อเดือน", "avg_pm25": "PM2.5 เฉลี่ย",
            "avg_visits": "ครั้งรับบริการเฉลี่ย", "avg_exceedance_days": "วันเกินมาตรฐานเฉลี่ย",
            "is_haze_season": "ฤดูฝุ่น",
        }),
        hide_index=True, width="stretch",
    )

    # เตือนเดือนที่ยอดต่ำผิดปกติ — เป็นปัญหาการรายงานของต้นทาง ไม่ใช่ภาระงานที่ลดลงจริง
    med = df["avg_visits"].median()
    thin = df[df["avg_visits"] < 0.6 * med]
    if not thin.empty and med:
        names = " · ".join(thin["month_name_th"].tolist())
        st.warning(
            f"**ระวังการตีความ: {names}** มียอดต่ำกว่าค่ากลางของปีเกิน 40% "
            "ซึ่งเกิดจาก **การรายงานเข้าระบบ HDC ไม่ครบ** ไม่ใช่ภาระงานที่ลดลงจริง  \n"
            "ตรวจสอบแล้วพบว่าธันวาคม 2567 รายงานเพียง 64,897 ครั้ง เทียบกับพฤศจิกายนเดือนก่อนหน้า "
            "331,302 ครั้ง (ต่างกัน 5 เท่า ทั้งที่ทั้งสองเดือนมีข้อมูลครบ 77 จังหวัด) "
            "เพราะข้อมูลปีงบประมาณถัดไปยังทยอยส่งไม่ครบ  \n"
            "ผลกระทบต่อการวิเคราะห์อยู่ในวงจำกัด — การหักฤดูกาลใน BQ1/BQ6 เทียบภายในเดือนปฏิทินเดียวกัน "
            "จึงหักผลนี้ออกไปแล้ว (ตัดธันวาคมออก r เปลี่ยนจาก 0.012 เป็น 0.015 เท่านั้น) "
            "แต่ **ห้ามใช้กราฟนี้สรุปว่าธันวาคมเป็นเดือนที่ภาระงานเบาที่สุด**"
        )


# ═════════════════════════════════════════════════════════════════════
# BQ3 — แหล่งกำเนิดฝุ่นแบบใดสัมพันธ์กับผู้ป่วยมากที่สุด ภูมิภาคใดเสี่ยงสูงสุด
# ═════════════════════════════════════════════════════════════════════
def tab_bq3(f: Q.Filters):
    st.subheader("BQ3 — แหล่งกำเนิดฝุ่นแบบใดสัมพันธ์กับผู้ป่วยมากที่สุด และภูมิภาคใดเสี่ยงสูงสุด")
    st.caption("ใช้ `pollution_source_type` จาก DIM_STATION · ผู้ใช้หลักคือกรมควบคุมมลพิษและเขตสุขภาพ")

    src = q_source(f)
    if src.empty:
        st.warning("ไม่มีข้อมูลตามตัวกรองที่เลือก")
        return

    c1, c2 = st.columns(2)
    with c1:
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        fig.add_trace(
            go.Bar(x=src["source_type"], y=src["avg_pm25"], name="PM2.5 เฉลี่ย",
                   marker_color=[SOURCE_COLORS.get(s, PM_COLOR) for s in src["source_type"]],
                   text=src["avg_pm25"].map(lambda x: f"{x:.1f}"), textposition="outside"),
            secondary_y=False,
        )
        fig.add_trace(
            go.Scatter(x=src["source_type"], y=src["exceedance_pct"], name="% วันเกินมาตรฐาน",
                       mode="lines+markers", line=dict(color="black", width=2, dash="dot")),
            secondary_y=True,
        )
        fig.update_yaxes(title_text="PM2.5 เฉลี่ย (µg/m³)", secondary_y=False)
        fig.update_yaxes(title_text="% วันเกินมาตรฐาน", secondary_y=True)
        fig.update_layout(title="⑥ ความรุนแรงของฝุ่นแยกตามแหล่งกำเนิด", height=400,
                          legend=dict(orientation="h", y=1.02, x=1, xanchor="right"),
                          **BARE_LAYOUT)
        st.plotly_chart(fig, width="stretch")

    with c2:
        d = src.dropna(subset=["r_deseason"]).sort_values("r_deseason")
        fig2 = px.bar(
            d, x="r_deseason", y="source_type", orientation="h", text="r_deseason",
            color="source_type", color_discrete_map=SOURCE_COLORS,
            labels={"r_deseason": "r หลังหักฤดูกาล (ฝุ่น ↔ ผู้ป่วย)", "source_type": ""},
            title="⑦ แหล่งกำเนิดใดสัมพันธ์กับจำนวนผู้ป่วยมากที่สุด",
        )
        fig2.add_vline(x=0, line_color="black", line_width=1)
        fig2.update_traces(textposition="outside")
        fig2.update_layout(height=400, showlegend=False, **BARE_LAYOUT)
        st.plotly_chart(fig2, width="stretch")

    st.dataframe(
        src.rename(columns={
            "source_type": "แหล่งกำเนิดฝุ่น", "n_provinces": "จำนวนจังหวัด",
            "n_province_months": "จังหวัด-เดือน", "avg_pm25": "PM2.5 เฉลี่ย",
            "exceedance_pct": "% วันเกินมาตรฐาน", "visits": "ครั้งรับบริการ",
            "population": "ประชากรรวม", "visits_per_100k": "ต่อประชากรแสนคน",
            "r_deseason": "r หลังหักฤดูกาล",
        }),
        hide_index=True, width="stretch",
    )

    c3, c4 = st.columns([2, 3])
    with c3:
        sr = q_source_region(f)
        if not sr.empty:
            pivot = sr.pivot(index="region_th", columns="source_type", values="avg_pm25")
            fig3 = px.imshow(
                pivot, text_auto=".1f", aspect="auto", color_continuous_scale="YlOrRd",
                labels=dict(x="แหล่งกำเนิดฝุ่น", y="", color="PM2.5"),
                title="⑧ ภาค × แหล่งกำเนิด — PM2.5 เฉลี่ย",
            )
            fig3.update_layout(height=420, **BARE_LAYOUT)
            st.plotly_chart(fig3, width="stretch")

    with c4:
        stn = q_stations(f)
        if stn.empty:
            st.info("ไม่มีสถานีตรวจวัดในพื้นที่ที่เลือก")
        else:
            try:
                fmap = px.scatter_map(
                    stn, lat="lat", lon="lon", color="pollution_source_type",
                    size="avg_pm25", hover_name="station_name",
                    hover_data={"province_name_th": True, "avg_pm25": ":.1f",
                                "exceedance_pct": ":.1f", "n_days": True,
                                "lat": False, "lon": False},
                    color_discrete_map=SOURCE_COLORS, size_max=20, zoom=4.2,
                    map_style="open-street-map",
                    labels={"pollution_source_type": "แหล่งกำเนิด", "avg_pm25": "PM2.5"},
                    title="⑨ แผนที่สถานีตรวจวัด แยกสีตามแหล่งกำเนิดฝุ่น",
                )
                fmap.update_layout(height=420, legend=dict(orientation="h", y=-0.05),
                                   margin=dict(l=0, r=0, t=40, b=0))
                st.plotly_chart(fmap, width="stretch")
            except Exception as e:  # ถ้าเปิดแผนที่ไม่ได้ (ไม่มีเน็ต) ให้แสดงตารางแทน
                st.warning(f"แสดงแผนที่ไม่ได้ ({e}) — แสดงเป็นตารางแทน")
                st.dataframe(stn, hide_index=True, width="stretch")

    top_pm = src.loc[src["avg_pm25"].idxmax()]
    top_r = src.dropna(subset=["r_deseason"])
    top_r = top_r.loc[top_r["r_deseason"].idxmax()] if not top_r.empty else None

    msg = (f"**คำตอบของ BQ3** — แหล่งกำเนิดที่ทำให้ฝุ่น*รุนแรงที่สุด*คือ "
           f"**{top_pm['source_type']}** (PM2.5 {top_pm['avg_pm25']:.1f} µg/m³ · "
           f"เกินมาตรฐาน {top_pm['exceedance_pct']:.1f}% ของวัน)")
    if top_r is not None:
        msg += (f" แต่แหล่งที่*สัมพันธ์กับจำนวนผู้ป่วยมากที่สุด*กลับเป็น "
                f"**{top_r['source_type']}** (r = {top_r['r_deseason']:.3f}) "
                "— สองอย่างนี้ไม่ใช่ตัวเดียวกัน")
    st.success(msg)

    st.warning(
        "**ข้อจำกัดที่ต้องระบุคู่กับผลนี้เสมอ** — ประเภทแหล่งกำเนิดฝุ่นกับภูมิภาค**แยกกันไม่ออก** "
        "ในข้อมูลชุดนี้ สถานีประเภท 'การเผาในที่โล่ง' ทั้ง 12 แห่งอยู่ในภาคเหนือทั้งหมด "
        "ส่วน 'อุตสาหกรรม' กระจุกในภาคกลางและภาคตะวันออก "
        "ดังนั้นความต่างที่เห็นอาจมาจากลักษณะของภูมิภาค (ระบบบริการสาธารณสุข โครงสร้างประชากร ภูมิประเทศ) "
        "ไม่ใช่จากชนิดของแหล่งกำเนิดฝุ่นโดยตรง การจะแยกสองปัจจัยนี้ออกจากกันต้องมีสถานีหลายประเภท"
        "ในภูมิภาคเดียวกัน ซึ่งเครือข่ายตรวจวัดปัจจุบันยังไม่มี"
    )


# ═════════════════════════════════════════════════════════════════════
# BQ4 — กลุ่มควบคุม: ช่วงฝุ่นสูงเทียบฝุ่นต่ำ
# ═════════════════════════════════════════════════════════════════════
def tab_bq4(f: Q.Filters):
    st.subheader("BQ4 — เทียบกับกลุ่มควบคุมแล้ว ผู้ป่วยทางเดินหายใจเพิ่มขึ้นชัดกว่าจริงหรือไม่")
    st.caption(
        "เปรียบเทียบเดือนที่ฝุ่นเกินมาตรฐานไทย (> 37.5) กับเดือนที่ผ่านเกณฑ์ WHO (≤ 15) "
        "**ภายในจังหวัดเดียวกัน** แล้วหาค่ากลางข้ามจังหวัด"
    )

    df = q_control(f)
    if df.empty:
        st.warning("ไม่มีจังหวัดใดมีทั้งเดือนฝุ่นสูงและฝุ่นต่ำมากพอจะเทียบได้")
        return

    df = df.copy()
    df["ประเภท"] = df["is_respiratory"].map({True: "ทางเดินหายใจ", False: "กลุ่มควบคุม"})
    df["label"] = df["disease_name_en"]

    c1, c2 = st.columns([3, 2])
    with c1:
        d = df.sort_values("ratio_median")
        fig = px.bar(
            d, x="ratio_median", y="label", orientation="h", color="ประเภท",
            text="ratio_median",
            color_discrete_map={"ทางเดินหายใจ": VIS_COLOR, "กลุ่มควบคุม": CTRL_COLOR},
            labels={"ratio_median": "ผู้ป่วยเดือนฝุ่นสูง ÷ เดือนฝุ่นต่ำ (ค่ากลาง)", "label": ""},
            title="⑩ อัตราส่วนผู้ป่วยช่วงฝุ่นสูงเทียบฝุ่นต่ำ — เส้นประ 1.0 คือ 'ไม่ต่างกัน'",
        )
        fig.add_vline(x=1.0, line_dash="dash", line_color="black")
        fig.update_traces(textposition="outside")
        fig.update_layout(height=480, **BARE_LAYOUT)
        st.plotly_chart(fig, width="stretch")

    with c2:
        sub = q_subgroup(f)
        if not sub.empty:
            sub = sub.copy()
            sub["ประเภท"] = sub["is_respiratory"].map({True: "ทางเดินหายใจ", False: "กลุ่มควบคุม"})
            s = sub.dropna(subset=["r_deseason"]).sort_values("r_deseason")
            fig2 = px.bar(
                s, x="r_deseason", y="disease_name_en", orientation="h", color="ประเภท",
                color_discrete_map={"ทางเดินหายใจ": VIS_COLOR, "กลุ่มควบคุม": CTRL_COLOR},
                labels={"r_deseason": "r หลังหักฤดูกาล", "disease_name_en": ""},
                title="⑪ วิธีที่สอง: สหสัมพันธ์รายกลุ่มโรค",
            )
            fig2.add_vline(x=0, line_color="black", line_width=1)
            fig2.update_layout(height=480, showlegend=False, **BARE_LAYOUT)
            st.plotly_chart(fig2, width="stretch")

    st.dataframe(
        df[["disease_name_en", "disease_group_name_th", "ประเภท", "ratio_median",
            "ratio_mean", "n_prov_increase", "n_provinces"]].rename(columns={
            "disease_name_en": "กลุ่มโรค", "disease_group_name_th": "กลุ่มหลัก",
            "ratio_median": "อัตราส่วน (ค่ากลาง)", "ratio_mean": "อัตราส่วน (เฉลี่ย)",
            "n_prov_increase": "จังหวัดที่เพิ่มขึ้น", "n_provinces": "จังหวัดที่เทียบได้",
        }),
        hide_index=True, width="stretch",
    )

    resp = df[df["is_respiratory"]]
    ctrl = df[~df["is_respiratory"]]
    if not resp.empty and not ctrl.empty:
        top = resp.iloc[0]
        r_med, c_med = resp["ratio_median"].median(), ctrl["ratio_median"].median()
        st.success(
            f"**คำตอบของ BQ4 — ใช่ แต่ผลไม่แรง**  \n"
            f"กลุ่มที่เพิ่มชัดที่สุดคือ **{top['disease_name_en']}** อัตราส่วน "
            f"**{top['ratio_median']:.3f}** (เพิ่ม {(top['ratio_median'] - 1) * 100:.1f}% "
            f"ในเดือนฝุ่นสูง) และเพิ่มขึ้นใน **{int(top['n_prov_increase'])} จาก "
            f"{int(top['n_provinces'])} จังหวัด**  \n"
            f"ค่ากลางของกลุ่มทางเดินหายใจอยู่ที่ **{r_med:.3f}** เทียบกับกลุ่มควบคุม "
            f"**{c_med:.3f}** — กลุ่มทางเดินหายใจสูงกว่าจริง ซึ่งเป็นทิศทางที่สนับสนุนสมมติฐาน "
            "แต่ขนาดของผลเล็กเกินกว่าจะใช้พยากรณ์ภาระงานรายเดือนได้"
        )

    st.info(
        "**ทำไมสองกราฟให้คำตอบไม่เหมือนกัน** — กราฟ ⑩ ถามว่า *เดือนฝุ่นสูงมีผู้ป่วยมากกว่าเดือนฝุ่นต่ำไหม* "
        "ส่วนกราฟ ⑪ ถามว่า *ผู้ป่วยขึ้นลงตามฝุ่นแบบต่อเนื่องไหม* คนละคำถาม  \n"
        "กราฟ ⑩ จัดกลุ่มทางเดินหายใจไว้อันดับต้น (ปอดบวม หลอดลมอักเสบ) ตรงตามสมมติฐาน "
        "แต่กราฟ ⑪ กลับให้โรคตาสูงสุด **การรายงานทั้งสองด้านคือความซื่อตรงต่อข้อมูล** "
        "และข้อสรุปที่ปลอดภัยคือ: มีสัญญาณอ่อน ๆ ไปในทางที่คาด แต่ยังไม่หนักแน่นพอจะตั้งเป็นเกณฑ์ปฏิบัติ"
    )


# ═════════════════════════════════════════════════════════════════════
# BQ5 — สภาพอากาศแบบใดสัมพันธ์กับ PM2.5 สูงสุด
# ═════════════════════════════════════════════════════════════════════
def tab_bq5(f: Q.Filters):
    st.subheader("BQ5 — สภาพอากาศแบบใด (ลม ความชื้น ฝน) สัมพันธ์กับระดับ PM2.5 สูงสุด")
    st.caption("วิเคราะห์ที่ grain **รายวัน** จาก FACT_AIR_QUALITY_DAILY × DIM_WEATHER จึงคมกว่าทุกแท็บ")

    hm = q_heatmap(f)
    if hm.empty:
        st.warning("ไม่มีข้อมูลตามตัวกรองที่เลือก")
        return

    c1, c2 = st.columns([3, 2])
    with c1:
        pivot = hm.pivot(index="humidity_band", columns="wind_band", values="avg_pm25")
        hum_order = [b for b in pivot.index if "แห้ง" in b] + \
                    [b for b in pivot.index if "ปกติ" in b] + \
                    [b for b in pivot.index if "ชื้น" in b]
        wind_order = [b for b in pivot.columns if "สงบ" in b] + \
                     [b for b in pivot.columns if "ปกติ" in b] + \
                     [b for b in pivot.columns if "แรง" in b]
        pivot = pivot.reindex(index=hum_order or None, columns=wind_order or None)
        fig = px.imshow(
            pivot, text_auto=".1f", aspect="auto", color_continuous_scale="YlOrRd",
            labels=dict(x="ความเร็วลม", y="ความชื้น", color="PM2.5"),
            title="⑫ PM2.5 เฉลี่ยรายวัน ตามความชื้น × ความเร็วลม",
        )
        fig.update_layout(height=420, **BARE_LAYOUT)
        st.plotly_chart(fig, width="stretch")

    with c2:
        band = st.selectbox(
            "แยกตามปัจจัย", ["humidity_band", "wind_band", "temp_band", "has_rain"],
            format_func=lambda x: {"humidity_band": "ความชื้น", "wind_band": "ความเร็วลม",
                                   "temp_band": "อุณหภูมิ", "has_rain": "มีฝนตก"}[x],
        )
        w = q_weather(f, band)
        w["band"] = w["band"].astype(str)
        fig2 = px.bar(
            w, x="band", y="avg_pm25", text="avg_pm25",
            color="avg_pm25", color_continuous_scale="YlOrRd",
            labels={"band": "", "avg_pm25": "PM2.5 เฉลี่ย (µg/m³)"},
            title="⑬ PM2.5 เฉลี่ยแยกตามปัจจัย",
        )
        fig2.add_hline(y=Q.THAI_STANDARD_PM25, line_dash="dash", line_color="red")
        fig2.update_traces(textposition="outside")
        fig2.update_layout(height=420, coloraxis_showscale=False, **BARE_LAYOUT)
        st.plotly_chart(fig2, width="stretch")

    st.dataframe(
        q_weather(f, "humidity_band").rename(columns={
            "band": "ระดับความชื้น", "avg_pm25": "PM2.5 เฉลี่ย",
            "n_days": "จำนวนสถานี-วัน", "exceedance_pct": "% วันเกินมาตรฐาน"}),
        hide_index=True, width="stretch",
    )

    worst = hm.loc[hm["avg_pm25"].idxmax()]
    best = hm.loc[hm["avg_pm25"].idxmin()]
    ratio = worst["avg_pm25"] / best["avg_pm25"] if best["avg_pm25"] else 0
    st.success(
        f"**คำตอบของ BQ5 — ผลที่ใช้งานได้จริงที่สุดของทั้งโครงการ**  \n"
        f"วันที่ **{worst['humidity_band']} + {worst['wind_band']}** ค่าฝุ่นเฉลี่ย "
        f"**{worst['avg_pm25']:.1f}** µg/m³ ขณะที่วันที่ **{best['humidity_band']} + "
        f"{best['wind_band']}** อยู่ที่เพียง **{best['avg_pm25']:.1f}** µg/m³ "
        f"— ต่างกัน **{ratio:.1f} เท่า**  \n"
        "แปลว่า **พยากรณ์อากาศล่วงหน้าใช้เตือนวันฝุ่นวิกฤตได้ทันที** โดยไม่ต้องรอผลตรวจวัดฝุ่นจริง "
        "และเป็นเกณฑ์ระดับ *วัน* ซึ่งตรงกับ grain ที่งานวิจัยพบผลต่อสุขภาพ (1–7 วัน) "
        "ต่างจาก BQ1/BQ4 ที่ติดข้อจำกัดของข้อมูลผู้ป่วยรายเดือน"
    )


# ═════════════════════════════════════════════════════════════════════
# BQ6 — ความล่าช้า (lag) กี่เดือน
# ═════════════════════════════════════════════════════════════════════
def tab_bq6(f: Q.Filters):
    st.subheader("BQ6 — มีความล่าช้ากี่เดือนระหว่างช่วงฝุ่นสูงกับจำนวนผู้ป่วยที่เพิ่มขึ้นจริง")
    st.caption("Measure ที่ใช้: M5 Lagged PM2.5 (`avg_pm25_lag1`, `avg_pm25_lag2` จาก AGG)")

    lags = q_corr_lags(f)
    if lags.empty:
        st.warning("ไม่มีข้อมูลตามตัวกรองที่เลือก")
        return

    lags = lags.copy()
    lags["label"] = lags["lag_months"].map({0: "หน่วง 0 เดือน\n(เดือนเดียวกัน)",
                                            1: "หน่วง 1 เดือน", 2: "หน่วง 2 เดือน"})

    c1, c2 = st.columns([3, 2])
    with c1:
        fig = go.Figure()
        fig.add_trace(go.Bar(x=lags["label"], y=lags["r_deseason"], name="r หลังหักฤดูกาล",
                             marker_color=VIS_COLOR,
                             text=lags["r_deseason"].map(lambda x: f"{x:.3f}"),
                             textposition="outside"))
        fig.add_trace(go.Bar(x=lags["label"], y=lags["r_raw"], name="r ดิบ",
                             marker_color=CTRL_COLOR,
                             text=lags["r_raw"].map(lambda x: f"{x:.3f}"),
                             textposition="outside"))
        fig.add_hline(y=0, line_color="black", line_width=1)
        fig.update_layout(title="⑭ สหสัมพันธ์ที่ระยะหน่วง 0–2 เดือน", height=420,
                          barmode="group", yaxis_title="สัมประสิทธิ์สหสัมพันธ์ (r)",
                          legend=dict(orientation="h", y=1.02, x=1, xanchor="right"),
                          **BARE_LAYOUT)
        st.plotly_chart(fig, width="stretch")

    with c2:
        st.dataframe(
            lags[["lag_months", "r_raw", "r_deseason", "n"]].rename(columns={
                "lag_months": "หน่วง (เดือน)", "r_raw": "r ดิบ",
                "r_deseason": "r หลังหักฤดูกาล", "n": "จังหวัด-เดือน",
            }),
            hide_index=True, width="stretch",
        )
        best = lags.loc[lags["r_deseason"].abs().idxmax()]
        st.metric("ระยะหน่วงที่สัมพันธ์แรงที่สุด", f"{int(best['lag_months'])} เดือน",
                  f"r = {best['r_deseason']:.3f}", delta_color="off")
        st.caption(
            "จำนวนจังหวัด-เดือนลดลงเมื่อหน่วงมากขึ้น (915 → 824 → 677) "
            "เพราะเดือนแรก ๆ ของชุดข้อมูลไม่มีเดือนก่อนหน้าให้อ้างอิง"
        )

    st.error(
        "**คำตอบของ BQ6 — ไม่พบระยะหน่วงที่ใช้พยากรณ์ได้**  \n"
        "ค่า r ที่ระยะหน่วง 0, 1, 2 เดือนอยู่ที่ 0.012, −0.092, −0.137 ตามลำดับ "
        "ทั้งสามค่าเล็กมากและค่าที่หน่วง 1–2 เดือนยังเป็น**ลบ** ซึ่งไม่มีคำอธิบายทางการแพทย์รองรับ "
        "(ฝุ่นเดือนก่อนสูง แล้วผู้ป่วยเดือนนี้*น้อยลง* เป็นไปไม่ได้ในเชิงกลไก)  \n"
        "การตีความที่ถูกต้องคือ **สัญญาณนี้คือความผันผวนแบบสุ่ม ไม่ใช่ผลของฝุ่น** "
        "และสาเหตุคือ grain ของข้อมูลผู้ป่วยหยาบเกินไป — ผลของ PM2.5 ต่อสุขภาพเกิดใน 1–7 **วัน** "
        "การเฉลี่ยเป็นรายเดือนกลบสัญญาณนั้นทิ้ง  \n"
        "**ข้อเสนอ:** ถ้าต้องการตอบ BQ6 ให้ได้จริง ต้องขอข้อมูลผู้ป่วย**รายวัน**จาก HDC "
        "ซึ่งอยู่นอกขอบเขตข้อมูลที่เปิดเผยสาธารณะในปัจจุบัน ระหว่างนี้ให้ใช้ BQ5 แทน "
        "เพราะพยากรณ์อากาศให้สัญญาณเตือนล่วงหน้าระดับวันได้จริง"
    )

    st.markdown("**แนวโน้มระยะยาว — ใช้ประเมินว่ามาตรการที่ผ่านมาได้ผลหรือไม่**")
    yr = q_yearly(f)
    if not yr.empty:
        fig3 = make_subplots(specs=[[{"secondary_y": True}]])
        fig3.add_trace(
            go.Bar(x=yr["year"], y=yr["exceedance_pct"], name="% วันเกินมาตรฐานไทย",
                   marker_color=PM_COLOR,
                   text=yr["exceedance_pct"].map(lambda x: f"{x:.1f}%"), textposition="outside"),
            secondary_y=False,
        )
        fig3.add_trace(
            go.Scatter(x=yr["year"], y=yr["visits"], name="ครั้งรับบริการ",
                       mode="lines+markers", line=dict(color=VIS_COLOR, width=3)),
            secondary_y=True,
        )
        fig3.update_xaxes(dtick=1, title_text="ปี ค.ศ.")
        fig3.update_yaxes(title_text="% วันที่เกินมาตรฐาน", secondary_y=False, color=PM_COLOR)
        fig3.update_yaxes(title_text="ครั้งรับบริการ", secondary_y=True, color=VIS_COLOR)
        fig3.update_layout(title="⑮ แนวโน้มรายปี: มลพิษ เทียบ ภาระผู้ป่วย", height=400,
                           **PLOT_LAYOUT)
        st.plotly_chart(fig3, width="stretch")
        st.dataframe(
            yr.rename(columns={
                "year": "ปี", "avg_pm25": "PM2.5 เฉลี่ย",
                "exceedance_days_th": "วันเกินมาตรฐาน", "days_with_data": "วันที่มีข้อมูล",
                "exceedance_pct": "% เกินมาตรฐาน", "visits": "ครั้งรับบริการ",
                "n_provinces": "จำนวนจังหวัด"}),
            hide_index=True, width="stretch",
        )
        st.caption(
            "⚠️ จำนวนจังหวัดที่มีข้อมูลฝุ่นไม่เท่ากันทุกปี ยอด 'ครั้งรับบริการ' "
            "จึงอาจเปลี่ยนเพราะขอบเขตข้อมูล ไม่ใช่เพราะภาระงานจริงเปลี่ยน "
            "ให้ดูคอลัมน์ 'จำนวนจังหวัด' ประกอบเสมอ"
        )


# ═════════════════════════════════════════════════════════════════════
# BQ7 — drill-down จังหวัด → โรงพยาบาล → กลุ่มโรค
# ═════════════════════════════════════════════════════════════════════
def tab_bq7(f: Q.Filters):
    st.subheader("BQ7 — โรงพยาบาลใดควรได้รับการจัดสรรทรัพยากรเพิ่มในช่วงฝุ่นสูง")
    st.caption("Drill-down 3 ชั้น: จังหวัด → โรงพยาบาล → กลุ่มโรค · ผู้ใช้หลักคือผู้บริหารโรงพยาบาลและเขตสุขภาพ")

    # ── ชั้นที่ 1: จังหวัด ──
    st.markdown("#### ชั้นที่ 1 — จัดอันดับความเสี่ยงระดับจังหวัด")
    pr = q_prov_risk(f)
    if pr.empty:
        st.warning("ไม่มีข้อมูลตามตัวกรองที่เลือก")
        return

    c1, c2 = st.columns([3, 2])
    with c1:
        top = pr.head(15).sort_values("risk_score")
        fig = px.bar(
            top, x="risk_score", y="province_name_th", orientation="h",
            color="source_type", color_discrete_map=SOURCE_COLORS,
            text="risk_score", hover_data=["exceedance_pct", "visits_per_100k", "avg_pm25"],
            labels={"risk_score": "คะแนนความเสี่ยง (0–1)", "province_name_th": "",
                    "source_type": "แหล่งกำเนิด"},
            title="⑯ 15 จังหวัดที่ควรได้รับความสำคัญสูงสุด",
        )
        fig.update_traces(textposition="outside")
        fig.update_layout(height=520, legend=dict(orientation="h", y=-0.08), **BARE_LAYOUT)
        st.plotly_chart(fig, width="stretch")

    with c2:
        fig2 = px.scatter(
            pr, x="exceedance_pct", y="visits_per_100k", color="region_th",
            size="avg_pm25", hover_name="province_name_th",
            category_orders={"region_th": Q.REGION_ORDER},
            labels={"exceedance_pct": "% วันที่ฝุ่นเกินมาตรฐาน",
                    "visits_per_100k": "ครั้งรับบริการ/ประชากรแสนคน", "region_th": "ภาค"},
            title="⑰ สองแกนที่ใช้คิดคะแนนความเสี่ยง",
            trendline="ols" if (HAS_STATSMODELS and len(pr) > 2) else None,
            trendline_scope="overall", trendline_color_override="#666",
        )
        fig2.update_layout(height=520, legend=dict(orientation="h", y=-0.18), **BARE_LAYOUT)
        st.plotly_chart(fig2, width="stretch")

    with st.expander("ดูตารางความเสี่ยงทั้งหมด และดาวน์โหลด CSV"):
        st.dataframe(
            pr.rename(columns={
                "province_name_th": "จังหวัด", "region_th": "ภาค",
                "source_type": "แหล่งกำเนิดฝุ่น", "n_stations": "จำนวนสถานี",
                "avg_pm25": "PM2.5 เฉลี่ย", "exceedance_days_th": "วันเกินมาตรฐาน",
                "days_with_data": "วันที่มีข้อมูล", "exceedance_pct": "% เกินมาตรฐาน",
                "visits": "ครั้งรับบริการ", "visits_per_100k": "ต่อประชากรแสนคน",
                "n_months": "เดือนที่ใช้ได้", "risk_score": "คะแนนความเสี่ยง"}),
            hide_index=True, width="stretch",
        )
        st.download_button("⬇️ ดาวน์โหลด province_risk.csv",
                           pr.to_csv(index=False).encode("utf-8-sig"),
                           "province_risk.csv", "text/csv")

    st.divider()

    # ── ชั้นที่ 2: โรงพยาบาล ──
    st.markdown("#### ชั้นที่ 2 — เจาะลงโรงพยาบาลในจังหวัดที่เลือก")
    prov_list = pr["province_name_th"].tolist()
    sel_prov = st.selectbox("เลือกจังหวัด (เรียงตามคะแนนความเสี่ยง)", prov_list, index=0)

    hr = q_hosp_rank(f, sel_prov, 25)
    if hr.empty:
        st.info(f"ไม่มีข้อมูลโรงพยาบาลใน {sel_prov}")
        return

    hr = hr.copy()
    hr["label"] = hr["hospcode"].astype(str) + " · อ." + hr["district_name_th"].fillna("—")

    c3, c4 = st.columns([3, 2])
    with c3:
        d = hr.head(15).sort_values("visits")
        fig3 = px.bar(
            d, x="visits", y="label", orientation="h", color="haze_ratio",
            color_continuous_scale="RdYlGn_r", color_continuous_midpoint=1.0,
            hover_data=["visits_haze", "visits_non_haze", "haze_ratio"],
            labels={"visits": "ครั้งรับบริการรวม", "label": "",
                    "haze_ratio": "ฤดูฝุ่น÷นอกฤดู"},
            title=f"⑱ โรงพยาบาลใน {sel_prov} — สีแดง = ภาระเพิ่มในฤดูฝุ่น",
        )
        fig3.update_layout(height=520, **BARE_LAYOUT)
        st.plotly_chart(fig3, width="stretch")

    with c4:
        st.dataframe(
            hr[["hospcode", "district_name_th", "visits", "visits_haze",
                "visits_non_haze", "haze_ratio"]].rename(columns={
                "hospcode": "รหัส รพ.", "district_name_th": "อำเภอ",
                "visits": "รวม", "visits_haze": "ฤดูฝุ่น",
                "visits_non_haze": "นอกฤดู", "haze_ratio": "อัตราส่วน"}),
            hide_index=True, width="stretch", height=520,
        )

    st.caption(
        "**อัตราส่วน** = ครั้งรับบริการเฉลี่ยต่อเดือนในฤดูฝุ่น ÷ นอกฤดูฝุ่น "
        "(หารด้วยจำนวนเดือนแล้ว จึงเทียบได้แม้จำนวนเดือนไม่เท่ากัน)  \n"
        "DIM_HOSPITAL ไม่มีชื่อโรงพยาบาลเพราะต้นทาง HDC ให้มาแค่ `hospcode` "
        "จึงแสดงเป็นรหัส + อำเภอ ซึ่งระบุตัวได้จริงในทางปฏิบัติ"
    )

    st.divider()

    # ── ชั้นที่ 3: กลุ่มโรค ──
    st.markdown("#### ชั้นที่ 3 — เจาะลงกลุ่มโรคของโรงพยาบาลที่เลือก")
    sel_label = st.selectbox("เลือกโรงพยาบาล (เรียงตามยอดรับบริการ)", hr["label"].tolist(), index=0)
    sel_code = hr[hr["label"] == sel_label].iloc[0]["hospcode"]

    hd = q_hosp_disease(f, sel_code)
    hm2 = q_hosp_monthly(f, sel_code)

    c5, c6 = st.columns([2, 3])
    with c5:
        if not hd.empty:
            hd = hd.copy()
            hd["ประเภท"] = hd["is_respiratory"].map({True: "ทางเดินหายใจ", False: "กลุ่มควบคุม"})
            fig4 = px.bar(
                hd.sort_values("haze_ratio"), x="haze_ratio", y="disease_name_en",
                orientation="h", color="ประเภท", text="haze_ratio",
                color_discrete_map={"ทางเดินหายใจ": VIS_COLOR, "กลุ่มควบคุม": CTRL_COLOR},
                labels={"haze_ratio": "ฤดูฝุ่น ÷ นอกฤดูฝุ่น", "disease_name_en": ""},
                title=f"⑲ กลุ่มโรคของ รพ. {sel_code}",
            )
            fig4.add_vline(x=1.0, line_dash="dash", line_color="black")
            fig4.update_traces(textposition="outside")
            fig4.update_layout(height=460, **BARE_LAYOUT)
            st.plotly_chart(fig4, width="stretch")

    with c6:
        if not hm2.empty:
            fig5 = make_subplots(specs=[[{"secondary_y": True}]])
            fig5.add_trace(
                go.Scatter(x=hm2["month_date"], y=hm2["avg_pm25"], name="PM2.5 จังหวัด",
                           line=dict(color=PM_COLOR, width=2)),
                secondary_y=False,
            )
            fig5.add_trace(
                go.Scatter(x=hm2["month_date"], y=hm2["visits"], name="ครั้งรับบริการ รพ. นี้",
                           mode="lines+markers", line=dict(color=VIS_COLOR, width=2, dash="dot")),
                secondary_y=True,
            )
            fig5.add_hline(y=Q.THAI_STANDARD_PM25, line_dash="dash", line_color="red",
                           secondary_y=False)
            fig5.update_yaxes(title_text="PM2.5 (µg/m³)", secondary_y=False, color=PM_COLOR)
            fig5.update_yaxes(title_text="ครั้งรับบริการ", secondary_y=True, color=VIS_COLOR)
            fig5.update_layout(title=f"⑳ รพ. {sel_code} รายเดือน เทียบ PM2.5 ของจังหวัด",
                               height=460, **PLOT_LAYOUT)
            st.plotly_chart(fig5, width="stretch")

    if not hd.empty:
        resp_top = hd[hd["is_respiratory"]].sort_values("haze_ratio", ascending=False)
        if not resp_top.empty:
            t = resp_top.iloc[0]
            st.success(
                f"**ข้อเสนอเชิงปฏิบัติสำหรับ รพ. {sel_code} (อ.{sel_label.split('อ.')[-1]})**  \n"
                f"กลุ่มโรคที่ภาระเพิ่มมากที่สุดในฤดูฝุ่นคือ **{t['disease_name_en']}** "
                f"อัตราส่วน **{t['haze_ratio']:.2f}** "
                f"(เฉลี่ย {t['avg_haze']:,.0f} ครั้ง/เดือนในฤดูฝุ่น เทียบ {t['avg_non_haze']:,.0f} นอกฤดู)  \n"
                "ใช้ตัวเลขนี้ประมาณกำลังคนและเวชภัณฑ์ที่ต้องเพิ่มในเดือน ธ.ค.–เม.ย. ได้โดยตรง"
            )

    st.warning(
        "**ข้อควรระวังก่อนนำไปจัดสรรงบจริง** — ค่า PM2.5 เป็นค่าของ**ทั้งจังหวัด** "
        "ไม่ใช่ค่าที่วัดหน้าโรงพยาบาล จังหวัดส่วนใหญ่มีสถานีตรวจวัดเพียง 1 แห่ง "
        "โรงพยาบาลที่อยู่ห่างจากสถานีหลายสิบกิโลเมตรอาจเผชิญระดับฝุ่นต่างจากตัวเลขนี้มาก  \n"
        "ตัวเลขชุดนี้เหมาะกับการ**จัดลำดับความสำคัญเบื้องต้น** แล้วจึงลงพื้นที่ตรวจสอบก่อนตัดสินใจ"
    )


# ═════════════════════════════════════════════════════════════════════
# คุณภาพข้อมูล
# ═════════════════════════════════════════════════════════════════════
def tab_quality(f: Q.Filters):
    st.subheader("คุณภาพข้อมูล — ทุกตัวเลขบนแผงนี้เชื่อถือได้แค่ไหน")
    st.caption(
        "ตาม \"หมายเหตุคุณภาพข้อมูล\" ท้ายหัวข้อ 1.4 ของเอกสาร: "
        "ต้องแสดง `coverage_ratio` กำกับควบคู่กับ Measure หลักเสมอ"
    )

    cov = q_cov_stats(f)
    dq = q_dq(f)

    c1, c2, c3, c4 = st.columns(4)
    ac = cov.get("avg_coverage")
    c1.metric("coverage_ratio เฉลี่ย", f"{ac * 100:.1f}%" if ac else "—",
              f"ต่ำสุดในตาราง {cov.get('min_coverage', 0) * 100:.0f}%", delta_color="off")
    c2.metric("สถานี-วันที่ผ่านเกณฑ์", f"{int(cov.get('n_station_days') or 0):,}",
              f"ครบ 24 ชม. {cov.get('pct_full') or 0:.1f}%", delta_color="off")
    c3.metric("สถานี-วันที่ถูกคัดทิ้ง", f"{int(cov.get('dropped_station_days') or 0):,}",
              f"{cov.get('pct_dropped') or 0:.1f}% ของข้อมูลดิบ", delta_color="off")
    tot = int(dq.get("n_province_months") or 0)
    usable = tot - int(dq.get("n_no_pm") or 0) - int(dq.get("n_thin_pm") or 0)
    c4.metric("จังหวัด-เดือนที่ใช้วิเคราะห์ได้", f"{usable:,}",
              f"{usable * 100 / tot:.1f}% จาก {tot:,}" if tot else "—", delta_color="off")

    st.info(
        f"**เหตุใด coverage_ratio ต่ำสุดจึงเป็น {cov.get('min_coverage', 0.75):.2f} ไม่ใช่ 0**  \n"
        f"ขั้น Clean ของ ETL คัดวันที่วัดได้ไม่ถึง 18 จาก 24 ชั่วโมงทิ้งไปแล้ว "
        f"(`MIN_READINGS_PER_DAY = 18`) — คิดเป็น **{int(cov.get('dropped_station_days') or 0):,} "
        f"สถานี-วัน หรือ {cov.get('pct_dropped') or 0:.1f}% ของข้อมูลดิบ** "
        "ตรงกับที่เอกสารระบุไว้ว่า \"~35% ของวันมีข้อมูลไม่ครบ 18 ชั่วโมง\"  \n"
        "สิ่งที่เหลืออยู่ในคลังข้อมูลจึงเป็นวันที่ผ่านเกณฑ์แล้วทั้งหมด "
        "ตัวเลขนี้ไม่ได้แปลว่าข้อมูลสมบูรณ์ แต่แปลว่า**ข้อมูลที่ไม่ครบถูกคัดออกอย่างเป็นระบบก่อนเข้าคลัง**"
    )

    c5, c6 = st.columns([2, 3])
    with c5:
        cp = q_cov_prov(f)
        if not cp.empty:
            fig = px.bar(
                cp.head(20), x="avg_coverage", y="province_name_th", orientation="h",
                color="region_th", category_orders={"region_th": Q.REGION_ORDER},
                labels={"avg_coverage": "coverage_ratio เฉลี่ย",
                        "province_name_th": "", "region_th": "ภาค"},
                title="㉑ 20 จังหวัดที่ข้อมูลรายชั่วโมงครบน้อยที่สุด",
            )
            fig.update_layout(height=520, legend=dict(orientation="h", y=-0.1), **BARE_LAYOUT)
            fig.update_xaxes(range=[0.7, 1.0])
            st.plotly_chart(fig, width="stretch")

    with c6:
        cm = q_coverage(f)
        if not cm.empty:
            pivot = cm.pivot(
                index="province_name_th",
                columns="month_date",
                values="days_with_data"
            ).fillna(0)

            # แปลง Timestamp เป็น string เพื่อให้ Plotly px.imshow รองรับ
            pivot.columns = pivot.columns.strftime("%Y-%m")

            fig2 = px.imshow(
                pivot,
                aspect="auto",
                color_continuous_scale="Greens",
                labels=dict(x="เดือน", y="", color="จำนวนวันที่มีข้อมูล"),
                title="㉒ ความครบถ้วนรายจังหวัด-เดือน (เข้ม = ครบ · ขาว = ไม่มีข้อมูล)",
            )
            fig2.update_layout(height=520, **BARE_LAYOUT)
            st.plotly_chart(fig2, width="stretch")

    st.markdown("**ตารางในคลังข้อมูล**")
    st.dataframe(_summary(), hide_index=True, width="stretch")

    st.markdown("""
**ข้อจำกัดที่ต้องระบุทุกครั้งที่นำผลไปใช้**

1. **Grain ไม่ตรงกัน** — ข้อมูลฝุ่นเป็นราย *ชั่วโมง* แต่ข้อมูลผู้ป่วยละเอียดที่สุดแค่ราย *เดือน*
   การเฉลี่ยฝุ่นขึ้นเป็นรายเดือนกลบผลระยะสั้น 1–7 วันที่งานวิจัยพบไว้ — นี่คือสาเหตุหลักที่
   BQ1 และ BQ6 ไม่พบความสัมพันธ์
2. **Ecological fallacy** — ข้อมูลเป็นระดับจังหวัด สรุปถึงระดับบุคคลไม่ได้
   ("จังหวัดที่ฝุ่นสูงมีผู้ป่วยมาก" ≠ "คนที่สูดฝุ่นมากคือคนที่ป่วย")
3. **แหล่งกำเนิดฝุ่นแยกจากภูมิภาคไม่ออก** — สถานี 'การเผาในที่โล่ง' ทั้ง 12 แห่งอยู่ในภาคเหนือ
   ผลของ BQ3 จึงอาจสะท้อนความต่างของภูมิภาค ไม่ใช่ของชนิดแหล่งกำเนิด
4. **ความครอบคลุมไม่เท่ากัน** — จังหวัดส่วนใหญ่มีสถานีเดียว กรุงเทพฯ มี 3 สถานี
   ค่าเฉลี่ยระดับจังหวัดจึงมีความแม่นยำไม่เท่ากัน
5. **'ครั้งรับบริการ' ไม่ใช่ 'จำนวนผู้ป่วย'** — คนเดียวมาหลายครั้งถูกนับหลายครั้ง
   และสะท้อน *การเข้าถึงบริการ* พอ ๆ กับ *การเจ็บป่วยจริง*
6. **ธันวาคมรายงานไม่ครบ** — ดูรายละเอียดในแท็บ BQ2
""")


@st.cache_data(show_spinner=False)
def _summary():
    return Q.warehouse_summary(get_con())


# ═════════════════════════════════════════════════════════════════════
def main():
    try:
        Q.find_warehouse()
    except FileNotFoundError as e:
        st.error(str(e))
        st.stop()

    f = build_filters()
    render_header(f)

    tabs = st.tabs([
        "BQ1 ความสัมพันธ์",
        "BQ2 ฤดูกาล & ฤดูฝุ่น",
        "BQ3 แหล่งกำเนิดฝุ่น",
        "BQ4 กลุ่มควบคุม",
        "BQ5 สภาพอากาศ",
        "BQ6 ระยะหน่วง (Lag)",
        "BQ7 Drill-down โรงพยาบาล",
        "✅ คุณภาพข้อมูล",
    ])
    for tab, fn in zip(tabs, [tab_bq1, tab_bq2, tab_bq3, tab_bq4,
                              tab_bq5, tab_bq6, tab_bq7, tab_quality]):
        with tab:
            fn(f)


if __name__ == "__main__":
    main()
