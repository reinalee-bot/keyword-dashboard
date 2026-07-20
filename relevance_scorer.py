"""
SCK 뉴스 관련성 판정 모듈
config/relevance_config.yaml 의 설정을 읽어 기사 제목·설명에 점수를 부여한다.

반환 필드:
  _relevance_score       int  0-100
  _relevance_level       str  높음 / 보통 / 낮음
  _relevance_type        str  자사·관계사 / 경쟁사 / 벤더 / 시장동향 / 리스크 / 일반
  _relevance_reasons     list[str]  판정 근거 최대 3개
  _low_relevance_reason  str  감점 또는 낮은 관련성 사유
"""

import os
from functools import lru_cache

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config", "relevance_config.yaml")

_FALLBACK = {
    "_relevance_score":    50,
    "_relevance_level":    "보통",
    "_relevance_type":     "일반",
    "_relevance_reasons":  [],
    "_low_relevance_reason": "",
}


@lru_cache(maxsize=1)
def _load_config() -> dict:
    import yaml  # import here to avoid hard dependency at module level
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _lower(lst) -> list:
    return [str(x).lower() for x in (lst or [])]


def _hits(text: str, terms: list) -> list:
    """text 안에서 발견된 terms 반환 (소문자 비교)."""
    return [t for t in terms if t in text]


# ─────────────────────────────────────────────────────────────
def score_relevance(title: str, description: str) -> dict:
    """
    기사 제목과 description 을 받아 SCK 관련성 점수 및 판정을 반환한다.
    설정 파일 로드에 실패하면 중립값(FALLBACK)을 반환한다.
    """
    try:
        cfg = _load_config()
    except Exception:
        return dict(_FALLBACK)

    tl = (title or "").lower()
    dl = (description or "").lower()
    cx = tl + " " + dl  # 제목+설명 합산 텍스트

    owned   = _lower(cfg.get("owned_entities", []))
    comps   = _lower(cfg.get("competitor_entities", []))
    vendors = _lower(cfg.get("vendor_entities", []))
    topics  = _lower(cfg.get("business_topics", []))
    impacts = _lower(cfg.get("enterprise_impact", []))
    risks   = _lower(cfg.get("risk_terms", []))
    promos  = _lower(cfg.get("promotional_terms", []))
    local_  = _lower(cfg.get("consumer_or_local_terms", []))

    score   = 0
    reasons: list = []
    deducts: list = []

    # ── 1. 자사·관계사 직접 언급 ─────────────────────────────
    own_h = _hits(cx, owned)
    if own_h:
        score = 90
        reasons.append(f"자사/관계사 직접 언급: {own_h[0]}")

    # ── 2. 경쟁사 ────────────────────────────────────────────
    comp_t = _hits(tl, comps)   # 제목에 등장
    comp_d = _hits(dl, comps)   # 본문에 등장
    comp_score = 0
    if comp_t:
        comp_score = 80
        reasons.append(f"경쟁사 주요 주체 ({comp_t[0]})")
    elif len(comp_d) >= 2:
        comp_score = 55
        reasons.append(f"경쟁사 보도 내 주요 언급 ({comp_d[0]})")
    elif comp_d:
        comp_score = 35
        reasons.append(f"경쟁사 단순 등장 ({comp_d[0]})")

    if comp_score > score:
        score = comp_score

    # ── 3. 벤더 + 맥락 ───────────────────────────────────────
    vendor_h = _hits(cx, vendors)
    impact_h = _hits(cx, impacts)
    promo_h  = _hits(cx, promos)

    if vendor_h:
        if impact_h:
            # 기업 영향 맥락 2개 이상이면 추가 가점
            v_score = 70 if len(impact_h) >= 2 else 65
            reasons.append(
                f"벤더({vendor_h[0]}) + 기업 영향 맥락({', '.join(impact_h[:2])})"
            )
        elif promo_h:
            v_score = 15
            reasons.append(f"벤더 홍보성 기사 ({vendor_h[0]})")
            deducts.append(f"단순 홍보성 벤더 기사 ({promo_h[0]})")
        else:
            v_score = 20
            reasons.append(f"벤더 언급({vendor_h[0]}) — 기업 영향 맥락 없음")
        if v_score > score:
            score = v_score

    # ── 4. 시장·트렌드 ───────────────────────────────────────
    topic_h = _hits(cx, topics)
    if topic_h:
        n_t = len(topic_h)
        n_i = len(impact_h)
        if n_i >= 2:
            t_score = 70
            reasons.append(
                f"사업 주제({', '.join(topic_h[:2])}) + 기업 영향 복수({', '.join(impact_h[:2])})"
            )
        elif n_i == 1:
            t_score = 55
            reasons.append(f"사업 주제({topic_h[0]}) + 기업 영향 맥락({impact_h[0]})")
        elif n_t >= 2:
            t_score = 35
            reasons.append(f"사업 관련 주제 복수 ({', '.join(topic_h[:2])})")
        else:
            t_score = 20
            reasons.append(f"사업 관련 주제 언급 ({topic_h[0]})")
        if t_score > score:
            score = t_score

    # ── 5. 리스크 ────────────────────────────────────────────
    risk_h = _hits(cx, risks)
    if risk_h:
        # SCK 사업 관련 맥락(벤더·주제·자사)과 연결 시 우선순위 상승
        if own_h or vendor_h or topic_h:
            r_score = 70
            reasons.append(f"리스크 + SCK 관련 맥락 ({risk_h[0]})")
        else:
            r_score = 40
            reasons.append(f"리스크 키워드: {', '.join(risk_h[:2])}")
        if r_score > score:
            score = r_score

    # ── 6. 감점 ──────────────────────────────────────────────
    local_h = _hits(cx, local_)
    if local_h:
        score = max(0, score - 30)
        deducts.append(f"소비자/지역 관련 ({local_h[0]})")

    # 홍보성 단어 있고 기업 영향 맥락 없으면 추가 감점
    if promo_h and not impact_h and not own_h:
        score = max(0, score - 20)
        if not any("홍보성" in d for d in deducts):
            deducts.append(f"기업 홍보성 내용 ({promo_h[0]})")

    # ── 유형 결정 (우선순위: 자사 > 경쟁사 > 리스크 > 벤더 > 시장동향 > 일반) ──
    if own_h:
        rtype = "자사·관계사"
    elif comp_t or comp_score >= 55:
        rtype = "경쟁사"
    elif risk_h and score >= 60:
        rtype = "리스크"
    elif vendor_h and impact_h:
        rtype = "벤더"
    elif topic_h and score >= 35:
        rtype = "시장동향"
    elif 0 < comp_score < 55:
        rtype = "경쟁사"
    elif risk_h:
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

    # 낮음이지만 감점 사유 없을 때도 사유 표시
    low_reason = "; ".join(deducts)
    if level == "낮음" and not low_reason:
        low_reason = "SCK 사업 관련 맥락 부족"

    return {
        "_relevance_score":    score,
        "_relevance_level":    level,
        "_relevance_type":     rtype,
        "_relevance_reasons":  [r for r in reasons if r][:3],
        "_low_relevance_reason": low_reason,
    }
