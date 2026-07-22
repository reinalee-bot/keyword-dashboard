"""
Tab4 PR 모니터링 섹션의 순수 헬퍼 함수 (Streamlit 의존 없음)

테스트 가능한 로직을 dashboard.py에서 분리한 모듈.
"""
import hashlib
import os
from datetime import datetime, timezone, timedelta


def today_kst() -> str:
    """Asia/Seoul 기준 오늘 날짜 YYYY-MM-DD"""
    kst = timezone(timedelta(hours=9))
    return datetime.now(kst).strftime("%Y-%m-%d")


def monitoring_config_version(config_path: str) -> str:
    """monitoring_queries.yaml 내용 해시 (8자) — 설정 변경 시 캐시 갱신."""
    try:
        with open(config_path, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()[:8]
    except Exception:
        return "default"


def apply_category_filter(articles: list, category: str) -> list:
    """
    기사 목록에 카테고리 필터를 적용해 (전체순위, 기사) 튜플 목록을 반환한다.
    필터를 적용해도 전체 순위(1-based)는 유지된다.
    """
    ranked = [(i + 1, art) for i, art in enumerate(articles)]
    if category == "전체":
        return ranked
    return [(rank, art) for rank, art in ranked
            if art.get("_monitoring_category", "기타") == category]


def count_by_category(articles: list) -> dict:
    """카테고리별 기사 수를 반환한다 (0건 카테고리는 포함하지 않음)."""
    counts: dict = {}
    for art in articles:
        cat = art.get("_monitoring_category", "기타")
        counts[cat] = counts.get(cat, 0) + 1
    return counts


def make_widget_key(prefix: str, url: str) -> str:
    """
    Streamlit 위젯 고유 key 생성.
    prefix로 자동 모니터링('monitoring_util')과 직접 검색('manual_util')을 구분한다.
    """
    return f"{prefix}_{hashlib.md5(url.encode()).hexdigest()[:12]}"


def apply_urgency_filter(ranked: list, risk_only: bool = False) -> list:
    """
    긴급 리스크 필터를 적용한다.
    risk_only=True이면 _is_risk_priority=True인 기사만 반환한다.
    """
    if not risk_only:
        return ranked
    return [(rank, art) for rank, art in ranked
            if art.get("_is_risk_priority", False)]


def apply_review_filter(ranked: list, review_filter: str, reviews: dict) -> list:
    """
    검토 상태 필터를 적용한다.
    - '전체': 변경 없음
    - '검토 전': reviews에 없거나 review_status == '검토 전'인 기사
    - 그 외: reviews의 review_status가 해당 상태인 기사
    """
    if review_filter == "전체":
        return ranked
    from monitoring_review_store import make_article_id
    result = []
    for rank, art in ranked:
        aid = make_article_id(
            art.get("url", ""), art.get("title", ""),
            art.get("media_name", ""), art.get("pub_date", ""))
        rv = reviews.get(aid, {})
        status = rv.get("review_status", "검토 전") or "검토 전"
        if status == review_filter:
            result.append((rank, art))
    return result


def count_review_summary(articles: list, reviews: dict) -> dict:
    """
    전체 선정 기사 기준 검토 현황을 집계한다.
    반환: {"전체": N, "검토완료": N, "관심 기사": N, "PR 후보": N, "제외": N, "검토 전": N}
    """
    from monitoring_review_store import make_article_id
    total = len(articles)
    sub: dict = {"관심 기사": 0, "PR 후보": 0, "제외": 0, "검토 전": 0}
    for art in articles:
        aid = make_article_id(
            art.get("url", ""), art.get("title", ""),
            art.get("media_name", ""), art.get("pub_date", ""))
        rv = reviews.get(aid, {})
        status = rv.get("review_status", "검토 전") or "검토 전"
        if status in sub:
            sub[status] += 1
        else:
            sub["검토 전"] += 1
    reviewed = sub["관심 기사"] + sub["PR 후보"] + sub["제외"]
    return {"전체": total, "검토완료": reviewed, **sub}


def sort_monitoring_articles(ranked: list, sort_by: str = "우선순위순") -> list:
    """
    정렬 기준에 따라 기사 목록을 재정렬한다.
    - '우선순위순': monitoring.py 선정 순서(rank) 유지
    - 'PR 활용도순': _pr_value_score 내림차순
    """
    if sort_by == "PR 활용도순":
        return sorted(ranked, key=lambda x: x[1].get("_pr_value_score", 0), reverse=True)
    return sorted(ranked, key=lambda x: x[0])
