"""
키워드 트렌드 KPI 대시보드 — 4탭 구조
BUILD: 2026-06-30-KEYWORD-V2
"""
import io, os, re
from datetime import datetime, date, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests as _req
import streamlit as st

import github_storage as gh
from news_crawler import fetch_news_keywords
from collector import collect_single_keyword

# ── 상수 ──────────────────────────────────────────────
BUILD_VERSION = "2026-06-30-KEYWORD-V2"

BASE_DIR    = os.path.dirname(__file__)
DATA_DIR    = os.path.join(BASE_DIR, "data")
TRENDS_CSV  = os.path.join(DATA_DIR, "trends.csv")
DERIVED_CSV = os.path.join(DATA_DIR, "derived_keywords.csv")
CONTENT_CSV = os.path.join(DATA_DIR, "applied_content.csv")
TRACKED_CSV = os.path.join(DATA_DIR, "tracked_keywords.csv")
MANUAL_CSV  = os.path.join(DATA_DIR, "monthly_manual.csv")

DERIVED_COLS = ["keyword","kpi_month","usage_type","status",
                "vendor","idea","source_url","discovery_source","added_at"]
CONTENT_COLS = ["keyword","kpi_month","content_type",
                "content_name","url","published_at","added_at"]
TRENDS_COLS  = ["keyword","date","ratio","source","collected_at"]
TRACKED_COLS = ["keyword","added_at"]
MANUAL_COLS  = ["kpi_month","manual_derived","manual_reflected","note","added_at"]

CURRENT_MONTH = datetime.today().strftime("%Y-%m")

# ── 페이지 설정 ───────────────────────────────────────
st.set_page_config(page_title="키워드 인텔리전스 | SCK·STK",
                   page_icon="📊", layout="wide")

st.markdown("""
<style>
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.css');
*,*::before,*::after{font-family:'Pretendard',-apple-system,BlinkMacSystemFont,'Apple SD Gothic Neo',sans-serif!important;word-break:keep-all}
#MainMenu,footer,.stApp>header,[data-testid="stToolbar"],[data-testid="stDecoration"]{display:none!important}
.block-container{max-width:1400px!important;padding:0 2rem 4rem!important;margin:0 auto!important}
.stApp{background:#F7F9FC}

/* ─ 탭 ─ */
[data-testid="stTabs"] [role="tablist"]{border-bottom:2px solid #DCE3EA;gap:0;padding:0}
[data-testid="stTabs"] [role="tab"]{font-weight:600!important;font-size:14px!important;color:#667085!important;padding:10px 22px!important;border-bottom:3px solid transparent!important;margin-bottom:-2px!important;transition:color .15s}
[data-testid="stTabs"] [role="tab"][aria-selected="true"]{color:#2F6BFF!important;border-bottom:3px solid #2F6BFF!important;background:transparent!important}
[data-testid="stTabs"] [role="tab"]:hover{color:#2F6BFF!important;background:#F0F5FF!important}
[data-testid="stTabsContent"]{padding-top:1.6rem}

/* ─ 헤더 ─ */
.kd-header{display:flex;align-items:center;justify-content:space-between;background:#fff;border-bottom:1px solid #DCE3EA;padding:9px 2rem;margin:0 -2rem 0 -2rem}
.kd-logo{display:flex;align-items:center;gap:9px}
.kd-mark{width:26px;height:26px;background:#2F6BFF;border-radius:6px;display:flex;align-items:center;justify-content:center;color:#fff;font-size:13px;font-weight:800}
.kd-name{font-size:13px;font-weight:700;color:#102A43}
.kd-meta{display:flex;align-items:center;gap:14px;font-size:11.5px;color:#667085}
.kd-live{background:#F0FDF4;color:#166534;padding:3px 10px;border-radius:20px;font-weight:700;font-size:11px}
.kd-live::before{content:"● ";color:#16A34A;font-size:8px}

/* ─ 히어로 ─ */
.kd-hero{padding:1.4rem 0 1.1rem;border-bottom:1px solid #DCE3EA;margin-bottom:1.4rem}
.kd-hero-title{font-size:1.55rem;font-weight:800;color:#102A43;margin:0 0 .35rem;line-height:1.25;letter-spacing:-.01em}
.kd-hero-sub{font-size:.88rem;color:#667085;margin:0;line-height:1.5}

/* ─ 섹션 헤더 ─ */
.sh-main{margin:0 0 1.3rem;border-left:4px solid #2F6BFF;padding-left:14px}
.sh-main .t{font-size:1.05rem;font-weight:800;color:#102A43;margin:0;line-height:1.3}
.sh-main .s{font-size:12px;color:#667085;margin:3px 0 0;line-height:1.5}
.sh-sub{border-left:3px solid #2F6BFF;padding-left:11px;margin:0 0 10px}
.sh-sub .t{font-size:14px;font-weight:700;color:#101828;margin:0}
.sh-sub .s{font-size:11.5px;color:#667085;margin:2px 0 0}

/* ─ KPI 카드 ─ */
.kpi-card{background:#fff;border:1px solid #DCE3EA;border-radius:12px;padding:18px 20px 16px}
.kpi-lbl{font-size:10px;font-weight:700;color:#667085;text-transform:uppercase;letter-spacing:.07em;margin-bottom:9px}
.kpi-val{font-size:2.5rem;font-weight:800;color:#101828;line-height:1}
.kpi-unit{font-size:.88rem;font-weight:400;color:#667085;margin-left:3px}
.kpi-hint{font-size:11.5px;color:#667085;margin-top:7px}
.bdg-pass{display:inline-block;background:#ECFDF5;color:#065F46;border-radius:6px;padding:6px 16px;font-weight:700;font-size:14px;margin-top:9px}
.bdg-fail{display:inline-block;background:#FFF7ED;color:#9A3412;border-radius:6px;padding:6px 16px;font-weight:700;font-size:14px;margin-top:9px}

/* ─ 태그 ─ */
.tag-pr{display:inline-block;background:#EFF6FF;color:#1e40af;border-radius:4px;padding:2px 8px;font-size:11.5px;font-weight:600}
.tag-owned{display:inline-block;background:#FDF4FF;color:#7e22ce;border-radius:4px;padding:2px 8px;font-size:11.5px;font-weight:600}
.tag-common{display:inline-block;background:#F0FDF4;color:#166534;border-radius:4px;padding:2px 8px;font-size:11.5px;font-weight:600}
.tag-none{display:inline-block;background:#F1F5F9;color:#94A3B8;border-radius:4px;padding:2px 8px;font-size:11.5px;font-weight:600}
.tag-done{display:inline-block;background:#EFF6FF;color:#1D4ED8;border-radius:4px;padding:2px 8px;font-size:11.5px;font-weight:600}
.tag-todo{display:inline-block;background:#F1F5F9;color:#475569;border-radius:4px;padding:2px 8px;font-size:11.5px;font-weight:600}

/* ─ 트렌드 카드 ─ */
.tc-kw{font-size:1rem;font-weight:800;color:#101828;margin-bottom:9px}
.tc-row{font-size:13px;color:#667085;margin:3px 0}
.tc-row strong{color:#101828}

/* ─ 테이블 헤더 ─ */
.th{font-size:10.5px;font-weight:700;color:#667085;text-transform:uppercase;letter-spacing:.05em}
.td{font-size:13px;line-height:1.65}

/* ─ 기타 ─ */
hr{border-color:#DCE3EA!important;margin:1.2rem 0!important}
.stProgress>div>div{background:#2F6BFF!important}
.notice-box{background:#EFF6FF;border:1px solid #BFDBFE;border-radius:8px;padding:10px 14px;font-size:13px;color:#1e40af;margin:.6rem 0}
.warn-box{background:#FEF3C7;border:1px solid #FDE68A;border-radius:8px;padding:10px 14px;font-size:13px;color:#92400E;margin:.6rem 0}

/* ─ 익스팬더 — _arr 텍스트 겹침 수정 ─ */
[data-testid="stExpander"]>details{border:1px solid #DCE3EA;border-radius:8px;overflow:hidden;margin:.5rem 0}
[data-testid="stExpander"]>details>summary{display:flex!important;align-items:center!important;list-style:none!important;padding:10px 16px!important;cursor:pointer!important;background:#fff!important;user-select:none!important;gap:0!important}
[data-testid="stExpander"]>details>summary::-webkit-details-marker{display:none!important}
[data-testid="stExpander"]>details>summary::marker{display:none!important}
/* 내부 클래스명 텍스트(_arr 등) 숨김 */
[data-testid="stExpander"] summary>span{font-size:0!important;line-height:0!important;overflow:hidden!important;display:inline-flex!important;align-items:center!important;justify-content:center!important;width:20px!important;height:20px!important;flex-shrink:0!important}
[data-testid="stExpander"] summary>span svg{width:16px!important;height:16px!important;display:block!important}
/* 레이블 텍스트 */
[data-testid="stExpander"] summary p,[data-testid="stExpander"] summary div>p{margin:0!important;font-size:14px!important;font-weight:600!important;color:#101828!important;line-height:1.5!important}

@media(max-width:768px){
  .block-container{padding:0 1rem 3rem!important}
  .kd-header{padding:8px 1rem;margin:0 -1rem;flex-wrap:wrap;gap:6px}
  .kpi-val{font-size:2rem}
}
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════
# 초기화
# ══════════════════════════════════════════════════════════
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
        changed = False
        for col in DERIVED_COLS:
            if col not in df.columns:
                df[col] = ""; changed = True
        if "status" not in df.columns or (df["status"] == "").all():
            if "reflected" in df.columns:
                df["status"] = df["reflected"].apply(lambda x: "반영완료" if str(x).strip() in ["1","true","True"] else "도출")
            else:
                df["status"] = "도출"
            changed = True
        if changed:
            df[DERIVED_COLS].fillna("").to_csv(DERIVED_CSV, index=False, encoding="utf-8-sig")
    if not os.path.exists(CONTENT_CSV):
        pd.DataFrame(columns=CONTENT_COLS).to_csv(CONTENT_CSV, index=False, encoding="utf-8-sig")
    if not os.path.exists(MANUAL_CSV):
        pd.DataFrame(columns=MANUAL_COLS).to_csv(MANUAL_CSV, index=False, encoding="utf-8-sig")
    if not os.path.exists(TRACKED_CSV):
        try:
            from keywords import KEYWORDS as _kws
        except ImportError:
            _kws = []
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        pd.DataFrame([[k, now] for k in _kws], columns=TRACKED_COLS).to_csv(
            TRACKED_CSV, index=False, encoding="utf-8-sig")


# ══════════════════════════════════════════════════════════
# 도출 키워드 CRUD
# ══════════════════════════════════════════════════════════
@st.cache_data(ttl=30)
def _gh_load_derived() -> pd.DataFrame:
    df = gh.read_csv("data/derived_keywords.csv")
    return df if df is not None else pd.DataFrame(columns=DERIVED_COLS)

def _invalidate_derived():
    _gh_load_derived.clear()

def _read_derived_all() -> pd.DataFrame:
    if gh.is_configured():
        df = _gh_load_derived()
    elif not os.path.exists(DERIVED_CSV):
        return pd.DataFrame(columns=DERIVED_COLS)
    else:
        try:
            df = pd.read_csv(DERIVED_CSV, dtype=str)
        except Exception:
            return pd.DataFrame(columns=DERIVED_COLS)
    df = df.fillna("")
    for c in DERIVED_COLS:
        if c not in df.columns:
            df[c] = ""
    return df

def _write_derived(df: pd.DataFrame, msg: str) -> bool:
    if gh.is_configured():
        ok = gh.write_csv(df, "data/derived_keywords.csv", msg)
        if ok: _invalidate_derived()
        return ok
    df[DERIVED_COLS].to_csv(DERIVED_CSV, index=False, encoding="utf-8-sig")
    return True

def load_derived(month: str) -> pd.DataFrame:
    cols = ["키워드","활용처","상태","벤더","아이디어","출처URL","등록출처","등록일"]
    df = _read_derived_all()
    if df.empty or "kpi_month" not in df.columns:
        return pd.DataFrame(columns=cols)
    df = df[df["kpi_month"] == month].copy()
    for c, v in [("keyword",""),("kpi_month",month),("usage_type",""),("status","도출"),
                 ("vendor",""),("idea",""),("source_url",""),("discovery_source","직접 입력"),("added_at","")]:
        if c not in df.columns: df[c] = v
    df = df.rename(columns={"keyword":"키워드","kpi_month":"월","usage_type":"활용처",
                             "status":"상태","vendor":"벤더","idea":"아이디어",
                             "source_url":"출처URL","discovery_source":"등록출처","added_at":"등록일"})
    return df.reindex(columns=cols, fill_value="").reset_index(drop=True)

def add_keyword(keyword: str, month: str, usage_type: str="",
                vendor: str="", idea: str="", source_url: str="",
                discovery_source: str="직접 입력") -> bool:
    df = _read_derived_all()
    if not df.empty and ((df["keyword"]==keyword)&(df["kpi_month"]==month)).any():
        return False
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    row = pd.DataFrame([[keyword, month, usage_type, "도출", vendor, idea, source_url, discovery_source, now]],
                       columns=DERIVED_COLS)
    df = pd.concat([df, row], ignore_index=True)
    _write_derived(df, f"키워드 추가: {keyword} ({month})")
    return True

def delete_keyword(keyword: str, month: str):
    df = _read_derived_all()
    df = df[~((df["keyword"]==keyword)&(df["kpi_month"]==month))]
    _write_derived(df, f"키워드 삭제: {keyword} ({month})")

def update_usage_type(keyword: str, month: str, new_usage: str) -> bool:
    """활용처를 영구 저장소에 직접 수정합니다."""
    df = _read_derived_all()
    mask = (df["keyword"]==keyword)&(df["kpi_month"]==month)
    if not mask.any():
        return False
    df.loc[mask, "usage_type"] = new_usage
    return bool(_write_derived(df, f"활용처 변경: {keyword} → {new_usage}"))

def _set_status(keyword: str, month: str, status: str):
    df = _read_derived_all()
    mask = (df["keyword"]==keyword)&(df["kpi_month"]==month)
    if mask.any():
        df.loc[mask, "status"] = status
        _write_derived(df, f"상태 변경: {keyword} → {status}")


# ══════════════════════════════════════════════════════════
# 콘텐츠 CRUD
# ══════════════════════════════════════════════════════════
@st.cache_data(ttl=30)
def _gh_load_content() -> pd.DataFrame:
    df = gh.read_csv("data/applied_content.csv")
    return df if df is not None else pd.DataFrame(columns=CONTENT_COLS)

def _invalidate_content():
    _gh_load_content.clear()

def _read_content_all() -> pd.DataFrame:
    if gh.is_configured():
        return _gh_load_content()
    if not os.path.exists(CONTENT_CSV):
        return pd.DataFrame(columns=CONTENT_COLS)
    df = pd.read_csv(CONTENT_CSV, dtype=str).fillna("")
    for c in CONTENT_COLS:
        if c not in df.columns: df[c] = ""
    return df

def _write_content(df: pd.DataFrame, msg: str) -> bool:
    if gh.is_configured():
        ok = gh.write_csv(df, "data/applied_content.csv", msg)
        if ok: _invalidate_content()
        return ok
    df[CONTENT_COLS].to_csv(CONTENT_CSV, index=False, encoding="utf-8-sig")
    return True

def load_content(month: str) -> pd.DataFrame:
    df = _read_content_all()
    if df.empty or "kpi_month" not in df.columns:
        return pd.DataFrame(columns=CONTENT_COLS)
    return df[df["kpi_month"]==month].copy().reset_index(drop=True)

def add_content(keyword,month,ctype,cname,url,pub_at) -> bool:
    df = _read_content_all()
    if not df.empty and ((df["keyword"]==keyword)&(df["kpi_month"]==month)&(df["content_name"]==cname)).any():
        return False
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    row = pd.DataFrame([[keyword,month,ctype,cname,url,pub_at,now]], columns=CONTENT_COLS)
    df = pd.concat([df, row], ignore_index=True)
    _write_content(df, f"콘텐츠 등록: {keyword} — {cname}")
    _set_status(keyword, month, "반영완료")
    return True

def delete_content_row(keyword,month,cname):
    df = _read_content_all()
    df = df[~((df["keyword"]==keyword)&(df["kpi_month"]==month)&(df["content_name"]==cname))]
    _write_content(df, f"콘텐츠 삭제: {keyword} — {cname}")
    if df[(df["keyword"]==keyword)&(df["kpi_month"]==month)].empty:
        _set_status(keyword, month, "도출")


# ══════════════════════════════════════════════════════════
# 월별 수동 KPI
# ══════════════════════════════════════════════════════════
@st.cache_data(ttl=30)
def _gh_load_manual() -> pd.DataFrame:
    df = gh.read_csv("data/monthly_manual.csv")
    return df if df is not None else pd.DataFrame(columns=MANUAL_COLS)

def _read_manual_all() -> pd.DataFrame:
    if gh.is_configured():
        df = _gh_load_manual()
    elif not os.path.exists(MANUAL_CSV):
        return pd.DataFrame(columns=MANUAL_COLS)
    else:
        try:
            df = pd.read_csv(MANUAL_CSV, dtype=str)
        except Exception:
            return pd.DataFrame(columns=MANUAL_COLS)
    df = df.fillna("")
    for c in MANUAL_COLS:
        if c not in df.columns: df[c] = ""
    return df

def _write_manual(df: pd.DataFrame, msg: str) -> bool:
    if gh.is_configured():
        ok = gh.write_csv(df, "data/monthly_manual.csv", msg)
        if ok: _gh_load_manual.clear()
        return ok
    df[MANUAL_COLS].to_csv(MANUAL_CSV, index=False, encoding="utf-8-sig")
    return True

def add_manual_month(month,derived,reflected,note="") -> bool:
    df = _read_manual_all()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if month in df["kpi_month"].values:
        idx = df[df["kpi_month"]==month].index[0]
        df.loc[idx, ["manual_derived","manual_reflected","note","added_at"]] = [str(derived),str(reflected),note,now]
    else:
        df = pd.concat([df, pd.DataFrame([{"kpi_month":month,"manual_derived":str(derived),
                                           "manual_reflected":str(reflected),"note":note,"added_at":now}])],
                       ignore_index=True)
    return _write_manual(df[MANUAL_COLS], f"수동 KPI 입력: {month}")

def delete_manual_month(month) -> bool:
    df = _read_manual_all()
    df = df[df["kpi_month"]!=month].reset_index(drop=True)
    return _write_manual(df[MANUAL_COLS], f"수동 KPI 삭제: {month}")

def load_monthly_kpi_summary() -> pd.DataFrame:
    df_d = _read_derived_all(); df_c = _read_content_all(); df_m = _read_manual_all()
    auto = {}
    if not df_d.empty and "kpi_month" in df_d.columns:
        for month, grp in df_d.groupby("kpi_month"):
            if not month: continue
            kws = grp["keyword"].tolist()
            done = df_c[(df_c["kpi_month"]==month)&(df_c["keyword"].isin(kws))]["keyword"].nunique() if not df_c.empty else 0
            auto[month] = {"도출":len(kws),"반영":done,"비고":"자동 집계"}
    manual = {}
    if not df_m.empty:
        for _, r in df_m.iterrows():
            m = r.get("kpi_month","")
            if not m or m in auto: continue
            try: d,rv = int(r.get("manual_derived",0) or 0), int(r.get("manual_reflected",0) or 0)
            except: d,rv = 0,0
            note = r.get("note","").strip()
            manual[m] = {"도출":d,"반영":rv,"비고":f"수동 입력 ({note})" if note else "수동 입력"}
    all_m = {**auto, **manual}
    if not all_m:
        return pd.DataFrame(columns=["월","도출 키워드","반영 완료","반영률(%)","KPI 달성","비고"])
    rows = []
    for m in sorted(all_m.keys(), reverse=True):
        d = all_m[m]; t = d["도출"]; dv = d["반영"]
        rate = round(dv/t*100,1) if t>0 else 0.0
        st_ = "⏳ 진행 중" if m==CURRENT_MONTH else ("✅ 달성" if t>=5 and rate>=70 else "❌ 미달성")
        rows.append({"월":m,"도출 키워드":t,"반영 완료":dv,"반영률(%)":rate,"KPI 달성":st_,"비고":d.get("비고","")})
    return pd.DataFrame(rows)


# ══════════════════════════════════════════════════════════
# 추적 키워드 CRUD
# ══════════════════════════════════════════════════════════
@st.cache_data(ttl=30)
def _gh_load_tracked() -> pd.DataFrame:
    df = gh.read_csv("data/tracked_keywords.csv")
    return df if df is not None else pd.DataFrame(columns=TRACKED_COLS)

def _invalidate_tracked():
    _gh_load_tracked.clear()

def _read_tracked_all() -> pd.DataFrame:
    if gh.is_configured():
        return _gh_load_tracked()
    if not os.path.exists(TRACKED_CSV):
        ensure_data()
    try:
        df = pd.read_csv(TRACKED_CSV, dtype=str)
    except Exception:
        return pd.DataFrame(columns=TRACKED_COLS)
    for c in TRACKED_COLS:
        if c not in df.columns: df[c] = ""
    return df

def _write_tracked(df: pd.DataFrame, msg: str):
    if gh.is_configured():
        ok = gh.write_csv(df, "data/tracked_keywords.csv", msg)
        if ok: _invalidate_tracked()
    else:
        df.to_csv(TRACKED_CSV, index=False, encoding="utf-8-sig")

def load_tracked_keywords() -> list:
    df = _read_tracked_all()
    return df["keyword"].dropna().tolist() if not df.empty else []

def add_tracked_keyword(keyword: str) -> bool:
    df = _read_tracked_all()
    if keyword in df["keyword"].tolist(): return False
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    df = pd.concat([df, pd.DataFrame([[keyword,now]], columns=TRACKED_COLS)], ignore_index=True)
    _write_tracked(df, f"추적 추가: {keyword}")
    return True

def remove_tracked_keyword(keyword: str):
    df = _read_tracked_all()
    df = df[df["keyword"]!=keyword]
    _write_tracked(df, f"추적 삭제: {keyword}")

def remove_all_tracked_keywords() -> bool:
    _write_tracked(pd.DataFrame(columns=TRACKED_COLS), "전체 추적 해제")
    return True


# ══════════════════════════════════════════════════════════
# 트렌드 데이터 + 분석
# ══════════════════════════════════════════════════════════
@st.cache_data(ttl=3600*8)
def load_trends() -> pd.DataFrame:
    if not os.path.exists(TRENDS_CSV): return pd.DataFrame()
    df = pd.read_csv(TRENDS_CSV)
    df["date"] = pd.to_datetime(df["date"])
    return df

def get_last_collection_time() -> str:
    if not os.path.exists(TRENDS_CSV): return "수집 기록 없음"
    try:
        df = pd.read_csv(TRENDS_CSV, usecols=["collected_at"])
        if df.empty: return "수집 기록 없음"
        last = pd.to_datetime(df["collected_at"]).max()
        kst = last + timedelta(hours=9)
        return kst.strftime("%Y.%m.%d %H:%M")
    except Exception:
        return "—"

def to_weekly(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["주차"] = df["date"].dt.to_period("W").apply(lambda p: p.start_time)
    return (df.groupby(["주차","keyword"])["ratio"].mean().reset_index()
              .rename(columns={"keyword":"키워드","ratio":"평균 관심도"}))

def derive_trend_summary(series: pd.Series) -> tuple:
    """(레이블, 툴팁) — 각 키워드 독립 호출."""
    if len(series) < 4:
        return "분석 대기", "분석에 필요한 데이터가 충분하지 않습니다."
    recent4 = float(series.iloc[-4:].mean())
    n = len(series)
    prev4 = float(series.iloc[-8:-4].mean()) if n>=8 else float(series.iloc[:max(1,n-4)].mean())
    pct   = (recent4-prev4) / max(prev4,1) * 100
    x     = np.arange(min(4,n)); y = series.iloc[-4:].values.astype(float)
    slope = float(np.polyfit(x,y,1)[0]) if len(y)>=2 else 0.0
    cv    = float(series.iloc[-4:].std() / max(float(series.iloc[-4:].mean()),1))
    r1    = float(series.iloc[-1]) if n>=1 else 0.0
    p1    = float(series.iloc[-2]) if n>=2 else r1
    if pct>=30 and slope>1:   return "급상승",         f"최근 4주 평균이 이전 대비 {pct:.0f}% 증가했습니다."
    if pct>=10:                return "꾸준한 상승",    f"최근 4주 평균이 이전 대비 {pct:.0f}% 증가했습니다."
    if pct>=3:                 return "완만한 상승",    f"최근 4주 평균이 이전 대비 {pct:.0f}% 증가했습니다."
    if cv>=0.35:               return "등락 반복",      f"관심도 변동성이 높습니다. (변동계수 {cv:.2f})"
    if pct<=-20:               return "지속 하락",      f"최근 4주 평균이 이전 대비 {abs(pct):.0f}% 감소했습니다."
    if pct<=-8:                return "전월 대비 하락세",f"최근 4주 평균이 이전 대비 {abs(pct):.0f}% 감소했습니다."
    if (r1-p1)>5 and pct<-5:  return "반등 조짐",      "하락 추세 중 최근 1~2주 반등 신호가 보입니다."
    return "비슷하게 유지 중", f"최근 4주 관심도가 안정적입니다. (평균 {recent4:.1f})"

def compute_kw_stats(df_kw: pd.DataFrame) -> dict:
    """키워드별 독립 통계 계산. 절대로 타 키워드 변수를 공유하지 않음."""
    if df_kw.empty: return {}
    s = df_kw.sort_values("date")["ratio"].reset_index(drop=True)
    if len(s)==0: return {}
    cur   = float(s.iloc[-1])
    pw    = float(s.iloc[-2]) if len(s)>=2 else cur
    wkc   = (cur-pw)/max(pw,1)*100
    avg4  = float(s.iloc[-4:].mean()) if len(s)>=4 else float(s.mean())
    n     = len(s)
    prev4 = float(s.iloc[-8:-4].mean()) if n>=8 else float(s.iloc[:max(1,n-4)].mean()) if n>4 else avg4
    ac    = (avg4-prev4)/max(prev4,1)*100
    lbl, tip = derive_trend_summary(s)
    # 최고점 시기
    peak_idx = s.idxmax() if not s.empty else 0
    return {"current":cur,"wk_chg":wkc,"avg4":avg4,"avg_chg":ac,
            "trend_label":lbl,"trend_tip":tip,"series":s,"peak_idx":peak_idx,"n":n}

def _hex_rgba(h: str, a: float=0.13) -> str:
    h = h.lstrip("#"); r,g,b = int(h[:2],16),int(h[2:4],16),int(h[4:],16)
    return f"rgba({r},{g},{b},{a})"

def make_sparkline(series: pd.Series, color: str) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=list(range(len(series))), y=series.values,
                             mode="lines", line=dict(color=color,width=2),
                             fill="tozeroy", fillcolor=_hex_rgba(color)))
    fig.update_layout(height=52, margin=dict(l=0,r=0,t=2,b=2),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      showlegend=False, xaxis=dict(visible=False,fixedrange=True),
                      yaxis=dict(visible=False,fixedrange=True))
    return fig

def draw_unified_chart(df_period: pd.DataFrame, keywords: list, source: str, ckey: str=""):
    df_s = df_period[df_period["source"]==source]
    if df_s.empty:
        st.info(f"{'네이버' if source=='naver' else '구글'} 데이터가 없습니다.")
        return
    df_s = df_s[df_s["keyword"].isin(keywords)]
    if df_s.empty:
        st.info("선택된 키워드의 데이터가 없습니다.")
        return
    dw = to_weekly(df_s)
    COLORS = ["#2F6BFF","#10B981","#F59E0B","#EF4444","#8B5CF6"]
    kw_list = dw["키워드"].unique().tolist()
    cmap = {k: COLORS[i%len(COLORS)] for i,k in enumerate(kw_list)}
    fig = px.line(dw, x="주차", y="평균 관심도", color="키워드",
                  markers=True, line_shape="spline", height=400, color_discrete_map=cmap)
    fig.update_layout(plot_bgcolor="white", paper_bgcolor="white",
                      font=dict(family="Pretendard,Apple SD Gothic Neo,sans-serif"),
                      legend_title_text="키워드", xaxis_title="", yaxis_title="관심도 (0~100)",
                      yaxis=dict(range=[0,105],gridcolor="#f0f0f0"),
                      xaxis=dict(gridcolor="#f0f0f0"),
                      margin=dict(l=10,r=10,t=10,b=10), hovermode="x unified",
                      legend=dict(orientation="h",yanchor="bottom",y=1.02,xanchor="right",x=1))
    fig.update_traces(line_width=2.5, marker_size=6)
    st.plotly_chart(fig, use_container_width=True, key=ckey or None)


# ══════════════════════════════════════════════════════════
# 뉴스 키워드
# ══════════════════════════════════════════════════════════
@st.cache_data(ttl=3600, persist="disk")
def get_news_keywords():
    return fetch_news_keywords(top_n=20)


# ══════════════════════════════════════════════════════════
# 네이버 뉴스 기사 검색
# ══════════════════════════════════════════════════════════
_NAVER_NEWS = "https://openapi.naver.com/v1/search/news.json"
_MEDIA = {"chosun.com":"조선일보","donga.com":"동아일보","joongang.co.kr":"중앙일보",
          "mk.co.kr":"매일경제","hankyung.com":"한국경제","heraldcorp.com":"헤럴드경제",
          "yonhapnews.co.kr":"연합뉴스","yna.co.kr":"연합뉴스","zdnet.co.kr":"ZDNet",
          "etnews.com":"전자신문","dt.co.kr":"디지털타임스","boannews.com":"보안뉴스"}

def _media(url: str) -> str:
    try:
        h = urlparse(url).netloc.lower().replace("www.","").replace("m.","")
        for d,n in _MEDIA.items():
            if d in h: return n
        return h.split(".")[0].upper()
    except: return "—"

def _strip(t): return re.sub(r"<[^>]+>","",t or "").strip()

def _pubdt(s):
    try:
        dt = parsedate_to_datetime(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except: return datetime.min.replace(tzinfo=timezone.utc)

@st.cache_data(ttl=86400, show_spinner=False)
def fetch_news_articles(keywords: tuple, days: int=7) -> dict:
    from dotenv import load_dotenv; load_dotenv()
    cid = os.getenv("NAVER_CLIENT_ID","").strip() or st.secrets.get("NAVER_CLIENT_ID","")
    csc = os.getenv("NAVER_CLIENT_SECRET","").strip() or st.secrets.get("NAVER_CLIENT_SECRET","")
    if not cid or not csc: return {}
    cutoff = datetime.now(timezone.utc)-timedelta(days=days)
    result = {}
    for kw in keywords:
        arts,seen_u,seen_t = [],[],[]
        try:
            r = _req.get(_NAVER_NEWS, headers={"X-Naver-Client-Id":cid,"X-Naver-Client-Secret":csc},
                         params={"query":kw,"display":20,"sort":"date"}, timeout=6)
            if r.status_code==200:
                for it in r.json().get("items",[]):
                    dt = _pubdt(it.get("pubDate",""))
                    if dt<cutoff: continue
                    url = it.get("originallink") or it.get("link","")
                    ttl = _strip(it.get("title",""))
                    dsc = _strip(it.get("description",""))
                    if url in seen_u: continue
                    seen_u.append(url)
                    seen_t.append(ttl)
                    arts.append({"title":ttl,"media":_media(url),"date":dt.strftime("%Y-%m-%d"),
                                 "summary":dsc[:120]+("…" if len(dsc)>120 else ""),"url":url,"_dt":dt})
                    if len(arts)>=3: break
        except Exception: pass
        result[kw] = sorted(arts, key=lambda x:x["_dt"], reverse=True)
    return result


# ══════════════════════════════════════════════════════════
# 엑셀 내보내기
# ══════════════════════════════════════════════════════════
def build_excel() -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        load_monthly_kpi_summary().to_excel(w, sheet_name="월별 KPI 요약", index=False)
        d = _read_derived_all()
        if not d.empty: d.rename(columns={"keyword":"키워드","kpi_month":"월","usage_type":"활용처",
                                           "status":"상태","vendor":"벤더","idea":"아이디어",
                                           "source_url":"출처URL","discovery_source":"등록출처","added_at":"등록일"}).to_excel(w,sheet_name="도출 키워드",index=False)
        c = _read_content_all()
        if not c.empty: c.rename(columns={"keyword":"키워드","kpi_month":"월","content_type":"유형",
                                           "content_name":"콘텐츠명","url":"URL","published_at":"발행일","added_at":"등록일"}).to_excel(w,sheet_name="적용 콘텐츠",index=False)
    return buf.getvalue()


# ══════════════════════════════════════════════════════════
# 활용처 수정 다이얼로그
# ══════════════════════════════════════════════════════════
@st.dialog("콘텐츠 등록 / 활용처 수정")
def content_dialog(keyword: str, month: str, usage: str):
    st.markdown(f"**키워드:** `{keyword}`")
    USAGES = ["PR 기사","온드미디어","공통"]
    idx = USAGES.index(usage) if usage in USAGES else 0
    nu = st.selectbox("활용처 변경", USAGES, index=idx, key=f"dlg_usage_{keyword}_{month}")
    if st.button("활용처 저장", key=f"dlg_usave_{keyword}_{month}", type="secondary"):
        if update_usage_type(keyword, month, nu):
            st.success(f"'{keyword}'의 활용처를 '{nu}'로 변경했습니다.")
            st.rerun()
        else:
            st.error("저장 실패.")
    st.markdown("---")
    df_all_c = _read_content_all()
    ex = df_all_c[(df_all_c["keyword"]==keyword)&(df_all_c["kpi_month"]==month)]
    if not ex.empty:
        st.markdown("**등록된 콘텐츠**")
        for _, row in ex.iterrows():
            cn,cu,cd = row.get("content_name",""),row.get("url",""),row.get("published_at","")
            ca,cb = st.columns([8,2])
            with ca: st.markdown(f"• [{cn or cu}]({cu}) — {cd}" if cu else f"• {cn} — {cd}")
            with cb:
                if st.button("삭제", key=f"dlg_del_{keyword}_{cn}", type="secondary"):
                    delete_content_row(keyword,month,cn); st.rerun()
        st.markdown("---")
    st.markdown("**새 콘텐츠 등록**")
    ct = st.selectbox("유형 *", ["PR 기사","온드미디어"], index=1 if usage=="온드미디어" else 0, key=f"dlg_ct_{keyword}")
    cn = st.text_input("콘텐츠명 *", placeholder="예: AI보안 동향 보도자료 2026-06", key=f"dlg_cn_{keyword}")
    cu = st.text_input("URL (선택)", placeholder="https://...", key=f"dlg_cu_{keyword}")
    cd = st.date_input("발행일", value=date.today(), key=f"dlg_cd_{keyword}")
    if st.button("저장", type="primary", use_container_width=True, key=f"dlg_cs_{keyword}"):
        if not cn.strip(): st.warning("콘텐츠명을 입력해 주세요.")
        elif add_content(keyword,month,ct,cn.strip(),cu.strip(),str(cd)):
            st.success("등록 완료. 반영 완료로 처리됩니다."); st.rerun()
        else: st.warning("이미 등록된 콘텐츠명입니다.")


# ══════════════════════════════════════════════════════════
# 공유 렌더링 헬퍼
# ══════════════════════════════════════════════════════════
def _usage_html(u: str) -> str:
    m = {"PR 기사":"<span class='tag-pr'>PR 기사</span>",
         "온드미디어":"<span class='tag-owned'>온드미디어</span>",
         "공통":"<span class='tag-common'>공통</span>"}
    return m.get(u, "<span class='tag-none'>미지정</span>")

def _status_html(s: str) -> str:
    return "<span class='tag-done'>반영완료</span>" if s=="반영완료" else "<span class='tag-todo'>도출</span>"

def _trend_badge(label: str, tip: str) -> str:
    if "상승" in label or "반등" in label: bg,fg = "#ECFDF5","#065F46"
    elif "하락" in label:                  bg,fg = "#FEF2F2","#991B1B"
    elif "대기" in label:                  bg,fg = "#F1F5F9","#667085"
    else:                                  bg,fg = "#EFF6FF","#1D4ED8"
    return (f"<span title='{tip}' style='display:inline-block;background:{bg};color:{fg};"
            f"border-radius:20px;padding:2px 10px;font-size:11.5px;font-weight:700'>{label}</span>")

def _render_monthly_table(df: pd.DataFrame):
    if df.empty: st.info("집계할 데이터가 없습니다."); return
    def _row(r):
        s = r["KPI 달성"]
        sc = "color:#1d4ed8;font-weight:700" if "달성" in s and "미달성" not in s \
             else ("color:#92400e;font-weight:700" if "진행" in s else "color:#dc2626;font-weight:700")
        return (f"<tr><td style='padding:6px 12px'>{r['월']}</td>"
                f"<td style='padding:6px 12px;text-align:center'>{r['도출 키워드']}건</td>"
                f"<td style='padding:6px 12px;text-align:center'>{r['반영 완료']}건</td>"
                f"<td style='padding:6px 12px;text-align:center'>{r['반영률(%)']}%</td>"
                f"<td style='padding:6px 12px;text-align:center;{sc}'>{s}</td>"
                f"<td style='padding:6px 12px;color:#64748b;font-size:.85rem'>{r['비고']}</td></tr>")
    rows = "\n".join(_row(r) for _,r in df.iterrows())
    st.markdown(f"""<table style='width:100%;border-collapse:collapse;background:#fff;
        border-radius:8px;overflow:hidden;font-size:.92rem;border:1px solid #DCE3EA'>
  <thead style='background:#f1f5f9;font-weight:700;color:#475569'>
    <tr><th style='padding:8px 12px;text-align:left'>월</th>
        <th style='padding:8px 12px'>도출</th><th style='padding:8px 12px'>반영</th>
        <th style='padding:8px 12px'>반영률</th><th style='padding:8px 12px'>KPI</th>
        <th style='padding:8px 12px;text-align:left'>비고</th></tr></thead>
  <tbody>{rows}</tbody></table>""", unsafe_allow_html=True)

def _render_manual_form(df_monthly: pd.DataFrame, pfx: str=""):
    dm = _read_manual_all()
    if not dm.empty:
        st.markdown("**저장된 수동 입력**")
        for _,mr in dm.iterrows():
            c1,c2,c3,c4,c5 = st.columns([2,1.2,1.2,2.5,1])
            c1.text(mr["kpi_month"]); c2.text(f"도출 {mr['manual_derived']}건")
            c3.text(f"반영 {mr['manual_reflected']}건"); c4.text(mr.get("note","") or "")
            with c5:
                if st.button("삭제", key=f"{pfx}dm_{mr['kpi_month']}", type="secondary"):
                    delete_manual_month(mr["kpi_month"]); st.rerun()
        st.markdown("---")
    st.markdown("**새 달 추가**")
    a,b,c,d_ = st.columns([2,1.2,1.2,3])
    with a: mm = st.text_input("월 (YYYY-MM)", placeholder="예: 2026-05", key=f"{pfx}mm_in")
    with b: md = st.number_input("도출 건수", min_value=0, step=1, key=f"{pfx}md_in")
    with c: mr2 = st.number_input("반영 건수", min_value=0, step=1, key=f"{pfx}mr_in")
    with d_: mn = st.text_input("비고 (선택)", placeholder="예: 시스템 도입 전", key=f"{pfx}mn_in")
    if st.button("저장", type="primary", key=f"{pfx}ms_btn"):
        ms = mm.strip()
        autos = set(df_monthly[df_monthly["비고"]=="자동 집계"]["월"].tolist()) if not df_monthly.empty else set()
        if not re.match(r"^\d{4}-\d{2}$", ms): st.warning("YYYY-MM 형식으로 입력해 주세요.")
        elif ms==CURRENT_MONTH: st.warning("이번 달은 자동 집계됩니다.")
        elif ms in autos: st.warning(f"{ms}은 자동 집계 데이터가 있습니다.")
        elif int(mr2)>int(md): st.warning("반영 건수는 도출 건수보다 클 수 없습니다.")
        else:
            if add_manual_month(ms,int(md),int(mr2),mn.strip()):
                st.success(f"{ms} 저장 완료!"); st.rerun()

def _render_news_insight(pfx: str, kw_list: list):
    s_sel = f"{pfx}ins_sel"; s_art = f"{pfx}ins_art"
    if s_sel not in st.session_state: st.session_state[s_sel] = kw_list[:5]
    if s_art not in st.session_state: st.session_state[s_art] = None
    st.session_state[s_sel] = [k for k in st.session_state[s_sel] if k in kw_list]
    ca,cb,cc = st.columns([6,1.8,1.2])
    with ca:
        sel = st.multiselect("키워드 선택 (최대 5개)", kw_list,
                             default=st.session_state[s_sel], max_selections=5,
                             label_visibility="collapsed", key=f"{pfx}ins_ms")
        st.session_state[s_sel] = sel
    with cb:
        if st.button("이번 주 기사 불러오기", type="primary",
                     use_container_width=True, key=f"{pfx}ins_fetch", disabled=not sel):
            with st.spinner("네이버 뉴스 최근 7일 기사 불러오는 중…"):
                st.session_state[s_art] = fetch_news_articles(tuple(sel), days=7)
            st.rerun()
    with cc:
        if st.button("새로고침", type="secondary", use_container_width=True,
                     key=f"{pfx}ins_rf", disabled=st.session_state[s_art] is None):
            fetch_news_articles.clear(); st.session_state[s_art] = None; st.rerun()
    arts_data = st.session_state[s_art]
    if arts_data is None:
        st.info("키워드를 선택한 뒤 '이번 주 기사 불러오기'를 클릭하세요.")
    elif not arts_data:
        st.warning("API 키를 확인하거나 잠시 후 다시 시도해 주세요.")
    else:
        all_a = []
        for kw,arts in arts_data.items():
            for a in arts: all_a.append({**a,"_kw":kw})
        all_a.sort(key=lambda x:x["_dt"],reverse=True)
        for a in all_a[:10]:
            badge = (f"<span style='background:#EFF6FF;color:#1D4ED8;border-radius:4px;"
                     f"padding:1px 7px;font-size:11px;font-weight:600'>{a['_kw']}</span>")
            st.markdown(f"{badge} &nbsp; <span style='color:#64748B;font-size:12px'>{a['media']} · {a['date']}</span>",
                        unsafe_allow_html=True)
            st.markdown(f"**[{a['title']}]({a['url']})**")
            if a["summary"]:
                st.markdown(f"<span style='font-size:13px;color:#475569'>{a['summary']}</span>",
                            unsafe_allow_html=True)
            st.markdown("<hr style='margin:7px 0;border-color:#DCE3EA'>", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════
# ── 메인 실행 ──────────────────────────────────────────
# ══════════════════════════════════════════════════════════
ensure_data()

# ── 공통 KPI ──────────────────────────────────────────
df_cur       = load_derived(CURRENT_MONTH)
df_cont_cur  = load_content(CURRENT_MONTH)
KPI_D   = len(df_cur)
KPI_R   = df_cont_cur["keyword"].nunique() if not df_cont_cur.empty else 0
KPI_TD  = 5; KPI_TR = 70
RATE    = round(KPI_R/KPI_D*100) if KPI_D>0 else 0
KPI_OK  = KPI_D>=KPI_TD and RATE>=KPI_TR
NOW_STR = datetime.now().strftime("%Y.%m.%d %H:%M")
SYNC_LBL= "GitHub 동기화" if gh.is_configured() else "로컬 모드"

# ── 헤더 ──────────────────────────────────────────────
st.markdown(f"""
<div class="kd-header">
  <div class="kd-logo">
    <div class="kd-mark">K</div>
    <div class="kd-name">SCK/STK Corp · 커뮤니케이션팀</div>
  </div>
  <div class="kd-meta">
    <span>기준월 <strong>{CURRENT_MONTH}</strong></span>
    <span>{NOW_STR} 기준</span>
    <span>{SYNC_LBL}</span>
    <span class="kd-live">라이브</span>
  </div>
</div>
<div class="kd-hero">
  <div class="kd-hero-title">SCK 커뮤니케이션팀<br>키워드 트렌드 대시보드</div>
  <div class="kd-hero-sub">트렌드 키워드의 발굴부터 PR·온드미디어 반영까지 한 화면에서 관리합니다.</div>
</div>""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════
# 4개 탭
# ══════════════════════════════════════════════════════════
tab1, tab2, tab3, tab4 = st.tabs([
    "📊 전체 현황",
    "🔍 급상승 키워드 발굴",
    "📈 트렌드 키워드 탐색",
    "📋 활용처 관리",
])


# ════════════════════════════════════════════════════════
# TAB 1 · 전체 현황
# ════════════════════════════════════════════════════════
with tab1:
    st.markdown("""<div class="sh-sub"><div class="t">이번 달 KPI 현황</div>
<div class="s">도출 목표 5건 · 반영률 목표 70% · 적용 콘텐츠 등록 기준</div></div>""", unsafe_allow_html=True)

    c1,c2,c3,c4 = st.columns(4, gap="medium")
    with c1:
        p1 = min(int(KPI_D/KPI_TD*100),100)
        st.markdown(f"<div class='kpi-card'><div class='kpi-lbl'>이번 달 도출 키워드</div>"
                    f"<div class='kpi-val'>{KPI_D}<span class='kpi-unit'>건</span></div>"
                    f"<div class='kpi-hint'>목표 {KPI_TD}건 · 달성률 {p1}%</div></div>", unsafe_allow_html=True)
        st.progress(min(KPI_D/KPI_TD,1.0))
    with c2:
        st.markdown(f"<div class='kpi-card'><div class='kpi-lbl'>반영 완료</div>"
                    f"<div class='kpi-val'>{KPI_R}<span class='kpi-unit'>건</span></div>"
                    f"<div class='kpi-hint'>도출 {KPI_D}건 중</div></div>", unsafe_allow_html=True)
        st.progress(min(KPI_R/max(KPI_D,1),1.0))
    with c3:
        p2 = min(int(RATE/KPI_TR*100),100)
        st.markdown(f"<div class='kpi-card'><div class='kpi-lbl'>전체 반영률</div>"
                    f"<div class='kpi-val'>{RATE}<span class='kpi-unit'>%</span></div>"
                    f"<div class='kpi-hint'>목표 {KPI_TR}% · 달성률 {p2}%</div></div>", unsafe_allow_html=True)
        st.progress(min(RATE/KPI_TR,1.0))
    with c4:
        bc = "bdg-pass" if KPI_OK else "bdg-fail"
        bt = "달성" if KPI_OK else "진행 중"
        hint = "도출·반영 두 목표 모두 달성" if KPI_OK else f"도출 {max(KPI_TD-KPI_D,0)}건 · 반영률 {max(KPI_TR-RATE,0)}%p 부족"
        st.markdown(f"<div class='kpi-card'><div class='kpi-lbl'>이번 달 KPI</div>"
                    f"<span class='{bc}'>{bt}</span>"
                    f"<div class='kpi-hint' style='margin-top:10px'>{hint}</div></div>", unsafe_allow_html=True)
        st.progress(1.0 if KPI_OK else max(RATE/100,0.03))

    st.markdown("<div style='margin-top:1.8rem'></div>", unsafe_allow_html=True)

    # 3열 요약
    rc1,rc2,rc3 = st.columns(3, gap="medium")
    with rc1:
        st.markdown("""<div class="sh-sub"><div class="t">최근 등록 키워드</div></div>""", unsafe_allow_html=True)
        da = _read_derived_all()
        if not da.empty:
            for _,r in da.sort_values("added_at",ascending=False).head(5).iterrows():
                lbl = r.get("usage_type","") or "미지정"
                st.markdown(f"• **{r['keyword']}** <span style='color:#667085;font-size:11.5px'>{r.get('kpi_month','')} · {lbl}</span>",
                            unsafe_allow_html=True)
        else: st.caption("등록된 키워드가 없습니다.")
    with rc2:
        st.markdown("""<div class="sh-sub"><div class="t">활용처 미지정</div></div>""", unsafe_allow_html=True)
        da = _read_derived_all()
        unset = da[da["usage_type"].str.strip()==""] if not da.empty else pd.DataFrame()
        st.markdown(f"<div style='font-size:2.2rem;font-weight:800;color:#101828'>{len(unset)}<span style='font-size:.9rem;font-weight:400;color:#667085'>건</span></div>",
                    unsafe_allow_html=True)
        for _,r in unset.head(5).iterrows():
            st.caption(f"• {r['keyword']} ({r.get('kpi_month','')})")
    with rc3:
        st.markdown("""<div class="sh-sub"><div class="t">추적 데이터 대기</div></div>""", unsafe_allow_html=True)
        t_kws = load_tracked_keywords()
        df_tr = load_trends()
        if not df_tr.empty and t_kws:
            have = df_tr["keyword"].unique().tolist()
            pending = [k for k in t_kws if k not in have]
        else: pending = t_kws
        st.markdown(f"<div style='font-size:2.2rem;font-weight:800;color:#101828'>{len(pending)}<span style='font-size:.9rem;font-weight:400;color:#667085'>건</span></div>",
                    unsafe_allow_html=True)
        for k in pending[:5]: st.caption(f"• {k} — 수집 대기")

    st.markdown("<div style='margin-top:2rem'></div>", unsafe_allow_html=True)
    st.markdown("""<div class="sh-main"><div class="t">이번 주 키워드 인사이트</div>
<div class="s">최근 7일 국내 기사 · 네이버 뉴스 검색 API · 참고 자료용 — 반영률 집계 미포함</div></div>""",
                unsafe_allow_html=True)
    _render_news_insight("t1_", df_cur["키워드"].tolist() if not df_cur.empty else [])

    with st.expander("📅 월별 KPI 누적 현황 상세 보기", expanded=False):
        dfm = load_monthly_kpi_summary()
        buf_m = io.BytesIO()
        with pd.ExcelWriter(buf_m,engine="openpyxl") as w: dfm.to_excel(w,index=False,sheet_name="월별 KPI")
        cc1,_ = st.columns([2,5])
        with cc1:
            st.download_button("⬇ 월별 KPI 엑셀", buf_m.getvalue(),
                               file_name=f"monthly_kpi_{CURRENT_MONTH}.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                               key="t1_dl_m")
        _render_monthly_table(dfm)
        st.markdown("<div style='margin-top:1rem'></div>", unsafe_allow_html=True)
        st.caption("📝 과거 달 수동 입력")
        _render_manual_form(dfm, pfx="t1_")


# ════════════════════════════════════════════════════════
# TAB 2 · 급상승 키워드 발굴
# ════════════════════════════════════════════════════════
with tab2:

    # ① 빠른 등록 — 탭 최상단
    st.markdown("""<div class="sh-main"><div class="t">도출 키워드 빠른 등록</div>
<div class="s">이번 달 발굴한 키워드를 바로 등록합니다. 등록 즉시 모든 화면에 반영됩니다.</div></div>""",
                unsafe_allow_html=True)

    with st.form("t2_quick_reg", clear_on_submit=True):
        qa,qb,qc = st.columns([4,3,1.4])
        with qa: q_kw = st.text_input("키워드 *", placeholder="예: 제로트러스트")
        with qb: q_us = st.selectbox("활용처 *", ["PR 기사","온드미디어","공통"])
        with qc:
            st.markdown("<div style='height:29px'></div>", unsafe_allow_html=True)
            q_sub = st.form_submit_button("＋ 키워드 등록", use_container_width=True, type="primary")
        with st.expander("추가 정보 입력 (선택)"):
            e1,e2 = st.columns(2)
            with e1: q_ve = st.text_input("관련 벤더", placeholder="예: Palo Alto", key="t2_ve")
            with e2: q_id = st.text_input("아이디어·메모", placeholder="예: Q3 보도자료", key="t2_id")
            q_su = st.text_input("출처 URL", placeholder="https://...", key="t2_su")

    if q_sub:
        kw_t = q_kw.strip() if q_kw else ""
        if not kw_t:
            st.warning("키워드를 입력해 주세요.")
        else:
            ok = add_keyword(kw_t, CURRENT_MONTH, usage_type=q_us,
                             vendor=q_ve.strip() if q_ve else "",
                             idea=q_id.strip() if q_id else "",
                             source_url=q_su.strip() if q_su else "",
                             discovery_source="직접 입력")
            if ok:
                # 모든 관련 캐시 명시적 무효화
                _invalidate_derived()
                st.success(f"✅ '{kw_t}' 등록 완료 — 활용처: {q_us}")
                st.rerun()
            else:
                st.warning("이미 등록된 키워드입니다.")

    st.markdown("<div style='margin-top:2rem'></div>", unsafe_allow_html=True)

    # ② 마지막 업데이트 + 새로고침
    last_upd = get_last_collection_time()
    col_lu, col_rf = st.columns([8,2])
    with col_lu:
        st.markdown(f"""<div class="sh-main">
  <div class="t">급상승 키워드 발굴 <span style='font-weight:400;font-size:.85rem;color:#667085'>
    &nbsp;마지막 업데이트 {last_upd}</span></div>
  <div class="s">구글 뉴스 RSS 기사 빈도 기반 · 1시간마다 자동 갱신</div></div>""", unsafe_allow_html=True)
    with col_rf:
        st.markdown("<div style='margin-top:6px'></div>", unsafe_allow_html=True)
        if st.button("🔄 데이터 새로고침", key="t2_disc_rf", use_container_width=True):
            get_news_keywords.clear(); load_trends.clear(); st.rerun()

    # ③ 급상승 키워드 목록
    with st.spinner("IT 뉴스 키워드 분석 중…"):
        news_kws_raw, sources_ok = get_news_keywords()

    if news_kws_raw:
        df_cur_t2     = load_derived(CURRENT_MONTH)
        tracked_set2  = set(load_tracked_keywords())
        derived_set2  = set(df_cur_t2["키워드"].tolist()) if not df_cur_t2.empty else set()
        st.caption(f"📰 {sources_ok}  |  1시간마다 갱신")

        top8 = news_kws_raw[:8]
        rest = news_kws_raw[8:]

        # 상위 8개 카드 (4열 × 2행)
        for rs in range(0,len(top8),4):
            batch = top8[rs:rs+4]
            cols2 = st.columns(4, gap="small")
            for col, (w,cnt) in zip(cols2, batch):
                with col:
                    is_t = w in tracked_set2; is_d = w in derived_set2
                    with st.container(border=True):
                        st.markdown(f"<div style='font-size:.98rem;font-weight:700;color:#101828;margin-bottom:4px'>{w}</div>"
                                    f"<div style='font-size:11.5px;color:#667085;margin-bottom:10px'>언급 {cnt}회</div>",
                                    unsafe_allow_html=True)
                        ba,bb = st.columns(2)
                        with ba:
                            if is_t: st.markdown("<span style='color:#059669;font-size:12px;font-weight:600'>📌 추적 중</span>", unsafe_allow_html=True)
                            elif st.button("📌 추적", key=f"t2_tr_{w}", use_container_width=True, type="secondary"):
                                add_tracked_keyword(w)
                                with st.spinner("수집 중…"): collect_single_keyword(w); load_trends.clear()
                                st.rerun()
                        with bb:
                            if is_d: st.markdown("<span style='color:#059669;font-size:12px;font-weight:600'>✅ 도출됨</span>", unsafe_allow_html=True)
                            elif st.button("＋ 도출", key=f"t2_dr_{w}", use_container_width=True, type="primary"):
                                if add_keyword(w, CURRENT_MONTH, discovery_source="뉴스 자동탐지"):
                                    _invalidate_derived(); st.rerun()
                                else: st.info("이미 등록됨")

        # 나머지 컴팩트 표
        if rest:
            st.markdown("<div style='margin-top:1.5rem'></div>", unsafe_allow_html=True)
            h0,h1,h2,h3 = st.columns([0.5,2.5,1.2,3.5])
            for c_,l_ in zip([h0,h1,h2,h3],["#","키워드","언급","액션"]):
                c_.markdown(f"<span class='th'>{l_}</span>", unsafe_allow_html=True)
            st.markdown("<hr style='margin:4px 0'>", unsafe_allow_html=True)
            for i_,(w,cnt) in enumerate(rest,start=9):
                is_t = w in tracked_set2; is_d = w in derived_set2
                r0,r1,r2,r3 = st.columns([0.5,2.5,1.2,3.5])
                with r0: st.markdown(f"<span class='td' style='color:#667085'>{i_}</span>", unsafe_allow_html=True)
                with r1: st.markdown(f"<span class='td' style='font-weight:600'>{w}</span>", unsafe_allow_html=True)
                with r2: st.markdown(f"<span class='td'>{cnt}회</span>", unsafe_allow_html=True)
                with r3:
                    ba,bb,_ = st.columns([1.3,1.1,1.5])
                    with ba:
                        if not is_t:
                            if st.button("📌 추적", key=f"t2_rtr_{w}", use_container_width=True, type="secondary"):
                                add_tracked_keyword(w)
                                with st.spinner("수집 중…"): collect_single_keyword(w); load_trends.clear()
                                st.rerun()
                        else: st.caption("추적 중")
                    with bb:
                        if not is_d:
                            if st.button("＋ 도출", key=f"t2_rdr_{w}", use_container_width=True, type="primary"):
                                if add_keyword(w,CURRENT_MONTH,discovery_source="뉴스 자동탐지"):
                                    _invalidate_derived(); st.rerun()
                        else: st.caption("도출됨")
                st.markdown("<hr style='margin:2px 0;border-color:#F7F9FC'>", unsafe_allow_html=True)
    else:
        st.info("뉴스 데이터를 불러오지 못했습니다.")

    st.markdown("<div style='margin-top:2rem'></div>", unsafe_allow_html=True)

    # ④ 이번 주 키워드 인사이트
    st.markdown("""<div class="sh-main"><div class="t">이번 주 키워드 인사이트</div>
<div class="s">최근 7일 국내 기사 · 네이버 뉴스 검색 API</div></div>""", unsafe_allow_html=True)
    df_cur_t2_news = load_derived(CURRENT_MONTH)
    _render_news_insight("t2_", df_cur_t2_news["키워드"].tolist() if not df_cur_t2_news.empty else [])


# ════════════════════════════════════════════════════════
# TAB 3 · 트렌드 키워드 탐색
# ════════════════════════════════════════════════════════
with tab3:
    tracked_kws = load_tracked_keywords()

    st.markdown("""<div class="sh-main"><div class="t">추적 키워드 관리</div>
<div class="s">칩 클릭 → 그래프 숨김/복원 &nbsp;·&nbsp; ✕ → 추적 목록에서 삭제 &nbsp;·&nbsp; 아래에서 새 키워드 추가</div></div>""",
                unsafe_allow_html=True)

    # 전체 선택/숨기기/전체 추적 해제 버튼 — 눈에 잘 띄게 상단 배치
    if "hidden_kws" not in st.session_state: st.session_state["hidden_kws"] = set()
    st.session_state["hidden_kws"] &= set(tracked_kws)
    if "t3_conf_del" not in st.session_state: st.session_state["t3_conf_del"] = False

    if tracked_kws:
        btn1,btn2,btn3,_ = st.columns([1.5,1.5,1.8,5.5])
        with btn1:
            if st.button("전체 표시", key="t3_show_all", type="secondary", use_container_width=True):
                st.session_state["hidden_kws"] = set(); st.rerun()
        with btn2:
            if st.button("전체 숨기기", key="t3_hide_all", type="secondary", use_container_width=True):
                st.session_state["hidden_kws"] = set(tracked_kws); st.rerun()
        with btn3:
            if st.button(f"⚠ 전체 추적 해제 ({len(tracked_kws)}개)", key="t3_del_all_btn",
                         type="secondary", use_container_width=True):
                st.session_state["t3_conf_del"] = True

    if st.session_state.get("t3_conf_del"):
        st.markdown(f"<div class='warn-box'>추적 중인 키워드 <strong>{len(tracked_kws)}개</strong>를 모두 해제하시겠습니까?</div>",
                    unsafe_allow_html=True)
        ca,cb = st.columns([2,2])
        with ca:
            if st.button("취소", key="t3_conf_can", type="secondary"):
                st.session_state["t3_conf_del"] = False; st.rerun()
        with cb:
            if st.button("전체 추적 해제 확인", key="t3_conf_ok", type="primary"):
                remove_all_tracked_keywords()
                st.session_state["hidden_kws"] = set()
                st.session_state["t3_conf_del"] = False
                _invalidate_tracked(); st.rerun()

    # 키워드 칩
    if not tracked_kws:
        st.info("추적 중인 키워드가 없습니다. 아래에서 추가하세요.")
    else:
        CHIP_ROW = 5
        for rs in range(0,len(tracked_kws),CHIP_ROW):
            batch = tracked_kws[rs:rs+CHIP_ROW]
            widths = []
            for _ in batch: widths += [3,0.45]
            widths.append(max(0.1,16-sum(widths)))
            chip_cols = st.columns(widths)
            for j,kw in enumerate(batch):
                hid = kw in st.session_state["hidden_kws"]
                with chip_cols[j*2]:
                    if st.button(f"{'○' if hid else '●'} {kw}", key=f"chip_{kw}", use_container_width=True):
                        (st.session_state["hidden_kws"].discard if hid else st.session_state["hidden_kws"].add)(kw)
                        st.rerun()
                with chip_cols[j*2+1]:
                    if st.button("✕", key=f"chip_x_{kw}", type="secondary"):
                        remove_tracked_keyword(kw); st.session_state["hidden_kws"].discard(kw); st.rerun()

    # 새 키워드 추가
    st.markdown("")
    na,nb = st.columns([5,1])
    with na:
        new_tk = st.text_input("새 추적 키워드", placeholder="예: 제로트러스트",
                               label_visibility="collapsed", key="t3_new_tk")
    with nb:
        if st.button("＋ 추가", type="primary", use_container_width=True, key="t3_add_btn"):
            kt = new_tk.strip()
            if not kt: st.warning("키워드를 입력해 주세요.")
            elif not add_tracked_keyword(kt): st.info(f"'{kt}'는 이미 추적 중입니다.")
            else:
                with st.spinner(f"'{kt}' 데이터 수집 중…"):
                    nok,gok = collect_single_keyword(kt); load_trends.clear()
                _invalidate_tracked()
                st.success(f"'{kt}' 추가 — 네이버 {'✅' if nok else '⚠️'} / 구글 {'✅' if gok else '⚠️'}")
                st.rerun()

    st.markdown("<div style='margin-top:2rem'></div>", unsafe_allow_html=True)

    # ── 통합 비교 그래프 ──────────────────────────────
    st.markdown("""<div class="sh-main"><div class="t">통합 검색 추이 비교</div>
<div class="s">비교할 키워드를 선택하세요. 최대 5개</div></div>""", unsafe_allow_html=True)

    if "period_days" not in st.session_state: st.session_state["period_days"] = 30
    if "t3_sel_kws"  not in st.session_state: st.session_state["t3_sel_kws"]  = tracked_kws[:3]
    # 삭제된 키워드 정리
    st.session_state["t3_sel_kws"] = [k for k in st.session_state["t3_sel_kws"] if k in tracked_kws]

    ca_kw, ca_pr = st.columns([7,3])
    with ca_kw:
        sel_kws = st.multiselect(
            "비교 키워드 (최대 5개)",
            options=tracked_kws,
            default=st.session_state["t3_sel_kws"][:5],
            max_selections=5,
            placeholder="키워드를 선택하세요",
            key="t3_ms_kw")
        st.session_state["t3_sel_kws"] = sel_kws
    with ca_pr:
        PERIODS = {"7일":7,"30일":30,"90일":90}
        pl = st.radio("기간", list(PERIODS.keys()), horizontal=True,
                      index=list(PERIODS.values()).index(st.session_state["period_days"]),
                      key="t3_period_r")
        st.session_state["period_days"] = PERIODS[pl]

    period_days = st.session_state["period_days"]
    cutoff = pd.Timestamp.today().normalize() - pd.Timedelta(days=period_days)
    df_tr = load_trends()

    visible_kws = [k for k in sel_kws if k not in st.session_state["hidden_kws"]]

    if not sel_kws:
        st.info("위에서 비교할 키워드를 선택해 주세요.")
    elif df_tr.empty:
        st.warning("trends.csv에 데이터가 없습니다. `python collector.py`를 실행해 주세요.")
    else:
        df_period = df_tr[(df_tr["keyword"].isin(sel_kws)) & (df_tr["date"]>=cutoff)]
        src_choice = st.radio("데이터 소스", ["네이버 데이터랩","구글 트렌드"],
                              horizontal=True, key="t3_src_r")
        src_key = "naver" if "네이버" in src_choice else "google"
        st.caption("국내 검색 기준 · 0~100 상대 지수" if src_key=="naver"
                   else "구글 트렌드 · 0~100 상대 지수")

        if visible_kws:
            draw_unified_chart(df_period, visible_kws, src_key,
                               ckey=f"t3_chart_{src_key}_{period_days}")
        else:
            st.info("모든 키워드가 숨김 상태입니다. 상단 칩을 클릭해 복원하세요.")

        # 데이터 없는 키워드 안내
        no_data = [k for k in sel_kws
                   if df_period[(df_period["keyword"]==k)&(df_period["source"]==src_key)].empty]
        if no_data:
            nd_str = " · ".join(f"{k} · 비교 데이터 부족" for k in no_data)
            st.markdown(f"<div class='notice-box'>⚠ {nd_str}</div>", unsafe_allow_html=True)

        st.caption("⚠ 네이버(일별)와 구글(주별)은 집계 기준이 달라 직접 비교하지 마세요.")

        with st.expander("원본 데이터 보기"):
            df_s_ = df_period[df_period["source"]==src_key].copy()
            if not df_s_.empty:
                df_s_["date"] = df_s_["date"].dt.strftime("%Y-%m-%d")
                st.dataframe(df_s_[["keyword","date","ratio"]].rename(
                    columns={"keyword":"키워드","date":"날짜","ratio":"관심도"})
                    .sort_values("날짜",ascending=False).head(60),
                    use_container_width=True, hide_index=True)
            else: st.info("해당 소스 데이터가 없습니다.")

        st.markdown("<div style='margin-top:2rem'></div>", unsafe_allow_html=True)

        # ── 키워드별 추이 요약 카드 — 완전 독립 처리 ────────
        st.markdown(f"""<div class="sh-sub"><div class="t">키워드별 추이 요약</div>
<div class="s">최근 {period_days}일 · 각 키워드 독립 처리 — 데이터 부족이 다른 키워드에 영향을 주지 않습니다</div></div>""",
                    unsafe_allow_html=True)

        NCOLS = min(3, len(sel_kws)) if sel_kws else 1
        card_cols = st.columns(NCOLS, gap="medium")

        for idx_k, kw in enumerate(sel_kws):
            # ★ 각 키워드마다 완전히 독립된 로컬 변수 사용
            _df_n = df_period[(df_period["keyword"]==kw)&(df_period["source"]=="naver")].copy()
            _df_g = df_period[(df_period["keyword"]==kw)&(df_period["source"]=="google")].copy()
            _st_n = compute_kw_stats(_df_n)  # 독립 호출
            _st_g = compute_kw_stats(_df_g)  # 독립 호출

            with card_cols[idx_k % NCOLS]:
                with st.container(border=True):
                    st.markdown(f"<div class='tc-kw'>{kw}</div>", unsafe_allow_html=True)

                    if not _st_n and not _st_g:
                        st.caption("데이터 없음 — 수집 대기 중")
                        if kw not in load_tracked_keywords():
                            if st.button("추적 추가", key=f"t3_add_from_card_{kw}_{idx_k}", type="secondary"):
                                add_tracked_keyword(kw); st.rerun()
                        continue

                    _st  = _st_n if _st_n else _st_g
                    _src = "네이버" if _st_n else "구글"

                    wcs = f"+{_st['wk_chg']:.1f}%" if _st['wk_chg']>=0 else f"{_st['wk_chg']:.1f}%"
                    wcc = "#059669" if _st['wk_chg']>=0 else "#DC2626"
                    acs = f"+{_st['avg_chg']:.1f}%" if _st['avg_chg']>=0 else f"{_st['avg_chg']:.1f}%"
                    acc = "#059669" if _st['avg_chg']>=0 else "#DC2626"

                    # 최고점 시기
                    if _st_n and len(_st_n["series"])>0:
                        _ser = _st_n["series"]
                        peak_wk_idx = _ser.idxmax()
                        try:
                            peak_dt = _df_n.sort_values("date")["date"].iloc[peak_wk_idx]
                            peak_str = pd.Timestamp(peak_dt).strftime("%Y.%m.%d")
                        except: peak_str = "—"
                    else: peak_str = "—"

                    st.markdown(f"""
<div class='tc-row'>현재 관심도 <strong>{_st['current']:.0f}</strong> <span style='font-size:11px;color:#667085'>({_src})</span></div>
<div class='tc-row'>전주 대비 <strong style='color:{wcc}'>{wcs}</strong></div>
<div class='tc-row'>최근 4주 평균 <strong>{_st['avg4']:.1f}</strong></div>
<div class='tc-row'>이전 4주 대비 <strong style='color:{acc}'>{acs}</strong></div>
<div class='tc-row'>최고점 <strong>{peak_str}</strong></div>
<div class='tc-row'>검색량 추세 &nbsp; {_trend_badge(_st['trend_label'], _st['trend_tip'])}</div>
""", unsafe_allow_html=True)

                    # 스파크라인 — 네이버 우선
                    _plot_ser = _st_n["series"] if _st_n and len(_st_n["series"])>=3 \
                                else (_st_g["series"] if _st_g and len(_st_g["series"])>=3 else None)
                    if _plot_ser is not None:
                        st.plotly_chart(make_sparkline(_plot_ser,"#2F6BFF"),
                                        use_container_width=True,
                                        config={"displayModeBar":False},
                                        key=f"t3_sp_{kw}_{period_days}_{idx_k}_{src_key}")


# ════════════════════════════════════════════════════════
# TAB 4 · 활용처 관리
# ════════════════════════════════════════════════════════
with tab4:
    df_cur4  = load_derived(CURRENT_MONTH)
    df_con4  = load_content(CURRENT_MONTH)

    st.markdown("""<div class="sh-main"><div class="t">활용처 · 반영 현황</div>
<div class="s">인라인으로 활용처를 수정하거나 '수정' 버튼으로 콘텐츠를 등록합니다. 저장 후 앱 재접속에도 유지됩니다.</div></div>""",
                unsafe_allow_html=True)

    cf1,cf2 = st.columns([7,2])
    with cf1:
        flt = st.radio("필터", ["전체","PR 기사","온드미디어","미지정","미반영"],
                       horizontal=True, label_visibility="collapsed", key="t4_flt")
    with cf2:
        st.download_button("⬇ 엑셀 다운로드", data=build_excel(),
                           file_name=f"keyword_kpi_{CURRENT_MONTH}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           use_container_width=True, key="t4_dl")

    if df_cur4.empty:
        st.info("이번 달 등록된 도출 키워드가 없습니다. '급상승 키워드 발굴' 탭에서 추가해 주세요.")
    else:
        if flt=="PR 기사":       df4 = df_cur4[df_cur4["활용처"].isin(["PR 기사","공통"])].copy()
        elif flt=="온드미디어":    df4 = df_cur4[df_cur4["활용처"].isin(["온드미디어","공통"])].copy()
        elif flt=="미지정":       df4 = df_cur4[df_cur4["활용처"].str.strip()==""].copy()
        elif flt=="미반영":       df4 = df_cur4[df_cur4["상태"]!="반영완료"].copy()
        else:                     df4 = df_cur4.copy()

        # 콘텐츠 인덱스
        if not df_con4.empty:
            lc = (df_con4.sort_values("added_at",ascending=False)
                  .drop_duplicates(subset="keyword",keep="first").set_index("keyword"))
            cc_map = df_con4.groupby("keyword").size().to_dict()
        else: lc = pd.DataFrame(); cc_map = {}

        USAGES = ["PR 기사","온드미디어","공통"]

        # 헤더
        h0,h1,h2,h3,h4,h5,h6,h7 = st.columns([2.2,1.6,1.3,1.6,2.8,1.3,1.5,1.1])
        for c_,l_ in zip([h0,h1,h2,h3,h4,h5,h6,h7],
                         ["키워드","활용처 선택","저장","상태","콘텐츠명","링크","반영일","편집"]):
            c_.markdown(f"<span class='th'>{l_}</span>", unsafe_allow_html=True)
        st.markdown("<hr style='margin:5px 0 3px'>", unsafe_allow_html=True)

        for ri, row in df4.iterrows():
            kw    = row["키워드"]
            usage = row["활용처"] or ""
            stat  = row["상태"] or "도출"
            has_c = not lc.empty and kw in lc.index
            cn = lc.loc[kw,"content_name"] if has_c else ""
            cu = lc.loc[kw,"url"]          if has_c else ""
            cd = lc.loc[kw,"published_at"] if has_c else ""
            ctot = cc_map.get(kw,0)

            r0,r1,r2,r3,r4,r5,r6,r7 = st.columns([2.2,1.6,1.3,1.6,2.8,1.3,1.5,1.1])
            with r0:
                st.markdown(f"<span class='td' style='font-weight:600'>{kw}</span>",
                            unsafe_allow_html=True)
            with r1:
                # 인라인 selectbox — 활용처 직접 선택
                cur_idx = USAGES.index(usage) if usage in USAGES else 0
                nu = st.selectbox("_", USAGES, index=cur_idx,
                                  label_visibility="collapsed",
                                  key=f"t4_sel_{kw}_{ri}")
            with r2:
                # 저장 버튼 — key에 ri 포함으로 고유성 보장
                if st.button("저장", key=f"t4_sv_{kw}_{ri}", type="primary",
                             use_container_width=True):
                    if update_usage_type(kw, CURRENT_MONTH, nu):
                        st.toast(f"'{kw}' → '{nu}' 저장됨")
                        _invalidate_derived()
                        st.rerun()
                    else:
                        st.error("저장 실패")
            with r3:
                st.markdown(f"<span class='td'>{_status_html(stat)}</span>",
                            unsafe_allow_html=True)
            with r4:
                if cn:
                    disp = cn+(f" 외 {ctot-1}건" if ctot>1 else "")
                    st.markdown(f"<span class='td'>{disp}</span>", unsafe_allow_html=True)
                else:
                    st.markdown("<span class='td' style='color:#94A3B8'>—</span>",
                                unsafe_allow_html=True)
            with r5:
                if cu: st.markdown(f"[보기]({cu})")
                else:  st.markdown("<span style='color:#94A3B8;font-size:13px'>—</span>",
                                   unsafe_allow_html=True)
            with r6:
                st.markdown(f"<span class='td' style='color:#64748B'>{cd or '—'}</span>",
                            unsafe_allow_html=True)
            with r7:
                if st.button("편집", key=f"t4_ed_{kw}_{ri}", use_container_width=True):
                    content_dialog(kw, CURRENT_MONTH, usage)
            st.markdown("<hr style='margin:3px 0;border-color:#F7F9FC'>", unsafe_allow_html=True)

    with st.expander("키워드 삭제 (주의)"):
        st.caption("잘못 등록된 키워드를 삭제합니다. 연결된 콘텐츠도 함께 삭제됩니다.")
        if not df_cur4.empty:
            dk = st.selectbox("삭제할 키워드", df_cur4["키워드"].tolist(),
                              label_visibility="collapsed", key="t4_dk_sel")
            if st.button("선택한 키워드 삭제", type="secondary", key="t4_dk_btn"):
                delete_keyword(dk, CURRENT_MONTH)
                df_c = _read_content_all()
                df_c = df_c[~((df_c["keyword"]==dk)&(df_c["kpi_month"]==CURRENT_MONTH))]
                _write_content(df_c, f"콘텐츠 일괄 삭제: {dk}")
                _invalidate_derived(); _invalidate_content()
                st.success(f"'{dk}' 삭제됐습니다."); st.rerun()
        else: st.info("삭제할 키워드가 없습니다.")

    with st.expander("📅 월별 KPI 누적 현황"):
        dfm4 = load_monthly_kpi_summary()
        buf4 = io.BytesIO()
        with pd.ExcelWriter(buf4,engine="openpyxl") as w: dfm4.to_excel(w,index=False,sheet_name="월별 KPI")
        cc_dl,_ = st.columns([2,5])
        with cc_dl:
            st.download_button("⬇ 월별 KPI 엑셀", buf4.getvalue(),
                               file_name=f"monthly_kpi_{CURRENT_MONTH}.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                               key="t4_dl_m")
        _render_monthly_table(dfm4)
        st.markdown("<div style='margin-top:1rem'></div>", unsafe_allow_html=True)
        st.caption("📝 과거 달 수동 입력")
        _render_manual_form(dfm4, pfx="t4_")


# ── 푸터 (빌드 버전 포함) ───────────────────────────────
_tcnt = len(pd.read_csv(TRENDS_CSV)) if os.path.exists(TRENDS_CSV) else 0
st.markdown(f"""
<div style="margin-top:3rem;padding-top:1.5rem;border-top:1px solid #DCE3EA;
            display:flex;justify-content:space-between;align-items:center;
            font-size:11px;color:#94A3B8;flex-wrap:wrap;gap:4px">
  <span>키워드 인텔리전스 · SCK/STK Corp · {CURRENT_MONTH}</span>
  <span style='font-weight:700;color:#2F6BFF'>BUILD {BUILD_VERSION}</span>
  <span>트렌드 {_tcnt:,}건 · 네이버 데이터랩 · 구글 트렌드</span>
</div>""", unsafe_allow_html=True)
