"""
linkedin_import.py — LinkedIn Company Page 분석 파일 가져오기

지원 파일:
  Content export (.xlsx / .xls / .csv)  → 게시물 성과 자동 반영
  Visitors export (.xlsx / .xls / .csv) → 방문자 특성 섹션 전용 표시

LinkedIn 로그인 / 크롤링 / 비공식 API 미사용.
"""

from __future__ import annotations

import io
import re
from typing import Optional

import numpy as np
import pandas as pd
import streamlit as st


# ── LinkedIn Content 컬럼 후보 매핑 ─────────────────────────────
# 내부 컬럼명 → LinkedIn 익스포트에서 가능한 컬럼 이름 목록 (우선순위 순)
_CONTENT_COL_ALIASES: dict[str, list[str]] = {
    "published_at": [
        "date", "published date", "post published date", "created date",
        "created", "post date", "published_date", "게시일", "날짜", "작성일", "게시 일자",
    ],
    "url": [
        "post url", "url", "content url", "post_url", "content_url",
        "link", "게시물 url", "링크", "게시물url", "게시물 링크",
    ],
    "text": [
        "post", "content", "post body", "body", "message", "text",
        "post text", "post content", "게시물", "내용", "본문", "텍스트", "게시물 내용",
    ],
    "impressions": [
        "impressions", "impression", "views", "노출수", "노출", "조회수",
    ],
    "link_clicks": [
        "link clicks", "clicks", "link click", "click", "클릭수", "링크 클릭수", "클릭",
        "링크 클릭", "ctr clicks",
    ],
    "reactions": [
        "reactions", "likes", "reaction", "like", "반응", "좋아요", "반응수", "좋아요 수",
    ],
    "comments": [
        "comments", "comment", "댓글", "댓글수", "댓글 수",
    ],
    "reposts": [
        "reposts", "shares", "repost", "share", "리포스트", "공유", "리포스트수", "공유수",
        "공유 수",
    ],
    "content_type": [
        "content type", "post type", "type", "콘텐츠 유형", "유형", "게시물 유형",
        "post_type",
    ],
    "title": [
        "title", "headline", "subject", "제목",
    ],
}

# Visitors 파일 고유 컬럼 패턴 (이 중 하나라도 있으면 Visitors 파일로 판단)
_VISITORS_SIGNATURE_COLS = [
    "job function", "seniority", "company size", "industry",
    "unique visitors", "page views",
    "직무", "직급", "회사 규모", "산업",
    "순 방문자", "페이지 조회수",
]

_CONTENT_SIGNATURE_COLS = [
    "impressions", "reactions", "likes", "reposts", "shares",
    "노출수", "반응", "좋아요", "공유",
]


# ── 파일 읽기 ────────────────────────────────────────────────────

def _read_file(uploaded) -> tuple[Optional[pd.DataFrame], str]:
    """
    업로드된 파일을 DataFrame으로 읽기.
    Returns: (DataFrame | None, error_message)

    LinkedIn 내보내기는 .xls 확장자지만 실제로 HTML 테이블인 경우가 많음.
    여러 방법을 순차적으로 시도.
    """
    name = uploaded.name.lower()
    data = uploaded.read()
    uploaded.seek(0)

    errors: list[str] = []

    # ── CSV
    if name.endswith(".csv"):
        for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
            try:
                df = pd.read_csv(io.BytesIO(data), dtype=str, encoding=enc)
                return df, ""
            except UnicodeDecodeError:
                continue
            except Exception as e:
                errors.append(f"csv/{enc}: {e}")
        return None, " | ".join(errors) or "CSV 파싱 실패"

    # ── XLSX
    if name.endswith(".xlsx"):
        try:
            df = pd.read_excel(io.BytesIO(data), dtype=str, engine="openpyxl")
            return df, ""
        except Exception as e:
            return None, f"xlsx: {e}"

    # ── XLS (LinkedIn은 HTML 위장 .xls를 내보내는 경우가 많음)
    if name.endswith(".xls"):
        # 1) xlrd 시도 (진짜 바이너리 xls)
        try:
            df = pd.read_excel(io.BytesIO(data), dtype=str, engine="xlrd")
            return df, ""
        except Exception as e:
            errors.append(f"xlrd: {e}")

        # 2) HTML 테이블 파싱 (LinkedIn이 .xls로 저장한 HTML 위장 파일)
        try:
            tables = pd.read_html(io.BytesIO(data), encoding="utf-8", flavor="lxml")
            if tables:
                return tables[0].astype(str), ""
        except Exception as e:
            errors.append(f"html-utf8: {e}")

        try:
            tables = pd.read_html(io.BytesIO(data), encoding="cp949", flavor="lxml")
            if tables:
                return tables[0].astype(str), ""
        except Exception as e:
            errors.append(f"html-cp949: {e}")

        # 3) openpyxl 최후 시도
        try:
            df = pd.read_excel(io.BytesIO(data), dtype=str, engine="openpyxl")
            return df, ""
        except Exception as e:
            errors.append(f"openpyxl: {e}")

        return None, " | ".join(errors)

    return None, f"지원하지 않는 확장자: {name}"


# ── 파일 유형 자동 감지 ──────────────────────────────────────────

def detect_file_type(df: pd.DataFrame) -> str:
    """'content' | 'visitors' | 'unknown'"""
    cols_lower = [str(c).lower().strip() for c in df.columns]

    visitor_hits = sum(1 for pat in _VISITORS_SIGNATURE_COLS if pat in cols_lower)
    content_hits = sum(1 for pat in _CONTENT_SIGNATURE_COLS if pat in cols_lower)

    if visitor_hits >= 2 and visitor_hits > content_hits:
        return "visitors"
    if content_hits >= 2:
        return "content"
    return "unknown"


# ── Content 파일 컬럼 매핑 ────────────────────────────────────────

def guess_column_mapping(df_columns: list[str]) -> dict[str, Optional[str]]:
    """
    내부 컬럼명 → 실제 파일 컬럼명 매핑 추론.
    못 찾은 경우 None.
    """
    col_lower = {str(c).lower().strip(): c for c in df_columns}
    mapping: dict[str, Optional[str]] = {}

    for internal, aliases in _CONTENT_COL_ALIASES.items():
        found = None
        for alias in aliases:
            if alias in col_lower:
                found = col_lower[alias]
                break
        # 부분 매칭 (정확 매칭 실패 시)
        if found is None:
            for alias in aliases:
                for actual_lower, actual in col_lower.items():
                    if alias in actual_lower or actual_lower in alias:
                        found = actual
                        break
                if found:
                    break
        mapping[internal] = found

    return mapping


# ── 해시태그 추출 ────────────────────────────────────────────────

def extract_hashtags_from_text(text: str) -> list[str]:
    """게시물 본문에서 #태그 추출 → 정규화된 목록."""
    if not text or not isinstance(text, str):
        return []
    tags = re.findall(r"#([\w가-힣]+)", text)
    seen: set[str] = set()
    result: list[str] = []
    for t in tags:
        normalized = "#" + re.sub(r"\s+", "", t).lower()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


# ── Content 파일 파싱 ─────────────────────────────────────────────

def parse_content_file(
    df_raw: pd.DataFrame,
    mapping: dict[str, Optional[str]],
) -> list[dict]:
    """
    매핑을 적용해 내부 형식 dict 목록 반환.
    해시태그는 text 컬럼에서 자동 추출.
    """
    rows = []

    for _, raw_row in df_raw.iterrows():
        def _get(internal: str, default="") -> str:
            col = mapping.get(internal)
            if col and col in df_raw.columns:
                v = raw_row.get(col, default)
                return "" if (v is None or (isinstance(v, float) and np.isnan(v))) else str(v).strip()
            return default

        def _num(internal: str):
            v = _get(internal)
            if not v:
                return np.nan
            # 콤마 제거 후 숫자 변환
            try:
                return float(re.sub(r"[,\s]", "", v))
            except ValueError:
                return np.nan

        text_val = _get("text")
        hashtags = extract_hashtags_from_text(text_val)

        # 날짜 정규화
        raw_date = _get("published_at")
        try:
            parsed_date = str(pd.to_datetime(raw_date, dayfirst=False).date())
        except Exception:
            parsed_date = raw_date

        rows.append({
            "published_at"  : parsed_date,
            "url"           : _get("url"),
            "title"         : _get("title") or text_val[:60] or "(제목 없음)",
            "content_type"  : _get("content_type"),
            "impressions"   : _num("impressions"),
            "link_clicks"   : _num("link_clicks"),
            "reactions"     : _num("reactions"),
            "comments"      : _num("comments"),
            "reposts"       : _num("reposts"),
            "hashtags_auto" : ", ".join(hashtags),  # 본문에서 추출한 자동 태그
            "_raw_text"     : text_val[:200],        # 미리보기용 (저장 안 함)
        })

    return rows


# ── 중복 감지 ────────────────────────────────────────────────────

def detect_duplicates(
    new_rows: list[dict],
    existing_df: pd.DataFrame,
) -> list[dict]:
    """
    각 새 행에 _dup_type / _dup_post_id 필드 추가.
    - 'url'    : URL 완전 일치
    - 'date+title': 날짜+제목(앞 20자) 일치
    - None     : 신규
    """
    existing_urls = {}
    existing_date_title = {}

    for _, row in existing_df.iterrows():
        url = str(row.get("url", "")).strip().rstrip("/")
        pid = str(row.get("post_id", ""))
        if url:
            existing_urls[url] = pid
        dt_key = f"{row.get('published_at','')}|{str(row.get('title',''))[:20]}"
        existing_date_title[dt_key] = pid

    result = []
    for r in new_rows:
        r2 = dict(r)
        url_key = str(r2.get("url", "")).strip().rstrip("/")
        dt_key  = f"{r2.get('published_at','')}|{str(r2.get('title',''))[:20]}"

        if url_key and url_key in existing_urls:
            r2["_dup_type"] = "url"
            r2["_dup_post_id"] = existing_urls[url_key]
        elif dt_key in existing_date_title:
            r2["_dup_type"] = "date+title"
            r2["_dup_post_id"] = existing_date_title[dt_key]
        else:
            r2["_dup_type"] = None
            r2["_dup_post_id"] = None
        result.append(r2)
    return result


# ── 기존 해시태그 보존 여부 판단 ────────────────────────────────────

def _was_manually_edited(existing_hashtags: str, auto_hashtags: str) -> bool:
    """기존 저장 해시태그와 자동 추출 해시태그가 다르면 수동 편집된 것으로 간주."""
    def _norm(s):
        return set(h.strip().lower() for h in re.split(r"[,\s]+", s or "") if h.strip())
    return bool(existing_hashtags) and _norm(existing_hashtags) != _norm(auto_hashtags)


# ── 데이터 병합 ───────────────────────────────────────────────────

def merge_into_existing(
    existing_df: pd.DataFrame,
    confirmed_rows: list[dict],
    preserve_hashtags: bool = True,
) -> tuple[pd.DataFrame, dict]:
    """
    기존 DataFrame에 확인된 행 목록을 병합.

    Returns:
        (updated_df, stats)  where stats = {new, updated, skipped}
    """
    import hashlib
    from datetime import datetime

    df = existing_df.copy()
    stats = {"new": 0, "updated": 0, "skipped": 0}

    # post_id 인덱스 빌드
    idx_by_id: dict[str, int] = {str(row["post_id"]): i
                                  for i, row in df.iterrows()
                                  if pd.notna(row.get("post_id"))}

    new_rows = []

    for r in confirmed_rows:
        pid = r.get("_dup_post_id")
        dup_type = r.get("_dup_type")
        hashtags = r.get("hashtags", r.get("hashtags_auto", ""))
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        def _safe_num(v):
            try:
                return float(v) if v is not None and not (isinstance(v, float) and np.isnan(v)) else np.nan
            except Exception:
                return np.nan

        base = {
            "published_at"  : r.get("published_at", ""),
            "url"           : r.get("url", ""),
            "title"         : r.get("title", ""),
            "content_type"  : r.get("content_type", ""),
            "impressions"   : _safe_num(r.get("impressions")),
            "link_clicks"   : _safe_num(r.get("link_clicks")),
            "reactions"     : _safe_num(r.get("reactions")),
            "comments"      : _safe_num(r.get("comments")),
            "reposts"       : _safe_num(r.get("reposts")),
        }

        if pid and pid in idx_by_id:
            # 기존 행 업데이트
            loc = idx_by_id[pid]
            existing_tags = str(df.at[loc, "hashtags"] or "")
            auto_tags = r.get("hashtags_auto", "")

            if preserve_hashtags and _was_manually_edited(existing_tags, auto_tags):
                # 수동 편집된 해시태그는 보존
                pass
            else:
                df.at[loc, "hashtags"] = hashtags

            for k, v in base.items():
                df.at[loc, k] = v
            stats["updated"] += 1

        else:
            # 신규 행
            raw = str(r.get("published_at", "")) + str(r.get("title", ""))
            new_pid = hashlib.md5(raw.encode()).hexdigest()[:12]
            new_row = {
                "post_id"       : new_pid,
                "discovery_path": "",
                "source_keywords": "",
                "campaign"      : "",
                "ga4_sessions"      : np.nan,
                "ga4_active_users"  : np.nan,
                "ga4_engaged_sessions": np.nan,
                "ga4_avg_engage_sec"  : np.nan,
                "utm_content"   : "",
                "promotion"     : "Organic",
                "measured_at"   : "",
                "note"          : "",
                "added_at"      : now_str,
                "hashtags"      : hashtags,
                **base,
            }
            new_rows.append(new_row)
            stats["new"] += 1

    if new_rows:
        df = pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True)

    return df, stats


# ── Streamlit 렌더링 ─────────────────────────────────────────────

def render_import_section(
    existing_df: pd.DataFrame,
    prefix: str,
    ss_key: str,
    on_save,      # callable(df_new: pd.DataFrame) → bool
) -> None:
    """
    LinkedIn 파일 가져오기 UI.
    on_save: 확인 후 저장 처리 콜백.
    """
    import_key = f"{prefix}import"

    with st.expander("📥 LinkedIn 파일 가져오기 (Content · Visitors)", expanded=False):
        st.markdown("""
<div style="background:#EFF6FF;border-left:4px solid #3B82F6;
     padding:10px 14px;border-radius:6px;margin-bottom:.75rem;font-size:13px;color:#374151">
LinkedIn 게시물 성과를 자동 반영합니다.
해시태그별 대시보드 유입은 LinkedIn이 직접 제공하지 않으므로,
UTM별 GA4 유입 수치를 추가한 경우에만 함께 비교할 수 있습니다.
</div>""", unsafe_allow_html=True)

        col_type, col_up = st.columns([1, 3])
        with col_type:
            file_type_sel = st.selectbox(
                "파일 유형",
                ["자동 감지", "게시물 성과 (Content)", "방문자 특성 (Visitors)"],
                key=f"{prefix}import_type",
            )
        with col_up:
            uploaded = st.file_uploader(
                "LinkedIn Company Page 관리자에서 내려받은 파일",
                type=["xlsx", "xls", "csv"],
                key=f"{prefix}import_file",
                help="LinkedIn 관리자 > 분석 > 게시물/방문자 > Excel 내보내기",
            )

        if not uploaded:
            st.caption("LinkedIn 관리자 > 분석 > 게시물 또는 방문자 > 내보내기로 파일을 받으세요.")
            return

        # 파일 읽기
        with st.spinner("파일 읽는 중..."):
            df_raw, read_err = _read_file(uploaded)

        if df_raw is None or len(df_raw) == 0:
            st.error(
                "파일을 읽을 수 없습니다. xlsx/xls/csv 형식인지 확인하세요.\n\n"
                f"**오류 상세:** {read_err}" if read_err else
                "파일을 읽을 수 없습니다. xlsx/xls/csv 형식인지 확인하세요."
            )
            return

        # 파일 유형 결정
        if file_type_sel == "자동 감지":
            detected = detect_file_type(df_raw)
        elif "Visitors" in file_type_sel:
            detected = "visitors"
        else:
            detected = "content"

        if detected == "visitors":
            _render_visitors_preview(df_raw, prefix)
            return

        if detected == "unknown":
            st.warning("파일 유형을 자동 감지하지 못했습니다. '게시물 성과 (Content)' 또는 '방문자 특성 (Visitors)'을 직접 선택하세요.")
            return

        # Content 파일 처리
        _render_content_import(df_raw, existing_df, prefix, ss_key, on_save)


def _render_visitors_preview(df_raw: pd.DataFrame, prefix: str) -> None:
    """방문자 특성 파일 미리보기 (세션 상태에 저장)."""
    st.success(f"✅ 방문자 특성 파일 감지 — {len(df_raw)}행")

    # 세션 상태에 저장 (방문자 데이터는 영구 저장 안 함)
    st.session_state[f"{prefix}visitors_df"] = df_raw

    st.markdown("#### 방문자 데이터 미리보기")
    st.dataframe(df_raw.head(20), use_container_width=True)
    st.caption("방문자 데이터는 현재 세션 동안만 유지되며, 게시물 성과 데이터와 병합되지 않습니다.")


def _render_content_import(
    df_raw: pd.DataFrame,
    existing_df: pd.DataFrame,
    prefix: str,
    ss_key: str,
    on_save,
) -> None:
    """Content 파일 컬럼 매핑 → 미리보기 → 확정 UI."""

    columns = list(df_raw.columns)
    mapping = guess_column_mapping(columns)

    # ── 컬럼 매핑 확인 / 수정
    required = ["published_at", "url", "impressions"]
    missing_required = [k for k in required if not mapping.get(k)]

    with st.expander("🔧 컬럼 매핑 확인" + (" ⚠️ 필수 항목 미매핑" if missing_required else " ✅"), expanded=bool(missing_required)):
        st.caption("LinkedIn 내보내기 버전마다 컬럼명이 다를 수 있습니다. 잘못된 매핑은 직접 수정하세요.")

        col_options = ["(건너뜀)"] + columns
        updated_mapping = {}

        internal_labels = {
            "published_at" : "게시일 *",
            "url"          : "게시물 URL *",
            "impressions"  : "노출수 *",
            "link_clicks"  : "링크 클릭",
            "reactions"    : "반응",
            "comments"     : "댓글",
            "reposts"      : "리포스트",
            "text"         : "게시물 본문 (해시태그 추출)",
            "title"        : "제목",
            "content_type" : "콘텐츠 유형",
        }

        cols_per_row = 2
        items = list(internal_labels.items())
        for i in range(0, len(items), cols_per_row):
            row_items = items[i:i+cols_per_row]
            row_cols = st.columns(cols_per_row)
            for j, (internal, label) in enumerate(row_items):
                current = mapping.get(internal)
                try:
                    idx = col_options.index(current) if current in col_options else 0
                except ValueError:
                    idx = 0
                sel = row_cols[j].selectbox(
                    label,
                    col_options,
                    index=idx,
                    key=f"{prefix}map_{internal}",
                )
                updated_mapping[internal] = sel if sel != "(건너뜀)" else None

    mapping.update(updated_mapping)

    # 필수 항목 재확인
    still_missing = [k for k in required if not mapping.get(k)]
    if still_missing:
        labels = {"published_at": "게시일", "url": "게시물 URL", "impressions": "노출수"}
        st.error(f"필수 컬럼 미매핑: {', '.join(labels.get(k, k) for k in still_missing)}")
        return

    # ── 파싱
    parsed = parse_content_file(df_raw, mapping)
    if not parsed:
        st.warning("가져올 데이터가 없습니다.")
        return

    parsed_with_dup = detect_duplicates(parsed, existing_df)

    n_total   = len(parsed_with_dup)
    n_dup_url = sum(1 for r in parsed_with_dup if r.get("_dup_type") == "url")
    n_dup_dt  = sum(1 for r in parsed_with_dup if r.get("_dup_type") == "date+title")
    n_new     = sum(1 for r in parsed_with_dup if r.get("_dup_type") is None)
    n_no_tag  = sum(1 for r in parsed_with_dup if not r.get("hashtags_auto"))

    # ── 미리보기 요약
    st.markdown("#### 가져오기 미리보기")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("전체 행", n_total)
    m2.metric("신규", n_new)
    m3.metric("중복(업데이트)", n_dup_url + n_dup_dt)
    m4.metric("해시태그 없음", n_no_tag,
              delta="보완 필요" if n_no_tag > 0 else None,
              delta_color="inverse" if n_no_tag > 0 else "normal")

    # ── 미리보기 테이블
    preview_rows = []
    for r in parsed_with_dup:
        dup = r.get("_dup_type")
        status = ("🔄 URL 중복" if dup == "url"
                  else "🔄 날짜+제목 중복" if dup == "date+title"
                  else "🆕 신규")
        tags = r.get("hashtags_auto", "")
        preview_rows.append({
            "상태"       : status,
            "게시일"     : r.get("published_at", ""),
            "제목(앞50)" : str(r.get("title", ""))[:50],
            "노출수"     : r.get("impressions", ""),
            "반응"       : r.get("reactions", ""),
            "링크클릭"   : r.get("link_clicks", ""),
            "자동 해시태그" : tags if tags else "⚠️ 없음",
        })
    st.dataframe(pd.DataFrame(preview_rows), use_container_width=True, height=260)

    # ── 해시태그 보완 UI (해시태그 없는 게시물만)
    hashtag_edits: dict[int, str] = {}
    if n_no_tag > 0:
        with st.expander(f"✏️ 해시태그 보완 필요 ({n_no_tag}건)", expanded=True):
            st.caption("본문에서 해시태그를 추출하지 못한 게시물입니다. 직접 입력하거나 비워 두세요.")
            for idx, r in enumerate(parsed_with_dup):
                if r.get("hashtags_auto"):
                    continue
                label = f"{r.get('published_at','')} | {str(r.get('title',''))[:40]}"
                val = st.text_input(
                    label,
                    key=f"{prefix}tag_edit_{idx}",
                    placeholder="#AIAgent, #디지털전환",
                )
                hashtag_edits[idx] = val

    # ── 해시태그 병합 (자동 + 수동 보완)
    confirmed = []
    for idx, r in enumerate(parsed_with_dup):
        r2 = dict(r)
        manual = hashtag_edits.get(idx, "")
        auto   = r2.get("hashtags_auto", "")
        if auto:
            r2["hashtags"] = auto
        elif manual.strip():
            # 수동 입력 해시태그 정규화
            tags = re.split(r"[,\n\r]+", manual)
            seen: set[str] = set()
            normed = []
            for t in tags:
                t = t.strip().lstrip("#").strip()
                if not t:
                    continue
                n = "#" + re.sub(r"\s+", "", t).lower()
                if n not in seen:
                    seen.add(n)
                    normed.append(n)
            r2["hashtags"] = ", ".join(normed)
        else:
            r2["hashtags"] = ""
        confirmed.append(r2)

    # ── 옵션
    preserve = st.checkbox(
        "기존에 수동으로 편집한 해시태그는 덮어쓰지 않기",
        value=True,
        key=f"{prefix}preserve_tags",
    )

    # ── 확정 버튼
    st.divider()
    if st.button(
        f"✅ 가져오기 확정  ({n_new}건 추가 · {n_dup_url+n_dup_dt}건 업데이트)",
        type="primary",
        key=f"{prefix}import_confirm",
        use_container_width=True,
    ):
        with st.spinner("데이터 병합 중..."):
            df_merged, stats = merge_into_existing(existing_df, confirmed, preserve_hashtags=preserve)

        ok = on_save(df_merged)
        st.session_state[ss_key] = df_merged

        # LinkedIn 탭(index 4)에 머물도록 표시
        st.session_state["_active_tab_idx"] = 4

        if ok:
            st.success(
                f"✅ 저장 완료 — 신규 {stats['new']}건 추가, {stats['updated']}건 업데이트"
            )
        else:
            st.warning(
                f"⚠️ 로컬 저장 완료 (GitHub 동기화 실패) — 신규 {stats['new']}건, 업데이트 {stats['updated']}건"
            )
        st.rerun()


def render_visitors_section(prefix: str) -> None:
    """방문자 특성 섹션 — 세션에 Visitors 데이터가 있을 때만 표시."""
    df_vis = st.session_state.get(f"{prefix}visitors_df")
    if df_vis is None or len(df_vis) == 0:
        return

    st.markdown("---")
    st.markdown("### 👥 방문자 특성")
    st.caption(
        "LinkedIn Company Page 방문자 특성 데이터입니다. "
        "게시물 성과 데이터와 병합되지 않으며, 세션 종료 시 초기화됩니다."
    )

    # 직무·직급·산업·회사 규모 분포 표시 (있는 컬럼만)
    col_lower_map = {str(c).lower().strip(): c for c in df_vis.columns}

    breakdown_patterns = {
        "직무 기능": ["job function", "직무 기능", "직무"],
        "직급": ["seniority", "직급"],
        "산업": ["industry", "산업"],
        "회사 규모": ["company size", "회사 규모"],
        "지역": ["country", "region", "국가", "지역"],
    }

    found_breakdowns = {}
    for label, patterns in breakdown_patterns.items():
        for pat in patterns:
            if pat in col_lower_map:
                found_breakdowns[label] = col_lower_map[pat]
                break

    if found_breakdowns:
        tabs = st.tabs(list(found_breakdowns.keys()) + ["전체 데이터"])
        for tab, (label, col) in zip(tabs, found_breakdowns.items()):
            with tab:
                sub = df_vis[[col]].copy()
                # 수치 컬럼 찾기 (첫 번째 숫자 컬럼)
                num_cols = [c for c in df_vis.columns
                            if c != col and pd.to_numeric(df_vis[c], errors="coerce").notna().any()]
                if num_cols:
                    sub[num_cols[0]] = pd.to_numeric(df_vis[num_cols[0]], errors="coerce")
                    sub = sub.dropna().sort_values(num_cols[0], ascending=False)
                    st.dataframe(sub.rename(columns={col: label}), use_container_width=True)
                else:
                    st.dataframe(sub, use_container_width=True)

        with tabs[-1]:
            st.dataframe(df_vis, use_container_width=True)
    else:
        st.dataframe(df_vis, use_container_width=True)
