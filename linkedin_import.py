"""
linkedin_import.py — LinkedIn Company Page Content / Visitors Excel 파싱 모듈

지원 파일:
  Content  : 관리자 > 분석 > 게시물 > 게시물 성과 내보내기 (.xls / .xlsx / .csv)
  Visitors : 관리자 > 분석 > 방문자 > 방문자 특성 내보내기 (.xls / .xlsx)

LinkedIn 로그인 / 크롤링 / 비공식 API 미사용.
"""

from __future__ import annotations

import io
import re
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd


# ── Content 표준 컬럼 매핑 ────────────────────────────────────────────
_STANDARD_MAP: dict[str, str] = {
    "게시물의 제목"   : "text",
    "게시물 링크"     : "url",
    "만든 날짜"       : "published_at",
    "게시물 형식"     : "post_format",
    "캠페인 이름"     : "campaign",
    "콘텐츠 종류"     : "content_type",
    "노출수"          : "impressions",
    "조회수"          : "views",
    "외부 사이트 조회": "external_views",
    "클릭"            : "clicks",
    "클릭률(CTR)"     : "ctr",
    "추천"            : "reactions",
    "댓글"            : "comments",
    "퍼감"            : "reposts",
    "팔로워"          : "followers",
    "참여율"          : "engagement_rate",
}

_REQUIRED_INTERNAL = {"url", "impressions", "published_at"}
_REQUIRED_KR       = {"게시물의 제목", "게시물 링크", "노출수"}

_NUM_COLS = {
    "impressions", "views", "external_views", "clicks",
    "ctr", "reactions", "comments", "reposts", "followers", "engagement_rate",
}

# ── Visitors 시트 이름 ─────────────────────────────────────────────────
_VISITOR_SHEETS = {"방문자 통계", "지역", "직종", "직급", "업계", "회사 규모"}
_VISITOR_BREAKDOWN_SHEETS = ["지역", "직종", "직급", "업계", "회사 규모"]


# ══════════════════════════════════════════════════════════════════════
# 파일 유형 감지
# ══════════════════════════════════════════════════════════════════════

def detect_upload_type(uploaded) -> tuple[str, str]:
    """
    업로드 파일 유형 자동 감지.
    Returns: (file_type, error_msg)
    file_type: 'content' | 'visitors' | 'unknown'
    """
    name = uploaded.name.lower()

    if name.endswith(".csv"):
        uploaded.seek(0)
        return "content", ""

    data = uploaded.read()
    uploaded.seek(0)

    engine = "openpyxl" if name.endswith(".xlsx") else "xlrd"
    try:
        xf = pd.ExcelFile(io.BytesIO(data), engine=engine)
    except Exception as e:
        # xlrd 실패 → HTML 위장 XLS 시도
        try:
            pd.read_html(io.BytesIO(data), flavor="lxml", encoding="utf-8")
            uploaded.seek(0)
            return "content", ""  # HTML XLS는 Content로 처리
        except Exception:
            return "unknown", str(e)

    sheets = set(xf.sheet_names)

    # Content 시트 우선
    for c in ("전체 게시물", "All posts", "Posts"):
        if c in sheets:
            return "content", ""

    # Visitors 시트 감지 (2개 이상 or 방문자 통계 단독)
    visitor_overlap = sheets & _VISITOR_SHEETS
    if len(visitor_overlap) >= 2 or "방문자 통계" in sheets:
        return "visitors", ""

    return "unknown", ""


# ══════════════════════════════════════════════════════════════════════
# Content 파싱 (기존)
# ══════════════════════════════════════════════════════════════════════

def read_linkedin_file(uploaded) -> tuple[Optional[pd.DataFrame], Optional[pd.DataFrame], str]:
    """
    LinkedIn Content export 파일을 읽어 (df_posts, df_stats, error) 반환.

    df_posts : 전체 게시물 시트 (header=1)
    df_stats : 통계 시트 (있으면), 없으면 None
    error    : 오류 문자열, 성공 시 ""
    """
    name = uploaded.name.lower()
    data = uploaded.read()
    uploaded.seek(0)

    # ── CSV
    if name.endswith(".csv"):
        for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
            try:
                df = pd.read_csv(io.BytesIO(data), dtype=str, encoding=enc)
                return df, None, ""
            except UnicodeDecodeError:
                continue
            except Exception as e:
                return None, None, f"CSV 파싱 오류: {e}"
        return None, None, "CSV 인코딩 감지 실패"

    # ── XLSX / XLS
    engine = "openpyxl" if name.endswith(".xlsx") else "xlrd"
    try:
        xf = pd.ExcelFile(io.BytesIO(data), engine=engine)
    except Exception as e:
        return None, None, f"Excel 열기 실패: {e}"

    sheets = xf.sheet_names
    posts_sheet = _find_posts_sheet(xf, sheets)
    if posts_sheet is None:
        return None, None, (
            f"게시물 시트를 찾을 수 없습니다. (시트 목록: {sheets})\n"
            "LinkedIn Company Page > 분석 > 게시물 > '게시물 성과 내보내기'로 내려받은 파일인지 확인하세요."
        )

    df_posts = _read_posts_sheet(xf, posts_sheet)
    if df_posts is None:
        return None, None, f"'{posts_sheet}' 시트에서 필수 컬럼({_REQUIRED_KR})을 찾을 수 없습니다."

    df_stats = None
    for sname in sheets:
        if sname != posts_sheet:
            try:
                df_stats = xf.parse(sname, header=1, dtype=str)
            except Exception:
                pass
            break

    return df_posts, df_stats, ""


def _find_posts_sheet(xf: pd.ExcelFile, sheets: list[str]) -> Optional[str]:
    for candidate in ("전체 게시물", "All posts", "Posts"):
        if candidate in sheets:
            return candidate
    for sname in sheets:
        try:
            df = xf.parse(sname, header=1, dtype=str, nrows=1)
            if _REQUIRED_KR.issubset(set(df.columns)):
                return sname
        except Exception:
            continue
    return None


def _read_posts_sheet(xf: pd.ExcelFile, sheet: str) -> Optional[pd.DataFrame]:
    try:
        df = xf.parse(sheet, header=1, dtype=str)
    except Exception:
        return None
    if not _REQUIRED_KR.issubset(set(df.columns)):
        return None
    return df


# ── 해시태그 추출 ─────────────────────────────────────────────────────

def extract_hashtags(text: str) -> str:
    if not text or not isinstance(text, str):
        return ""
    raw_tags = re.findall(r"#([a-zA-Z0-9_가-힣ㄱ-ㆎ]+)", text)
    seen: set[str] = set()
    result: list[str] = []
    for t in raw_tags:
        norm = "#" + t.lower()
        if norm not in seen:
            seen.add(norm)
            result.append(norm)
    return ", ".join(result)


def _to_num(val: str) -> float:
    if val is None or str(val).strip() in ("", "nan", "None", "-"):
        return np.nan
    cleaned = re.sub(r"[,%\s]", "", str(val))
    try:
        return float(cleaned)
    except ValueError:
        return np.nan


def parse_posts(df_raw: pd.DataFrame) -> list[dict]:
    rows: list[dict] = []

    for _, raw in df_raw.iterrows():
        def _s(kr_col: str) -> str:
            v = raw.get(kr_col, "")
            return "" if str(v).strip() in ("nan", "None", "") else str(v).strip()

        def _n(kr_col: str) -> float:
            return _to_num(_s(kr_col))

        text = _s("게시물의 제목")
        url  = _s("게시물 링크").rstrip("/")

        raw_date = _s("만든 날짜")
        try:
            published_at = str(pd.to_datetime(raw_date).date())
        except Exception:
            published_at = raw_date

        rows.append({
            "url"           : url,
            "published_at"  : published_at,
            "title"         : text[:80] + ("…" if len(text) > 80 else ""),
            "text"          : text,
            "post_format"   : _s("게시물 형식"),
            "campaign"      : _s("캠페인 이름"),
            "content_type"  : _s("콘텐츠 종류"),
            "hashtags"      : extract_hashtags(text),
            "impressions"   : _n("노출수"),
            "views"         : _n("조회수"),
            "external_views": _n("외부 사이트 조회"),
            "clicks"        : _n("클릭"),
            "ctr"           : _n("클릭률(CTR)"),
            "reactions"     : _n("추천"),
            "comments"      : _n("댓글"),
            "reposts"       : _n("퍼감"),
            "followers"     : _n("팔로워"),
            "engagement_rate": _n("참여율"),
        })

    return [r for r in rows if r["url"]]


def merge_posts(
    existing_df: pd.DataFrame,
    new_rows: list[dict],
) -> tuple[pd.DataFrame, dict]:
    import hashlib

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    url_idx: dict[str, int] = {}
    for i, row in existing_df.iterrows():
        u = str(row.get("url", "")).rstrip("/")
        if u:
            url_idx[u] = int(i)

    extra_rows: list[dict] = []
    stats = {"new": 0, "updated": 0}

    for r in new_rows:
        url = r["url"].rstrip("/")
        pid = hashlib.md5(url.encode()).hexdigest()[:12]

        if url in url_idx:
            loc = url_idx[url]
            for col in ("published_at", "title", "text", "post_format",
                        "campaign", "content_type", "impressions", "views",
                        "external_views", "clicks", "ctr", "reactions",
                        "comments", "reposts", "followers", "engagement_rate"):
                if col in existing_df.columns:
                    existing_df.at[loc, col] = r.get(col, "")
            existing_tags = str(existing_df.at[loc, "hashtags"] or "").strip()
            if not existing_tags or existing_tags == "nan":
                existing_df.at[loc, "hashtags"] = r.get("hashtags", "")
            existing_df.at[loc, "updated_at"] = now_str
            stats["updated"] += 1
        else:
            extra_rows.append({
                "post_id"        : pid,
                "url"            : r["url"],
                "published_at"   : r["published_at"],
                "title"          : r["title"],
                "text"           : r["text"],
                "post_format"    : r["post_format"],
                "campaign"       : r["campaign"],
                "content_type"   : r["content_type"],
                "hashtags"       : r["hashtags"],
                "impressions"    : r["impressions"],
                "views"          : r["views"],
                "external_views" : r["external_views"],
                "clicks"         : r["clicks"],
                "ctr"            : r["ctr"],
                "reactions"      : r["reactions"],
                "comments"       : r["comments"],
                "reposts"        : r["reposts"],
                "followers"      : r["followers"],
                "engagement_rate": r["engagement_rate"],
                "utm_content"    : "",
                "ga4_sessions"   : np.nan,
                "added_at"       : now_str,
                "updated_at"     : now_str,
            })
            stats["new"] += 1

    if extra_rows:
        existing_df = pd.concat(
            [existing_df, pd.DataFrame(extra_rows)],
            ignore_index=True,
        )

    return existing_df, stats


# ══════════════════════════════════════════════════════════════════════
# Visitors 파싱
# ══════════════════════════════════════════════════════════════════════

def read_visitors_file(uploaded) -> tuple[dict[str, pd.DataFrame], str, str]:
    """
    LinkedIn Visitors export 파일을 읽어 (sheets_data, period_label, error) 반환.

    sheets_data  : {"방문자 통계": df, "지역": df, ...}
    period_label : 파일 내 기간 문자열 (없으면 오늘 날짜)
    error        : 오류 문자열, 성공 시 ""
    """
    name = uploaded.name.lower()
    data = uploaded.read()
    uploaded.seek(0)

    engine = "openpyxl" if name.endswith(".xlsx") else "xlrd"
    try:
        xf = pd.ExcelFile(io.BytesIO(data), engine=engine)
    except Exception as e:
        return {}, "", f"파일 열기 실패: {e}"

    sheets_data: dict[str, pd.DataFrame] = {}
    period_label = ""

    for sname in xf.sheet_names:
        if sname not in _VISITOR_SHEETS:
            continue
        try:
            # Row 0 에서 기간 텍스트 추출 시도
            df_peek = xf.parse(sname, header=None, dtype=str, nrows=2)
            if not period_label and len(df_peek) > 0:
                first_row_text = " ".join(
                    str(v) for v in df_peek.iloc[0].tolist() if pd.notna(v)
                )
                date_matches = re.findall(r"\d{4}[-./]\d{1,2}[-./]\d{1,2}", first_row_text)
                if len(date_matches) >= 2:
                    d0 = re.sub(r"[./]", "-", date_matches[0])
                    d1 = re.sub(r"[./]", "-", date_matches[-1])
                    period_label = f"{d0} ~ {d1}"
                elif len(date_matches) == 1:
                    period_label = re.sub(r"[./]", "-", date_matches[0])

            # header=1 (row0=설명, row1=헤더)
            df = xf.parse(sname, header=1, dtype=str)
            if df.empty or len(df.columns) < 2:
                df = xf.parse(sname, header=0, dtype=str)

            df = df.dropna(how="all")
            if not df.empty:
                sheets_data[sname] = df
        except Exception:
            continue

    if not period_label:
        from datetime import date as _date
        period_label = str(_date.today())

    if not sheets_data:
        return {}, period_label, "방문자 시트를 읽을 수 없습니다. LinkedIn 방문자 특성 내보내기 파일인지 확인하세요."

    return sheets_data, period_label, ""


def parse_visitors_snapshot(
    sheets_data: dict[str, pd.DataFrame],
    period_label: str,
    uploaded_at: str,
) -> list[dict]:
    """
    Visitors 시트 데이터 → snapshot row 목록.

    각 row: snapshot_id, uploaded_at, period_label, sheet, rank, label, count, pct
    """
    import hashlib
    snapshot_id = hashlib.md5(period_label.encode()).hexdigest()[:8]
    rows: list[dict] = []

    def _base(sheet: str, rank: int, label: str, count, pct) -> dict:
        return {
            "snapshot_id" : snapshot_id,
            "uploaded_at" : uploaded_at,
            "period_label": period_label,
            "sheet"       : sheet,
            "rank"        : rank,
            "label"       : label,
            "count"       : count,
            "pct"         : pct,
        }

    # ── 방문자 통계 → 총 방문자 수
    if "방문자 통계" in sheets_data:
        df = sheets_data["방문자 통계"].copy()
        # 가장 큰 합계를 가진 숫자 컬럼 합산
        total = None
        for col in df.columns:
            numeric = pd.to_numeric(df[col], errors="coerce")
            valid = numeric.dropna()
            if len(valid) >= 1:
                col_sum = int(valid.sum())
                if total is None or col_sum > total:
                    total = col_sum
        if total is not None:
            rows.append(_base("총_방문자", 1, "총 방문자", total, 100.0))

    # ── 분류별 breakdown
    for sname in _VISITOR_BREAKDOWN_SHEETS:
        if sname not in sheets_data:
            continue
        df = sheets_data[sname].copy()
        if df.empty:
            continue

        # label 컬럼: 첫 번째로 보이는 문자열 위주 컬럼
        label_col = None
        count_col = None
        pct_col   = None

        for col in df.columns:
            col_str = str(col).strip()
            numeric = pd.to_numeric(df[col], errors="coerce")
            n_valid = numeric.notna().sum()
            n_rows  = len(df)

            if n_valid / max(n_rows, 1) < 0.4:
                # 주로 문자열 → label
                if label_col is None:
                    label_col = col
                continue

            # 숫자 컬럼: % 인지 count 인지 판별
            vals = numeric.dropna()
            if "%" in col_str or (len(vals) > 0 and vals.between(0, 101).all()):
                if pct_col is None:
                    pct_col = col
            else:
                if count_col is None:
                    count_col = col

        if label_col is None:
            # fallback: 첫 번째 컬럼을 label로
            label_col = df.columns[0]

        rank = 0
        for _, row in df.iterrows():
            label_val = str(row.get(label_col, "")).strip()
            if not label_val or label_val.lower() in ("nan", "none", "합계", "total", "기타"):
                continue

            count_val = None
            if count_col:
                cv = pd.to_numeric(row.get(count_col, ""), errors="coerce")
                count_val = int(cv) if pd.notna(cv) else None

            pct_val = None
            if pct_col:
                raw_pct = str(row.get(pct_col, "")).replace("%", "").strip()
                pv = pd.to_numeric(raw_pct, errors="coerce")
                if pd.notna(pv):
                    pct_val = float(pv) if pv > 1 else float(pv) * 100

            rank += 1
            rows.append(_base(sname, rank, label_val, count_val, pct_val))

    return rows


def merge_visitors(
    existing_df: pd.DataFrame,
    new_rows: list[dict],
) -> tuple[pd.DataFrame, dict]:
    """
    같은 period_label의 기존 snapshot을 교체하거나 신규 추가.
    Returns: (merged_df, stats)
    """
    if not new_rows:
        return existing_df, {"rows_added": 0, "replaced": False, "period_label": ""}

    snapshot_id  = new_rows[0]["snapshot_id"]
    period_label = new_rows[0]["period_label"]
    replaced     = False

    if len(existing_df) > 0 and "snapshot_id" in existing_df.columns:
        existing_ids = set(existing_df["snapshot_id"].astype(str))
        if snapshot_id in existing_ids:
            existing_df = existing_df[
                existing_df["snapshot_id"].astype(str) != snapshot_id
            ].copy()
            replaced = True

    new_df = pd.DataFrame(new_rows)
    merged = pd.concat([existing_df, new_df], ignore_index=True)

    return merged, {
        "rows_added"  : len(new_rows),
        "replaced"    : replaced,
        "period_label": period_label,
    }
