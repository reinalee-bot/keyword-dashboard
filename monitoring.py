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
    _is_risk_priority    : 긴급 리스크(urgent_incident) 여부
    _monitoring_category : 카테고리 (리스크/자사·관계사/경쟁사/…)
    _monitoring_reason   : PR 담당자 안내 자연어 문장
"""

import os
import re
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

# 카테고리 다양성 제한 없는 카테고리 (리스크 제외)
_UNLIMITED_CATS = {"자사·관계사", "경쟁사"}

# 리스크 카테고리 최대 선정 수
_MAX_RISK_COUNT = 5


# ══════════════════════════════════════════════════════════════
# 리스크 세분류
# ══════════════════════════════════════════════════════════════

_NON_INCIDENT_ARTICLE_TYPES = frozenset({"보도자료형", "행사·현장"})

_NON_INCIDENT_SIGNALS = [
    "미리보기", "isec", "코드게이트", "해킹 대회", "해킹 대결", "경진대회",
    "컨퍼런스", "전시회", "세미나", "포럼", "인간 vs ai", "ai vs 인간",
    "파트너십", "맞손", "mou 체결", "업무협약 체결",
    "정식 출시", "베타 출시", "제품 출시", "솔루션 출시",
    "지원사업", "공급기업 선정", "사업 선정", "지원 사업 참여",
    "보안 지원", "보안 공급", "정보보호 지원",
    "규제 강화", "ai 규제", "정책 발표",
    "취약점 대응", "취약점 예방", "악용 전 대응",
    "방어 전략", "예방 전략", "보안 전망", "트렌드 분석",
    "ctem", "aem으로",
]

_INCIDENT_SIGNALS = [
    "데이터 유출", "정보 유출", "개인정보 유출",
    "인증정보 털", "계정 탈취", "비밀번호 유출", "데이터·인증정보",
    "랜섬웨어 감염", "랜섬웨어 피해", "랜섬웨어에 감염",
    "침해 사고", "해킹 사고", "사이버 침해",
    "사이버 공격 피해", "공격 피해", "보안 사고",
    "서비스 장애 발생", "시스템 침해",
    "제로데이 공격", "제로데이 악용", "제로데이 연쇄",
    "실제 악용", "루트 권한 탈",
    "보안키 교체 권고", "긴급 패치",
]


def _classify_monitoring_risk(article: dict) -> str:
    """
    리스크 기사를 세분류한다.
    Returns: "urgent_incident" | "security_trend" | "not_risk"
    """
    if article.get("_relevance_type", "") != "리스크":
        return "not_risk"
    atype = article.get("article_type", "")
    if atype in _NON_INCIDENT_ARTICLE_TYPES:
        return "not_risk"
    text = (article.get("title", "") + " " + article.get("description", "")).lower()
    for sig in _NON_INCIDENT_SIGNALS:
        if sig in text:
            return "not_risk"
    for sig in _INCIDENT_SIGNALS:
        if sig in text:
            return "urgent_incident"
    return "security_trend"


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
# 2차 이벤트 클러스터링 (동일 보도자료/사건 감지)
# ══════════════════════════════════════════════════════════════

_KR_PARTICLES = sorted(
    ["에서", "으로", "에게", "부터", "까지", "에도", "에만",
     "을", "를", "이", "가", "은", "는", "의", "에", "서", "로", "와", "과", "도", "만"],
    key=len, reverse=True,
)

_SYNONYM_MAP = (
    ({"스트라이커", "스트레이커"}, "스트라이커"),
    ({"파트너십", "협력", "맞손"}, "파트너협력"),
    ({"지원사업", "공급기업"}, "지원선정"),
    ({"호남", "호남권", "호남서"}, "호남지역"),
    ({"선정", "참여"}, "참여선정"),
)

_TITLE_STOP = frozenset({
    "및", "와", "이", "가", "을", "를", "은", "는", "으로", "로", "의", "에", "에서",
    "한", "하는", "하고", "하여", "위해", "통해", "대해", "대한", "관련", "관한",
    "통한", "있는", "있어", "있다", "됩니다", "됩", "했", "했다", "한다", "된",
    "기업", "시장", "서비스", "제공", "시스템", "솔루션", "플랫폼", "사업",
    "국내", "기반", "분야", "위한", "대한", "등의", "부터",
})


def _strip_kr_particles(word: str) -> str:
    """단어 끝의 한국어 조사를 제거한다."""
    for p in _KR_PARTICLES:
        if word.endswith(p) and len(word) > len(p) + 1:
            return word[:-len(p)]
    return word


def _normalize_synonyms(word: str) -> str:
    """동의어를 표준 형태로 정규화한다."""
    for syn_set, canonical in _SYNONYM_MAP:
        if word in syn_set:
            return canonical
    return word


def _event_tokens(title: str) -> frozenset:
    """제목에서 의미 있는 이벤트 토큰 집합을 추출한다."""
    words = re.split(r"[\s,·\-·]+", title)
    tokens = set()
    for w in words:
        w = w.strip("'\"()[].,!?「」『』")
        if not w:
            continue
        stripped    = _strip_kr_particles(w)
        normalized  = _normalize_synonyms(stripped)
        if normalized not in _TITLE_STOP and len(normalized) >= 2:
            tokens.add(normalized)
    return frozenset(tokens)


def _same_monitoring_event(a: dict, b: dict) -> bool:
    """두 기사가 같은 사건/보도의 다른 제목 기사인지 판단한다."""
    dt_a = a.get("_dt")
    dt_b = b.get("_dt")
    if dt_a and dt_b:
        if abs((dt_a - dt_b).total_seconds()) > 72 * 3600:
            return False
    tok_a  = _event_tokens(a.get("title", ""))
    tok_b  = _event_tokens(b.get("title", ""))
    common = tok_a & tok_b
    if not common:
        return False
    entity_shared = any(len(t) >= 3 for t in common)
    if not entity_shared:
        return False
    union   = tok_a | tok_b
    jaccard = len(common) / len(union) if union else 0
    return len(common) >= 3 and (jaccard >= 0.25 or len(common) >= 4)


def _merge_monitoring_event_clusters(articles: list) -> list:
    """
    _same_monitoring_event()로 감지된 동일 사건 기사들을 클러스터로 묶어
    _monitoring_priority가 가장 높은 대표 1건만 남긴다.
    _matched_queries / _matched_groups는 클러스터 전체를 병합한다.
    """
    used   = [False] * len(articles)
    result = []

    for i, art in enumerate(articles):
        if used[i]:
            continue
        cluster = [art]
        for j in range(i + 1, len(articles)):
            if not used[j] and _same_monitoring_event(art, articles[j]):
                cluster.append(articles[j])
                used[j] = True
        used[i] = True

        if len(cluster) == 1:
            result.append(art)
            continue

        rep = max(cluster, key=lambda a: a.get("_monitoring_priority", 0))
        for member in cluster:
            if member is rep:
                continue
            for mq in member.get("_matched_queries", []):
                if mq not in rep.setdefault("_matched_queries", []):
                    rep["_matched_queries"].append(mq)
            for mg in member.get("_matched_groups", []):
                if mg not in rep.setdefault("_matched_groups", []):
                    rep["_matched_groups"].append(mg)
        result.append(rep)

    return result


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
        risk_class = _classify_monitoring_risk(article)
        if risk_class in ("urgent_incident", "security_trend"):
            return "리스크"
        # not_risk → 다른 카테고리로 낙하

    if rtype == "자사·관계사" or "company" in groups:
        if any(e.lower() in text for e in _COMPANY_ENTITIES):
            return "자사·관계사"

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


def _is_promotional_article(article: dict) -> bool:
    """홍보성 기사(보도자료·출시·협약) 여부."""
    if article.get("article_type", "") == "보도자료형":
        return True
    text = (article.get("title", "") + " " + article.get("description", "")).lower()
    signals = [
        "정식 출시", "베타 출시", "제품 출시", "솔루션 출시",
        "파트너십 체결", "mou 체결", "업무협약 체결", "맞손",
        "론칭", "출시 발표",
    ]
    return any(s in text for s in signals)


def _is_vendor_mention_only(article: dict) -> bool:
    """벤더 그룹에서만 수집된 기사 (자사 직접 언급 없음)."""
    groups = set(article.get("_matched_groups", []))
    if groups != {"vendor"}:
        return False
    text = (article.get("title", "") + " " + article.get("description", "")).lower()
    return not any(e.lower() in text for e in _COMPANY_ENTITIES)


def _is_local_support_program(article: dict) -> bool:
    """지역 지원사업·선정 기사 여부."""
    text = (article.get("title", "") + " " + article.get("description", "")).lower()
    support_signals = [
        "지원사업", "공급기업 선정", "사업 선정", "지원 사업 참여",
        "보안 지원", "정보보호 지원", "보안 공급",
    ]
    region_signals = [
        "호남", "충청", "경북", "경남", "전북", "전남", "강원", "제주",
        "광역", "지자체", "지역",
    ]
    if any(s in text for s in support_signals):
        return True
    if any(r in text for r in region_signals) and any(
        s in text for s in ["지원", "선정", "사업"]
    ):
        return True
    return False


def _calc_pr_value_score(article: dict, category: str) -> int:
    """PR 활용도 점수 0-100을 반환한다."""
    rlevel  = article.get("_relevance_level", "낮음")
    atype   = article.get("article_type", "일반 기사")
    tier    = article.get("_media_tier", 4)
    queries = set(article.get("_matched_queries", []))

    if category == "자사·관계사":
        base = 90 if rlevel != "낮음" else 60
    elif category == "리스크":
        base = 80 if rlevel != "낮음" else 55
    elif category == "경쟁사":
        base = 75 if rlevel != "낮음" else 45
    elif category == "기획기사 후보":
        base = 70 if tier <= 2 else 60
    elif category == "AI·AX 시장동향":
        base = {"높음": 70, "보통": 55}.get(rlevel, 25)
    elif category == "클라우드·보안":
        risk_queries = {
            "cloud_security/소프트웨어 라이선스",
            "cloud_security/사이버 공격 기업",
            "cloud_security/클라우드 보안",
        }
        b = 65 if (queries & risk_queries) else 50
        base = max(b - 25, 20) if rlevel == "낮음" else b
    elif category == "주요 벤더":
        base = {"높음": 60, "보통": 40}.get(rlevel, 20)
    else:
        if atype == "기획·분석":
            base = 45
        else:
            base = {"높음": 40, "보통": 30}.get(rlevel, 15)

    # PR 점수 상한 (홍보성·지역지원·벤더전용 기사)
    cap = 100
    if _is_promotional_article(article):
        cap = min(cap, 35)
    if _is_vendor_mention_only(article):
        cap = min(cap, 25)
    if _is_local_support_program(article):
        cap = min(cap, 25)
    return min(base, cap)


def _make_reason(article: dict, category: str, risk_class: str = "") -> str:
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
        if risk_class == "urgent_incident":
            return f"긴급 리스크 기사 — {hint}"
        elif risk_class == "security_trend":
            return f"보안 트렌드 기사 — {hint}"
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
    rscore     = article.get("_relevance_score", 0)
    buzz       = article.get("score", 0)

    category   = _determine_category(article)
    risk_class = _classify_monitoring_risk(article)
    pr_score   = _calc_pr_value_score(article, category)
    is_risk    = (risk_class == "urgent_incident")
    priority   = max(0, min(100, round(rscore * 0.45 + buzz * 0.30 + pr_score * 0.25)))
    reason     = _make_reason(article, category, risk_class)

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

    - target_count: 목표 선정 수 (자사·관계사, 경쟁사, 긴급리스크는 초과 가능)
    - max_count   : 절대 최대 반환 수
    """
    if not articles:
        return []

    if media_config is None:
        media_config = load_media_config()

    # ── 1차 클러스터링 (제목 유사도) ─────────────────────────────
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

    # ── 2차 클러스터링 (동일 이벤트 감지) ────────────────────────
    scored = _merge_monitoring_event_clusters(scored)

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

    # ── 정렬: 긴급 리스크 우선 → 우선순위 내림차순 → 날짜 내림차순 ─
    def _sort_key(a):
        risk_first = 0 if a.get("_is_risk_priority") else 1
        dt = a.get("_dt") or datetime.min.replace(tzinfo=timezone.utc)
        return (risk_first, -a.get("_monitoring_priority", 0), -dt.timestamp())

    eligible.sort(key=_sort_key)

    # ── 다양성 규칙 + target_count 적용 ──────────────────────────
    vendor_count   = {}
    media_count    = {}
    category_count = {}
    selected       = []

    for art in eligible:
        cat    = art.get("_monitoring_category", "기타")
        media  = art.get("media_name", "")
        vendor = _get_vendor_name(art)

        # 목표 수 도달 후에도 must-include 카테고리는 계속 추가
        risk_count = category_count.get("리스크", 0)
        is_must = (
            cat in _UNLIMITED_CATS
            or (cat == "리스크" and risk_count < _MAX_RISK_COUNT)
        )
        if len(selected) >= target_count and not is_must:
            continue

        # 리스크 카테고리 상한
        if cat == "리스크" and risk_count >= _MAX_RISK_COUNT:
            continue

        # 일반 카테고리 상한 (리스크·무제한 카테고리 제외)
        if cat not in {"리스크"} | _UNLIMITED_CATS and category_count.get(cat, 0) >= 5:
            continue

        # 매체·벤더 다양성
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
