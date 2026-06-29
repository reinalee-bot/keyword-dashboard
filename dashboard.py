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

import numpy as np
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
MANUAL_CSV   = os.path.join(DATA_DIR, "monthly_manual.csv")

DERIVED_COLS = ["keyword", "kpi_month", "usage_type", "status",
                "vendor", "idea", "source_url", "discovery_source", "added_at"]
CONTENT_COLS = ["keyword", "kpi_month", "content_type",
                "content_name", "url", "published_at", "added_at"]
TRENDS_COLS  = ["keyword", "date", "ratio", "source", "collected_at"]
TRACKED_COLS = ["keyword", "added_at"]
MANUAL_COLS  = ["kpi_month", "manual_derived", "manual_reflected", "note", "added_at"]

CURRENT_MONTH = datetime.today().strftime("%Y-%m")

st.set_page_config(
    page_title="키워드 인텔리전스 | SCK·STK",
    page_icon="📊",
    layout="wide",
)

# ── CSS ──────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.css');

* {
    font-family: 'Pretendard', -apple-system, BlinkMacSystemFont,
                 'Apple SD Gothic Neo', sans-serif !important;
    word-break: keep-all;
}

#MainMenu, footer, .stApp > header,
[data-testid="stToolbar"], [data-testid="stDecoration"] {
    display: none !important;
}

.block-container {
    max-width: 1400px !important;
    padding: 0 2rem 4rem !important;
    margin: 0 auto !important;
}

.stApp { background: #F7F9FC; }

[data-testid="stTabs"] [role="tablist"] {
    border-bottom: 2px solid #DCE3EA;
    gap: 0;
}
[data-testid="stTabs"] [role="tab"] {
    font-weight: 600 !important;
    font-size: 14px !important;
    color: #667085 !important;
    padding: 10px 20px !important;
    border-bottom: 2px solid transparent !important;
    margin-bottom: -2px !important;
}
[data-testid="stTabs"] [role="tab"][aria-selected="true"] {
    color: #2F6BFF !important;
    border-bottom: 2px solid #2F6BFF !important;
    background: transparent !important;
}
[data-testid="stTabs"] [role="tab"]:hover {
    color: #2F6BFF !important;
    background: #F0F5FF !important;
}
[data-testid="stTabsContent"] { padding-top: 1.5rem; }

.dash-header {
    display: flex; align-items: center; justify-content: space-between;
    background: #ffffff; border-bottom: 1px solid #DCE3EA;
    padding: 10px 2rem; margin: 0 -2rem 0 -2rem;
}
.dash-logo { display: flex; align-items: center; gap: 8px; }
.dash-logo-mark {
    width: 26px; height: 26px; background: #2F6BFF; border-radius: 6px;
    display: flex; align-items: center; justify-content: center;
    color: white; font-size: 13px; font-weight: 700; flex-shrink: 0;
}
.dash-logo-text .dt { font-size: 13px; font-weight: 700; color: #102A43; }
.dash-meta { display: flex; align-items: center; gap: 16px; font-size: 11.5px; color: #667085; }
.dash-live {
    display: flex; align-items: center; gap: 5px;
    background: #F0FDF4; color: #166534;
    padding: 3px 10px; border-radius: 20px; font-weight: 600; font-size: 11px;
}
.dash-live::before { content: "●"; font-size: 8px; color: #16A34A; }

.page-hero {
    padding: 1.6rem 0 1.2rem;
    border-bottom: 1px solid #DCE3EA;
    margin-bottom: 1.5rem;
}
.page-hero-title {
    font-size: 1.6rem; font-weight: 800; color: #102A43;
    margin: 0 0 0.4rem; line-height: 1.25; letter-spacing: -0.01em;
}
.page-hero-desc { font-size: 0.9rem; color: #667085; margin: 0; line-height: 1.5; }

.sec-hdr-main {
    margin: 0 0 1.4rem 0;
    border-left: 4px solid #2F6BFF;
    padding-left: 14px;
}
.sec-hdr-main .sh-t {
    font-size: 1.05rem; font-weight: 800; color: #102A43; margin: 0; line-height: 1.3;
}
.sec-hdr-main .sh-s { font-size: 12px; color: #667085; margin: 3px 0 0; line-height: 1.5; }

.sec-hdr { border-left: 3px solid #2F6BFF; padding-left: 11px; margin: 0 0 12px 0; }
.sec-hdr .sh-t { font-size: 14px; font-weight: 700; color: #101828; margin: 0; line-height: 1.3; }
.sec-hdr .sh-s { font-size: 11.5px; color: #667085; margin: 2px 0 0; line-height: 1.4; }

.kpi-card {
    background: #fff; border: 1px solid #DCE3EA;
    border-radius: 12px; padding: 20px 22px 18px;
}
.kpi-label {
    font-size: 10px; font-weight: 700; color: #667085;
    text-transform: uppercase; letter-spacing: .07em; margin-bottom: 10px;
}
.kpi-value { font-size: 2.6rem; font-weight: 800; color: #101828; line-height: 1; }
.kpi-unit  { font-size: .9rem; font-weight: 400; color: #667085; margin-left: 3px; }
.kpi-target { font-size: 11.5px; color: #667085; margin-top: 8px; }
.badge-pass {
    display: inline-block; background: #ECFDF5; color: #065F46;
    border-radius: 6px; padding: 6px 16px; font-weight: 700; font-size: 14px; margin-top: 10px;
}
.badge-fail {
    display: inline-block; background: #FFF7ED; color: #9A3412;
    border-radius: 6px; padding: 6px 16px; font-weight: 700; font-size: 14px; margin-top: 10px;
}

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

.kw-table-hdr {
    font-size: 11px; font-weight: 700; color: #667085;
    text-transform: uppercase; letter-spacing: .05em; padding: 0 4px;
}
.kw-cell { padding: 2px 4px; font-size: 13.5px; line-height: 1.6; }

.trend-card-kw { font-size: 1rem; font-weight: 800; color: #101828; margin-bottom: 10px; }
.trend-stat { font-size: 13px; color: #667085; margin: 3px 0; }
.trend-stat strong { color: #101828; }

button[kind="primary"],
.stButton button[kind="primary"] {
    background-color: #2F6BFF !important;
    border-color: #2F6BFF !important;
    color: white !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
    height: 40px !important;
}
button[kind="primary"]:hover,
.stButton button[kind="primary"]:hover {
    background-color: #1a56d6 !important;
    border-color: #1a56d6 !important;
}
.stButton button[kind="secondary"] {
    border-radius: 8px !important;
    border-color: #DCE3EA !important;
    color: #374151 !important;
}

hr { border-color: #DCE3EA !important; margin: 1.5rem 0 !important; }
.stProgress > div > div { background: #2F6BFF !important; }

@media (max-width: 768px) {
    .block-container { padding: 0 1rem 3rem !important; }
    .dash-header { padding: 10px 1rem; margin: 0 -1rem; flex-wrap: wrap; gap: 8px; }
    .page-hero-title { font-size: 1.3rem; }
    .kpi-card { padding: 14px 16px; }
    .kpi-value { font-size: 2rem; }
}
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════
# 데이터 초기화
# ══════════════════════════════════════════════════════
def ensure_data():
    os.makedirs(DATA_DIR, exist_ok=True)

    if not os.path.exists(TRENDS_CSV):
        pd.DataFrame(columns=TRENDS_COLS).to_csv(TRENDS_CSV, index=False, encoding="utf-8-sig")

    if not os.path.exists(DERIVED_CSV):
        pd.DataFrame(columns=DERIVED_COLS).to_csv(DERIVED_CSV, index=False, encoding="utf-8-sig")
    else:
        try:
            df = pd.read_csv(DERIVED_CSV, dtype=str).fillna("")
        except Exception:
            df = pd.DataFrame(columns=DERIVED_COLS)
        if "usage_type" not in df.columns:
            df["usage_type"] = ""
        if "status" not in df.columns:
            if "reflected" in df.columns:
                df["status"] = df["reflected"].apply(
                    lambda x: "반영완료" if str(x).strip() in ["1", "true", "True"] else "도출"
                )
            else:
                df["status"] = "도출"
        if "vendor" not in df.columns:
            df["vendor"] = ""
        if "idea" not in df.columns:
            df["idea"] = ""
        if "source_url" not in df.columns:
            df["source_url"] = ""
        if "discovery_source" not in df.columns:
            df["discovery_source"] = df["source"] if "source" in df.columns else "직접 입력"
        for col in DERIVED_COLS:
            if col not in df.columns:
                df[col] = ""
        df[DERIVED_COLS].fillna("").to_csv(DERIVED_CSV, index=False, encoding="utf-8-sig")

    if not os.path.exists(CONTENT_CSV):
        pd.DataFrame(columns=CONTENT_COLS).to_csv(CONTENT_CSV, index=False, encoding="utf-8-sig")
    if not os.path.exists(MANUAL_CSV):
        pd.DataFrame(columns=MANUAL_COLS).to_csv(MANUAL_CSV, index=False, encoding="utf-8-sig")
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
    _TARGET = ["키워드", "활용처", "상태", "벤더", "아이디어", "출처URL", "등록출처", "등록일"]
    df = _read_derived_all()
    if df.empty or "kpi_month" not in df.columns:
        return pd.DataFrame(columns=_TARGET)
    df = df[df["kpi_month"] == month].copy()
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


def update_usage_type(keyword: str, month: str, new_usage: str) -> bool:
    """derived_keywords.csv의 usage_type을 수정합니다 (활용처 수정 버그 수정)."""
    df = _read_derived_all()
    mask = (df["keyword"] == keyword) & (df["kpi_month"] == month)
    if not mask.any():
        return False
    df.loc[mask, "usage_type"] = new_usage
    return bool(_write_derived(df, f"활용처 변경: {keyword} → {new_usage}"))


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
# (다) 월별 수동 KPI CRUD
# ══════════════════════════════════════════════════════

@st.cache_data(ttl=30)
def _load_manual_from_github() -> pd.DataFrame:
    df = gh.read_csv("data/monthly_manual.csv")
    return df if df is not None else pd.DataFrame(columns=MANUAL_COLS)


def _read_manual_all() -> pd.DataFrame:
    if gh.is_configured():
        df = _load_manual_from_github()
    elif not os.path.exists(MANUAL_CSV):
        return pd.DataFrame(columns=MANUAL_COLS)
    else:
        try:
            df = pd.read_csv(MANUAL_CSV, dtype=str)
        except Exception:
            return pd.DataFrame(columns=MANUAL_COLS)
    df = df.fillna("")
    for col in MANUAL_COLS:
        if col not in df.columns:
            df[col] = ""
    return df


def _write_manual(df: pd.DataFrame, message: str) -> bool:
    if gh.is_configured():
        ok = gh.write_csv(df, "data/monthly_manual.csv", message)
        if ok:
            _load_manual_from_github.clear()
        return ok
    df[MANUAL_COLS].to_csv(MANUAL_CSV, index=False, encoding="utf-8-sig")
    return True


def add_manual_month(kpi_month: str, derived: int, reflected: int, note: str = "") -> bool:
    df = _read_manual_all()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if kpi_month in df["kpi_month"].values:
        idx = df[df["kpi_month"] == kpi_month].index[0]
        df.loc[idx, ["manual_derived", "manual_reflected", "note", "added_at"]] = [
            str(derived), str(reflected), note, now
        ]
    else:
        new_row = pd.DataFrame([{
            "kpi_month": kpi_month, "manual_derived": str(derived),
            "manual_reflected": str(reflected), "note": note, "added_at": now,
        }])
        df = pd.concat([df, new_row], ignore_index=True)
    return _write_manual(df[MANUAL_COLS], f"수동 KPI 입력: {kpi_month}")


def delete_manual_month(kpi_month: str) -> bool:
    df = _read_manual_all()
    df = df[df["kpi_month"] != kpi_month].reset_index(drop=True)
    return _write_manual(df[MANUAL_COLS], f"수동 KPI 삭제: {kpi_month}")


def load_monthly_kpi_summary() -> pd.DataFrame:
    df_derived = _read_derived_all()
    df_content = _read_content_all()
    df_manual  = _read_manual_all()

    auto_months: dict = {}
    if not df_derived.empty and "kpi_month" in df_derived.columns:
        for month, grp in df_derived.groupby("kpi_month"):
            if not month:
                continue
            kws  = grp["keyword"].tolist()
            done = (
                df_content[
                    (df_content["kpi_month"] == month) & (df_content["keyword"].isin(kws))
                ]["keyword"].nunique()
                if not df_content.empty else 0
            )
            auto_months[month] = {"도출": len(kws), "반영": done, "비고": "자동 집계"}

    manual_months: dict = {}
    if not df_manual.empty:
        for _, row in df_manual.iterrows():
            m = row.get("kpi_month", "")
            if not m or m in auto_months:
                continue
            try:
                d = int(row.get("manual_derived", 0) or 0)
                r = int(row.get("manual_reflected", 0) or 0)
            except (ValueError, TypeError):
                d, r = 0, 0
            note_val = row.get("note", "").strip()
            manual_months[m] = {
                "도출": d, "반영": r,
                "비고": f"수동 입력 ({note_val})" if note_val else "수동 입력",
            }

    all_months = {**auto_months, **manual_months}
    if not all_months:
        return pd.DataFrame(columns=["월", "도출 키워드", "반영 완료", "반영률(%)", "KPI 달성", "비고"])

    rows = []
    for m in sorted(all_months.keys(), reverse=True):
        d     = all_months[m]
        total = d["도출"]
        done  = d["반영"]
        rate  = round(done / total * 100, 1) if total > 0 else 0.0
        if m == CURRENT_MONTH:
            status = "⏳ 진행 중"
        elif total >= 5 and rate >= 70:
            status = "✅ 달성"
        else:
            status = "❌ 미달성"
        rows.append({
            "월": m, "도출 키워드": total, "반영 완료": done,
            "반영률(%)": rate, "KPI 달성": status, "비고": d.get("비고", ""),
        })
    return pd.DataFrame(rows)


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


def remove_all_tracked_keywords() -> bool:
    empty = pd.DataFrame(columns=TRACKED_COLS)
    _write_tracked(empty, "전체 추적 해제")
    return True


# ══════════════════════════════════════════════════════
# 트렌드 데이터 + 분석 함수
# ══════════════════════════════════════════════════════

@st.cache_data(ttl=3600 * 8)
def load_trends() -> pd.DataFrame:
    if not os.path.exists(TRENDS_CSV):
        return pd.DataFrame()
    df = pd.read_csv(TRENDS_CSV)
    df["date"] = pd.to_datetime(df["date"])
    return df


def get_last_collection_time() -> str:
    if not os.path.exists(TRENDS_CSV):
        return "수집 기록 없음"
    try:
        df = pd.read_csv(TRENDS_CSV, usecols=["collected_at"])
        if df.empty:
            return "수집 기록 없음"
        last = pd.to_datetime(df["collected_at"]).max()
        kst  = last + timedelta(hours=9)
        return kst.strftime("%Y.%m.%d %H:%M")
    except Exception:
        return "—"


def to_weekly(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["주차"] = df["date"].dt.to_period("W").apply(lambda p: p.start_time)
    return (
        df.groupby(["주차", "keyword"])["ratio"]
        .mean().reset_index()
        .rename(columns={"keyword": "키워드", "ratio": "평균 관심도"})
    )


def draw_unified_chart(df_period: pd.DataFrame, keywords: list, source: str, chart_key: str = "") -> None:
    df_src = df_period[df_period["source"] == source]
    if df_src.empty:
        src_name = "네이버" if source == "naver" else "구글"
        st.info(f"선택 기간에 {src_name} 데이터가 없습니다.")
        return
    df_src   = df_src[df_src["keyword"].isin(keywords)]
    df_weekly = to_weekly(df_src)
    COLORS    = ["#2F6BFF", "#10B981", "#F59E0B", "#EF4444", "#8B5CF6"]
    kw_list   = df_weekly["키워드"].unique().tolist()
    color_map = {kw: COLORS[i % len(COLORS)] for i, kw in enumerate(kw_list)}
    fig = px.line(
        df_weekly, x="주차", y="평균 관심도", color="키워드",
        markers=True, line_shape="spline", height=400,
        color_discrete_map=color_map,
    )
    fig.update_layout(
        plot_bgcolor="white", paper_bgcolor="white",
        font=dict(family="Pretendard, Apple SD Gothic Neo, sans-serif"),
        legend_title_text="키워드",
        xaxis_title="", yaxis_title="관심도 (0~100)",
        yaxis=dict(range=[0, 105], gridcolor="#f0f0f0"),
        xaxis=dict(gridcolor="#f0f0f0"),
        margin=dict(l=10, r=10, t=10, b=10),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    fig.update_traces(line_width=2.5, marker_size=6)
    if chart_key:
        st.plotly_chart(fig, use_container_width=True, key=chart_key)
    else:
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
    half      = len(s) // 2
    first_avg = s.iloc[:half].mean()
    last_avg  = s.iloc[half:].mean()
    change    = None if first_avg == 0 else (last_avg - first_avg) / first_avg * 100
    return change, s


def change_badge(pct) -> str:
    if pct is None:
        return "<span style='color:#aaa'>—</span>"
    color = "#2e7d32" if pct >= 0 else "#c62828"
    arrow = "▲" if pct >= 0 else "▼"
    return f"<span style='color:{color};font-weight:700'>{arrow} {abs(pct):.0f}%</span>"


def derive_trend_summary(series: pd.Series) -> tuple:
    """추세 레이블과 툴팁 설명을 반환합니다. 키워드별 독립 실행."""
    if len(series) < 4:
        return "분석 대기", "분석에 필요한 데이터가 충분하지 않습니다."
    recent4 = float(series.iloc[-4:].mean())
    n       = len(series)
    prev4   = float(series.iloc[-8:-4].mean()) if n >= 8 else float(series.iloc[:max(1, n - 4)].mean())
    pct     = (recent4 - prev4) / max(prev4, 1) * 100
    x       = np.arange(min(4, n))
    y       = series.iloc[-4:].values.astype(float)
    slope   = float(np.polyfit(x, y, 1)[0]) if len(y) >= 2 else 0.0
    cv      = float(series.iloc[-4:].std() / max(float(series.iloc[-4:].mean()), 1))
    recent1 = float(series.iloc[-1]) if n >= 1 else 0.0
    prev1   = float(series.iloc[-2]) if n >= 2 else recent1
    if pct >= 30 and slope > 1:
        return "급상승", f"최근 4주 평균이 이전 대비 {pct:.0f}% 증가했습니다."
    elif pct >= 10:
        return "꾸준한 상승", f"최근 4주 평균이 이전 대비 {pct:.0f}% 증가했습니다."
    elif pct >= 3:
        return "완만한 상승", f"최근 4주 평균이 이전 대비 {pct:.0f}% 증가했습니다."
    elif cv >= 0.35:
        return "등락 반복", f"관심도 변동성이 높습니다. (변동계수 {cv:.2f})"
    elif pct <= -20:
        return "지속 하락", f"최근 4주 평균이 이전 대비 {abs(pct):.0f}% 감소했습니다."
    elif pct <= -8:
        return "전월 대비 하락세", f"최근 4주 평균이 이전 대비 {abs(pct):.0f}% 감소했습니다."
    elif (recent1 - prev1) > 5 and pct < -5:
        return "반등 조짐", "하락 추세 중 최근 1~2주 반등 신호가 보입니다."
    else:
        return "비슷하게 유지 중", f"최근 4주 관심도가 안정적입니다. (평균 {recent4:.1f})"


def compute_kw_stats(df_kw: pd.DataFrame) -> dict:
    """키워드 요약 카드 통계 — 각 키워드별로 독립 호출."""
    if df_kw.empty:
        return {}
    s = df_kw.sort_values("date")["ratio"].reset_index(drop=True)
    if len(s) == 0:
        return {}
    current  = float(s.iloc[-1])
    prev_wk  = float(s.iloc[-2]) if len(s) >= 2 else current
    wk_chg   = (current - prev_wk) / max(prev_wk, 1) * 100
    avg4     = float(s.iloc[-4:].mean()) if len(s) >= 4 else float(s.mean())
    n        = len(s)
    prev4    = float(s.iloc[-8:-4].mean()) if n >= 8 else float(s.iloc[:max(1, n - 4)].mean()) if n > 4 else avg4
    avg_chg  = (avg4 - prev4) / max(prev4, 1) * 100
    trend_label, trend_tip = derive_trend_summary(s)
    return {
        "current": current, "wk_chg": wk_chg,
        "avg4": avg4, "avg_chg": avg_chg,
        "trend_label": trend_label, "trend_tip": trend_tip,
        "series": s,
    }


# ══════════════════════════════════════════════════════
# 뉴스 키워드 (1시간 캐시)
# ══════════════════════════════════════════════════════

@st.cache_data(ttl=3600, persist="disk")
def get_news_keywords():
    return fetch_news_keywords(top_n=20)


# ══════════════════════════════════════════════════════
# 이번 주 키워드 인사이트 — 네이버 뉴스 검색 API
# ══════════════════════════════════════════════════════

_NAVER_NEWS_URL = "https://openapi.naver.com/v1/search/news.json"

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
    try:
        host = urlparse(url).netloc.lower().replace("www.", "").replace("m.", "")
        for domain, name in _MEDIA_MAP.items():
            if domain in host:
                return name
        return host.split(".")[0].upper()
    except Exception:
        return "—"


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


def _parse_pub_date(date_str: str) -> datetime:
    try:
        dt = parsedate_to_datetime(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return datetime.min.replace(tzinfo=timezone.utc)


def _similar_title(t1: str, t2: str) -> bool:
    t1, t2 = t1[:40].lower(), t2[:40].lower()
    if not t1 or not t2:
        return False
    common = sum(c in t2 for c in t1)
    return common / max(len(t1), 1) >= 0.8


@st.cache_data(ttl=86400, show_spinner=False)
def fetch_news_articles(keywords: tuple, days: int = 7) -> dict:
    from dotenv import load_dotenv
    load_dotenv()
    cid = os.getenv("NAVER_CLIENT_ID", "").strip()
    csc = os.getenv("NAVER_CLIENT_SECRET", "").strip()
    if not cid:
        cid = st.secrets.get("NAVER_CLIENT_ID", "").strip()
    if not csc:
        csc = st.secrets.get("NAVER_CLIENT_SECRET", "").strip()
    if not cid or not csc:
        return {}

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    result: dict = {}

    for kw in keywords:
        articles: list  = []
        seen_urls:  set  = set()
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
                if url in seen_urls:
                    continue
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
    df_derived  = _read_derived_all()
    df_content  = _read_content_all()
    df_summary  = load_monthly_kpi_summary().rename(columns={
        "도출 키워드": "도출 건수", "반영 완료": "반영 건수",
    })
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
# 반영 콘텐츠 등록 다이얼로그 (활용처 수정 포함 — 버그 수정)
# ══════════════════════════════════════════════════════

@st.dialog("반영 콘텐츠 등록 및 활용처 수정")
def content_dialog(keyword: str, month: str, usage_type: str):
    st.markdown(f"**키워드:** {keyword}")

    # 활용처 수정 (update_usage_type 함수로 파일에 직접 저장)
    usage_options = ["PR 기사", "온드미디어", "공통"]
    cur_idx = usage_options.index(usage_type) if usage_type in usage_options else 0
    new_usage = st.selectbox(
        "활용처 변경", usage_options, index=cur_idx,
        key=f"usage_sel_{keyword}_{month}",
    )
    if st.button("활용처 저장", key=f"usage_save_{keyword}_{month}", type="secondary"):
        if update_usage_type(keyword, month, new_usage):
            st.success(f"'{keyword}'의 활용처를 '{new_usage}'로 변경했습니다.")
            st.rerun()
        else:
            st.error("저장 실패. 잠시 후 다시 시도해 주세요.")

    st.markdown("---")

    # 기존 콘텐츠 목록
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
    st.caption("적용 콘텐츠를 등록하면 '반영 완료' 처리됩니다.")
    type_options = ["PR 기사", "온드미디어"]
    default_idx  = 1 if usage_type == "온드미디어" else 0
    c_type = st.selectbox("콘텐츠 유형 *", type_options, index=default_idx, key=f"ctype_{keyword}")
    c_name = st.text_input("콘텐츠명 *", placeholder="예: AI보안 동향 보도자료 2026-06", key=f"cname_{keyword}")
    c_url  = st.text_input("URL (선택)", placeholder="https://...", key=f"curl_{keyword}")
    c_date = st.date_input("발행일", value=date.today(), key=f"cdate_{keyword}")

    if st.button("저장", type="primary", use_container_width=True, key=f"csave_{keyword}"):
        if not c_name.strip():
            st.warning("콘텐츠명을 입력해 주세요.")
        else:
            ok = add_content(keyword, month, c_type, c_name.strip(), c_url.strip(), str(c_date))
            if ok:
                st.success("콘텐츠가 등록됐습니다. 반영 완료로 처리됩니다.")
                st.rerun()
            else:
                st.warning("이미 등록된 콘텐츠명입니다.")


# ══════════════════════════════════════════════════════
# 공유 렌더링 함수
# ══════════════════════════════════════════════════════

def _render_monthly_table(df_monthly: pd.DataFrame) -> None:
    if df_monthly.empty:
        st.info("집계할 데이터가 없습니다.")
        return

    def _row_html(row) -> str:
        s = row["KPI 달성"]
        if "달성" in s and "미달성" not in s:
            sc = "color:#1d4ed8;font-weight:700"
        elif "진행" in s:
            sc = "color:#92400e;font-weight:700"
        else:
            sc = "color:#dc2626;font-weight:700"
        return (
            f"<tr>"
            f"<td style='padding:6px 12px'>{row['월']}</td>"
            f"<td style='padding:6px 12px;text-align:center'>{row['도출 키워드']}건</td>"
            f"<td style='padding:6px 12px;text-align:center'>{row['반영 완료']}건</td>"
            f"<td style='padding:6px 12px;text-align:center'>{row['반영률(%)']}%</td>"
            f"<td style='padding:6px 12px;text-align:center;{sc}'>{s}</td>"
            f"<td style='padding:6px 12px;color:#64748b;font-size:0.85rem'>{row['비고']}</td>"
            f"</tr>"
        )

    rows_html = "\n".join(_row_html(r) for _, r in df_monthly.iterrows())
    st.markdown(f"""
<table style='width:100%;border-collapse:collapse;background:#fff;border-radius:8px;
              overflow:hidden;font-size:0.92rem;border:1px solid #DCE3EA'>
  <thead style='background:#f1f5f9;font-weight:700;color:#475569'>
    <tr>
      <th style='padding:8px 12px;text-align:left'>월</th>
      <th style='padding:8px 12px'>도출 키워드</th>
      <th style='padding:8px 12px'>반영 완료</th>
      <th style='padding:8px 12px'>반영률</th>
      <th style='padding:8px 12px'>KPI 달성</th>
      <th style='padding:8px 12px;text-align:left'>비고</th>
    </tr>
  </thead>
  <tbody>{rows_html}</tbody>
</table>""", unsafe_allow_html=True)


def _render_manual_input_form(df_monthly: pd.DataFrame, key_prefix: str = "") -> None:
    df_manual_cur = _read_manual_all()
    if not df_manual_cur.empty:
        st.markdown("**저장된 수동 입력 데이터**")
        for _, mr in df_manual_cur.iterrows():
            _mc1, _mc2, _mc3, _mc4, _mc5 = st.columns([2, 1.2, 1.2, 2.5, 1])
            with _mc1: st.text(mr["kpi_month"])
            with _mc2: st.text(f"도출 {mr['manual_derived']}건")
            with _mc3: st.text(f"반영 {mr['manual_reflected']}건")
            with _mc4: st.text(mr.get("note", "") or "")
            with _mc5:
                if st.button("삭제", key=f"{key_prefix}del_manual_{mr['kpi_month']}", type="secondary"):
                    delete_manual_month(mr["kpi_month"])
                    st.rerun()
        st.markdown("---")

    st.markdown("**새 달 추가**")
    _ma, _mb, _mc, _md = st.columns([2, 1.2, 1.2, 3])
    with _ma:
        m_month = st.text_input("월 (YYYY-MM)", placeholder="예: 2026-05", key=f"{key_prefix}manual_month_input")
    with _mb:
        m_derived = st.number_input("도출 건수", min_value=0, step=1, key=f"{key_prefix}manual_derived_input")
    with _mc:
        m_reflected = st.number_input("반영 건수", min_value=0, step=1, key=f"{key_prefix}manual_reflected_input")
    with _md:
        m_note = st.text_input("비고 (선택)", placeholder="예: 시스템 도입 전", key=f"{key_prefix}manual_note_input")

    if st.button("저장", type="primary", key=f"{key_prefix}manual_save_btn"):
        _month_str  = m_month.strip()
        _auto_months = set(df_monthly[df_monthly["비고"] == "자동 집계"]["월"].tolist()) if not df_monthly.empty else set()
        if not re.match(r"^\d{4}-\d{2}$", _month_str):
            st.warning("월은 YYYY-MM 형식으로 입력해 주세요.")
        elif _month_str == CURRENT_MONTH:
            st.warning("이번 달은 자동 집계되므로 수동 입력하지 않아도 됩니다.")
        elif _month_str in _auto_months:
            st.warning(f"{_month_str}은 자동 집계 데이터가 있습니다.")
        elif int(m_reflected) > int(m_derived):
            st.warning("반영 건수는 도출 건수보다 클 수 없습니다.")
        else:
            if add_manual_month(_month_str, int(m_derived), int(m_reflected), m_note.strip()):
                st.success(f"{_month_str} KPI 저장 완료!")
                st.rerun()
            else:
                st.error("저장 실패.")


def _render_news_insight(key_prefix: str, derived_kw_list: list) -> None:
    """이번 주 키워드 인사이트 공유 렌더링."""
    if f"{key_prefix}insight_sel_kws" not in st.session_state:
        st.session_state[f"{key_prefix}insight_sel_kws"] = derived_kw_list[:5]
    if f"{key_prefix}insight_articles" not in st.session_state:
        st.session_state[f"{key_prefix}insight_articles"] = None

    _sel_cleaned = [k for k in st.session_state[f"{key_prefix}insight_sel_kws"] if k in derived_kw_list]
    if _sel_cleaned != st.session_state[f"{key_prefix}insight_sel_kws"]:
        st.session_state[f"{key_prefix}insight_sel_kws"] = _sel_cleaned

    col_kw_sel, col_fetch, col_refresh = st.columns([6, 1.5, 1.2])
    with col_kw_sel:
        sel_kws = st.multiselect(
            "조회할 키워드 (최대 5개)",
            options=derived_kw_list,
            default=st.session_state[f"{key_prefix}insight_sel_kws"],
            max_selections=5,
            placeholder="키워드를 선택하세요",
            label_visibility="collapsed",
            key=f"{key_prefix}insight_multisel",
        )
        st.session_state[f"{key_prefix}insight_sel_kws"] = sel_kws
    with col_fetch:
        fetch_clicked = st.button(
            "이번 주 기사 불러오기",
            use_container_width=True, type="primary",
            key=f"{key_prefix}btn_fetch_news", disabled=not sel_kws,
        )
    with col_refresh:
        refresh_clicked = st.button(
            "새로고침",
            use_container_width=True, type="secondary",
            key=f"{key_prefix}btn_refresh_news",
            disabled=st.session_state[f"{key_prefix}insight_articles"] is None,
        )

    if refresh_clicked and sel_kws:
        fetch_news_articles.clear()
        st.session_state[f"{key_prefix}insight_articles"] = None
        st.rerun()

    if fetch_clicked and sel_kws:
        with st.spinner("네이버 뉴스에서 최근 7일 기사를 불러오는 중…"):
            st.session_state[f"{key_prefix}insight_articles"] = fetch_news_articles(
                keywords=tuple(sel_kws), days=7,
            )
        st.rerun()

    articles_data = st.session_state[f"{key_prefix}insight_articles"]
    if articles_data is None:
        st.info("키워드를 선택한 뒤 '이번 주 기사 불러오기'를 눌러 주세요.")
    elif not articles_data:
        st.warning("API 키를 확인하거나 잠시 후 다시 시도해 주세요.")
    else:
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
                kw_badge  = (
                    f"<span style='background:#EFF6FF;color:#1D4ED8;border-radius:4px;"
                    f"padding:1px 7px;font-size:11px;font-weight:600'>{art['_kw']}</span>"
                )
                media_str = f"<span style='color:#64748B;font-size:12px'>{art['media']} · {art['date']}</span>"
                st.markdown(f"{kw_badge} &nbsp; {media_str}", unsafe_allow_html=True)
                st.markdown(f"**[{art['title']}]({art['url']})**")
                if art["summary"]:
                    st.markdown(
                        f"<span style='font-size:13px;color:#475569'>{art['summary']}</span>",
                        unsafe_allow_html=True,
                    )
                st.markdown("<hr style='margin:8px 0;border-color:#DCE3EA'>", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════
# 메인 화면
# ══════════════════════════════════════════════════════
ensure_data()

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

# ── 공통 KPI 데이터 ──
df_cur         = load_derived(CURRENT_MONTH)
df_content_cur = load_content(CURRENT_MONTH)
KPI_DERIVED     = len(df_cur)
KPI_REFLECTED   = df_content_cur["keyword"].nunique() if not df_content_cur.empty else 0
KPI_TARGET_D    = 5
KPI_TARGET_R    = 70
reflection_rate = round(KPI_REFLECTED / KPI_DERIVED * 100) if KPI_DERIVED > 0 else 0
kpi_pass        = (KPI_DERIVED >= KPI_TARGET_D) and (reflection_rate >= KPI_TARGET_R)

tab1, tab2, tab3, tab4 = st.tabs([
    "📊 전체 현황",
    "🔍 급상승 키워드 발굴",
    "📈 트렌드 키워드 탐색",
    "📋 활용처 관리",
])


# ════════════════════════════════════════════════════
# TAB 1: 전체 현황
# ════════════════════════════════════════════════════
with tab1:

    st.markdown("""
<div class="sec-hdr">
  <div class="sh-t">이번 달 KPI 현황</div>
  <div class="sh-s">도출 목표 5건 · 반영률 목표 70% · 반영 완료는 적용 콘텐츠 등록 기준</div>
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

    st.markdown("<div style='margin-top:2rem'></div>", unsafe_allow_html=True)

    col_rec, col_undet, col_pending = st.columns(3, gap="medium")

    with col_rec:
        st.markdown("""<div class="sec-hdr"><div class="sh-t">최근 등록 키워드</div></div>""", unsafe_allow_html=True)
        df_all_t1 = _read_derived_all()
        if not df_all_t1.empty:
            recent5 = df_all_t1.sort_values("added_at", ascending=False).head(5)
            for _, r in recent5.iterrows():
                usage_label = r.get("usage_type", "") or "미지정"
                month_label = r.get("kpi_month", "")
                st.markdown(
                    f"• **{r['keyword']}** "
                    f"<span style='color:#667085;font-size:11.5px'>{month_label} · {usage_label}</span>",
                    unsafe_allow_html=True,
                )
        else:
            st.caption("등록된 키워드가 없습니다.")

    with col_undet:
        st.markdown("""<div class="sec-hdr"><div class="sh-t">활용처 미지정</div></div>""", unsafe_allow_html=True)
        df_all_check = _read_derived_all()
        if not df_all_check.empty:
            unset = df_all_check[df_all_check["usage_type"].str.strip() == ""]
            st.markdown(
                f"<div style='font-size:2rem;font-weight:800;color:#101828'>"
                f"{len(unset)}<span style='font-size:1rem;font-weight:400;color:#667085'>건</span></div>",
                unsafe_allow_html=True,
            )
            for _, r in unset.head(5).iterrows():
                st.caption(f"• {r['keyword']} ({r.get('kpi_month', '')})")
        else:
            st.markdown(
                "<div style='font-size:2rem;font-weight:800;color:#101828'>0"
                "<span style='font-size:1rem;font-weight:400;color:#667085'>건</span></div>",
                unsafe_allow_html=True,
            )

    with col_pending:
        st.markdown("""<div class="sec-hdr"><div class="sh-t">추적 데이터 대기</div></div>""", unsafe_allow_html=True)
        tracked_kws_t1  = load_tracked_keywords()
        df_trends_t1    = load_trends()
        if not df_trends_t1.empty and tracked_kws_t1:
            tracked_with_data = df_trends_t1["keyword"].unique().tolist()
            pending_kws = [k for k in tracked_kws_t1 if k not in tracked_with_data]
        else:
            pending_kws = tracked_kws_t1
        st.markdown(
            f"<div style='font-size:2rem;font-weight:800;color:#101828'>"
            f"{len(pending_kws)}<span style='font-size:1rem;font-weight:400;color:#667085'>건</span></div>",
            unsafe_allow_html=True,
        )
        for kw_p in pending_kws[:5]:
            st.caption(f"• {kw_p} — 수집 대기")

    st.markdown("<div style='margin-top:2rem'></div>", unsafe_allow_html=True)

    st.markdown("""
<div class="sec-hdr-main">
  <div class="sh-t">이번 주 키워드 인사이트</div>
  <div class="sh-s">최근 7일 국내 기사 · 네이버 뉴스 검색 API · 참고 자료용 — 반영률 집계 미포함</div>
</div>""", unsafe_allow_html=True)
    _derived_kw_list_t1 = df_cur["키워드"].tolist() if not df_cur.empty else []
    _render_news_insight("t1_", _derived_kw_list_t1)

    st.markdown("<div style='margin-top:2rem'></div>", unsafe_allow_html=True)

    with st.expander("📅 월별 KPI 누적 현황 (전체 기간)", expanded=False):
        df_monthly_t1 = load_monthly_kpi_summary()
        _buf_t1 = io.BytesIO()
        with pd.ExcelWriter(_buf_t1, engine="openpyxl") as _w_t1:
            df_monthly_t1.to_excel(_w_t1, index=False, sheet_name="월별 KPI 누적표")
        _col_t1, _ = st.columns([2, 5])
        with _col_t1:
            st.download_button(
                "⬇ 월별 KPI 엑셀", data=_buf_t1.getvalue(),
                file_name=f"monthly_kpi_{CURRENT_MONTH}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="t1_monthly_dl",
            )
        _render_monthly_table(df_monthly_t1)
        st.markdown("<div style='margin-top:1.2rem'></div>", unsafe_allow_html=True)
        st.caption("📝 과거 달 수동 입력")
        _render_manual_input_form(df_monthly_t1, key_prefix="t1_")


# ════════════════════════════════════════════════════
# TAB 2: 급상승 키워드 발굴
# ════════════════════════════════════════════════════
with tab2:

    # 도출 키워드 빠른 등록 — 탭 최상단
    st.markdown("""
<div class="sec-hdr-main">
  <div class="sh-t">도출 키워드 빠른 등록</div>
  <div class="sh-s">이번 달 발굴한 키워드를 바로 등록하세요. 등록 직후 모든 화면에 즉시 반영됩니다.</div>
</div>""", unsafe_allow_html=True)

    with st.form("quick_register_form_t2", clear_on_submit=True):
        col_kw2, col_usage2, col_btn2 = st.columns([4, 3, 1.3])
        with col_kw2:
            reg_keyword2 = st.text_input("키워드 *", placeholder="예: 제로트러스트")
        with col_usage2:
            reg_usage2 = st.selectbox("활용처 *", ["PR 기사", "온드미디어", "공통"])
        with col_btn2:
            st.markdown("<div style='height:29px'></div>", unsafe_allow_html=True)
            reg_submit2 = st.form_submit_button("＋ 키워드 등록", use_container_width=True, type="primary")
        with st.expander("추가 정보 입력 (선택)"):
            col_v2, col_i2 = st.columns(2)
            with col_v2:
                reg_vendor2 = st.text_input("관련 벤더", placeholder="예: Palo Alto")
            with col_i2:
                reg_idea2 = st.text_input("활용 아이디어·메모", placeholder="예: Q3 보도자료")
            reg_source_url2 = st.text_input("출처 URL", placeholder="https://...")

    if reg_submit2:
        kw2 = reg_keyword2.strip() if reg_keyword2 else ""
        if not kw2:
            st.warning("키워드를 입력해 주세요.")
        else:
            ok2 = add_keyword(
                kw2, CURRENT_MONTH,
                usage_type=reg_usage2,
                vendor=reg_vendor2.strip() if reg_vendor2 else "",
                idea=reg_idea2.strip() if reg_idea2 else "",
                source_url=reg_source_url2.strip() if reg_source_url2 else "",
                discovery_source="직접 입력",
            )
            if ok2:
                # 캐시 명시적 무효화 — 등록 후 즉시 전체 반영
                if gh.is_configured():
                    _load_derived_from_github.clear()
                st.success(f"'{kw2}' 등록 완료 — 활용처: {reg_usage2}")
                st.rerun()
            else:
                st.warning("이미 등록된 키워드입니다.")

    st.markdown("<div style='margin-top:2rem'></div>", unsafe_allow_html=True)

    # 마지막 업데이트 + 새로고침
    last_update_t2 = get_last_collection_time()
    col_upd_label, col_upd_btn = st.columns([7, 2])
    with col_upd_label:
        st.markdown(f"""
<div class="sec-hdr-main">
  <div class="sh-t">급상승 키워드 발굴
    <span style='font-weight:400;font-size:0.85rem;color:#667085'>
      &nbsp;마지막 업데이트 {last_update_t2}
    </span>
  </div>
  <div class="sh-s">구글 뉴스 기사 빈도 기반 · 1시간마다 자동 갱신</div>
</div>""", unsafe_allow_html=True)
    with col_upd_btn:
        st.markdown("<div style='margin-top:6px'></div>", unsafe_allow_html=True)
        if st.button("🔄 데이터 새로고침", key="btn_disc_refresh", use_container_width=True):
            get_news_keywords.clear()
            load_trends.clear()
            st.rerun()

    with st.spinner("IT 뉴스에서 키워드를 분석 중…"):
        news_kws, sources_ok = get_news_keywords()

    if news_kws:
        df_cur_t2      = load_derived(CURRENT_MONTH)
        tracked_set_t2 = set(load_tracked_keywords())
        derived_set_t2 = set(df_cur_t2["키워드"].tolist()) if not df_cur_t2.empty else set()

        st.caption(f"📰 {sources_ok}  |  1시간마다 자동 갱신")

        top8 = news_kws[:8]
        rest = news_kws[8:]

        for row_start in range(0, len(top8), 4):
            batch = top8[row_start:row_start + 4]
            cols_t2 = st.columns(4, gap="small")
            for col_c, (word, count) in zip(cols_t2, batch):
                with col_c:
                    is_tracking = word in tracked_set_t2
                    is_derived  = word in derived_set_t2
                    with st.container(border=True):
                        st.markdown(
                            f"<div style='font-size:1rem;font-weight:700;color:#101828;"
                            f"margin-bottom:4px'>{word}</div>"
                            f"<div style='font-size:11.5px;color:#667085;margin-bottom:10px'>"
                            f"언급 {count}회</div>",
                            unsafe_allow_html=True,
                        )
                        btn_c1, btn_c2 = st.columns(2)
                        with btn_c1:
                            if is_tracking:
                                st.markdown(
                                    "<span style='color:#059669;font-size:12px;"
                                    "font-weight:600'>📌 추적 중</span>",
                                    unsafe_allow_html=True,
                                )
                            else:
                                if st.button("📌 추적", key=f"t2_track_{word}",
                                             use_container_width=True, type="secondary"):
                                    add_tracked_keyword(word)
                                    with st.spinner("수집 중…"):
                                        collect_single_keyword(word)
                                        load_trends.clear()
                                    st.rerun()
                        with btn_c2:
                            if is_derived:
                                st.markdown(
                                    "<span style='color:#059669;font-size:12px;"
                                    "font-weight:600'>✅ 도출됨</span>",
                                    unsafe_allow_html=True,
                                )
                            else:
                                if st.button("＋ 도출", key=f"t2_derive_{word}",
                                             use_container_width=True, type="primary"):
                                    ok_d = add_keyword(word, CURRENT_MONTH, discovery_source="뉴스 자동탐지")
                                    if ok_d:
                                        if gh.is_configured():
                                            _load_derived_from_github.clear()
                                        st.rerun()
                                    else:
                                        st.info("이미 등록됨")

        if rest:
            st.markdown("<div style='margin-top:1.5rem'></div>", unsafe_allow_html=True)
            st.markdown("**더 보기**")
            h0, h1, h2, h3 = st.columns([0.5, 2.5, 1.2, 3.5])
            for c_h, lbl in zip([h0, h1, h2, h3], ["#", "키워드", "언급 수", "액션"]):
                c_h.markdown(f"<span class='kw-table-hdr'>{lbl}</span>", unsafe_allow_html=True)
            st.markdown("<hr style='margin:4px 0 4px'>", unsafe_allow_html=True)

            for i_r, (word, count) in enumerate(rest, start=9):
                is_tracking = word in tracked_set_t2
                is_derived  = word in derived_set_t2
                r0, r1, r2, r3 = st.columns([0.5, 2.5, 1.2, 3.5])
                with r0:
                    st.markdown(f"<span class='kw-cell' style='color:#667085'>{i_r}</span>", unsafe_allow_html=True)
                with r1:
                    st.markdown(f"<span class='kw-cell' style='font-weight:600'>{word}</span>", unsafe_allow_html=True)
                with r2:
                    st.markdown(f"<span class='kw-cell'>{count}회</span>", unsafe_allow_html=True)
                with r3:
                    btn_a, btn_b, _ = st.columns([1.2, 1, 1.5])
                    with btn_a:
                        if not is_tracking:
                            if st.button("📌 추적", key=f"t2_rtrack_{word}",
                                         use_container_width=True, type="secondary"):
                                add_tracked_keyword(word)
                                with st.spinner("수집 중…"):
                                    collect_single_keyword(word)
                                    load_trends.clear()
                                st.rerun()
                        else:
                            st.caption("추적 중")
                    with btn_b:
                        if not is_derived:
                            if st.button("＋ 도출", key=f"t2_rderive_{word}",
                                         use_container_width=True, type="primary"):
                                ok_r = add_keyword(word, CURRENT_MONTH, discovery_source="뉴스 자동탐지")
                                if ok_r:
                                    if gh.is_configured():
                                        _load_derived_from_github.clear()
                                    st.rerun()
                        else:
                            st.caption("도출됨")
                st.markdown("<hr style='margin:2px 0;border-color:#F7F9FC'>", unsafe_allow_html=True)
    else:
        st.info("뉴스 데이터를 불러오지 못했습니다.")

    st.markdown("<div style='margin-top:2rem'></div>", unsafe_allow_html=True)

    st.markdown("""
<div class="sec-hdr-main">
  <div class="sh-t">이번 주 키워드 인사이트</div>
  <div class="sh-s">최근 7일 국내 기사 · 네이버 뉴스 검색 API · 참고 자료용</div>
</div>""", unsafe_allow_html=True)
    _df_cur_t2_news = load_derived(CURRENT_MONTH)
    _derived_kw_list_t2 = _df_cur_t2_news["키워드"].tolist() if not _df_cur_t2_news.empty else []
    _render_news_insight("t2_", _derived_kw_list_t2)


# ════════════════════════════════════════════════════
# TAB 3: 트렌드 키워드 탐색
# ════════════════════════════════════════════════════
with tab3:

    st.markdown("""
<div class="sec-hdr-main">
  <div class="sh-t">추적 키워드 관리</div>
  <div class="sh-s">칩 클릭 → 그래프 숨김/복원 &nbsp;·&nbsp; ✕ → 목록에서 삭제 &nbsp;·&nbsp; 추가하면 즉시 데이터 수집</div>
</div>""", unsafe_allow_html=True)

    tracked_kws = load_tracked_keywords()

    if "hidden_kws" not in st.session_state:
        st.session_state["hidden_kws"] = set()
    st.session_state["hidden_kws"] &= set(tracked_kws)

    if tracked_kws:
        ctrl1, ctrl2, ctrl3, _ = st.columns([1.5, 1.5, 1.8, 5.5])
        with ctrl1:
            if st.button("전체 표시", key="t3_show_all", type="secondary", use_container_width=True):
                st.session_state["hidden_kws"] = set()
                st.rerun()
        with ctrl2:
            if st.button("전체 숨기기", key="t3_hide_all", type="secondary", use_container_width=True):
                st.session_state["hidden_kws"] = set(tracked_kws)
                st.rerun()
        with ctrl3:
            if st.button("⚠ 전체 추적 해제", key="t3_remove_all_btn", type="secondary", use_container_width=True):
                st.session_state["t3_confirm_remove_all"] = True

    if st.session_state.get("t3_confirm_remove_all", False):
        st.warning(f"추적 중인 키워드 {len(tracked_kws)}개를 모두 해제하시겠습니까?")
        col_can, col_con = st.columns([2, 2])
        with col_can:
            if st.button("취소", key="t3_cancel_remove", type="secondary"):
                st.session_state["t3_confirm_remove_all"] = False
                st.rerun()
        with col_con:
            if st.button("전체 추적 해제 확인", key="t3_confirm_remove", type="primary"):
                remove_all_tracked_keywords()
                st.session_state["hidden_kws"] = set()
                st.session_state["t3_confirm_remove_all"] = False
                st.rerun()

    if not tracked_kws:
        st.info("추적 중인 키워드가 없습니다. 아래에서 추가해 주세요.")
    else:
        CHIPS_PER_ROW = 5
        for row_start in range(0, len(tracked_kws), CHIPS_PER_ROW):
            batch  = tracked_kws[row_start:row_start + CHIPS_PER_ROW]
            widths = []
            for _ in batch:
                widths += [3, 0.45]
            widths.append(max(0.1, 16 - sum(widths)))
            chip_cols = st.columns(widths)
            for j, kw in enumerate(batch):
                is_hidden  = kw in st.session_state["hidden_kws"]
                chip_label = f"○ {kw}" if is_hidden else f"● {kw}"
                chip_help  = "다시 클릭하면 복원됩니다" if is_hidden else "클릭하면 그래프에서 숨깁니다"
                with chip_cols[j * 2]:
                    if st.button(chip_label, key=f"chip_toggle_{kw}",
                                 use_container_width=True, help=chip_help):
                        if is_hidden:
                            st.session_state["hidden_kws"].discard(kw)
                        else:
                            st.session_state["hidden_kws"].add(kw)
                        st.rerun()
                with chip_cols[j * 2 + 1]:
                    if st.button("✕", key=f"chip_del_{kw}", type="secondary",
                                 help=f"'{kw}' 추적 삭제"):
                        remove_tracked_keyword(kw)
                        st.session_state["hidden_kws"].discard(kw)
                        st.rerun()

    st.markdown("")
    col_add_in, col_add_btn = st.columns([5, 1])
    with col_add_in:
        new_track_kw = st.text_input(
            "새 추적 키워드", placeholder="예: 제로트러스트",
            label_visibility="collapsed", key="new_track_input",
        )
    with col_add_btn:
        if st.button("＋ 추가", use_container_width=True, type="primary", key="btn_track_add"):
            kw_t = new_track_kw.strip()
            if not kw_t:
                st.warning("키워드를 입력해 주세요.")
            elif not add_tracked_keyword(kw_t):
                st.info(f"'{kw_t}'는 이미 추적 중입니다.")
            else:
                with st.spinner(f"'{kw_t}' 데이터 수집 중…"):
                    naver_ok, google_ok = collect_single_keyword(kw_t)
                    load_trends.clear()
                msgs = []
                msgs.append("네이버 ✅" if naver_ok else "네이버 ⚠️ (키 확인 필요)")
                msgs.append("구글 ✅" if google_ok else "구글은 다음 수집 때 채워집니다")
                st.success(f"'{kw_t}' 추가 완료 — {' / '.join(msgs)}")
                st.rerun()

    st.markdown("<div style='margin-top:2rem'></div>", unsafe_allow_html=True)

    st.markdown("""
<div class="sec-hdr-main">
  <div class="sh-t">통합 검색 추이 비교</div>
  <div class="sh-s">비교할 키워드를 선택하세요. 최대 5개</div>
</div>""", unsafe_allow_html=True)

    if "period_days" not in st.session_state:
        st.session_state["period_days"] = 30

    col_kw_pick, col_period_t3 = st.columns([7, 3])
    with col_kw_pick:
        if "t3_sel_kws" not in st.session_state:
            st.session_state["t3_sel_kws"] = tracked_kws[:5]
        valid_tracked_set = set(tracked_kws)
        st.session_state["t3_sel_kws"] = [k for k in st.session_state["t3_sel_kws"] if k in valid_tracked_set]
        sel_kws_t3 = st.multiselect(
            "비교 키워드 (최대 5개)",
            options=tracked_kws,
            default=st.session_state["t3_sel_kws"],
            max_selections=5,
            placeholder="키워드를 선택하세요",
            key="t3_kw_multisel",
        )
        if sel_kws_t3 != st.session_state["t3_sel_kws"]:
            st.session_state["t3_sel_kws"] = sel_kws_t3
    with col_period_t3:
        PERIOD_OPTIONS  = {"7일": 7, "30일": 30, "90일": 90}
        period_label_t3 = st.radio(
            "기간", list(PERIOD_OPTIONS.keys()),
            horizontal=True,
            index=list(PERIOD_OPTIONS.values()).index(st.session_state["period_days"]),
            key="t3_period_radio",
        )
        st.session_state["period_days"] = PERIOD_OPTIONS[period_label_t3]

    period_days_t3 = st.session_state["period_days"]
    cutoff_t3      = pd.Timestamp.today().normalize() - pd.Timedelta(days=period_days_t3)
    df_trends_t3   = load_trends()

    if not sel_kws_t3:
        st.info("위에서 비교할 키워드를 선택해 주세요.")
    elif df_trends_t3.empty:
        st.warning("data/trends.csv 에 데이터가 없습니다. 터미널에서 `python collector.py` 를 실행해 주세요.")
    else:
        df_period_t3 = df_trends_t3[
            (df_trends_t3["keyword"].isin(sel_kws_t3)) & (df_trends_t3["date"] >= cutoff_t3)
        ]

        src_choice = st.radio(
            "데이터 소스", ["네이버 데이터랩", "구글 트렌드"],
            horizontal=True, key="t3_src_radio",
        )
        src_key = "naver" if src_choice == "네이버 데이터랩" else "google"
        st.caption("국내 검색 기준 · 0~100 상대 지수" if src_key == "naver" else "국내·글로벌 검색 기준 · 0~100 상대 지수")

        draw_unified_chart(df_period_t3, sel_kws_t3, src_key,
                           chart_key=f"t3_unified_{src_key}_{period_days_t3}")
        st.caption("⚠️ 네이버(일별)와 구글(주별)은 집계 기준이 달라 직접 비교하지 마세요.")

        with st.expander("원본 데이터 보기"):
            df_src_t3 = df_period_t3[df_period_t3["source"] == src_key].copy()
            if not df_src_t3.empty:
                df_src_t3["date"] = df_src_t3["date"].dt.strftime("%Y-%m-%d")
                st.dataframe(
                    df_src_t3[["keyword", "date", "ratio"]].rename(
                        columns={"keyword": "키워드", "date": "날짜", "ratio": "관심도"}
                    ).sort_values("날짜", ascending=False).head(60),
                    use_container_width=True, hide_index=True,
                )
            else:
                st.info("해당 소스의 데이터가 없습니다.")

        st.markdown("<div style='margin-top:2rem'></div>", unsafe_allow_html=True)

        # 키워드별 요약 카드 — 각 키워드를 완전히 독립 처리 (다중 키워드 버그 수정)
        st.markdown(f"""
<div class="sec-hdr">
  <div class="sh-t">키워드별 추이 요약</div>
  <div class="sh-s">최근 {period_days_t3}일 기준 · 각 키워드 독립 처리 — 한 키워드의 데이터 부족이 나머지에 영향을 주지 않습니다</div>
</div>""", unsafe_allow_html=True)

        NUM_COLS_T3  = min(3, len(sel_kws_t3)) if sel_kws_t3 else 1
        card_cols_t3 = st.columns(NUM_COLS_T3, gap="medium")

        for i_kw, kw in enumerate(sel_kws_t3):
            # 키워드마다 새로운 로컬 변수 — session_state 공유 없음
            _df_kw_n = df_period_t3[
                (df_period_t3["keyword"] == kw) & (df_period_t3["source"] == "naver")
            ].copy()
            _df_kw_g = df_period_t3[
                (df_period_t3["keyword"] == kw) & (df_period_t3["source"] == "google")
            ].copy()
            _stats_n = compute_kw_stats(_df_kw_n)
            _stats_g = compute_kw_stats(_df_kw_g)

            with card_cols_t3[i_kw % NUM_COLS_T3]:
                with st.container(border=True):
                    st.markdown(f"<div class='trend-card-kw'>{kw}</div>", unsafe_allow_html=True)

                    if not _stats_n and not _stats_g:
                        st.caption("데이터 없음 — 수집 대기 중")
                        continue

                    _stats    = _stats_n if _stats_n else _stats_g
                    _src_note = "네이버" if _stats_n else "구글"

                    _wk_chg_str  = f"+{_stats['wk_chg']:.1f}%" if _stats['wk_chg'] >= 0 else f"{_stats['wk_chg']:.1f}%"
                    _wk_color    = "#059669" if _stats['wk_chg'] >= 0 else "#DC2626"
                    _avg_chg_str = f"+{_stats['avg_chg']:.1f}%" if _stats['avg_chg'] >= 0 else f"{_stats['avg_chg']:.1f}%"
                    _avg_color   = "#059669" if _stats['avg_chg'] >= 0 else "#DC2626"

                    st.markdown(f"""
<div class='trend-stat'>현재 관심도 <strong>{_stats['current']:.0f}</strong>
  <span style='font-size:11px;color:#667085'>({_src_note})</span></div>
<div class='trend-stat'>전주 대비 <strong style='color:{_wk_color}'>{_wk_chg_str}</strong></div>
<div class='trend-stat'>최근 4주 평균 <strong>{_stats['avg4']:.1f}</strong></div>
<div class='trend-stat'>이전 4주 대비 <strong style='color:{_avg_color}'>{_avg_chg_str}</strong></div>
""", unsafe_allow_html=True)

                    _trend_label = _stats["trend_label"]
                    _trend_tip   = _stats["trend_tip"]

                    if "상승" in _trend_label or "반등" in _trend_label:
                        _bg, _fg = "#ECFDF5", "#065F46"
                    elif "하락" in _trend_label:
                        _bg, _fg = "#FEF2F2", "#991B1B"
                    elif "대기" in _trend_label:
                        _bg, _fg = "#F7F9FC", "#667085"
                    else:
                        _bg, _fg = "#EFF6FF", "#2F6BFF"

                    st.markdown(
                        f"<span title='{_trend_tip}' style='display:inline-block;"
                        f"background:{_bg};color:{_fg};border-radius:20px;"
                        f"padding:2px 10px;font-size:11.5px;font-weight:700;margin-top:6px'>"
                        f"{_trend_label}</span>",
                        unsafe_allow_html=True,
                    )

                    if _stats_n and len(_stats_n["series"]) >= 3:
                        st.plotly_chart(
                            make_sparkline(_stats_n["series"], "#2F6BFF"),
                            use_container_width=True,
                            config={"displayModeBar": False},
                            key=f"t3_spark_n_{kw}_{period_days_t3}_{i_kw}",
                        )


# ════════════════════════════════════════════════════
# TAB 4: 활용처 관리
# ════════════════════════════════════════════════════
with tab4:

    # 탭 내부에서 최신 데이터 재조회 — 빠른 등록 후 즉시 반영
    df_cur_t4     = load_derived(CURRENT_MONTH)
    df_content_t4 = load_content(CURRENT_MONTH)

    st.markdown("""
<div class="sec-hdr-main">
  <div class="sh-t">활용처 · 반영 현황</div>
  <div class="sh-s">'수정' 버튼으로 활용처 변경 및 적용 콘텐츠를 등록합니다. 저장 후 앱 재접속에도 유지됩니다.</div>
</div>""", unsafe_allow_html=True)

    col_filter_t4, col_dl_t4 = st.columns([7, 2])
    with col_filter_t4:
        filter_tab_t4 = st.radio(
            "활용처 필터", ["전체", "PR 기사", "온드미디어", "미지정"],
            horizontal=True, label_visibility="collapsed", key="t4_filter",
        )
    with col_dl_t4:
        st.download_button(
            "⬇ 엑셀 다운로드", data=build_excel(),
            file_name=f"keyword_kpi_{CURRENT_MONTH}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True, key="t4_dl_btn",
        )

    if df_cur_t4.empty:
        st.info("이번 달 등록된 도출 키워드가 없습니다. '급상승 키워드 발굴' 탭에서 추가해 주세요.")
    else:
        if filter_tab_t4 == "전체":
            df_filtered_t4 = df_cur_t4.copy()
        elif filter_tab_t4 == "PR 기사":
            df_filtered_t4 = df_cur_t4[df_cur_t4["활용처"].isin(["PR 기사", "공통"])].copy()
        elif filter_tab_t4 == "온드미디어":
            df_filtered_t4 = df_cur_t4[df_cur_t4["활용처"].isin(["온드미디어", "공통"])].copy()
        else:
            df_filtered_t4 = df_cur_t4[df_cur_t4["활용처"].str.strip() == ""].copy()

        if not df_content_t4.empty:
            latest_cont_t4 = (
                df_content_t4.sort_values("added_at", ascending=False)
                .drop_duplicates(subset="keyword", keep="first")
                .set_index("keyword")
            )
            cont_counts_t4 = df_content_t4.groupby("keyword").size().to_dict()
        else:
            latest_cont_t4 = pd.DataFrame()
            cont_counts_t4 = {}

        h0, h1, h2, h3, h4, h5, h6 = st.columns([2.5, 1.8, 1.5, 3.2, 1.4, 1.6, 1.2])
        for c_h, lbl in zip(
            [h0, h1, h2, h3, h4, h5, h6],
            ["키워드", "활용처", "상태", "적용 콘텐츠명", "링크", "반영일", "수정"],
        ):
            c_h.markdown(f"<span class='kw-table-hdr'>{lbl}</span>", unsafe_allow_html=True)
        st.markdown("<hr style='margin:6px 0 4px;'>", unsafe_allow_html=True)

        for row_idx, row in df_filtered_t4.iterrows():
            kw     = row["키워드"]
            usage  = row["활용처"] or ""
            status = row["상태"] or "도출"

            has_cont = not latest_cont_t4.empty and kw in latest_cont_t4.index
            if has_cont:
                cont      = latest_cont_t4.loc[kw]
                cont_name = cont.get("content_name", "")
                cont_url  = cont.get("url", "")
                cont_date = cont.get("published_at", "")
                cnt_total = cont_counts_t4.get(kw, 0)
            else:
                cont_name = cont_url = cont_date = ""
                cnt_total = 0

            if usage == "PR 기사":
                u_html = f"<span class='usage-tag-pr'>{usage}</span>"
            elif usage == "온드미디어":
                u_html = f"<span class='usage-tag-owned'>{usage}</span>"
            elif usage == "공통":
                u_html = f"<span class='usage-tag-common'>{usage}</span>"
            else:
                u_html = "<span class='usage-tag-none'>미지정</span>"

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
                    st.markdown(f"[콘텐츠 보기]({cont_url})")
                else:
                    st.markdown("<span style='color:#94A3B8;font-size:13px'>—</span>", unsafe_allow_html=True)
            with r5:
                st.markdown(
                    f"<span class='kw-cell' style='color:#64748B'>{cont_date or '—'}</span>",
                    unsafe_allow_html=True,
                )
            with r6:
                # row_idx 포함 → 동일 키워드명이 있어도 위젯 key 충돌 없음
                if st.button("수정", key=f"t4_edit_{kw}_{CURRENT_MONTH}_{row_idx}",
                             use_container_width=True):
                    content_dialog(kw, CURRENT_MONTH, usage)

            st.markdown("<hr style='margin:4px 0;border-color:#F7F9FC'>", unsafe_allow_html=True)

    with st.expander("키워드 삭제"):
        st.caption("잘못 등록된 키워드를 삭제합니다. 연결된 적용 콘텐츠도 함께 삭제됩니다.")
        if not df_cur_t4.empty:
            del_options_t4 = df_cur_t4["키워드"].tolist()
            del_kw_t4 = st.selectbox(
                "삭제할 키워드 선택", del_options_t4,
                label_visibility="collapsed", key="t4_del_kw_sel",
            )
            if st.button("선택한 키워드 삭제", type="secondary", key="t4_btn_del_kw"):
                delete_keyword(del_kw_t4, CURRENT_MONTH)
                df_c = _read_content_all()
                df_c = df_c[~((df_c["keyword"] == del_kw_t4) & (df_c["kpi_month"] == CURRENT_MONTH))]
                _write_content(df_c, f"콘텐츠 일괄 삭제: {del_kw_t4}")
                st.success(f"'{del_kw_t4}' 삭제됐습니다.")
                st.rerun()
        else:
            st.info("삭제할 키워드가 없습니다.")

    st.markdown("<div style='margin-top:2rem'></div>", unsafe_allow_html=True)

    with st.expander("📅 월별 KPI 누적 현황 및 수동 입력"):
        df_monthly_t4 = load_monthly_kpi_summary()
        _buf_t4 = io.BytesIO()
        with pd.ExcelWriter(_buf_t4, engine="openpyxl") as _w_t4:
            df_monthly_t4.to_excel(_w_t4, index=False, sheet_name="월별 KPI 누적표")
        _col_dl_t4b, _ = st.columns([2, 5])
        with _col_dl_t4b:
            st.download_button(
                "⬇ 월별 KPI 엑셀", data=_buf_t4.getvalue(),
                file_name=f"monthly_kpi_{CURRENT_MONTH}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="t4_monthly_dl",
            )
        _render_monthly_table(df_monthly_t4)
        st.markdown("<div style='margin-top:1.2rem'></div>", unsafe_allow_html=True)
        st.caption("📝 과거 달 수동 입력 (시스템에 기록이 없는 달)")
        _render_manual_input_form(df_monthly_t4, key_prefix="t4_")


# ── 푸터 ──
_trend_cnt = len(pd.read_csv(TRENDS_CSV)) if os.path.exists(TRENDS_CSV) else 0
st.markdown(f"""
<div style="margin-top:3rem;padding-top:1.5rem;border-top:1px solid #DCE3EA;
            display:flex;justify-content:space-between;align-items:center;
            font-size:11px;color:#94A3B8;">
  <span>키워드 인텔리전스 · SCK/STK Corp · {CURRENT_MONTH}</span>
  <span>트렌드 데이터 {_trend_cnt:,}건 · 네이버 데이터랩 · 구글 트렌드</span>
</div>""", unsafe_allow_html=True)
