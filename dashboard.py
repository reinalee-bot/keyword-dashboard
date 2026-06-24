"""
키워드 트렌드 KPI 대시보드 — CSV 저장 방식
  data/trends.csv           : 네이버·구글 검색 트렌드 데이터
  data/derived_keywords.csv : 도출 키워드 관리 (활용처·상태·벤더·아이디어)
  data/applied_content.csv  : 반영 콘텐츠 (보도자료·기획기사·SNS 게시물 등)
  data/tracked_keywords.csv : 추적 키워드 목록

GitHub 연동(GITHUB_TOKEN + GITHUB_REPO 설정 시):
  - CSV 읽기·쓰기를 GitHub API로 처리
  - 팀 누구나 수정 → GitHub 커밋 → 영구 보존
"""

import io
import os
import re
from datetime import datetime, date, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests as _requests
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
CONTENT_CSV  = os.path.join(DATA_DIR, "applied_content.csv")
TRACKED_CSV  = os.path.join(DATA_DIR, "tracked_keywords.csv")

# (가) 도출 키워드 컬럼
DERIVED_COLS = [
    "keyword", "kpi_month", "usage_type", "status",
    "vendor", "idea", "source_url", "discovery_source", "added_at",
]
# (나) 적용 콘텐츠 컬럼
CONTENT_COLS = [
    "keyword", "kpi_month", "content_type",
    "content_name", "url", "published_at", "added_at",
]
TRENDS_COLS  = ["keyword", "date", "ratio", "source", "collected_at"]
TRACKED_COLS = ["keyword", "added_at"]

CURRENT_MONTH = datetime.today().strftime("%Y-%m")

st.set_page_config(
    page_title="키워드 인텔리전스 | SCK·STK",
    page_icon="📊",
    layout="wide",
)

# ── CSS ──────────────────────────────────────────────
st.markdown("""
<style>
/* ────────────────────────────────────────────────
   색상 체계 (전체 테마)
   메인:   #2563EB (블루)
   배경:   #F8FAFC / #ffffff
   텍스트: #0F172A (짙은 네이비) / #64748B (보조) / #94A3B8 (힌트)
   테두리: #E2E8F0 (연한 회색)
   주황:   #9A3412 / #FFF7ED — KPI 목표 미달·경고에만 사용
   빨강:   #DC2626 — 삭제·오류에만 사용
──────────────────────────────────────────────── */

/* ── Streamlit 기본 여백·헤더 제거 ── */
#MainMenu { visibility: hidden; }
footer    { visibility: hidden; }
.stApp > header { display: none; }
[data-testid="stToolbar"]    { display: none !important; }
[data-testid="stDecoration"] { display: none !important; }
.block-container {
    max-width: 1400px !important;
    padding: 0 2rem 4rem !important;
    margin: 0 auto !important;
}

/* 한글 단어 중간 줄바꿈 방지 */
* { word-break: keep-all; }

/* ── 전체 배경 ── */
.stApp { background: #F8FAFC; }

/* ═══════════════════════════════════════
   상단 슬림 네비바
═══════════════════════════════════════ */
.dash-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    background: #ffffff;
    border-bottom: 1px solid #E2E8F0;
    padding: 10px 2rem;
    margin: 0 -2rem 0 -2rem;
}
.dash-logo { display: flex; align-items: center; gap: 8px; }
.dash-logo-mark {
    width: 26px; height: 26px;
    background: #2563EB; border-radius: 6px;
    display: flex; align-items: center; justify-content: center;
    color: white; font-size: 13px; font-weight: 700; flex-shrink: 0;
}
.dash-logo-text .dt { font-size: 13px; font-weight: 700; color: #0F172A; }
.dash-meta { display: flex; align-items: center; gap: 16px; font-size: 11.5px; color: #64748B; }
.dash-live {
    display: flex; align-items: center; gap: 5px;
    background: #F0FDF4; color: #166534;
    padding: 3px 10px; border-radius: 20px; font-weight: 600; font-size: 11px;
}
.dash-live::before { content: "●"; font-size: 8px; color: #16A34A; }

/* ═══════════════════════════════════════
   페이지 타이틀
═══════════════════════════════════════ */
.page-hero {
    padding: 1.8rem 0 1.5rem;
    border-bottom: 1px solid #E2E8F0;
    margin-bottom: 2rem;
}
.page-hero-title {
    font-size: 1.7rem; font-weight: 800; color: #0F172A;
    margin: 0 0 0.5rem; line-height: 1.25; letter-spacing: -0.01em;
}
.page-hero-desc { font-size: 0.95rem; color: #64748B; margin: 0; line-height: 1.5; }

/* ═══════════════════════════════════════
   섹션 헤더
═══════════════════════════════════════ */
.sec-hdr-main {
    margin: 0 0 1.5rem 0;
    padding-bottom: 0.75rem;
    border-bottom: 2px solid #2563EB;
}
.sec-hdr-main .sh-t { font-size: 1.1rem; font-weight: 800; color: #0F172A; margin: 0; line-height: 1.3; }
.sec-hdr-main .sh-s { font-size: 12.5px; color: #64748B; margin: 4px 0 0; line-height: 1.5; }

.sec-hdr { border-left: 3px solid #2563EB; padding-left: 12px; margin: 0 0 14px 0; }
.sec-hdr .sh-t { font-size: 15px; font-weight: 700; color: #0F172A; margin: 0; line-height: 1.3; }
.sec-hdr .sh-s { font-size: 12px; color: #94A3B8; margin: 3px 0 0; line-height: 1.4; }

/* ═══════════════════════════════════════
   KPI 카드
═══════════════════════════════════════ */
.kpi-card {
    background: white; border: 1px solid #E2E8F0;
    border-radius: 10px; padding: 20px 22px 18px;
}
.kpi-label {
    font-size: 10.5px; font-weight: 700; color: #94A3B8;
    text-transform: uppercase; letter-spacing: .07em; margin-bottom: 10px;
}
.kpi-value { font-size: 2.6rem; font-weight: 700; color: #0F172A; line-height: 1; }
.kpi-unit  { font-size: .95rem; font-weight: 400; color: #94A3B8; margin-left: 3px; }
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
   반영 현황 표
═══════════════════════════════════════ */
.kw-table-hdr {
    font-size: 11px; font-weight: 700; color: #64748B;
    text-transform: uppercase; letter-spacing: .05em; padding: 0 4px;
}
.kw-cell { padding: 2px 4px; font-size: 13.5px; line-height: 1.6; }
.status-done {
    display: inline-block; background: #EFF6FF; color: #1D4ED8;
    border-radius: 4px; padding: 2px 8px; font-size: 11.5px; font-weight: 600;
}
.status-todo {
    display: inline-block; background: #F1F5F9; color: #475569;
    border-radius: 4px; padding: 2px 8px; font-size: 11.5px; font-weight: 600;
}
.usage-tag-pr {
    display: inline-block; background: #EFF6FF; color: #1e40af;
    border-radius: 4px; padding: 2px 8px; font-size: 11.5px; font-weight: 600;
}
.usage-tag-owned {
    display: inline-block; background: #FDF4FF; color: #7e22ce;
    border-radius: 4px; padding: 2px 8px; font-size: 11.5px; font-weight: 600;
}
.usage-tag-common {
    display: inline-block; background: #F0FDF4; color: #166534;
    border-radius: 4px; padding: 2px 8px; font-size: 11.5px; font-weight: 600;
}
.usage-tag-none {
    display: inline-block; background: #F1F5F9; color: #94A3B8;
    border-radius: 4px; padding: 2px 8px; font-size: 11.5px; font-weight: 600;
}

/* ═══════════════════════════════════════
   그래프
═══════════════════════════════════════ */
.src-naver  { font-size: 12px; font-weight: 700; color: #059669; }
.src-google { font-size: 12px; font-weight: 700; color: #DC2626; }
.chart-hint { font-size: 11px; color: #94A3B8; margin: 2px 0 6px; }

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
div[data-testid*="chip_del"] button,
div[data-key*="chip_del"] button {
    color: #DC2626 !important;
    border-color: #FCA5A5 !important;
    background: white !important;
}
div[data-testid*="chip_del"] button:hover,
div[data-key*="chip_del"] button:hover { background: #FEF2F2 !important; }

/* ═══════════════════════════════════════
   기타
═══════════════════════════════════════ */
hr { border-color: #E2E8F0 !important; margin: 1.5rem 0 !important; }
.stProgress > div > div { background: #2563EB !important; }
.spark-hdr { font-size: 11px; font-weight: 700; color: #64748B; text-transform: uppercase; letter-spacing: .05em; }
.section-title { font-size:1.1rem; font-weight:700; color:#0F172A; margin:0 0 4px 0; }

/* ═══════════════════════════════════════
   모바일 반응형
═══════════════════════════════════════ */
@media (max-width: 768px) {
    .block-container { padding: 0 1rem 3rem !important; }
    .dash-header { padding: 10px 1rem; margin: 0 -1rem; flex-wrap: wrap; gap: 8px; }
    .dash-meta { gap: 10px; flex-wrap: wrap; }
    .page-hero-title { font-size: 1.3rem; }
    .kpi-card { padding: 14px 16px; }
    .kpi-value { font-size: 2rem; }
}
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════
# 데이터 초기화 — 파일 없으면 생성, 구버전이면 마이그레이션
# ══════════════════════════════════════════════════════
def ensure_data():
    os.makedirs(DATA_DIR, exist_ok=True)

    if not os.path.exists(TRENDS_CSV):
        pd.DataFrame(columns=TRENDS_COLS).to_csv(TRENDS_CSV, index=False, encoding="utf-8-sig")

    # derived_keywords.csv — 새 컬럼 구조로 마이그레이션 + NaN 정리
    if not os.path.exists(DERIVED_CSV):
        pd.DataFrame(columns=DERIVED_COLS).to_csv(DERIVED_CSV, index=False, encoding="utf-8-sig")
    else:
        try:
            df = pd.read_csv(DERIVED_CSV, dtype=str).fillna("")
        except Exception:
            df = pd.DataFrame(columns=DERIVED_COLS)

        changed = False
        if "usage_type" not in df.columns:
            df["usage_type"] = ""; changed = True
        if "status" not in df.columns:
            if "reflected" in df.columns:
                df["status"] = df["reflected"].apply(
                    lambda x: "반영완료" if str(x).strip() in ["1", "true", "True"] else "도출"
                )
            else:
                df["status"] = "도출"
            changed = True
        if "vendor" not in df.columns:
            df["vendor"] = ""; changed = True
        if "idea" not in df.columns:
            df["idea"] = ""; changed = True
        if "source_url" not in df.columns:
            df["source_url"] = ""; changed = True
        if "discovery_source" not in df.columns:
            df["discovery_source"] = df["source"] if "source" in df.columns else "직접 입력"
            changed = True

        # 항상 NaN 제거 후 저장 (컬럼 변경 여부와 관계없이)
        for col in DERIVED_COLS:
            if col not in df.columns:
                df[col] = ""
        df[DERIVED_COLS].fillna("").to_csv(DERIVED_CSV, index=False, encoding="utf-8-sig")

    if not os.path.exists(CONTENT_CSV):
        pd.DataFrame(columns=CONTENT_COLS).to_csv(CONTENT_CSV, index=False, encoding="utf-8-sig")

    if not os.path.exists(TRACKED_CSV):
        try:
            from keywords import KEYWORDS as _default_kws
        except ImportError:
            _default_kws = []
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        pd.DataFrame([[kw, now] for kw in _default_kws], columns=TRACKED_COLS).to_csv(
            TRACKED_CSV, index=False, encoding="utf-8-sig"
        )


# ══════════════════════════════════════════════════════
# (가) 도출 키워드 CRUD
# ══════════════════════════════════════════════════════

@st.cache_data(ttl=30)
def _load_derived_from_github() -> pd.DataFrame:
    df = gh.read_csv("data/derived_keywords.csv")
    return df if df is not None else pd.DataFrame(columns=DERIVED_COLS)


def _read_derived_all() -> pd.DataFrame:
    if gh.is_configured():
        df = _load_derived_from_github()
    elif not os.path.exists(DERIVED_CSV):
        return pd.DataFrame(columns=DERIVED_COLS)
    else:
        try:
            df = pd.read_csv(DERIVED_CSV, dtype=str)
        except Exception:
            return pd.DataFrame(columns=DERIVED_COLS)

    # NaN → 빈 문자열, 누락 컬럼 → 빈 문자열 (구버전 CSV·GitHub 캐시 모두 대응)
    df = df.fillna("")
    for col in DERIVED_COLS:
        if col not in df.columns:
            df[col] = ""
    return df


def _write_derived(df: pd.DataFrame, message: str) -> bool:
    if gh.is_configured():
        ok = gh.write_csv(df, "data/derived_keywords.csv", message)
        if ok:
            _load_derived_from_github.clear()
        return ok
    df[DERIVED_COLS].to_csv(DERIVED_CSV, index=False, encoding="utf-8-sig")
    return True


def load_derived(month: str) -> pd.DataFrame:
    """이번 달 도출 키워드. 구버전·신버전 CSV 모두 안전하게 처리."""
    _TARGET = ["키워드", "활용처", "상태", "벤더", "아이디어", "출처URL", "등록출처", "등록일"]

    df = _read_derived_all()
    if df.empty or "kpi_month" not in df.columns:
        return pd.DataFrame(columns=_TARGET)

    df = df[df["kpi_month"] == month].copy()

    # 이중 안전장치: 내부 컬럼명이 빠져있으면 빈 값 보충
    _DEFAULTS = {
        "keyword": "", "kpi_month": month, "usage_type": "",
        "status": "도출", "vendor": "", "idea": "",
        "source_url": "", "discovery_source": "직접 입력", "added_at": "",
    }
    for col, val in _DEFAULTS.items():
        if col not in df.columns:
            df[col] = val

    df = df.rename(columns={
        "keyword": "키워드", "kpi_month": "월", "usage_type": "활용처",
        "status": "상태", "vendor": "벤더", "idea": "아이디어",
        "source_url": "출처URL", "discovery_source": "등록출처", "added_at": "등록일",
    })

    # reindex: 컬럼이 없어도 빈 문자열로 채워서 KeyError 방지
    return df.reindex(columns=_TARGET, fill_value="").reset_index(drop=True)


def add_keyword(keyword: str, month: str, usage_type: str = "",
                vendor: str = "", idea: str = "", source_url: str = "",
                discovery_source: str = "직접 입력") -> bool:
    df = _read_derived_all()
    if not df.empty and ((df["keyword"] == keyword) & (df["kpi_month"] == month)).any():
        return False
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    new_row = pd.DataFrame(
        [[keyword, month, usage_type, "도출", vendor, idea, source_url, discovery_source, now]],
        columns=DERIVED_COLS,
    )
    df = pd.concat([df, new_row], ignore_index=True)
    _write_derived(df, f"키워드 추가: {keyword} ({month})")
    return True


def delete_keyword(keyword: str, month: str):
    df = _read_derived_all()
    df = df[~((df["keyword"] == keyword) & (df["kpi_month"] == month))]
    _write_derived(df, f"키워드 삭제: {keyword} ({month})")


def _update_keyword_status(keyword: str, month: str, status: str):
    df = _read_derived_all()
    mask = (df["keyword"] == keyword) & (df["kpi_month"] == month)
    if mask.any():
        df.loc[mask, "status"] = status
        _write_derived(df, f"상태 변경: {keyword} → {status}")


# ══════════════════════════════════════════════════════
# (나) 적용 콘텐츠 CRUD
# ══════════════════════════════════════════════════════

@st.cache_data(ttl=30)
def _load_content_from_github() -> pd.DataFrame:
    df = gh.read_csv("data/applied_content.csv")
    return df if df is not None else pd.DataFrame(columns=CONTENT_COLS)


def _read_content_all() -> pd.DataFrame:
    if gh.is_configured():
        return _load_content_from_github()
    if not os.path.exists(CONTENT_CSV):
        return pd.DataFrame(columns=CONTENT_COLS)
    df = pd.read_csv(CONTENT_CSV, dtype=str).fillna("")
    for col in CONTENT_COLS:
        if col not in df.columns:
            df[col] = ""
    return df


def _write_content(df: pd.DataFrame, message: str) -> bool:
    if gh.is_configured():
        ok = gh.write_csv(df, "data/applied_content.csv", message)
        if ok:
            _load_content_from_github.clear()
        return ok
    df[CONTENT_COLS].to_csv(CONTENT_CSV, index=False, encoding="utf-8-sig")
    return True


def load_content(month: str) -> pd.DataFrame:
    df = _read_content_all()
    if df.empty or "kpi_month" not in df.columns:
        return pd.DataFrame(columns=CONTENT_COLS)
    return df[df["kpi_month"] == month].copy().reset_index(drop=True)


def add_content(keyword: str, month: str, content_type: str,
                content_name: str, url: str, published_at: str) -> bool:
    df = _read_content_all()
    dup = (
        not df.empty
        and ((df["keyword"] == keyword) & (df["kpi_month"] == month) & (df["content_name"] == content_name)).any()
    )
    if dup:
        return False
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    new_row = pd.DataFrame(
        [[keyword, month, content_type, content_name, url, published_at, now]],
        columns=CONTENT_COLS,
    )
    df = pd.concat([df, new_row], ignore_index=True)
    _write_content(df, f"콘텐츠 등록: {keyword} — {content_name}")
    _update_keyword_status(keyword, month, "반영완료")
    return True


def delete_content_row(keyword: str, month: str, content_name: str):
    df = _read_content_all()
    df = df[~((df["keyword"] == keyword) & (df["kpi_month"] == month) & (df["content_name"] == content_name))]
    _write_content(df, f"콘텐츠 삭제: {keyword} — {content_name}")
    remaining = df[(df["keyword"] == keyword) & (df["kpi_month"] == month)]
    if remaining.empty:
        _update_keyword_status(keyword, month, "도출")


# ══════════════════════════════════════════════════════
# 추적 키워드 CRUD
# ══════════════════════════════════════════════════════

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


# ══════════════════════════════════════════════════════
# 트렌드 데이터 로드 (1분 캐시)
# ══════════════════════════════════════════════════════
@st.cache_data(ttl=3600 * 8)   # 8시간 캐시 — 매일 자동 수집 주기에 맞춤
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
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def make_sparkline(series: pd.Series, color: str) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=list(range(len(series))), y=series.values,
        mode="lines", line=dict(color=color, width=2),
        fill="tozeroy", fillcolor=_hex_to_rgba(color, 0.13),
    ))
    fig.update_layout(
        height=55, margin=dict(l=0, r=0, t=2, b=2),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
        xaxis=dict(visible=False, fixedrange=True),
        yaxis=dict(visible=False, fixedrange=True),
    )
    return fig


def compute_change(df_kw: pd.DataFrame) -> tuple:
    if df_kw.empty:
        return None, pd.Series(dtype=float)
    s = df_kw.sort_values("date")["ratio"].reset_index(drop=True)
    if len(s) < 4:
        return None, s
    half = len(s) // 2
    first_avg = s.iloc[:half].mean()
    last_avg  = s.iloc[half:].mean()
    change = None if first_avg == 0 else (last_avg - first_avg) / first_avg * 100
    return change, s


def change_badge(pct) -> str:
    if pct is None:
        return "<span style='color:#aaa'>—</span>"
    color = "#2e7d32" if pct >= 0 else "#c62828"
    arrow = "▲" if pct >= 0 else "▼"
    return f"<span style='color:{color};font-weight:700'>{arrow} {abs(pct):.0f}%</span>"


# ══════════════════════════════════════════════════════
# 뉴스 키워드 (1시간 캐시) — 급상승 키워드 발굴용
# ══════════════════════════════════════════════════════
@st.cache_data(ttl=3600, persist="disk")
def get_news_keywords():
    return fetch_news_keywords(top_n=20)


# ══════════════════════════════════════════════════════
# 이번 주 키워드 인사이트 — 네이버 뉴스 검색 API
# ══════════════════════════════════════════════════════
# 캐시 정책:
#   fetch_news_articles  → 24시간 캐시 (버튼 클릭 시에만 호출, 자동 호출 없음)
#   load_trends          → 8시간 캐시  (트렌드 그래프)
#   get_news_keywords    → 1시간 캐시  (급상승 키워드 발굴)
#   _read_derived_all 등 CRUD → 캐시 없음 (쓰기 후 즉시 반영 필요)

_NAVER_NEWS_URL = "https://openapi.naver.com/v1/search/news.json"

# 알려진 IT·보안 매체 도메인 → 한글 이름 매핑
_MEDIA_MAP: dict = {
    "chosun.com": "조선일보", "donga.com": "동아일보",
    "joongang.co.kr": "중앙일보", "khan.co.kr": "경향신문",
    "hani.co.kr": "한겨레", "mk.co.kr": "매일경제",
    "hankyung.com": "한국경제", "heraldcorp.com": "헤럴드경제",
    "yonhapnews.co.kr": "연합뉴스", "yna.co.kr": "연합뉴스",
    "zdnet.co.kr": "ZDNet Korea", "etnews.com": "전자신문",
    "dt.co.kr": "디지털타임스", "itworld.co.kr": "IT World",
    "ciokorea.com": "CIO Korea", "boannews.com": "보안뉴스",
    "datanet.co.kr": "데이터넷", "comworld.co.kr": "컴퓨터월드",
    "ahnlab.com": "안랩", "krcert.or.kr": "KISA",
    "securityweek.com": "Security Week", "theregister.com": "The Register",
}


def _media_name(url: str) -> str:
    """URL에서 매체명을 추출합니다."""
    try:
        host = urlparse(url).netloc.lower().replace("www.", "").replace("m.", "")
        for domain, name in _MEDIA_MAP.items():
            if domain in host:
                return name
        return host.split(".")[0].upper()
    except Exception:
        return "—"


def _strip_html(text: str) -> str:
    """HTML 태그를 제거합니다."""
    return re.sub(r"<[^>]+>", "", text or "").strip()


def _parse_pub_date(date_str: str) -> datetime:
    """네이버 뉴스 pubDate(RFC2822)를 datetime으로 변환합니다."""
    try:
        dt = parsedate_to_datetime(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return datetime.min.replace(tzinfo=timezone.utc)


def _similar_title(t1: str, t2: str) -> bool:
    """두 기사 제목이 80% 이상 겹치면 중복으로 봅니다."""
    t1, t2 = t1[:40].lower(), t2[:40].lower()
    if not t1 or not t2:
        return False
    common = sum(c in t2 for c in t1)
    return common / max(len(t1), 1) >= 0.8


@st.cache_data(ttl=86400, show_spinner=False)   # 24시간 캐시
def fetch_news_articles(keywords: tuple, days: int = 7) -> dict:
    """
    네이버 뉴스 검색 API로 키워드별 최신 기사를 가져옵니다.
    - keywords: 튜플 (캐시 키로 사용하려면 해시 가능해야 함)
    - 반환: {keyword: [{"title","media","date","summary","url"}, ...]}
    - 자동 호출 금지 — 버튼 클릭 시에만 호출하세요.
    """
    from dotenv import load_dotenv
    load_dotenv()
    cid = os.getenv("NAVER_CLIENT_ID", "").strip()
    csc = os.getenv("NAVER_CLIENT_SECRET", "").strip()

    if not cid or not csc:
        return {}

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    result: dict = {}

    for kw in keywords:
        articles: list = []
        seen_urls:   set = set()
        seen_titles: list = []
        try:
            resp = _requests.get(
                _NAVER_NEWS_URL,
                headers={"X-Naver-Client-Id": cid, "X-Naver-Client-Secret": csc},
                params={"query": kw, "display": 20, "sort": "date"},
                timeout=6,
            )
            if resp.status_code != 200:
                result[kw] = []
                continue

            items = resp.json().get("items", [])
            for item in items:
                pub_dt = _parse_pub_date(item.get("pubDate", ""))
                if pub_dt < cutoff:
                    continue

                url   = item.get("originallink") or item.get("link", "")
                title = _strip_html(item.get("title", ""))
                desc  = _strip_html(item.get("description", ""))

                # URL 중복 제거
                if url in seen_urls:
                    continue
                # 유사 제목 중복 제거
                if any(_similar_title(title, t) for t in seen_titles):
                    continue

                seen_urls.add(url)
                seen_titles.append(title)
                articles.append({
                    "title":   title,
                    "media":   _media_name(url),
                    "date":    pub_dt.strftime("%Y-%m-%d"),
                    "summary": desc[:120] + ("…" if len(desc) > 120 else ""),
                    "url":     url,
                    "_dt":     pub_dt,
                })
                if len(articles) >= 3:
                    break

        except Exception:
            articles = []

        result[kw] = sorted(articles, key=lambda x: x["_dt"], reverse=True)

    return result


# ══════════════════════════════════════════════════════
# 엑셀 내보내기
# ══════════════════════════════════════════════════════
def build_excel() -> bytes:
    df_derived = _read_derived_all()
    df_content = _read_content_all()

    if df_derived.empty:
        df_summary = pd.DataFrame(columns=["월", "도출 건수", "반영 건수", "반영률(%)", "KPI 달성"])
    else:
        months = df_derived["kpi_month"].dropna().unique()
        rows = []
        for m in sorted(months):
            kws   = df_derived[df_derived["kpi_month"] == m]["keyword"].tolist()
            done  = (df_content[(df_content["kpi_month"] == m) & (df_content["keyword"].isin(kws))]["keyword"].nunique()
                     if not df_content.empty else 0)
            total = len(kws)
            rate  = round(done / total * 100, 1) if total > 0 else 0.0
            rows.append({"월": m, "도출 건수": total, "반영 건수": done, "반영률(%)": rate,
                         "KPI 달성": "달성" if total >= 5 and rate >= 70 else "미달성"})
        df_summary = pd.DataFrame(rows)

    df_det = df_derived.rename(columns={
        "keyword": "키워드", "kpi_month": "월", "usage_type": "활용처", "status": "상태",
        "vendor": "벤더", "idea": "아이디어", "source_url": "출처URL",
        "discovery_source": "등록출처", "added_at": "등록일",
    }) if not df_derived.empty else pd.DataFrame()

    df_co = df_content.rename(columns={
        "keyword": "키워드", "kpi_month": "월", "content_type": "콘텐츠 유형",
        "content_name": "콘텐츠명", "url": "URL", "published_at": "발행일", "added_at": "등록일",
    }) if not df_content.empty else pd.DataFrame()

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df_summary.to_excel(writer, sheet_name="월별 KPI 요약", index=False)
        if not df_det.empty:
            df_det.to_excel(writer, sheet_name="도출 키워드", index=False)
        if not df_co.empty:
            df_co.to_excel(writer, sheet_name="적용 콘텐츠", index=False)
    return buf.getvalue()


# ══════════════════════════════════════════════════════
# 반영 콘텐츠 등록 다이얼로그
# ══════════════════════════════════════════════════════
@st.dialog("반영 콘텐츠 등록")
def content_dialog(keyword: str, month: str, usage_type: str):
    st.markdown(f"**키워드:** {keyword} &nbsp;·&nbsp; **활용처:** {usage_type or '미지정'}")

    # 기존 등록 콘텐츠 목록
    df_all_cont = _read_content_all()
    existing = df_all_cont[(df_all_cont["keyword"] == keyword) & (df_all_cont["kpi_month"] == month)]
    if not existing.empty:
        st.markdown("**등록된 콘텐츠**")
        for _, row in existing.iterrows():
            c_name = row.get("content_name", "")
            c_url  = row.get("url", "")
            c_date = row.get("published_at", "")
            col_a, col_b = st.columns([8, 2])
            with col_a:
                if c_url:
                    st.markdown(f"• [{c_name or c_url}]({c_url}) — {c_date}")
                else:
                    st.markdown(f"• {c_name} — {c_date}")
            with col_b:
                if st.button("삭제", key=f"del_cont_{keyword}_{c_name}", type="secondary"):
                    delete_content_row(keyword, month, c_name)
                    st.rerun()
        st.markdown("---")

    st.markdown("**새 콘텐츠 추가**")
    st.caption("적용 콘텐츠(보도자료·기획기사·인터뷰·링크드인·인스타 게시물 등)를 등록하면 '반영 완료' 처리됩니다.")

    type_options = ["PR 기사", "온드미디어"]
    default_idx  = 1 if usage_type == "온드미디어" else 0
    c_type = st.selectbox("콘텐츠 유형 *", type_options, index=default_idx, key=f"ctype_{keyword}")
    c_name = st.text_input("콘텐츠명 *", placeholder="예: AI보안 동향 보도자료 2026-06", key=f"cname_{keyword}")
    c_url  = st.text_input("URL (선택)", placeholder="https://...", key=f"curl_{keyword}")
    c_date = st.date_input("발행일", value=date.today(), key=f"cdate_{keyword}")

    if st.button("저장", type="primary", use_container_width=True, key=f"csave_{keyword}"):
        if not c_name.strip():
            st.warning("콘텐츠명 또는 URL 중 하나는 반드시 입력해 주세요.")
        else:
            ok = add_content(keyword, month, c_type, c_name.strip(), c_url.strip(), str(c_date))
            if ok:
                st.success("콘텐츠가 등록됐습니다. 반영 완료로 처리됩니다.")
                st.rerun()
            else:
                st.warning("이미 등록된 콘텐츠명입니다.")


# ══════════════════════════════════════════════════════
# 메인 화면
# ══════════════════════════════════════════════════════
ensure_data()

# ── 헤더 바 + 페이지 타이틀 ──────────────────────────
_now_str    = datetime.now().strftime("%Y.%m.%d %H:%M")
_sync_label = "GitHub 동기화" if gh.is_configured() else "로컬 모드"
st.markdown(f"""
<div class="dash-header">
  <div class="dash-logo">
    <div class="dash-logo-mark">K</div>
    <div class="dash-logo-text">
      <div class="dt">SCK/STK Corp &nbsp;·&nbsp; 커뮤니케이션팀</div>
    </div>
  </div>
  <div class="dash-meta">
    <span>기준월 <strong>{CURRENT_MONTH}</strong></span>
    <span>{_now_str} 기준</span>
    <span>{_sync_label}</span>
    <span class="dash-live">라이브</span>
  </div>
</div>
<div class="page-hero">
  <div class="page-hero-title">SCK 커뮤니케이션팀<br>키워드 트렌드 대시보드</div>
  <div class="page-hero-desc">트렌드 키워드의 발굴부터 PR·온드미디어 반영까지 관리합니다.</div>
</div>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════
# 섹션 1: 도출 키워드 빠른 등록
# ══════════════════════════════════════════════════════
st.markdown("""
<div class="sec-hdr-main">
  <div class="sh-t">도출 키워드 빠른 등록</div>
  <div class="sh-s">이번 달 발굴한 키워드를 바로 등록하세요. 벤더·아이디어 등 추가 정보는 펼쳐서 입력할 수 있습니다.</div>
</div>""", unsafe_allow_html=True)

with st.form("quick_register_form", clear_on_submit=True):
    col_kw, col_usage, col_btn = st.columns([4, 3, 1.3])
    with col_kw:
        reg_keyword = st.text_input("키워드 *", placeholder="예: 제로트러스트")
    with col_usage:
        reg_usage = st.selectbox("활용처 *", ["PR 기사", "온드미디어", "공통"])
    with col_btn:
        st.markdown("<div style='height:29px'></div>", unsafe_allow_html=True)
        reg_submit = st.form_submit_button("＋ 등록", use_container_width=True, type="primary")

    with st.expander("추가 정보 입력 (선택)"):
        col_v, col_i = st.columns(2)
        with col_v:
            reg_vendor = st.text_input("관련 벤더", placeholder="예: Palo Alto, CrowdStrike")
        with col_i:
            reg_idea = st.text_input("활용 아이디어·메모", placeholder="예: Q3 보도자료, 링크드인 인포그래픽")
        reg_source_url = st.text_input("출처 URL", placeholder="https://... (참고 기사 또는 자료 링크)")

if reg_submit:
    kw = reg_keyword.strip() if reg_keyword else ""
    if not kw:
        st.warning("키워드를 입력해 주세요.")
    else:
        ok = add_keyword(
            kw, CURRENT_MONTH,
            usage_type=reg_usage,
            vendor=reg_vendor.strip(),
            idea=reg_idea.strip(),
            source_url=reg_source_url.strip(),
            discovery_source="직접 입력",
        )
        if ok:
            st.success(f"'{kw}' 등록 완료 — 활용처: {reg_usage}")
            st.rerun()
        else:
            st.warning("이미 등록된 키워드입니다. 기존 항목을 확인해 주세요.")

st.markdown("<div style='margin-top:2rem'></div>", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════
# KPI 자동 계산
# ══════════════════════════════════════════════════════
df_cur         = load_derived(CURRENT_MONTH)
df_content_cur = load_content(CURRENT_MONTH)

KPI_DERIVED   = len(df_cur)
# 반영 완료 = 적용 콘텐츠(applied_content.csv)가 1건 이상 등록된 키워드 수
KPI_REFLECTED = (
    df_content_cur["keyword"].nunique()
    if not df_content_cur.empty else 0
)
KPI_TARGET_D    = 5
KPI_TARGET_R    = 70
reflection_rate = round(KPI_REFLECTED / KPI_DERIVED * 100) if KPI_DERIVED > 0 else 0
kpi_pass        = (KPI_DERIVED >= KPI_TARGET_D) and (reflection_rate >= KPI_TARGET_R)


# ══════════════════════════════════════════════════════
# 섹션 2: KPI 카드 (4개)
# ══════════════════════════════════════════════════════
st.markdown("""
<div class="sec-hdr">
  <div class="sh-t">이번 달 KPI 현황</div>
  <div class="sh-s">도출 목표 5건 · 반영률 목표 70% · 반영 완료는 적용 콘텐츠(보도자료·SNS 게시물 등) 등록 기준</div>
</div>""", unsafe_allow_html=True)

c1, c2, c3, c4 = st.columns(4, gap="medium")

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
    st.markdown(f"""
    <div class="kpi-card">
      <div class="kpi-label">반영 완료</div>
      <div class="kpi-value">{KPI_REFLECTED}<span class="kpi-unit">건</span></div>
      <div class="kpi-target">도출 {KPI_DERIVED}건 중 · 적용 콘텐츠 등록 기준</div>
    </div>""", unsafe_allow_html=True)
    st.progress(min(KPI_REFLECTED / max(KPI_DERIVED, 1), 1.0))

with c3:
    pct2 = min(int(reflection_rate / KPI_TARGET_R * 100), 100)
    st.markdown(f"""
    <div class="kpi-card">
      <div class="kpi-label">전체 반영률</div>
      <div class="kpi-value">{reflection_rate}<span class="kpi-unit">%</span></div>
      <div class="kpi-target">목표 {KPI_TARGET_R}% · 달성률 {pct2}%</div>
    </div>""", unsafe_allow_html=True)
    st.progress(min(reflection_rate / KPI_TARGET_R, 1.0))

with c4:
    badge_cls  = "badge-pass" if kpi_pass else "badge-fail"
    badge_text = "달성" if kpi_pass else "진행 중"
    hint = "도출·반영 두 목표 모두 달성" if kpi_pass else (
        f"도출 {max(KPI_TARGET_D - KPI_DERIVED, 0)}건 · "
        f"반영률 {max(KPI_TARGET_R - reflection_rate, 0)}%p 부족"
    )
    st.markdown(f"""
    <div class="kpi-card">
      <div class="kpi-label">이번 달 KPI</div>
      <span class="{badge_cls}">{badge_text}</span>
      <div class="kpi-target" style="margin-top:12px">{hint}</div>
    </div>""", unsafe_allow_html=True)
    st.progress(1.0 if kpi_pass else max(reflection_rate / 100, 0.03))

st.markdown("<div style='margin-top:2.5rem'></div>", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════
# 섹션 3: 활용처 + 반영 현황 표
# ══════════════════════════════════════════════════════
st.markdown("""
<div class="sec-hdr-main">
  <div class="sh-t">활용처 · 반영 현황</div>
  <div class="sh-s">'수정' 버튼으로 적용 콘텐츠(보도자료·기획기사·SNS 게시물 등)를 등록하면 반영 완료 처리됩니다.</div>
</div>""", unsafe_allow_html=True)

col_filter_row, col_dl = st.columns([7, 2])
with col_filter_row:
    filter_tab = st.radio(
        "활용처 필터", ["전체", "PR 기사", "온드미디어"],
        horizontal=True, label_visibility="collapsed",
    )
with col_dl:
    st.download_button(
        "⬇ 엑셀 다운로드", data=build_excel(),
        file_name=f"keyword_kpi_{CURRENT_MONTH}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

if df_cur.empty:
    st.info("이번 달 등록된 도출 키워드가 없습니다. 위 '도출 키워드 빠른 등록'에서 추가해 주세요.")
else:
    # 활용처 필터 — '공통'은 PR 기사·온드미디어 양쪽에 표시
    if filter_tab == "전체":
        df_filtered = df_cur.copy()
    elif filter_tab == "PR 기사":
        df_filtered = df_cur[df_cur["활용처"].isin(["PR 기사", "공통"])].copy()
    else:
        df_filtered = df_cur[df_cur["활용처"].isin(["온드미디어", "공통"])].copy()

    # 최신 콘텐츠 인덱스 (keyword → 가장 최근 1건)
    if not df_content_cur.empty:
        latest_cont = (
            df_content_cur.sort_values("added_at", ascending=False)
            .drop_duplicates(subset="keyword", keep="first")
            .set_index("keyword")
        )
        cont_counts = df_content_cur.groupby("keyword").size().to_dict()
    else:
        latest_cont = pd.DataFrame()
        cont_counts = {}

    # 표 헤더
    h0, h1, h2, h3, h4, h5, h6 = st.columns([2.5, 1.8, 1.5, 3.2, 1.4, 1.6, 1.2])
    for col, label in zip(
        [h0, h1, h2, h3, h4, h5, h6],
        ["키워드", "활용처", "상태", "적용 콘텐츠명", "링크", "반영일", "수정"],
    ):
        col.markdown(f"<span class='kw-table-hdr'>{label}</span>", unsafe_allow_html=True)
    st.markdown("<hr style='margin:6px 0 4px;'>", unsafe_allow_html=True)

    for _, row in df_filtered.iterrows():
        kw     = row["키워드"]
        usage  = row["활용처"] or ""
        status = row["상태"] or "도출"

        # 콘텐츠 정보
        has_cont = not latest_cont.empty and kw in latest_cont.index
        if has_cont:
            cont      = latest_cont.loc[kw]
            cont_name = cont.get("content_name", "")
            cont_url  = cont.get("url", "")
            cont_date = cont.get("published_at", "")
            cnt_total = cont_counts.get(kw, 0)
        else:
            cont_name = cont_url = cont_date = ""
            cnt_total = 0

        # 활용처 태그 HTML
        if usage == "PR 기사":
            u_html = f"<span class='usage-tag-pr'>{usage}</span>"
        elif usage == "온드미디어":
            u_html = f"<span class='usage-tag-owned'>{usage}</span>"
        elif usage == "공통":
            u_html = f"<span class='usage-tag-common'>{usage}</span>"
        else:
            u_html = f"<span class='usage-tag-none'>미지정</span>"

        # 상태 태그 HTML
        s_html = (
            "<span class='status-done'>반영완료</span>"
            if status == "반영완료"
            else "<span class='status-todo'>도출</span>"
        )

        r0, r1, r2, r3, r4, r5, r6 = st.columns([2.5, 1.8, 1.5, 3.2, 1.4, 1.6, 1.2])
        with r0:
            st.markdown(f"<span class='kw-cell' style='font-weight:600'>{kw}</span>", unsafe_allow_html=True)
        with r1:
            st.markdown(f"<span class='kw-cell'>{u_html}</span>", unsafe_allow_html=True)
        with r2:
            st.markdown(f"<span class='kw-cell'>{s_html}</span>", unsafe_allow_html=True)
        with r3:
            if cont_name:
                disp = cont_name + (f" 외 {cnt_total - 1}건" if cnt_total > 1 else "")
                st.markdown(f"<span class='kw-cell'>{disp}</span>", unsafe_allow_html=True)
            else:
                st.markdown("<span class='kw-cell' style='color:#94A3B8'>—</span>", unsafe_allow_html=True)
        with r4:
            if cont_url:
                st.markdown(f"[콘텐츠 보기]({cont_url})", unsafe_allow_html=False)
            else:
                st.markdown("<span style='color:#94A3B8;font-size:13px'>—</span>", unsafe_allow_html=True)
        with r5:
            st.markdown(
                f"<span class='kw-cell' style='color:#64748B'>{cont_date or '—'}</span>",
                unsafe_allow_html=True,
            )
        with r6:
            if st.button("수정", key=f"edit_{kw}", use_container_width=True):
                content_dialog(kw, CURRENT_MONTH, usage)

        st.markdown("<hr style='margin:4px 0;border-color:#F1F5F9'>", unsafe_allow_html=True)

    # 키워드 삭제 (숨김 처리)
    with st.expander("키워드 삭제"):
        st.caption("잘못 등록된 키워드를 삭제합니다. 연결된 적용 콘텐츠도 함께 삭제됩니다.")
        del_options = df_cur["키워드"].tolist()
        del_kw = st.selectbox("삭제할 키워드 선택", del_options, label_visibility="collapsed", key="del_kw_sel")
        if st.button("선택한 키워드 삭제", type="secondary", key="btn_del_kw"):
            delete_keyword(del_kw, CURRENT_MONTH)
            df_c = _read_content_all()
            df_c = df_c[~((df_c["keyword"] == del_kw) & (df_c["kpi_month"] == CURRENT_MONTH))]
            _write_content(df_c, f"콘텐츠 일괄 삭제: {del_kw}")
            st.success(f"'{del_kw}' 삭제됐습니다.")
            st.rerun()

st.markdown("<div style='margin-top:2.5rem'></div>", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════
# 섹션 4: 이번 주 키워드 인사이트
# ══════════════════════════════════════════════════════
# ※ 이 섹션은 반영률 집계와 무관한 참고 자료입니다.
# ※ 버튼을 눌렀을 때만 API 호출 — 페이지 로드 시 자동 호출 없음.
# ══════════════════════════════════════════════════════
st.markdown("""
<div class="sec-hdr-main">
  <div class="sh-t">이번 주 키워드 인사이트</div>
  <div class="sh-s">최근 7일 국내 기사 · 네이버 뉴스 검색 API · 참고 자료용 — 반영률 집계 미포함</div>
</div>""", unsafe_allow_html=True)

# ── 키워드 선택 (session_state 유지) ─────────────────
_derived_kw_list = df_cur["키워드"].tolist() if not df_cur.empty else []

if "insight_sel_kws" not in st.session_state:
    st.session_state["insight_sel_kws"] = _derived_kw_list[:5]  # 기본: 이번 달 도출 키워드 (최대 5개)
if "insight_articles" not in st.session_state:
    st.session_state["insight_articles"] = None   # None = 아직 미조회

# 선택 목록에서 삭제된 키워드 정리
_available_kws = _derived_kw_list if _derived_kw_list else []
_sel_cleaned   = [k for k in st.session_state["insight_sel_kws"] if k in _available_kws]
if _sel_cleaned != st.session_state["insight_sel_kws"]:
    st.session_state["insight_sel_kws"] = _sel_cleaned

col_kw_sel, col_fetch, col_refresh = st.columns([6, 1.5, 1.2])
with col_kw_sel:
    sel_kws = st.multiselect(
        "조회할 키워드 (최대 5개)",
        options=_available_kws,
        default=st.session_state["insight_sel_kws"],
        max_selections=5,
        placeholder="키워드를 선택하세요",
        label_visibility="collapsed",
        key="insight_multisel",
    )
    st.session_state["insight_sel_kws"] = sel_kws

with col_fetch:
    fetch_clicked = st.button(
        "이번 주 기사 불러오기",
        use_container_width=True,
        type="primary",
        key="btn_fetch_news",
        disabled=not sel_kws,
    )

with col_refresh:
    refresh_clicked = st.button(
        "새로고침",
        use_container_width=True,
        type="secondary",
        key="btn_refresh_news",
        disabled=st.session_state["insight_articles"] is None,
    )

# ── 새로고침: 해당 섹션 캐시만 비우고 재조회 ───────────
if refresh_clicked and sel_kws:
    fetch_news_articles.clear()           # 뉴스 캐시만 비움 (트렌드·뉴스발굴 캐시는 유지)
    st.session_state["insight_articles"] = None
    st.rerun()

# ── 기사 불러오기: 버튼 클릭 시에만 API 호출 ──────────
if fetch_clicked and sel_kws:
    with st.spinner(f"네이버 뉴스에서 최근 7일 기사를 불러오는 중…"):
        st.session_state["insight_articles"] = fetch_news_articles(
            keywords=tuple(sel_kws),
            days=7,
        )
    st.rerun()

# ── 결과 표시 ─────────────────────────────────────────
articles_data = st.session_state["insight_articles"]

if articles_data is None:
    st.info("키워드를 선택한 뒤 '이번 주 기사 불러오기'를 눌러 주세요.")
elif not articles_data:
    st.warning("API 키를 확인하거나 잠시 후 다시 시도해 주세요.")
else:
    # 전체 기사 수집 후 날짜순 정렬, 최대 10건
    all_articles: list = []
    for kw, arts in articles_data.items():
        for a in arts:
            all_articles.append({**a, "_kw": kw})

    all_articles.sort(key=lambda x: x["_dt"], reverse=True)
    all_articles = all_articles[:10]

    if not all_articles:
        st.info("최근 7일 이내 해당 키워드 기사가 없습니다.")
    else:
        st.caption(f"총 {len(all_articles)}건 · 24시간 캐시 적용 (새로고침 버튼으로 갱신)")
        for art in all_articles:
            with st.container():
                kw_badge = (
                    f"<span style='background:#EFF6FF;color:#1D4ED8;border-radius:4px;"
                    f"padding:1px 7px;font-size:11px;font-weight:600'>{art['_kw']}</span>"
                )
                media_str = f"<span style='color:#64748B;font-size:12px'>{art['media']} · {art['date']}</span>"
                st.markdown(
                    f"{kw_badge} &nbsp; {media_str}",
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f"**[{art['title']}]({art['url']})**",
                    unsafe_allow_html=False,
                )
                if art["summary"]:
                    st.markdown(
                        f"<span style='font-size:13px;color:#475569'>{art['summary']}</span>",
                        unsafe_allow_html=True,
                    )
                st.markdown("<hr style='margin:8px 0;border-color:#F1F5F9'>", unsafe_allow_html=True)

st.markdown("<div style='margin-top:3rem'></div>", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════
# 섹션 5: 트렌드 키워드 탐색 (상위)
# ══════════════════════════════════════════════════════
st.markdown("""
<div class="sec-hdr-main">
  <div class="sh-t">트렌드 키워드 탐색</div>
  <div class="sh-s">네이버 데이터랩·구글 트렌드 검색량 변화 추적 &nbsp;·&nbsp; 급상승 키워드 자동 발굴</div>
</div>""", unsafe_allow_html=True)

# ── 소섹션: 추적 키워드 ───────────────────────────────
st.markdown("""
<div class="sec-hdr">
  <div class="sh-t">추적 키워드</div>
  <div class="sh-s">칩 클릭 → 그래프 숨김/복원 &nbsp;·&nbsp; ✕ → 목록에서 삭제 &nbsp;·&nbsp; 추가하면 즉시 데이터 수집</div>
</div>""", unsafe_allow_html=True)

tracked_kws = load_tracked_keywords()

if "hidden_kws" not in st.session_state:
    st.session_state["hidden_kws"] = set()
st.session_state["hidden_kws"] &= set(tracked_kws)

if not tracked_kws:
    st.info("추적 중인 키워드가 없습니다. 아래에서 추가해 주세요.")
else:
    CHIPS_PER_ROW = 4
    for row_start in range(0, len(tracked_kws), CHIPS_PER_ROW):
        batch  = tracked_kws[row_start : row_start + CHIPS_PER_ROW]
        widths = []
        for _ in batch:
            widths += [3, 0.45]
        widths.append(max(0.1, 14 - sum(widths)))
        cols = st.columns(widths)
        for j, kw in enumerate(batch):
            is_hidden  = kw in st.session_state["hidden_kws"]
            chip_label = f"○ {kw}" if is_hidden else f"● {kw}"
            chip_help  = "다시 클릭하면 그래프에 복원됩니다" if is_hidden else "클릭하면 그래프에서 잠깐 숨깁니다"
            with cols[j * 2]:
                if st.button(chip_label, key=f"chip_toggle_{kw}", use_container_width=True, help=chip_help):
                    if is_hidden:
                        st.session_state["hidden_kws"].discard(kw)
                    else:
                        st.session_state["hidden_kws"].add(kw)
                    st.rerun()
            with cols[j * 2 + 1]:
                if st.button("✕", key=f"chip_del_{kw}", help=f"'{kw}'를 추적 목록에서 완전 삭제", type="secondary"):
                    remove_tracked_keyword(kw)
                    st.session_state["hidden_kws"].discard(kw)
                    st.rerun()

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
active_kws  = [kw for kw in tracked_kws if kw not in st.session_state["hidden_kws"]]
df_trends   = load_trends()

if df_trends.empty:
    st.warning("data/trends.csv 에 데이터가 없습니다. 터미널에서 `python collector.py` 를 먼저 실행해 주세요.")
elif not active_kws:
    st.info("모든 키워드가 숨김 상태입니다. 칩을 다시 클릭해서 복원하세요.")
else:
    df_period = df_trends[(df_trends["keyword"].isin(active_kws)) & (df_trends["date"] >= cutoff)]
    df_naver  = df_period[df_period["source"] == "naver"]
    df_google = df_period[df_period["source"] == "google"]

    col_n, col_g = st.columns(2, gap="medium")
    with col_n:
        st.markdown('<div class="src-naver">네이버 데이터랩 — 검색 트렌드</div>', unsafe_allow_html=True)
        st.markdown('<div class="chart-hint">국내 검색 기준 · 0~100 상대 지수 · 인스타그램 기획 참고</div>', unsafe_allow_html=True)
        if not df_naver.empty:
            draw_chart(to_weekly(df_naver))
            with st.expander("네이버 원본 데이터"):
                s = df_naver.copy(); s["date"] = s["date"].dt.strftime("%Y-%m-%d")
                st.dataframe(
                    s[["keyword", "date", "ratio"]].rename(columns={"keyword": "키워드", "date": "날짜", "ratio": "관심도"})
                    .sort_values("날짜", ascending=False).head(40),
                    use_container_width=True, hide_index=True,
                )
        else:
            st.info("선택 기간에 네이버 데이터가 없습니다.")

    with col_g:
        st.markdown('<div class="src-google">구글 트렌드 — 검색 트렌드</div>', unsafe_allow_html=True)
        st.markdown('<div class="chart-hint">국내·글로벌 검색 기준 · 0~100 상대 지수 · 링크드인 기획 참고</div>', unsafe_allow_html=True)
        if not df_google.empty:
            draw_chart(to_weekly(df_google))
            with st.expander("구글 원본 데이터"):
                g = df_google.copy(); g["date"] = g["date"].dt.strftime("%Y-%m-%d")
                st.dataframe(
                    g[["keyword", "date", "ratio"]].rename(columns={"keyword": "키워드", "date": "날짜", "ratio": "관심도"})
                    .sort_values("날짜", ascending=False).head(40),
                    use_container_width=True, hide_index=True,
                )
        else:
            st.info("선택 기간에 구글 데이터가 없습니다.")

    st.caption("⚠️ 네이버(일별)와 구글(주별)은 집계 기준이 달라 직접 비교하지 마세요.")

    st.markdown("<div style='margin-top:1.5rem'></div>", unsafe_allow_html=True)
    st.markdown(f"""
<div class="sec-hdr">
  <div class="sh-t">키워드별 추이 요약</div>
  <div class="sh-s">최근 {period_days}일 · 전반부 대비 후반부 변화율 · 데이터 부족 시 표시</div>
</div>""", unsafe_allow_html=True)

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
                st.plotly_chart(make_sparkline(n_series, "#03c75a"), use_container_width=True,
                                config={"displayModeBar": False}, key=f"spark_n_{kw}_{period_days}")
            else:
                st.caption("데이터 부족")
        with c2:
            st.markdown(change_badge(n_change), unsafe_allow_html=True)
        with c3:
            g_change, g_series = compute_change(row_g)
            if len(g_series) >= 3:
                st.plotly_chart(make_sparkline(g_series, "#ea4335"), use_container_width=True,
                                config={"displayModeBar": False}, key=f"spark_g_{kw}_{period_days}")
            else:
                st.caption("데이터 부족")
        with c4:
            st.markdown(change_badge(g_change), unsafe_allow_html=True)
        st.markdown("<hr style='margin:4px 0;border-color:#f0f0f0'>", unsafe_allow_html=True)

st.markdown("<div style='margin-top:2.5rem'></div>", unsafe_allow_html=True)

# ── 소섹션: 급상승 키워드 발굴 ────────────────────────
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
    news_rows    = [news_kws[i:i + cols_per_row] for i in range(0, len(news_kws), cols_per_row)]

    for news_row in news_rows:
        cols = st.columns(cols_per_row, gap="small")
        for col, (word, count) in zip(cols, news_row):
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
                        if st.button("📌 추적에 추가", key=f"track_{word}", use_container_width=True, type="primary"):
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
                            ok = add_keyword(word, CURRENT_MONTH, discovery_source="뉴스 자동탐지")
                            if ok:
                                st.success(f"'{word}' 도출 추가!")
                                st.rerun()
                            else:
                                st.info("이미 등록된 키워드입니다. 기존 항목을 확인해 주세요.")
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
                ok = add_keyword(manual_kw.strip(), CURRENT_MONTH, discovery_source="직접 입력")
                if ok:
                    st.success(f"'{manual_kw.strip()}' 추가됐습니다!")
                    st.rerun()
                else:
                    st.warning("이미 등록된 키워드입니다. 기존 항목을 확인해 주세요.")
            else:
                st.warning("키워드를 입력해 주세요.")

# ── 푸터 ──────────────────────────────────────────────
_trend_cnt = len(pd.read_csv(TRENDS_CSV)) if os.path.exists(TRENDS_CSV) else 0
st.markdown(f"""
<div style="margin-top:3rem;padding-top:1.5rem;border-top:1px solid #E2E8F0;
            display:flex;justify-content:space-between;align-items:center;
            font-size:11px;color:#94A3B8;">
  <span>키워드 인텔리전스 · SCK/STK Corp · {CURRENT_MONTH}</span>
  <span>트렌드 데이터 {_trend_cnt:,}건 · 네이버 데이터랩 · 구글 트렌드</span>
</div>""", unsafe_allow_html=True)
