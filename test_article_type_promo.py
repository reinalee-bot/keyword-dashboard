"""
test_article_type_promo.py

P5A: classify_article_extended() / determine_promotional_likelihood() 단위 테스트

커버리지:
  - article_type 4종 기본 판정 (제외 대상 포함)
  - promotional_likelihood 3단계 (높음·보통·낮음)
  - 인터뷰+높음 / 행사+높음 / 기획+보통 / 일반+낮음 조합
  - classification_basis (title_only / title_and_description)
  - description만 PR 신호가 있는 케이스
  - 강한 PR 신호(_STRONG_PR_TITLE_SIGNALS)
  - P2a / P2b / P2c / P2d 각각
  - P2 다중 발동
  - 강한 PR 신호 + P2 동시 발동
  - 빈 title / 빈 description
  - 기존 classify_article_type() 하위 호환
  - 기존 45건 회귀 (보도자료형 → promotional_likelihood="높음")
"""
import json
import os
import sys

import pytest

# ── 경로 설정 ─────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

import news_fetcher as nf

ext  = nf.classify_article_extended
dpl  = nf.determine_promotional_likelihood
compat = nf.classify_article_type


# ══════════════════════════════════════════════════════════
# A. article_type 4종 기본 판정
# ══════════════════════════════════════════════════════════

class TestArticleType4종:
    """classify_article_extended 가 올바른 4종 article_type을 반환하는지 확인."""

    def test_interview_type(self):
        title = "클라우드 전문가 대표이사, AI 보안 전략 강조했다"
        r = ext(title, "")
        assert r["article_type"] == "인터뷰", r

    def test_event_type(self):
        title = "사이버 보안 컨퍼런스 2026 개막…주요 벤더 총출동"
        r = ext(title, "")
        assert r["article_type"] == "행사·현장", r

    def test_feature_type(self):
        title = "AI 보안 트렌드 심층 분석 리포트: 기획의 핵심 과제"
        r = ext(title, "기업 생태계 전망 진단")
        assert r["article_type"] == "기획·분석", r

    def test_general_type(self):
        title = "국내 클라우드 시장 점유율 변화"
        r = ext(title, "")
        assert r["article_type"] == "일반 기사", r

    def test_exclusion_stock(self):
        title = "AI 보안 종목 주가 급등 코스닥 상한가"
        r = ext(title, "")
        assert r["article_type"] == "제외 대상", r

    def test_exclusion_ad(self):
        title = "보안 솔루션 채용공고 신입 모집"
        r = ext(title, "")
        assert r["article_type"] == "제외 대상", r

    def test_column_marker_feature(self):
        title = "[보안 칼럼] AI 시대의 제로트러스트 도입 현황"
        r = ext(title, "")
        assert r["article_type"] == "기획·분석", r

    def test_no_보도자료형_in_output(self):
        """강한 PR 신호가 있어도 article_type에 '보도자료형'이 없어야 한다."""
        title = "테크회사, 업무협약 체결…클라우드 솔루션 출시"
        r = ext(title, "")
        assert r["article_type"] != "보도자료형", r


# ══════════════════════════════════════════════════════════
# B. promotional_likelihood 3단계
# ══════════════════════════════════════════════════════════

class TestPromotionalLikelihood:
    """promotional_likelihood 3단계 판정 검증."""

    def test_high_strong_signal(self):
        title = "클루커스, Straiker와 전략적 파트너십 체결"
        assert dpl(title, "") == "높음"

    def test_high_book_announce(self):
        title = "[신간] 인공지능 보안 완전 정복"
        assert dpl(title, "") == "높음"

    def test_high_p2_rule(self):
        # P2a: 기업명+지원+제공
        title = "SGA솔루션즈, 호남 중소기업 PC 보안 지원…악성코드·패치 관리 제공"
        assert dpl(title, "") == "높음"

    def test_high_pr_score_ge2(self):
        title = "테크플러스, 클라우드 솔루션 출시 및 파트너십 발표"
        assert dpl(title, "") == "높음"

    def test_high_pr_score1_with_org(self):
        title = "㈜에이아이솔루션 신규 서비스 출시"
        assert dpl(title, "") == "높음"

    def test_medium_pr_score1_no_org(self):
        title = "국내 클라우드 파트너십 동향 분석"
        r = dpl(title, "")
        assert r == "보통", r

    def test_low_no_pr_signal(self):
        title = "AI 에이전트 상호 공격 신세대 기법 등장"
        assert dpl(title, "") == "낮음"

    def test_low_empty_inputs(self):
        assert dpl("", "") == "낮음"


# ══════════════════════════════════════════════════════════
# C. 조합 케이스 (article_type × promotional_likelihood)
# ══════════════════════════════════════════════════════════

class TestTypeLikelihoodCombinations:

    def test_interview_high(self):
        """인터뷰 형식 + 홍보성 높음 조합."""
        # 대표이사(인터뷰 단서 2개) + 솔루션 출시(강한 PR 신호)
        title = "보안업체 대표이사, 새 솔루션 출시 전략 강조했다"
        r = ext(title, "")
        assert r["article_type"] == "인터뷰", r
        assert r["promotional_likelihood"] == "높음", r

    def test_event_high(self):
        """행사 + 홍보성 높음 조합."""
        title = "클라우드 컨퍼런스 2026 개막…제품 론칭 현장"
        r = ext(title, "")
        assert r["article_type"] == "행사·현장", r
        assert r["promotional_likelihood"] == "높음", r

    def test_feature_medium(self):
        """기획·분석 + 홍보성 보통 조합 (PR 단어 1개, 기관 없음)."""
        title = "AI 보안 트렌드 심층 분석: 파트너십 생태계 핵심 과제 전망"
        r = ext(title, "")
        assert r["article_type"] == "기획·분석", r
        assert r["promotional_likelihood"] == "보통", r

    def test_general_low(self):
        """일반 기사 + 홍보성 낮음 조합."""
        title = "AI 에이전트 상호 공격 신세대 기법 주목"
        r = ext(title, "")
        assert r["article_type"] == "일반 기사", r
        assert r["promotional_likelihood"] == "낮음", r


# ══════════════════════════════════════════════════════════
# D. classification_basis
# ══════════════════════════════════════════════════════════

class TestClassificationBasis:

    def test_title_only_when_empty_description(self):
        r = ext("AI 보안 동향", "")
        assert r["classification_basis"] == "title_only"

    def test_title_only_when_whitespace_description(self):
        r = ext("AI 보안 동향", "   ")
        assert r["classification_basis"] == "title_only"

    def test_title_and_description(self):
        r = ext("AI 보안 동향", "최신 공격 기법 분석")
        assert r["classification_basis"] == "title_and_description"

    def test_description_only_pr_signal(self):
        """제목에는 PR 단어 없고 설명에만 있는 케이스."""
        title = "클라우드 보안 업체 동향"        # PR 단어 없음
        desc  = "이 회사는 새로운 솔루션을 출시했다고 밝혔다"  # 출시 포함
        r = ext(title, desc)
        assert r["classification_basis"] == "title_and_description"
        # 설명 기여 PR 단어가 promotional_score에 반영돼야 한다
        assert r["promotional_score"] >= 1, r
        # description_signal 에 발견된 PR 단어가 있어야 한다
        assert r["description_signal"] != "", r

    def test_description_contributes_to_high(self):
        """설명 PR 단어가 높음을 만드는 케이스 (title: 1개 + desc: 1개 → score 2)."""
        title = "㈜테크솔루션, AI 파트너십 추진"           # 파트너십(1) + 기관
        desc  = "새로운 솔루션 출시도 함께 발표했다"        # 출시, 발표
        r = ext(title, desc)
        assert r["promotional_likelihood"] == "높음", r


# ══════════════════════════════════════════════════════════
# E. P2 복합 규칙
# ══════════════════════════════════════════════════════════

class TestP2RulesInExtended:

    def test_p2a_fires(self):
        title = "SGA솔루션즈, 호남 중소기업 PC 보안 지원…악성코드·패치 관리 제공"
        r = ext(title, "")
        assert "P2a" in r["matched_rule"], r
        assert r["promotional_likelihood"] == "높음", r

    def test_p2b_fires(self):
        title = "한국IDG, '2025 CIO 코리아 어워즈' 개최…국내 최우수 IT 리더 선정"
        r = ext(title, "")
        assert "P2b" in r["matched_rule"], r
        assert r["promotional_likelihood"] == "높음", r

    def test_p2c_fires(self):
        title = "PLURA-EDR, 3종 CC인증 획득…국내 최초 통합형 모델 공개"
        r = ext(title, "")
        assert "P2c" in r["matched_rule"], r
        assert r["promotional_likelihood"] == "높음", r

    def test_p2d_fires(self):
        # P2d: 기업명+쉼표 + 따옴표 제품명 + 제목 말미 '출시'
        title = "넥서스AI, '넥서스AI 플랫폼' 정식 출시"
        r = ext(title, "")
        assert "P2d" in r["matched_rule"], r
        assert r["promotional_likelihood"] == "높음", r

    def test_p2a_article_type_not_보도자료형(self):
        """P2 발동해도 article_type은 '보도자료형'이 아니어야 한다."""
        title = "SGA솔루션즈, 호남 중소기업 PC 보안 지원…악성코드·패치 관리 제공"
        r = ext(title, "")
        assert r["article_type"] != "보도자료형", r

    def test_p2_multiple_rules_fired(self):
        """P2 다중 발동 — matched_rule에 복수 규칙이 기록된다."""
        # P2a: 기업명+지원+제공 / P2c: 3종+공개(미공개 아님)+제외어 없음
        title = "엔플루엔스, 3종 보안 솔루션 지원 공개 제공"
        r = ext(title, "")
        rules = set(r["matched_rule"].split(",")) if r["matched_rule"] else set()
        assert len(rules) >= 2, f"expected multiple P2 rules, got: {r['matched_rule']!r}"
        assert r["promotional_likelihood"] == "높음", r

    def test_strong_signal_and_p2_coexist(self):
        """강한 PR 신호와 P2 규칙이 동시 발동될 때 두 필드 모두 기록된다."""
        # '업무협약 체결' → 강한 PR 신호 / 3종+공개 → P2c
        title = "에이블클라우드, 3종 솔루션 공개…업무협약 체결 완료"
        r = ext(title, "")
        assert r["title_signal"] != "", f"expected title_signal, got empty: {r}"
        assert "P2c" in r["matched_rule"], r
        assert r["promotional_likelihood"] == "높음", r

    def test_p2_does_not_affect_article_type_path(self):
        """P2 발동 여부와 상관없이 article_type은 내용 기반 4종으로만 결정된다."""
        # P2a fires (한글 기업명+지원+제공) + 인터뷰 단서(대표이사, 강조했다) → 인터뷰
        title = "에이아이솔루션, 대표이사 AI 전략 강조했다…보안 솔루션 지원 제공"
        r = ext(title, "")
        assert "P2a" in r["matched_rule"], r
        assert r["article_type"] == "인터뷰", r


# ══════════════════════════════════════════════════════════
# F. 근거 필드 (title_signal, description_signal, matched_rule)
# ══════════════════════════════════════════════════════════

class TestEvidenceFields:

    def test_title_signal_strong(self):
        title = "테크회사, 클라우드 솔루션 정식 출시"
        r = ext(title, "")
        assert r["title_signal"] == "정식 출시", r

    def test_title_signal_book(self):
        title = "[신간] 인공지능 완전 정복"
        r = ext(title, "")
        assert "[신간]" in r["title_signal"], r

    def test_title_signal_pr_word(self):
        title = "국내 클라우드 파트너십 현황"
        r = ext(title, "")
        assert r["title_signal"] == "파트너십", r

    def test_title_signal_empty_when_no_pr(self):
        title = "AI 에이전트 공격 기법 분석"
        r = ext(title, "")
        assert r["title_signal"] == "", r

    def test_description_signal_captured(self):
        title = "클라우드 보안 업체 동향"
        desc  = "회사는 신규 서비스를 출시하며 시장에 진입했다"
        r = ext(title, desc)
        assert r["description_signal"] != "", r

    def test_description_signal_empty_when_title_has_it(self):
        """title에 이미 있는 PR 단어는 description_signal에 기록하지 않는다."""
        title = "테크플러스 솔루션 출시 발표"
        desc  = "솔루션 출시 행사가 열렸다"
        r = ext(title, desc)
        # '출시'는 title에 이미 있으므로 description_signal에 중복 기록 안 됨
        assert "출시" not in r["description_signal"] or r["description_signal"] == "", r

    def test_matched_rule_sorted(self):
        """matched_rule이 쉼표 오름차순 정렬된 규칙명 형태다."""
        title = "엔플루엔스, 3종 보안 솔루션 지원 공개 제공"
        r = ext(title, "")
        if r["matched_rule"]:
            parts = r["matched_rule"].split(",")
            assert parts == sorted(parts), r

    def test_promotional_score_int(self):
        r = ext("클라우드 파트너십 발표", "")
        assert isinstance(r["promotional_score"], int)


# ══════════════════════════════════════════════════════════
# G. 빈 입력 에지 케이스
# ══════════════════════════════════════════════════════════

class TestEdgeCases:

    def test_empty_title_and_description(self):
        r = ext("", "")
        assert r["article_type"] in {"일반 기사", "제외 대상"}, r
        assert r["promotional_likelihood"] == "낮음", r
        assert r["classification_basis"] == "title_only", r

    def test_empty_title_nonempty_description(self):
        r = ext("", "AI 보안 분석 기술 트렌드")
        assert isinstance(r["article_type"], str)
        assert r["classification_basis"] == "title_and_description", r

    def test_whitespace_only_inputs(self):
        r = ext("   ", "   ")
        assert r["classification_basis"] == "title_only", r
        assert r["promotional_likelihood"] == "낮음", r


# ══════════════════════════════════════════════════════════
# H. 하위 호환 — classify_article_type() 결과 유지
# ══════════════════════════════════════════════════════════

class TestBackwardCompat:
    """classify_article_type()이 6종 반환을 유지하는지 확인."""

    CASES = [
        ("보도자료형", "웹케시, IBK기업은행 공급계약 체결"),
        ("기획·분석",  "[보안 칼럼] AI 시대의 제로트러스트 도입 현황"),
        ("인터뷰",     "클라우드 전문가 대표이사, AI 전략 강조했다 밝혔다"),
        ("행사·현장",  "사이버 보안 컨퍼런스 2026 개막…주요 벤더 총출동"),
        ("일반 기사",  "AI 에이전트 상호 공격 신세대 기법 등장"),
        ("제외 대상",  "AI 관련 종목 주가 급등 코스닥 상한가"),
    ]

    @pytest.mark.parametrize("expected,title", CASES)
    def test_compat(self, expected, title):
        result = compat(title, "")
        assert result == expected, f"title={title!r}: expected {expected!r}, got {result!r}"

    def test_보도자료형_still_returned(self):
        """기존 함수가 '보도자료형'을 계속 반환해야 한다."""
        title = "테크플러스, 클라우드 신규 서비스 출시"
        assert compat(title, "") == "보도자료형"


# ══════════════════════════════════════════════════════════
# I. 기존 45건 회귀 — 보도자료형 → promotional_likelihood="높음"
# ══════════════════════════════════════════════════════════

_REGRESSION_JSON = os.path.join(BASE_DIR, "regression_collected.json")
_EXPECTED_PR_IDX = {0, 3, 5, 6, 11, 14, 19, 24, 26, 29, 31, 42}  # EXPECTED_MAP 보도자료형 idx


@pytest.mark.skipif(
    not os.path.exists(_REGRESSION_JSON),
    reason="regression_collected.json 없음",
)
class TestRegressionPromotional:
    """기존 45건 회귀: 보도자료형 기대 기사 → promotional_likelihood="높음"."""

    def _load_articles(self):
        with open(_REGRESSION_JSON, encoding="utf-8") as f:
            return json.load(f)

    def test_expected_보도자료형_all_high(self):
        articles = self._load_articles()
        failures = []
        for idx in sorted(_EXPECTED_PR_IDX):
            art   = articles[idx]
            title = art.get("title", "")
            r     = ext(title, "")
            if r["promotional_likelihood"] != "높음":
                failures.append(
                    f"idx={idx} title={title[:40]!r} → {r['promotional_likelihood']!r}"
                )
        assert not failures, "보도자료형 기대 기사 중 promotional_likelihood≠높음:\n" + "\n".join(failures)

    def test_no_보도자료형_in_extended_output(self):
        """45건 중 어떤 기사도 article_type에 '보도자료형'이 없어야 한다."""
        articles = self._load_articles()
        violations = []
        for idx, art in enumerate(articles):
            title = art.get("title", "")
            r     = ext(title, "")
            if r["article_type"] == "보도자료형":
                violations.append(f"idx={idx} title={title[:40]!r}")
        assert not violations, "'보도자료형' article_type 발견:\n" + "\n".join(violations)

    def test_all_45_return_valid_dict(self):
        """45건 전체가 올바른 키를 가진 dict를 반환해야 한다."""
        REQUIRED_KEYS = {
            "article_type", "promotional_likelihood", "title_signal",
            "description_signal", "matched_rule", "promotional_score",
            "classification_basis",
        }
        articles = self._load_articles()
        for idx, art in enumerate(articles):
            r = ext(art.get("title", ""), "")
            assert REQUIRED_KEYS <= r.keys(), f"idx={idx}: 누락된 키 {REQUIRED_KEYS - r.keys()}"
            assert r["promotional_likelihood"] in {"높음", "보통", "낮음"}, f"idx={idx}: {r}"
            assert r["classification_basis"] in {"title_only", "title_and_description"}, f"idx={idx}: {r}"


# ══════════════════════════════════════════════════════════
# J. determine_promotional_likelihood() 독립 호출 일관성
# ══════════════════════════════════════════════════════════

class TestDeterminePromotionalLikelihoodConsistency:
    """dpl()과 ext()의 promotional_likelihood가 일치해야 한다."""

    TITLES = [
        "테크회사, 클라우드 솔루션 정식 출시",
        "SGA솔루션즈, 호남 중소기업 PC 보안 지원…악성코드·패치 관리 제공",
        "AI 에이전트 공격 기법 분석",
        "[신간] 인공지능 보안 완전 정복",
        "국내 클라우드 파트너십 현황",
        "㈜테크솔루션 신규 서비스 출시",
    ]

    @pytest.mark.parametrize("title", TITLES)
    def test_consistency_title_only(self, title):
        assert dpl(title, "") == ext(title, "")["promotional_likelihood"], title

    @pytest.mark.parametrize("title", TITLES)
    def test_consistency_with_description(self, title):
        desc = "솔루션 출시 파트너십 발표"
        assert dpl(title, desc) == ext(title, desc)["promotional_likelihood"], title
