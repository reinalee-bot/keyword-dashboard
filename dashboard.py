"""
SCK 커뮤니케이션팀 키워드 트렌드 대시보드 — 5탭 구조
BUILD: 2026-06-30-KEYWORD-V6
"""
import hashlib, io, os, re
from datetime import datetime, date, timedelta, timezone

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import streamlit as st

import github_storage as gh
import news_fetcher as nf
from collector import collect_single_keyword
import monitoring as mon
import monitoring_review_store as mrs
from monitoring_tab_helpers import (
    today_kst, monitoring_config_version,
    apply_category_filter, count_by_category, make_widget_key,
    apply_urgency_filter, sort_monitoring_articles,
    apply_review_filter, count_review_summary,
)

# ── 상수 ──────────────────────────────────────────────────
BUILD_VERSION = "2026-07-06-KEYWORD-V7"

BASE_DIR    = os.path.dirname(__file__)
DATA_DIR    = os.path.join(BASE_DIR, "data")
TRENDS_CSV  = os.path.join(DATA_DIR, "trends.csv")
DERIVED_CSV = os.path.join(DATA_DIR, "derived_keywords.csv")
CONTENT_CSV = os.path.join(DATA_DIR, "applied_content.csv")
TRACKED_CSV = os.path.join(DATA_DIR, "tracked_keywords.csv")
MANUAL_CSV   = os.path.join(DATA_DIR, "monthly_manual.csv")
NEWS_UTIL_CSV = os.path.join(DATA_DIR, "news_utilization.csv")

NEWS_UTIL_COLS = ["등록일","기사 제목","기사 URL","매체명","발행일","키워드","활용처","메모","상태"]
NEWS_UTIL_USAGES = ["PR 파이프라인 소재","온드미디어 소재","현업 확인 필요",
                    "데일리 브리핑 포함","참고 기사","보류"]

DERIVED_COLS = ["keyword","kpi_month","usage_type","status",
                "vendor","idea","source_url","discovery_source","added_at"]
CONTENT_COLS = ["keyword","kpi_month","content_type",
                "content_name","url","published_at","added_at"]
TRENDS_COLS  = ["keyword","date","ratio","source","collected_at"]
TRACKED_COLS = ["keyword","added_at"]
MANUAL_COLS  = ["kpi_month","manual_derived","manual_reflected","note","added_at"]
CURRENT_MONTH = datetime.today().strftime("%Y-%m")
USAGES = ["PR 기사","온드미디어","공통"]

# ── 페이지 설정 ───────────────────────────────────────────
st.set_page_config(page_title="뉴스 & 트렌드 모니터링 | SCK·STK",
                   page_icon="📊", layout="wide")

# ── CSS ──────────────────────────────────────────────────────
# 핵심 원칙:
#   html / body / button / input / select / span 에 font-family 강제 금지
#   → Streamlit Material Symbols 아이콘 폰트가 상속으로 덮이면
#     아이콘 이름(arrow_drop_down 등)이 텍스트로 노출됨
#   텍스트 콘텐츠 요소에만 Pretendard 적용,
#   아이콘 요소(.material-symbols-rounded)는 명시적으로 복구
st.markdown("""
<style>
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.css');

/* ── Pretendard: 텍스트 콘텐츠 요소만 지정 ─────────────────
   html / body / button / input / select 제외
   → Material Symbols 폰트 상속 차단 방지                    */
p, h1, h2, h3, h4, h5, h6, li, td, th, label, caption,
.stMarkdown, .stText, .stCaption,
[data-testid="stMarkdownContainer"],
[data-testid="stMarkdownContainer"] p,
[data-testid="stMarkdownContainer"] li {
  font-family: 'Pretendard', -apple-system, BlinkMacSystemFont,
               'Apple SD Gothic Neo', sans-serif !important;
  word-break: keep-all;
}

/* ── Material Symbols 명시적 복구 ───────────────────────────
   Pretendard가 상위 요소에서 상속되더라도 아이콘 폰트 우선   */
.material-symbols-rounded,
.material-symbols-outlined,
.material-symbols-sharp,
[class*="material-symbols"] {
  font-family: 'Material Symbols Rounded' !important;
  font-weight: normal !important;
  font-style: normal !important;
  line-height: 1 !important;
  letter-spacing: normal !important;
  text-transform: none !important;
  white-space: nowrap !important;
  word-wrap: normal !important;
  direction: ltr !important;
  font-feature-settings: 'liga' !important;
  -webkit-font-feature-settings: 'liga' !important;
  -webkit-font-smoothing: antialiased !important;
}

/* ── 시스템 UI 제거 ─────────────────────────────────────── */
#MainMenu, footer, .stApp > header,
[data-testid="stToolbar"],
[data-testid="stDecoration"] { display: none !important; }

/* ── 레이아웃 ────────────────────────────────────────────── */
.block-container {
  max-width: 1400px !important;
  padding: 0 2rem 4rem !important;
  margin: 0 auto !important;
}
.stApp { background: #F7F9FC; }

/* ── 탭 ─────────────────────────────────────────────────── */
[data-testid="stTabs"] [role="tablist"] {
  border-bottom: 2px solid #DCE3EA; gap: 0; padding: 0;
}
[data-testid="stTabs"] [role="tab"] {
  font-weight: 600 !important; font-size: 14px !important;
  color: #667085 !important; padding: 10px 20px !important;
  border-bottom: 3px solid transparent !important;
  margin-bottom: -2px !important;
}
[data-testid="stTabs"] [role="tab"][aria-selected="true"] {
  color: #2F6BFF !important;
  border-bottom: 3px solid #2F6BFF !important;
  background: transparent !important;
}
[data-testid="stTabs"] [role="tab"]:hover {
  color: #2F6BFF !important; background: #F0F5FF !important;
}
[data-testid="stTabsContent"] { padding-top: 1.6rem; }

/* ── 헤더 ───────────────────────────────────────────────── */
.kd-header {
  display: flex; align-items: center;
  justify-content: space-between; background: #fff;
  border-bottom: 1px solid #DCE3EA; padding: 9px 2rem;
  margin: 0 -2rem .5rem -2rem;
}
.kd-mark {
  width: 26px; height: 26px; background: #2F6BFF;
  border-radius: 6px; display: flex; align-items: center;
  justify-content: center; color: #fff;
  font-size: 13px; font-weight: 800;
}
.kd-logo  { display: flex; align-items: center; gap: 9px; }
.kd-name  { font-size: 13px; font-weight: 700; color: #102A43; }
.kd-meta  {
  display: flex; align-items: center; gap: 14px;
  font-size: 11.5px; color: #667085;
}
.kd-live  {
  background: #F0FDF4; color: #166534; padding: 3px 10px;
  border-radius: 20px; font-weight: 700; font-size: 11px;
}
.kd-live::before { content: "● "; color: #16A34A; font-size: 8px; }

/* ── 히어로 ─────────────────────────────────────────────── */
.kd-hero { padding: 1.2rem 0 1rem; border-bottom: 1px solid #DCE3EA; margin-bottom: 1.4rem; }
.kd-hero-title { font-size: 1.5rem; font-weight: 800; color: #102A43; margin: 0 0 .3rem; }
.kd-hero-sub   { font-size: .88rem; color: #667085; margin: 0; }

/* ── 섹션 헤더 ──────────────────────────────────────────── */
.sh-main { margin: 0 0 1.2rem; border-left: 4px solid #2F6BFF; padding-left: 14px; }
.sh-main .t { font-size: 1rem; font-weight: 800; color: #102A43; margin: 0; }
.sh-main .s { font-size: 12px; color: #667085; margin: 3px 0 0; }
.sh-sub  { border-left: 3px solid #2F6BFF; padding-left: 11px; margin: 0 0 10px; }
.sh-sub .t { font-size: 14px; font-weight: 700; color: #101828; margin: 0; }
.sh-sub .s { font-size: 11.5px; color: #667085; margin: 2px 0 0; }

/* ── KPI 카드 ───────────────────────────────────────────── */
.kpi-card { background: #fff; border: 1px solid #DCE3EA; border-radius: 12px; padding: 18px 20px 16px; }
.kpi-lbl  { font-size: 10px; font-weight: 700; color: #667085; text-transform: uppercase; letter-spacing: .07em; margin-bottom: 9px; }
.kpi-val  { font-size: 2.4rem; font-weight: 800; color: #101828; line-height: 1; }
.kpi-unit { font-size: .88rem; font-weight: 400; color: #667085; margin-left: 3px; }
.kpi-hint { font-size: 11.5px; color: #667085; margin-top: 7px; }
.bdg-pass { display: inline-block; background: #ECFDF5; color: #065F46; border-radius: 6px; padding: 6px 14px; font-weight: 700; font-size: 13px; margin-top: 9px; }
.bdg-fail { display: inline-block; background: #FFF7ED; color: #9A3412; border-radius: 6px; padding: 6px 14px; font-weight: 700; font-size: 13px; margin-top: 9px; }

/* ── 태그 ───────────────────────────────────────────────── */
.tag-pr    { display:inline-block;background:#EFF6FF;color:#1e40af;border-radius:4px;padding:2px 8px;font-size:11.5px;font-weight:600; }
.tag-done  { display:inline-block;background:#ECFDF5;color:#065F46;border-radius:4px;padding:2px 8px;font-size:11.5px;font-weight:600; }
.tag-todo  { display:inline-block;background:#F1F5F9;color:#475569;border-radius:4px;padding:2px 8px;font-size:11.5px;font-weight:600; }
.tag-owned { display:inline-block;background:#FDF4FF;color:#7e22ce;border-radius:4px;padding:2px 8px;font-size:11.5px;font-weight:600; }
.tag-common{ display:inline-block;background:#F0FDF4;color:#166534;border-radius:4px;padding:2px 8px;font-size:11.5px;font-weight:600; }
.tag-none  { display:inline-block;background:#F1F5F9;color:#94A3B8;border-radius:4px;padding:2px 8px;font-size:11.5px;font-weight:600; }

/* ── 기사 카드 ──────────────────────────────────────────── */
.art-kw      { display:inline-block;background:#EFF6FF;color:#1D4ED8;border-radius:4px;padding:2px 8px;font-size:11px;font-weight:700;margin-right:4px; }
.art-type-pr { display:inline-block;background:#FEF3C7;color:#92400E;border-radius:4px;padding:2px 7px;font-size:11px;font-weight:600;margin-right:4px; }
.art-type-feat{display:inline-block;background:#EDE9FE;color:#5B21B6;border-radius:4px;padding:2px 7px;font-size:11px;font-weight:600;margin-right:4px; }
.art-type-int{ display:inline-block;background:#FDF4FF;color:#7e22ce;border-radius:4px;padding:2px 7px;font-size:11px;font-weight:600;margin-right:4px; }
.art-type-ev { display:inline-block;background:#ECFDF5;color:#065F46;border-radius:4px;padding:2px 7px;font-size:11px;font-weight:600;margin-right:4px; }
.art-type-gen{ display:inline-block;background:#F1F5F9;color:#475569;border-radius:4px;padding:2px 7px;font-size:11px;font-weight:600;margin-right:4px; }
.art-media   { display:inline-block;background:#F0FDF4;color:#166534;border-radius:4px;padding:2px 7px;font-size:11px;font-weight:600; }
.art-score   { display:inline-block;background:#F1F5F9;color:#475569;border-radius:20px;padding:2px 10px;font-size:11px;font-weight:600; }
.art-meta    { font-size:12px;color:#667085;line-height:1.8; }
.art-desc    { font-size:13px;color:#475569;line-height:1.65;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden; }
.art-status-err { font-size:12px;color:#DC2626;font-weight:600; }
/* ── SCK 관련성 배지 ────────────────────────────────── */
.rel-high { display:inline-block;background:#D1FAE5;color:#065F46;border-radius:4px;padding:2px 8px;font-size:11px;font-weight:700;margin-right:4px; }
.rel-mid  { display:inline-block;background:#FEF3C7;color:#92400E;border-radius:4px;padding:2px 8px;font-size:11px;font-weight:700;margin-right:4px; }
.rel-low  { display:inline-block;background:#F3F4F6;color:#6B7280;border-radius:4px;padding:2px 8px;font-size:11px;font-weight:700;margin-right:4px; }
.rel-type { display:inline-block;background:#EFF6FF;color:#1E40AF;border-radius:4px;padding:2px 7px;font-size:10px;font-weight:600; }
.rel-why  { font-size:11px;color:#94A3B8;line-height:1.6;margin:2px 0 5px; }
.art-suggest    { font-size:11.5px;color:#2F6BFF;background:#EEF4FF;border-radius:4px;padding:3px 8px;display:inline-block;margin:4px 0; }
.art-suggest.risk { color:#B45309;background:#FFFBEB; }
.art-util-reg   { font-size:11px;color:#059669;font-weight:600; }
.news-stat-card { background:#F7F9FC;border:1px solid #E4EAF0;border-radius:10px;padding:14px 18px;text-align:center; }
.news-stat-num  { font-size:1.45rem;font-weight:800;color:#101828;line-height:1.3; }
.news-stat-lbl  { font-size:11px;color:#667085;margin-top:2px; }
.flow-step      { display:inline-block;background:#EEF4FF;color:#2F6BFF;border-radius:20px;
                  padding:3px 12px;font-size:11.5px;font-weight:600;margin:2px; }
.flow-arrow     { color:#94A3B8;font-size:13px;margin:0 2px; }
.insight-bar    { background:#F0FDF4;border-left:3px solid #10B981;border-radius:0 6px 6px 0;
                  padding:8px 14px;font-size:13px;color:#065F46;margin:8px 0 14px; }

/* ── 트렌드 카드 ────────────────────────────────────────── */
.tc-kw  { font-size:.98rem;font-weight:800;color:#101828;margin-bottom:9px; }
.tc-row { font-size:13px;color:#667085;margin:4px 0;line-height:1.5; }
.tc-row strong { color:#101828; }
.tc-wait       { padding:24px 0;text-align:center; }
.tc-wait-title { font-weight:700;color:#667085;font-size:13px;margin-bottom:4px; }
.tc-wait-sub   { font-size:12px;color:#94A3B8; }

/* ── 공통 ───────────────────────────────────────────────── */
hr { border-color:#DCE3EA !important; margin:1.2rem 0 !important; }
.stProgress > div > div { background:#2F6BFF !important; }
.notice-box { background:#EFF6FF;border:1px solid #BFDBFE;border-radius:8px;padding:10px 14px;font-size:13px;color:#1e40af;margin:.6rem 0; }
.warn-box   { background:#FEF3C7;border:1px solid #FDE68A;border-radius:8px;padding:10px 14px;font-size:13px;color:#92400E;margin:.6rem 0; }
.th { font-size:10.5px;font-weight:700;color:#667085;text-transform:uppercase;letter-spacing:.05em; }
.td { font-size:13px;line-height:1.65; }

@media(max-width:768px) {
  .block-container { padding:0 .8rem 3rem !important; }
  .kd-header { flex-wrap:wrap; gap:6px; }
  .kpi-val { font-size:2rem; }
}
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════
# 데이터 초기화
# ══════════════════════════════════════════════════════════
def ensure_data():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(TRENDS_CSV):
        pd.DataFrame(columns=TRENDS_COLS).to_csv(TRENDS_CSV, index=False, encoding="utf-8-sig")
    for path, cols in [(DERIVED_CSV,DERIVED_COLS),(CONTENT_CSV,CONTENT_COLS),
                       (MANUAL_CSV,MANUAL_COLS),(NEWS_UTIL_CSV,NEWS_UTIL_COLS)]:
        if not os.path.exists(path):
            pd.DataFrame(columns=cols).to_csv(path, index=False, encoding="utf-8-sig")
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
@st.cache_data(ttl=30, show_spinner=False)
def _gh_load_derived() -> pd.DataFrame:
    df = gh.read_csv("data/derived_keywords.csv")
    return df if df is not None else pd.DataFrame(columns=DERIVED_COLS)

def _inv_derived(): _gh_load_derived.clear()

def _read_derived_all() -> pd.DataFrame:
    if gh.is_configured():
        df = _gh_load_derived()
    elif os.path.exists(DERIVED_CSV):
        try:   df = pd.read_csv(DERIVED_CSV, dtype=str)
        except: df = pd.DataFrame(columns=DERIVED_COLS)
    else:
        return pd.DataFrame(columns=DERIVED_COLS)
    df = df.fillna("")
    for c in DERIVED_COLS:
        if c not in df.columns: df[c] = ""
    return df

def _write_derived(df: pd.DataFrame, msg: str) -> bool:
    if gh.is_configured():
        ok = gh.write_csv(df, "data/derived_keywords.csv", msg)
        if ok: _inv_derived()
        return ok
    df[DERIVED_COLS].to_csv(DERIVED_CSV, index=False, encoding="utf-8-sig")
    return True

def load_derived(month: str) -> pd.DataFrame:
    df = _read_derived_all()
    if df.empty or "kpi_month" not in df.columns:
        return pd.DataFrame(columns=["키워드","활용처","상태","벤더","아이디어","출처URL","등록출처","등록일"])
    df = df[df["kpi_month"] == month].copy()
    for c,v in [("keyword",""),("usage_type",""),("status","도출"),("vendor",""),
                ("idea",""),("source_url",""),("discovery_source","직접 입력"),("added_at","")]:
        if c not in df.columns: df[c] = v
    return df.rename(columns={"keyword":"키워드","usage_type":"활용처","status":"상태",
                               "vendor":"벤더","idea":"아이디어","source_url":"출처URL",
                               "discovery_source":"등록출처","added_at":"등록일"}
                     ).reindex(columns=["키워드","활용처","상태","벤더","아이디어","출처URL","등록출처","등록일"],
                               fill_value="").reset_index(drop=True)

def add_keyword(keyword, month, usage_type="", vendor="", idea="",
                source_url="", discovery_source="직접 입력") -> bool:
    df = _read_derived_all()
    if not df.empty and ((df["keyword"]==keyword)&(df["kpi_month"]==month)).any():
        return False
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    row = pd.DataFrame([[keyword,month,usage_type,"도출",vendor,idea,
                         source_url,discovery_source,now]], columns=DERIVED_COLS)
    _write_derived(pd.concat([df,row],ignore_index=True), f"키워드 추가: {keyword} ({month})")
    return True

def delete_keyword(keyword, month):
    df = _read_derived_all()
    _write_derived(df[~((df["keyword"]==keyword)&(df["kpi_month"]==month))],
                   f"키워드 삭제: {keyword} ({month})")

def update_usage_type(keyword, month, new_usage) -> bool:
    if not new_usage or str(new_usage).strip() in ("","nan","None"):
        new_usage = ""
    df = _read_derived_all()
    mask = (df["keyword"]==keyword) & (df["kpi_month"]==month)
    if not mask.any(): return False
    df.loc[mask,"usage_type"] = new_usage
    return bool(_write_derived(df, f"활용처 변경: {keyword} → {new_usage or '미지정'}"))

def _set_status(keyword, month, status):
    df = _read_derived_all()
    mask = (df["keyword"]==keyword) & (df["kpi_month"]==month)
    if mask.any():
        df.loc[mask,"status"] = status
        _write_derived(df, f"상태 변경: {keyword} → {status}")


# ══════════════════════════════════════════════════════════
# 콘텐츠 CRUD
# ══════════════════════════════════════════════════════════
@st.cache_data(ttl=30, show_spinner=False)
def _gh_load_content() -> pd.DataFrame:
    df = gh.read_csv("data/applied_content.csv")
    return df if df is not None else pd.DataFrame(columns=CONTENT_COLS)

def _inv_content(): _gh_load_content.clear()

def _read_content_all() -> pd.DataFrame:
    if gh.is_configured(): return _gh_load_content()
    if not os.path.exists(CONTENT_CSV): return pd.DataFrame(columns=CONTENT_COLS)
    try:   df = pd.read_csv(CONTENT_CSV, dtype=str).fillna("")
    except: df = pd.DataFrame(columns=CONTENT_COLS)
    for c in CONTENT_COLS:
        if c not in df.columns: df[c] = ""
    return df

def _write_content(df, msg) -> bool:
    if gh.is_configured():
        ok = gh.write_csv(df,"data/applied_content.csv",msg)
        if ok: _inv_content()
        return ok
    df[CONTENT_COLS].to_csv(CONTENT_CSV,index=False,encoding="utf-8-sig")
    return True

def load_content(month: str) -> pd.DataFrame:
    df = _read_content_all()
    if df.empty or "kpi_month" not in df.columns: return pd.DataFrame(columns=CONTENT_COLS)
    return df[df["kpi_month"]==month].copy().reset_index(drop=True)

def add_content(keyword, month, ctype, cname, url, pub_at) -> bool:
    df = _read_content_all()
    if not df.empty and ((df["keyword"]==keyword)&(df["kpi_month"]==month)&(df["url"]==url)).any():
        return False
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    row = pd.DataFrame([[keyword,month,ctype,cname,url,pub_at,now]],columns=CONTENT_COLS)
    _write_content(pd.concat([df,row],ignore_index=True), f"콘텐츠 등록: {keyword} — {cname}")
    _set_status(keyword,month,"반영완료")
    return True

def _read_news_util() -> pd.DataFrame:
    if not os.path.exists(NEWS_UTIL_CSV):
        return pd.DataFrame(columns=NEWS_UTIL_COLS)
    try:   df = pd.read_csv(NEWS_UTIL_CSV, dtype=str).fillna("")
    except: df = pd.DataFrame(columns=NEWS_UTIL_COLS)
    for c in NEWS_UTIL_COLS:
        if c not in df.columns: df[c] = ""
    return df

def add_news_util(title, url, media, pub_date, keyword, usage, memo="") -> bool:
    df = _read_news_util()
    if not df.empty and (df["기사 URL"]==url).any() and (df["활용처"]==usage).any():
        return False
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    row = pd.DataFrame([[now, title, url, media, pub_date, keyword, usage, memo, "등록"]],
                       columns=NEWS_UTIL_COLS)
    pd.concat([df, row], ignore_index=True).to_csv(NEWS_UTIL_CSV, index=False, encoding="utf-8-sig")
    return True

def count_news_util() -> int:
    df = _read_news_util()
    return len(df[df["상태"]=="등록"]) if not df.empty else 0

def delete_content_row(keyword, month, cname):
    df = _read_content_all()
    df = df[~((df["keyword"]==keyword)&(df["kpi_month"]==month)&(df["content_name"]==cname))]
    _write_content(df, f"콘텐츠 삭제: {keyword} — {cname}")
    if df[(df["keyword"]==keyword)&(df["kpi_month"]==month)].empty:
        _set_status(keyword,month,"도출")


# ══════════════════════════════════════════════════════════
# 월별 수동 KPI
# ══════════════════════════════════════════════════════════
@st.cache_data(ttl=30, show_spinner=False)
def _gh_load_manual() -> pd.DataFrame:
    df = gh.read_csv("data/monthly_manual.csv")
    return df if df is not None else pd.DataFrame(columns=MANUAL_COLS)

def _read_manual_all() -> pd.DataFrame:
    if gh.is_configured(): df = _gh_load_manual()
    elif os.path.exists(MANUAL_CSV):
        try:   df = pd.read_csv(MANUAL_CSV,dtype=str)
        except: df = pd.DataFrame(columns=MANUAL_COLS)
    else:
        return pd.DataFrame(columns=MANUAL_COLS)
    df = df.fillna("")
    for c in MANUAL_COLS:
        if c not in df.columns: df[c] = ""
    return df

def _write_manual(df, msg) -> bool:
    if gh.is_configured():
        ok = gh.write_csv(df,"data/monthly_manual.csv",msg)
        if ok: _gh_load_manual.clear()
        return ok
    df[MANUAL_COLS].to_csv(MANUAL_CSV,index=False,encoding="utf-8-sig")
    return True

def add_manual_month(month, derived, reflected, note="") -> bool:
    df = _read_manual_all()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if month in df["kpi_month"].values:
        idx = df[df["kpi_month"]==month].index[0]
        df.loc[idx,["manual_derived","manual_reflected","note","added_at"]] = [str(derived),str(reflected),note,now]
    else:
        df = pd.concat([df,pd.DataFrame([{"kpi_month":month,"manual_derived":str(derived),
                                          "manual_reflected":str(reflected),"note":note,"added_at":now}])],
                       ignore_index=True)
    return _write_manual(df[MANUAL_COLS], f"수동 KPI: {month}")

def delete_manual_month(month) -> bool:
    df = _read_manual_all()
    return _write_manual(df[df["kpi_month"]!=month].reset_index(drop=True), f"수동 KPI 삭제: {month}")

def load_monthly_kpi_summary() -> pd.DataFrame:
    df_d = _read_derived_all(); df_c = _read_content_all(); df_m = _read_manual_all()
    auto = {}
    if not df_d.empty and "kpi_month" in df_d.columns:
        for month,grp in df_d.groupby("kpi_month"):
            if not month: continue
            kws  = grp["keyword"].tolist()
            done = df_c[(df_c["kpi_month"]==month)&(df_c["keyword"].isin(kws))]["keyword"].nunique() \
                   if not df_c.empty else 0
            auto[month] = {"도출":len(kws),"반영":done,"비고":"자동 집계"}
    manual = {}
    if not df_m.empty:
        for _,r in df_m.iterrows():
            m = r.get("kpi_month","")
            if not m or m in auto: continue
            try:   d_,rv = int(r.get("manual_derived",0) or 0), int(r.get("manual_reflected",0) or 0)
            except: d_,rv = 0,0
            manual[m] = {"도출":d_,"반영":rv,"비고":f"수동 입력 ({r.get('note','')})".rstrip(" ()")}
    all_m = {**auto,**manual}
    if not all_m:
        return pd.DataFrame(columns=["월","도출 키워드","반영 완료","반영률(%)","KPI 달성","비고"])
    rows = []
    for m in sorted(all_m.keys(),reverse=True):
        d=all_m[m]; t=d["도출"]; rv=d["반영"]
        rate = round(rv/t*100,1) if t>0 else 0.0
        st_ = "⏳ 진행 중" if m==CURRENT_MONTH else ("✅ 달성" if t>=5 and rate>=70 else "❌ 미달성")
        rows.append({"월":m,"도출 키워드":t,"반영 완료":rv,"반영률(%)":rate,"KPI 달성":st_,"비고":d["비고"]})
    return pd.DataFrame(rows)


# ══════════════════════════════════════════════════════════
# 추적 키워드 CRUD
# ══════════════════════════════════════════════════════════
@st.cache_data(ttl=30, show_spinner=False)
def _gh_load_tracked() -> pd.DataFrame:
    df = gh.read_csv("data/tracked_keywords.csv")
    return df if df is not None else pd.DataFrame(columns=TRACKED_COLS)

def _inv_tracked(): _gh_load_tracked.clear()

def _read_tracked_all() -> pd.DataFrame:
    if gh.is_configured(): return _gh_load_tracked()
    if not os.path.exists(TRACKED_CSV): ensure_data()
    try:   df = pd.read_csv(TRACKED_CSV,dtype=str)
    except: return pd.DataFrame(columns=TRACKED_COLS)
    for c in TRACKED_COLS:
        if c not in df.columns: df[c] = ""
    return df

def _write_tracked(df, msg):
    if gh.is_configured():
        ok = gh.write_csv(df,"data/tracked_keywords.csv",msg)
        if ok: _inv_tracked()
    else:
        df.to_csv(TRACKED_CSV,index=False,encoding="utf-8-sig")

def load_tracked_keywords() -> list:
    df = _read_tracked_all()
    return df["keyword"].dropna().tolist() if not df.empty else []

def add_tracked_keyword(keyword) -> bool:
    df = _read_tracked_all()
    if keyword in df["keyword"].tolist(): return False
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    df = pd.concat([df,pd.DataFrame([[keyword,now]],columns=TRACKED_COLS)],ignore_index=True)
    _write_tracked(df, f"추적 추가: {keyword}")
    return True

def remove_tracked_keyword(keyword):
    df = _read_tracked_all()
    _write_tracked(df[df["keyword"]!=keyword], f"추적 삭제: {keyword}")

def remove_all_tracked():
    _write_tracked(pd.DataFrame(columns=TRACKED_COLS), "전체 추적 해제")


# ══════════════════════════════════════════════════════════
# 트렌드 데이터
# ══════════════════════════════════════════════════════════
@st.cache_data(ttl=600, show_spinner=False)   # 10분 — 8시간 캐시가 갱신 지연의 근본 원인이었음
def load_trends() -> pd.DataFrame:
    if not os.path.exists(TRENDS_CSV): return pd.DataFrame()
    df = pd.read_csv(TRENDS_CSV)
    df["date"] = pd.to_datetime(df["date"])
    return df

def _persist_trends_to_gh(keyword: str):
    """collect_single_keyword 직후 호출 — Streamlit 리디플로이 전에 trends.csv를 GitHub에 영구 저장.
    tracked_keywords 커밋이 리디플로이를 트리거하므로 이 함수가 없으면 로컬 수집 데이터가 소실됨."""
    if not gh.is_configured() or not os.path.exists(TRENDS_CSV):
        return
    try:
        gh.write_csv(pd.read_csv(TRENDS_CSV), "data/trends.csv", f"트렌드 수집: {keyword}")
    except Exception:
        pass

def to_weekly(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["주차"] = d["date"].dt.to_period("W").apply(lambda p: p.start_time)
    return (d.groupby(["주차","keyword"])["ratio"].mean().reset_index()
             .rename(columns={"keyword":"키워드","ratio":"평균 관심도"}))

def derive_trend_summary(series: pd.Series) -> tuple:
    if len(series) < 4: return "분석 대기","분석에 필요한 데이터가 충분하지 않습니다."
    r4  = float(series.iloc[-4:].mean()); n = len(series)
    p4  = float(series.iloc[-8:-4].mean()) if n>=8 else float(series.iloc[:max(1,n-4)].mean())
    pct = (r4-p4)/max(p4,1)*100
    x   = np.arange(min(4,n)); y = series.iloc[-4:].values.astype(float)
    slp = float(np.polyfit(x,y,1)[0]) if len(y)>=2 else 0.0
    cv  = float(series.iloc[-4:].std()/max(float(series.iloc[-4:].mean()),1))
    r1  = float(series.iloc[-1]) if n>=1 else 0.0
    p1  = float(series.iloc[-2]) if n>=2 else r1
    if pct>=30 and slp>1: return "급상승",          f"최근 4주 평균이 이전 대비 {pct:.0f}% 증가했습니다."
    if pct>=10:           return "꾸준한 상승",      f"최근 4주 평균이 이전 대비 {pct:.0f}% 증가했습니다."
    if pct>=3:            return "완만한 상승",      f"최근 4주 평균이 이전 대비 {pct:.0f}% 증가했습니다."
    if cv>=0.35:          return "등락 반복",        f"관심도 변동성이 높습니다. (변동계수 {cv:.2f})"
    if pct<=-20:          return "지속 하락",        f"최근 4주 평균이 이전 대비 {abs(pct):.0f}% 감소했습니다."
    if pct<=-8:           return "전월 대비 하락세", f"최근 4주 평균이 이전 대비 {abs(pct):.0f}% 감소했습니다."
    if (r1-p1)>5 and pct<-5: return "반등 조짐","하락 추세 중 최근 1~2주 반등 신호가 보입니다."
    return "비슷하게 유지 중",f"최근 4주 관심도가 안정적입니다. (평균 {r4:.1f})"

def compute_kw_stats(df_kw: pd.DataFrame) -> dict:
    if df_kw.empty: return {}
    s = df_kw.sort_values("date")["ratio"].reset_index(drop=True)
    if s.empty: return {}
    cur  = float(s.iloc[-1]); pw = float(s.iloc[-2]) if len(s)>=2 else cur
    avg4 = float(s.iloc[-4:].mean()) if len(s)>=4 else float(s.mean())
    n    = len(s)
    prv4 = float(s.iloc[-8:-4].mean()) if n>=8 else float(s.iloc[:max(1,n-4)].mean()) if n>4 else avg4
    lbl,tip = derive_trend_summary(s)
    return {"current":cur,"wk_chg":(cur-pw)/max(pw,1)*100,"avg4":avg4,
            "avg_chg":(avg4-prv4)/max(prv4,1)*100,"trend_label":lbl,"trend_tip":tip,
            "series":s,"n":n}

def get_last_collection_time() -> str:
    if not os.path.exists(TRENDS_CSV): return "수집 기록 없음"
    try:
        df = pd.read_csv(TRENDS_CSV, usecols=["collected_at"])
        if df.empty: return "수집 기록 없음"
        # collected_at은 로컬(KST) 시각으로 저장됨 — 추가 변환 불필요
        ts = pd.to_datetime(df["collected_at"]).max()
        return ts.strftime("%Y.%m.%d %H:%M")
    except: return "—"


# ══════════════════════════════════════════════════════════
# 뉴스 키워드 (캐시)
# ══════════════════════════════════════════════════════════
@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_news_keywords_cached():
    from news_crawler import fetch_news_keywords
    return fetch_news_keywords(top_n=20)


# ══════════════════════════════════════════════════════════
# 자격증명
# ══════════════════════════════════════════════════════════
def _get_naver_creds():
    from dotenv import load_dotenv; load_dotenv()
    cid = os.getenv("NAVER_CLIENT_ID","").strip() or st.secrets.get("NAVER_CLIENT_ID","")
    csc = os.getenv("NAVER_CLIENT_SECRET","").strip() or st.secrets.get("NAVER_CLIENT_SECRET","")
    return cid, csc


# ══════════════════════════════════════════════════════════
# 활용처 자동저장 콜백 팩토리
# ══════════════════════════════════════════════════════════
def _make_usage_cb(kw, month):
    def _cb():
        val = st.session_state.get(f"t5_sel_{kw}") or ""
        if update_usage_type(kw, month, val):
            _inv_derived()
            st.session_state[f"t5_saved_{kw}"] = True
    return _cb


# ══════════════════════════════════════════════════════════
# collapsible_header — st.expander 완전 대체
# 이 함수를 통해서만 접이식 섹션을 만든다.
# ══════════════════════════════════════════════════════════
def collapsible_header(title: str, key: str, default_open: bool = False) -> bool:
    """
    st.expander 대체 함수.
    - _arr 깨진 텍스트 문제 없음 (Streamlit 내부 컴포넌트 미사용)
    - 반환값이 True 면 본문 렌더링
    """
    if key not in st.session_state:
        st.session_state[key] = default_open
    is_open = st.session_state[key]
    icon    = "▲" if is_open else "▼"
    label   = f"{icon}  {title}"

    if st.button(label, key=f"_coll_{key}",
                 type="secondary", use_container_width=True):
        st.session_state[key] = not is_open
        st.rerun()

    return st.session_state[key]


# ══════════════════════════════════════════════════════════
# 렌더링 헬퍼
# ══════════════════════════════════════════════════════════
def _trend_badge(label, tip):
    if "상승" in label or "반등" in label: bg,fg = "#ECFDF5","#065F46"
    elif "하락" in label:                  bg,fg = "#FEF2F2","#991B1B"
    elif "대기" in label:                  bg,fg = "#F1F5F9","#667085"
    else:                                  bg,fg = "#EFF6FF","#1D4ED8"
    return (f"<span title='{tip}' style='display:inline-block;background:{bg};color:{fg};"
            f"border-radius:20px;padding:2px 10px;font-size:11.5px;font-weight:700'>{label}</span>")

def _art_type_html(t):
    cls = {"보도자료형":"art-type-pr","기획·분석":"art-type-feat",
           "인터뷰":"art-type-int","행사·현장":"art-type-ev"}.get(t,"art-type-gen")
    return f"<span class='{cls}'>{t}</span>"

def _status_html(s):
    return ("<span class='tag-done'>반영완료</span>" if s=="반영완료"
            else "<span class='tag-todo'>도출</span>")

def _hex_rgba(h, a=0.13):
    h=h.lstrip("#"); r,g,b=int(h[:2],16),int(h[2:4],16),int(h[4:],16)
    return f"rgba({r},{g},{b},{a})"

def _sparkline(series, color="#2F6BFF"):
    fig = go.Figure(go.Scatter(x=list(range(len(series))),y=series.values,
                               mode="lines",line=dict(color=color,width=2),
                               fill="tozeroy",fillcolor=_hex_rgba(color)))
    fig.update_layout(height=48,margin=dict(l=0,r=0,t=0,b=0),
                      paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(0,0,0,0)",
                      showlegend=False,
                      xaxis=dict(visible=False,fixedrange=True),
                      yaxis=dict(visible=False,fixedrange=True))
    return fig

def _render_monthly_table(df):
    if df.empty: st.info("집계할 데이터가 없습니다."); return
    def _row(r):
        s = r["KPI 달성"]
        sc = ("color:#1d4ed8;font-weight:700" if "달성" in s and "미달성" not in s
              else ("color:#92400e;font-weight:700" if "진행" in s else "color:#dc2626;font-weight:700"))
        return (f"<tr><td style='padding:6px 12px'>{r['월']}</td>"
                f"<td style='padding:6px 12px;text-align:center'>{r['도출 키워드']}건</td>"
                f"<td style='padding:6px 12px;text-align:center'>{r['반영 완료']}건</td>"
                f"<td style='padding:6px 12px;text-align:center'>{r['반영률(%)']}%</td>"
                f"<td style='padding:6px 12px;text-align:center;{sc}'>{s}</td>"
                f"<td style='padding:6px 12px;color:#64748b;font-size:.85rem'>{r['비고']}</td></tr>")
    rows = "\n".join(_row(r) for _,r in df.iterrows())
    st.markdown(f"""<table style='width:100%;border-collapse:collapse;background:#fff;border-radius:8px;overflow:hidden;font-size:.92rem;border:1px solid #DCE3EA'>
<thead style='background:#f1f5f9;font-weight:700;color:#475569'>
<tr><th style='padding:8px 12px;text-align:left'>월</th>
    <th style='padding:8px 12px'>도출</th><th style='padding:8px 12px'>반영</th>
    <th style='padding:8px 12px'>반영률</th><th style='padding:8px 12px'>KPI</th>
    <th style='padding:8px 12px;text-align:left'>비고</th></tr></thead>
<tbody>{rows}</tbody></table>""", unsafe_allow_html=True)

def _render_manual_form(df_monthly, pfx=""):
    dm = _read_manual_all()
    if not dm.empty:
        st.markdown("**저장된 수동 입력**")
        for _,mr in dm.iterrows():
            c1,c2,c3,c4,c5 = st.columns([2,1.2,1.2,2.5,1])
            c1.text(mr["kpi_month"]); c2.text(f"도출 {mr['manual_derived']}건")
            c3.text(f"반영 {mr['manual_reflected']}건"); c4.text(mr.get("note","") or "")
            with c5:
                if st.button("삭제",key=f"{pfx}dm_{mr['kpi_month']}",type="secondary"):
                    delete_manual_month(mr["kpi_month"]); st.rerun()
        st.markdown("---")
    st.markdown("**새 달 추가**")
    a,b,c,d_ = st.columns([2,1.2,1.2,3])
    with a: mm = st.text_input("월 (YYYY-MM)",placeholder="예: 2026-05",key=f"{pfx}mm_in")
    with b: md = st.number_input("도출 건수",min_value=0,step=1,label_visibility="collapsed",key=f"{pfx}md_in")
    with c: mr2= st.number_input("반영 건수",min_value=0,step=1,label_visibility="collapsed",key=f"{pfx}mr_in")
    with d_: mn= st.text_input("비고",placeholder="시스템 도입 전 등",key=f"{pfx}mn_in")
    if st.button("저장",type="primary",key=f"{pfx}ms_btn"):
        ms = mm.strip()
        autos = set(df_monthly[df_monthly["비고"]=="자동 집계"]["월"].tolist()) if not df_monthly.empty else set()
        if not re.match(r"^\d{4}-\d{2}$",ms): st.warning("YYYY-MM 형식으로 입력해 주세요.")
        elif ms==CURRENT_MONTH: st.warning("이번 달은 자동 집계됩니다.")
        elif ms in autos: st.warning(f"{ms}은 자동 집계 데이터가 있습니다.")
        elif int(mr2)>int(md): st.warning("반영 건수는 도출 건수보다 클 수 없습니다.")
        else:
            if add_manual_month(ms,int(md),int(mr2),mn.strip()):
                st.success(f"{ms} 저장 완료!"); st.rerun()


# ══════════════════════════════════════════════════════════
# 콘텐츠 등록 다이얼로그
# ══════════════════════════════════════════════════════════
@st.dialog("콘텐츠 등록 / 상세 편집")
def content_dialog(keyword, month, usage):
    st.markdown(f"**키워드:** `{keyword}`")
    nu = st.selectbox("활용처 변경", USAGES,
                      index=USAGES.index(usage) if usage in USAGES else 0,
                      key=f"dlg_u_{keyword}_{month}")
    if st.button("활용처 저장",key=f"dlg_us_{keyword}_{month}",type="secondary"):
        if update_usage_type(keyword,month,nu):
            _inv_derived(); st.success(f"'{nu}'로 변경했습니다."); st.rerun()
        else: st.error("저장 실패.")
    st.markdown("---")
    df_all_c = _read_content_all()
    ex = df_all_c[(df_all_c["keyword"]==keyword)&(df_all_c["kpi_month"]==month)]
    if not ex.empty:
        st.markdown("**등록된 콘텐츠**")
        for _,row in ex.iterrows():
            cn,cu,cd = row.get("content_name",""),row.get("url",""),row.get("published_at","")
            ca,cb = st.columns([8,2])
            with ca: st.markdown(f"• [{cn or cu}]({cu}) — {cd}" if cu else f"• {cn} — {cd}")
            with cb:
                if st.button("삭제",key=f"dlg_del_{keyword}_{cn}",type="secondary"):
                    delete_content_row(keyword,month,cn); st.rerun()
        st.markdown("---")
    st.markdown("**새 콘텐츠 등록**")
    ct = st.selectbox("유형",["PR 기사","온드미디어"],key=f"dlg_ct_{keyword}")
    cn = st.text_input("콘텐츠명 *",placeholder="예: AI보안 동향 보도자료",key=f"dlg_cn_{keyword}")
    cu = st.text_input("URL (선택)",placeholder="https://...",key=f"dlg_cu_{keyword}")
    cd = st.date_input("발행일",value=date.today(),key=f"dlg_cd_{keyword}")
    if st.button("저장",type="primary",use_container_width=True,key=f"dlg_cs_{keyword}"):
        if not cn.strip(): st.warning("콘텐츠명을 입력해 주세요.")
        elif add_content(keyword,month,ct,cn.strip(),cu.strip(),str(cd)):
            _inv_content(); _inv_derived(); st.success("등록 완료!"); st.rerun()
        else: st.warning("이미 등록된 콘텐츠입니다.")

def build_excel() -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf,engine="openpyxl") as w:
        load_monthly_kpi_summary().to_excel(w,sheet_name="월별 KPI",index=False)
        d = _read_derived_all()
        if not d.empty: d.to_excel(w,sheet_name="도출 키워드",index=False)
        c = _read_content_all()
        if not c.empty: c.to_excel(w,sheet_name="적용 콘텐츠",index=False)
    return buf.getvalue()


# ══════════════════════════════════════════════════════════
# ── 메인 실행 ─────────────────────────────────────────────
# ══════════════════════════════════════════════════════════
ensure_data()

df_cur      = load_derived(CURRENT_MONTH)
df_cont_cur = load_content(CURRENT_MONTH)
KPI_D  = len(df_cur)
KPI_R  = df_cont_cur["keyword"].nunique() if not df_cont_cur.empty else 0
KPI_TD = 5; KPI_TR = 70
RATE   = round(KPI_R/KPI_D*100) if KPI_D>0 else 0
KPI_OK = KPI_D>=KPI_TD and RATE>=KPI_TR
NOW_STR= datetime.now().strftime("%Y.%m.%d %H:%M")
SYNC   = "GitHub 동기화" if gh.is_configured() else "로컬 모드"
MEDIA_CFG = nf.load_media_config()

# ── PR 모니터링 당일 캐시 ─────────────────────────────────────
_MON_CONFIG_PATH = mon.CONFIG_PATH

@st.cache_data(ttl=86400, show_spinner=False)
def _get_daily_monitoring_cached(date_key: str, refresh_token: int, config_version: str):
    """
    최근 24시간 PR 모니터링 결과를 캐싱한다.
    캐시 키: date_key(KST 날짜) / refresh_token(강제 새로고침) / config_version(설정 해시)
    """
    cid, csc = _get_naver_creds()
    _end   = datetime.now(timezone.utc)
    _start = _end - timedelta(hours=24)
    candidates = mon.fetch_daily_monitoring_candidates(
        _start, _end, cid=cid, csc=csc, media_config=MEDIA_CFG
    )
    selected = mon.select_daily_monitoring_articles(
        candidates, target_count=15, max_count=20, media_config=MEDIA_CFG
    )
    updated_at = _end + timedelta(hours=9)  # KST
    stats = {"candidate_count": len(candidates), "selected_count": len(selected)}
    return selected, updated_at, stats

st.markdown(f"""
<div class="kd-header">
  <div class="kd-logo">
    <div class="kd-mark">K</div>
    <div class="kd-name">SCK/STK Corp · 커뮤니케이션팀</div>
  </div>
  <div class="kd-meta">
    <span>기준월 <strong>{CURRENT_MONTH}</strong></span>
    <span>{NOW_STR} KST</span>
    <span>{SYNC}</span>
    <span class="kd-live">라이브</span>
  </div>
</div>
<div class="kd-hero">
  <div class="kd-hero-title">뉴스 &amp; 트렌드 모니터링</div>
  <div class="kd-hero-sub">주요 뉴스와 키워드 흐름을 모니터링하고, PR 활용 가능한 이슈와 소재를 발굴합니다.</div>
</div>""", unsafe_allow_html=True)

tab1,tab2,tab3,tab4,tab5 = st.tabs([
    "📊 모니터링 현황",
    "🔍 키워드 발굴·등록",
    "📈 키워드 추이 분석",
    "📰 관련 뉴스 수집",
    "📋 PR 활용 관리",
])


# ════════════════════════════════════════════════════════
# TAB 1 · 모니터링 현황
# ════════════════════════════════════════════════════════
with tab1:
    st.markdown("""<div class="sh-main"><div class="t">모니터링 현황</div>
<div class="s">이번 달 등록 키워드, 반영 현황, 기사 수집 상태를 요약해 확인합니다.</div></div>""",
                unsafe_allow_html=True)
    st.markdown("""<div class="sh-sub"><div class="t">이번 달 KPI 현황</div>
<div class="s">도출 목표 5건 · 반영률 목표 70%</div></div>""", unsafe_allow_html=True)

    c1,c2,c3,c4 = st.columns(4,gap="medium")
    with c1:
        st.markdown(f"<div class='kpi-card'><div class='kpi-lbl'>도출 키워드</div>"
                    f"<div class='kpi-val'>{KPI_D}<span class='kpi-unit'>건</span></div>"
                    f"<div class='kpi-hint'>목표 {KPI_TD}건</div></div>",unsafe_allow_html=True)
        st.progress(min(KPI_D/KPI_TD,1.0))
    with c2:
        st.markdown(f"<div class='kpi-card'><div class='kpi-lbl'>반영 완료</div>"
                    f"<div class='kpi-val'>{KPI_R}<span class='kpi-unit'>건</span></div>"
                    f"<div class='kpi-hint'>도출 {KPI_D}건 중</div></div>",unsafe_allow_html=True)
        st.progress(min(KPI_R/max(KPI_D,1),1.0))
    with c3:
        st.markdown(f"<div class='kpi-card'><div class='kpi-lbl'>전체 반영률</div>"
                    f"<div class='kpi-val'>{RATE}<span class='kpi-unit'>%</span></div>"
                    f"<div class='kpi-hint'>목표 {KPI_TR}%</div></div>",unsafe_allow_html=True)
        st.progress(min(RATE/KPI_TR,1.0))
    with c4:
        bc="bdg-pass" if KPI_OK else "bdg-fail"
        bt="달성" if KPI_OK else "진행 중"
        hint="두 목표 모두 달성" if KPI_OK else f"도출 {max(KPI_TD-KPI_D,0)}건 · 반영률 {max(KPI_TR-RATE,0)}%p 부족"
        st.markdown(f"<div class='kpi-card'><div class='kpi-lbl'>KPI 달성</div>"
                    f"<span class='{bc}'>{bt}</span>"
                    f"<div class='kpi-hint' style='margin-top:10px'>{hint}</div></div>",unsafe_allow_html=True)
        st.progress(1.0 if KPI_OK else max(RATE/100,0.03))

    st.markdown("<div style='margin-top:1.8rem'></div>",unsafe_allow_html=True)
    rc1,rc2 = st.columns(2,gap="medium")
    with rc1:
        st.markdown("""<div class="sh-sub"><div class="t">최근 등록 키워드</div></div>""",unsafe_allow_html=True)
        da = _read_derived_all()
        if not da.empty:
            for _,r in da.sort_values("added_at",ascending=False).head(6).iterrows():
                lbl = r.get("usage_type","") or "미지정"
                st.markdown(f"• **{r['keyword']}** "
                            f"<span style='color:#667085;font-size:11.5px'>{r.get('kpi_month','')} · {lbl}</span>",
                            unsafe_allow_html=True)
        else: st.caption("등록된 키워드가 없습니다.")
    with rc2:
        st.markdown("""<div class="sh-sub"><div class="t">기사 수집 현황</div></div>""",unsafe_allow_html=True)
        t4_res = st.session_state.get("t4_results",{})
        if t4_res:
            total_art = sum(v.get("filtered_count",0) for v in t4_res.values())
            last_f    = st.session_state.get("t4_last_fetch","")
            st.markdown(f"<div style='font-size:2rem;font-weight:800;color:#101828'>{total_art}"
                        f"<span style='font-size:.88rem;font-weight:400;color:#667085'>건</span></div>",
                        unsafe_allow_html=True)
            if last_f: st.caption(f"마지막 수집 {last_f}")
            st.caption("'📰 관련 뉴스 수집' 탭에서 전체 내용을 확인하세요.")
        else:
            st.caption("'📰 관련 뉴스 수집' 탭에서 기사를 수집하면 여기에 요약이 표시됩니다.")

    st.markdown("<div style='margin-top:1rem'></div>",unsafe_allow_html=True)

    # ── 월별 KPI 누적 현황 (collapsible_header 사용 — _arr 없음) ──
    if collapsible_header("월별 KPI 누적 현황", "t1_kpi_exp"):
        with st.container(border=False):
            dfm = load_monthly_kpi_summary()
            buf_m = io.BytesIO()
            with pd.ExcelWriter(buf_m,engine="openpyxl") as w: dfm.to_excel(w,index=False,sheet_name="월별KPI")
            cc,_ = st.columns([2,5])
            with cc:
                st.download_button("⬇ 엑셀 다운로드",buf_m.getvalue(),
                                   file_name=f"kpi_{CURRENT_MONTH}.xlsx",
                                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                   key="t1_dl_m")
            _render_monthly_table(dfm)
            st.markdown("<div style='margin-top:1rem'></div>",unsafe_allow_html=True)
            _render_manual_form(dfm,pfx="t1_")

    st.markdown("<div style='margin-top:2rem'></div>", unsafe_allow_html=True)
    st.markdown("""<div class="sh-sub"><div class="t">다음 단계</div>
<div class="s">아래 탭에서 작업을 이어가세요.</div></div>""", unsafe_allow_html=True)
    _na, _nb, _nc = st.columns(3, gap="medium")
    with _na:
        st.markdown("""<div style='background:#F0F4FF;border:1px solid #C7D7FD;border-radius:10px;
padding:16px 18px;text-align:center'>
<div style='font-size:1.3rem'>🔍</div>
<div style='font-weight:700;color:#101828;font-size:14px;margin:6px 0 4px'>키워드 등록하기</div>
<div style='font-size:12px;color:#667085'>키워드 발굴·등록 탭</div></div>""", unsafe_allow_html=True)
    with _nb:
        st.markdown("""<div style='background:#F0FDF4;border:1px solid #A7F3D0;border-radius:10px;
padding:16px 18px;text-align:center'>
<div style='font-size:1.3rem'>📰</div>
<div style='font-weight:700;color:#101828;font-size:14px;margin:6px 0 4px'>관련 뉴스 수집하기</div>
<div style='font-size:12px;color:#667085'>관련 뉴스 수집 탭</div></div>""", unsafe_allow_html=True)
    with _nc:
        st.markdown("""<div style='background:#FFF7ED;border:1px solid #FED7AA;border-radius:10px;
padding:16px 18px;text-align:center'>
<div style='font-size:1.3rem'>📋</div>
<div style='font-weight:700;color:#101828;font-size:14px;margin:6px 0 4px'>PR 활용 관리하기</div>
<div style='font-size:12px;color:#667085'>PR 활용 관리 탭</div></div>""", unsafe_allow_html=True)


# ════════════════════════════════════════════════════════
# TAB 2 · 키워드 발굴·등록
# ════════════════════════════════════════════════════════
with tab2:
    st.markdown("""<div class="sh-main"><div class="t">키워드 발굴·등록</div>
<div class="s">급상승 키워드를 확인하거나 PR 모니터링에 필요한 키워드를 직접 등록합니다.</div></div>""",unsafe_allow_html=True)

    # 메인 등록 폼 (expander 없음 — form 내부 expander가 _arr 원인 중 하나)
    with st.form("t2_qreg",clear_on_submit=True):
        qa,qb,qc = st.columns([4,3,1.5])
        with qa: q_kw = st.text_input("키워드 *",placeholder="예: 제로트러스트")
        with qb: q_us = st.selectbox("활용처 *",USAGES)
        with qc:
            st.markdown("<div style='height:28px'></div>",unsafe_allow_html=True)
            q_sub = st.form_submit_button("＋ 키워드 등록",use_container_width=True,type="primary")

    # 추가 정보 (form 외부 — expander 대신 collapsible_header)
    if collapsible_header("추가 정보 입력 (선택)","t2_extra_exp"):
        with st.container(border=False):
            ea,eb = st.columns(2)
            with ea:
                st.text_input("관련 벤더",placeholder="예: Palo Alto Networks",key="t2_ve_s")
                st.text_input("아이디어·메모",placeholder="예: 이달 보도자료 핵심 소재",key="t2_id_s")
            with eb:
                st.text_input("출처 URL",placeholder="https://...",key="t2_su_s")
                st.checkbox("등록 후 자동 추적 시작",value=True,key="t2_at_s",
                            help="체크 시 트렌드 탐색 탭에도 즉시 추가됩니다.")

    if q_sub:
        kw_t = (q_kw or "").strip()
        q_ve = st.session_state.get("t2_ve_s","") or ""
        q_id = st.session_state.get("t2_id_s","") or ""
        q_su = st.session_state.get("t2_su_s","") or ""
        q_at = st.session_state.get("t2_at_s", True)
        if not kw_t:
            st.warning("키워드를 입력해 주세요.")
        elif add_keyword(kw_t,CURRENT_MONTH,usage_type=q_us,
                         vendor=q_ve.strip(),idea=q_id.strip(),source_url=q_su.strip()):
            _inv_derived()
            if q_at:
                if add_tracked_keyword(kw_t):
                    with st.spinner(f"'{kw_t}' 트렌드 데이터 수집 중…"):
                        collect_single_keyword(kw_t)
                        _persist_trends_to_gh(kw_t)
                    load_trends.clear(); _inv_tracked()
            st.success(f"✅ '{kw_t}' 등록 완료!")
            # 선택 필드 초기화
            for _k in ["t2_ve_s","t2_id_s","t2_su_s"]:
                if _k in st.session_state: del st.session_state[_k]
            st.rerun()
        else:
            st.warning("이미 등록된 키워드입니다.")

    st.markdown("<div style='margin-top:2rem'></div>",unsafe_allow_html=True)

    # ── 뉴스 키워드 발굴 ─────────────────────────────────
    last_upd = get_last_collection_time()
    st.markdown(f"""<div class="sh-main">
<div class="t">급상승 키워드 탐색
  <span style='font-weight:400;font-size:.82rem;color:#667085'>&nbsp;· 마지막 트렌드 업데이트 {last_upd}</span>
</div>
<div class="s">구글 뉴스 RSS 기사 빈도 기반 · 버튼 클릭 시 분석</div></div>""",unsafe_allow_html=True)

    if "t2_news_kws" not in st.session_state: st.session_state["t2_news_kws"] = None

    _,fb,fc = st.columns([5,2,1.5])
    with fb:
        if st.button("🔍 키워드 분석 시작",type="primary",use_container_width=True,key="t2_analyze"):
            with st.spinner("IT 뉴스 키워드 분석 중…"):
                try: st.session_state["t2_news_kws"] = _fetch_news_keywords_cached()
                except Exception as e: st.error(f"분석 실패: {e}")
    with fc:
        if st.button("캐시 초기화",type="secondary",use_container_width=True,key="t2_rf"):
            _fetch_news_keywords_cached.clear()
            st.session_state["t2_news_kws"] = None
            st.rerun()

    news_data = st.session_state["t2_news_kws"]
    if news_data is None:
        st.markdown("""<div class='notice-box'>
'🔍 키워드 분석 시작' 버튼을 클릭하면 IT 뉴스 기사 빈도 기반 키워드를 분석합니다.
</div>""",unsafe_allow_html=True)
    else:
        news_kws_raw, sources_ok = news_data
        if not news_kws_raw:
            st.info("분석된 키워드가 없습니다. 잠시 후 다시 시도해 주세요.")
        else:
            tracked_set2 = set(load_tracked_keywords())
            derived_set2 = set(df_cur["키워드"].tolist()) if not df_cur.empty else set()
            st.caption(f"📰 {sources_ok}")
            top8 = news_kws_raw[:8]; rest = news_kws_raw[8:]
            for rs in range(0,len(top8),4):
                batch=top8[rs:rs+4]; cols2=st.columns(4,gap="small")
                for col,(w,cnt) in zip(cols2,batch):
                    is_t=w in tracked_set2; is_d=w in derived_set2
                    with col:
                        with st.container(border=True):
                            st.markdown(f"<div style='font-size:.96rem;font-weight:700;margin-bottom:4px'>{w}</div>"
                                        f"<div style='font-size:11.5px;color:#667085;margin-bottom:10px'>언급 {cnt}회</div>",
                                        unsafe_allow_html=True)
                            ba,bb = st.columns(2)
                            with ba:
                                if is_t: st.markdown("<span style='color:#059669;font-size:12px;font-weight:600'>📌 추적 중</span>",unsafe_allow_html=True)
                                elif st.button("📌 추적",key=f"t2_tr_{w}",use_container_width=True,type="secondary"):
                                    add_tracked_keyword(w)
                                    with st.spinner("수집 중…"):
                                        collect_single_keyword(w); _persist_trends_to_gh(w); load_trends.clear()
                                    st.rerun()
                            with bb:
                                if is_d: st.markdown("<span style='color:#059669;font-size:12px;font-weight:600'>✅ 도출됨</span>",unsafe_allow_html=True)
                                elif st.button("＋ 도출",key=f"t2_dr_{w}",use_container_width=True,type="primary"):
                                    if add_keyword(w,CURRENT_MONTH,discovery_source="뉴스 자동탐지"):
                                        _inv_derived(); st.rerun()
                                    else: st.info("이미 등록됨")
            if rest:
                st.markdown("<div style='margin-top:1.2rem'></div>",unsafe_allow_html=True)
                h0,h1,h2,h3 = st.columns([.5,2.5,1.2,3.5])
                for c_,l_ in zip([h0,h1,h2,h3],["#","키워드","언급","액션"]):
                    c_.markdown(f"<span class='th'>{l_}</span>",unsafe_allow_html=True)
                st.markdown("<hr style='margin:4px 0'>",unsafe_allow_html=True)
                for i_,(w,cnt) in enumerate(rest,start=9):
                    is_t=w in tracked_set2; is_d=w in derived_set2
                    r0,r1,r2,r3 = st.columns([.5,2.5,1.2,3.5])
                    r0.markdown(f"<span class='td' style='color:#667085'>{i_}</span>",unsafe_allow_html=True)
                    r1.markdown(f"<span class='td' style='font-weight:600'>{w}</span>",unsafe_allow_html=True)
                    r2.markdown(f"<span class='td'>{cnt}회</span>",unsafe_allow_html=True)
                    with r3:
                        ba,bb,_ = st.columns([1.3,1.1,1.5])
                        with ba:
                            if not is_t:
                                if st.button("📌 추적",key=f"t2_rtr_{w}",use_container_width=True,type="secondary"):
                                    add_tracked_keyword(w)
                                    with st.spinner("수집 중…"):
                                        collect_single_keyword(w); _persist_trends_to_gh(w); load_trends.clear()
                                    st.rerun()
                            else: st.caption("추적 중")
                        with bb:
                            if not is_d:
                                if st.button("＋ 도출",key=f"t2_rdr_{w}",use_container_width=True,type="primary"):
                                    if add_keyword(w,CURRENT_MONTH,discovery_source="뉴스 자동탐지"):
                                        _inv_derived(); st.rerun()
                            else: st.caption("도출됨")
                    st.markdown("<hr style='margin:2px 0;border-color:#F7F9FC'>",unsafe_allow_html=True)


# ════════════════════════════════════════════════════════
# TAB 3 · 키워드 추이 분석
# ════════════════════════════════════════════════════════
with tab3:
    tracked_kws = load_tracked_keywords()

    st.markdown(f"""<div class="sh-main">
<div class="t">키워드 추이 분석 · {len(tracked_kws)}개 추적 중</div>
<div class="s">등록 키워드의 검색 관심도와 변동 추이를 비교해 PR 활용 가능성을 검토합니다.</div></div>""",
                unsafe_allow_html=True)

    if "hidden_kws"   not in st.session_state: st.session_state["hidden_kws"]   = set()
    if "t3_conf_del"  not in st.session_state: st.session_state["t3_conf_del"]  = False
    st.session_state["hidden_kws"] &= set(tracked_kws)
    hidden_kws = st.session_state["hidden_kws"]

    if tracked_kws:
        ba_,bb_,bc_,bd_ = st.columns([1.8,1.8,2.2,2.4])
        with ba_:
            if st.button("그래프 전체 표시",key="t3_show_all",type="secondary",use_container_width=True):
                st.session_state["hidden_kws"]=set(); st.rerun()
        with bb_:
            if st.button("그래프 전체 숨김",key="t3_hide_all",type="secondary",use_container_width=True):
                st.session_state["hidden_kws"]=set(tracked_kws); st.rerun()
        with bc_:
            if st.button(f"선택 추적 해제 (전체 {len(tracked_kws)}개)",key="t3_del_all",
                         type="secondary",use_container_width=True):
                st.session_state["t3_conf_del"]=True
        with bd_:
            if st.button("데이터 새로고침",key="t3_refresh_trends",type="primary",
                         use_container_width=True,help="trends.csv 캐시를 지우고 최신 데이터를 다시 읽습니다"):
                load_trends.clear()
                st.rerun()

        if st.session_state["t3_conf_del"]:
            st.markdown(f"<div class='warn-box'>추적 중인 키워드 <strong>{len(tracked_kws)}개</strong>를 모두 삭제하시겠습니까?</div>",
                        unsafe_allow_html=True)
            cc1,cc2 = st.columns([2,2])
            with cc1:
                if st.button("취소",key="t3_can",type="secondary"):
                    st.session_state["t3_conf_del"]=False; st.rerun()
            with cc2:
                if st.button("확인 — 전체 삭제",key="t3_ok",type="primary"):
                    remove_all_tracked(); st.session_state["hidden_kws"]=set()
                    st.session_state["t3_conf_del"]=False; _inv_tracked(); st.rerun()

        CHIP_COLS = 3
        for row_start in range(0,len(tracked_kws),CHIP_COLS):
            batch = tracked_kws[row_start:row_start+CHIP_COLS]
            widths = []
            for _ in batch: widths += [4.5,0.6]
            remaining = CHIP_COLS - len(batch)
            if remaining>0: widths += [5.1*remaining]
            chip_cols = st.columns(widths)
            for j,kw in enumerate(batch):
                hid = kw in hidden_kws
                with chip_cols[j*2]:
                    if st.button(f"{'●' if not hid else '○'} {kw}",key=f"chip_body_{kw}",
                                 type="primary" if not hid else "secondary",use_container_width=True):
                        if hid: hidden_kws.discard(kw)
                        else:   hidden_kws.add(kw)
                        st.session_state["hidden_kws"]=hidden_kws; st.rerun()
                with chip_cols[j*2+1]:
                    if st.button("×",key=f"chip_x_{kw}",type="secondary",
                                 use_container_width=True,help=f"'{kw}' 추적 삭제"):
                        remove_tracked_keyword(kw); hidden_kws.discard(kw)
                        st.session_state["hidden_kws"]=hidden_kws; _inv_tracked(); st.rerun()

    if not tracked_kws:
        st.info("추적 중인 키워드가 없습니다. 아래에서 추가하세요.")

    na,nb = st.columns([5,1])
    with na:
        new_tk = st.text_input("새 추적 키워드 추가",placeholder="예: 제로트러스트",
                               label_visibility="collapsed",key="t3_new_tk")
    with nb:
        if st.button("＋ 추가",type="primary",use_container_width=True,key="t3_add_btn"):
            kt = new_tk.strip()
            if not kt: st.warning("키워드를 입력해 주세요.")
            elif not add_tracked_keyword(kt): st.info(f"'{kt}'는 이미 추적 중입니다.")
            else:
                with st.spinner(f"'{kt}' 수집 중…"):
                    nok,gok = collect_single_keyword(kt)
                    _persist_trends_to_gh(kt)
                    load_trends.clear()
                _inv_tracked()
                st.success(f"추가 완료 — 네이버 {'✅' if nok else '⚠️'} / 구글 {'✅' if gok else '⚠️'}")
                st.rerun()

    st.markdown("<div style='margin-top:2rem'></div>",unsafe_allow_html=True)

    # ── 통합 비교 차트 ────────────────────────────────────
    if "period_days" not in st.session_state: st.session_state["period_days"]=30
    if "t3_sel_kws"  not in st.session_state: st.session_state["t3_sel_kws"]=tracked_kws[:3]
    st.session_state["t3_sel_kws"]=[k for k in st.session_state["t3_sel_kws"] if k in tracked_kws]

    st.markdown("""<div class="sh-main"><div class="t">통합 검색 추이 비교</div>
<div class="s">최대 5개 키워드 동시 비교</div></div>""",unsafe_allow_html=True)

    ca_kw,ca_pr = st.columns([7,3])
    with ca_kw:
        sel_kws = st.multiselect("비교 키워드 (최대 5개)",options=tracked_kws,
                                  default=st.session_state["t3_sel_kws"][:5],
                                  max_selections=5,placeholder="키워드를 선택하세요",
                                  key="t3_ms_kw")
        st.session_state["t3_sel_kws"]=sel_kws
    with ca_pr:
        PERIODS={"7일":7,"30일":30,"90일":90}
        pl=st.radio("기간",list(PERIODS.keys()),horizontal=True,
                    index=list(PERIODS.values()).index(st.session_state["period_days"]),
                    key="t3_period_r")
        st.session_state["period_days"]=PERIODS[pl]

    period_days = st.session_state["period_days"]
    cutoff      = pd.Timestamp.today().normalize()-pd.Timedelta(days=period_days)
    df_tr       = load_trends()

    if not sel_kws:
        st.info("위에서 비교할 키워드를 선택해 주세요.")
    elif df_tr.empty:
        st.warning("트렌드 데이터가 없습니다. GitHub Actions 수집 후 다시 확인해 주세요.")
    else:
        df_period = df_tr[(df_tr["keyword"].isin(sel_kws))&(df_tr["date"]>=cutoff)]
        src_choice= st.radio("소스",["네이버 데이터랩","구글 트렌드"],horizontal=True,key="t3_src_r")
        src_key   = "naver" if "네이버" in src_choice else "google"

        vis_kws = [k for k in sel_kws if k not in hidden_kws]
        if vis_kws:
            df_s  = df_period[df_period["source"]==src_key]
            df_s2 = df_s[df_s["keyword"].isin(vis_kws)] if not df_s.empty else pd.DataFrame()
            dw    = to_weekly(df_s2) if not df_s2.empty else pd.DataFrame()
            if not dw.empty:
                COLORS=["#2F6BFF","#10B981","#F59E0B","#EF4444","#8B5CF6"]
                kw_list=dw["키워드"].unique().tolist()
                cmap={k:COLORS[i%len(COLORS)] for i,k in enumerate(kw_list)}
                fig=px.line(dw,x="주차",y="평균 관심도",color="키워드",
                            markers=True,line_shape="spline",height=380,color_discrete_map=cmap)
                fig.update_layout(plot_bgcolor="white",paper_bgcolor="white",
                                  font=dict(family="Pretendard,sans-serif"),
                                  yaxis=dict(range=[0,105],gridcolor="#f0f0f0"),
                                  xaxis=dict(gridcolor="#f0f0f0"),
                                  margin=dict(l=10,r=10,t=10,b=10),hovermode="x unified",
                                  legend=dict(orientation="h",yanchor="bottom",y=1.02,xanchor="right",x=1))
                fig.update_traces(line_width=2.5,marker_size=6)
                st.plotly_chart(fig,use_container_width=True,
                                key=f"t3_chart_{src_key}_{period_days}")
            else:
                st.caption("선택한 기간에 표시할 수 있는 데이터가 없습니다.")

        # ── 트렌드 요약 카드 (완전 독립 사전계산) ────────────
        st.markdown(f"""<div class="sh-sub" style="margin-top:2rem">
<div class="t">키워드별 추이 요약</div>
<div class="s">최근 {period_days}일 · 각 키워드 독립 처리</div></div>""",unsafe_allow_html=True)

        # STEP 1: 모든 통계 사전 계산 (렌더링 전)
        _pre: dict = {}
        for _kw in sel_kws:
            _dn = df_period.loc[(df_period["keyword"]==_kw)&(df_period["source"]=="naver")].copy()
            _dg = df_period.loc[(df_period["keyword"]==_kw)&(df_period["source"]=="google")].copy()
            _pre[_kw]={"n":compute_kw_stats(_dn),"g":compute_kw_stats(_dg),"dn":_dn,"dg":_dg}

        # STEP 2: 렌더링 (_pre 에서만 읽기)
        def _chg_fmt(v):
            return (f"+{v:.1f}%","#059669") if v>=0 else (f"{v:.1f}%","#DC2626")

        NCOLS   = min(3,len(sel_kws)) if sel_kws else 1
        COLORS5 = ["#2F6BFF","#10B981","#F59E0B","#EF4444","#8B5CF6"]
        card_cols = st.columns(NCOLS,gap="medium")

        for idx_k,_kw in enumerate(sel_kws):
            _td  = _pre[_kw]
            _sn  = _td["n"]; _sg = _td["g"]
            _use = _sn if _sn else _sg
            _ref_df  = _td["dn"] if _sn else _td["dg"]
            _col_c   = COLORS5[idx_k%len(COLORS5)]

            with card_cols[idx_k%NCOLS]:
                with st.container(border=True):
                    st.markdown(f"<div class='tc-kw'>{_kw}</div>",unsafe_allow_html=True)

                    if not _use:
                        msg = ("데이터 부족 (최소 4주 필요)" if not _ref_df.empty
                               else "데이터 수집 대기 중" if _kw in tracked_kws else "추적 키워드 아님")
                        st.markdown(f"""<div class='tc-wait'>
<div class='tc-wait-title'>{msg}</div>
<div class='tc-wait-sub'>트렌드 데이터가 확보되면 자동으로 분석됩니다.</div></div>""",
                                    unsafe_allow_html=True)
                        continue

                    if _sn and _sg:
                        # 네이버 + 구글 양쪽 데이터 모두 있을 때: 2열 나란히 표시
                        _nc,_gc = st.columns(2)
                        with _nc:
                            nwcs,nwcc = _chg_fmt(_sn['wk_chg'])
                            nacs,nacc = _chg_fmt(_sn['avg_chg'])
                            st.markdown(f"""<div style='font-size:11px;font-weight:700;color:#2F6BFF;margin-bottom:4px'>네이버 데이터랩</div>
<div class='tc-row'>관심도 &nbsp;<strong>{_sn['current']:.0f}</strong></div>
<div class='tc-row'>전주 대비 &nbsp;<strong style='color:{nwcc}'>{nwcs}</strong></div>
<div class='tc-row'>4주 평균 &nbsp;<strong>{_sn['avg4']:.1f}</strong></div>
<div class='tc-row'>이전 4주 대비 &nbsp;<strong style='color:{nacc}'>{nacs}</strong></div>""",unsafe_allow_html=True)
                        with _gc:
                            gwcs,gwcc = _chg_fmt(_sg['wk_chg'])
                            gacs,gacc = _chg_fmt(_sg['avg_chg'])
                            st.markdown(f"""<div style='font-size:11px;font-weight:700;color:#10B981;margin-bottom:4px'>구글 트렌드</div>
<div class='tc-row'>관심도 &nbsp;<strong>{_sg['current']:.0f}</strong></div>
<div class='tc-row'>전주 대비 &nbsp;<strong style='color:{gwcc}'>{gwcs}</strong></div>
<div class='tc-row'>4주 평균 &nbsp;<strong>{_sg['avg4']:.1f}</strong></div>
<div class='tc-row'>이전 4주 대비 &nbsp;<strong style='color:{gacc}'>{gacs}</strong></div>""",unsafe_allow_html=True)
                        try:    peak_str=pd.Timestamp(_td["dn"].loc[_td["dn"]["ratio"].idxmax(),"date"]).strftime("%Y.%m.%d")
                        except: peak_str="—"
                        try:    last_str=pd.Timestamp(_td["dn"]["date"].max()).strftime("%Y.%m.%d")
                        except: last_str="—"
                        st.markdown(f"""<div class='tc-row' style='margin-top:6px'>최고점 날짜 &nbsp;<strong>{peak_str}</strong></div>
<div class='tc-row'>마지막 데이터 &nbsp;<strong>{last_str}</strong></div>
<div class='tc-row'>검색량 추세 &nbsp; {_trend_badge(_sn['trend_label'],_sn['trend_tip'])}</div>""",unsafe_allow_html=True)
                    else:
                        # 단일 소스 — 어느 소스가 있고 없는지 명확히 표시
                        if _sn:
                            _src_color = "#2F6BFF"
                            _src_lbl   = "네이버 데이터랩"
                            _miss_lbl  = "구글 트렌드"
                            _miss_reason = "검색량 부족"
                        else:
                            _src_color = "#10B981"
                            _src_lbl   = "구글 트렌드"
                            _miss_lbl  = "네이버 데이터랩"
                            _miss_reason = "데이터 없음"
                        wcs,wcc = _chg_fmt(_use['wk_chg'])
                        acs,acc = _chg_fmt(_use['avg_chg'])
                        try:    peak_str=pd.Timestamp(_ref_df.loc[_ref_df["ratio"].idxmax(),"date"]).strftime("%Y.%m.%d")
                        except: peak_str="—"
                        try:    last_str=pd.Timestamp(_ref_df["date"].max()).strftime("%Y.%m.%d")
                        except: last_str="—"
                        st.markdown(f"""
<div style='display:flex;align-items:center;gap:8px;margin-bottom:6px'>
  <span style='font-size:11px;font-weight:700;color:{_src_color}'>{_src_lbl}</span>
  <span style='font-size:10px;color:#94A3B8;background:#F1F5F9;border-radius:10px;padding:1px 7px'>{_miss_lbl}: {_miss_reason}</span>
</div>
<div class='tc-row'>관심도 &nbsp;<strong>{_use['current']:.0f}</strong></div>
<div class='tc-row'>전주 대비 &nbsp;<strong style='color:{wcc}'>{wcs}</strong></div>
<div class='tc-row'>최근 4주 평균 &nbsp;<strong>{_use['avg4']:.1f}</strong></div>
<div class='tc-row'>이전 4주 대비 &nbsp;<strong style='color:{acc}'>{acs}</strong></div>
<div class='tc-row'>최고점 날짜 &nbsp;<strong>{peak_str}</strong></div>
<div class='tc-row'>마지막 데이터 &nbsp;<strong>{last_str}</strong></div>
<div class='tc-row'>검색량 추세 &nbsp; {_trend_badge(_use['trend_label'],_use['trend_tip'])}</div>
""",unsafe_allow_html=True)

                    _sp = (_sn.get("series") if _sn and _sn.get("n",0)>=3
                           else (_sg.get("series") if _sg and _sg.get("n",0)>=3 else None))
                    if _sp is not None:
                        _sp_key=f"sp_{hashlib.md5(_kw.encode()).hexdigest()[:6]}_{idx_k}_{period_days}_{src_key}"
                        st.plotly_chart(_sparkline(_sp,_col_c),use_container_width=True,
                                        config={"displayModeBar":False},key=_sp_key)

        # 원본 데이터 보기 (collapsible_header)
        st.markdown("<div style='margin-top:.8rem'></div>",unsafe_allow_html=True)
        if collapsible_header("원본 트렌드 데이터 보기","t3_raw_exp"):
            df_raw = df_period[df_period["source"]==src_key].copy() if "df_period" in dir() and not df_period.empty else pd.DataFrame()
            if not df_raw.empty:
                df_raw["date"]=df_raw["date"].dt.strftime("%Y-%m-%d")
                st.dataframe(
                    df_raw[["keyword","date","ratio"]].rename(
                        columns={"keyword":"키워드","date":"날짜","ratio":"관심도"})
                    .sort_values("날짜",ascending=False).head(60),
                    use_container_width=True,hide_index=True)
            else:
                st.info("해당 조건에 데이터가 없습니다.")


# ════════════════════════════════════════════════════════
# TAB 4 · PR 모니터링 & 관련 뉴스 수집
# ════════════════════════════════════════════════════════
with tab4:
    # ── 세션 상태 초기화 ────────────────────────────────
    for _k, _v in [("t4_results", {}), ("t4_last_fetch", None),
                   ("t4_clusters", {}), ("t4_mon_kws", []),
                   ("t4_mon_history", []), ("mon_refresh_token", 0),
                   ("mon_cat_filter", "전체"),
                   ("mon_risk_only", False), ("mon_sort_by", "우선순위순"),
                   ("mon_review_filter", "전체")]:
        if _k not in st.session_state:
            st.session_state[_k] = _v

    def _t4_kw_add(kw: str) -> bool:
        kw = kw.strip()
        if kw and kw not in st.session_state["t4_mon_kws"] and len(st.session_state["t4_mon_kws"]) < 5:
            st.session_state["t4_mon_kws"].append(kw)
            return True
        return False

    def _pr_suggest(article_type, score, in_whitelist, title="", is_risk_priority=False,
                    category="", monitoring_reason=""):
        if is_risk_priority:
            return ("📌 SCK 직접 관련 보안 사고 — 즉시 내용 확인 및 대응 검토 필요", True)
        if category == "자사·관계사":
            return ("SCK·관계사 직접 관련 — PR 팀 검토 우선", False)
        if category == "기획기사 후보":
            hint = monitoring_reason.split(" — ")[-1] if " — " in monitoring_reason else ""
            if hint:
                return (f"기획기사 소재 검토 — {hint}", False)
            return ("기획기사 소재 검토 — 심층 분석 기사", False)
        if category == "경쟁사":
            return ("경쟁사 동향 — 시장 포지셔닝 브리핑 참고", False)
        if category == "리스크":
            return ("보안 트렌드 기사 — 이슈 모니터링 참고", False)
        if article_type == "보도자료형":
            return ("보도자료 참고용 — 직접 PR 활용은 제한적", False)
        if article_type == "인터뷰":
            return ("온드미디어 콘텐츠 소재 검토 가능", False)
        if in_whitelist and score >= 50:
            return ("주요 매체 기사 — PR 파이프라인 등록 검토", False)
        if score >= 40:
            return ("시장 동향 브리핑 참고 기사", False)
        return ("온드미디어 콘텐츠 소재 검토 가능", False)

    _tab4_sub1, _tab4_sub2 = st.tabs(["📋 오늘의 주요 기사", "🔍 키워드 직접 검색"])
    with _tab4_sub1:
        # ══════════════════════════════════════════════════════
        # ① 오늘의 PR 모니터링
        # ══════════════════════════════════════════════════════
        _mhdr_c1, _mhdr_c2 = st.columns([5, 1])
        with _mhdr_c1:
            st.markdown("""<div class="sh-main">
    <div class="t">오늘의 PR 모니터링</div>
    <div class="s">최근 24시간 기준 SCK 커뮤니케이션팀이 확인할 주요 기사</div></div>""",
                        unsafe_allow_html=True)
        with _mhdr_c2:
            st.markdown("<div style='margin-top:1.3rem'></div>", unsafe_allow_html=True)
            if st.button("새로고침", key="mon_refresh_btn", type="secondary",
                         use_container_width=True):
                st.session_state["mon_refresh_token"] += 1
                st.rerun()

        _today_key  = today_kst()
        _cfg_ver    = monitoring_config_version(_MON_CONFIG_PATH)
        _refresh_tok = st.session_state["mon_refresh_token"]

        _mon_selected  = []
        _mon_updated_at = None
        _mon_error     = False

        with st.spinner("최근 24시간 뉴스를 수집하고 있습니다. 최초 실행에는 시간이 걸릴 수 있습니다."):
            try:
                _mon_selected, _mon_updated_at, _ = _get_daily_monitoring_cached(
                    _today_key, _refresh_tok, _cfg_ver
                )
            except Exception:
                _mon_error = True

        if _mon_error:
            st.error("모니터링 수집 중 오류가 발생했습니다. "
                     "잠시 후 새로고침하거나 하단의 직접 키워드 검색을 이용해 주세요.")
        else:
            _mon_cnt = len(_mon_selected)
            _upd_str = (_mon_updated_at.strftime("%Y.%m.%d %H:%M KST")
                        if _mon_updated_at else "—")
            st.caption(f"마지막 업데이트: {_upd_str}  ·  최종 선정 {_mon_cnt}건")

            # ── ① 검토 현황 요약 (7단계) ─────────────────────────
            _mon_reviews = mrs.load_reviews()
            _rv_summary  = count_review_summary(_mon_selected, _mon_reviews)
            _rvc1, _rvc2, _rvc3, _rvc4, _rvc5 = st.columns(5)
            for _rvc, _lbl, _val in [
                (_rvc1, "전체 선정",  _rv_summary["전체"]),
                (_rvc2, "검토 완료",  _rv_summary["검토완료"]),
                (_rvc3, "관심 기사",  _rv_summary["관심 기사"]),
                (_rvc4, "PR 후보",    _rv_summary["PR 후보"]),
                (_rvc5, "제외",       _rv_summary["제외"]),
            ]:
                with _rvc:
                    st.markdown(
                        f"<div style='background:#F8FAFC;border:1px solid #E2E8F0;border-radius:8px;"
                        f"padding:8px 10px;text-align:center;margin-bottom:4px'>"
                        f"<div style='font-size:20px;font-weight:800;color:#102A43'>{_val}</div>"
                        f"<div style='font-size:11px;color:#64748B'>{_lbl}</div></div>",
                        unsafe_allow_html=True)

            if _mon_cnt < 10:
                st.info(f"최근 24시간 기준, 모니터링 기준을 통과한 기사는 총 {_mon_cnt}건입니다.")

            # ── ② 카테고리 필터 (캐시 결과에만 적용 — API 재호출 없음) ──
            _ALL_CATS = ["전체","리스크","자사·관계사","경쟁사","기획기사 후보",
                         "AI·AX 시장동향","클라우드·보안","주요 벤더","기타"]
            _cat_counts = count_by_category(_mon_selected)

            _filter_labels = []
            for _cat in _ALL_CATS:
                _cnt_c = len(_mon_selected) if _cat == "전체" else _cat_counts.get(_cat, 0)
                _filter_labels.append(f"{_cat} {_cnt_c}" if _cnt_c else _cat)

            _cur_cat = st.session_state.get("mon_cat_filter", "전체")
            _cat_sel_idx = (_ALL_CATS.index(_cur_cat) if _cur_cat in _ALL_CATS else 0)

            _cat_choice = st.radio(
                "카테고리 필터", _filter_labels,
                index=_cat_sel_idx, horizontal=True,
                key="mon_cat_radio", label_visibility="collapsed",
            )
            _cat_active = _ALL_CATS[_filter_labels.index(_cat_choice)] if _cat_choice in _filter_labels else "전체"
            if _cat_active != st.session_state["mon_cat_filter"]:
                st.session_state["mon_cat_filter"] = _cat_active

            # ── 긴급 리스크 필터 + 정렬 + 검토 상태 필터 ──────
            _frow1, _frow2, _frow3 = st.columns([4, 4, 4])
            with _frow1:
                _risk_only_val = st.checkbox(
                    "🚨 긴급 리스크만 보기", key="mon_risk_only_chk",
                    value=st.session_state.get("mon_risk_only", False))
                if _risk_only_val != st.session_state["mon_risk_only"]:
                    st.session_state["mon_risk_only"] = _risk_only_val
            with _frow2:
                _sort_opts = ["우선순위순", "PR 활용도순"]
                _sort_cur  = st.session_state.get("mon_sort_by", "우선순위순")
                _sort_sel  = st.radio(
                    "정렬", _sort_opts, horizontal=True,
                    index=(_sort_opts.index(_sort_cur) if _sort_cur in _sort_opts else 0),
                    key="mon_sort_radio", label_visibility="collapsed")
                if _sort_sel != st.session_state["mon_sort_by"]:
                    st.session_state["mon_sort_by"] = _sort_sel
            with _frow3:
                _rv_filter_opts = ["전체", "검토 전", "관심 기사", "PR 후보", "제외"]
                _rv_filter_cur  = st.session_state.get("mon_review_filter", "전체")
                _rv_filter_sel  = st.radio(
                    "검토 상태", _rv_filter_opts, horizontal=True,
                    index=(_rv_filter_opts.index(_rv_filter_cur)
                           if _rv_filter_cur in _rv_filter_opts else 0),
                    key="mon_rv_filter_radio", label_visibility="collapsed")
                if _rv_filter_sel != st.session_state["mon_review_filter"]:
                    st.session_state["mon_review_filter"] = _rv_filter_sel

            # ── 기사 카드 ─────────────────────────────────────
            _ranked = apply_category_filter(_mon_selected, _cat_active)
            _ranked = apply_urgency_filter(_ranked, st.session_state.get("mon_risk_only", False))
            _ranked = apply_review_filter(_ranked, st.session_state.get("mon_review_filter", "전체"),
                                          _mon_reviews)
            _ranked = sort_monitoring_articles(_ranked, st.session_state.get("mon_sort_by", "우선순위순"))

            if not _ranked:
                st.caption("해당 조건에 선정된 기사가 없습니다.")
            else:
                _CAT_STYLE = {
                    "리스크":       ("#FEF3C7","#92400E"),
                    "자사·관계사":  ("#EDE9FE","#5B21B6"),
                    "경쟁사":       ("#FDF4FF","#7e22ce"),
                    "기획기사 후보":("#ECFDF5","#065F46"),
                    "AI·AX 시장동향":("#EFF6FF","#1E40AF"),
                    "클라우드·보안":("#F0FDF4","#166534"),
                    "주요 벤더":    ("#F1F5F9","#475569"),
                    "기타":         ("#F1F5F9","#475569"),
                }
                for _rank, _art in _ranked:
                    _mon_url     = _art.get("url", "")
                    _mon_ak      = make_widget_key("monitoring_util", _mon_url or f"no_url_{_rank}")
                    _mon_ttl     = _art.get("title", "") or ""
                    _mon_mn      = _art.get("media_name", "") or ""
                    _mon_dt      = _art.get("pub_datetime", "") or ""
                    _mon_at      = _art.get("article_type", "") or ""
                    _mon_cat     = _art.get("_monitoring_category", "기타") or "기타"
                    _mon_rl      = _art.get("_relevance_level", "") or ""
                    _mon_rws     = _art.get("_relevance_reasons", []) or []
                    _mon_why     = _art.get("_monitoring_reason", "") or ""
                    _mon_sc      = _art.get("score", 0) or 0
                    _mon_wl      = _art.get("_in_whitelist", False)
                    _mon_pri     = _art.get("_monitoring_priority", 0) or 0
                    _mon_prscore = _art.get("_pr_value_score", 0) or 0
                    _mon_rsc     = _art.get("_relevance_score", 0) or 0
                    _mon_mqs     = _art.get("_matched_queries", []) or []
                    _mon_mgs     = _art.get("_matched_groups", []) or []
                    _mon_is_risk = _art.get("_is_risk_priority", False)

                    # 긴급 리스크는 붉은 배지, 일반 보안 트렌드는 기존 앰버색 유지
                    _base_cat_bg, _base_cat_fg = _CAT_STYLE.get(_mon_cat, ("#F1F5F9","#475569"))
                    if _mon_cat == "리스크" and _mon_is_risk:
                        _cat_bg, _cat_fg = "#FEE2E2", "#991B1B"
                    else:
                        _cat_bg, _cat_fg = _base_cat_bg, _base_cat_fg
                    _rl_cls = {"높음":"rel-high","보통":"rel-mid","낮음":"rel-low"}.get(_mon_rl,"rel-mid")

                    with st.container(border=True):
                        # 순위 + 카테고리 + 긴급 배지 + 관련성 배지 행
                        _badge_parts = [
                            f"<span style='font-size:13px;font-weight:800;color:#102A43'>#{_rank}</span>",
                            f"<span style='display:inline-block;background:{_cat_bg};color:{_cat_fg};"
                            f"border-radius:4px;padding:2px 7px;font-size:11px;font-weight:700'>{_mon_cat}</span>",
                        ]
                        if _mon_is_risk:
                            _badge_parts.append(
                                "<span style='display:inline-block;background:#DC2626;color:#fff;"
                                "border-radius:4px;padding:2px 7px;font-size:11px;font-weight:700'>"
                                "📌 주목 이슈</span>")
                        if _mon_rl in ("높음", "보통"):
                            _badge_parts.append(f"<span class='{_rl_cls}'>관련성 {_mon_rl}</span>")
                        st.markdown(" ".join(_badge_parts), unsafe_allow_html=True)

                        # 제목
                        if _mon_url:
                            st.markdown(f"**[{_mon_ttl}]({_mon_url})**")
                        else:
                            st.markdown(f"**{_mon_ttl or '(제목 없음)'}**")

                        # 메타 (매체 · 발행시간 · 점수 요약)
                        _meta_parts = [p for p in [_mon_mn, _mon_dt] if p]
                        if _meta_parts:
                            st.markdown(f"<span class='art-meta'>{' · '.join(_meta_parts)}</span>",
                                        unsafe_allow_html=True)
                        # 4축 분류 표시: 기사유형 / SCK관련성 / PR목적 / 주목도
                        _pr_purpose_map = {
                            "기획기사 후보": "기획기사 소재",
                            "리스크": "리스크 모니터링",
                            "자사·관계사": "자사 PR 대응",
                            "경쟁사": "경쟁사 분석",
                            "AI·AX 시장동향": "시장 동향 파악",
                            "클라우드·보안": "기술 동향 파악",
                            "주요 벤더": "벤더 동향 파악",
                        }
                        _pr_purpose = _pr_purpose_map.get(_mon_cat, "참고용")
                        _attention = "높음" if _mon_prscore >= 70 else "보통" if _mon_prscore >= 45 else "낮음"
                        _axis_html = (
                            f"<div style='font-size:11px;color:#64748B;margin:3px 0;line-height:1.7'>"
                            f"<b>기사유형</b> {_mon_at or '—'} &nbsp;│&nbsp; "
                            f"<b>SCK관련성</b> {_mon_rl or '—'} &nbsp;│&nbsp; "
                            f"<b>PR목적</b> {_pr_purpose} &nbsp;│&nbsp; "
                            f"<b>주목도</b> {_attention}"
                            f"</div>"
                        )
                        st.markdown(_axis_html, unsafe_allow_html=True)

                        # 판정 신뢰도 (콘텐츠 기반 — SCK 관련성과 무관)
                        _confidence = _mon_art.get("_confidence", "")
                        if _confidence:
                            _conf_color = {"높음": "#166534", "보통": "#92400E", "낮음": "#991B1B"}
                            _conf_bg    = {"높음": "#DCFCE7", "보통": "#FEF3C7", "낮음": "#FEE2E2"}
                            _conf_icon  = {"높음": "✅", "보통": "ℹ️", "낮음": "⚠️"}
                            _conf_note  = {"높음": "본문 미확보 — 제목·요약 기반 분류 (콘텐츠 충분)",
                                           "보통": "본문 미확보 — 제목·요약 기반 분류 (콘텐츠 보통)",
                                           "낮음": "본문 미확보 — 제목·요약만 확보 (판정 신뢰도 낮음)"}
                            st.markdown(
                                f"<div style='font-size:11px;color:{_conf_color.get(_confidence,\"#374151\")};background:{_conf_bg.get(_confidence,\"#F3F4F6\")};padding:3px 7px;border-radius:4px;margin:3px 0'>"
                                f"{_conf_icon.get(_confidence,'')} 판정 신뢰도 <b>{_confidence}</b> — {_conf_note.get(_confidence,'')}"
                                f"</div>",
                                unsafe_allow_html=True)

                        st.markdown(
                            f"<span class='art-meta' style='font-size:11.5px'>"
                            f"뉴스중요도 <b>{_mon_sc}</b> &nbsp;·&nbsp; PR활용도 <b>{_mon_prscore}</b>"
                            f"</span>",
                            unsafe_allow_html=True)

                        # 선정 이유
                        if _mon_why:
                            st.markdown(
                                f"<div style='font-size:12.5px;color:#344054;margin:4px 0;line-height:1.5'>"
                                f"📌 {_mon_why}</div>",
                                unsafe_allow_html=True)

                        # PR 활용 제안 (monitoring.py _is_risk_priority를 단일 기준으로 사용)
                        _sug, _is_risk_sug = _pr_suggest(
                            _mon_at, _mon_sc, _mon_wl, _mon_ttl, _mon_is_risk,
                            category=_mon_cat, monitoring_reason=_mon_why)
                        _sug_cls = "art-suggest risk" if _is_risk_sug else "art-suggest"
                        st.markdown(f"<span class='{_sug_cls}'>💡 {_sug}</span>",
                                    unsafe_allow_html=True)

                        # 판정 근거 (expander) — 9축 세부 점수 포함
                        with st.expander("판정 근거 및 세부 점수 보기"):
                            _dc1, _dc2 = st.columns(2)
                            with _dc1:
                                st.markdown(f"**모니터링 우선순위**: {_mon_pri}")
                                st.markdown(f"**뉴스 중요도**: {_mon_sc}")
                                st.markdown(f"**PR 활용도(합계)**: {_mon_prscore}")
                                st.markdown(f"**판정 신뢰도**: {_confidence or '—'}")
                            with _dc2:
                                st.markdown(f"**수집 검색어**: {', '.join(_mon_mqs) if _mon_mqs else '—'}")
                                st.markdown(f"**수집 영역**: {', '.join(_mon_mgs) if _mon_mgs else '—'}")
                                if _mon_rws:
                                    st.markdown(f"**판정 근거**: {' · '.join(_mon_rws[:3])}")
                            # 9축 세부 점수 표시
                            _axes = _mon_art.get("_score_axes")
                            if _axes:
                                st.markdown("**세부 점수 (9평가축)**")
                                _ax_rows = [
                                    ("① SCK 사업 관련성", _axes.get("sck_relevance", 0), 25),
                                    ("② 산업 인사이트",   _axes.get("industry_insight", 0), 25),
                                    ("③ 근거 구체성",     _axes.get("evidence_quality", 0), 20),
                                    ("④ PR 기획 확장성",  _axes.get("pr_expandability", 0), 15),
                                    ("⑤ 기사 품질·객관성",_axes.get("article_quality", 0), 10),
                                    ("⑥ 최신성",         _axes.get("recency", 0), 5),
                                ]
                                _ax_html = "<table style='font-size:11px;width:100%;border-collapse:collapse'>"
                                for _ax_name, _ax_val, _ax_max in _ax_rows:
                                    _ax_pct = int(_ax_val / _ax_max * 100) if _ax_max else 0
                                    _ax_html += (
                                        f"<tr><td style='padding:1px 4px;width:45%'>{_ax_name}</td>"
                                        f"<td style='width:30px;text-align:right'><b>{_ax_val}</b>/{_ax_max}</td>"
                                        f"<td style='padding:0 6px;width:60%'>"
                                        f"<div style='background:#E5E7EB;border-radius:3px;height:8px'>"
                                        f"<div style='background:#3B82F6;width:{_ax_pct}%;height:8px;border-radius:3px'></div>"
                                        f"</div></td></tr>"
                                    )
                                # 감점 행
                                _ded_pr  = _axes.get("deduct_pr", 0)
                                _ded_ctx = _axes.get("deduct_context", 0)
                                _ded_dup = _axes.get("deduct_duplicate", 0)
                                if _ded_pr or _ded_ctx or _ded_dup:
                                    _ax_html += f"<tr><td colspan='3' style='padding-top:4px;font-weight:bold'>감점</td></tr>"
                                    if _ded_pr:  _ax_html += f"<tr><td style='padding:1px 4px;color:#DC2626'>보도자료성</td><td style='color:#DC2626;text-align:right'>{_ded_pr}</td><td></td></tr>"
                                    if _ded_ctx: _ax_html += f"<tr><td style='padding:1px 4px;color:#DC2626'>문맥 관련성 부족</td><td style='color:#DC2626;text-align:right'>{_ded_ctx}</td><td></td></tr>"
                                    if _ded_dup: _ax_html += f"<tr><td style='padding:1px 4px;color:#DC2626'>중복·홍보성</td><td style='color:#DC2626;text-align:right'>{_ded_dup}</td><td></td></tr>"
                                _ax_html += "</table>"
                                st.markdown(_ax_html, unsafe_allow_html=True)
                            # 품질 요소 판정
                            _qf = _mon_art.get("_quality_factors")
                            if _qf:
                                _qf_labels = {
                                    "industry_change":  "변화·현상 감지",
                                    "cause_background": "원인·배경 포함",
                                    "business_impact":  "기업 영향 언급",
                                    "data_statistics":  "수치·통계 존재★",
                                    "multiple_cases":   "복수 사례",
                                    "expert_source":    "전문가·외부 근거",
                                    "pr_expandability": "기획 확장 가능성",
                                    "is_promotional":   "홍보·보도자료 중심★",
                                }
                                _qf_parts = []
                                for _qk, _qlabel in _qf_labels.items():
                                    _qv = _qf.get(_qk)
                                    if _qv is None:
                                        _qf_parts.append(f"<span style='color:#9CA3AF'>{_qlabel}: 판단불가</span>")
                                    elif _qv:
                                        _qf_parts.append(f"<span style='color:#16A34A'>✓ {_qlabel}</span>")
                                    else:
                                        _qf_parts.append(f"<span style='color:#9CA3AF'>✗ {_qlabel}</span>")
                                st.markdown(
                                    "<div style='font-size:11px;margin-top:6px'><b>품질 요소 판정</b><br>"
                                    + " &nbsp;│&nbsp; ".join(_qf_parts)
                                    + "<br><small>★=패턴 기반(신뢰도 高), 그 외=단어 등장 여부</small></div>",
                                    unsafe_allow_html=True)

                        # 액션 버튼 행
                        _mba, _mbb = st.columns([1, 1])
                        with _mba:
                            if _mon_url:
                                st.link_button("기사 원문", _mon_url, use_container_width=True)
                        with _mbb:
                            _mon_reg_k = f"mon_reg_open_{_mon_ak}"
                            if _mon_reg_k not in st.session_state:
                                st.session_state[_mon_reg_k] = False
                            if st.button("활용처 등록", key=f"{_mon_ak}_regbtn",
                                         use_container_width=True, type="primary"):
                                st.session_state[_mon_reg_k] = not st.session_state[_mon_reg_k]
                                st.rerun()

                        # 활용처 등록 인라인 폼
                        if st.session_state.get(_mon_reg_k, False):
                            _sel_m = st.selectbox(
                                "활용처", NEWS_UTIL_USAGES,
                                key=f"{_mon_ak}_usage",
                                label_visibility="collapsed")
                            _memo_m = st.text_input(
                                "메모", key=f"{_mon_ak}_memo",
                                placeholder="관련 메모 (선택 사항)",
                                label_visibility="collapsed")
                            _mcs1, _mcs2 = st.columns([1, 1])
                            with _mcs1:
                                if st.button("저장", key=f"{_mon_ak}_save",
                                             type="primary", use_container_width=True):
                                    _kw_m = _art.get("_source_query", "")
                                    add_news_util(_mon_ttl, _mon_url, _mon_mn,
                                                  _art.get("pub_date", ""), _kw_m, _sel_m, _memo_m)
                                    if _sel_m in ("PR 파이프라인 소재", "온드미디어 소재"):
                                        _ctype_m = "PR 기사" if "PR" in _sel_m else "온드미디어"
                                        if add_content(_kw_m, CURRENT_MONTH, _ctype_m,
                                                       _mon_ttl, _mon_url, _art.get("pub_date","")):
                                            _inv_content(); _inv_derived()
                                    st.session_state[_mon_reg_k] = False
                                    st.toast(f"등록됨 — {_sel_m}")
                                    st.rerun()
                            with _mcs2:
                                if st.button("취소", key=f"{_mon_ak}_cancel",
                                             type="secondary", use_container_width=True):
                                    st.session_state[_mon_reg_k] = False
                                    st.rerun()

                        # ── 검토 결과 기록 (7단계) ──────────────────────────
                        _art_id = mrs.make_article_id(
                            _mon_url, _mon_ttl, _mon_mn, _art.get("pub_date", ""))
                        _existing_rv = _mon_reviews.get(_art_id, {})

                        _rs_key = f"{_mon_ak}_rv_status"
                        _ut_key = f"{_mon_ak}_rv_usage"
                        _ex_key = f"{_mon_ak}_rv_exclusion"
                        _fu_key = f"{_mon_ak}_rv_follow"
                        _rm_key = f"{_mon_ak}_rv_memo"
                        if _rs_key not in st.session_state:
                            st.session_state[_rs_key] = _existing_rv.get("review_status", "검토 전")
                        if _ut_key not in st.session_state:
                            st.session_state[_ut_key] = _existing_rv.get("usage_type", "추가 검토")
                        if _ex_key not in st.session_state:
                            _ex_saved = _existing_rv.get("exclusion_reason", "")
                            st.session_state[_ex_key] = (
                                _ex_saved if _ex_saved in mrs.EXCLUSION_REASONS
                                else mrs.EXCLUSION_REASONS[0])
                        if _fu_key not in st.session_state:
                            st.session_state[_fu_key] = _existing_rv.get("follow_up_required", "")
                        if _rm_key not in st.session_state:
                            st.session_state[_rm_key] = _existing_rv.get("reviewer_memo", "")

                        _rv_saved = bool(_existing_rv)
                        _rv_exp_label = (
                            f"📝 검토 결과 기록 [{st.session_state[_rs_key]}]"
                            if _rv_saved else "📝 검토 결과 기록")

                        with st.expander(_rv_exp_label, expanded=False):
                            _rv_status_sel = st.selectbox(
                                "검토 상태",
                                mrs.REVIEW_STATUSES,
                                key=_rs_key)

                            _is_pr_candidate = (_rv_status_sel == "PR 후보")
                            _is_excluded     = (_rv_status_sel == "제외")
                            if _is_pr_candidate:
                                _rv_usage_sel  = st.selectbox(
                                    "활용 형태",
                                    mrs.USAGE_TYPES,
                                    key=_ut_key)
                                _rv_excl_sel   = ""
                                _rv_follow_val = st.text_area(
                                    "후속 확인 사항",
                                    key=_fu_key,
                                    placeholder="예: 현업 인터뷰 필요, 관련 매출 수치 확인",
                                    height=80)
                            elif _is_excluded:
                                _rv_usage_sel  = ""
                                _rv_excl_sel   = st.selectbox(
                                    "제외 사유",
                                    mrs.EXCLUSION_REASONS,
                                    key=_ex_key)
                                _rv_follow_val = ""
                            else:
                                _rv_usage_sel  = ""
                                _rv_excl_sel   = ""
                                _rv_follow_val = ""

                            _rv_memo_val = st.text_area(
                                "담당자 메모",
                                key=_rm_key,
                                placeholder="자유 메모",
                                height=80)

                            if _rv_saved:
                                st.caption(
                                    f"저장일시: {_existing_rv.get('reviewed_at', '—')}")

                            if st.button("저장", key=f"{_mon_ak}_rv_save",
                                         type="primary", use_container_width=True):
                                _rv_data = {
                                    "article_id":            _art_id,
                                    "title":                 _mon_ttl,
                                    "url":                   _mon_url,
                                    "media":                 _mon_mn,
                                    "published_at":          _mon_dt,
                                    "category":              _mon_cat,
                                    "monitoring_priority":   str(_mon_pri),
                                    "relevance_score":       str(_mon_rsc),
                                    "news_importance_score": str(_mon_sc),
                                    "pr_usability_score":    str(_mon_prscore),
                                    "selection_reason":      _mon_why,
                                    "pr_suggestion":         _sug,
                                    "review_status":         _rv_status_sel,
                                    "usage_type":            _rv_usage_sel,
                                    "exclusion_reason":      _rv_excl_sel,
                                    "follow_up_required":    _rv_follow_val,
                                    "reviewer_memo":         _rv_memo_val,
                                }
                                _ok, _err = mrs.save_review(_rv_data)
                                if _ok:
                                    st.toast(f"저장됨 — {_rv_status_sel}")
                                    st.rerun()
                                else:
                                    st.error(f"저장 실패: {_err}")

    with _tab4_sub2:
        st.markdown("""<div class='sh-main'>
<div class='t'>키워드 직접 검색</div>
<div class='s'>기사화·기획기사 개발을 위한 직접 키워드 검색</div></div>""",
                    unsafe_allow_html=True)


        # 요약 지표 카드
        _t4_res_cur = st.session_state.get("t4_results", {})
        _t4_cl_cur  = st.session_state.get("t4_clusters", {})
        _stat_kws   = len(_t4_res_cur)
        _stat_raw   = sum(v.get("raw_count", 0)       for v in _t4_res_cur.values())
        _stat_filt  = sum(v.get("filtered_count", 0)   for v in _t4_res_cur.values())
        _stat_sel   = sum(len(v)                       for v in _t4_cl_cur.values())
        _stat_util  = count_news_util()
        _sc1,_sc2,_sc3,_sc4,_sc5 = st.columns(5)
        for _sc,_num,_lbl in [(_sc1,_stat_kws,"수집 키워드"),(_sc2,_stat_raw,"원본 기사"),
                               (_sc3,_stat_filt,"중복 제거 후"),(_sc4,_stat_sel,"선별 기사"),
                               (_sc5,_stat_util,"활용처 등록")]:
            with _sc:
                st.markdown(f"<div class='news-stat-card'><div class='news-stat-num'>{_num}</div>"
                            f"<div class='news-stat-lbl'>{_lbl}</div></div>",
                            unsafe_allow_html=True)
        st.markdown("<div style='margin-bottom:1rem'></div>", unsafe_allow_html=True)

        # 조회 조건 설정
        with st.expander("🔧 조회 조건 설정", expanded=not bool(_t4_res_cur)):
            st.markdown("""<p style='font-size:13px;font-weight:700;color:#344054;margin:0 0 4px'>
    분석 키워드 <span style='font-size:11px;font-weight:400;color:#94A3B8'>최대 5개 · 키워드별 독립 검색(OR) 후 결과 종합 표시</span></p>""",
                        unsafe_allow_html=True)

            _mon_kws = st.session_state["t4_mon_kws"]
            if _mon_kws:
                _chip_cols = st.columns(5)
                for _ci, _ckw in enumerate(_mon_kws):
                    with _chip_cols[_ci]:
                        if st.button(f"× {_ckw}", key=f"t4_rm_{_ci}",
                                     type="primary", use_container_width=True):
                            st.session_state["t4_mon_kws"].pop(_ci); st.rerun()

            if len(_mon_kws) < 5:
                with st.form("t4_kw_add_form", clear_on_submit=True, border=False):
                    _fi1, _fi2 = st.columns([8, 1])
                    with _fi1:
                        _new_kw = st.text_input("키워드 입력",
                                                placeholder="키워드 입력 후 Enter 또는 추가 클릭",
                                                label_visibility="collapsed")
                    with _fi2:
                        _kw_add_btn = st.form_submit_button("추가", use_container_width=True)
                if _kw_add_btn and _new_kw.strip():
                    _t4_kw_add(_new_kw); st.rerun()

            _imp_col, _hist_col = st.columns([3, 7])
            with _imp_col:
                if st.button("↓ 트렌드 탭 키워드 불러오기", key="t4_mon_import",
                             use_container_width=True, type="secondary"):
                    for _tk in load_tracked_keywords():
                        _t4_kw_add(_tk)
                    st.rerun()
            with _hist_col:
                _hist = st.session_state["t4_mon_history"]
                if _hist:
                    st.markdown("<span style='font-size:11.5px;color:#667085'>최근 검색: </span>",
                                unsafe_allow_html=True)
                    _hc = st.columns(min(5, len(_hist)))
                    for _hi, _hkw in enumerate(_hist[:5]):
                        with _hc[_hi]:
                            if st.button(_hkw, key=f"t4_hist_{_hi}", type="secondary",
                                         use_container_width=True):
                                _t4_kw_add(_hkw); st.rerun()

            st.markdown("<hr style='margin:.5rem 0 .8rem'>", unsafe_allow_html=True)

            t4_days = st.radio("조회 기간", ["최근 7일", "최근 14일", "최근 30일"],
                               horizontal=True, key="t4_days_r")
            _fc, _fd, _fe = st.columns([3, 3, 3])
            with _fc: t4_scope = st.selectbox("언론사 범위", ["주요 제휴·우선 매체만", "전체 뉴스 검색 결과"], key="t4_scope")
            with _fd: t4_type  = st.selectbox("기사 유형", ["전체","보도자료형","기획·분석","인터뷰","행사·현장","일반 기사"], key="t4_type")
            with _fe: t4_sort  = st.selectbox("정렬", ["추천순","화제성순","최신순"], key="t4_sort")

            st.caption("※ 화제성 추정 점수는 매체 우선순위, 키워드 포함도, 최신성, 중복 보도 여부 등을 기준으로 산출한 내부 참고 지표입니다. 실제 기사 영향력 또는 PR 성과로 단정하지 않습니다.")

            _btn_a, _btn_b = st.columns([3, 1])
            _t4_cur_kws = st.session_state["t4_mon_kws"]
            with _btn_a:
                t4_fetch = st.button("기사 불러오기", type="primary", use_container_width=True,
                                     key="t4_fetch_btn", disabled=not _t4_cur_kws)
            with _btn_b:
                t4_reset = st.button("결과 지우기", type="secondary", use_container_width=True, key="t4_rf_btn")
            _last_f = st.session_state.get("t4_last_fetch")
            if _last_f:
                _last_str = _last_f.strftime("%Y.%m.%d %H:%M") if hasattr(_last_f, "strftime") else str(_last_f)
                st.caption(f"마지막 업데이트 {_last_str} KST")
            else:
                st.caption("키워드를 입력한 뒤 '기사 불러오기'를 눌러주세요.")

        if t4_reset:
            st.session_state["t4_results"]   = {}
            st.session_state["t4_clusters"]  = {}
            st.session_state["t4_last_fetch"] = None
            st.rerun()

        if t4_fetch and _t4_cur_kws:
            days_map  = {"최근 7일": 7, "최근 14일": 14, "최근 30일": 30}
            n_days    = days_map.get(t4_days, 7)
            date_to   = datetime.now().strftime("%Y-%m-%d")
            date_from = (datetime.now() - timedelta(days=n_days)).strftime("%Y-%m-%d")
            sort_api  = "date" if t4_sort == "최신순" else "sim"
            scope_key = "whitelist" if "주요" in t4_scope else "all"
            type_f    = "" if t4_type == "전체" else t4_type
            cid, csc  = _get_naver_creds()
            new_results = {}; new_clusters = {}
            prog = st.progress(0, "기사 수집 중…")
            for i, kw in enumerate(_t4_cur_kws):
                prog.progress(i / max(len(_t4_cur_kws), 1),
                              f"'{kw}' 기사 수집 중 ({i+1}/{len(_t4_cur_kws)})")
                _res = nf.fetch_articles_for_keyword(
                    keyword=kw, date_from=date_from, date_to=date_to,
                    sort_api=sort_api, media_scope=scope_key,
                    article_type_filter=type_f, cid=cid, csc=csc,
                    media_config=MEDIA_CFG, display=100)
                new_results[kw] = _res
                new_clusters[kw] = (nf.process_and_score(_res["articles"], MEDIA_CFG, t4_sort)
                                    if _res["status"] == "success" and _res["articles"] else [])
            prog.progress(1.0, "완료")
            now_kst = datetime.now(timezone.utc) + timedelta(hours=9)
            st.session_state["t4_results"]    = new_results
            st.session_state["t4_clusters"]   = new_clusters
            st.session_state["t4_last_fetch"] = now_kst
            for _hkw in _t4_cur_kws:
                if _hkw in st.session_state["t4_mon_history"]:
                    st.session_state["t4_mon_history"].remove(_hkw)
                st.session_state["t4_mon_history"].insert(0, _hkw)
            st.session_state["t4_mon_history"] = st.session_state["t4_mon_history"][:10]
            st.rerun()

        t4_res      = st.session_state.get("t4_results", {})
        t4_clusters = st.session_state.get("t4_clusters", {})

        if not t4_clusters:
            st.markdown("""<div class='notice-box'>
    키워드를 입력하거나 트렌드 키워드를 불러온 뒤 기사보기를 실행해 주세요.
    수집된 기사는 중복 제거 후 PR 활용 가능성이 높은 기사 중심으로 선별됩니다.
    </div>""", unsafe_allow_html=True)
        else:
            # 인사이트 자동 요약
            _kw_cnt_map = {kw: len(cls) for kw, cls in t4_clusters.items() if cls}
            _wl_total   = sum(1 for cls in t4_clusters.values()
                              for cl in cls if cl["rep"].get("_in_whitelist"))
            _all_cl     = sum(len(v) for v in t4_clusters.values())
            _reg_cand   = sum(1 for cls in t4_clusters.values()
                              for cl in cls if cl["rep"].get("_score", 0) >= 50)
            if _kw_cnt_map:
                _top_kw = max(_kw_cnt_map, key=_kw_cnt_map.get)
                _wl_pct = round(_wl_total / max(_all_cl, 1) * 100)
                _ins_parts = []
                if len(_kw_cnt_map) > 1:
                    _ins_parts.append(f"<b>{_top_kw}</b> 관련 기사가 가장 많이 선별됐습니다 ({_kw_cnt_map[_top_kw]}건)")
                if _wl_pct > 0:
                    _ins_parts.append(f"주요 매체 비율 <b>{_wl_pct}%</b>")
                if _reg_cand > 0:
                    _ins_parts.append(f"PR 활용 후보 <b>{_reg_cand}건</b> 확인")
                if _ins_parts:
                    st.markdown(f"<div class='insight-bar'>{'  ·  '.join(_ins_parts)}</div>",
                                unsafe_allow_html=True)

            STATUS_MSG = {"auth_missing":"API 키 설정 필요","auth_failed":"API 인증 실패",
                          "rate_limit":"API 호출 한도 초과","timeout":"응답 시간 초과",
                          "api_error":"API 오류","exception":"수집 중 오류 발생"}

            for kw, clusters in t4_clusters.items():
                _res    = t4_res.get(kw, {})
                _status = _res.get("status", "")
                _err    = _res.get("error", "")
                cnt_str = (f"{_res.get('filtered_count',0)}건 선별" if _status == "success"
                           else f"<span class='art-status-err'>{STATUS_MSG.get(_status, _status)}</span>")
                st.markdown(
                    f"<div style='font-size:1rem;font-weight:800;color:#101828;padding:.8rem 0 .4rem'>"
                    f"{kw} &nbsp;<span style='font-size:13px;font-weight:400;color:#667085'>{cnt_str}</span>"
                    f"{'  · '+_err if _err else ''}</div>", unsafe_allow_html=True)
                if not clusters:
                    if _status == "success":
                        st.caption("해당 키워드·조건에 맞는 기사가 없습니다.")
                    continue

                main_cls = [cl for cl in clusters
                            if cl["rep"].get("_relevance_level", "보통") != "낮음"]
                low_cls  = [cl for cl in clusters
                            if cl["rep"].get("_relevance_level", "보통") == "낮음"]

                for ci in range(0, len(main_cls), 2):
                    batch_cl = main_cls[ci:ci+2]
                    card_c   = st.columns(len(batch_cl), gap="medium")
                    for col, cl in zip(card_c, batch_cl):
                        rep    = cl["rep"]
                        others = [a for a in cl["cluster"] if a["url"] != rep["url"]]
                        _url_base = nf.article_key(rep.get("url","") or f"no_url_{ci}")
                        # direct search prefix: manual_util_
                        ak = make_widget_key("manual_util", f"{kw}::{ci}::{_url_base}")
                        with col:
                            with st.container(border=True):
                                at  = rep.get("article_type", "")
                                sc  = rep.get("_score", 0)
                                wl  = rep.get("_in_whitelist", False)
                                ttl = rep.get("title", "")
                                url = rep.get("url", "")
                                mn  = rep.get("media_name", "")
                                dt_s= rep.get("pub_datetime", "")
                                cls_= cl["size"]

                                badges = [f"<span class='art-kw'>{rep.get('search_keyword','')}</span>"]
                                if at:  badges.append(_art_type_html(at))
                                if wl:  badges.append("<span class='art-media'>주요 매체</span>")
                                badges.append(
                                    f"<span class='art-score' title='내부 참고 지표 — 키워드 관련성, 관련 보도 수, 매체 우선등급, 최신성을 종합'>"
                                    f"화제성 추정 {sc}점</span>")
                                st.markdown(" ".join(badges), unsafe_allow_html=True)

                                _rl  = rep.get("_relevance_level", "")
                                _rt  = rep.get("_relevance_type", "")
                                _rws = rep.get("_relevance_reasons", [])
                                if _rl:
                                    _rl_cls = {"높음":"rel-high","보통":"rel-mid","낮음":"rel-low"}.get(_rl,"rel-mid")
                                    _rel_html = (
                                        f"<span class='{_rl_cls}'>SCK 관련성: {_rl}</span>"
                                        + (f"<span class='rel-type'>{_rt}</span>" if _rt and _rt != "일반" else "")
                                    )
                                    st.markdown(_rel_html, unsafe_allow_html=True)
                                    if _rws:
                                        st.markdown(
                                            f"<div class='rel-why'>근거: {' · '.join(_rws[:3])}</div>",
                                            unsafe_allow_html=True)

                                if url: st.markdown(f"**[{ttl}]({url})**")
                                else:   st.markdown(f"**{ttl}**")

                                meta_parts = [p for p in [mn, dt_s] if p]
                                cl_str = f" · 관련 보도 {cls_}건" if cls_ > 1 else ""
                                st.markdown(f"<span class='art-meta'>{' · '.join(meta_parts)}{cl_str}</span>",
                                            unsafe_allow_html=True)

                                dsc = rep.get("description", "")
                                if dsc:
                                    st.markdown(f"<div class='art-desc'>{dsc[:250]}</div>",
                                                unsafe_allow_html=True)

                                _suggest, _is_risk = _pr_suggest(at, sc, wl, ttl)
                                _sug_cls = "art-suggest risk" if _is_risk else "art-suggest"
                                st.markdown(f"<span class='{_sug_cls}'>💡 {_suggest}</span>",
                                            unsafe_allow_html=True)

                                if others:
                                    show_key = f"t4_rel_{ak}"
                                    if show_key not in st.session_state:
                                        st.session_state[show_key] = False
                                    rel_icon = "▲" if st.session_state[show_key] else "▼"
                                    if st.button(f"관련 보도 {len(others)}건 {rel_icon}",
                                                 key=f"t4_rel_btn_{ak}", type="secondary",
                                                 use_container_width=True):
                                        st.session_state[show_key] = not st.session_state[show_key]
                                        st.rerun()
                                    if st.session_state[show_key]:
                                        for oa in others[:6]:
                                            ourl=oa.get("url",""); ottl=oa.get("title","")
                                            omn=oa.get("media_name",""); odt=oa.get("pub_date","")
                                            st.markdown(f"• [{omn}: {ottl}]({ourl}) — {odt}" if ourl
                                                        else f"• {omn}: {ottl} — {odt}")

                                _ba, _bb = st.columns([1, 1])
                                with _ba:
                                    if url: st.link_button("기사 원문", url, use_container_width=True)
                                with _bb:
                                    _reg_open_k = f"t4_reg_open_{ak}"
                                    if _reg_open_k not in st.session_state:
                                        st.session_state[_reg_open_k] = False
                                    if st.button("활용처 등록", key=f"t4_reg_{ak}",
                                                 use_container_width=True, type="primary"):
                                        st.session_state[_reg_open_k] = not st.session_state[_reg_open_k]
                                        st.rerun()

                                if st.session_state.get(_reg_open_k, False):
                                    _sel = st.selectbox(
                                        "활용처", NEWS_UTIL_USAGES,
                                        key=f"t4_sel_usage_{ak}",
                                        label_visibility="collapsed")
                                    _memo_v = st.text_input(
                                        "메모", key=f"t4_memo_{ak}",
                                        placeholder="관련 메모 (선택 사항)",
                                        label_visibility="collapsed")
                                    _cs1, _cs2 = st.columns([1, 1])
                                    with _cs1:
                                        if st.button("저장", key=f"t4_reg_save_{ak}",
                                                     type="primary", use_container_width=True):
                                            kw_t = rep.get("search_keyword", "")
                                            add_news_util(ttl, url, mn,
                                                          rep.get("pub_date",""),
                                                          kw_t, _sel, _memo_v)
                                            if _sel in ("PR 파이프라인 소재", "온드미디어 소재"):
                                                ctype = "PR 기사" if "PR" in _sel else "온드미디어"
                                                if add_content(kw_t, CURRENT_MONTH, ctype,
                                                               ttl, url, rep.get("pub_date","")):
                                                    _inv_content(); _inv_derived()
                                            st.session_state[_reg_open_k] = False
                                            st.toast(f"등록됨 — {_sel}")
                                            st.rerun()
                                    with _cs2:
                                        if st.button("취소", key=f"t4_reg_cancel_{ak}",
                                                     type="secondary", use_container_width=True):
                                            st.session_state[_reg_open_k] = False
                                            st.rerun()

                if low_cls:
                    with st.expander(f"관련성 낮은 기사 {len(low_cls)}건 (펼쳐보기)"):
                        st.caption("SCK 사업 맥락과 직접 연결되지 않아 주요 목록에서 제외된 기사입니다.")
                        for _lcl in low_cls:
                            _lr  = _lcl["rep"]
                            _ltl = _lr.get("title", "")
                            _lu  = _lr.get("url", "")
                            _lmn = _lr.get("media_name", "")
                            _ldt = _lr.get("pub_date", "")
                            _lrr = _lr.get("_low_relevance_reason", "")
                            _lsz = _lcl["size"]
                            _meta = " · ".join(p for p in [_lmn, _ldt] if p)
                            if _lsz > 1: _meta += f" · 관련 보도 {_lsz}건"
                            _reason_txt = f"  ({_lrr})" if _lrr else ""
                            st.markdown(
                                (f"• **[{_ltl}]({_lu})**  " if _lu else f"• **{_ltl}**  ") +
                                f"\n  <span style='font-size:11px;color:#94A3B8'>{_meta}</span>"
                                f"<span style='font-size:11px;color:#D97706'>{_reason_txt}</span>",
                                unsafe_allow_html=True)

                st.markdown("<hr>", unsafe_allow_html=True)


# ════════════════════════════════════════════════════════
# TAB 5 · 활용처 관리
# ════════════════════════════════════════════════════════
with tab5:
    df_cur5  = load_derived(CURRENT_MONTH)
    df_con5  = load_content(CURRENT_MONTH)

    st.markdown("""<div class="sh-main"><div class="t">PR 활용 관리</div>
<div class="s">뉴스 모니터링에서 선별한 기사와 키워드의 PR 활용처 및 반영 상태를 관리합니다.</div></div>""",
                unsafe_allow_html=True)

    FILTER_OPTS=["전체","PR 기사","온드미디어","미지정","미반영"]
    if "t5_flt" not in st.session_state: st.session_state["t5_flt"]="전체"

    filt_cols=st.columns([1.4,1.4,1.6,1.2,1.2,0.3,2.2])
    for i,f in enumerate(FILTER_OPTS):
        with filt_cols[i]:
            active=st.session_state["t5_flt"]==f
            if st.button(f,key=f"t5_f_{i}",type="primary" if active else "secondary",use_container_width=True):
                st.session_state["t5_flt"]=f; st.rerun()
    with filt_cols[6]:
        st.download_button("⬇ 엑셀 다운로드",data=build_excel(),
                           file_name=f"keyword_kpi_{CURRENT_MONTH}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           use_container_width=True,key="t5_dl")

    flt=st.session_state["t5_flt"]

    if df_cur5.empty:
        st.info("이번 달 등록된 도출 키워드가 없습니다. '🔍 키워드 발굴·등록' 탭에서 추가해 주세요.")
    else:
        if flt=="PR 기사":      df5=df_cur5[df_cur5["활용처"].isin(["PR 기사","공통"])].copy()
        elif flt=="온드미디어": df5=df_cur5[df_cur5["활용처"].isin(["온드미디어","공통"])].copy()
        elif flt=="미지정":     df5=df_cur5[df_cur5["활용처"].str.strip()==""].copy()
        elif flt=="미반영":     df5=df_cur5[df_cur5["상태"]!="반영완료"].copy()
        else:                   df5=df_cur5.copy()

        if not df_con5.empty:
            lc   =(df_con5.sort_values("added_at",ascending=False)
                   .drop_duplicates(subset="keyword",keep="first").set_index("keyword"))
            cc_map=df_con5.groupby("keyword").size().to_dict()
        else: lc=pd.DataFrame(); cc_map={}

        h0,h1,h2,h3,h4,h5,h6=st.columns([2.2,2,1.5,3,1,1.5,1.1])
        for hc,hl in zip([h0,h1,h2,h3,h4,h5,h6],
                         ["키워드","활용처","반영 상태","콘텐츠명","링크","반영일","상세 편집"]):
            hc.markdown(f"<span class='th'>{hl}</span>",unsafe_allow_html=True)
        st.markdown("<hr style='margin:5px 0 3px'>",unsafe_allow_html=True)

        for _,row in df5.iterrows():
            kw   =row["키워드"]; usage=row["활용처"] or ""; stat=row["상태"] or "도출"
            has_c=not lc.empty and kw in lc.index
            cn=lc.loc[kw,"content_name"]  if has_c else ""
            cu=lc.loc[kw,"url"]            if has_c else ""
            cd=lc.loc[kw,"published_at"]   if has_c else ""
            ctot=cc_map.get(kw,0)
            cur_idx=USAGES.index(usage) if usage in USAGES else 0

            r0,r1,r2,r3,r4,r5,r6=st.columns([2.2,2,1.5,3,1,1.5,1.1])
            with r0: st.markdown(f"<span class='td' style='font-weight:600'>{kw}</span>",unsafe_allow_html=True)
            with r1:
                st.selectbox(f"활용처_{kw}",USAGES,index=cur_idx,key=f"t5_sel_{kw}",
                             label_visibility="collapsed",on_change=_make_usage_cb(kw,CURRENT_MONTH))
                if st.session_state.pop(f"t5_saved_{kw}",False):
                    st.markdown("<span style='color:#059669;font-size:11px'>✓ 저장됨</span>",unsafe_allow_html=True)
            with r2: st.markdown(_status_html(stat),unsafe_allow_html=True)
            with r3:
                if cn:
                    disp=cn+(f" 외 {ctot-1}건" if ctot>1 else "")
                    st.markdown(f"<span class='td'>{disp}</span>",unsafe_allow_html=True)
                else: st.markdown("<span class='td' style='color:#94A3B8'>—</span>",unsafe_allow_html=True)
            with r4:
                if cu: st.markdown(f"[↗]({cu})",unsafe_allow_html=True)
                else:  st.markdown("<span style='color:#94A3B8;font-size:13px'>—</span>",unsafe_allow_html=True)
            with r5: st.markdown(f"<span class='td' style='color:#64748B'>{cd or '—'}</span>",unsafe_allow_html=True)
            with r6:
                if st.button("편집",key=f"t5_ed_{kw}",use_container_width=True):
                    content_dialog(kw,CURRENT_MONTH,usage)
            st.markdown("<hr style='margin:2px 0;border-color:#F1F5F9'>",unsafe_allow_html=True)

    st.markdown("<div style='margin-top:.8rem'></div>",unsafe_allow_html=True)

    # 키워드 삭제 (collapsible_header)
    if collapsible_header("키워드 삭제 (주의)","t5_del_exp"):
        st.caption("잘못 등록된 키워드와 해당 콘텐츠 기록을 삭제합니다.")
        if not df_cur5.empty:
            dk=st.selectbox("삭제할 키워드",df_cur5["키워드"].tolist(),
                            label_visibility="collapsed",key="t5_dk_sel")
            if st.button("삭제",type="secondary",key="t5_dk_btn"):
                delete_keyword(dk,CURRENT_MONTH)
                df_c=_read_content_all()
                _write_content(df_c[~((df_c["keyword"]==dk)&(df_c["kpi_month"]==CURRENT_MONTH))],
                               f"콘텐츠 일괄 삭제: {dk}")
                _inv_derived(); _inv_content()
                st.success(f"'{dk}' 삭제 완료"); st.rerun()
        else: st.info("삭제할 키워드가 없습니다.")

    st.markdown("<div style='margin-top:.4rem'></div>",unsafe_allow_html=True)

    # 월별 KPI 누적 현황 (collapsible_header)
    if collapsible_header("월별 KPI 누적 현황","t5_kpi_exp"):
        dfm5=load_monthly_kpi_summary()
        buf5=io.BytesIO()
        with pd.ExcelWriter(buf5,engine="openpyxl") as w: dfm5.to_excel(w,index=False,sheet_name="월별KPI")
        cc_dl,_=st.columns([2,5])
        with cc_dl:
            st.download_button("⬇ 월별 KPI 엑셀",buf5.getvalue(),
                               file_name=f"monthly_kpi_{CURRENT_MONTH}.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                               key="t5_dl_m")
        _render_monthly_table(dfm5)
        st.markdown("<div style='margin-top:1rem'></div>",unsafe_allow_html=True)
        _render_manual_form(dfm5,pfx="t5_")


# ── 푸터 ─────────────────────────────────────────────────
_tcnt=len(pd.read_csv(TRENDS_CSV)) if os.path.exists(TRENDS_CSV) else 0
_mcnt=len(MEDIA_CFG)
st.markdown(f"""
<div style="margin-top:3rem;padding-top:1.5rem;border-top:1px solid #DCE3EA;
display:flex;justify-content:space-between;align-items:center;
font-size:11px;color:#94A3B8;flex-wrap:wrap;gap:4px">
  <span>뉴스 &amp; 트렌드 모니터링 · SCK/STK Corp · {CURRENT_MONTH}</span>
  <span style='font-weight:700;color:#2F6BFF'>BUILD {BUILD_VERSION}</span>
  <span>트렌드 {_tcnt:,}건 · 매체 {_mcnt}개 · 네이버 데이터랩 · 구글 트렌드</span>
</div>""",unsafe_allow_html=True)
