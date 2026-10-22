"""
instagram_tab.py — 📸 Instagram 콘텐츠 성과 탭

목적:
  Instagram 관리자 내보내기 CSV를 기반으로 게시물·릴스·캐러셀별 성과를 분석한다.
  LinkedIn 분석과 데이터·화면·저장 파일은 완전히 분리한다.

지표 정의:
  반응 수  = Likes + Comments + Shares + Saves
  반응률   = 반응 수 / Reach  (Reach > 0인 경우)
  도달     = Reach (게시물 도달 합계 — 고유 방문자 아님)
  조회수   = Views (동영상: 재생 횟수, 이미지: 조회 횟수)
  Date = "Lifetime" → 현재까지 누적 값, 게시물 경과 기간 차이 유의
"""

from __future__ import annotations

import io
import os
import re
from datetime import datetime

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import github_storage as gh

# ── 상수 ──────────────────────────────────────────────────────────────
_CSV_PATH  = "data/instagram_post_snapshots.csv"
_LOCAL_CSV = os.path.join(os.path.dirname(__file__), _CSV_PATH)

_COLS = [
    "snapshot_id", "post_id", "account_username", "permalink",
    "caption", "hashtags", "post_type", "duration_sec",
    "published_at", "metric_period", "snapshot_date",
    "views", "reach", "likes", "shares", "follows", "comments", "saves",
    "added_at",
]

_NUM_COLS = [
    "views", "reach", "likes", "shares", "follows", "comments", "saves",
    "duration_sec",
]

_POST_TYPE_KR = {
    "ig image"    : "이미지",
    "ig reel"     : "릴스",
    "ig carousel" : "캐러셀",
    "ig video"    : "동영상",
}


# ══════════════════════════════════════════════════════════════════════
# 데이터 로드·저장
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
# 파싱
# ══════════════════════════════════════════════════════════════════════

_IG_REQUIRED_COLS = {"Post ID", "Description", "Permalink", "Post type", "Reach"}


def is_instagram_csv(df_raw: pd.DataFrame) -> bool:
    return _IG_REQUIRED_COLS.issubset(set(df_raw.columns))


def _extract_hashtags(caption: str) -> str:
    """캡션 텍스트에서 #태그를 추출해 쉼표 구분 문자열로 반환. 중복 제거, 순서 유지."""
    tags = re.findall(r'#(\w+)', caption or "")
    seen: dict = {}
    for t in tags:
        seen.setdefault(t, None)
    return ", ".join(f"#{t}" for t in seen)


def _extract_snapshot_date(filename: str) -> str:
    """파일명에서 날짜 추출. 예: 'Sep-01-2026_Oct-21-2026_...' → '2026-10-21'"""
    month_map = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    }
    matches = re.findall(r"([A-Za-z]{3})-(\d{2})-(\d{4})", filename)
    dates = []
    for m, d, y in matches:
        mon = month_map.get(m.lower())
        if mon:
            dates.append(f"{y}-{mon:02d}-{int(d):02d}")
    if dates:
        return dates[-1]
    from datetime import date as _date
    return str(_date.today())


def parse_instagram_csv(df_raw: pd.DataFrame, snapshot_date: str) -> list[dict]:
    """Instagram CSV → 내부 dict 목록 변환."""
    import hashlib

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows: list[dict] = []

    def _s(col: str, row: pd.Series) -> str:
        v = row.get(col, "")
        return "" if str(v).strip() in ("nan", "None", "") else str(v).strip()

    def _n(col: str, row: pd.Series) -> float:
        raw = _s(col, row)
        try:
            return float(re.sub(r"[,%\s]", "", raw))
        except (ValueError, AttributeError):
            return np.nan

    for _, raw in df_raw.iterrows():
        post_id   = _s("Post ID", raw)
        permalink = _s("Permalink", raw)
        if not post_id and not permalink:
            continue

        key           = post_id or permalink
        snapshot_id   = hashlib.md5(f"{key}|{snapshot_date}".encode()).hexdigest()[:12]
        raw_pt        = _s("Post type", raw).lower()
        post_type_kr  = _POST_TYPE_KR.get(raw_pt, _s("Post type", raw))

        # 게시 시간 파싱
        raw_time = _s("Publish time", raw)
        try:
            published_at = str(pd.to_datetime(raw_time).date())
        except Exception:
            published_at = raw_time

        rows.append({
            "snapshot_id"   : snapshot_id,
            "post_id"       : post_id,
            "account_username": _s("Account username", raw),
            "permalink"     : permalink,
            "caption"       : _s("Description", raw)[:500],
            "hashtags"      : _extract_hashtags(_s("Description", raw)),
            "post_type"     : post_type_kr,
            "duration_sec"  : _n("Duration (sec)", raw),
            "published_at"  : published_at,
            "metric_period" : _s("Date", raw) or "Lifetime",
            "snapshot_date" : snapshot_date,
            "views"         : _n("Views", raw),
            "reach"         : _n("Reach", raw),
            "likes"         : _n("Likes", raw),
            "shares"        : _n("Shares", raw),
            "follows"       : _n("Follows", raw),
            "comments"      : _n("Comments", raw),
            "saves"         : _n("Saves", raw),
            "added_at"      : now_str,
        })

    return rows


def merge_snapshots(existing_df: pd.DataFrame, new_rows: list[dict]) -> tuple[pd.DataFrame, dict]:
    """
    (post_id, snapshot_date) 조합이 이미 있으면 교체, 없으면 추가.
    Returns: (merged_df, stats)
    """
    if not new_rows:
        return existing_df, {"new": 0, "updated": 0, "snapshot_date": ""}

    snapshot_date = new_rows[0]["snapshot_date"]
    stats = {"new": 0, "updated": 0, "snapshot_date": snapshot_date}

    if len(existing_df) > 0:
        # 같은 (post_id, snapshot_date) 조합 제거 후 재삽입
        mask = (
            (existing_df["snapshot_date"].astype(str) == snapshot_date) &
            (existing_df["post_id"].astype(str).isin({r["post_id"] for r in new_rows}))
        )
        stats["updated"] = int(mask.sum())
        existing_df = existing_df[~mask].copy()
    else:
        existing_df = pd.DataFrame(columns=_COLS)

    stats["new"] = len(new_rows) - stats["updated"]

    new_df = pd.DataFrame(new_rows)
    merged = pd.concat([existing_df, new_df], ignore_index=True)
    return merged, stats


# ══════════════════════════════════════════════════════════════════════
# 지표 보강
# ══════════════════════════════════════════════════════════════════════

def _enrich(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["_pub"]    = pd.to_datetime(df["published_at"], errors="coerce")
    df["_engage"] = (
        df["likes"].fillna(0)
        + df["comments"].fillna(0)
        + df["shares"].fillna(0)
        + df["saves"].fillna(0)
    )
    df["_eng_rate"] = df.apply(
        lambda r: (r["_engage"] / r["reach"] * 100) if pd.notna(r["reach"]) and r["reach"] > 0 else np.nan,
        axis=1,
    )
    return df


def _fmt(val, pct: bool = False, na: str = "-") -> str:
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return na
    if pct:
        return f"{val:.1f}%"
    return f"{val:,.0f}"


# ══════════════════════════════════════════════════════════════════════
# 공개 렌더 함수
# ══════════════════════════════════════════════════════════════════════

@st.fragment
def render(prefix: str = "ig_") -> None:
    """dashboard.py 에서 `with tab6: instagram_tab.render()` 로 호출합니다."""

    ss_df = f"{prefix}df"
    if ss_df not in st.session_state:
        st.session_state[ss_df] = _load()

    df: pd.DataFrame = st.session_state[ss_df]

    _render_upload(df, prefix, ss_df)

    df = st.session_state[ss_df]

    if len(df) == 0:
        _render_empty_state()
        return

    # 최신 snapshot만 분석에 사용
    df_latest = _get_latest_snapshot(df)
    df_c      = _enrich(df_latest)

    sub1, sub2, sub3, sub4 = st.tabs(["📊 성과 요약", "📋 게시물 목록", "🎞️ 포맷별 비교", "#️⃣ 해시태그 분석"])
    with sub1:
        _render_summary(df_c, df, prefix)
    with sub2:
        _render_list(df_c, prefix)
    with sub3:
        _render_format_compare(df_c, prefix)
    with sub4:
        _render_hashtags_ig(df_c, prefix)


def _get_latest_snapshot(df: pd.DataFrame) -> pd.DataFrame:
    """각 post_id에 대해 가장 최근 snapshot_date 행만 반환."""
    if "snapshot_date" not in df.columns or df["snapshot_date"].isna().all():
        return df
    df2 = df.copy()
    df2["_sd"] = pd.to_datetime(df2["snapshot_date"], errors="coerce")
    idx = df2.groupby("post_id")["_sd"].idxmax().dropna()
    return df2.loc[idx].drop(columns=["_sd"]).copy()


# ══════════════════════════════════════════════════════════════════════
# 업로드 섹션
# ══════════════════════════════════════════════════════════════════════

def _render_upload(df: pd.DataFrame, prefix: str, ss_df: str) -> None:
    has_data    = len(df) > 0
    snapshot_dates = sorted(df["snapshot_date"].dropna().unique()) if has_data else []
    last_update = snapshot_dates[-1] if snapshot_dates else None

    with st.expander(
        "📥 Instagram CSV 업로드" + (f" (최근 업데이트: {last_update})" if last_update else ""),
        expanded=not has_data,
    ):
        st.markdown("""
<div style="background:#FFF7ED;border-left:4px solid #F97316;
     padding:10px 14px;border-radius:6px;margin-bottom:.75rem;font-size:13px;color:#374151">
Instagram 프로페셔널 계정 &gt; 인사이트 &gt; 게시물 내보내기(.csv)를 업로드하세요.<br>
업로드할 때마다 <b>snapshot</b>으로 누적되어 기간별 성과 변화를 추적할 수 있습니다.<br>
현재 CSV의 <b>Date = Lifetime</b>이면 누적 값이므로 게시일 경과 기간 차이에 유의하세요.
</div>""", unsafe_allow_html=True)

        uploaded = st.file_uploader(
            "Instagram 내보내기 CSV",
            type=["csv"],
            key=f"{prefix}upload",
            label_visibility="collapsed",
        )

        if not uploaded:
            st.caption("파일을 올리면 자동으로 분석이 시작됩니다.")
            return

        # ── 파싱
        for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
            try:
                df_raw = pd.read_csv(uploaded, dtype=str, encoding=enc)
                uploaded.seek(0)
                break
            except UnicodeDecodeError:
                uploaded.seek(0)
                continue
            except Exception as e:
                st.error(f"CSV 읽기 오류: {e}")
                return
        else:
            st.error("CSV 인코딩을 감지할 수 없습니다.")
            return

        if not is_instagram_csv(df_raw):
            st.error(
                "Instagram 내보내기 CSV 형식이 아닙니다. "
                "필수 컬럼: Post ID, Description, Permalink, Post type, Reach"
            )
            return

        snapshot_date = _extract_snapshot_date(uploaded.name)
        new_rows      = parse_instagram_csv(df_raw, snapshot_date)

        if not new_rows:
            st.warning("파싱 가능한 게시물이 없습니다.")
            return

        # ── 미리보기
        n_posts = len(new_rows)
        dates   = [r["published_at"] for r in new_rows if r["published_at"]]
        period  = f"{min(dates)} ~ {max(dates)}" if dates else "-"
        types_cnt = {}
        for r in new_rows:
            types_cnt[r["post_type"]] = types_cnt.get(r["post_type"], 0) + 1

        p1, p2, p3 = st.columns(3)
        p1.metric("게시물 수",   n_posts)
        p2.metric("게시 기간",   period)
        p3.metric("스냅샷 날짜", snapshot_date)

        type_str = " / ".join(f"{k} {v}건" for k, v in types_cnt.items())
        st.caption(f"포맷: {type_str}")

        prev_df = pd.DataFrame([{
            "게시일"     : r["published_at"],
            "포맷"       : r["post_type"],
            "요약"       : r["caption"][:40] + "…" if len(r["caption"]) > 40 else r["caption"],
            "조회"       : r["views"],
            "도달"       : r["reach"],
            "좋아요"     : r["likes"],
            "댓글"       : r["comments"],
        } for r in new_rows])
        st.dataframe(prev_df, use_container_width=True, height=200)
        st.divider()

        if st.button(
            f"✅ 가져오기 확정  ({n_posts}건 · 스냅샷 {snapshot_date})",
            type="primary", key=f"{prefix}confirm", use_container_width=True,
        ):
            with st.spinner("저장 중..."):
                df_merged, stats = merge_snapshots(df.copy(), new_rows)
                df_merged = _cast(df_merged)
                ok = _save(
                    df_merged,
                    f"feat: Instagram 가져오기 — {snapshot_date} 신규{stats['new']} 갱신{stats['updated']}",
                )

            st.session_state[ss_df] = df_merged
            if ok:
                st.success(f"✅ 저장 완료 — 신규 {stats['new']}건, 갱신 {stats['updated']}건")
            else:
                st.warning(f"⚠️ 로컬 저장 완료 (GitHub 동기화 실패) — 신규 {stats['new']}건")
            st.rerun()

    # ── 해시태그 일괄 업데이트 ────────────────────────────────────────
    with st.expander("🏷️ 해시태그 일괄 업데이트 (CSV)", expanded=False):
        st.caption(
            "컬럼: `post_id`, `hashtags` — post_id가 일치하는 행의 해시태그를 업데이트합니다. "
            "없는 post_id는 건너뜁니다."
        )
        _ht_upload = st.file_uploader(
            "해시태그 CSV", type=["csv"],
            key=f"{prefix}ht_bulk_upload", label_visibility="collapsed",
        )
        if _ht_upload:
            try:
                _ht_raw = pd.read_csv(_ht_upload, dtype=str)
            except Exception as e:
                st.error(f"CSV 읽기 오류: {e}")
                _ht_raw = None
            if _ht_raw is not None:
                if "post_id" not in _ht_raw.columns or "hashtags" not in _ht_raw.columns:
                    st.error("CSV에 `post_id`와 `hashtags` 컬럼이 필요합니다.")
                else:
                    _ht_map = dict(zip(_ht_raw["post_id"].astype(str), _ht_raw["hashtags"].astype(str)))
                    st.caption(f"{len(_ht_map)}개 행 감지")
                    if st.button("✅ 적용", key=f"{prefix}ht_bulk_apply", type="primary"):
                        _ig_df_bulk = st.session_state.get(ss_df, pd.DataFrame()).copy()
                        _matched = 0
                        for _i, _row in _ig_df_bulk.iterrows():
                            _pid = str(_row.get("post_id", ""))
                            if _pid in _ht_map:
                                _ig_df_bulk.at[_i, "hashtags"] = _ht_map[_pid]
                                _matched += 1
                        with st.spinner("저장 중…"):
                            ok2 = _save(_ig_df_bulk, f"feat: Instagram 해시태그 일괄 업데이트 {_matched}건")
                        st.session_state[ss_df] = _ig_df_bulk
                        if ok2:
                            st.success(f"✅ {_matched}건 업데이트 완료")
                        else:
                            st.warning(f"⚠️ 로컬 저장 완료 — {_matched}건 (GitHub 동기화 실패)")


# ══════════════════════════════════════════════════════════════════════
# 빈 상태
# ══════════════════════════════════════════════════════════════════════

def _render_empty_state() -> None:
    st.markdown("""
<div style="text-align:center;padding:3rem 1rem;color:#94A3B8">
  <div style="font-size:2.5rem">📸</div>
  <div style="font-size:1.1rem;font-weight:600;margin:.5rem 0">
    Instagram CSV를 업로드하면 콘텐츠 성과 분석이 시작됩니다</div>
  <div style="font-size:13px">
    Instagram 프로페셔널 계정 &gt; 인사이트 &gt; 게시물 내보내기(.csv)
  </div>
</div>""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════
# 자동 인사이트 (2문장)
# ══════════════════════════════════════════════════════════════════════

def _render_insights(df: pd.DataFrame) -> None:
    """성과 요약 최상단 — 2문장 자동 인사이트"""
    n = len(df)
    if n < 2:
        return

    small_sample = n < 10
    suffix = "  \n현재 표본이 적어 다음 기간 데이터로 반복 확인이 필요합니다." if small_sample else ""

    sentences: list[str] = []

    # ── 문장 1: 포맷별 도달 비교 또는 최고 조회 게시물
    types = df["post_type"].dropna().unique()
    has_multi_format = len(types) >= 2

    if has_multi_format:
        fmt_reach = (
            df.groupby("post_type")["reach"]
            .agg(["mean", "count"])
            .rename(columns={"mean": "avg_reach", "count": "n"})
            .dropna()
        )
        valid_fmt = fmt_reach[fmt_reach["n"] >= 2]

        if len(valid_fmt) >= 2:
            top_fmt   = valid_fmt["avg_reach"].idxmax()
            top_reach = valid_fmt.loc[top_fmt, "avg_reach"]
            others    = valid_fmt.drop(index=top_fmt)
            others_str = "·".join(others.index.tolist())
            others_avg = others["avg_reach"].mean()
            note = "다만 포맷별 표본이 적어 포맷 자체의 효과로 단정하기보다 계속 관찰이 필요합니다." if fmt_reach["n"].min() < 3 else ""
            s1 = (
                f"이번 기간 **{top_fmt}**은 평균 도달 **{top_reach:,.0f}**로 "
                f"{others_str}(평균 {others_avg:,.0f})보다 관찰상 높았습니다. "
                + (note if note else "각 포맷 표본이 늘어나면 더 신뢰도 높은 비교가 가능합니다.")
            )
        else:
            s1 = _insight_top_views(df)
    else:
        s1 = _insight_top_views(df)

    if s1:
        sentences.append(s1)

    # ── 문장 2: 반응률 관점
    valid_eng = df.dropna(subset=["_eng_rate", "reach"])
    valid_eng = valid_eng[valid_eng["reach"] > 0]

    if len(valid_eng) >= 2:
        top_eng = valid_eng.loc[valid_eng["_eng_rate"].idxmax()]
        med_reach = valid_eng["reach"].median()
        top_reach = float(top_eng["reach"])
        top_er    = float(top_eng["_eng_rate"])
        caption_short = str(top_eng.get("caption", "") or "")[:30].strip()

        if top_reach < med_reach * 0.8:
            reach_ctx = f"도달 {top_reach:,.0f}으로 중앙값보다 낮았지만"
        elif top_reach > med_reach * 1.3:
            reach_ctx = f"도달 {top_reach:,.0f}으로 중앙값보다 높은 상황에서"
        else:
            reach_ctx = f"도달 {top_reach:,.0f}으로 중앙값과 유사한 상황에서"

        # 캡션에서 확인되는 콘텐츠 특성
        content_hint = _infer_content_char(str(top_eng.get("caption", "") or ""), str(top_eng.get("post_type", "") or ""))

        s2 = (
            f"“{caption_short}…” 게시물은 {reach_ctx} "
            f"반응률 **{top_er:.1f}%**로 가장 높았습니다. "
            f"{content_hint}이 기존 팔로워의 반응을 이끌었을 가능성이 있습니다."
        )
        sentences.append(s2)

    if not sentences:
        return

    st.markdown("#### \U0001f4a1 이번 기간 인사이트")
    st.info("  \n".join(sentences) + suffix, icon="\U0001f4a1")


def _insight_top_views(df: pd.DataFrame) -> str:
    valid = df.dropna(subset=["views"])
    if valid.empty:
        return ""
    top = valid.loc[valid["views"].idxmax()]
    med = valid["views"].median()
    ratio = float(top["views"]) / med if med > 0 else 1.0
    short = str(top.get("caption", "") or "")[:25].strip()
    return (
        f"“{short}…” 게시물은 조회 **{int(top['views']):,}회**로 중앙값보다 "
        f"**{ratio:.1f}배** 많은 조회를 기록했습니다. "
        "게시 시점·포맷·소재 등 다양한 요인이 복합적으로 작용했을 가능성이 있습니다."
    )


def _infer_content_char(caption: str, post_type: str) -> str:
    combined = caption.lower()
    if any(k in combined for k in ["채용", "recruit", "워크앳", "workat"]):
        return "채용 관련 CTA 포함 콘텐츠"
    if any(k in combined for k in ["ob", "네트워킹", "퇴직", "동문", "alumni"]):
        return "커뮤니티·네트워킹 콘텐츠"
    if any(k in combined for k in ["people", "피플", "인터뷰", "interview", "10문"]):
        return "임직원 인터뷰 콘텐츠"
    if any(k in combined for k in ["한가위", "추석", "명절", "설날"]):
        return "명절·캠페인 콘텐츠"
    if "릴스" in post_type or "reel" in post_type.lower():
        return "동영상(릴스) 포맷 콘텐츠"
    return "해당 주제 콘텐츠"


# ══════════════════════════════════════════════════════════════════════
# 성과 요약 탭
# ══════════════════════════════════════════════════════════════════════

def _render_summary(df: pd.DataFrame, df_all: pd.DataFrame, prefix: str) -> None:
    st.markdown("#### 📊 성과 요약")

    # ── 자동 인사이트
    _render_insights(df)

    st.divider()

    # ── KPI 행
    n         = len(df)
    views_sum = df["views"].sum()
    reach_sum = df["reach"].sum()
    engage    = df["_engage"].sum()
    eng_med   = df["_eng_rate"].median()

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("게시물 수",        f"{n:,}")
    k2.metric("조회수 합계",       _fmt(views_sum))
    k3.metric("게시물 도달 합계",  _fmt(reach_sum))
    k4.metric("반응 수 합계",      _fmt(engage))
    k5.metric("중앙값 반응률",     _fmt(eng_med, pct=True))

    st.caption("※ 게시물 도달 합계는 동일 사용자가 여러 게시물을 본 경우 중복 집계될 수 있습니다.")

    st.divider()

    # ── 베스트 게시물
    c1, c2, c3 = st.columns(3)

    def _best(col: str, label: str, fmt_fn) -> None:
        sub = df.dropna(subset=[col])
        if sub.empty:
            return
        row = sub.loc[sub[col].idxmax()]
        st.markdown(f"**{label}**")
        cap = str(row.get("caption", "") or "")[:55]
        st.markdown(f"<span style='font-size:13px;color:#374151'>{cap}…</span>",
                    unsafe_allow_html=True)
        st.markdown(f"<b style='font-size:1.2rem;color:#F97316'>{fmt_fn(row[col])}</b>",
                    unsafe_allow_html=True)
        st.caption(f"{row.get('post_type','')} · {row.get('published_at','')}")

    with c1:
        _best("views",     "🎬 최고 조회수",  lambda v: f"{v:,.0f}회")
    with c2:
        _best("reach",     "📡 최고 도달",    lambda v: f"{v:,.0f}")
    with c3:
        _best("_eng_rate", "💬 최고 반응률",  lambda v: f"{v:.1f}%")

    st.divider()

    # ── 날짜별 조회·도달 추이
    df_t = df.dropna(subset=["_pub"]).sort_values("_pub")
    if len(df_t) >= 2:
        fig = go.Figure()
        fig.add_trace(go.Bar(x=df_t["_pub"], y=df_t["reach"],
                             name="도달", marker_color="#FED7AA", yaxis="y"))
        fig.add_trace(go.Scatter(x=df_t["_pub"], y=df_t["_eng_rate"],
                                 name="반응률(%)", mode="lines+markers",
                                 line=dict(color="#F97316", width=2), yaxis="y2"))
        fig.update_layout(
            height=280,
            yaxis=dict(title="도달"),
            yaxis2=dict(title="반응률(%)", overlaying="y", side="right"),
            legend=dict(orientation="h", y=1.08),
            margin=dict(l=0, r=0, t=30, b=0),
        )
        st.plotly_chart(fig, use_container_width=True)

    # ── 스냅샷 이력 (2개 이상 스냅샷 있을 때만)
    _render_snapshot_growth(df_all, prefix)


def _render_snapshot_growth(df_all: pd.DataFrame, prefix: str) -> None:
    """동일 게시물의 복수 스냅샷이 있을 때 증분 성장 표시."""
    if "snapshot_date" not in df_all.columns:
        return
    snapshots = sorted(df_all["snapshot_date"].dropna().unique())
    if len(snapshots) < 2:
        return

    with st.expander(f"📈 스냅샷 증분 (스냅샷 {len(snapshots)}개)"):
        st.caption(
            "동일 게시물이 여러 날짜에 업로드된 경우의 수치 변화입니다. "
            "단순 비교이며 게시 후 경과 시간이 다를 수 있습니다."
        )
        snap_sel = st.selectbox(
            "비교 기준 스냅샷",
            snapshots,
            index=len(snapshots) - 1,
            key=f"{prefix}snap_sel",
        )
        prev_snap = snapshots[snapshots.index(snap_sel) - 1] if snapshots.index(snap_sel) > 0 else None
        if not prev_snap:
            st.info("이전 스냅샷이 없습니다.")
            return

        cur  = df_all[df_all["snapshot_date"] == snap_sel].set_index("post_id")
        prev = df_all[df_all["snapshot_date"] == prev_snap].set_index("post_id")
        common = cur.index.intersection(prev.index)
        if common.empty:
            st.info("두 스냅샷에 공통 게시물이 없습니다.")
            return

        rows = []
        for pid in common:
            for col in ("views", "reach", "likes", "comments"):
                cv = pd.to_numeric(cur.at[pid, col], errors="coerce") if col in cur.columns else np.nan
                pv = pd.to_numeric(prev.at[pid, col], errors="coerce") if col in prev.columns else np.nan
                delta = (cv - pv) if pd.notna(cv) and pd.notna(pv) else np.nan
                rows.append({
                    "post_id": pid,
                    "지표": col,
                    f"{prev_snap}": pv,
                    f"{snap_sel}": cv,
                    "증가": delta,
                })

        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════════════
# 게시물 목록 탭
# ══════════════════════════════════════════════════════════════════════

def _render_list(df: pd.DataFrame, prefix: str) -> None:
    st.markdown("#### 📋 게시물 목록")

    fc1, fc2 = st.columns(2)
    with fc1:
        type_opts = ["전체"] + sorted(df["post_type"].dropna().unique().tolist())
        sel_type  = st.selectbox("포맷", type_opts, key=f"{prefix}list_type")
    with fc2:
        sort_by = st.selectbox(
            "정렬 기준",
            ["게시일 (최신순)", "조회수 (높은순)", "도달 (높은순)", "반응률 (높은순)"],
            key=f"{prefix}list_sort",
        )

    df_f = df.copy()
    if sel_type != "전체":
        df_f = df_f[df_f["post_type"] == sel_type]

    sort_map = {
        "게시일 (최신순)": ("_pub", False),
        "조회수 (높은순)": ("views", False),
        "도달 (높은순)":  ("reach", False),
        "반응률 (높은순)": ("_eng_rate", False),
    }
    sc, sa = sort_map[sort_by]
    df_f = df_f.sort_values(sc, ascending=sa, na_position="last")

    display_rows = []
    for _, r in df_f.iterrows():
        display_rows.append({
            "게시일"   : str(r["_pub"].date()) if pd.notna(r["_pub"]) else "-",
            "포맷"     : r["post_type"] or "-",
            "본문 요약": str(r["caption"] or "")[:50],
            "해시태그" : str(r.get("hashtags", "") or ""),
            "조회"     : _fmt(r["views"]),
            "도달"     : _fmt(r["reach"]),
            "좋아요"   : _fmt(r["likes"]),
            "댓글"     : _fmt(r["comments"]),
            "공유"     : _fmt(r["shares"]),
            "저장"     : _fmt(r["saves"]),
            "반응률"   : _fmt(r["_eng_rate"], pct=True),
            "원문"     : r["permalink"],
        })

    df_disp = pd.DataFrame(display_rows)
    st.dataframe(
        df_disp, use_container_width=True, height=420,
        column_config={
            "원문"     : st.column_config.LinkColumn("원문", display_text="링크"),
            "본문 요약": st.column_config.TextColumn("본문 요약", width="large"),
            "해시태그" : st.column_config.TextColumn("해시태그", width="medium"),
        },
    )
    st.caption(f"총 {len(df_f)}건 (누적 기간: Lifetime)")

    # ── 해시태그 인라인 편집 ──────────────────────────
    with st.expander("✏️ 해시태그 수동 편집"):
        st.caption("게시물을 선택해 해시태그를 직접 입력하거나 수정합니다. 쉼표 구분(예: #AI, #인공지능)")
        _ig_df_full = st.session_state.get(f"{prefix}df", pd.DataFrame())
        if _ig_df_full.empty:
            st.info("저장된 게시물 데이터가 없습니다.")
        else:
            _ig_opts = {
                f"{str(r.get('published_at',''))[:10]} · {str(r.get('caption',''))[:30]}": idx
                for idx, r in _ig_df_full.iterrows()
            }
            _sel_label = st.selectbox("게시물 선택", list(_ig_opts.keys()), key=f"{prefix}ht_edit_sel")
            _sel_idx = _ig_opts[_sel_label]
            _cur_ht = str(_ig_df_full.at[_sel_idx, "hashtags"] or "")
            _new_ht = st.text_input("해시태그 (쉼표 구분)", value=_cur_ht, key=f"{prefix}ht_edit_val",
                                     placeholder="#AI, #인공지능, #ChatGPT")
            if st.button("💾 저장", key=f"{prefix}ht_edit_save", type="primary"):
                _ig_df_full.at[_sel_idx, "hashtags"] = _new_ht.strip()
                with st.spinner("저장 중…"):
                    ok = _save(_ig_df_full, "feat: Instagram 해시태그 수동 편집")
                st.session_state[f"{prefix}df"] = _ig_df_full.copy()
                if ok:
                    st.success("저장됐습니다.")
                else:
                    st.warning("로컬 저장 완료 (GitHub 동기화 실패)")


# ══════════════════════════════════════════════════════════════════════
# 포맷별 비교 탭
# ══════════════════════════════════════════════════════════════════════

def _render_format_compare(df: pd.DataFrame, prefix: str) -> None:
    st.markdown("#### 🎞️ 포맷별 비교")

    st.warning(
        "포맷별 결과는 게시 시점·소재·해시태그 등의 영향을 함께 받는 **관찰치**이며, "
        "포맷 단독 효과나 인과관계를 의미하지 않습니다.",
        icon="⚠️",
    )

    records = []
    for ptype, sub in df.groupby("post_type"):
        n = len(sub)
        records.append({
            "포맷"           : ptype,
            "게시물 수"      : n,
            "평균 조회수"    : sub["views"].mean(),
            "중앙값 조회수"  : sub["views"].median(),
            "평균 도달"      : sub["reach"].mean(),
            "중앙값 도달"    : sub["reach"].median(),
            "평균 반응률"    : sub["_eng_rate"].mean(),
            "중앙값 반응률"  : sub["_eng_rate"].median(),
            "평균 저장"      : sub["saves"].mean(),
            "평균 공유"      : sub["shares"].mean(),
            "_n"             : n,
        })

    if not records:
        st.info("데이터가 없습니다.")
        return

    df_fmt = pd.DataFrame(records)
    low_sample = df_fmt[df_fmt["_n"] < 3]
    ok_sample  = df_fmt[df_fmt["_n"] >= 3]

    if len(ok_sample) >= 2:
        # 반응률 차트
        fig = px.bar(
            ok_sample.sort_values("중앙값 반응률"),
            x="중앙값 반응률", y="포맷",
            orientation="h", text="게시물 수",
            color_discrete_sequence=["#F97316"],
            height=max(200, len(ok_sample) * 60),
            title="포맷별 중앙값 반응률 (3건 이상)",
        )
        fig.update_traces(textposition="outside")
        fig.update_layout(margin=dict(l=0, r=20, t=40, b=0))
        st.plotly_chart(fig, use_container_width=True)

    # 상세 표
    display = df_fmt.copy()
    for col in ("평균 조회수", "중앙값 조회수", "평균 도달", "중앙값 도달", "평균 저장", "평균 공유"):
        display[col] = display[col].apply(lambda v: f"{v:,.0f}" if pd.notna(v) else "-")
    for col in ("평균 반응률", "중앙값 반응률"):
        display[col] = display[col].apply(lambda v: f"{v:.1f}%" if pd.notna(v) else "-")

    st.dataframe(
        display[["포맷", "게시물 수", "평균 조회수", "중앙값 조회수",
                  "평균 도달", "중앙값 도달", "평균 반응률", "중앙값 반응률",
                  "평균 저장", "평균 공유"]],
        use_container_width=True, hide_index=True,
    )

    if len(low_sample) > 0:
        names = low_sample["포맷"].tolist()
        st.caption(
            f"⚠️ 표본 부족 (3건 미만): {', '.join(names)} — "
            "현재는 참고용 관찰치입니다. 게시물이 쌓이면 재평가하세요."
        )


# ══════════════════════════════════════════════════════════════════════
# 해시태그 분석 탭
# ══════════════════════════════════════════════════════════════════════

def _render_hashtags_ig(df: pd.DataFrame, prefix: str) -> None:
    st.markdown("#### #️⃣ 해시태그 분석")

    st.warning(
        "해시태그별 결과는 게시 시점·소재·포맷 등의 영향을 함께 받는 **관찰치**이며, "
        "해시태그 단독 효과나 인과관계를 의미하지 않습니다.",
        icon="⚠️",
    )

    records: list[dict] = []
    tag_posts: dict[str, list] = {}

    for i, row in df.iterrows():
        ht_val = str(row.get("hashtags", "") or "")
        if not ht_val:
            # caption에서 실시간 추출 (hashtags 컬럼이 빈 경우)
            ht_val = _extract_hashtags(str(row.get("caption", "") or ""))
        tags = [t.strip().lstrip("#") for t in re.split(r"[,\s]+", ht_val) if t.strip().lstrip("#")]
        for tag in tags:
            tag_posts.setdefault(tag, []).append(i)

    for tag, idxs in tag_posts.items():
        sub = df.loc[idxs]
        n   = len(sub)
        records.append({
            "해시태그"       : f"#{tag}",
            "사용 횟수"      : n,
            "평균 도달"      : round(float(sub["reach"].mean()), 0) if sub["reach"].notna().any() else float("nan"),
            "평균 반응률(%)" : round(float(sub["_eng_rate"].mean()), 1) if sub["_eng_rate"].notna().any() else float("nan"),
            "평균 저장"      : round(float(sub["saves"].mean()), 0) if sub["saves"].notna().any() else float("nan"),
            "_n"             : n,
        })

    if not records:
        st.info(
            "해시태그 데이터가 없습니다. "
            "CSV 업로드 시 캡션에서 자동 추출되거나, '게시물 목록' 탭에서 직접 입력할 수 있습니다."
        )
        return

    df_ht = pd.DataFrame(records).sort_values("평균 도달", ascending=False)
    df_rank = df_ht[df_ht["_n"] >= 2].copy()
    df_low  = df_ht[df_ht["_n"] < 2].copy()

    if len(df_rank) > 0:
        st.markdown("**✅ 성과 비교 (2건 이상)**")
        st.dataframe(
            df_rank[["해시태그", "사용 횟수", "평균 도달", "평균 반응률(%)", "평균 저장"]],
            use_container_width=True, hide_index=True,
            column_config={
                "평균 도달":       st.column_config.NumberColumn(format="%,.0f"),
                "평균 반응률(%)":  st.column_config.NumberColumn(format="%.1f"),
                "평균 저장":       st.column_config.NumberColumn(format="%,.0f"),
            },
        )
        top10 = df_rank[~df_rank["해시태그"].str.contains("SCK", case=False)].head(10)
        if len(top10) > 0:
            import plotly.express as _px_ig
            fig = _px_ig.bar(
                top10.sort_values("평균 반응률(%)"),
                x="평균 반응률(%)", y="해시태그",
                orientation="h", text="사용 횟수",
                title="해시태그별 평균 반응률 (상위 10개)",
                color_discrete_sequence=["#F97316"],
                height=max(220, len(top10) * 35),
            )
            fig.update_traces(textposition="outside")
            fig.update_layout(margin=dict(l=0, r=20, t=40, b=0))
            st.plotly_chart(fig, use_container_width=True)

    if len(df_low) > 0:
        with st.expander(f"🔍 표본 부족 ({len(df_low)}개 태그, 2건 미만)"):
            st.dataframe(
                df_low[["해시태그", "사용 횟수", "평균 도달"]],
                use_container_width=True, hide_index=True,
            )


# ══════════════════════════════════════════════════════════════════════
# 공개 데이터 접근
# ══════════════════════════════════════════════════════════════════════

def load_posts() -> pd.DataFrame:
    """dashboard.py 등 외부에서 Instagram 게시물 데이터를 읽을 때 사용."""
    return _load()
