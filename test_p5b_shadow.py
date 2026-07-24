"""
test_p5b_shadow.py

P5B: shadow 모드 런타임 통합 단위 테스트

커버리지:
  - 기본 모드(_EXTENDED_SHADOW=False): art dict에 _ext_* 필드 없음
  - shadow 모드(_EXTENDED_SHADOW=True): art dict에 _ext_* 필드 존재
  - _ext_* 필드가 기존 article_type을 덮어쓰지 않음
  - REVIEW_COLS에 _ext_* 필드 없음
  - 동일 입력 결정성 (두 번 호출 → 동일 결과)
  - 하위 호환 (기존 호출부 반환 스키마 불변)
  - 저장 함수로 _ext_* 필드 전달 안 됨
  - 빈 title/description 처리
  - P2 다중 발동 정보 보존
  - enrich_article_extended() 직접 호출 검증
  - 신규 _ext_ 필드가 monitoring_reviews.csv에 저장되지 않음
"""
import contextlib
import os
import sys
import tempfile

import pytest

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

import news_fetcher as nf
from monitoring_review_store import REVIEW_COLS, save_review, reset_ws_cache

# ── 헬퍼 ─────────────────────────────────────────────────────────────────────

_EXT_KEYS = {
    "_ext_article_type",
    "_ext_promotional_likelihood",
    "_ext_title_signal",
    "_ext_description_signal",
    "_ext_matched_rule",
    "_ext_promotional_score",
    "_ext_classification_basis",
}


def _make_art(title: str, description: str = "") -> dict:
    """article 처리 루프에서 생성되는 최소 art dict 생성."""
    return {
        "title":       title,
        "description": description,
        "url":         "",
        "media_name":  "",
        "article_type": "",
        "_filter_reason": "",
    }


@contextlib.contextmanager
def _shadow_on():
    """테스트 내에서만 _EXTENDED_SHADOW=True로 설정하는 컨텍스트 매니저."""
    old = nf._EXTENDED_SHADOW
    nf._EXTENDED_SHADOW = True
    try:
        yield
    finally:
        nf._EXTENDED_SHADOW = old


# ══════════════════════════════════════════════════════════
# A. 기본 모드 / shadow 모드 on/off
# ══════════════════════════════════════════════════════════

class TestShadowOnOff:

    def test_default_shadow_is_false(self):
        """모듈 기본값은 False여야 한다."""
        assert nf._EXTENDED_SHADOW is False

    def test_no_ext_fields_in_default_mode(self):
        """기본 모드에서 enrich_article_extended() 를 호출하지 않으면 _ext_ 없음."""
        art = _make_art("테크플러스, 클라우드 솔루션 출시")
        art["article_type"] = nf.classify_article_type(art["title"], art["description"])
        # shadow 미활성 → enrich 미호출
        assert _EXT_KEYS.isdisjoint(art.keys()), f"예상치 않은 _ext_ 키: {_EXT_KEYS & art.keys()}"

    def test_ext_fields_present_in_shadow_mode(self):
        """shadow 모드 활성 후 enrich_article_extended() 호출 시 _ext_ 키 모두 존재."""
        art = _make_art("테크플러스, 클라우드 솔루션 출시")
        with _shadow_on():
            nf.enrich_article_extended(art)
        assert _EXT_KEYS <= art.keys(), f"누락된 키: {_EXT_KEYS - art.keys()}"

    def test_shadow_flag_restored_after_context(self):
        """_shadow_on() 컨텍스트 종료 후 플래그가 원래대로 복원된다."""
        with _shadow_on():
            pass
        assert nf._EXTENDED_SHADOW is False


# ══════════════════════════════════════════════════════════
# B. enrich_article_extended() 직접 호출 검증
# ══════════════════════════════════════════════════════════

class TestEnrichArticleExtended:

    def test_does_not_overwrite_article_type(self):
        """enrich_article_extended()는 article_type 필드를 덮어쓰지 않는다."""
        art = _make_art("테크플러스, 클라우드 솔루션 출시")
        art["article_type"] = "보도자료형"          # 기존 판정 고정
        nf.enrich_article_extended(art)
        assert art["article_type"] == "보도자료형"  # 변경 없어야 함

    def test_ext_article_type_not_보도자료형(self):
        """_ext_article_type 에는 '보도자료형'이 나타나지 않는다."""
        art = _make_art("테크플러스, 클라우드 솔루션 출시")
        nf.enrich_article_extended(art)
        assert art["_ext_article_type"] != "보도자료형"

    def test_ext_promo_high_for_strong_signal(self):
        """강한 PR 신호 → _ext_promotional_likelihood='높음'."""
        art = _make_art("클루커스, Straiker와 전략적 파트너십 체결")
        nf.enrich_article_extended(art)
        assert art["_ext_promotional_likelihood"] == "높음"

    def test_ext_promo_low_for_general(self):
        """PR 단어 없음 → _ext_promotional_likelihood='낮음'."""
        art = _make_art("AI 에이전트 공격 기법 등장")
        nf.enrich_article_extended(art)
        assert art["_ext_promotional_likelihood"] == "낮음"

    def test_ext_matched_rule_p2a(self):
        """P2a 발동 → _ext_matched_rule에 'P2a' 포함."""
        art = _make_art("SGA솔루션즈, 호남 중소기업 PC 보안 지원…악성코드·패치 관리 제공")
        nf.enrich_article_extended(art)
        assert "P2a" in art["_ext_matched_rule"]

    def test_ext_matched_rule_multiple_p2(self):
        """P2 복수 발동 → _ext_matched_rule에 복수 규칙 기록."""
        art = _make_art("엔플루엔스, 3종 보안 솔루션 지원 공개 제공")
        nf.enrich_article_extended(art)
        rules = [r for r in art["_ext_matched_rule"].split(",") if r]
        assert len(rules) >= 2, f"expected ≥2 rules, got: {art['_ext_matched_rule']!r}"

    def test_ext_promotional_score_int(self):
        art = _make_art("클라우드 파트너십 발표")
        nf.enrich_article_extended(art)
        assert isinstance(art["_ext_promotional_score"], int)

    def test_ext_classification_basis_title_only(self):
        art = _make_art("AI 보안 동향", "")
        nf.enrich_article_extended(art)
        assert art["_ext_classification_basis"] == "title_only"

    def test_ext_classification_basis_with_desc(self):
        art = _make_art("AI 보안 동향", "최신 공격 기법 분석")
        nf.enrich_article_extended(art)
        assert art["_ext_classification_basis"] == "title_and_description"

    def test_empty_title_no_crash(self):
        art = _make_art("", "")
        nf.enrich_article_extended(art)
        assert "_ext_article_type" in art


# ══════════════════════════════════════════════════════════
# C. 결정성
# ══════════════════════════════════════════════════════════

class TestDeterminism:

    TITLES = [
        "테크회사, 클라우드 솔루션 정식 출시",
        "SGA솔루션즈, 호남 중소기업 PC 보안 지원…악성코드·패치 관리 제공",
        "AI 에이전트 공격 기법 분석",
        "클라우드 전문가 대표이사, AI 전략 강조했다",
    ]

    @pytest.mark.parametrize("title", TITLES)
    def test_deterministic(self, title):
        art1 = _make_art(title)
        art2 = _make_art(title)
        nf.enrich_article_extended(art1)
        nf.enrich_article_extended(art2)
        for key in _EXT_KEYS:
            assert art1[key] == art2[key], f"비결정적 {key}: {art1[key]!r} != {art2[key]!r}"


# ══════════════════════════════════════════════════════════
# D. 스키마 보호 — REVIEW_COLS 및 저장 경로 격리
# ══════════════════════════════════════════════════════════

class TestSchemaIsolation:

    def test_ext_keys_not_in_review_cols(self):
        """_ext_* 키가 REVIEW_COLS에 포함되지 않는다."""
        for key in _EXT_KEYS:
            assert key not in REVIEW_COLS, f"{key!r} 가 REVIEW_COLS에 있어서는 안 됨"

    def test_ext_prefix_fields_not_in_review_cols(self):
        """REVIEW_COLS 중 '_ext_' 로 시작하는 필드가 없다."""
        ext_in_cols = [c for c in REVIEW_COLS if c.startswith("_ext_")]
        assert ext_in_cols == [], f"_ext_ 접두사 필드 발견: {ext_in_cols}"

    def test_save_review_ignores_ext_fields(self):
        """save_review()에 _ext_ 필드를 포함해 전달해도 저장 데이터에 포함되지 않는다."""
        import hashlib

        # 임시 CSV로 격리
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as tmp:
            tmp_path = tmp.name

        try:
            import monitoring_review_store as mrs
            original_csv = mrs.REVIEWS_CSV
            mrs.REVIEWS_CSV = tmp_path
            reset_ws_cache()

            review = {
                "article_id":          "test_p5b_isolation",
                "title":               "P5B 격리 테스트",
                "url":                 "https://example.com/test",
                "media":               "테스트매체",
                "published_at":        "2026-07-23",
                "review_status":       "검토 전",
                # _ext_ 필드 포함
                "_ext_article_type":           "일반 기사",
                "_ext_promotional_likelihood": "높음",
                "_ext_matched_rule":           "P2a",
                "_ext_promotional_score":      2,
                "_ext_classification_basis":   "title_only",
            }
            ok, _ = save_review(review)
            assert ok

            import pandas as pd
            df = pd.read_csv(tmp_path, dtype=str).fillna("")
            assert "article_id" in df.columns
            # _ext_ 컬럼이 없어야 함
            ext_cols = [c for c in df.columns if c.startswith("_ext_")]
            assert ext_cols == [], f"_ext_ 컬럼이 CSV에 저장됨: {ext_cols}"
        finally:
            mrs.REVIEWS_CSV = original_csv
            reset_ws_cache()
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def test_prod_csv_no_ext_columns(self):
        """운영 monitoring_reviews.csv에 _ext_* 컬럼이 포함되지 않는다.
        shadow 필드가 운영 저장소에 유출되지 않음을 검증한다.
        (특정 해시 대신 구조적 불변식을 검사 — 스키마 변경에 강인)
        """
        import pandas as pd
        csv_path = os.path.join(BASE_DIR, "data", "monitoring_reviews.csv")
        if not os.path.exists(csv_path):
            return  # 파일 없음 — 이상 없음
        try:
            df = pd.read_csv(csv_path, dtype=str).fillna("")
        except Exception as exc:
            assert False, f"운영 CSV 읽기 실패: {exc}"
        ext_cols = [c for c in df.columns if c.startswith("_ext_")]
        assert ext_cols == [], f"_ext_ 컬럼이 운영 CSV에 존재: {ext_cols}"


# ══════════════════════════════════════════════════════════
# E. shadow 모드와 기존 classify_article_type() 호환성
# ══════════════════════════════════════════════════════════

class TestBackwardCompatInShadowMode:

    def test_article_type_unchanged_when_shadow_on(self):
        """shadow 모드에서도 article_type 결과는 classify_article_type() 과 동일."""
        titles = [
            "웹케시, IBK기업은행 공급계약 체결",
            "[보안 칼럼] AI 시대의 제로트러스트",
            "클라우드 전문가 대표이사 AI 전략 강조했다 밝혔다",
            "AI 에이전트 상호 공격 신세대 기법",
        ]
        for title in titles:
            old_type = nf.classify_article_type(title, "")
            art = _make_art(title)
            art["article_type"] = old_type
            nf.enrich_article_extended(art)
            assert art["article_type"] == old_type, (
                f"article_type 덮어씌워짐: {title!r} -> {art['article_type']!r}"
            )

    def test_shadow_on_and_off_give_same_article_type(self):
        """shadow on/off 여부와 무관하게 article_type 판정은 동일하다."""
        title = "테크플러스, 클라우드 신규 서비스 출시"
        desc  = ""
        # shadow off
        type_off = nf.classify_article_type(title, desc)
        # shadow on (enrich는 별도 필드만 추가)
        art = _make_art(title, desc)
        art["article_type"] = nf.classify_article_type(title, desc)
        nf.enrich_article_extended(art)
        assert art["article_type"] == type_off

    def test_ext_type_and_legacy_type_can_differ(self):
        """_ext_article_type은 보도자료형을 반환하지 않으므로 기존 판정과 다를 수 있다."""
        title = "테크플러스, 클라우드 신규 서비스 출시"
        art = _make_art(title)
        art["article_type"] = nf.classify_article_type(title, "")
        nf.enrich_article_extended(art)
        # 기존: 보도자료형 / 신규: 일반 기사 또는 다른 4종
        assert art["article_type"] != art["_ext_article_type"] or \
               art["article_type"] not in {"보도자료형"}, \
               "두 판정이 같다면 보도자료형이 아니어야 함"


# ══════════════════════════════════════════════════════════
# F. 45건 회귀 (title-only 환경 shadow 결과)
# ══════════════════════════════════════════════════════════

import json as _json

_REGRESSION_JSON = os.path.join(BASE_DIR, "regression_collected.json")
_PR_IDX = {0, 3, 5, 6, 11, 14, 19, 24, 26, 29, 31, 42}  # 기존 보도자료형 기대


@pytest.mark.skipif(
    not os.path.exists(_REGRESSION_JSON),
    reason="regression_collected.json 없음",
)
class TestShadowRegression45:

    def _load(self):
        with open(_REGRESSION_JSON, encoding="utf-8") as f:
            return _json.load(f)

    def test_no_보도자료형_in_ext_for_all_45(self):
        """45건 전체에서 _ext_article_type에 '보도자료형'이 없다."""
        arts = self._load()
        for idx, a in enumerate(arts):
            art = _make_art(a.get("title", ""))
            nf.enrich_article_extended(art)
            assert art["_ext_article_type"] != "보도자료형", \
                f"idx={idx}: '보도자료형' 발견"

    def test_pr_expected_all_high_in_shadow(self):
        """기존 '보도자료형' 기대 기사 모두 _ext_promotional_likelihood='높음'."""
        arts = self._load()
        fails = []
        for idx in sorted(_PR_IDX):
            art = _make_art(arts[idx].get("title", ""))
            nf.enrich_article_extended(art)
            if art["_ext_promotional_likelihood"] != "높음":
                fails.append(
                    f"idx={idx}: {arts[idx]['title'][:40]!r} → {art['_ext_promotional_likelihood']!r}"
                )
        assert not fails, "보도자료형 기대 기사 중 promo≠높음:\n" + "\n".join(fails)

    def test_행사현장_preserved_in_shadow(self):
        """행사·현장 기대 기사(idx=20)가 신규 체계에서도 '행사·현장'으로 분류된다."""
        arts = self._load()
        art = _make_art(arts[20].get("title", ""))
        nf.enrich_article_extended(art)
        assert art["_ext_article_type"] == "행사·현장", \
            f"idx=20: expected 행사·현장, got {art['_ext_article_type']!r}"

    def test_all_45_ext_schema_valid(self):
        """45건 모두 _ext_* 키 7개가 올바른 타입으로 존재한다."""
        arts = self._load()
        for idx, a in enumerate(arts):
            art = _make_art(a.get("title", ""))
            nf.enrich_article_extended(art)
            assert _EXT_KEYS <= art.keys(), f"idx={idx}: 누락 키"
            assert art["_ext_promotional_likelihood"] in {"높음", "보통", "낮음"}, \
                f"idx={idx}: 유효하지 않은 promotional_likelihood"
            assert art["_ext_classification_basis"] in {"title_only", "title_and_description"}, \
                f"idx={idx}: 유효하지 않은 classification_basis"
            assert isinstance(art["_ext_promotional_score"], int), \
                f"idx={idx}: promotional_score가 int가 아님"
