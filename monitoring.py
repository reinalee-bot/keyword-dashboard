"""
SCK 자동 모니터링 후보 수집·순위 계산 모듈

1단계: fetch_daily_monitoring_candidates()
    config/monitoring_queries.yaml 의 모든 활성 검색어를 순회해
    기사를 수집·통합·중복제거한다.

2단계: select_daily_monitoring_articles()
    1단계 후보에 클러스터링·화제성·PR 점수를 적용해 최종 목록을 반환한다.

추가 필드 (1단계):
    _monitoring_group   : 최초 수집 그룹명
    _source_query       : 최초 수집 검색어
    _matched_queries    : 이 기사를 포함한 모든 "group/query" 문자열 목록
    _matched_groups     : 이 기사를 포함한 그룹명 목록

추가 필드 (2단계):
    score                : 화제성 점수 (calculate_article_score)
    _pr_value_score      : PR 활용도 점수 0-100
    _monitoring_priority : 모니터링 우선순위 0-100
    _is_risk_priority    : 리스크 우선 정렬 여부
    _monitoring_category : 카테고리 (리스크/자사·관계사/경쟁사/…)
    _monitoring_reason   : PR 담당자 안내 자연어 문장
"""

import os
from datetime import datetime, timezone
from functools import lru_cache

import yaml

from news_fetcher import (
    _title_similarity,
    calculate_article_score,
    cluster_articles,
    fetch_articles_for_keyword,
    load_media_config,
)

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config", "monitoring_queries.yaml")

# 자사 엔티티 목록 (제목/설명 직접 언급 확인용)
_COMPANY_ENTITIES  = ["SCK", "에쓰씨케이", "SCK Corp", "STK", "SPK", "에쓰핀테크놀로지"]
_COMPETITOR_ENTITIES = ["디모아"]

# 벤더 정규화 맵 (소문자 키워드 → 표준명)
_VENDOR_MAP = {
    "microsoft": "Microsoft",
    "마이크로소프트": "Microsoft",
    "adobe": "Adobe",
    "어도비": "Adobe",
    "autodesk": "Autodesk",
    "오토데스크": "Autodesk",
}

# 카테고리 우선순위 (낮은 숫자 = 높은 우선순위)
_CATEGORY_ORDER = {
    "리스크": 0,
    "자사·관계사": 1,
    "경쟁사": 2,
    "기획기사 후보": 3,
    "AI·AX 시장동향": 4,
    "클라우드·보안": 5,
    "주요 벤더": 6,
    "기타": 7,
}

# 카테고리 다양성 제한 없는 카테고리
_UNLIMITED_CATS = {"리스크", "자사·관계사", "경쟁사"}


# ══════════════════════════════════════════════════════════════
# 설정 로드
# ══════════════════════════════════════════════════════════════

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


# ══════════════════════════════════════════════════════════════
# 1단계: 후보 수집
# ══════════════════════════════════════════════════════════════

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
    동일 기사가 여러 검색어에서 발견되면 대표 1건의
    _matched_queries / _matched_groups 에 합쳐진다.
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
            art["_matched_groups"]   = [item["group"]]
            all_articles.append(art)

    # ── URL 중복 제거 및 필드 병합 ────────────────────────────
    url_index = {}
    for art in all_articles:
        url = art.get("url", "")
        if url in url_index:
            existing = url_index[url]
            for mq in art["_matched_queries"]:
                if mq not in existing["_matched_queries"]:
                    existing["_matched_queries"].append(mq)
            for mg in art["_matched_groups"]:
                if mg not in existing["_matched_groups"]:
                    existing["_matched_groups"].append(mg)
        else:
            url_index[url] = art

    deduped = list(url_index.values())

    # ── 제목 유사 중복 제거 및 필드 병합 ─────────────────────
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
            rep = unique[dup_idx]
            for mq in art["_matched_queries"]:
                if mq not in rep["_matched_queries"]:
                    rep["_matched_queries"].append(mq)
            for mg in art["_matched_groups"]:
                if mg not in rep["_matched_groups"]:
                    rep["_matched_groups"].append(mg)
        else:
            title_pool.append(title)
            unique.append(art)

    return unique


# ══════════════════════════════════════════════════════════════
# 2단계: 점수 계산·선정
# ══════════════════════════════════════════════════════════════

def _get_vendor_name(article: dict):
    """vendor group 기사에서 표준 벤더명을 반환한다. 없으면 None."""
    if "vendor" not in article.get("_matched_groups", []):
        return None
    for q in article.get("_matched_queries", []):
        if q.startswith("vendor/"):
            kw = q.split("/", 1)[1].lower()
            for key, name in _VENDOR_MAP.items():
                if key in kw or kw in key:
                    return name
    return None


def _determine_category(article: dict) -> str:
    """카테고리 우선순위 사다리에 따라 _monitoring_category를 결정한다."""
    rtype  = article.get("_relevance_type", "일반")
    rlevel = article.get("_relevance_level", "낮음")
    atype  = article.get("article_type", "일반 기사")
    groups = set(article.get("_matched_groups", []))
    text   = (article.get("title", "") + " " + article.get("description", "")).lower()

    if rtype == "리스크":
        return "리스크"

    if rtype == "자사·관계사" or "company" in groups:
        if any(e.lower() in text for e in _COMPANY_ENTITIES):
            return "자사·관계사"
        # 검색어 매치만으로는 자사·관계사 인정 안 함

    if rtype == "경쟁사" or "competitor" in groups:
        if any(e.lower() in text for e in _COMPETITOR_ENTITIES):
            return "경쟁사"

    if atype == "기획·분석" and rlevel in {"높음", "보통"}:
        return "기획기사 후보"

    if "ai_ax" in groups:
        return "AI·AX 시장동향"

    if "cloud_security" in groups:
        return "클라우드·보안"

    if "vendor" in groups:
        return "주요 벤더"

    return "기타"


def _calc_pr_value_score(article: dict, category: str) -> int:
    """PR 활용도 점수 0-100을 반환한다."""
    rlevel  = article.get("_relevance_level", "낮음")
    atype   = article.get("article_type", "일반 기사")
    tier    = article.get("_media_tier", 4)
    queries = set(article.get("_matched_queries", []))

    if category == "자사·관계사":
        return 90 if rlevel != "낮음" else 60

    if category == "리스크":
        return 80 if rlevel != "낮음" else 55

    if category == "경쟁사":
        return 75 if rlevel != "낮음" else 45

    if category == "기획기사 후보":
        return 70 if tier <= 2 else 60

    if category == "AI·AX 시장동향":
        return {"높음": 70, "보통": 55}.get(rlevel, 25)

    if category == "클라우드·보안":
        risk_queries = {
            "cloud_security/소프트웨어 라이선스",
            "cloud_security/사이버 공격 기업",
            "cloud_security/클라우드 보안",
        }
        base = 65 if (queries & risk_queries) else 50
        return max(base - 25, 20) if rlevel == "낮음" else base

    if category == "주요 벤더":
        return {"높음": 60, "보통": 40}.get(rlevel, 20)

    # 기타
    if atype == "기획·분석":
        return 45
    return {"높음": 40, "보통": 30}.get(rlevel, 15)


def _make_reason(article: dict, category: str) -> str:
    """PR 담당자용 모니터링 이유 자연어 문장을 반환한다."""
    rlevel = article.get("_relevance_level", "낮음")
    media  = article.get("media_name", "")

    if category == "자사·관계사":
        if rlevel == "낮음":
            return "자사 관련 언급 포함 (관련성 낮음, 모니터링 참고용)"
        return "SCK·관계사 관련 기사 — PR 팀 직접 확인 필요"

    if category == "리스크":
        reasons = article.get("_relevance_reasons", [])
        hint = reasons[0] if reasons else "보안·리스크 키워드 감지"
        return f"기업 IT 리스크 기사 — {hint}"

    if category == "경쟁사":
        return "경쟁사(디모아) 동향 기사 — 시장 포지셔닝 참고"

    if category == "기획기사 후보":
        return f"{media} 기획·분석 기사 — PR 활용 가능성 높음"

    if category == "AI·AX 시장동향":
        matched = [q.split("/", 1)[1] for q in article.get("_matched_queries", [])
                   if q.startswith("ai_ax/")]
        hint = matched[0] if matched else "AI·AX 시장"
        return f"기업 {hint} 시장 동향 기사"

    if category == "클라우드·보안":
        matched = [q.split("/", 1)[1] for q in article.get("_matched_queries", [])
                   if q.startswith("cloud_security/")]
        hint = matched[0] if matched else "클라우드·보안"
        return f"{hint} 관련 기업 영향 기사"

    if category == "주요 벤더":
        matched = [q.split("/", 1)[1] for q in article.get("_matched_queries", [])
                   if q.startswith("vendor/")]
        vendor = matched[0] if matched else "주요 벤더"
        if rlevel == "높음":
            return f"{vendor} 정책·변화로 기업 고객 영향 가능"
        return f"{vendor} 관련 시장 동향"

    return f"관련성 {rlevel} 기사 — 참고용"


def score_monitoring_candidate(article: dict) -> dict:
    """
    기사에 PR 모니터링 점수·분류 필드를 추가한다.
    _relevance_score / _relevance_level 등 기존 필드는 변경하지 않는다.
    article["score"] (화제성)는 이미 설정돼 있어야 한다.
    반환: 동일 article dict (in-place 수정 + 반환)
    """
    rscore = article.get("_relevance_score", 0)
    buzz   = article.get("score", 0)

    category = _determine_category(article)
    pr_score = _calc_pr_value_score(article, category)
    is_risk  = (article.get("_relevance_type", "") == "리스크")
    priority = max(0, min(100, round(rscore * 0.45 + buzz * 0.30 + pr_score * 0.25)))
    reason   = _make_reason(article, category)

    article["_pr_value_score"]      = pr_score
    article["_monitoring_priority"] = priority
    article["_is_risk_priority"]    = is_risk
    article["_monitoring_category"] = category
    article["_monitoring_reason"]   = reason
    return article


def select_daily_monitoring_articles(
    articles: list,
    target_count: int = 15,
    max_count: int = 20,
    *,
    media_config=None,
) -> list:
    """
    1단계 후보에 클러스터링·화제성·PR 점수를 적용해 최종 PR 모니터링 목록을 반환한다.

    - target_count: 목표 선정 수 (부족해도 낮음 기사로 채우지 않는다)
    - max_count   : 절대 최대 반환 수
    """
    if not articles:
        return []

    if media_config is None:
        media_config = load_media_config()

    # ── 클러스터링 ───────────────────────────────────────────
    clusters = cluster_articles(articles, threshold=0.75)

    # ── 화제성 점수 계산 + 클러스터 멤버 필드 병합 ──────────
    scored = []
    for cl in clusters:
        rep  = cl["rep"]
        size = cl["size"]

        for member in cl["cluster"]:
            if member is rep:
                continue
            for mq in member.get("_matched_queries", []):
                if mq not in rep.setdefault("_matched_queries", []):
                    rep["_matched_queries"].append(mq)
            for mg in member.get("_matched_groups", []):
                if mg not in rep.setdefault("_matched_groups", []):
                    rep["_matched_groups"].append(mg)

        rep["score"] = calculate_article_score(rep, size, media_config)
        scored.append(rep)

    # ── PR 점수·카테고리·이유 계산 ────────────────────────────
    for art in scored:
        score_monitoring_candidate(art)

    # ── 선정 대상 필터링 ─────────────────────────────────────
    eligible = []
    for art in scored:
        level   = art.get("_relevance_level", "낮음")
        cat     = art.get("_monitoring_category", "기타")
        is_risk = art.get("_is_risk_priority", False)

        if level in {"높음", "보통"}:
            eligible.append(art)
        elif is_risk:
            art["_monitoring_reason"] += " (관련성 낮음이나 리스크 기사로 예외 포함)"
            eligible.append(art)
        elif cat == "자사·관계사":
            art["_monitoring_reason"] += " (관련성 낮음이나 자사 언급으로 예외 포함)"
            eligible.append(art)

    # ── 정렬: 리스크 우선 → 우선순위 내림차순 → 날짜 내림차순 ─
    def _sort_key(a):
        risk_first = 0 if a.get("_is_risk_priority") else 1
        dt = a.get("_dt") or datetime.min.replace(tzinfo=timezone.utc)
        return (risk_first, -a.get("_monitoring_priority", 0), -dt.timestamp())

    eligible.sort(key=_sort_key)

    # ── 다양성 규칙 적용 ─────────────────────────────────────
    vendor_count   = {}
    media_count    = {}
    category_count = {}
    selected       = []

    for art in eligible:
        cat    = art.get("_monitoring_category", "기타")
        media  = art.get("media_name", "")
        vendor = _get_vendor_name(art)

        if cat not in _UNLIMITED_CATS and category_count.get(cat, 0) >= 5:
            continue
        if media_count.get(media, 0) >= 3:
            continue
        if vendor and vendor_count.get(vendor, 0) >= 3:
            continue

        selected.append(art)
        category_count[cat] = category_count.get(cat, 0) + 1
        media_count[media]  = media_count.get(media, 0) + 1
        if vendor:
            vendor_count[vendor] = vendor_count.get(vendor, 0) + 1

        if len(selected) >= max_count:
            break

    return selected
