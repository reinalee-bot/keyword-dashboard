"""
linkedin_tab.py — 📣 LinkedIn 키워드·콘텐츠 성과 탭

목적:
  LinkedIn Content Excel을 기반으로,
  특정 키워드·해시태그를 포함한 게시물이 LinkedIn 내에서 기록한
  노출·클릭·반응·참여율을 관찰한다.

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

# ── 상수 ──────────────────────────────────────────────────────────────
_CSV_PATH  = "data/linkedin_posts.csv"
_LOCAL_CSV = os.path.join(os.path.dirname(__file__), _CSV_PATH)

_COLS = [
    "post_id", "url", "published_at", "title", "text",
    "post_format", "campaign", "content_type", "hashtags",
    "impressions", "views", "external_views", "clicks", "ctr",
    "reactions", "comments", "reposts", "followers", "engagement_rate",
    "utm_content", "ga4_sessions",   # 미래 연동용 구조 보존, UI에서 미표시
    "added_at", "updated_at",
]

_NUM_COLS = [
    "impressions", "views", "external_views", "clicks", "ctr",
    "reactions", "comments", "reposts", "followers", "engagement_rate",
]


# ── 데이터 로드·저장 ──────────────────────────────────────────────────

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


# ── 공개 렌더 함수 ────────────────────────────────────────────────────

@st.fragment
def render(prefix: str = "li_") -> None:
    """dashboard.py 에서 `with tab5: linkedin_tab.render()` 로 호출합니다."""

    ss_df = f"{prefix}df"
    if ss_df not in st.session_state:
        st.session_state[ss_df] = _load()

    df: pd.DataFrame = st.session_state[ss_df]

    # ── 업로드 섹션 (최상단 CTA)
    _render_upload(df, prefix, ss_df)

    # 업로드 후 데이터 재조회
    df = st.session_state[ss_df]

    if len(df) == 0:
        _render_empty_state()
        _render_advanced(df, prefix, ss_df)
        return

    # ── 분석 화면
    df_c = _enrich(df)

    sub1, sub2, sub3 = st.tabs(["📊 성과 요약", "📋 게시물 목록", "#️⃣ 해시태그 관찰"])
    with sub1:
        _render_summary(df_c, prefix)
    with sub2:
        _render_list(df_c, prefix)
    with sub3:
        _render_hashtags(df_c, prefix)

    # ── 고급·보조 기능 (접힌 상태)
    _render_advanced(df, prefix, ss_df)


# ── 업로드 섹션 ───────────────────────────────────────────────────────

def _render_upload(df: pd.DataFrame, prefix: str, ss_df: str) -> None:
    has_data = len(df) > 0

    with st.expander(
        "📥 LinkedIn Content Excel 업로드" + (" (데이터 추가·갱신)" if has_data else ""),
        expanded=not has_data,
    ):
        st.markdown("""
<div style="background:#EFF6FF;border-left:4px solid #3B82F6;
     padding:10px 14px;border-radius:6px;margin-bottom:.75rem;font-size:13px;color:#374151">
LinkedIn Content Excel을 업로드하면 게시물 본문에서 키워드와 해시태그를 자동 추출하고,
해당 키워드를 포함한 게시물의 <b>노출·클릭·반응·참여율</b>을 비교합니다.<br>
결과는 주제, 이미지, 게시 시점 등의 영향을 함께 받는 <b>관찰치</b>이며
키워드 또는 해시태그 단독 효과를 뜻하지 않습니다.
</div>""", unsafe_allow_html=True)

        uploaded = st.file_uploader(
            "LinkedIn Content 내보내기 파일 (.xls / .xlsx / .csv)",
            type=["xls", "xlsx", "csv"],
            key=f"{prefix}upload",
            label_visibility="collapsed",
        )

        if not uploaded:
            st.caption("파일을 올리면 자동으로 분석이 시작됩니다.")
            return

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

        # ── 미리보기
        n_total = len(new_rows)
        n_dup   = sum(1 for r in new_rows
                      if r["url"].rstrip("/") in
                      {str(u).rstrip("/") for u in df["url"] if pd.notna(u) and str(u).strip()})
        n_new   = n_total - n_dup

        dates = [r["published_at"] for r in new_rows if r["published_at"]]
        period = f"{min(dates)} ~ {max(dates)}" if dates else "-"

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("전체 게시물", n_total)
        m2.metric("신규", n_new)
        m3.metric("갱신 (기존 URL)", n_dup)
        m4.metric("기간", period)

        # 미리보기 테이블 (간략)
        prev = pd.DataFrame([{
            "게시일"    : r["published_at"],
            "게시물 요약": r["title"][:45] + "…" if len(r["title"]) > 45 else r["title"],
            "해시태그"  : r["hashtags"] or "(없음)",
            "노출수"    : r["impressions"],
            "클릭"      : r["clicks"],
            "참여율"    : f"{r['engagement_rate']*100:.1f}%" if r["engagement_rate"] and not np.isnan(r["engagement_rate"]) else "-",
        } for r in new_rows])
        st.dataframe(prev, use_container_width=True, height=220)

        st.divider()

        # 통계 시트 안내 (있을 때)
        if df_stats is not None:
            st.info("💡 `통계` 시트(일별 채널 성과)도 감지됐습니다. 성과 요약 탭의 '일별 추이' 차트에 활용됩니다.", icon="📈")
            if f"{prefix}stats_df" not in st.session_state:
                st.session_state[f"{prefix}stats_df"] = df_stats

        if st.button(
            f"✅ 가져오기 확정  (신규 {n_new}건 추가 · 갱신 {n_dup}건)",
            type="primary",
            key=f"{prefix}confirm",
            use_container_width=True,
        ):
            with st.spinner("저장 중..."):
                df_merged, stats = li.merge_posts(df.copy(), new_rows)
                df_merged = _cast(df_merged)
                ok = _save(df_merged, f"feat: LinkedIn Content 가져오기 — 신규{stats['new']} 갱신{stats['updated']}")

            st.session_state[ss_df] = df_merged
            if ok:
                st.success(f"✅ 저장 완료 — 신규 {stats['new']}건, 갱신 {stats['updated']}건")
            else:
                st.warning(f"⚠️ 로컬 저장 완료 (GitHub 동기화 실패) — 신규 {stats['new']}건, 갱신 {stats['updated']}건")
            st.rerun()


# ── 빈 상태 ───────────────────────────────────────────────────────────

def _render_empty_state() -> None:
    st.markdown("""
<div style="text-align:center;padding:3rem 1rem;color:#94A3B8">
  <div style="font-size:2.5rem">📣</div>
  <div style="font-size:1.1rem;font-weight:600;margin:.5rem 0">
    LinkedIn Content Excel을 업로드하면 성과 분석이 시작됩니다</div>
  <div style="font-size:13px">
    LinkedIn 관리자 &gt; 분석 &gt; 게시물 &gt; 내보내기(.xls/.xlsx)
  </div>
</div>""", unsafe_allow_html=True)


# ── 지표 보강 ─────────────────────────────────────────────────────────

def _enrich(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["_pub"] = pd.to_datetime(df["published_at"], errors="coerce")
    # pct 표시용 (소수 → %)
    df["_ctr_pct"]    = df["ctr"].apply(lambda x: x * 100 if pd.notna(x) else np.nan)
    df["_eng_pct"]    = df["engagement_rate"].apply(lambda x: x * 100 if pd.notna(x) else np.nan)
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


# ── 성과 요약 탭 ──────────────────────────────────────────────────────

def _render_summary(df: pd.DataFrame, prefix: str) -> None:
    st.markdown("#### 📊 성과 요약")

    imp  = df["impressions"].sum()
    clk  = df["clicks"].sum()
    eng_med = df["_eng_pct"].median()
    n    = len(df)

    # ── KPI 행
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("게시물 수",   f"{n:,}")
    k2.metric("총 노출수",   f"{imp:,.0f}")
    k3.metric("총 클릭수",   f"{clk:,.0f}")
    k4.metric("중앙값 참여율", _fmt(eng_med, pct=True))
    ctr_med = df["_ctr_pct"].median()
    k5.metric("중앙값 CTR", _fmt(ctr_med, pct=True))

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
        _best("_eng_pct", "🏆 최고 참여율", lambda v: f"{v:.1f}%")
    with c2:
        _best("clicks",   "🖱️ 최고 클릭수", lambda v: f"{v:,.0f}회")
    with c3:
        _best("impressions", "👁 최고 노출수", lambda v: f"{v:,.0f}회")

    # ── 자동 요약 문장
    try:
        top_eng = df.loc[df["_eng_pct"].dropna().idxmax() if df["_eng_pct"].notna().any() else 0]
        top_clk = df.loc[df["clicks"].dropna().idxmax() if df["clicks"].notna().any() else 0]
        summary = (
            f"분석 기간({df['_pub'].min().strftime('%Y-%m-%d') if df['_pub'].notna().any() else '?'}"
            f" ~ {df['_pub'].max().strftime('%Y-%m-%d') if df['_pub'].notna().any() else '?'})에 "
            f"총 **{n}개** 게시물을 발행했습니다. "
            f"**{top_eng['title'][:30]}…** 이 참여율 **{top_eng['_eng_pct']:.1f}%** 로 가장 높았고, "
            f"**{top_clk['title'][:30]}…** 이 **{int(top_clk['impressions']):,}회** 노출·**{int(top_clk['clicks']):,}회** 클릭으로 LinkedIn 내 도달과 관심을 가장 많이 만들었습니다."
        )
        st.info(summary)
    except Exception:
        pass

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

    # 통계 시트 일별 추이 (있으면)
    _render_stats_trend(prefix)


def _render_stats_trend(prefix: str) -> None:
    df_s = st.session_state.get(f"{prefix}stats_df")
    if df_s is None or len(df_s) == 0:
        return
    # 날짜 컬럼 자동 탐지
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


# ── 게시물 목록 탭 ────────────────────────────────────────────────────

def _render_list(df: pd.DataFrame, prefix: str) -> None:
    st.markdown("#### 📋 게시물 목록")

    # 필터 행
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

    # 표 렌더링
    display_rows = []
    for _, r in df_f.iterrows():
        display_rows.append({
            "게시일"    : str(r["_pub"].date()) if pd.notna(r["_pub"]) else "-",
            "게시물 요약": r["title"],
            "해시태그"  : r["hashtags"] or "-",
            "노출"      : _fmt(r["impressions"]),
            "클릭"      : _fmt(r["clicks"]),
            "CTR"       : _fmt(r["_ctr_pct"], pct=True),
            "반응"      : _fmt(r["reactions"]),
            "댓글"      : _fmt(r["comments"]),
            "퍼감"      : _fmt(r["reposts"]),
            "참여율"    : _fmt(r["_eng_pct"], pct=True),
            "원문"      : r["url"],
        })

    df_disp = pd.DataFrame(display_rows)
    st.dataframe(
        df_disp,
        use_container_width=True,
        height=420,
        column_config={
            "원문": st.column_config.LinkColumn("원문", display_text="링크"),
            "게시물 요약": st.column_config.TextColumn("게시물 요약", width="large"),
        },
    )
    st.caption(f"총 {len(df_f)}건")

    # CSV 내보내기
    csv_bytes = df_f.drop(
        columns=[c for c in df_f.columns if c.startswith("_")], errors="ignore"
    ).to_csv(index=False).encode("utf-8-sig")
    st.download_button("⬇ CSV 내보내기", csv_bytes,
                       file_name="linkedin_posts.csv", mime="text/csv",
                       key=f"{prefix}csv_dl")


# ── 해시태그 관찰 탭 ──────────────────────────────────────────────────

def _render_hashtags(df: pd.DataFrame, prefix: str) -> None:
    st.markdown("#### #️⃣ 해시태그 관찰")

    st.warning(
        "해시태그별 결과는 게시 주제·이미지·게시 시간·광고 여부 등의 영향을 함께 받는 **관찰치**이며, "
        "해시태그 단독 효과나 인과관계를 의미하지 않습니다.",
        icon="⚠️",
    )

    # 해시태그별 집계
    records: list[dict] = []
    tag_posts: dict[str, list[int]] = {}

    for i, row in df.iterrows():
        tags = [t.strip() for t in str(row.get("hashtags", "") or "").split(",") if t.strip()]
        for tag in tags:
            tag_posts.setdefault(tag, []).append(i)

    for tag, idxs in tag_posts.items():
        sub = df.loc[idxs]
        n = len(sub)
        records.append({
            "해시태그"        : tag,
            "게시물 수"       : n,
            "총 노출수"       : sub["impressions"].sum(),
            "중앙값 노출"     : sub["impressions"].median(),
            "총 클릭"         : sub["clicks"].sum(),
            "중앙값 클릭"     : sub["clicks"].median(),
            "중앙값 참여율"   : sub["_eng_pct"].median(),
            "_n"              : n,
        })

    if not records:
        st.info("해시태그 데이터가 없습니다. 게시물 본문에 #태그가 포함된 게시물을 가져오면 자동 분석됩니다.")
        return

    df_ht = pd.DataFrame(records).sort_values("총 노출수", ascending=False)

    # 상시 태그 감지 (전체 게시물 >= 80% 이상 등장)
    total_posts = len(df)
    always_tags = {r["해시태그"] for r in records if r["_n"] / total_posts >= 0.8}

    df_rank = df_ht[df_ht["_n"] >= 3].copy()  # 3건 이상만 비교
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

        # 차트
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


# ── 고급·보조 기능 ────────────────────────────────────────────────────

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
                                  key=f"{prefix}mf_text", height=100,
                                  placeholder="#SCK #AI보안 게시물 내용을 붙여넣으면 해시태그가 자동 추출됩니다.")
        with c2:
            f_imp = st.number_input("노출수 *", min_value=0, key=f"{prefix}mf_imp")
            f_clk = st.number_input("클릭", min_value=0, key=f"{prefix}mf_clk")
            f_rea = st.number_input("추천(반응)", min_value=0, key=f"{prefix}mf_rea")
            f_com = st.number_input("댓글", min_value=0, key=f"{prefix}mf_com")
            f_rep = st.number_input("퍼감", min_value=0, key=f"{prefix}mf_rep")
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
                url = f_url.strip().rstrip("/")
                text = f_text.strip()
                hashtags = li.extract_hashtags(text)
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                pid = hashlib.md5(url.encode()).hexdigest()[:12]

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
                    "utm_content"    : "",    # 미래 연동 구조 보존
                    "ga4_sessions"   : np.nan,
                    "added_at"       : now_str,
                    "updated_at"     : now_str,
                }])

                # 중복 URL 제거 후 추가
                df_new = df[df["url"].astype(str).str.rstrip("/") != url].copy()
                df_new = _cast(pd.concat([df_new, new_row], ignore_index=True))
                ok = _save(df_new, f"feat: LinkedIn 게시물 수동 등록 — {url[:40]}")
                st.session_state[ss_df] = df_new
                if ok:
                    st.success("✅ 등록 완료!")
                else:
                    st.warning("⚠️ 로컬 저장 완료 (GitHub 동기화 실패)")
                st.rerun()
