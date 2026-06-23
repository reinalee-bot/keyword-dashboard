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
    page_title="키워드 트렌드 대시보드",
    page_icon="📊",
    layout="wide",
)

st.markdown("""
<style>
    .stApp { background-color: #f8f9fc; }
    .kpi-card {
        background: white; border-radius: 14px;
        padding: 22px 18px 18px; box-shadow: 0 2px 10px rgba(0,0,0,0.07);
        text-align: center;
    }
    .kpi-label  { font-size:.85rem; color:#888; margin-bottom:8px; font-weight:500; }
    .kpi-value  { font-size:2.3rem; font-weight:700; color:#1a1a2e; }
    .kpi-target { font-size:.78rem; color:#bbb; margin-top:4px; }
    .badge-pass { display:inline-block; background:#e8f5e9; color:#2e7d32;
                  border-radius:20px; padding:5px 16px; font-weight:700; margin-top:8px; }
    .badge-fail { display:inline-block; background:#fff3e0; color:#e65100;
                  border-radius:20px; padding:5px 16px; font-weight:700; margin-top:8px; }
    .section-title { font-size:1.15rem; font-weight:700; color:#1a1a2e; margin:0 0 4px 0; }
    .src-naver { font-size:.82rem; color:#03c75a; font-weight:600; }
    .src-google { font-size:.82rem; color:#ea4335; font-weight:600; }
    .chart-hint { font-size:.76rem; color:#bbb; margin-bottom:10px; }
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

# ── 헤더 ─────────────────────────────────────────────
st.markdown("## 📊 키워드 트렌드 KPI 대시보드")
_sync_status = "🔄 GitHub 자동 동기화 활성" if gh.is_configured() else "💾 로컬 저장 모드"
st.caption(
    f"기준 월: **{CURRENT_MONTH}**  |  "
    f"마지막 업데이트: {datetime.now().strftime('%Y년 %m월 %d일 %H:%M')}  |  "
    f"데이터: 네이버 데이터랩 · 구글 트렌드  |  {_sync_status}"
)
st.divider()

# ── KPI 자동 계산 ────────────────────────────────────
df_cur          = load_derived(CURRENT_MONTH)
KPI_DERIVED     = len(df_cur)
KPI_REFLECTED   = int(df_cur["반영"].sum()) if not df_cur.empty else 0
KPI_TARGET_D    = 5
KPI_TARGET_R    = 70
reflection_rate = round(KPI_REFLECTED / KPI_DERIVED * 100) if KPI_DERIVED > 0 else 0
kpi_pass        = (KPI_DERIVED >= KPI_TARGET_D) and (reflection_rate >= KPI_TARGET_R)

# ── KPI 카드 3개 ──────────────────────────────────────
c1, c2, c3 = st.columns(3, gap="large")

with c1:
    st.markdown(f"""
    <div class="kpi-card">
        <div class="kpi-label">이번 달 도출 키워드 수</div>
        <div class="kpi-value">{KPI_DERIVED}<span style="font-size:1rem;color:#aaa"> 건</span></div>
        <div class="kpi-target">목표 {KPI_TARGET_D}건</div>
    </div>""", unsafe_allow_html=True)
    st.progress(min(KPI_DERIVED / KPI_TARGET_D, 1.0),
                text=f"목표 대비 {min(int(KPI_DERIVED/KPI_TARGET_D*100),100)}%")

with c2:
    st.markdown(f"""
    <div class="kpi-card">
        <div class="kpi-label">키워드 반영률</div>
        <div class="kpi-value">{reflection_rate}<span style="font-size:1rem;color:#aaa"> %</span></div>
        <div class="kpi-target">목표 {KPI_TARGET_R}%  (반영 {KPI_REFLECTED} / 도출 {KPI_DERIVED}건)</div>
    </div>""", unsafe_allow_html=True)
    st.progress(min(reflection_rate / KPI_TARGET_R, 1.0),
                text=f"목표 대비 {min(int(reflection_rate/KPI_TARGET_R*100),100)}%")

with c3:
    badge_cls  = "badge-pass" if kpi_pass else "badge-fail"
    badge_text = "✅ 달성" if kpi_pass else "⏳ 진행 중"
    hint = "두 목표 모두 달성!" if kpi_pass else (
        f"도출 {max(KPI_TARGET_D-KPI_DERIVED,0)}건 더 필요 · "
        f"반영률 {max(KPI_TARGET_R-reflection_rate,0)}%p 더 필요"
    )
    st.markdown(f"""
    <div class="kpi-card">
        <div class="kpi-label">이번 달 KPI 달성 여부</div>
        <div style="margin-top:10px">
            <span class="{badge_cls}">{badge_text}</span>
        </div>
        <div class="kpi-target" style="margin-top:12px">{hint}</div>
    </div>""", unsafe_allow_html=True)
    st.progress(1.0 if kpi_pass else max(reflection_rate/100, 0.05),
                text="달성!" if kpi_pass else "미달성")

st.divider()

# ══════════════════════════════════════════════════════
# 섹션 1: 내 추적 키워드 관리 + 그래프
# ══════════════════════════════════════════════════════
st.markdown('<div class="section-title">🎯 내 추적 키워드 — 네이버·구글 그래프에 반영됩니다</div>',
            unsafe_allow_html=True)
st.caption("키워드를 추가하면 즉시 데이터를 수집하고 아래 그래프에 반영됩니다.")

tracked_kws = load_tracked_keywords()

# ── 세션 상태: 잠깐 숨김 키워드 집합 ──────────────────
if "hidden_kws" not in st.session_state:
    st.session_state["hidden_kws"] = set()
# 삭제된 키워드가 hidden 집합에 남아있으면 정리
st.session_state["hidden_kws"] &= set(tracked_kws)

# ── 칩 렌더링 ─────────────────────────────────────────
st.caption(
    "**칩 클릭** → 그래프에서 잠깐 숨김 / 다시 클릭 → 복원  ·  "
    "**✕** → 추적 목록에서 완전 삭제"
)

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
                             help=f"'{kw}'를 추적 목록에서 완전 삭제"):
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

# ── 주간 검색 관심도 그래프 (추적 키워드 중 숨김 제외) ─
active_kws = [kw for kw in tracked_kws if kw not in st.session_state["hidden_kws"]]
df_trends  = load_trends()

if df_trends.empty:
    st.warning("data/trends.csv 에 데이터가 없습니다. 터미널에서 `python collector.py` 를 먼저 실행해 주세요.")
elif not active_kws:
    st.info("모든 키워드가 숨김 상태입니다. 칩을 다시 클릭해서 복원하세요.")
else:
    df_filtered = df_trends[df_trends["keyword"].isin(active_kws)]
    df_naver    = df_filtered[df_filtered["source"] == "naver"]
    df_google   = df_filtered[df_filtered["source"] == "google"]

    col_n, col_g = st.columns(2, gap="large")
    with col_n:
        st.markdown('<div class="src-naver">🟢 네이버 데이터랩 — 검색 트렌드</div>', unsafe_allow_html=True)
        st.markdown('<div class="chart-hint">국내 검색 기준 · 0~100 상대 지수 · 인스타그램 콘텐츠 기획 참고</div>', unsafe_allow_html=True)
        if not df_naver.empty:
            draw_chart(to_weekly(df_naver))
            with st.expander("네이버 원본 데이터"):
                s = df_naver.copy(); s["date"] = s["date"].dt.strftime("%Y-%m-%d")
                st.dataframe(s[["keyword","date","ratio"]].rename(columns={"keyword":"키워드","date":"날짜","ratio":"관심도"}).sort_values("날짜", ascending=False).head(40), use_container_width=True, hide_index=True)
        else:
            st.info("추적 키워드의 네이버 데이터가 없습니다. '＋ 추가' 버튼으로 수집하세요.")

    with col_g:
        st.markdown('<div class="src-google">🔴 구글 트렌드 — 검색 트렌드</div>', unsafe_allow_html=True)
        st.markdown('<div class="chart-hint">국내·글로벌 검색 기준 · 0~100 상대 지수 · 링크드인 콘텐츠 기획 참고</div>', unsafe_allow_html=True)
        if not df_google.empty:
            draw_chart(to_weekly(df_google))
            with st.expander("구글 원본 데이터"):
                g = df_google.copy(); g["date"] = g["date"].dt.strftime("%Y-%m-%d")
                st.dataframe(g[["keyword","date","ratio"]].rename(columns={"keyword":"키워드","date":"날짜","ratio":"관심도"}).sort_values("날짜", ascending=False).head(40), use_container_width=True, hide_index=True)
        else:
            st.info("추적 키워드의 구글 데이터가 없습니다. 다음 수집 시 자동으로 채워집니다.")

    st.caption("⚠️ 네이버(일별)와 구글(주별)은 집계 기준이 달라 직접 비교하지 마세요.")

st.divider()

# ══════════════════════════════════════════════════════
# 섹션 2: 이번 주 급상승 키워드 발굴
# ══════════════════════════════════════════════════════
st.markdown(
    '<div class="section-title">🔥 이번 주 급상승 키워드 발굴'
    '<span style="font-size:.8rem;color:#888;font-weight:400;margin-left:10px">'
    '구글 뉴스 기사 빈도 기반 (위 그래프의 네이버·구글 검색 트렌드와 다릅니다)'
    '</span></div>',
    unsafe_allow_html=True,
)

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

st.divider()
st.caption(
    f"ⓒ keyword-dashboard  ·  기준 월: {CURRENT_MONTH}  ·  "
    f"저장 위치: data/trends.csv ({len(pd.read_csv(TRENDS_CSV))}건)"
    if os.path.exists(TRENDS_CSV) else f"ⓒ keyword-dashboard  ·  기준 월: {CURRENT_MONTH}"
)
