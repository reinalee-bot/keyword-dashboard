"""
7단계: 모니터링 기사 검토 결과 저장·조회 모듈

저장소 우선순위:
  1차 (영구): Google Sheets
    - 재배포/재시작 후에도 데이터 유지
    - st.secrets["gcp_service_account"] 와 st.secrets["GOOGLE_SHEET_ID"] 필요
    - 미설정 시 자동으로 2차 저장소로 폴백
  2차 (로컬 백업): data/monitoring_reviews.csv
    - Google Sheets 연동 시에도 항상 동시 기록 (로컬 캐시)
    - Streamlit Community Cloud 재배포 시 소멸 (비영구)

Streamlit 의존 없음 — 단위 테스트 가능.
인증 정보는 코드·로그·커밋에 절대 노출하지 않는다.
"""
import hashlib
import logging
import os
from datetime import datetime, timezone, timedelta

import pandas as pd

try:
    import gspread
    import gspread.exceptions
    _GSPREAD_AVAILABLE = True
except ImportError:
    gspread = None  # type: ignore
    _GSPREAD_AVAILABLE = False

BASE_DIR    = os.path.dirname(__file__)
REVIEWS_CSV = os.path.join(BASE_DIR, "data", "monitoring_reviews.csv")

REVIEW_COLS = [
    "article_id", "title", "url", "media", "published_at",
    "category", "monitoring_priority", "relevance_score",
    "news_importance_score", "pr_usability_score",
    "selection_reason", "pr_suggestion",
    "review_status", "usage_type", "exclusion_reason",
    "follow_up_required", "reviewer_memo", "reviewed_at",
    # P5C: 분류 근거 필드 (신규)
    "promotional_likelihood", "title_signal", "description_signal",
    "matched_rule", "promotional_score", "classification_basis",
]

REVIEW_STATUSES   = ["검토 전", "관심 기사", "PR 후보", "제외"]
USAGE_TYPES       = ["기획기사", "보도자료", "인터뷰", "온드미디어", "내부 브리핑", "추가 검토"]
EXCLUSION_REASONS = [
    "보도자료성", "SCK 관련성 낮음", "인사이트 부족", "근거 부족",
    "중복 기사", "오래된 기사", "오분류", "기타",
]

_KST      = timezone(timedelta(hours=9))
_log      = logging.getLogger(__name__)
_WSNAME   = "monitoring_reviews"
_COL_END  = chr(ord('A') + len(REVIEW_COLS) - 1)  # 'X' (24열)

# ─────────────────────────────────────────────────────────────
# 기사 식별자
# ─────────────────────────────────────────────────────────────

def make_article_id(url: str, title: str = "",
                    media: str = "", pub_date: str = "") -> str:
    """기사 고유 식별자 생성 (MD5 32자).
    URL이 있으면 정규화된 URL 기준, 없으면 제목+매체+날짜 조합.
    Python 내장 hash()는 사용하지 않는다.
    """
    if url and url.strip():
        key = url.strip().rstrip("/").lower()
    else:
        key = f"{title.strip()}|{media.strip()}|{pub_date.strip()}"
    return hashlib.md5(key.encode("utf-8")).hexdigest()


# ─────────────────────────────────────────────────────────────
# CSV 백엔드
# ─────────────────────────────────────────────────────────────

def _load_csv_df() -> pd.DataFrame:
    """CSV를 읽어 DataFrame으로 반환. 파일 없거나 읽기 실패 시 빈 DataFrame."""
    if not os.path.exists(REVIEWS_CSV):
        return pd.DataFrame(columns=REVIEW_COLS)
    try:
        df = pd.read_csv(REVIEWS_CSV, dtype=str).fillna("")
    except Exception:
        return pd.DataFrame(columns=REVIEW_COLS)
    for col in REVIEW_COLS:
        if col not in df.columns:
            df[col] = ""
    return df[REVIEW_COLS]


def _save_csv_df(df: pd.DataFrame) -> None:
    os.makedirs(os.path.dirname(REVIEWS_CSV), exist_ok=True)
    df.to_csv(REVIEWS_CSV, index=False, encoding="utf-8-sig")


def _upsert_csv(row_data: dict) -> None:
    """CSV에 article_id 기준 upsert."""
    article_id = row_data["article_id"]
    df = _load_csv_df()
    new_row = pd.DataFrame([{col: str(row_data.get(col, "")) for col in REVIEW_COLS}])
    df = df[df["article_id"] != article_id]
    df = pd.concat([df, new_row], ignore_index=True)
    _save_csv_df(df)


# ─────────────────────────────────────────────────────────────
# Google Sheets 백엔드
# ─────────────────────────────────────────────────────────────

def _get_gsheet_worksheet():
    """
    Google Sheets 워크시트 연결을 반환한다. 실패 시 None.
    인증 정보는 로그·예외 메시지에 절대 노출하지 않는다.

    인증 정보 로드 순서:
      1. st.secrets["gcp_service_account"] (Streamlit Cloud 배포 환경)
      2. GCP_SERVICE_ACCOUNT_JSON 환경변수 (JSON 문자열, 로컬 개발용)
    시트 ID 로드 순서:
      1. st.secrets["GOOGLE_SHEET_ID"]
      2. GOOGLE_SHEET_ID 환경변수
    """
    if not _GSPREAD_AVAILABLE:
        return None

    creds_dict = None
    sheet_id   = ""

    # Streamlit secrets 시도
    try:
        import streamlit as st
        raw = st.secrets.get("gcp_service_account", {})
        if raw:
            creds_dict = dict(raw)
        sheet_id = str(st.secrets.get("GOOGLE_SHEET_ID", "")).strip()
    except Exception:
        pass  # Streamlit 없는 환경 (단위 테스트 등)

    # 환경변수 fallback
    if not creds_dict:
        json_str = os.environ.get("GCP_SERVICE_ACCOUNT_JSON", "").strip()
        if json_str:
            try:
                import json
                creds_dict = json.loads(json_str)
            except Exception:
                _log.warning("GCP_SERVICE_ACCOUNT_JSON 파싱 실패 [JSONDecodeError]")
    if not sheet_id:
        sheet_id = os.environ.get("GOOGLE_SHEET_ID", "").strip()

    if not creds_dict or not sheet_id:
        return None

    try:
        gc = gspread.service_account_from_dict(creds_dict)
        sh = gc.open_by_key(sheet_id)

        try:
            ws = sh.worksheet(_WSNAME)
        except gspread.exceptions.WorksheetNotFound:
            ws = sh.add_worksheet(_WSNAME, rows=2000, cols=len(REVIEW_COLS))

        # 헤더 행 확인 및 삽입 (신규 컬럼 추가 포함)
        try:
            first_row = ws.row_values(1)
            if not first_row or first_row[0] != "article_id":
                ws.insert_row(REVIEW_COLS, 1)
            else:
                # 기존 시트에 신규 컬럼이 없으면 헤더 끝에 추가
                missing = [c for c in REVIEW_COLS if c not in first_row]
                if missing:
                    ws.update([first_row + missing], "A1")
        except Exception:
            pass

        return ws
    except Exception as exc:
        _log.warning("Google Sheets 연결 실패 [%s]", type(exc).__name__)
        return None


def _migrate_csv_to_gsheet(ws) -> None:
    """기존 CSV 데이터를 Google Sheets로 일회성 마이그레이션.
    시트에 헤더 외 데이터가 있으면 중복 방지를 위해 건너뛴다.
    """
    try:
        existing = ws.get_all_values()
        if len(existing) > 1:
            return  # 이미 데이터 존재 → 마이그레이션 불필요
        df = _load_csv_df()
        if df.empty:
            return
        rows = [list(row.astype(str)) for _, row in df.iterrows()]
        ws.append_rows(rows, value_input_option="RAW")
        _log.info("CSV → Google Sheets 마이그레이션 완료: %d건", len(rows))
    except Exception as exc:
        _log.warning("마이그레이션 실패 [%s]", type(exc).__name__)


def _gsheet_load(ws) -> dict:
    """Google Sheets에서 {article_id: row_dict} 형태로 로드."""
    try:
        records = ws.get_all_records(default_blank="")
        result = {}
        for rec in records:
            aid = str(rec.get("article_id", "")).strip()
            if aid:
                result[aid] = {col: str(rec.get(col, "")) for col in REVIEW_COLS}
        return result
    except Exception as exc:
        _log.warning("Google Sheets 읽기 실패 [%s]", type(exc).__name__)
        return {}


def _gsheet_upsert(ws, row_data: dict) -> bool:
    """Google Sheets에 article_id 기준 upsert. 헤더 기반 컬럼 매핑. 성공 시 True."""
    try:
        article_id = row_data["article_id"]
        # 헤더 기반 컬럼 매핑 — 시트 컬럼 순서와 REVIEW_COLS가 다를 수 있음
        col_map = _ws_col_map if _ws_col_map else {h: i for i, h in enumerate(REVIEW_COLS)}
        n_cols  = max(col_map.values()) + 1 if col_map else len(REVIEW_COLS)
        values  = [""] * n_cols
        for col_name, idx in col_map.items():
            if col_name in row_data:
                values[idx] = str(row_data.get(col_name, ""))
        col_end = chr(ord('A') + n_cols - 1)
        cell = ws.find(article_id, in_column=1)
        if cell is not None:
            # gspread 6.x: update(values, range_name) — 인자 순서 주의
            ws.update([values], f"A{cell.row}:{col_end}{cell.row}")
        else:
            ws.append_row(values, value_input_option="RAW")
        return True
    except Exception as exc:
        _log.warning("Google Sheets 쓰기 실패 [%s]", type(exc).__name__)
        return False


def _gsheet_delete(ws, article_id: str) -> bool:
    """Google Sheets에서 article_id 행 삭제. 성공 시 True."""
    try:
        cell = ws.find(article_id, in_column=1)
        if cell is None:
            return False
        ws.delete_rows(cell.row)
        return True
    except Exception as exc:
        _log.warning("Google Sheets 삭제 실패 [%s]", type(exc).__name__)
        return False


# ─────────────────────────────────────────────────────────────
# 워크시트 싱글턴 (프로세스 내 1회 연결)
# ─────────────────────────────────────────────────────────────

_ws_singleton = None
_ws_init_done = False
_ws_col_map: dict = {}  # {col_name: 0-based col index} — 헤더 기반 컬럼 위치 캐시


def _get_ws():
    """캐시된 워크시트를 반환한다. 첫 호출 시 연결 및 마이그레이션을 수행한다."""
    global _ws_singleton, _ws_init_done, _ws_col_map
    if not _ws_init_done:
        _ws_singleton = _get_gsheet_worksheet()
        if _ws_singleton is not None:
            _migrate_csv_to_gsheet(_ws_singleton)
            try:
                headers = _ws_singleton.row_values(1) or REVIEW_COLS[:]
                _ws_col_map = {h: i for i, h in enumerate(headers)}
            except Exception:
                _ws_col_map = {h: i for i, h in enumerate(REVIEW_COLS)}
        _ws_init_done = True
    return _ws_singleton


def reset_ws_cache() -> None:
    """워크시트 캐시를 초기화한다 (테스트·재연결 용도)."""
    global _ws_singleton, _ws_init_done, _ws_col_map
    _ws_singleton = None
    _ws_init_done = False
    _ws_col_map   = {}


# ─────────────────────────────────────────────────────────────
# 공개 API
# ─────────────────────────────────────────────────────────────

def load_reviews() -> dict:
    """저장된 검토 결과를 {article_id: review_dict} 형태로 반환한다.

    Google Sheets가 연결돼 있으면 Sheets에서 로드,
    실패하거나 미설정 시 CSV에서 로드한다.
    """
    ws = _get_ws()
    if ws is not None:
        data = _gsheet_load(ws)
        if data:
            return data
        # GSheets 읽기 결과가 비어 있으면 CSV fallback
    # CSV fallback
    df = _load_csv_df()
    if df.empty:
        return {}
    return {
        row["article_id"]: row.to_dict()
        for _, row in df.iterrows()
        if row.get("article_id", "")
    }


def save_review(review_data: dict) -> tuple[bool, str]:
    """검토 결과를 upsert 저장한다.

    저장 순서:
      1. Google Sheets (설정된 경우)
      2. CSV (항상 — GSheets 결과와 무관하게 로컬 백업)

    반환: (성공 여부, 오류 메시지 또는 빈 문자열)
    """
    article_id = review_data.get("article_id", "").strip()
    if not article_id:
        return False, "article_id가 없습니다."

    review_status = review_data.get("review_status", "검토 전")
    if review_status not in REVIEW_STATUSES:
        return False, f"유효하지 않은 검토 상태입니다: {review_status}"

    now_str  = datetime.now(_KST).strftime("%Y-%m-%d %H:%M:%S KST")
    row_data = {col: str(review_data.get(col, "")) for col in REVIEW_COLS}
    row_data["reviewed_at"] = now_str

    warnings = []
    gsheet_ok = False

    # 1차: Google Sheets
    ws = _get_ws()
    if ws is not None:
        gsheet_ok = _gsheet_upsert(ws, row_data)
        if not gsheet_ok:
            warnings.append("Google Sheets 저장 실패 — CSV에 백업 저장됨")

    # 2차: CSV (항상 기록)
    try:
        _upsert_csv(row_data)
    except Exception as exc:
        warnings.append(f"CSV 저장 실패: {type(exc).__name__}")
        if not gsheet_ok:
            return False, " / ".join(warnings)

    return True, " / ".join(warnings)


def delete_review(article_id: str) -> bool:
    """특정 기사의 검토 결과를 삭제한다."""
    deleted = False

    ws = _get_ws()
    if ws is not None:
        deleted = _gsheet_delete(ws, article_id) or deleted

    try:
        df = _load_csv_df()
        new_df = df[df["article_id"] != article_id]
        if len(new_df) < len(df):
            _save_csv_df(new_df)
            deleted = True
    except Exception:
        pass

    return deleted


def count_by_review_status(reviews: dict) -> dict:
    """저장된 검토 결과 기준 상태별 건수를 반환한다."""
    counts: dict = {}
    for rv in reviews.values():
        st = rv.get("review_status", "검토 전") or "검토 전"
        counts[st] = counts.get(st, 0) + 1
    return counts
