"""
8단계 기사 분류 품질 검증 테스트 (30건)
- 보도자료성 기사가 기획기사 후보로 오분류되지 않는지 검증
- 기획·분석 기사가 올바르게 분류되는지 검증
- 리스크 분류(SCK 무관 타사 사건 = security_trend) 검증
- 운영 CSV 미접촉 (news_fetcher, monitoring 단위 함수만 테스트)
"""
import sys
import os
import unittest

_BASE = os.path.dirname(__file__)
if _BASE not in sys.path:
    sys.path.insert(0, _BASE)

import news_fetcher as nf
import monitoring as mon


# ─────────────────────────────────────────────────────────────
# 헬퍼: 최소 기사 dict 생성
# ─────────────────────────────────────────────────────────────
def _art(title, desc="", atype=None, rlevel="보통", rtype="일반", groups=None, tier=3, matched_queries=None, matched_groups=None):
    """테스트용 기사 dict 생성."""
    a = {
        "title": title,
        "description": desc,
        "article_type": atype or nf.classify_article_type(title, desc),
        "_relevance_level": rlevel,
        "_relevance_type": rtype,
        "_matched_groups": groups or matched_groups or [],
        "_matched_queries": matched_queries or [],
        "_media_tier": tier,
        "_relevance_reasons": [],
        "_relevance_score": {"높음": 80, "보통": 55, "낮음": 20}.get(rlevel, 55),
        "media_name": "테스트매체",
        "url": "https://example.com/test",
        "_in_whitelist": tier <= 2,
    }
    return a


# ══════════════════════════════════════════════════════════════
# Group 1: classify_article_type — 보도자료 강 신호 우선
# ══════════════════════════════════════════════════════════════
class TestClassifyArticleType(unittest.TestCase):

    # ① 파트너십 체결 → 보도자료형 (기획·분석 불가)
    def test_01_partnership_is_pr(self):
        result = nf.classify_article_type(
            "SCK Corp, MS와 파트너십 체결로 클라우드 보안 시장 진출",
            "SCK Corp이 마이크로소프트와 전략적 파트너십 체결을 공식 발표했다.")
        self.assertEqual(result, "보도자료형")

    # ② 제품 출시 → 보도자료형
    def test_02_product_launch_is_pr(self):
        result = nf.classify_article_type(
            "보안 스타트업 A사, 차세대 EDR 솔루션 출시 발표",
            "A사가 기업 보안 솔루션을 정식 출시한다고 밝혔다.")
        self.assertEqual(result, "보도자료형")

    # ③ MOU 체결 → 보도자료형
    def test_03_mou_is_pr(self):
        result = nf.classify_article_type(
            "A사·B사 사이버보안 분야 MOU 체결",
            "두 회사는 업무협약 체결을 통해 공동 사업을 추진하기로 했다.")
        self.assertEqual(result, "보도자료형")

    # ④ 기획 분석 단어 3개 이상 + 파트너십 강 신호 없음 → 기획·분석
    def test_04_analysis_article_classified_correctly(self):
        result = nf.classify_article_type(
            "기업 보안 전략의 핵심, AI 기반 위협 분석 왜 중요한가",
            "기업들이 사이버 위협에 대응하는 전략을 심층 분석한다.")
        self.assertEqual(result, "기획·분석")

    # ⑤ 선정 + 공급기업 → 보도자료형
    def test_05_selection_is_pr(self):
        result = nf.classify_article_type(
            "A사, 중소기업 보안 지원사업 공급기업 선정",
            "정보보호 솔루션 공급기업으로 선정됐다고 발표했다.")
        self.assertEqual(result, "보도자료형")

    # ⑥ 수상 → 보도자료형
    def test_06_award_is_pr(self):
        result = nf.classify_article_type(
            "SCK Corp, 대한민국 SW 대상 수상",
            "SCK Corp가 올해 IT 솔루션 부문에서 대상을 수상했다.")
        self.assertEqual(result, "보도자료형")

    # ⑦ 인터뷰 → 인터뷰
    def test_07_interview_classified(self):
        result = nf.classify_article_type(
            '"AI 시대 보안은 달라진다" SCK 대표이사 인터뷰',
            "SCK 대표이사가 AI 보안 트렌드에 대해 강조했다.")
        self.assertEqual(result, "인터뷰")

    # ⑧ 세미나 → 행사·현장
    def test_08_event_classified(self):
        result = nf.classify_article_type(
            "ISEC 2026 보안 컨퍼런스 현장",
            "올해 ISEC에서 최신 사이버보안 트렌드가 발표됐다.")
        self.assertEqual(result, "행사·현장")

    # ⑨ 기획 단어 2개 + 파트너십 없음 → 기획·분석 불가 (3개 미만)
    def test_09_two_feature_words_not_enough(self):
        result = nf.classify_article_type(
            "시장 분석 보고서",
            "올해 클라우드 시장 현황을 정리했다.")
        # 분석(1) + 시장(X - 제거됨) → "기획·분석" 아님
        self.assertNotEqual(result, "기획·분석")

    # ⑩ 수주 계약 → 보도자료형
    def test_10_contract_is_pr(self):
        result = nf.classify_article_type(
            "A사, 공공기관 IT 솔루션 수주 계약 체결",
            "계약 규모는 50억원이며 2026년 말까지 납품한다.")
        self.assertEqual(result, "보도자료형")


# ══════════════════════════════════════════════════════════════
# Group 2: _determine_category — 기획기사 후보 조건
# ══════════════════════════════════════════════════════════════
class TestDetermineCategory(unittest.TestCase):

    # ⑪ 보도자료형 + 관련성 높음 → 기획기사 후보 제외
    def test_11_pr_type_not_editorial_candidate(self):
        a = _art("SCK Corp 제품 출시 발표", atype="보도자료형", rlevel="높음")
        result = mon._determine_category(a)
        self.assertNotEqual(result, "기획기사 후보",
            "보도자료형 기사는 기획기사 후보가 될 수 없어야 한다.")

    # ⑫ 기획·분석 + 관련성 높음 + 보도자료 아님 → 기획기사 후보
    def test_12_analysis_high_relevance_is_candidate(self):
        a = _art("AI 보안 전략의 핵심 과제", atype="기획·분석", rlevel="높음")
        result = mon._determine_category(a)
        self.assertEqual(result, "기획기사 후보")

    # ⑬ 기획·분석 + 관련성 낮음 → 기획기사 후보 아님
    def test_13_analysis_low_relevance_not_candidate(self):
        a = _art("글로벌 클라우드 트렌드 분석", atype="기획·분석", rlevel="낮음")
        result = mon._determine_category(a)
        self.assertNotEqual(result, "기획기사 후보")

    # ⑭ 파트너십 기사 (보도자료형) → 기획기사 후보 아님
    def test_14_partnership_not_editorial_candidate(self):
        a = _art(
            "A사·B사 파트너십 체결 발표",
            desc="파트너십 체결을 공식 발표했다.",
            atype="보도자료형",
            rlevel="높음"
        )
        result = mon._determine_category(a)
        self.assertNotEqual(result, "기획기사 후보")

    # ⑮ 리스크 관련성 기사 → 리스크 카테고리
    def test_15_risk_relevance_type_is_risk(self):
        a = _art(
            "기업 사이버 보안 위협 급증",
            rtype="리스크", rlevel="높음", atype="기획·분석"
        )
        result = mon._determine_category(a)
        self.assertEqual(result, "리스크")

    # ⑯ 자사 언급 기사 → 자사·관계사
    def test_16_company_mention_category(self):
        a = _art(
            "SCK Corp 보안 솔루션 확대 배포",
            rtype="자사·관계사", rlevel="높음", groups=["company"],
            atype="일반 기사"
        )
        a["title"] = "SCK Corp 보안 솔루션 확대 배포"
        a["description"] = "에쓰씨케이가 기업 고객 보안 솔루션 배포를 확대했다."
        result = mon._determine_category(a)
        self.assertEqual(result, "자사·관계사")

    # ⑰ 경쟁사 기사 → 경쟁사
    def test_17_competitor_category(self):
        a = _art(
            "디모아, 신규 MDR 서비스 출시",
            rtype="경쟁사", rlevel="보통", groups=["competitor"],
            atype="보도자료형"
        )
        a["title"] = "디모아 MDR 서비스 확대"
        a["description"] = "디모아가 관리형 보안 탐지·대응 서비스를 강화했다."
        result = mon._determine_category(a)
        self.assertEqual(result, "경쟁사")


# ══════════════════════════════════════════════════════════════
# Group 3: _classify_monitoring_risk — SCK 직접 언급 요건
# ══════════════════════════════════════════════════════════════
class TestClassifyMonitoringRisk(unittest.TestCase):

    def _risk_art(self, title, desc="", atype="일반 기사"):
        return {
            "title": title,
            "description": desc,
            "article_type": atype,
            "_relevance_type": "리스크",
        }

    # ⑱ 타사 랜섬웨어 사고 → security_trend (SCK 무관)
    def test_18_third_party_ransomware_is_trend(self):
        a = self._risk_art("A병원 랜섬웨어 감염으로 환자 정보 유출")
        result = mon._classify_monitoring_risk(a)
        self.assertEqual(result, "security_trend",
            "SCK와 무관한 타사 사건은 security_trend여야 한다.")

    # ⑲ SCK 직접 언급 보안 사고 → urgent_incident
    def test_19_sck_direct_incident_is_urgent(self):
        a = self._risk_art("SCK Corp 시스템 침해 사고 발생")
        result = mon._classify_monitoring_risk(a)
        self.assertEqual(result, "urgent_incident")

    # ⑳ 보도자료형 리스크 → not_risk
    def test_20_pr_type_risk_is_not_risk(self):
        a = self._risk_art("보안 솔루션 출시 발표", atype="보도자료형")
        result = mon._classify_monitoring_risk(a)
        self.assertEqual(result, "not_risk")

    # ㉑ 분석 전망 기사 (사건 시그널 없음) → security_trend
    def test_21_trend_analysis_is_security_trend(self):
        a = self._risk_art(
            "2026년 기업 사이버 보안 위협 전망",
            "기업들이 대응해야 할 주요 보안 위협을 분석했다.")
        result = mon._classify_monitoring_risk(a)
        self.assertIn(result, ("security_trend", "not_risk"),
            "사건 시그널 없는 전망 기사는 urgent_incident가 아니어야 한다.")

    # ㉒ _relevance_type이 리스크 아님 → not_risk
    def test_22_non_risk_type_is_not_risk(self):
        a = {
            "title": "랜섬웨어 감염 피해",
            "description": "",
            "article_type": "일반 기사",
            "_relevance_type": "일반",
        }
        result = mon._classify_monitoring_risk(a)
        self.assertEqual(result, "not_risk")


# ══════════════════════════════════════════════════════════════
# Group 4: _calc_pr_value_score — 점수 분산화
# ══════════════════════════════════════════════════════════════
class TestCalcPrValueScore(unittest.TestCase):

    def _scored_art(self, category, rlevel="보통", atype="기획·분석", tier=3,
                    reasons=None, queries=None, risk_class="not_risk"):
        a = _art("테스트 기사", atype=atype, rlevel=rlevel, tier=tier)
        a["_relevance_reasons"] = reasons or []
        a["_matched_queries"] = queries or []
        a["_risk_class"] = risk_class
        return a

    # ㉓ urgent_incident → 점수 매우 높음 (90점)
    def test_23_urgent_incident_score_high(self):
        a = self._scored_art("리스크", risk_class="urgent_incident")
        score = mon._calc_pr_value_score(a, "리스크")
        self.assertGreaterEqual(score, 85)

    # ㉔ 기획기사 후보, 1등급 매체 → 80점
    def test_24_editorial_tier1_score(self):
        a = self._scored_art("기획기사 후보", rlevel="높음", tier=1)
        score = mon._calc_pr_value_score(a, "기획기사 후보")
        self.assertGreaterEqual(score, 75)

    # ㉕ 기획기사 후보, 4등급 매체, 이유 없음 → 60점 이하
    def test_25_editorial_tier4_no_reasons_lower_score(self):
        a = self._scored_art("기획기사 후보", tier=4, reasons=[])
        score = mon._calc_pr_value_score(a, "기획기사 후보")
        self.assertLessEqual(score, 65)

    # ㉖ 보도자료형 기사 → PR 점수 상한 35
    def test_26_pr_article_capped_at_35(self):
        a = self._scored_art("기획기사 후보", atype="보도자료형", rlevel="높음", tier=1)
        score = mon._calc_pr_value_score(a, "기획기사 후보")
        self.assertLessEqual(score, 35)

    # ㉗ 기획기사 후보: 이유 많을수록 점수 높아짐
    def test_27_more_reasons_higher_score(self):
        a_low  = self._scored_art("기획기사 후보", tier=2, reasons=[])
        a_high = self._scored_art("기획기사 후보", tier=2, reasons=["A", "B", "C", "D"])
        score_low  = mon._calc_pr_value_score(a_low, "기획기사 후보")
        score_high = mon._calc_pr_value_score(a_high, "기획기사 후보")
        self.assertGreater(score_high, score_low)


# ══════════════════════════════════════════════════════════════
# Group 5: _make_reason — 동적 이유 문구
# ══════════════════════════════════════════════════════════════
class TestMakeReason(unittest.TestCase):

    def _full_art(self, category, rlevel="보통", atype="기획·분석",
                  risk_class="not_risk", reasons=None, queries=None, media="테스트매체"):
        a = _art("테스트", atype=atype, rlevel=rlevel)
        a["media_name"] = media
        a["_relevance_reasons"] = reasons or []
        a["_matched_queries"] = queries or []
        a["_risk_class"] = risk_class
        return a

    # ㉘ 기획기사 후보 — matched_queries와 reasons 반영 (고정 문구 아님)
    def test_28_editorial_reason_uses_query(self):
        a = self._full_art(
            "기획기사 후보",
            reasons=["AI 보안 관련성"],
            queries=["ai_ax/AI 에이전트"]
        )
        reason = mon._make_reason(a, "기획기사 후보")
        self.assertIn("AI 에이전트", reason,
            "기획기사 후보 이유에 수집 쿼리가 반영돼야 한다.")

    # ㉙ 자사·관계사 — 고정 문구 형태 검증
    def test_29_company_reason_format(self):
        a = self._full_art("자사·관계사", rlevel="높음")
        reason = mon._make_reason(a, "자사·관계사")
        self.assertIn("SCK", reason)

    # ㉚ 리스크 urgent_incident → 긴급 표현 포함
    def test_30_urgent_incident_reason(self):
        a = self._full_art("리스크", risk_class="urgent_incident",
                           reasons=["침해 사고 키워드"])
        reason = mon._make_reason(a, "리스크", risk_class="urgent_incident")
        self.assertIn("긴급", reason)


if __name__ == "__main__":
    unittest.main(verbosity=2)
