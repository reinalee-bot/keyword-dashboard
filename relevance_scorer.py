"""
SCK 뉴스 관련성 판정 모듈 (v2)
config/relevance_config.yaml 의 설정을 읽어 기사 제목·설명에 점수를 부여한다.

반환 필드:
  _relevance_score       int  0-100
  _relevance_level       str  높음 / 보통 / 낮음
  _relevance_type        str  자사·관계사 / 경쟁사 / 벤더 / 시장동향 / 리스크 / 일반
  _relevance_reasons     list[str]  판정 근거 최대 3개
  _low_relevance_reason  str  감점 또는 낮은 관련성 사유
  _foreign_language      bool  True 이면 한글 비율 5% 미만의 외국어 기사
"""

import os
import re
from functools import lru_cache

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config", "relevance_config.yaml")

_FALLBACK = {
    "_relevance_score":    50,
    "_relevance_level":    "보통",
    "_relevance_type":     "일반",
    "_relevance_reasons":  [],
    "_low_relevance_reason": "",
    "_foreign_language":   False,
}

_KOREAN_RE = re.compile(r"[가-힣]")


@lru_cache(maxsize=1)
def _load_config() -> dict:
    import yaml
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _lower(lst) -> list:
    return [str(x).lower() for x in (lst or [])]


def _hits(text: str, terms: list) -> list:
    """text 안에서 발견된 terms 반환 (소문자 비교)."""
    return [t for t in terms if t in text]


def _is_foreign(text: str, threshold: float = 0.05) -> bool:
    """한글 비율이 threshold 미만이면 외국어 기사로 판단."""
    total = len(text.strip())
    if total == 0:
        return False
    korean_count = len(_KOREAN_RE.findall(text))
    return (korean_count / total) < threshold


def _check_ambiguous(term_key: str, text: str, cfg: dict) -> bool:
    """
    모호한 단어가 유효한 문맥에서 사용됐는지 확인.
    invalid_context 패턴 중 하나라도 있으면 False (무효).
    valid_context 패턴 중 하나라도 있으면 True (유효).
    둘 다 없으면 False (기본적으로 무효 처리 — 오탐 방지 우선).
    """
    ambig = cfg.get("ambiguous_terms", {})
    if term_key not in ambig:
        return True  # 설정 없으면 제한 없이 통과

    entry = ambig[term_key]
    invalid_list = [str(x).lower() for x in (entry.get("invalid_context") or [])]
    valid_list   = [str(x).lower() for x in (entry.get("valid_context")   or [])]

    # invalid_context 우선 확인
    for inv in invalid_list:
        if inv in text:
            return False

    # valid_context 중 하나라도 있어야 유효
    for vld in valid_list:
        if vld in text:
            return True

    return False


def _get_query_type(keyword: str, cfg: dict) -> str:
    """검색어의 query_types 분류 반환: broad_topic / vendor / competitor / unknown"""
    qt = cfg.get("query_types", {})
    kl = (keyword or "").lower().strip()
    for qtype, kws in qt.items():
        for kw in (kws or []):
            if str(kw).lower() == kl:
                return qtype
    return "unknown"


def _keyword_in_title(keyword: str, tl: str) -> bool:
    """query_keyword가 제목에 독립 단어로 있는지 확인 (TAX·MAX 등 부분 포함 방지)."""
    if not keyword:
        return False
    kl = re.escape(keyword.lower())
    return bool(re.search(r'(?<![a-zA-Z가-힣])' + kl + r'(?![a-zA-Z가-힣])', tl))


def _cosentence_check(tl: str, dl: str, topic_h: list, impact_h: list) -> bool:
    """
    impact가 제목에 있거나, 설명에서 topic과 같은 문장에 있는지 확인.
    broad_topic 쿼리에서 '동일 문장 문맥' 조건 검증용.
    """
    for imp in impact_h:
        if imp in tl:
            return True
    for sent in re.split(r"[.!?\n。…]", dl):
        sl = sent.strip()
        if any(t in sl for t in topic_h) and any(imp in sl for imp in impact_h):
            return True
    return False


# ─────────────────────────────────────────────────────────────
def score_relevance(title: str, description: str, query_keyword: str = None) -> dict:
    """
    기사 제목과 description 을 받아 SCK 관련성 점수 및 판정을 반환한다.
    query_keyword: 이 기사를 가져온 검색어 (분기 로직에 사용)
    설정 파일 로드에 실패하면 중립값(FALLBACK)을 반환한다.
    """
    try:
        cfg = _load_config()
    except Exception:
        return dict(_FALLBACK)

    tl = (title or "").lower()
    dl = (description or "").lower()
    cx = tl + " " + dl  # 제목+설명 합산 텍스트

    # ── 외국어 필터 ──────────────────────────────────────────
    is_foreign = _is_foreign(title + " " + (description or ""))
    if is_foreign:
        return {
            "_relevance_score":    10,
            "_relevance_level":    "낮음",
            "_relevance_type":     "일반",
            "_relevance_reasons":  [],
            "_low_relevance_reason": "외국어 기사 (한글 비율 5% 미만)",
            "_foreign_language":   True,
        }

    owned   = _lower(cfg.get("owned_entities", []))
    comps   = _lower(cfg.get("competitor_entities", []))
    vendors = _lower(cfg.get("vendor_entities", []))
    topics  = _lower(cfg.get("business_topics", []))
    impacts = _lower(cfg.get("enterprise_impact", []))
    risks   = _lower(cfg.get("risk_terms", []))
    promos  = _lower(cfg.get("promotional_terms", []))
    local_  = _lower(cfg.get("consumer_or_local_terms", []))

    # 검색어 타입 결정
    q_type = _get_query_type(query_keyword, cfg)

    score   = 0
    reasons: list = []
    deducts: list = []

    # ── 1. 자사·관계사 직접 언급 ─────────────────────────────
    own_h = _hits(cx, owned)
    if own_h:
        score = 90
        reasons.append(f"자사/관계사 직접 언급: {own_h[0]}")

    # ── 2. 경쟁사 ────────────────────────────────────────────
    comp_t = _hits(tl, comps)
    comp_d = _hits(dl, comps)
    comp_score = 0

    if comp_t:
        # 제목에서 경쟁사가 주체인지 확인 (제목 앞 절반에 위치)
        mid = len(tl) // 2
        is_subject = any(tl.find(c) <= mid for c in comp_t)
        if is_subject:
            comp_score = 80
            reasons.append(f"경쟁사 주요 주체 ({comp_t[0]})")
        else:
            # 제목 뒤쪽 단순 언급
            comp_score = 45
            reasons.append(f"경쟁사 언급 ({comp_t[0]})")
    elif len(comp_d) >= 2:
        comp_score = 55
        reasons.append(f"경쟁사 보도 내 주요 언급 ({comp_d[0]})")
    elif comp_d:
        # competitor 쿼리: 단순 등장은 낮음
        comp_score = 25 if q_type == "competitor" else 35
        reasons.append(f"경쟁사 단순 등장 ({comp_d[0]})")

    if comp_score > score:
        score = comp_score

    # ── 3. 벤더 + 맥락 ───────────────────────────────────────
    vendor_h = _hits(cx, vendors)
    impact_h = _hits(cx, impacts)
    promo_h  = _hits(cx, promos)

    # vendor 쿼리: 벤더가 제목 주체일 때만 높음 허용
    vendor_is_title_subject = vendor_h and any(
        tl.find(v) != -1 and tl.find(v) <= len(tl) // 2 for v in vendor_h
    )

    # 모호한 단어(예산/규제/비용/비용 절감)를 valid_context로 검증
    _AMBIG_MAP = {"예산": "예산", "규제": "규제", "비용": "비용", "비용 절감": "비용"}

    def _filter_impacts(imp_list: list) -> list:
        result = []
        for imp in imp_list:
            if imp in _AMBIG_MAP:
                if _check_ambiguous(_AMBIG_MAP[imp], cx, cfg):
                    result.append(imp)
            else:
                result.append(imp)
        return result

    if vendor_h:
        # impact 단어 문맥 검증: 모호한 단어 필터링
        valid_impacts = _filter_impacts(impact_h)

        if valid_impacts:
            if q_type == "vendor" and not vendor_is_title_subject:
                # vendor 쿼리인데 벤더가 타 기사 내 단순 언급 → 점수 제한(낮음)
                v_score = min(30, 20 + len(valid_impacts) * 5)
                reasons.append(
                    f"벤더({vendor_h[0]}) 언급 + 기업맥락({', '.join(valid_impacts[:2])}) — 타사 기사"
                )
            else:
                v_score = 70 if len(valid_impacts) >= 2 else 65
                reasons.append(
                    f"벤더({vendor_h[0]}) + 기업 영향 맥락({', '.join(valid_impacts[:2])})"
                )
        elif promo_h:
            v_score = 15
            reasons.append(f"벤더 홍보성 기사 ({vendor_h[0]})")
            deducts.append(f"단순 홍보성 벤더 기사 ({promo_h[0]})")
        else:
            # 기업 영향 맥락 없음 → 단순 언급 상한 20
            v_score = 20
            reasons.append(f"벤더 언급({vendor_h[0]}) — 기업 영향 맥락 없음")

        if v_score > score:
            score = v_score

    # ── 4. 시장·트렌드 ───────────────────────────────────────
    topic_h = _hits(cx, topics)
    if topic_h:
        n_t = len(topic_h)

        # impact 단어 문맥 검증 (비용 절감 포함)
        valid_impacts_t = _filter_impacts(impact_h)
        n_i = len(valid_impacts_t)

        if q_type == "broad_topic":
            # broad_topic 쿼리:
            #   (1) topic이 제목에 있거나 query_keyword 자체가 제목에 독립 단어로 있어야 핵심 주제로 인정
            #   (2) impact가 제목 또는 topic/keyword와 동일 문장에 있어야 보통 이상
            kw_in_tl    = _keyword_in_title(query_keyword, tl)
            topic_in_tl = any(t in tl for t in topic_h) or kw_in_tl

            # cosentence 판정에도 query_keyword를 topic 후보로 포함
            topic_for_cosent = list(topic_h)
            if query_keyword:
                topic_for_cosent.append(query_keyword.lower())
            cosentence = _cosentence_check(tl, dl, topic_for_cosent, valid_impacts_t) if n_i > 0 else False

            # query_keyword가 제목에 있고 산업·기업 문맥어도 제목에 있으면 35점(보통 하단)
            broad_ctx = _lower(cfg.get("broad_context_terms", []))
            broad_ctx_hit = kw_in_tl and any(b in tl for b in broad_ctx)

            if n_i >= 2 and topic_in_tl and cosentence:
                t_score = 55
                reasons.append(
                    f"사업 주제({', '.join(topic_h[:2]) or query_keyword}) + 기업 영향 복수({', '.join(valid_impacts_t[:2])})"
                )
            elif n_i == 1 and topic_in_tl and cosentence:
                t_score = 40
                reasons.append(f"사업 주제({topic_h[0] if topic_h else query_keyword}) + 기업 영향 맥락({valid_impacts_t[0]})")
            elif n_t >= 3 and topic_in_tl:
                t_score = 35
                reasons.append(f"사업 관련 주제 복수 ({', '.join(topic_h[:3])})")
            elif broad_ctx_hit:
                # query_keyword 제목 + 산업/기업 문맥어 제목 → 보통 하단
                t_score = 35
                reasons.append(f"검색 주제({query_keyword}) 제목 포함 + 산업 문맥")
            elif topic_in_tl:
                t_score = 20
                reasons.append(f"사업 관련 주제 언급 ({topic_h[0] if topic_h else query_keyword})")
            else:
                # topic이 본문에만 있는 경우 — 핵심 주제로 보기 어려움
                t_score = 10
                reasons.append(f"사업 주제 본문 언급 ({topic_h[0]})")
        else:
            # 일반 쿼리: 기존 로직
            if n_i >= 2:
                t_score = 70
                reasons.append(
                    f"사업 주제({', '.join(topic_h[:2])}) + 기업 영향 복수({', '.join(valid_impacts_t[:2])})"
                )
            elif n_i == 1:
                t_score = 55
                reasons.append(f"사업 주제({topic_h[0]}) + 기업 영향 맥락({valid_impacts_t[0]})")
            elif n_t >= 2:
                t_score = 35
                reasons.append(f"사업 관련 주제 복수 ({', '.join(topic_h[:2])})")
            else:
                t_score = 20
                reasons.append(f"사업 관련 주제 언급 ({topic_h[0]})")

        if t_score > score:
            score = t_score

    # ── 5. 리스크 ────────────────────────────────────────────
    # 모호한 리스크 단어 문맥 검증
    valid_risks = []
    for r in _hits(cx, risks):
        if r == "장애":
            if _check_ambiguous("장애", cx, cfg):
                valid_risks.append(r)
        else:
            valid_risks.append(r)

    if valid_risks:
        has_sck_ctx = bool(own_h or vendor_h or topic_h)
        if q_type == "broad_topic":
            # broad_topic 쿼리: 리스크 단독으로 높음 불가 (공공기관 인프라 오탐 방지)
            r_score = 30 if has_sck_ctx else 10
            reasons.append(f"리스크 키워드: {', '.join(valid_risks[:2])}")
        elif has_sck_ctx:
            r_score = 70
            reasons.append(f"리스크 + SCK 관련 맥락 ({valid_risks[0]})")
        else:
            r_score = 40
            reasons.append(f"리스크 키워드: {', '.join(valid_risks[:2])}")
        if r_score > score:
            score = r_score

    # ── 6. 감점 ──────────────────────────────────────────────
    local_h = _hits(cx, local_)
    if local_h:
        score = max(0, score - 30)
        deducts.append(f"소비자/지역 관련 ({local_h[0]})")

    # 홍보성 단어 있고 기업 영향 맥락 없으면 추가 감점
    valid_impacts_final = _filter_impacts(impact_h)
    if promo_h and not valid_impacts_final and not own_h:
        score = max(0, score - 20)
        if not any("홍보성" in d for d in deducts):
            deducts.append(f"기업 홍보성 내용 ({promo_h[0]})")

    # ── vendor 타사 기사 최종 상한 (리스크 등 모든 경로 우회 방지) ─────
    if q_type == "vendor" and vendor_h and not vendor_is_title_subject and score > 30:
        score = 30
        deducts.append("vendor 타사 기사 상한 (30점) 적용")

    # ── 유형 결정 ────────────────────────────────────────────
    if own_h:
        rtype = "자사·관계사"
    elif comp_t or comp_score >= 55:
        rtype = "경쟁사"
    elif valid_risks and score >= 60 and q_type != "broad_topic":
        rtype = "리스크"
    elif vendor_h and valid_impacts_final:
        rtype = "벤더"
    elif topic_h and score >= 35:
        rtype = "시장동향"
    elif 0 < comp_score < 55:
        rtype = "경쟁사"
    elif valid_risks:
        rtype = "리스크"
    elif vendor_h:
        rtype = "벤더"
    elif topic_h:
        rtype = "시장동향"
    else:
        rtype = "일반"

    # ── 레벨 결정 ────────────────────────────────────────────
    if score >= 65:
        level = "높음"
    elif score >= 35:
        level = "보통"
    else:
        level = "낮음"

    low_reason = "; ".join(deducts)
    if level == "낮음" and not low_reason:
        low_reason = "SCK 사업 관련 맥락 부족"

    return {
        "_relevance_score":    score,
        "_relevance_level":    level,
        "_relevance_type":     rtype,
        "_relevance_reasons":  [r for r in reasons if r][:3],
        "_low_relevance_reason": low_reason,
        "_foreign_language":   False,
    }
