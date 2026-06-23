"""
키워드 트렌드 KPI 대시보드 — CSV 저장 방식
  data/trends.csv          : 네이버·구글 검색 트렌드 데이터
  data/derived_keywords.csv: 도출 키워드 관리 (반영 Y/N)

GitHub 연동(GITHUB_TOKEN + GITHUB_REPO 설정 시):
  - derived_keywords.csv 읽기·쓰기를 GitHub API로 처리
  - 팀 누구나 '반영' 저장 → GitHub 커밋 → 영구 보존
"""

import io
import os
from datetime import datetime

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import github_storage as gh
from news_crawler import fetch_news_keywords
from collector import collect_single_keyword

# ──────────────────────────────────────────────────────
# 경로 설정
# ──────────────────────────────────────────────────────
BASE_DIR     = os.path.dirname(__file__)
DATA_DIR     = os.path.join(BASE_DIR, "data")
TRENDS_CSV   = os.path.join(DATA_DIR, "trends.csv")
DERIVED_CSV  = os.path.join(DATA_DIR, "derived_keywords.csv")

DERIVED_COLS  = ["keyword", "kpi_month", "reflected", "source", "added_at"]
TRENDS_COLS   = ["keyword", "date", "ratio", "source", "collected_at"]
TRACKED_CSV   = os.path.join(DATA_DIR, "tracked_keywords.csv")
TRACKED_COLS  = ["keyword", "added_at"]

CURRENT_MONTH = datetime.today().strftime("%Y-%m")   # 예: "2026-06"

st.set_page_config(
    page_title="키워드 인텔리전스 | SCK·STK",
    page_icon="📊",
    layout="wide",
)

st.markdown("""
<style>
/* ────────────────────────────────────────────────
   색상 변수 (전체 테마)
   포인트: #2563EB (블루) 1개
   배경:  #F8FAFC (거의 흰색)
   텍스트: #0F172A (다크 네이비) / #64748B (보조) / #94A3B8 (힌트)
   테두리: #E2E8F0 (연한 회색)
──────────────────────────────────────────────── */

/* ── Streamlit 기본 여백·헤더 제거 ── */
#MainMenu { visibility: hidden; }
footer    { visibility: hidden; }
.stApp > header { display: none; }
.block-container {
    max-width: 1240px !important;
    padding: 0 2.5rem 4rem !important;
    margin: 0 auto !important;
}

/* ── 전체 배경 ── */
.stApp { background: #F8FAFC; }

/* ═══════════════════════════════════════
   상단 헤더 바
═══════════════════════════════════════ */
.dash-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    background: #ffffff;
    border-bottom: 1px solid #E2E8F0;
    padding: 14px 2.5rem;
    margin: 0 -2.5rem 2rem -2.5rem;
}
.dash-logo {
    display: flex; align-items: center; gap: 10px;
}
.dash-logo-mark {
    width: 30px; height: 30px;
    background: #2563EB;
    border-radius: 8px;
    display: flex; align-items: center; justify-content: center;
    color: white; font-size: 15px; font-weight: 700; line-height: 1;
    flex-shrink: 0;
}
.dash-logo-text .dt { font-size: 15px; font-weight: 700; color: #0F172A; line-height: 1.2; }
.dash-logo-text .ds { font-size: 11px; color: #94A3B8; line-height: 1.3; }
.dash-meta {
    display: flex; align-items: center; gap: 20px;
    font-size: 12px; color: #64748B;
}
.dash-live {
    display: flex; align-items: center; gap: 5px;
    background: #F0FDF4; color: #166534;
    padding: 4px 12px; border-radius: 20px;
    font-weight: 600; font-size: 11px;
}
.dash-live::before {
    content: "●"; font-size: 8px; color: #16A34A;
}

/* ═══════════════════════════════════════
   섹션 헤더
═══════════════════════════════════════ */
.sec-hdr {
    border-left: 3px solid #2563EB;
    padding-left: 12px;
    margin: 0 0 14px 0;
}
.sec-hdr .sh-t {
    font-size: 15px; font-weight: 700; color: #0F172A;
    margin: 0; line-height: 1.3;
}
.sec-hdr .sh-s {
    font-size: 12px; color: #94A3B8;
    margin: 3px 0 0; line-height: 1.4;
}

/* ═══════════════════════════════════════
   KPI 카드
═══════════════════════════════════════ */
.kpi-card {
    background: white;
    border: 1px solid #E2E8F0;
    border-radius: 10px;
    padding: 20px 22px 18px;
}
.kpi-label {
    font-size: 10.5px; font-weight: 700; color: #94A3B8;
    text-transform: uppercase; letter-spacing: .07em; margin-bottom: 10px;
}
.kpi-value {
    font-size: 2.6rem; font-weight: 700; color: #0F172A; line-height: 1;
}
.kpi-unit { font-size: .95rem; font-weight: 400; color: #94A3B8; margin-left: 3px; }
.kpi-target { font-size: 12px; color: #94A3B8; margin-top: 8px; }
.badge-pass {
    display: inline-block; background: #F0FDF4; color: #166534;
    border-radius: 6px; padding: 6px 16px; font-weight: 700; font-size: 14px; margin-top: 10px;
}
.badge-fail {
    display: inline-block; background: #FFF7ED; color: #9A3412;
    border-radius: 6px; padding: 6px 16px; font-weight: 700; font-size: 14px; margin-top: 10px;
}

/* ═══════════════════════════════════════
   그래프 카드
═══════════════════════════════════════ */
.chart-card-wrap {
    background: white; border: 1px solid #E2E8F0;
    border-radius: 10px; padding: 16px 20px 8px;
}
.src-naver  { font-size: 12px; font-weight: 700; color: #059669; }
.src-google { font-size: 12px; font-weight: 700; color: #DC2626; }
.chart-hint { font-size: 11px; color: #94A3B8; margin: 2px 0 6px; }

/* ═══════════════════════════════════════
   발굴 키워드 카드
═══════════════════════════════════════ */
/* Streamlit border 컨테이너를 덮어씀 */
div[data-testid="stContainer"] > div[data-testid="element-container"] > div {
    border-radius: 8px !important;
}

/* ═══════════════════════════════════════
   버튼
═══════════════════════════════════════ */
button[kind="primary"],
.stButton button[kind="primary"] {
    background-color: #2563EB !important;
    border-color: #2563EB !important;
    color: white !important;
    border-radius: 7px !important;
    font-weight: 600 !important;
}
button[kind="primary"]:hover,
.stButton button[kind="primary"]:hover {
    background-color: #1D4ED8 !important;
    border-color: #1D4ED8 !important;
}
.stButton button[kind="secondary"] {
    border-radius: 7px !important;
    border-color: #E2E8F0 !important;
    color: #374151 !important;
}
/* ✕ 삭제 버튼 */
div[data-testid*="chip_del"] button,
div[data-key*="chip_del"] button {
    color: #DC2626 !important;
    border-color: #FCA5A5 !important;
    background: white !important;
}
div[data-testid*="chip_del"] button:hover,
div[data-key*="chip_del"] button:hover {
    background: #FEF2F2 !important;
}

/* ═══════════════════════════════════════
   구분선·기타
═══════════════════════════════════════ */
hr { border-color: #E2E8F0 !important; margin: 1.5rem 0 !important; }
.stProgress > div > div { background: #2563EB !important; }

/* 섹션 간 여백 */
.section-gap { margin-top: 2.5rem; }

/* 스파크라인 표 헤더 */
.spark-hdr {
    font-size: 11px; font-weight: 700; color: #64748B;
    text-transform: uppercase; letter-spacing: .05em;
}

/* 기존 section-title (하위 호환) */
.section-title { font-size:1.1rem; font-weight:700; color:#0F172A; margin:0 0 4px 0; }
</style>
""", unsafe_allow_html=True)


# ──────────────────────────────────────────────────────
# 데이터 초기화 — data/ 폴더와 CSV 파일 없으면 생성
# ──────────────────────────────────────────────────────
def ensure_data():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(TRENDS_CSV):
        pd.DataFrame(columns=TRENDS_COLS).to_csv(
            TRENDS_CSV, index=False, encoding="utf-8-sig"
        )
    if not os.path.exists(DERIVED_CSV):
        pd.DataFrame(columns=DERIVED_COLS).to_csv(
            DERIVED_CSV, index=False, encoding="utf-8-sig"
        )
    # 추적 키워드 초기값: keywords.py에서 가져옴
    if not os.path.exists(TRACKED_CSV):
        try:
            from keywords import KEYWORDS as _default_kws
        except ImportError:
            _default_kws = []
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        pd.DataFrame(
            [[kw, now] for kw in _default_kws], columns=TRACKED_COLS
        ).to_csv(TRACKED_CSV, index=False, encoding="utf-8-sig")


# ──────────────────────────────────────────────────────
# 도출 키워드 CSV CRUD — GitHub 연동 또는 로컬 파일
# ──────────────────────────────────────────────────────

@st.cache_data(ttl=30)
def _load_derived_from_github() -> pd.DataFrame:
    """GitHub에서 derived_keywords.csv를 읽습니다 (30초 캐시)."""
    df = gh.read_csv("data/derived_keywords.csv")
    return df if df is not None else pd.DataFrame(columns=DERIVED_COLS)


def _read_derived_all() -> pd.DataFrame:
    """도출 키워드 전체를 읽습니다 — GitHub 연동 시 GitHub에서, 아니면 로컬에서."""
    if gh.is_configured():
        return _load_derived_from_github()
    if not os.path.exists(DERIVED_CSV):
        return pd.DataFrame(columns=DERIVED_COLS)
    df = pd.read_csv(DERIVED_CSV, dtype=str)
    for col in DERIVED_COLS:
        if col not in df.columns:
            df[col] = ""
    return df


def _write_derived(df: pd.DataFrame, message: str) -> bool:
    """도출 키워드를 저장합니다 — GitHub 연동 시 GitHub에, 아니면 로컬에."""
    if gh.is_configured():
        ok = gh.write_csv(df, "data/derived_keywords.csv", message)
        if ok:
            _load_derived_from_github.clear()  # 캐시 초기화 → 다음 로드에서 fresh read
        return ok
    else:
        df.to_csv(DERIVED_CSV, index=False, encoding="utf-8-sig")
        return True


def load_derived(month: str) -> pd.DataFrame:
    df = _read_derived_all()
    df = df[df["kpi_month"] == month].copy() if "kpi_month" in df.columns else pd.DataFrame(columns=DERIVED_COLS)
    df["reflected"] = df["reflected"].astype(str).str.lower().isin(["1", "true", "yes"])
    df = df.rename(columns={
        "keyword": "키워드", "kpi_month": "월",
        "reflected": "반영", "source": "출처", "added_at": "도출일",
    })
    return df[["키워드", "월", "반영", "출처", "도출일"]].reset_index(drop=True)


def load_derived_all_for_excel() -> pd.DataFrame:
    return _read_derived_all()


def add_keyword(keyword: str, month: str, source: str = "manual") -> bool:
    df  = _read_derived_all()
    dup = ((df["keyword"] == keyword) & (df["kpi_month"] == month)) if len(df) > 0 else pd.Series([False])
    if dup.any():
        return False
    now     = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    new_row = pd.DataFrame([[keyword, month, "0", source, now]], columns=DERIVED_COLS)
    df      = pd.concat([df, new_row], ignore_index=True)
    _write_derived(df, f"키워드 추가: {keyword} ({month})")
    return True


def save_reflected(df_display: pd.DataFrame):
    """data_editor 결과(한글 컬럼)를 저장 — GitHub 또는 로컬"""
    all_df = _read_derived_all()
    for _, row in df_display.iterrows():
        mask = (
            (all_df["keyword"]   == row["키워드"]) &
            (all_df["kpi_month"] == row["월"])
        )
        all_df.loc[mask, "reflected"] = "1" if row["반영"] else "0"
    _write_derived(all_df, f"반영 상태 업데이트 ({datetime.now().strftime('%Y-%m-%d %H:%M')})")


def delete_keyword(keyword: str, month: str):
    df = _read_derived_all()
    df = df[~((df["keyword"] == keyword) & (df["kpi_month"] == month))]
    _write_derived(df, f"키워드 삭제: {keyword} ({month})")


# ──────────────────────────────────────────────────────
# 추적 키워드 CRUD — GitHub 연동 또는 로컬 파일
# ──────────────────────────────────────────────────────

@st.cache_data(ttl=30)
def _load_tracked_from_github() -> pd.DataFrame:
    df = gh.read_csv("data/tracked_keywords.csv")
    return df if df is not None else pd.DataFrame(columns=TRACKED_COLS)


def _read_tracked_all() -> pd.DataFrame:
    if gh.is_configured():
        return _load_tracked_from_github()
    if not os.path.exists(TRACKED_CSV):
        ensure_data()
    df = pd.read_csv(TRACKED_CSV, dtype=str)
    for col in TRACKED_COLS:
        if col not in df.columns:
            df[col] = ""
    return df


def _write_tracked(df: pd.DataFrame, message: str):
    if gh.is_configured():
        ok = gh.write_csv(df, "data/tracked_keywords.csv", message)
        if ok:
            _load_tracked_from_github.clear()
    else:
        df.to_csv(TRACKED_CSV, index=False, encoding="utf-8-sig")


def load_tracked_keywords() -> list:
    df = _read_tracked_all()
    return df["keyword"].dropna().tolist() if not df.empty else []


def add_tracked_keyword(keyword: str) -> bool:
    """추적 키워드 추가. 중복이면 False 반환."""
    df = _read_tracked_all()
    if keyword in df["keyword"].tolist():
        return False
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    new_row = pd.DataFrame([[keyword, now]], columns=TRACKED_COLS)
    df = pd.concat([df, new_row], ignore_index=True)
    _write_tracked(df, f"추적 키워드 추가: {keyword}")
    return True


def remove_tracked_keyword(keyword: str):
    df = _read_tracked_all()
    df = df[df["keyword"] != keyword]
    _write_tracked(df, f"추적 키워드 삭제: {keyword}")


# ──────────────────────────────────────────────────────
# 트렌드 데이터 로드 (1분 캐시)
# ──────────────────────────────────────────────────────
@st.cache_data(ttl=60)
def load_trends() -> pd.DataFrame:
    if not os.path.exists(TRENDS_CSV):
        return pd.DataFrame()
    df = pd.read_csv(TRENDS_CSV)
    df["date"] = pd.to_datetime(df["date"])
    return df


def to_weekly(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["주차"] = df["date"].dt.to_period("W").apply(lambda p: p.start_time)
    return (
        df.groupby(["주차", "keyword"])["ratio"]
        .mean().reset_index()
        .rename(columns={"keyword": "키워드", "ratio": "평균 관심도"})
    )


def draw_chart(df_weekly: pd.DataFrame) -> None:
    fig = px.line(
        df_weekly, x="주차", y="평균 관심도", color="키워드",
        markers=True, line_shape="spline", height=360,
        color_discrete_sequence=px.colors.qualitative.Set2,
    )
    fig.update_layout(
        plot_bgcolor="white", paper_bgcolor="white",
        font_family="Malgun Gothic, Apple SD Gothic Neo, sans-serif",
        legend_title_text="키워드",
        xaxis_title="주차", yaxis_title="관심도 (0~100)",
        yaxis=dict(range=[0, 105], gridcolor="#f0f0f0"),
        xaxis=dict(gridcolor="#f0f0f0"),
        margin=dict(l=10, r=10, t=10, b=10),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    fig.update_traces(line_width=2.5, marker_size=6)
    st.plotly_chart(fig, use_container_width=True)


def _hex_to_rgba(hex_color: str, alpha: float = 0.13) -> str:
    """#RRGGBB → rgba(r,g,b,alpha) 변환. Plotly fill에 사용."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def make_sparkline(series: pd.Series, color: str) -> go.Figure:
    """스파크라인: 작은 추이선 그래프 (축·레전드 없음)."""
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=list(range(len(series))),
        y=series.values,
        mode="lines",
        line=dict(color=color, width=2),
        fill="tozeroy",
        fillcolor=_hex_to_rgba(color, 0.13),
    ))
    fig.update_layout(
        height=55,
        margin=dict(l=0, r=0, t=2, b=2),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
        xaxis=dict(visible=False, fixedrange=True),
        yaxis=dict(visible=False, fixedrange=True),
    )
    return fig


def compute_change(df_kw: pd.DataFrame) -> tuple:
    """
    기간 전반부 평균 대비 후반부 평균 변화율을 계산합니다.
    반환: (변화율 % | None, 날짜순 ratio 시리즈)
    """
    if df_kw.empty:
        return None, pd.Series(dtype=float)
    s = df_kw.sort_values("date")["ratio"].reset_index(drop=True)
    if len(s) < 4:
        return None, s
    half      = len(s) // 2
    first_avg = s.iloc[:half].mean()
    last_avg  = s.iloc[half:].mean()
    if first_avg == 0:
        change = None
    else:
        change = (last_avg - first_avg) / first_avg * 100
    return change, s


def change_badge(pct) -> str:
    """변화율을 ▲/▼ 뱃지 HTML로 반환."""
    if pct is None:
        return "<span style='color:#aaa'>—</span>"
    color = "#2e7d32" if pct >= 0 else "#c62828"
    arrow = "▲" if pct >= 0 else "▼"
    return f"<span style='color:{color};font-weight:700'>{arrow} {abs(pct):.0f}%</span>"


# ──────────────────────────────────────────────────────
# 뉴스 키워드 (1시간 캐시)
# ──────────────────────────────────────────────────────
@st.cache_data(ttl=3600, persist="disk")
def get_news_keywords():
    return fetch_news_keywords(top_n=20)


# ──────────────────────────────────────────────────────
# 엑셀 내보내기
# ──────────────────────────────────────────────────────
def build_excel() -> bytes:
    df_all = load_derived_all_for_excel()

    if df_all.empty:
        df_summary = pd.DataFrame(columns=["월", "도출 건수", "반영 건수", "반영률(%)"])
    else:
        df_all["reflected_bool"] = df_all["reflected"].astype(str).str.lower().isin(["1", "true", "yes"])
        grp = df_all.groupby("kpi_month")
        df_summary = grp.agg(
            도출건수=("keyword", "count"),
            반영건수=("reflected_bool", "sum"),
        ).reset_index()
        df_summary.columns = ["월", "도출 건수", "반영 건수"]
        df_summary["반영률(%)"] = (
            df_summary["반영 건수"] / df_summary["도출 건수"] * 100
        ).round(1)
        df_summary["KPI 달성"] = df_summary.apply(
            lambda r: "달성" if r["도출 건수"] >= 5 and r["반영률(%)"] >= 70 else "미달성", axis=1
        )

    df_detail = df_all.rename(columns={
        "keyword": "키워드", "kpi_month": "월", "reflected": "반영",
        "source": "출처", "added_at": "도출일",
    }) if not df_all.empty else pd.DataFrame()

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df_summary.to_excel(writer, sheet_name="월별 KPI 요약", index=False)
        if not df_detail.empty:
            df_detail.to_excel(writer, sheet_name="키워드 상세", index=False)
    return buf.getvalue()


# ══════════════════════════════════════════════════════
# 메인 화면
# ══════════════════════════════════════════════════════
ensure_data()

# ── 헤더 바 ──────────────────────────────────────────
_now_str    = datetime.now().strftime("%Y.%m.%d %H:%M")
_sync_label = "GitHub 동기화" if gh.is_configured() else "로컬 모드"
st.markdown(f"""
<div class="dash-header">
  <div class="dash-logo">
    <div class="dash-logo-mark">K</div>
    <div class="dash-logo-text">
      <div class="dt">키워드 인텔리전스</div>
      <div class="ds">IT·보안 키워드 트렌드 & KPI 대시보드 · SCK/STK Corp</div>
    </div>
  </div>
  <div class="dash-meta">
    <span>기준월 <strong>{CURRENT_MONTH}</strong></span>
    <span>업데이트 {_now_str}</span>
    <span>{_sync_label}</span>
    <span class="dash-live">라이브</span>
  </div>
</div>
""", unsafe_allow_html=True)

# ── KPI 자동 계산 ────────────────────────────────────
df_cur          = load_derived(CURRENT_MONTH)
KPI_DERIVED     = len(df_cur)
KPI_REFLECTED   = int(df_cur["반영"].sum()) if not df_cur.empty else 0
KPI_TARGET_D    = 5
KPI_TARGET_R    = 70
reflection_rate = round(KPI_REFLECTED / KPI_DERIVED * 100) if KPI_DERIVED > 0 else 0
kpi_pass        = (KPI_DERIVED >= KPI_TARGET_D) and (reflection_rate >= KPI_TARGET_R)

# ── KPI 카드 3개 ──────────────────────────────────────
c1, c2, c3 = st.columns(3, gap="medium")

with c1:
    pct1 = min(int(KPI_DERIVED / KPI_TARGET_D * 100), 100)
    st.markdown(f"""
    <div class="kpi-card">
      <div class="kpi-label">이번 달 도출 키워드</div>
      <div class="kpi-value">{KPI_DERIVED}<span class="kpi-unit">건</span></div>
      <div class="kpi-target">목표 {KPI_TARGET_D}건 · 달성률 {pct1}%</div>
    </div>""", unsafe_allow_html=True)
    st.progress(min(KPI_DERIVED / KPI_TARGET_D, 1.0))

with c2:
    pct2 = min(int(reflection_rate / KPI_TARGET_R * 100), 100)
    st.markdown(f"""
    <div class="kpi-card">
      <div class="kpi-label">키워드 반영률</div>
      <div class="kpi-value">{reflection_rate}<span class="kpi-unit">%</span></div>
      <div class="kpi-target">목표 {KPI_TARGET_R}% · 반영 {KPI_REFLECTED} / 도출 {KPI_DERIVED}건</div>
    </div>""", unsafe_allow_html=True)
    st.progress(min(reflection_rate / KPI_TARGET_R, 1.0))

with c3:
    badge_cls  = "badge-pass" if kpi_pass else "badge-fail"
    badge_text = "달성" if kpi_pass else "진행 중"
    hint = "도출·반영 두 목표 모두 달성" if kpi_pass else (
        f"도출 {max(KPI_TARGET_D-KPI_DERIVED,0)}건 · "
        f"반영률 {max(KPI_TARGET_R-reflection_rate,0)}%p 부족"
    )
    st.markdown(f"""
    <div class="kpi-card">
      <div class="kpi-label">이번 달 KPI</div>
      <span class="{badge_cls}">{badge_text}</span>
      <div class="kpi-target" style="margin-top:12px">{hint}</div>
    </div>""", unsafe_allow_html=True)
    st.progress(1.0 if kpi_pass else max(reflection_rate / 100, 0.03))

st.markdown("<div style='margin-top:2rem'></div>", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════
# 섹션 1: 내 추적 키워드 관리 + 그래프
# ══════════════════════════════════════════════════════
st.markdown("""
<div class="sec-hdr">
  <div class="sh-t">추적 키워드</div>
  <div class="sh-s">칩 클릭 → 그래프 숨김/복원 &nbsp;·&nbsp; ✕ → 목록에서 삭제 &nbsp;·&nbsp; 추가하면 즉시 데이터 수집</div>
</div>""", unsafe_allow_html=True)

tracked_kws = load_tracked_keywords()

# ── 세션 상태: 잠깐 숨김 키워드 집합 ──────────────────
if "hidden_kws" not in st.session_state:
    st.session_state["hidden_kws"] = set()
# 삭제된 키워드가 hidden 집합에 남아있으면 정리
st.session_state["hidden_kws"] &= set(tracked_kws)

# ── 칩 렌더링 ─────────────────────────────────────────

if not tracked_kws:
    st.info("추적 중인 키워드가 없습니다. 아래에서 추가해 주세요.")
else:
    CHIPS_PER_ROW = 4
    for row_start in range(0, len(tracked_kws), CHIPS_PER_ROW):
        batch = tracked_kws[row_start : row_start + CHIPS_PER_ROW]
        # 칩당 [키워드 버튼(넓이 3) | ✕ 버튼(넓이 0.45)] × n + 빈 공간
        widths = []
        for _ in batch:
            widths += [3, 0.45]
        widths.append(max(0.1, 14 - sum(widths)))   # 우측 빈 공간
        cols = st.columns(widths)

        for j, kw in enumerate(batch):
            is_hidden = kw in st.session_state["hidden_kws"]
            chip_label = f"○ {kw}" if is_hidden else f"● {kw}"
            chip_help  = "다시 클릭하면 그래프에 복원됩니다" if is_hidden else "클릭하면 그래프에서 잠깐 숨깁니다"

            with cols[j * 2]:
                if st.button(chip_label, key=f"chip_toggle_{kw}",
                             use_container_width=True, help=chip_help):
                    if is_hidden:
                        st.session_state["hidden_kws"].discard(kw)
                    else:
                        st.session_state["hidden_kws"].add(kw)
                    st.rerun()

            with cols[j * 2 + 1]:
                if st.button("✕", key=f"chip_del_{kw}",
                             help=f"'{kw}'를 추적 목록에서 완전 삭제",
                             type="secondary"):
                    remove_tracked_keyword(kw)
                    st.session_state["hidden_kws"].discard(kw)
                    st.rerun()

# ── 새 키워드 추가 UI ──────────────────────────────────
st.markdown("")
col_add_in, col_add_btn = st.columns([5, 1])
with col_add_in:
    new_track_kw = st.text_input(
        "새 추적 키워드", placeholder="예: 제로트러스트  (입력 후 ＋ 추가 클릭)",
        label_visibility="collapsed", key="new_track_input",
    )
with col_add_btn:
    if st.button("＋ 추가", use_container_width=True, type="primary", key="btn_track_add"):
        kw = new_track_kw.strip()
        if not kw:
            st.warning("키워드를 입력해 주세요.")
        elif not add_tracked_keyword(kw):
            st.info(f"'{kw}'는 이미 추적 중입니다.")
        else:
            with st.spinner(f"'{kw}' 데이터 수집 중…"):
                naver_ok, google_ok = collect_single_keyword(kw)
                load_trends.clear()
            msgs = []
            msgs.append("네이버 ✅" if naver_ok else "네이버 ⚠️ (키 확인 필요)")
            msgs.append("구글 ✅" if google_ok else "구글은 다음 수집 때 채워집니다")
            st.success(f"'{kw}' 추가 완료 — {' / '.join(msgs)}")
            st.rerun()

st.markdown("")

# ── 기간 선택 버튼 (7일 / 30일 / 90일) ─────────────────
if "period_days" not in st.session_state:
    st.session_state["period_days"] = 30

PERIOD_OPTIONS = {"7일": 7, "30일": 30, "90일": 90}
p_cols = st.columns([1, 1, 1, 9])
for col, (label, days) in zip(p_cols, PERIOD_OPTIONS.items()):
    with col:
        btn_type = "primary" if st.session_state["period_days"] == days else "secondary"
        if st.button(label, key=f"period_{days}", type=btn_type, use_container_width=True):
            st.session_state["period_days"] = days
            st.rerun()

period_days = st.session_state["period_days"]
cutoff      = pd.Timestamp.today().normalize() - pd.Timedelta(days=period_days)

# ── 주간 검색 관심도 그래프 (추적 키워드 중 숨김 제외) ─
active_kws = [kw for kw in tracked_kws if kw not in st.session_state["hidden_kws"]]
df_trends  = load_trends()

if df_trends.empty:
    st.warning("data/trends.csv 에 데이터가 없습니다. 터미널에서 `python collector.py` 를 먼저 실행해 주세요.")
elif not active_kws:
    st.info("모든 키워드가 숨김 상태입니다. 칩을 다시 클릭해서 복원하세요.")
else:
    df_period   = df_trends[(df_trends["keyword"].isin(active_kws)) & (df_trends["date"] >= cutoff)]
    df_naver    = df_period[df_period["source"] == "naver"]
    df_google   = df_period[df_period["source"] == "google"]

    col_n, col_g = st.columns(2, gap="medium")
    with col_n:
        st.markdown('<div class="src-naver">네이버 데이터랩 — 검색 트렌드</div>', unsafe_allow_html=True)
        st.markdown('<div class="chart-hint">국내 검색 기준 · 0~100 상대 지수 · 인스타그램 기획 참고</div>', unsafe_allow_html=True)
        if not df_naver.empty:
            draw_chart(to_weekly(df_naver))
            with st.expander("네이버 원본 데이터"):
                s = df_naver.copy(); s["date"] = s["date"].dt.strftime("%Y-%m-%d")
                st.dataframe(s[["keyword","date","ratio"]].rename(columns={"keyword":"키워드","date":"날짜","ratio":"관심도"}).sort_values("날짜", ascending=False).head(40), use_container_width=True, hide_index=True)
        else:
            st.info("선택 기간에 네이버 데이터가 없습니다.")

    with col_g:
        st.markdown('<div class="src-google">구글 트렌드 — 검색 트렌드</div>', unsafe_allow_html=True)
        st.markdown('<div class="chart-hint">국내·글로벌 검색 기준 · 0~100 상대 지수 · 링크드인 기획 참고</div>', unsafe_allow_html=True)
        if not df_google.empty:
            draw_chart(to_weekly(df_google))
            with st.expander("구글 원본 데이터"):
                g = df_google.copy(); g["date"] = g["date"].dt.strftime("%Y-%m-%d")
                st.dataframe(g[["keyword","date","ratio"]].rename(columns={"keyword":"키워드","date":"날짜","ratio":"관심도"}).sort_values("날짜", ascending=False).head(40), use_container_width=True, hide_index=True)
        else:
            st.info("선택 기간에 구글 데이터가 없습니다.")

    st.caption("⚠️ 네이버(일별)와 구글(주별)은 집계 기준이 달라 직접 비교하지 마세요.")

    # ── 키워드별 추이 요약 표 (스파크라인 + ▲▼) ────────────
    st.markdown("<div style='margin-top:1.5rem'></div>", unsafe_allow_html=True)
    st.markdown(f"""
<div class="sec-hdr">
  <div class="sh-t">키워드별 추이 요약</div>
  <div class="sh-s">최근 {period_days}일 · 전반부 대비 후반부 변화율 · 데이터 부족 시 표시</div>
</div>""", unsafe_allow_html=True)

    # 헤더 행
    hdr = st.columns([2.2, 3.5, 1.2, 3.5, 1.2])
    for h, txt in zip(hdr, ["키워드", "네이버 추이", "변화", "구글 추이", "변화"]):
        h.markdown(f"<span class='spark-hdr'>{txt}</span>", unsafe_allow_html=True)

    st.markdown("<hr style='margin:4px 0 8px;'>", unsafe_allow_html=True)

    for kw in active_kws:
        row_n = df_period[(df_period["keyword"] == kw) & (df_period["source"] == "naver")]
        row_g = df_period[(df_period["keyword"] == kw) & (df_period["source"] == "google")]

        c0, c1, c2, c3, c4 = st.columns([2.2, 3.5, 1.2, 3.5, 1.2])

        with c0:
            st.markdown(f"<span style='font-weight:600'>{kw}</span>", unsafe_allow_html=True)

        with c1:
            n_change, n_series = compute_change(row_n)
            if len(n_series) >= 3:
                st.plotly_chart(
                    make_sparkline(n_series, "#03c75a"),
                    use_container_width=True,
                    config={"displayModeBar": False},
                    key=f"spark_n_{kw}_{period_days}",
                )
            else:
                st.caption("데이터 부족")

        with c2:
            st.markdown(change_badge(n_change), unsafe_allow_html=True)

        with c3:
            g_change, g_series = compute_change(row_g)
            if len(g_series) >= 3:
                st.plotly_chart(
                    make_sparkline(g_series, "#ea4335"),
                    use_container_width=True,
                    config={"displayModeBar": False},
                    key=f"spark_g_{kw}_{period_days}",
                )
            else:
                st.caption("데이터 부족")

        with c4:
            st.markdown(change_badge(g_change), unsafe_allow_html=True)

        st.markdown("<hr style='margin:4px 0;border-color:#f0f0f0'>", unsafe_allow_html=True)

st.markdown("<div style='margin-top:2.5rem'></div>", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════
# 섹션 2: 이번 주 급상승 키워드 발굴
# ══════════════════════════════════════════════════════
st.markdown("""
<div class="sec-hdr">
  <div class="sh-t">급상승 키워드 발굴</div>
  <div class="sh-s">구글 뉴스 기사 빈도 기반 · 매 시간 자동 갱신 · 위 검색 트렌드 그래프와 별개입니다</div>
</div>""", unsafe_allow_html=True)

with st.spinner("IT 뉴스에서 키워드를 분석 중…"):
    news_kws, sources_ok = get_news_keywords()

st.caption(f"📰 {sources_ok}  |  1시간마다 자동 갱신" if news_kws else "뉴스에 연결하지 못했습니다.")

if news_kws:
    tracked_set  = set(tracked_kws)
    derived_set  = set(df_cur["키워드"].tolist()) if not df_cur.empty else set()
    cols_per_row = 4
    rows         = [news_kws[i:i+cols_per_row] for i in range(0, len(news_kws), cols_per_row)]

    for row in rows:
        cols = st.columns(cols_per_row, gap="small")
        for col, (word, count) in zip(cols, row):
            with col:
                with st.container(border=True):
                    is_tracking = word in tracked_set
                    is_derived  = word in derived_set
                    st.markdown(
                        f"**{word}** &nbsp;<span style='color:#aaa;font-size:.8rem'>{count}회</span>",
                        unsafe_allow_html=True,
                    )
                    if is_tracking:
                        st.caption("📌 추적 중")
                    else:
                        if st.button("📌 추적에 추가", key=f"track_{word}",
                                     use_container_width=True, type="primary"):
                            add_tracked_keyword(word)
                            with st.spinner(f"'{word}' 수집 중…"):
                                naver_ok, google_ok = collect_single_keyword(word)
                                load_trends.clear()
                            msg  = "네이버 ✅" if naver_ok else "네이버 ⚠️"
                            msg += " / 구글 ✅" if google_ok else " / 구글은 다음 수집 때"
                            st.success(f"'{word}' 추적 시작! {msg}")
                            st.rerun()
                    if not is_derived:
                        if st.button("＋ 도출에 추가", key=f"derive_{word}", use_container_width=True):
                            ok = add_keyword(word, CURRENT_MONTH, source="뉴스 자동탐지")
                            st.success(f"'{word}' 도출 추가!") if ok else st.info("이미 도출됨")
                            if ok: st.rerun()
                    else:
                        st.caption("✅ 도출됨")
else:
    st.info("뉴스 데이터를 불러오지 못했습니다.")

with st.expander("✏️ 도출 키워드 직접 입력해서 추가하기"):
    col_input, col_btn = st.columns([4, 1])
    with col_input:
        manual_kw = st.text_input("키워드 입력", placeholder="예: 제로트러스트", label_visibility="collapsed")
    with col_btn:
        if st.button("추가", use_container_width=True):
            if manual_kw.strip():
                ok = add_keyword(manual_kw.strip(), CURRENT_MONTH, source="직접 입력")
                st.success(f"'{manual_kw.strip()}' 추가됐습니다!") if ok else st.warning("이미 추가된 키워드입니다.")
                if ok: st.rerun()
            else:
                st.warning("키워드를 입력해 주세요.")

_trend_cnt = len(pd.read_csv(TRENDS_CSV)) if os.path.exists(TRENDS_CSV) else 0
st.markdown(f"""
<div style="margin-top:3rem;padding-top:1.5rem;border-top:1px solid #E2E8F0;
            display:flex;justify-content:space-between;align-items:center;
            font-size:11px;color:#94A3B8;">
  <span>키워드 인텔리전스 · SCK/STK Corp · {CURRENT_MONTH}</span>
  <span>데이터 {_trend_cnt:,}건 · 네이버 데이터랩 · 구글 트렌드</span>
</div>""", unsafe_allow_html=True)
