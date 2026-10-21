"""
linkedin_tab.py — 📣 LinkedIn 키워드·콘텐츠 성과 탭

목적:
  LinkedIn Content Excel을 기반으로,
  특정 키워드·해시태그를 포함한 게시물이 LinkedIn 내에서 기록한
  노출·클릭·반응·참여율을 관찰한다.

  방문자 구성(Visitors Excel)은 LinkedIn 페이지 전체 방문자 특성이며,
  특정 게시물·해시태그 효과와 직접 연결하지 않는다.

  GA4·UTM 유입 측정은 이 탭의 범위가 아님 (별도 분리).
  LinkedIn 로그인 / 크롤링 / 비공식 API 미사용.
"""

from __future__ import annotations

import os
from datetime import datetime

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import github_storage as gh
import linkedin_import as li

# ── 상수: Content ──────────────────────────────────────────────────────
_CSV_PATH  = "data/linkedin_posts.csv"
_LOCAL_CSV = os.path.join(os.path.dirname(__file__), _CSV_PATH)

_COLS = [
    "post_id", "url", "published_at", "title", "text",
    "post_format", "campaign", "content_type", "hashtags",
    "impressions", "views", "external_views", "clicks", "ctr",
    "reactions", "comments", "reposts", "followers", "engagement_rate",
    "utm_content", "ga4_sessions",   # 미래 연동 구조 보존, UI 미표시
    "added_at", "updated_at",
]

_NUM_COLS = [
    "impressions", "views", "external_views", "clicks", "ctr",
    "reactions", "comments", "reposts", "followers", "engagement_rate",
]

# ── 상수: Visitors ────────────────────────────────────────────────────
_VIS_CSV_PATH  = "data/linkedin_visitors.csv"
_LOCAL_VIS_CSV = os.path.join(os.path.dirname(__file__), _VIS_CSV_PATH)

_VIS_COLS = [
    "snapshot_id", "uploaded_at", "period_label",
    "sheet", "rank", "label", "count", "pct",
]


# ══════════════════════════════════════════════════════════════════════
# 데이터 로드·저장 — Content
# ══════════════════════════════════════════════════════════════════════

def _load() -> pd.DataFrame:
    df = gh.read_csv(_CSV_PATH)
    if df is not None and len(df) > 0:
        return _cast(df)
    if os.path.exists(_LOCAL_CSV):
        try:
            return _cast(pd.read_csv(_LOCAL_CSV, dtype=str))
        except Exception:
            pass
    return pd.DataFrame(columns=_COLS)


def _cast(df: pd.DataFrame) -> pd.DataFrame:
    for col in _COLS:
        if col not in df.columns:
            df[col] = ""
    for c in _NUM_COLS:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df[_COLS].copy()


def _save(df: pd.DataFrame, msg: str) -> bool:
    os.makedirs(os.path.dirname(_LOCAL_CSV), exist_ok=True)
    df.to_csv(_LOCAL_CSV, index=False, encoding="utf-8")
    return gh.write_csv(df, _CSV_PATH, msg)


# ══════════════════════════════════════════════════════════════════════
# 데이터 로드·저장 — Visitors
# ══════════════════════════════════════════════════════════════════════

def _load_visitors() -> pd.DataFrame:
    df = gh.read_csv(_VIS_CSV_PATH)
    if df is not None and len(df) > 0:
        return _cast_visitors(df)
    if os.path.exists(_LOCAL_VIS_CSV):
        try:
            return _cast_visitors(pd.read_csv(_LOCAL_VIS_CSV, dtype=str))
        except Exception:
            pass
    return pd.DataFrame(columns=_VIS_COLS)


def _cast_visitors(df: pd.DataFrame) -> pd.DataFrame:
    for col in _VIS_COLS:
        if col not in df.columns:
            df[col] = ""
    df["count"] = pd.to_numeric(df["count"], errors="coerce")
    df["pct"]   = pd.to_numeric(df["pct"],   errors="coerce")
    df["rank"]  = pd.to_numeric(df["rank"],  errors="coerce")
    return df[_VIS_COLS].copy()


def _save_visitors(df: pd.DataFrame, msg: str) -> bool:
    os.makedirs(os.path.dirname(_LOCAL_VIS_CSV), exist_ok=True)
    df.to_csv(_LOCAL_VIS_CSV, index=False, encoding="utf-8")
    return gh.write_csv(df, _VIS_CSV_PATH, msg)


# ══════════════════════════════════════════════════════════════════════
# 공개 렌더 함수
# ══════════════════════════════════════════════════════════════════════

@st.fragment
def render(prefix: str = "li_") -> None:
    """dashboard.py 에서 `with tab5: linkedin_tab.render()` 로 호출합니다."""

    ss_df  = f"{prefix}df"
    ss_vis = f"{prefix}vis_df"

    if ss_df not in st.session_state:
        st.session_state[ss_df] = _load()
    if ss_vis not in st.session_state:
        st.session_state[ss_vis] = _load_visitors()

    df     = st.session_state[ss_df]
    df_vis = st.session_state[ss_vis]

    # ── 통합 업로드 섹션
    _render_upload(df, df_vis, prefix, ss_df, ss_vis)

    df     = st.session_state[ss_df]
    df_vis = st.session_state[ss_vis]

    has_content  = len(df) > 0
    has_visitors = len(df_vis) > 0

    if not has_content and not has_visitors:
        _render_empty_state()
        _render_advanced(df, prefix, ss_df)
        return

    # ── 서브 탭 구성
    tab_names = ["📊 성과 요약", "📋 게시물 목록", "#️⃣ 해시태그 관찰", "👥 방문자 구성"]
    tabs = st.tabs(tab_names)

    if has_content:
        df_c = _enrich(df)
        with tabs[0]:
            _render_summary(df_c, prefix)
        with tabs[1]:
            _render_list(df_c, prefix)
        with tabs[2]:
            _render_hashtags(df_c, prefix)
    else:
        for i in range(3):
            with tabs[i]:
                st.info("LinkedIn Content Excel을 업로드하면 표시됩니다.")

    with tabs[3]:
        if has_visitors:
            _render_visitors(df_vis, prefix)
        else:
            st.info("LinkedIn Visitors Excel을 업로드하면 방문자 구성 분석이 표시됩니다.")

    _render_advanced(df, prefix, ss_df)


# ══════════════════════════════════════════════════════════════════════
# 통합 업로드 섹션
# ══════════════════════════════════════════════════════════════════════

def _render_upload(
    df: pd.DataFrame,
    df_vis: pd.DataFrame,
    prefix: str,
    ss_df: str,
    ss_vis: str,
) -> None:
    has_data = len(df) > 0 or len(df_vis) > 0

    with st.expander(
        "📥 LinkedIn Excel 업로드" + (" (데이터 추가·갱신)" if has_data else ""),
        expanded=not has_data,
    ):
        st.markdown("""
<div style="background:#EFF6FF;border-left:4px solid #3B82F6;
     padding:10px 14px;border-radius:6px;margin-bottom:.75rem;font-size:13px;color:#374151">
<b>Content Excel</b>: 게시물 본문 키워드·해시태그 자동 추출 및 노출·클릭·반응·참여율 비교<br>
<b>Visitors Excel</b>: LinkedIn 페이지 방문자 전체의 직급·직종·업계·지역 구성 분석<br>
파일 유형은 자동으로 구분됩니다. 결과는 <b>관찰치</b>이며 인과관계를 의미하지 않습니다.
</div>""", unsafe_allow_html=True)

        uploaded = st.file_uploader(
            "LinkedIn Content 또는 Visitors 내보내기 파일 (.xls / .xlsx / .csv)",
            type=["xls", "xlsx", "csv"],
            key=f"{prefix}upload",
            label_visibility="collapsed",
        )

        if not uploaded:
            st.caption("Content Excel 또는 Visitors Excel을 올리면 파일 유형을 자동으로 감지합니다.")
            return

        with st.spinner("파일 유형 감지 중..."):
            file_type, detect_err = li.detect_upload_type(uploaded)

        if file_type == "unknown":
            st.error(
                f"파일 유형을 인식할 수 없습니다. LinkedIn 관리자 내보내기 파일인지 확인하세요.\n"
                f"{'상세: ' + detect_err if detect_err else ''}"
            )
            return

        badge = "📄 Content (게시물 성과)" if file_type == "content" else "👥 Visitors (방문자 특성)"
        st.caption(f"감지된 파일 유형: **{badge}**")

        if file_type == "content":
            _handle_content_upload(uploaded, df, prefix, ss_df)
        else:
            _handle_visitors_upload(uploaded, df_vis, prefix, ss_vis)


def _handle_content_upload(
    uploaded,
    df: pd.DataFrame,
    prefix: str,
    ss_df: str,
) -> None:
    with st.spinner("파일 읽는 중..."):
        df_posts, df_stats, err = li.read_linkedin_file(uploaded)

    if err or df_posts is None:
        st.error(f"파일을 읽을 수 없습니다.\n\n**오류 상세:** {err}")
        return

    with st.spinner("게시물 파싱 중..."):
        new_rows = li.parse_posts(df_posts)

    if not new_rows:
        st.warning("가져올 게시물이 없습니다. 파일 내용을 확인하세요.")
        return

    n_total = len(new_rows)
    n_dup   = sum(
        1 for r in new_rows
        if r["url"].rstrip("/") in
        {str(u).rstrip("/") for u in df["url"] if pd.notna(u) and str(u).strip()}
    )
    n_new = n_total - n_dup

    dates  = [r["published_at"] for r in new_rows if r["published_at"]]
    period = f"{min(dates)} ~ {max(dates)}" if dates else "-"

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("전체 게시물", n_total)
    m2.metric("신규", n_new)
    m3.metric("갱신 (기존 URL)", n_dup)
    m4.metric("기간", period)

    prev = pd.DataFrame([{
        "게시일"     : r["published_at"],
        "게시물 요약": r["title"][:45] + "…" if len(r["title"]) > 45 else r["title"],
        "해시태그"   : r["hashtags"] or "(없음)",
        "노출수"     : r["impressions"],
        "클릭"       : r["clicks"],
        "참여율"     : f"{r['engagement_rate']*100:.1f}%" if r["engagement_rate"] and not np.isnan(r["engagement_rate"]) else "-",
    } for r in new_rows])
    st.dataframe(prev, use_container_width=True, height=220)
    st.divider()

    if df_stats is not None:
        st.info("💡 `통계` 시트(일별 채널 성과)도 감지됐습니다. 성과 요약 탭 '일별 추이' 차트에 활용됩니다.", icon="📈")
        st.session_state[f"{prefix}stats_df"] = df_stats

    if st.button(
        f"✅ 가져오기 확정  (신규 {n_new}건 추가 · 갱신 {n_dup}건)",
        type="primary", key=f"{prefix}confirm", use_container_width=True,
    ):
        with st.spinner("저장 중..."):
            df_merged, stats = li.merge_posts(df.copy(), new_rows)
            df_merged = _cast(df_merged)
            ok = _save(df_merged, f"feat: LinkedIn Content 가져오기 — 신규{stats['new']} 갱신{stats['updated']}")

        st.session_state[ss_df] = df_merged
        msg = f"✅ 저장 완료 — 신규 {stats['new']}건, 갱신 {stats['updated']}건"
        if ok:
            st.success(msg)
        else:
            st.warning(f"⚠️ 로컬 저장 완료 (GitHub 동기화 실패) — 신규 {stats['new']}건, 갱신 {stats['updated']}건")
        st.rerun()


def _handle_visitors_upload(
    uploaded,
    df_vis: pd.DataFrame,
    prefix: str,
    ss_vis: str,
) -> None:
    with st.spinner("방문자 파일 읽는 중..."):
        sheets_data, period_label, err = li.read_visitors_file(uploaded)

    if err or not sheets_data:
        st.error(f"방문자 파일을 읽을 수 없습니다.\n\n**오류 상세:** {err}")
        return

    uploaded_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    new_rows = li.parse_visitors_snapshot(sheets_data, period_label, uploaded_at)

    if not new_rows:
        st.warning("방문자 데이터를 파싱할 수 없습니다. 파일 내용을 확인하세요.")
        return

    # 기간 겹침 확인
    existing_periods = (
        set(df_vis["period_label"].astype(str).unique())
        if len(df_vis) > 0 and "period_label" in df_vis.columns
        else set()
    )
    is_update = period_label in existing_periods

    n_sheets = len({r["sheet"] for r in new_rows} - {"총_방문자"})
    total_row = next((r for r in new_rows if r["sheet"] == "총_방문자"), None)

    v1, v2, v3 = st.columns(3)
    v1.metric("분석 기간", period_label)
    v2.metric("분류 시트 수", n_sheets)
    v3.metric("총 방문자 (추정)", f"{total_row['count']:,}" if total_row and total_row["count"] else "-")

    if is_update:
        st.warning(f"⚠️ **{period_label}** 기간의 데이터가 이미 있습니다. 가져오기 확정 시 교체됩니다.")
    else:
        st.info(f"📅 신규 기간 **{period_label}** 데이터를 추가합니다.")

    st.divider()

    if st.button(
        f"✅ 방문자 데이터 가져오기 확정",
        type="primary", key=f"{prefix}vis_confirm", use_container_width=True,
    ):
        with st.spinner("저장 중..."):
            df_merged, stats = li.merge_visitors(df_vis.copy(), new_rows)
            df_merged = _cast_visitors(df_merged)
            ok = _save_visitors(
                df_merged,
                f"feat: LinkedIn Visitors 가져오기 — {period_label} ({'갱신' if stats['replaced'] else '신규'})",
            )

        st.session_state[ss_vis] = df_merged
        if ok:
            st.success(f"✅ 저장 완료 — {period_label} ({'교체' if stats['replaced'] else '신규 추가'})")
        else:
            st.warning(f"⚠️ 로컬 저장 완료 (GitHub 동기화 실패) — {period_label}")
        st.rerun()


# ══════════════════════════════════════════════════════════════════════
# 빈 상태
# ══════════════════════════════════════════════════════════════════════

def _render_empty_state() -> None:
    st.markdown("""
<div style="text-align:center;padding:3rem 1rem;color:#94A3B8">
  <div style="font-size:2.5rem">📣</div>
  <div style="font-size:1.1rem;font-weight:600;margin:.5rem 0">
    LinkedIn Excel을 업로드하면 성과 분석이 시작됩니다</div>
  <div style="font-size:13px">
    Content: 관리자 &gt; 분석 &gt; 게시물 &gt; 내보내기<br>
    Visitors: 관리자 &gt; 분석 &gt; 방문자 &gt; 내보내기
  </div>
</div>""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════
# 지표 보강
# ══════════════════════════════════════════════════════════════════════

def _enrich(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["_pub"]          = pd.to_datetime(df["published_at"], errors="coerce")
    df["_ctr_pct"]      = df["ctr"].apply(lambda x: x * 100 if pd.notna(x) else np.nan)
    df["_eng_pct"]      = df["engagement_rate"].apply(lambda x: x * 100 if pd.notna(x) else np.nan)
    df["_engage_total"] = (
        df["reactions"].fillna(0)
        + df["comments"].fillna(0)
        + df["reposts"].fillna(0)
    )
    return df


def _fmt(val, pct: bool = False, na: str = "-") -> str:
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return na
    if pct:
        return f"{val:.1f}%"
    return f"{val:,.0f}"


# ══════════════════════════════════════════════════════════════════════
# 자동 인사이트 (2문장)
# ══════════════════════════════════════════════════════════════════════

def _infer_content_char(row: pd.Series) -> str:
    combined = (str(row.get("title", "") or "") + " " + str(row.get("text", "") or "")).lower()
    if any(k in combined for k in ["교육", "training", "실습", "학습", "edutech"]):
        return "교육·실습 맥락"
    if any(k in combined for k in ["보안", "security", "취약점", "hackerone", "redteam"]):
        return "보안 전문 정보"
    if any(k in combined for k in ["행사", "세미나", "conference", "event", "expo", "조찬"]):
        return "행사·세미나 참여 보고"
    if any(k in combined for k in ["파트너", "partner", "협력", "10주년", "기념"]):
        return "파트너십·기념 소식"
    if any(k in combined for k in ["ai", "autodesk", "adobe", "microsoft", "솔루션", "제품"]):
        return "솔루션·기술 소개"
    title_short = str(row.get("title", "") or "")[:15].strip()
    return f"'{title_short}' 관련" if title_short else "해당 콘텐츠"


def _render_insights(df: pd.DataFrame) -> None:
    """성과 요약 최상단 — 2문장 자동 인사이트"""
    valid_clk = df.dropna(subset=["clicks", "impressions"])
    valid_eng = df.dropna(subset=["_eng_pct"])

    if len(valid_clk) < 2 and len(valid_eng) < 2:
        return

    n = len(df)
    small_sample = n < 10

    st.markdown("#### 💡 이번 기간 인사이트")

    sentences: list[str] = []

    # ── 문장 1: 클릭 성과
    if len(valid_clk) >= 2:
        top_clk    = valid_clk.loc[valid_clk["clicks"].idxmax()]
        med_imp    = valid_clk["impressions"].median()
        med_ctr    = valid_clk["_ctr_pct"].median()
        top_imp    = float(top_clk["impressions"])
        top_ctr    = float(top_clk.get("_ctr_pct", np.nan) or np.nan)
        top_clicks = int(top_clk["clicks"])
        imp_ratio  = top_imp / med_imp if med_imp and med_imp > 0 else 1.0

        # 클릭 증가 주요 관찰 요인
        ctr_ratio = (top_ctr / med_ctr) if (med_ctr and med_ctr > 0 and pd.notna(top_ctr)) else 1.0
        if imp_ratio >= 1.5 and ctr_ratio <= 1.3:
            factor = "도달 규모 확대"
        elif imp_ratio <= 1.3 and ctr_ratio >= 1.5:
            factor = "높은 클릭률(CTR)"
        else:
            factor = "도달 규모와 CTR 모두"

        title_short = str(top_clk.get("title", "") or "")[:25].rstrip("…")
        s1 = (
            f"**"{title_short}…"** 게시물은 중앙값보다 **{imp_ratio:.1f}배** 많은 "
            f"**{int(top_imp):,}회** 노출을 확보해 **{top_clicks:,}회** 클릭으로 이어졌습니다. "
            f"클릭 증가의 주된 관찰 요인은 **{factor}**입니다."
        )
        sentences.append(s1)

    # ── 문장 2: 참여율 성과
    if len(valid_eng) >= 2:
        top_eng    = valid_eng.loc[valid_eng["_eng_pct"].idxmax()]
        med_imp    = valid_eng["impressions"].median() if "impressions" in valid_eng else np.nan
        med_eng    = valid_eng["_eng_pct"].median()
        top_imp_e  = float(top_eng.get("impressions", np.nan) or np.nan)
        top_ctr_e  = float(top_eng.get("_ctr_pct", np.nan) or np.nan)
        top_eng_v  = float(top_eng["_eng_pct"])

        # 노출 비교 문구
        if pd.notna(top_imp_e) and pd.notna(med_imp) and med_imp > 0:
            imp_ratio_e = top_imp_e / med_imp
            if imp_ratio_e >= 1.3:
                imp_context = f"노출은 중앙값보다 {imp_ratio_e:.1f}배 높은 상황에서도"
            elif imp_ratio_e <= 0.7:
                imp_context = "노출은 중앙값보다 낮았지만"
            else:
                imp_context = "노출은 중앙값과 유사했지만"
        else:
            imp_context = "노출 대비"

        ctr_str = f"CTR {top_ctr_e:.1f}%, " if pd.notna(top_ctr_e) else ""
        content_char = _infer_content_char(top_eng)
        title_short2 = str(top_eng.get("title", "") or "")[:25].rstrip("…")

        s2 = (
            f"**"{title_short2}…"** 게시물은 {imp_context} "
            f"{ctr_str}참여율 **{top_eng_v:.1f}%**로 관찰 기간 최고를 기록했습니다. "
            f"{content_char}의 콘텐츠가 관심을 이끌었을 가능성이 있으나, "
            f"현재 표본만으로 확정할 수는 없습니다."
        )
        sentences.append(s2)

    if not sentences:
        return

    suffix = "  \n현재 표본이 적어 다음 기간 데이터가 더 필요합니다." if small_sample else ""

    insight_text = "  \n".join(sentences) + suffix

    st.info(insight_text, icon="💡")


# ══════════════════════════════════════════════════════════════════════
# 성과 요약 탭
# ══════════════════════════════════════════════════════════════════════

def _render_summary(df: pd.DataFrame, prefix: str) -> None:
    st.markdown("#### 📊 성과 요약")

    # ── 자동 인사이트 (최상단)
    _render_insights(df)

    st.divider()

    # ── KPI 행
    imp     = df["impressions"].sum()
    clk     = df["clicks"].sum()
    eng_med = df["_eng_pct"].median()
    n       = len(df)

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("게시물 수",     f"{n:,}")
    k2.metric("총 노출수",     f"{imp:,.0f}")
    k3.metric("총 클릭수",     f"{clk:,.0f}")
    k4.metric("중앙값 참여율", _fmt(eng_med, pct=True))
    k5.metric("중앙값 CTR",    _fmt(df["_ctr_pct"].median(), pct=True))

    st.divider()

    # ── 베스트 게시물 3종
    c1, c2, c3 = st.columns(3)

    def _best(col: str, label: str, fmt_fn) -> None:
        sub = df.dropna(subset=[col])
        if sub.empty:
            return
        row = sub.loc[sub[col].idxmax()]
        st.markdown(f"**{label}**")
        st.markdown(f"<span style='font-size:13px;color:#374151'>{row['title'][:60]}</span>",
                    unsafe_allow_html=True)
        st.markdown(f"<b style='font-size:1.2rem;color:#2F6BFF'>{fmt_fn(row[col])}</b>",
                    unsafe_allow_html=True)
        if row.get("_pub") and pd.notna(row["_pub"]):
            st.caption(str(row["_pub"].date()))

    with c1:
        _best("_eng_pct",    "🏆 최고 참여율",  lambda v: f"{v:.1f}%")
    with c2:
        _best("clicks",      "🖱️ 최고 클릭수",  lambda v: f"{v:,.0f}회")
    with c3:
        _best("impressions", "👁 최고 노출수",   lambda v: f"{v:,.0f}회")

    st.divider()

    # ── 날짜별 추이 차트
    df_t = df.dropna(subset=["_pub"]).sort_values("_pub")
    if len(df_t) >= 2:
        fig = go.Figure()
        fig.add_trace(go.Bar(x=df_t["_pub"], y=df_t["impressions"],
                             name="노출수", marker_color="#BFDBFE", yaxis="y"))
        fig.add_trace(go.Scatter(x=df_t["_pub"], y=df_t["_eng_pct"],
                                 name="참여율(%)", mode="lines+markers",
                                 line=dict(color="#2F6BFF", width=2), yaxis="y2"))
        fig.update_layout(
            height=280,
            yaxis=dict(title="노출수"),
            yaxis2=dict(title="참여율(%)", overlaying="y", side="right"),
            legend=dict(orientation="h", y=1.08),
            margin=dict(l=0, r=0, t=30, b=0),
        )
        st.plotly_chart(fig, use_container_width=True)

    _render_stats_trend(prefix)


def _render_stats_trend(prefix: str) -> None:
    df_s = st.session_state.get(f"{prefix}stats_df")
    if df_s is None or len(df_s) == 0:
        return
    date_col = next((c for c in df_s.columns if "날짜" in str(c) or "date" in str(c).lower()), None)
    if not date_col:
        return
    num_cols = [c for c in df_s.columns if c != date_col
                and pd.to_numeric(df_s[c], errors="coerce").notna().any()]
    if not num_cols:
        return
    with st.expander("📈 일별 채널 추이 (`통계` 시트)"):
        df_s2 = df_s[[date_col] + num_cols[:4]].copy()
        df_s2[date_col] = pd.to_datetime(df_s2[date_col], errors="coerce")
        df_s2 = df_s2.dropna(subset=[date_col]).sort_values(date_col)
        for nc in num_cols[:4]:
            df_s2[nc] = pd.to_numeric(df_s2[nc], errors="coerce")
        fig = px.line(df_s2, x=date_col, y=num_cols[:4], height=260)
        fig.update_layout(margin=dict(l=0, r=0, t=20, b=0),
                          legend=dict(orientation="h", y=1.1))
        st.plotly_chart(fig, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════
# 게시물 목록 탭
# ══════════════════════════════════════════════════════════════════════

def _render_list(df: pd.DataFrame, prefix: str) -> None:
    st.markdown("#### 📋 게시물 목록")

    fc1, fc2, fc3 = st.columns(3)
    with fc1:
        min_d = df["_pub"].min()
        max_d = df["_pub"].max()
        date_range = st.date_input(
            "기간", value=(min_d.date() if pd.notna(min_d) else None,
                           max_d.date() if pd.notna(max_d) else None),
            key=f"{prefix}list_dr",
        )
    with fc2:
        sort_by = st.selectbox("정렬 기준",
            ["게시일 (최신순)", "참여율 (높은순)", "노출수 (높은순)", "클릭 (높은순)"],
            key=f"{prefix}list_sort",
        )
    with fc3:
        min_imp = st.number_input("최소 노출수", min_value=0, value=0, key=f"{prefix}list_imp")

    df_f = df.copy()
    if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
        s, e = pd.Timestamp(date_range[0]), pd.Timestamp(date_range[1])
        df_f = df_f[(df_f["_pub"] >= s) & (df_f["_pub"] <= e)]
    if min_imp > 0:
        df_f = df_f[df_f["impressions"] >= min_imp]

    sort_map = {
        "게시일 (최신순)": ("_pub", False),
        "참여율 (높은순)": ("_eng_pct", False),
        "노출수 (높은순)": ("impressions", False),
        "클릭 (높은순)": ("clicks", False),
    }
    sc, sa = sort_map[sort_by]
    df_f = df_f.sort_values(sc, ascending=sa, na_position="last")

    display_rows = []
    for _, r in df_f.iterrows():
        display_rows.append({
            "게시일"     : str(r["_pub"].date()) if pd.notna(r["_pub"]) else "-",
            "게시물 요약": r["title"],
            "해시태그"   : r["hashtags"] or "-",
            "노출"       : _fmt(r["impressions"]),
            "클릭"       : _fmt(r["clicks"]),
            "CTR"        : _fmt(r["_ctr_pct"], pct=True),
            "반응"       : _fmt(r["reactions"]),
            "댓글"       : _fmt(r["comments"]),
            "퍼감"       : _fmt(r["reposts"]),
            "참여율"     : _fmt(r["_eng_pct"], pct=True),
            "원문"       : r["url"],
        })

    df_disp = pd.DataFrame(display_rows)
    st.dataframe(
        df_disp, use_container_width=True, height=420,
        column_config={
            "원문"       : st.column_config.LinkColumn("원문", display_text="링크"),
            "게시물 요약": st.column_config.TextColumn("게시물 요약", width="large"),
        },
    )
    st.caption(f"총 {len(df_f)}건")

    csv_bytes = df_f.drop(
        columns=[c for c in df_f.columns if c.startswith("_")], errors="ignore"
    ).to_csv(index=False).encode("utf-8-sig")
    st.download_button("⬇ CSV 내보내기", csv_bytes,
                       file_name="linkedin_posts.csv", mime="text/csv",
                       key=f"{prefix}csv_dl")


# ══════════════════════════════════════════════════════════════════════
# 해시태그 관찰 탭
# ══════════════════════════════════════════════════════════════════════

def _render_hashtags(df: pd.DataFrame, prefix: str) -> None:
    st.markdown("#### #️⃣ 해시태그 관찰")

    st.warning(
        "해시태그별 결과는 게시 주제·이미지·게시 시간·광고 여부 등의 영향을 함께 받는 **관찰치**이며, "
        "해시태그 단독 효과나 인과관계를 의미하지 않습니다.",
        icon="⚠️",
    )

    records: list[dict] = []
    tag_posts: dict[str, list[int]] = {}

    for i, row in df.iterrows():
        tags = [t.strip() for t in str(row.get("hashtags", "") or "").split(",") if t.strip()]
        for tag in tags:
            tag_posts.setdefault(tag, []).append(i)

    for tag, idxs in tag_posts.items():
        sub = df.loc[idxs]
        n   = len(sub)
        records.append({
            "해시태그"     : tag,
            "게시물 수"    : n,
            "총 노출수"    : sub["impressions"].sum(),
            "중앙값 노출"  : sub["impressions"].median(),
            "총 클릭"      : sub["clicks"].sum(),
            "중앙값 클릭"  : sub["clicks"].median(),
            "중앙값 참여율": sub["_eng_pct"].median(),
            "_n"           : n,
        })

    if not records:
        st.info("해시태그 데이터가 없습니다. 게시물 본문에 #태그가 포함된 게시물을 가져오면 자동 분석됩니다.")
        return

    df_ht = pd.DataFrame(records).sort_values("총 노출수", ascending=False)

    total_posts = len(df)
    always_tags = {r["해시태그"] for r in records if r["_n"] / total_posts >= 0.8}

    df_rank = df_ht[df_ht["_n"] >= 3].copy()
    df_low  = df_ht[df_ht["_n"] < 3].copy()

    if len(df_rank) > 0:
        st.markdown("**✅ 성과 비교 (3건 이상 게시물)**")
        if always_tags:
            st.caption(f"상시 태그({', '.join(always_tags)})는 모든 게시물에 공통 적용되어 비교 의미가 낮습니다.")

        display_rank = df_rank.copy()
        display_rank["중앙값 참여율"] = display_rank["중앙값 참여율"].apply(
            lambda x: f"{x:.1f}%" if pd.notna(x) else "-"
        )
        display_rank["중앙값 노출"] = display_rank["중앙값 노출"].apply(
            lambda x: f"{x:,.0f}" if pd.notna(x) else "-"
        )
        display_rank["중앙값 클릭"] = display_rank["중앙값 클릭"].apply(
            lambda x: f"{x:,.0f}" if pd.notna(x) else "-"
        )
        st.dataframe(
            display_rank[["해시태그", "게시물 수", "총 노출수", "중앙값 노출",
                           "총 클릭", "중앙값 클릭", "중앙값 참여율"]],
            use_container_width=True, hide_index=True,
        )

        rank_chart = df_rank[~df_rank["해시태그"].isin(always_tags)].head(10)
        if len(rank_chart) > 0:
            fig = px.bar(
                rank_chart.sort_values("중앙값 참여율"),
                x="중앙값 참여율", y="해시태그",
                orientation="h", text="게시물 수",
                title="해시태그별 중앙값 참여율 (상시 태그 제외)",
                color_discrete_sequence=["#3B82F6"],
                height=max(220, len(rank_chart) * 35),
            )
            fig.update_traces(textposition="outside")
            fig.update_layout(margin=dict(l=0, r=20, t=40, b=0))
            st.plotly_chart(fig, use_container_width=True)

    if len(df_low) > 0:
        with st.expander(f"🔍 학습 중 — 표본 부족 ({len(df_low)}개 태그, 3건 미만)"):
            st.caption("아직 게시물 수가 적어 패턴을 파악하기 어렵습니다. 계속 관찰하세요.")
            st.dataframe(
                df_low[["해시태그", "게시물 수", "총 노출수", "총 클릭"]],
                use_container_width=True, hide_index=True,
            )


# ══════════════════════════════════════════════════════════════════════
# 방문자 구성 탭
# ══════════════════════════════════════════════════════════════════════

def _render_visitors(df_vis: pd.DataFrame, prefix: str) -> None:
    st.markdown("#### 👥 방문자 구성")

    st.info(
        "방문자 구성은 **LinkedIn 페이지 전체 방문자**의 특성입니다. "
        "특정 게시물·해시태그에서 유입된 사람이라고 연결하거나, "
        "콘텐츠의 직접 성과라고 해석하지 않습니다.",
        icon="ℹ️",
    )

    # ── 스냅샷 선택
    snapshots = (
        df_vis[["snapshot_id", "period_label", "uploaded_at"]]
        .drop_duplicates("snapshot_id")
        .sort_values("uploaded_at", ascending=False)
    )

    if len(snapshots) == 0:
        st.warning("방문자 데이터가 없습니다.")
        return

    period_options = snapshots["period_label"].tolist()
    selected_period = st.selectbox(
        "분석 기간", period_options, key=f"{prefix}vis_period"
    )

    df_cur = df_vis[df_vis["period_label"] == selected_period].copy()

    # ── 이전 스냅샷 (변화 비교용)
    prev_period = None
    if len(period_options) >= 2:
        idx = period_options.index(selected_period)
        if idx < len(period_options) - 1:
            prev_period = period_options[idx + 1]
    df_prev = df_vis[df_vis["period_label"] == prev_period].copy() if prev_period else None

    # ── 총 방문자 KPI
    total_row = df_cur[df_cur["sheet"] == "총_방문자"]
    total_visitors = int(total_row["count"].iloc[0]) if len(total_row) > 0 and pd.notna(total_row["count"].iloc[0]) else None

    prev_total = None
    if df_prev is not None:
        pr = df_prev[df_prev["sheet"] == "총_방문자"]
        if len(pr) > 0 and pd.notna(pr["count"].iloc[0]):
            prev_total = int(pr["count"].iloc[0])

    kv1, kv2, kv3 = st.columns(3)
    kv1.metric(
        "총 방문자 (추정)",
        f"{total_visitors:,}" if total_visitors else "-",
        delta=(
            f"{((total_visitors - prev_total) / prev_total * 100):+.1f}%"
            if total_visitors and prev_total else None
        ),
    )
    kv2.metric("분석 기간", selected_period)
    kv3.metric("이전 기간", prev_period or "-")

    st.divider()

    # ── 분류별 차트 (최대 5개 항목)
    _SHEET_LABELS = {
        "직급"     : "직급별 방문자 구성",
        "직종"     : "직종별 방문자 구성",
        "업계"     : "업계별 방문자 구성",
        "회사 규모": "회사 규모별 방문자 구성",
        "지역"     : "지역별 방문자 구성",
    }

    for sname, label in _SHEET_LABELS.items():
        sub_cur = (
            df_cur[df_cur["sheet"] == sname]
            .dropna(subset=["label"])
            .sort_values("rank")
            .head(5)
        )
        if sub_cur.empty:
            continue

        with st.container():
            st.markdown(f"**{label}**")

            # 이전 기간 비교 병합
            if df_prev is not None:
                sub_prev = (
                    df_prev[df_prev["sheet"] == sname]
                    .dropna(subset=["label"])
                    .rename(columns={"pct": "pct_prev", "count": "count_prev"})
                    [["label", "pct_prev", "count_prev"]]
                )
                sub_cur = sub_cur.merge(sub_prev, on="label", how="left")
                sub_cur["delta_pct"] = sub_cur["pct"] - sub_cur["pct_prev"]
            else:
                sub_cur["delta_pct"] = np.nan

            # 차트
            use_pct = sub_cur["pct"].notna().any()
            y_col   = "pct" if use_pct else "count"
            y_label = "비율(%)" if use_pct else "방문자 수"

            fig = px.bar(
                sub_cur.sort_values(y_col, ascending=True),
                x=y_col, y="label", orientation="h",
                color_discrete_sequence=["#3B82F6"],
                height=max(200, len(sub_cur) * 40),
                labels={y_col: y_label, "label": ""},
            )
            fig.update_layout(margin=dict(l=0, r=20, t=10, b=0))
            st.plotly_chart(fig, use_container_width=True)

            # 표 (변화율 포함)
            tbl_rows = []
            for _, r in sub_cur.iterrows():
                val_str = f"{r[y_col]:.1f}%" if use_pct and pd.notna(r[y_col]) else (
                    f"{int(r['count']):,}" if pd.notna(r.get("count")) else "-"
                )
                delta = r.get("delta_pct")
                delta_str = (
                    f"{delta:+.1f}%p" if pd.notna(delta) else "-"
                ) if df_prev is not None else ""

                row_d = {"항목": r["label"], "비율/수치": val_str}
                if df_prev is not None:
                    row_d["전기 대비"] = delta_str
                tbl_rows.append(row_d)

            st.dataframe(
                pd.DataFrame(tbl_rows),
                use_container_width=True, hide_index=True,
            )

    if df_prev is None and len(snapshots) == 1:
        st.caption("방문자 데이터를 추가 업로드하면 기간별 변화를 비교할 수 있습니다.")


# ══════════════════════════════════════════════════════════════════════
# 고급·보조 기능
# ══════════════════════════════════════════════════════════════════════

def _render_advanced(df: pd.DataFrame, prefix: str, ss_df: str) -> None:
    with st.expander("⚙️ 고급·보조 기능 (수동 등록 / CSV)"):
        st.caption(
            "아래 기능은 LinkedIn Content Excel 업로드로 커버되지 않는 경우에만 사용하세요."
        )

        adv1, adv2 = st.tabs(["📝 게시물 수동 등록", "📂 CSV 직접 불러오기"])

        with adv1:
            _render_manual_form(df, prefix, ss_df)

        with adv2:
            uploaded_csv = st.file_uploader(
                "linkedin_posts.csv 형식 파일",
                type="csv",
                key=f"{prefix}csv_up",
            )
            if uploaded_csv:
                try:
                    df_up = _cast(pd.read_csv(uploaded_csv, dtype=str))
                    mask = df_up["post_id"].isna() | (df_up["post_id"].astype(str).str.strip() == "")
                    import hashlib
                    df_up.loc[mask, "post_id"] = df_up.loc[mask].apply(
                        lambda r: hashlib.md5(str(r["url"]).encode()).hexdigest()[:12], axis=1
                    )
                    st.dataframe(df_up.head(5), use_container_width=True)
                    if st.button("✅ 이 데이터로 교체", key=f"{prefix}csv_apply"):
                        st.session_state[ss_df] = df_up
                        _save(df_up, "feat: LinkedIn CSV 직접 불러오기")
                        st.success("불러오기 완료!")
                        st.rerun()
                except Exception as e:
                    st.error(f"CSV 오류: {e}")


def _render_manual_form(df: pd.DataFrame, prefix: str, ss_df: str) -> None:
    import hashlib
    from datetime import date

    with st.form(key=f"{prefix}manual_form", border=True):
        st.markdown("**게시물 성과 수동 등록**")
        st.caption("LinkedIn Content Excel에 포함되지 않은 게시물을 직접 입력합니다.")

        c1, c2 = st.columns(2)
        with c1:
            f_date = st.date_input("게시일 *", value=date.today(), key=f"{prefix}mf_date")
            f_url  = st.text_input("LinkedIn 게시물 URL *", key=f"{prefix}mf_url",
                                   placeholder="https://www.linkedin.com/feed/update/…")
            f_text = st.text_area("게시물 본문 (해시태그 자동 추출)",
                                  key=f"{prefix}mf_text", height=100)
        with c2:
            f_imp = st.number_input("노출수 *", min_value=0, key=f"{prefix}mf_imp")
            f_clk = st.number_input("클릭",      min_value=0, key=f"{prefix}mf_clk")
            f_rea = st.number_input("추천(반응)", min_value=0, key=f"{prefix}mf_rea")
            f_com = st.number_input("댓글",       min_value=0, key=f"{prefix}mf_com")
            f_rep = st.number_input("퍼감",       min_value=0, key=f"{prefix}mf_rep")
            f_eng = st.number_input("참여율 (%)", min_value=0.0, step=0.1, key=f"{prefix}mf_eng")

        submitted = st.form_submit_button("등록", use_container_width=True, type="primary")

        if submitted:
            errs = []
            if not f_url.strip():
                errs.append("LinkedIn URL을 입력하세요.")
            if f_imp <= 0:
                errs.append("노출수는 1 이상이어야 합니다.")
            if errs:
                for e in errs:
                    st.error(e)
            else:
                url      = f_url.strip().rstrip("/")
                text     = f_text.strip()
                hashtags = li.extract_hashtags(text)
                now_str  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                pid      = hashlib.md5(url.encode()).hexdigest()[:12]

                new_row = pd.DataFrame([{
                    "post_id"        : pid,
                    "url"            : url,
                    "published_at"   : str(f_date),
                    "title"          : text[:80],
                    "text"           : text,
                    "post_format"    : "",
                    "campaign"       : "",
                    "content_type"   : "",
                    "hashtags"       : hashtags,
                    "impressions"    : f_imp,
                    "views"          : np.nan,
                    "external_views" : np.nan,
                    "clicks"         : f_clk if f_clk > 0 else np.nan,
                    "ctr"            : (f_clk / f_imp) if f_imp > 0 and f_clk > 0 else np.nan,
                    "reactions"      : f_rea if f_rea > 0 else np.nan,
                    "comments"       : f_com if f_com > 0 else np.nan,
                    "reposts"        : f_rep if f_rep > 0 else np.nan,
                    "followers"      : np.nan,
                    "engagement_rate": f_eng / 100 if f_eng > 0 else np.nan,
                    "utm_content"    : "",
                    "ga4_sessions"   : np.nan,
                    "added_at"       : now_str,
                    "updated_at"     : now_str,
                }])

                df_new = df[df["url"].astype(str).str.rstrip("/") != url].copy()
                df_new = _cast(pd.concat([df_new, new_row], ignore_index=True))
                ok = _save(df_new, f"feat: LinkedIn 게시물 수동 등록 — {url[:40]}")
                st.session_state[ss_df] = df_new
                if ok:
                    st.success("✅ 등록 완료!")
                else:
                    st.warning("⚠️ 로컬 저장 완료 (GitHub 동기화 실패)")
                st.rerun()
