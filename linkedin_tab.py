"""
linkedin_tab.py — 📣 LinkedIn 성과 분석 탭

LinkedIn 게시물 분석 수치를 수동 입력하고,
해시태그별 관찰 성과를 비교하는 모듈입니다.

저장: data/linkedin_posts.csv (GitHub 동기화 패턴 동일)
주의: LinkedIn 로그인/크롤링/비공식 API 미사용
"""

from __future__ import annotations

import io
import os
import re
from datetime import date, datetime

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import github_storage as gh

# ── 상수 ─────────────────────────────────────────────────────
_LINKEDIN_CSV   = "data/linkedin_posts.csv"
_LINKEDIN_LOCAL = os.path.join(os.path.dirname(__file__), _LINKEDIN_CSV)

_DASHBOARD_URL  = "https://keyword-dashboard-4dqkm8snau6crfozatwbcg.streamlit.app/"

_CONTENT_TYPES  = [
    "뉴스 공유", "인사이트", "행사", "채용·조직문화", "제품·솔루션", "기타"
]

_DISCOVERY_PATHS = [
    "키워드 대시보드 발굴",
    "기존 상시 해시태그",
    "직접 리서치",
    "혼합",
]

_COLS = [
    "post_id",          # UUID-like: published_at + title 해시
    "published_at",     # 게시일 (YYYY-MM-DD)
    "title",            # 게시물 제목/식별명
    "url",              # LinkedIn 게시물 URL
    "content_type",     # 콘텐츠 유형
    "campaign",         # 주요 주제/캠페인명
    "hashtags",         # 정규화된 해시태그, 쉼표 구분
    "discovery_path",   # 키워드 발굴 경로
    "source_keywords",  # 대시보드에서 발굴한 원본 키워드
    "impressions",      # 노출수
    "reactions",        # 반응 수
    "comments",         # 댓글 수
    "reposts",          # 리포스트 수
    "link_clicks",      # 링크 클릭 수 (선택)
    "ga4_sessions",     # GA4 대시보드 유입 세션 (선택)
    "utm_content",      # UTM content 값 (선택)
    "promotion",        # Organic / Paid·Boosted
    "measured_at",      # 수치 확인일 (YYYY-MM-DD)
    "note",             # 비고
    "added_at",         # 등록 시각
]


# ── 데이터 로드·저장 ──────────────────────────────────────────

def _load() -> pd.DataFrame:
    """GitHub → 로컬 순서로 CSV를 로드. 없으면 빈 DataFrame."""
    df = gh.read_csv(_LINKEDIN_CSV)
    if df is not None and len(df) > 0:
        return _cast(df)

    if os.path.exists(_LINKEDIN_LOCAL):
        try:
            df = pd.read_csv(_LINKEDIN_LOCAL, dtype=str)
            return _cast(df)
        except Exception:
            pass

    return pd.DataFrame(columns=_COLS)


def _cast(df: pd.DataFrame) -> pd.DataFrame:
    """타입 보정 및 누락 컬럼 보충."""
    for col in _COLS:
        if col not in df.columns:
            df[col] = ""
    num_cols = ["impressions", "reactions", "comments", "reposts",
                "link_clicks", "ga4_sessions"]
    for c in num_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df[_COLS].copy()


def _save(df: pd.DataFrame, msg: str) -> bool:
    """로컬 + GitHub에 저장."""
    os.makedirs(os.path.dirname(_LINKEDIN_LOCAL), exist_ok=True)
    df.to_csv(_LINKEDIN_LOCAL, index=False, encoding="utf-8")
    return gh.write_csv(df, _LINKEDIN_CSV, msg)


def _make_id(published_at: str, title: str) -> str:
    import hashlib
    raw = f"{published_at}|{title}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


# ── 해시태그 정규화 ───────────────────────────────────────────

def _normalize_hashtags(raw: str) -> str:
    """
    쉼표/줄바꿈 구분 → # 추가, 소문자 비교용 정규화, 중복 제거.
    저장 형태: #aIAgent → #aiagent (소문자)
    """
    tags = re.split(r"[,\n\r]+", raw)
    seen = set()
    result = []
    for t in tags:
        t = t.strip().lstrip("#").strip()
        if not t:
            continue
        normalized = "#" + re.sub(r"\s+", "", t).lower()
        if normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return ", ".join(result)


# ── 지표 계산 ─────────────────────────────────────────────────

def _calc(df: pd.DataFrame) -> pd.DataFrame:
    """자동 계산 지표 컬럼을 추가한 DataFrame 반환."""
    df = df.copy()
    imp = pd.to_numeric(df["impressions"], errors="coerce")
    rea = pd.to_numeric(df["reactions"],   errors="coerce")
    com = pd.to_numeric(df["comments"],    errors="coerce")
    rep = pd.to_numeric(df["reposts"],     errors="coerce")
    lnk = pd.to_numeric(df["link_clicks"], errors="coerce")
    ga4 = pd.to_numeric(df["ga4_sessions"], errors="coerce")

    df["_engage_total"] = rea.fillna(0) + com.fillna(0) + rep.fillna(0)
    df["_engage_rate"]  = (df["_engage_total"] / imp * 100).where(imp > 0)
    df["_ctr"]          = (lnk / imp * 100).where(imp > 0)
    df["_ga4_rate"]     = (ga4 / lnk * 100).where(lnk > 0)
    df["_hashtag_cnt"]  = df["hashtags"].apply(
        lambda x: len([h for h in str(x).split(",") if h.strip()]) if pd.notna(x) and str(x).strip() else 0
    )
    return df


def _fmt(val, pct=False, na="-"):
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return na
    if pct:
        return f"{val:.1f}%"
    return f"{val:,.0f}"


# ── UTM 링크 생성 ─────────────────────────────────────────────

def _build_utm(utm_content: str, promotion: str) -> str:
    medium = "paid_social" if "Paid" in promotion else "organic_social"
    uc = utm_content.strip()
    if not uc:
        return ""
    return (
        f"{_DASHBOARD_URL}"
        f"?utm_source=linkedin&utm_medium={medium}"
        f"&utm_campaign=keyword_dashboard&utm_content={uc}"
    )


# ── 탭 렌더링 (공개 함수) ─────────────────────────────────────

def render(prefix: str = "li_") -> None:
    """dashboard.py 에서 `with tab5: linkedin_tab.render()` 로 호출합니다."""

    # ── 세션 상태 초기화
    _ss_key = f"{prefix}df"
    _edit_key = f"{prefix}edit_id"
    if _ss_key not in st.session_state:
        st.session_state[_ss_key] = _load()
    if _edit_key not in st.session_state:
        st.session_state[_edit_key] = None

    df: pd.DataFrame = st.session_state[_ss_key]

    # ── 헤더
    st.markdown("""
<div style="background:#F0F4FF;border-left:4px solid #2F6BFF;
     padding:12px 16px;border-radius:6px;margin-bottom:1rem;font-size:13px;color:#374151">
LinkedIn 게시물 분석에서 확인한 수치를 입력하면,
해시태그·키워드 조합별 노출 및 반응 성과를 비교할 수 있습니다.
게시 주제, 이미지, 문안, 게시 시간 등도 성과에 영향을 주므로
<strong>결과는 참고용 상관관계로 해석합니다.</strong>
</div>""", unsafe_allow_html=True)

    # ── 상단 버튼 행
    col_btn1, col_btn2, col_btn3, _ = st.columns([1.5, 1.5, 1.5, 6])
    with col_btn1:
        show_form = st.button("➕ 게시물 성과 등록", key=f"{prefix}btn_add",
                              use_container_width=True)
    with col_btn2:
        if len(df) > 0:
            csv_dl = df.drop(columns=[c for c in df.columns if c.startswith("_")],
                             errors="ignore").to_csv(index=False).encode("utf-8")
            st.download_button("⬇ CSV 내보내기", csv_dl,
                               file_name="linkedin_posts.csv",
                               mime="text/csv", key=f"{prefix}csv_dl",
                               use_container_width=True)
    with col_btn3:
        # CSV 양식 다운로드
        template = pd.DataFrame(columns=[c for c in _COLS if c not in ("post_id","added_at")])
        t_bytes = template.to_csv(index=False).encode("utf-8")
        st.download_button("📄 CSV 양식", t_bytes,
                           file_name="linkedin_posts_template.csv",
                           mime="text/csv", key=f"{prefix}csv_tmpl",
                           use_container_width=True)

    # ── CSV 불러오기
    with st.expander("📂 CSV 불러오기"):
        uploaded = st.file_uploader("linkedin_posts.csv 형식",
                                    type="csv", key=f"{prefix}csv_up")
        if uploaded:
            try:
                df_up = pd.read_csv(uploaded, dtype=str)
                df_up = _cast(df_up)
                # post_id 없으면 생성
                mask = df_up["post_id"].isna() | (df_up["post_id"].astype(str).str.strip() == "")
                df_up.loc[mask, "post_id"] = df_up.loc[mask].apply(
                    lambda r: _make_id(str(r["published_at"]), str(r["title"])), axis=1)
                if st.button("✅ 이 데이터로 교체", key=f"{prefix}csv_apply"):
                    st.session_state[_ss_key] = df_up
                    _save(df_up, "feat: LinkedIn 게시물 CSV 불러오기")
                    st.success("불러오기 완료!")
                    st.rerun()
            except Exception as e:
                st.error(f"CSV 오류: {e}")

    # ── 등록/수정 폼
    edit_id = st.session_state.get(_edit_key)
    edit_row = None
    if edit_id:
        rows = df[df["post_id"] == edit_id]
        edit_row = rows.iloc[0] if len(rows) > 0 else None

    if show_form or edit_row is not None:
        _render_form(df, edit_row, prefix, _ss_key, _edit_key)
        st.divider()

    # ── 빈 상태
    if len(df) == 0:
        st.markdown("""
<div style="text-align:center;padding:3rem;color:#94A3B8">
  <div style="font-size:2.5rem">📣</div>
  <div style="font-size:1.1rem;font-weight:600;margin:.5rem 0">
    LinkedIn 게시물 분석에서 수치를 등록하면 해시태그별 성과 비교가 시작됩니다</div>
  <div style="font-size:13px">위 ➕ 게시물 성과 등록 버튼으로 첫 게시물을 입력하세요.</div>
</div>""", unsafe_allow_html=True)
        return

    # ── 계산 지표 추가
    df_c = _calc(df)

    # ── 분석 서브탭
    sub1, sub2, sub3, sub4 = st.tabs([
        "📋 게시물 목록", "📊 요약 KPI", "#️⃣ 해시태그 분석", "📈 차트"
    ])

    with sub1:
        _render_list(df_c, df, prefix, _ss_key, _edit_key)

    with sub2:
        _render_kpi(df_c, prefix)

    with sub3:
        _render_hashtags(df_c, prefix)

    with sub4:
        _render_charts(df_c, prefix)


# ── 게시물 등록/수정 폼 ───────────────────────────────────────

def _render_form(df: pd.DataFrame, edit_row, prefix: str, ss_key: str, edit_key: str):
    is_edit = edit_row is not None
    title_str = "✏️ 게시물 수정" if is_edit else "➕ 게시물 성과 등록"

    def _get(col, default=""):
        if is_edit and col in edit_row.index:
            v = edit_row[col]
            return default if (v is None or (isinstance(v, float) and np.isnan(v))) else v
        return default

    with st.form(key=f"{prefix}post_form", border=True):
        st.markdown(f"**{title_str}**")
        st.caption("LinkedIn 게시물 분석 화면에서 확인한 수치를 직접 입력하세요.")

        col1, col2 = st.columns(2)
        with col1:
            f_date = st.date_input("게시일 *", value=pd.to_datetime(_get("published_at", date.today())).date()
                                   if _get("published_at") else date.today(),
                                   key=f"{prefix}f_date")
            f_title = st.text_input("게시물 제목 또는 식별명 *",
                                    value=str(_get("title")), key=f"{prefix}f_title",
                                    placeholder="예: AI 에이전트 트렌드 인사이트")
            f_url = st.text_input("LinkedIn 게시물 URL *",
                                  value=str(_get("url")), key=f"{prefix}f_url",
                                  placeholder="https://www.linkedin.com/feed/update/urn:li:activity:...")
            f_ct = st.selectbox("콘텐츠 유형 *", _CONTENT_TYPES,
                                index=_CONTENT_TYPES.index(_get("content_type", _CONTENT_TYPES[0]))
                                if _get("content_type") in _CONTENT_TYPES else 0,
                                key=f"{prefix}f_ct")
            f_campaign = st.text_input("주요 주제 또는 캠페인명 *",
                                       value=str(_get("campaign")), key=f"{prefix}f_campaign",
                                       placeholder="예: AI 에이전트")
            f_hashtags = st.text_area("해시태그 *  (쉼표 또는 줄바꿈 구분)",
                                      value=str(_get("hashtags")), key=f"{prefix}f_tags",
                                      placeholder="#AIAgent, #AgentOps, #MicrosoftCopilot",
                                      height=90)
            f_discovery = st.selectbox(
                "키워드 발굴 경로 *", _DISCOVERY_PATHS,
                index=_DISCOVERY_PATHS.index(_get("discovery_path", _DISCOVERY_PATHS[0]))
                if _get("discovery_path") in _DISCOVERY_PATHS else 0,
                key=f"{prefix}f_disc",
            )
            f_src_kw = st.text_input(
                "대시보드에서 발굴한 원본 키워드  (선택, 쉼표 구분)",
                value=str(_get("source_keywords")), key=f"{prefix}f_srckw",
                placeholder="AI Agent, Zero Trust, Copilot",
                help="발굴 경로가 '키워드 대시보드 발굴' 또는 '혼합'일 때 입력하면 분석에 활용됩니다.",
            )
        with col2:
            f_measured = st.date_input("수치 확인일 *",
                                       value=pd.to_datetime(_get("measured_at", date.today())).date()
                                       if _get("measured_at") else date.today(),
                                       key=f"{prefix}f_measured")
            f_imp  = st.number_input("노출수 (Impressions) *", min_value=0,
                                     value=int(_get("impressions", 0) or 0), key=f"{prefix}f_imp")
            f_rea  = st.number_input("반응 수 (Reactions) *", min_value=0,
                                     value=int(_get("reactions", 0) or 0), key=f"{prefix}f_rea")
            f_com  = st.number_input("댓글 수 (Comments) *", min_value=0,
                                     value=int(_get("comments", 0) or 0), key=f"{prefix}f_com")
            f_rep  = st.number_input("공유·리포스트 수 (Reposts) *", min_value=0,
                                     value=int(_get("reposts", 0) or 0), key=f"{prefix}f_rep")
            f_lnk  = st.number_input("링크 클릭 수 (Link clicks, 없으면 0)", min_value=0,
                                     value=int(_get("link_clicks", 0) or 0), key=f"{prefix}f_lnk")
            f_ga4  = st.number_input("대시보드 GA4 유입 세션 (없으면 0)", min_value=0,
                                     value=int(_get("ga4_sessions", 0) or 0), key=f"{prefix}f_ga4")

        col3, col4 = st.columns(2)
        with col3:
            f_utm = st.text_input("UTM content 값 (선택)",
                                  value=str(_get("utm_content")), key=f"{prefix}f_utm",
                                  placeholder="20261021_ai_agent")
            f_promo = st.selectbox("유료 프로모션 여부", ["Organic", "Paid·Boosted"],
                                   index=0 if _get("promotion", "Organic") == "Organic" else 1,
                                   key=f"{prefix}f_promo")
        with col4:
            f_note = st.text_area("비고 (선택)", value=str(_get("note")),
                                  key=f"{prefix}f_note", height=80)

        # UTM 링크 미리보기
        if f_utm.strip():
            utm_link = _build_utm(f_utm, f_promo)
            st.markdown(f"**🔗 생성된 추적 링크:**")
            st.code(utm_link, language=None)

        save_col, cancel_col = st.columns([1, 3])
        with save_col:
            submitted = st.form_submit_button(
                "저장" if is_edit else "등록", use_container_width=True, type="primary")
        with cancel_col:
            cancelled = st.form_submit_button("취소", use_container_width=True)

        if cancelled:
            st.session_state[edit_key] = None
            st.rerun()

        if submitted:
            # ── 유효성 검사
            errors = []
            if not f_title.strip():
                errors.append("게시물 제목을 입력하세요.")
            if not f_url.strip():
                errors.append("LinkedIn URL을 입력하세요.")
            if f_imp <= 0:
                errors.append("노출수는 1 이상이어야 합니다.")
            if f_hashtags.strip() == "":
                errors.append("해시태그를 1개 이상 입력하세요.")

            # URL 중복 검사 (수정 제외)
            if f_url.strip():
                dup = df[df["url"].astype(str).str.strip() == f_url.strip()]
                if is_edit:
                    dup = dup[dup["post_id"] != edit_row["post_id"]]
                if len(dup) > 0:
                    errors.append(f"이미 등록된 URL입니다: {dup.iloc[0]['title']}")

            if errors:
                for e in errors:
                    st.error(e)
            else:
                post_id = edit_row["post_id"] if is_edit else _make_id(
                    str(f_date), f_title.strip())
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                row = {
                    "post_id"       : post_id,
                    "published_at"  : str(f_date),
                    "title"         : f_title.strip(),
                    "url"           : f_url.strip(),
                    "content_type"  : f_ct,
                    "campaign"      : f_campaign.strip(),
                    "hashtags"      : _normalize_hashtags(f_hashtags),
                    "discovery_path": f_discovery,
                    "source_keywords": f_src_kw.strip(),
                    "impressions" : f_imp,
                    "reactions"   : f_rea,
                    "comments"    : f_com,
                    "reposts"     : f_rep,
                    "link_clicks" : f_lnk if f_lnk > 0 else np.nan,
                    "ga4_sessions": f_ga4 if f_ga4 > 0 else np.nan,
                    "utm_content" : f_utm.strip(),
                    "promotion"   : f_promo,
                    "measured_at" : str(f_measured),
                    "note"        : f_note.strip(),
                    "added_at"    : now_str if not is_edit else _get("added_at", now_str),
                }
                new_row = pd.DataFrame([row])
                if is_edit:
                    df_new = df[df["post_id"] != post_id].copy()
                    df_new = pd.concat([new_row, df_new], ignore_index=True)
                else:
                    df_new = pd.concat([df, new_row], ignore_index=True)

                df_new = df_new[_COLS]
                ok = _save(df_new, f"feat: LinkedIn 게시물 {'수정' if is_edit else '등록'} — {f_title.strip()[:30]}")
                st.session_state[ss_key] = df_new
                st.session_state[edit_key] = None
                if ok:
                    st.success("✅ GitHub에 저장됐습니다.")
                else:
                    st.warning("⚠️ 로컬 저장 완료 (GitHub 동기화 실패 — 토큰 확인 필요)")
                st.rerun()


# ── 게시물 목록 탭 ────────────────────────────────────────────

def _render_list(df_c: pd.DataFrame, df_raw: pd.DataFrame,
                 prefix: str, ss_key: str, edit_key: str):
    st.markdown("#### 게시물 성과 목록")

    # 필터
    f_col1, f_col2, f_col3, f_col4 = st.columns(4)
    with f_col1:
        min_d = pd.to_datetime(df_c["published_at"], errors="coerce").min()
        max_d = pd.to_datetime(df_c["published_at"], errors="coerce").max()
        date_range = st.date_input("기간", value=(min_d.date() if pd.notna(min_d) else date.today(),
                                                   max_d.date() if pd.notna(max_d) else date.today()),
                                   key=f"{prefix}list_dr")
    with f_col2:
        ct_opts = ["전체"] + _CONTENT_TYPES
        sel_ct = st.selectbox("콘텐츠 유형", ct_opts, key=f"{prefix}list_ct")
    with f_col3:
        campaigns = ["전체"] + sorted(df_c["campaign"].dropna().unique().tolist())
        sel_camp = st.selectbox("주제/캠페인", campaigns, key=f"{prefix}list_camp")
    with f_col4:
        sel_promo = st.selectbox("프로모션", ["전체", "Organic", "Paid·Boosted"],
                                 key=f"{prefix}list_promo")

    df_f = df_c.copy()
    df_f["_pub"] = pd.to_datetime(df_f["published_at"], errors="coerce")
    if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
        s, e = pd.Timestamp(date_range[0]), pd.Timestamp(date_range[1])
        df_f = df_f[(df_f["_pub"] >= s) & (df_f["_pub"] <= e)]
    if sel_ct != "전체":
        df_f = df_f[df_f["content_type"] == sel_ct]
    if sel_camp != "전체":
        df_f = df_f[df_f["campaign"] == sel_camp]
    if sel_promo != "전체":
        df_f = df_f[df_f["promotion"] == sel_promo]

    # 특정 해시태그 필터
    tag_filter = st.text_input("특정 해시태그 포함 검색 (예: #aIAgent)",
                                key=f"{prefix}list_tag",
                                placeholder="#aIAgent 또는 aIAgent")
    if tag_filter.strip():
        tq = "#" + tag_filter.strip().lstrip("#").lower()
        df_f = df_f[df_f["hashtags"].astype(str).str.lower().str.contains(tq, na=False)]

    # 정렬: 참여율 높은 순
    df_f = df_f.sort_values("_engage_rate", ascending=False, na_position="last")

    if len(df_f) == 0:
        st.info("조건에 맞는 게시물이 없습니다.")
        return

    # 표시 테이블
    display_rows = []
    for _, r in df_f.iterrows():
        display_rows.append({
            "게시일"      : r["published_at"],
            "제목"        : r["title"],
            "유형"        : r["content_type"],
            "발굴 경로"   : r.get("discovery_path", ""),
            "노출수"      : _fmt(r["impressions"]),
            "참여 수"     : _fmt(r["_engage_total"]),
            "참여율"      : _fmt(r["_engage_rate"], pct=True),
            "CTR"         : _fmt(r["_ctr"], pct=True),
            "GA4 유입"    : _fmt(r["ga4_sessions"]),
            "태그 수"     : int(r["_hashtag_cnt"]) if pd.notna(r["_hashtag_cnt"]) else 0,
            "구분"        : r["promotion"],
            "post_id"     : r["post_id"],
        })
    df_disp = pd.DataFrame(display_rows)
    st.dataframe(df_disp.drop(columns=["post_id"]),
                 use_container_width=True, hide_index=True)

    # 수정/삭제
    st.markdown("**게시물 수정 또는 삭제:**")
    titles = df_f["title"].tolist()
    ids    = df_f["post_id"].tolist()
    sel_title = st.selectbox("게시물 선택", ["— 선택 —"] + titles,
                              key=f"{prefix}list_sel")
    if sel_title != "— 선택 —":
        idx = titles.index(sel_title)
        sel_id = ids[idx]
        edit_col, del_col = st.columns([1, 1])
        with edit_col:
            if st.button("✏️ 수정", key=f"{prefix}btn_edit"):
                st.session_state[edit_key] = sel_id
                st.rerun()
        with del_col:
            if st.button("🗑️ 삭제", key=f"{prefix}btn_del"):
                st.session_state[f"{prefix}del_confirm"] = sel_id

    # 삭제 확인
    del_id = st.session_state.get(f"{prefix}del_confirm")
    if del_id:
        rows = df_raw[df_raw["post_id"] == del_id]
        del_title = rows.iloc[0]["title"] if len(rows) > 0 else del_id
        st.warning(f"'{del_title}' 을 삭제하시겠습니까?")
        c1, c2, _ = st.columns([1, 1, 4])
        with c1:
            if st.button("확인 삭제", type="primary", key=f"{prefix}del_ok"):
                df_new = df_raw[df_raw["post_id"] != del_id].reset_index(drop=True)
                ok = _save(df_new, f"feat: LinkedIn 게시물 삭제 — {del_title[:30]}")
                st.session_state[ss_key] = df_new
                st.session_state[f"{prefix}del_confirm"] = None
                st.success("삭제됐습니다.")
                st.rerun()
        with c2:
            if st.button("취소", key=f"{prefix}del_cancel"):
                st.session_state[f"{prefix}del_confirm"] = None
                st.rerun()


# ── 요약 KPI ─────────────────────────────────────────────────

def _render_kpi(df_c: pd.DataFrame, prefix: str):
    st.markdown("#### 요약 KPI")

    # 기간 필터
    col_dr, col_promo = st.columns([2, 1])
    with col_dr:
        min_d = pd.to_datetime(df_c["published_at"], errors="coerce").min()
        max_d = pd.to_datetime(df_c["published_at"], errors="coerce").max()
        kpi_dr = st.date_input("기간 필터", value=(min_d.date() if pd.notna(min_d) else date.today(),
                                                    max_d.date() if pd.notna(max_d) else date.today()),
                               key=f"{prefix}kpi_dr")
    with col_promo:
        inc_paid = st.checkbox("Paid·Boosted 포함", value=False, key=f"{prefix}kpi_paid")

    df_k = df_c.copy()
    df_k["_pub"] = pd.to_datetime(df_k["published_at"], errors="coerce")
    if isinstance(kpi_dr, (list, tuple)) and len(kpi_dr) == 2:
        s, e = pd.Timestamp(kpi_dr[0]), pd.Timestamp(kpi_dr[1])
        df_k = df_k[(df_k["_pub"] >= s) & (df_k["_pub"] <= e)]

    df_organic = df_k[df_k["promotion"] == "Organic"]
    df_base    = df_k if inc_paid else df_organic

    total      = len(df_base)
    total_imp  = df_base["impressions"].sum()
    avg_er     = df_base["_engage_rate"].mean()
    med_er     = df_base["_engage_rate"].median()
    avg_ctr    = df_base["_ctr"].mean()
    total_ga4  = df_base["ga4_sessions"].sum()
    org_avg_er = df_organic["_engage_rate"].mean() if len(df_organic) > 0 else float("nan")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("등록 게시물", f"{total}건")
    c2.metric("총 노출수", _fmt(total_imp))
    c3.metric("평균 참여율", _fmt(avg_er, pct=True))
    c4.metric("중앙값 참여율", _fmt(med_er, pct=True))

    c5, c6, c7, c8 = st.columns(4)
    c5.metric("평균 링크 클릭률", _fmt(avg_ctr, pct=True))
    c6.metric("GA4 총 유입 세션", _fmt(total_ga4))
    c7.metric("Organic 평균 참여율", _fmt(org_avg_er, pct=True))
    c8.metric("Paid·Boosted 포함", "예" if inc_paid else "아니오 (기본)")

    st.caption("Boosted 게시물은 기본적으로 제외됩니다. 위 체크박스로 포함할 수 있습니다.")

    # ── 발굴 경로 비교 KPI
    st.divider()
    st.markdown("##### 🔍 키워드 발굴 경로별 관찰 비교")
    st.caption(
        "두 그룹의 평균·중앙값 참여율과 링크 클릭률을 비교합니다. "
        "발굴 경로 외에도 콘텐츠 품질·시간 등 다양한 변수가 영향을 주므로 인과관계로 단정하지 마세요."
    )

    df_dash = df_base[df_base["discovery_path"] == "키워드 대시보드 발굴"]
    df_other = df_base[df_base["discovery_path"] != "키워드 대시보드 발굴"]

    n_dash  = len(df_dash)
    n_other = len(df_other)

    low_dash  = n_dash  < 3
    low_other = n_other < 3

    kc1, kc2 = st.columns(2)

    with kc1:
        badge = " ⚠️ 비교 표본 부족" if low_dash else ""
        st.markdown(f"**대시보드 발굴{badge}**")
        st.metric("게시물 수", f"{n_dash}건")
        st.metric("평균 참여율",  _fmt(df_dash["_engage_rate"].mean(),  pct=True))
        st.metric("중앙값 참여율", _fmt(df_dash["_engage_rate"].median(), pct=True))
        st.metric("평균 링크 클릭률", _fmt(df_dash["_ctr"].mean(), pct=True))

    with kc2:
        badge2 = " ⚠️ 비교 표본 부족" if low_other else ""
        st.markdown(f"**기타 발굴 경로{badge2}**")
        st.metric("게시물 수", f"{n_other}건")
        st.metric("평균 참여율",  _fmt(df_other["_engage_rate"].mean(),  pct=True))
        st.metric("중앙값 참여율", _fmt(df_other["_engage_rate"].median(), pct=True))
        st.metric("평균 링크 클릭률", _fmt(df_other["_ctr"].mean(), pct=True))

    if low_dash or low_other:
        st.info(
            "⚠️ **비교 표본 부족:** 한 그룹의 게시물이 3건 미만입니다. "
            "데이터가 더 쌓인 후 해석하세요."
        )


# ── 해시태그 분석 ─────────────────────────────────────────────

def _render_hashtags(df_c: pd.DataFrame, prefix: str):
    st.markdown("#### 해시태그별 관찰 성과")
    st.caption("이 표는 해시태그 사용과 성과의 상관관계를 보여주며, 해시태그가 성과를 유발했다고 단정할 수 없습니다.")

    inc_paid_ht = st.checkbox("Paid·Boosted 포함", value=False, key=f"{prefix}ht_paid")
    df_ht = df_c if inc_paid_ht else df_c[df_c["promotion"] == "Organic"]

    if len(df_ht) == 0:
        st.info("분석할 데이터가 없습니다.")
        return

    # 해시태그 → 행 분해
    rows = []
    for _, r in df_ht.iterrows():
        tags = [t.strip() for t in str(r["hashtags"]).split(",") if t.strip()]
        for tag in tags:
            rows.append({
                "hashtag"     : tag,
                "impressions" : r["impressions"],
                "_engage_rate": r["_engage_rate"],
                "_ctr"        : r["_ctr"],
                "link_clicks" : r["link_clicks"],
                "ga4_sessions": r["ga4_sessions"],
                "published_at": r["published_at"],
                "post_id"     : r["post_id"],
            })

    if not rows:
        st.info("해시태그 데이터가 없습니다.")
        return

    df_tags = pd.DataFrame(rows)

    agg = df_tags.groupby("hashtag").agg(
        사용_게시물_수 = ("post_id",       "count"),
        총_노출수      = ("impressions",    "sum"),
        평균_참여율    = ("_engage_rate",   "mean"),
        중앙값_참여율  = ("_engage_rate",   "median"),
        평균_CTR      = ("_ctr",           "mean"),
        총_링크클릭    = ("link_clicks",    "sum"),
        총_GA4유입    = ("ga4_sessions",   "sum"),
        최고_참여율   = ("_engage_rate",   "max"),
        최근_사용일   = ("published_at",    "max"),
    ).reset_index()

    # 정렬: 평균 참여율
    agg = agg.sort_values("평균_참여율", ascending=False)

    # 표본 부족 배지
    def _badge(n):
        return "⚠️ 표본 부족" if n < 3 else ""

    agg["비고"] = agg["사용_게시물_수"].apply(_badge)

    # 포맷
    agg["평균_참여율"]  = agg["평균_참여율"].apply(lambda x: _fmt(x, pct=True))
    agg["중앙값_참여율"] = agg["중앙값_참여율"].apply(lambda x: _fmt(x, pct=True))
    agg["평균_CTR"]     = agg["평균_CTR"].apply(lambda x: _fmt(x, pct=True))
    agg["총_노출수"]    = agg["총_노출수"].apply(lambda x: _fmt(x))
    agg["총_링크클릭"]  = agg["총_링크클릭"].apply(_fmt)
    agg["총_GA4유입"]   = agg["총_GA4유입"].apply(_fmt)
    agg["최고_참여율"]  = agg["최고_참여율"].apply(lambda x: _fmt(x, pct=True))

    st.dataframe(agg.rename(columns={"hashtag": "해시태그"}),
                 use_container_width=True, hide_index=True)

    st.caption(
        "**표본 부족(3건 미만):** 소수의 게시물로 측정된 평균은 우연한 변동에 민감합니다. "
        "동일 해시태그를 최소 3건 이상 사용한 후 해석하세요."
    )


# ── 차트 ────────────────────────────────────────────────────

def _render_charts(df_c: pd.DataFrame, prefix: str):
    st.markdown("#### 시각화")
    inc_paid_ch = st.checkbox("Paid·Boosted 포함", value=False, key=f"{prefix}ch_paid")
    df_ch = df_c if inc_paid_ch else df_c[df_c["promotion"] == "Organic"]

    if len(df_ch) == 0:
        st.info("차트를 표시할 데이터가 없습니다.")
        return

    # ── A. 해시태그별 평균·중앙값 참여율 (bar)
    rows_tag = []
    for _, r in df_ch.iterrows():
        tags = [t.strip() for t in str(r["hashtags"]).split(",") if t.strip()]
        for tag in tags:
            rows_tag.append({"hashtag": tag,
                              "engage_rate": r["_engage_rate"],
                              "impressions": r["impressions"]})
    if rows_tag:
        df_ht = pd.DataFrame(rows_tag)
        ht_agg = df_ht.groupby("hashtag")["engage_rate"].agg(
            평균=("mean"), 중앙값=("median"), 건수=("count")).reset_index()
        ht_agg = ht_agg[ht_agg["건수"] >= 1].sort_values("평균", ascending=False).head(20)
        fig_bar = go.Figure()
        fig_bar.add_bar(x=ht_agg["hashtag"], y=ht_agg["평균"],   name="평균 참여율")
        fig_bar.add_bar(x=ht_agg["hashtag"], y=ht_agg["중앙값"], name="중앙값 참여율")
        fig_bar.update_layout(title="해시태그별 관찰 참여율 (상위 20개)",
                              barmode="group", xaxis_title="해시태그",
                              yaxis_title="참여율 (%)", height=400)
        st.plotly_chart(fig_bar, use_container_width=True)
        st.caption("참고용 상관관계 — 해시태그 단독 기여로 단정하지 않습니다.")

    # ── B. 게시일 기준 참여율 추이
    df_trend = df_ch.dropna(subset=["_engage_rate", "published_at"]).copy()
    df_trend["published_at"] = pd.to_datetime(df_trend["published_at"], errors="coerce")
    df_trend = df_trend.sort_values("published_at")
    if len(df_trend) >= 2:
        fig_trend = px.scatter(df_trend, x="published_at", y="_engage_rate",
                               color="content_type", hover_data=["title"],
                               title="게시일 기준 참여율 추이",
                               labels={"published_at": "게시일", "_engage_rate": "참여율 (%)"},
                               trendline="ols" if len(df_trend) >= 3 else None)
        fig_trend.update_layout(height=350)
        st.plotly_chart(fig_trend, use_container_width=True)

    # ── C. 노출수 vs 참여율 산점도
    df_sc = df_ch.dropna(subset=["impressions", "_engage_rate"]).copy()
    if len(df_sc) >= 2:
        fig_sc = px.scatter(df_sc, x="impressions", y="_engage_rate",
                            color="content_type", hover_data=["title"],
                            title="노출수 vs 참여율",
                            labels={"impressions": "노출수", "_engage_rate": "참여율 (%)"},
                            size_max=15)
        fig_sc.update_layout(height=350)
        st.plotly_chart(fig_sc, use_container_width=True)

    # ── D. 링크 클릭 vs GA4 유입 (데이터 있을 때만)
    df_lnk = df_ch.dropna(subset=["link_clicks", "ga4_sessions"]).copy()
    df_lnk = df_lnk[(df_lnk["link_clicks"] > 0) & (df_lnk["ga4_sessions"] > 0)]
    if len(df_lnk) >= 1:
        fig_lnk = go.Figure()
        fig_lnk.add_bar(x=df_lnk["title"], y=df_lnk["link_clicks"],  name="링크 클릭 수")
        fig_lnk.add_bar(x=df_lnk["title"], y=df_lnk["ga4_sessions"], name="GA4 대시보드 유입")
        fig_lnk.update_layout(title="게시물별 링크 클릭 vs GA4 유입 세션",
                              barmode="group", xaxis_title="게시물",
                              yaxis_title="수", height=350)
        st.plotly_chart(fig_lnk, use_container_width=True)
