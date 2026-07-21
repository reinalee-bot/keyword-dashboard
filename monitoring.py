"""
SCK 자동 모니터링 후보 수집 모듈

fetch_daily_monitoring_candidates()로 config/monitoring_queries.yaml의
모든 활성 검색어를 순회해 기사를 수집·통합·중복제거한다.

추가 필드:
    _monitoring_group : 최초 수집 그룹명
    _source_query     : 최초 수집 검색어
    _matched_queries  : 이 기사를 포함한 모든 "group/query" 문자열 목록
"""

import os
from functools import lru_cache

import yaml

from news_fetcher import _title_similarity, fetch_articles_for_keyword, load_media_config

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config", "monitoring_queries.yaml")


@lru_cache(maxsize=1)
def _load_monitoring_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_active_queries(cfg=None):
    """
    설정에서 enabled 그룹·쿼리만 추출.
    반환: [{"group": str, "query": str}, ...]
    """
    if cfg is None:
        cfg = _load_monitoring_config()
    result = []
    for group_name, group_cfg in cfg.get("groups", {}).items():
        if not group_cfg.get("enabled", True):
            continue
        for q in group_cfg.get("queries", []):
            if q.get("enabled", True):
                result.append({"group": group_name, "query": q["text"]})
    return result


def fetch_daily_monitoring_candidates(
    start_datetime,
    end_datetime,
    display_per_query=30,
    *,
    cid="",
    csc="",
    media_config=None,
    _cfg=None,
):
    """
    monitoring_queries.yaml의 모든 활성 검색어에 대해
    fetch_articles_for_keyword()를 호출하고 결과를 통합·중복제거해 반환한다.

    기존 relevance 필드는 그대로 유지된다.
    동일 기사가 여러 검색어에서 발견되면 대표 1건의 _matched_queries에 합쳐진다.
    """
    if media_config is None:
        media_config = load_media_config()

    cfg    = _cfg if _cfg is not None else _load_monitoring_config()
    active = load_active_queries(cfg)

    date_from = (start_datetime.strftime("%Y-%m-%d")
                 if hasattr(start_datetime, "strftime") else str(start_datetime)[:10])
    date_to   = (end_datetime.strftime("%Y-%m-%d")
                 if hasattr(end_datetime, "strftime") else str(end_datetime)[:10])

    # ── 검색어별 수집 ─────────────────────────────────────────
    all_articles = []
    for item in active:
        res = fetch_articles_for_keyword(
            keyword=item["query"],
            date_from=date_from,
            date_to=date_to,
            sort_api="date",
            media_scope="all",
            article_type_filter="",
            cid=cid,
            csc=csc,
            media_config=media_config,
            display=display_per_query,
        )
        for art in res.get("articles", []):
            art["_monitoring_group"] = item["group"]
            art["_source_query"]     = item["query"]
            art["_matched_queries"]  = [f"{item['group']}/{item['query']}"]
            all_articles.append(art)

    # ── URL 중복 제거 및 _matched_queries 병합 ─────────────────
    url_index = {}
    for art in all_articles:
        url = art.get("url", "")
        if url in url_index:
            existing = url_index[url]
            for mq in art["_matched_queries"]:
                if mq not in existing["_matched_queries"]:
                    existing["_matched_queries"].append(mq)
        else:
            url_index[url] = art

    deduped = list(url_index.values())

    # ── 제목 유사 중복 제거 및 _matched_queries 병합 ──────────
    unique      = []
    title_pool  = []
    for art in deduped:
        title   = art.get("title", "")
        dup_idx = next(
            (i for i, t in enumerate(title_pool)
             if _title_similarity(title, t) >= 0.90),
            None,
        )
        if dup_idx is not None:
            for mq in art["_matched_queries"]:
                if mq not in unique[dup_idx]["_matched_queries"]:
                    unique[dup_idx]["_matched_queries"].append(mq)
        else:
            title_pool.append(title)
            unique.append(art)

    return unique
