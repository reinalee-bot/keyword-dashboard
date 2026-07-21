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
