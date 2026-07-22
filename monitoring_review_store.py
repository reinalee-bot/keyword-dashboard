"""
7단계: 모니터링 기사 검토 결과 저장·조회 모듈
저장소: data/monitoring_reviews.csv (로컬 영구 저장, upsert 방식)
Streamlit 의존 없음 — 단위 테스트 가능.
"""
import hashlib
import os
from datetime import datetime, timezone, timedelta

import pandas as pd

BASE_DIR    = os.path.dirname(__file__)
REVIEWS_CSV = os.path.join(BASE_DIR, "data", "monitoring_reviews.csv")

REVIEW_COLS = [
    "article_id", "title", "url", "media", "published_at",
    "category", "monitoring_priority", "relevance_score",
    "news_importance_score", "pr_usability_score",
    "selection_reason", "pr_suggestion",
    "review_status", "usage_type", "follow_up_required",
    "reviewer_memo", "reviewed_at",
]

REVIEW_STATUSES = ["검토 전", "관심 기사", "PR 후보", "제외"]
USAGE_TYPES     = ["기획기사", "보도자료", "인터뷰", "온드미디어", "내부 브리핑", "추가 검토"]

_KST = timezone(timedelta(hours=9))


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


def _load_df() -> pd.DataFrame:
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


def load_reviews() -> dict:
    """저장된 검토 결과를 {article_id: review_dict} 형태로 반환한다."""
    df = _load_df()
    if df.empty:
        return {}
    return {
        row["article_id"]: row.to_dict()
        for _, row in df.iterrows()
        if row.get("article_id", "")
    }


def save_review(review_data: dict) -> tuple[bool, str]:
    """검토 결과를 upsert 저장한다.
    반환: (성공 여부, 오류 메시지 또는 빈 문자열)
    """
    article_id = review_data.get("article_id", "").strip()
    if not article_id:
        return False, "article_id가 없습니다."

    review_status = review_data.get("review_status", "검토 전")
    if review_status not in REVIEW_STATUSES:
        return False, f"유효하지 않은 검토 상태입니다: {review_status}"

    try:
        df = _load_df()

        now_str = datetime.now(_KST).strftime("%Y-%m-%d %H:%M:%S KST")
        row_data = {col: str(review_data.get(col, "")) for col in REVIEW_COLS}
        row_data["reviewed_at"] = now_str

        new_row = pd.DataFrame([row_data])

        # 기존 동일 article_id 행 제거 후 새 행 추가 (upsert)
        df = df[df["article_id"] != article_id]
        df = pd.concat([df, new_row], ignore_index=True)

        os.makedirs(os.path.dirname(REVIEWS_CSV), exist_ok=True)
        df.to_csv(REVIEWS_CSV, index=False, encoding="utf-8-sig")
        return True, ""
    except Exception as e:
        return False, str(e)


def delete_review(article_id: str) -> bool:
    """특정 기사의 검토 결과를 삭제한다."""
    try:
        df = _load_df()
        df = df[df["article_id"] != article_id]
        df.to_csv(REVIEWS_CSV, index=False, encoding="utf-8-sig")
        return True
    except Exception:
        return False


def count_by_review_status(reviews: dict) -> dict:
    """저장된 검토 결과 기준 상태별 건수를 반환한다."""
    counts: dict = {}
    for rv in reviews.values():
        st = rv.get("review_status", "검토 전") or "검토 전"
        counts[st] = counts.get(st, 0) + 1
    return counts
