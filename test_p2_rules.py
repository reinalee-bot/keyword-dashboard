"""
P2a~P2d 복합 PR 규칙 자동 테스트
- 규칙별 양성/음성 케이스
- 괄호·영문·혼합 기업명 에지케이스
- 기존 FP가 P2로 악화되지 않는지 확인
- 운영 데이터·CSV 미접촉 (news_fetcher 단위 함수만 테스트)
"""

import sys
import os
import unittest

_BASE = os.path.dirname(__file__)
if _BASE not in sys.path:
    sys.path.insert(0, _BASE)

import news_fetcher as nf

classify   = nf.classify_article_type
get_fired  = nf.get_compound_pr_rules_fired
check_p2a  = nf._check_p2a
check_p2b  = nf._check_p2b
check_p2c  = nf._check_p2c
check_p2d  = nf._check_p2d


# ══════════════════════════════════════════════════════════════
# P2a: 제목 시작 기업명, + 지원 + 제공
# ══════════════════════════════════════════════════════════════
class TestP2a(unittest.TestCase):

    def test_p2a_fires_on_support_provision(self):
        """기업명 시작 + 지원 + 제공 → P2a 발동"""
        title = "SGA솔루션즈, 호남 중소기업 PC 보안 지원…악성코드·패치 관리 제공"
        self.assertIn("P2a", get_fired(title))

    def test_p2a_result_is_pr_type(self):
        """P2a 발동 시 classify_article_type = 보도자료형"""
        title = "SGA솔루션즈, 호남 중소기업 PC 보안 지원…악성코드·패치 관리 제공"
        self.assertEqual(classify(title, ""), "보도자료형")

    def test_p2a_no_fire_without_provision(self):
        """지원만 있고 제공 없으면 P2a 미발동"""
        title = "SGA솔루션즈, 호남 중소기업 PC 보안 지원…악성코드 관리"
        self.assertNotIn("P2a", get_fired(title))

    def test_p2a_no_fire_without_support(self):
        """제공만 있고 지원 없으면 P2a 미발동"""
        title = "SGA솔루션즈, 호남 중소기업 PC 보안 솔루션 제공"
        self.assertNotIn("P2a", get_fired(title))

    def test_p2a_no_fire_no_company_start(self):
        """제목 시작에 기업명 없으면 P2a 미발동"""
        title = "PC 보안 지원 서비스 제공 확대"
        self.assertNotIn("P2a", get_fired(title))

    def test_p2a_bracket_company_name(self):
        """괄호 포함 기업명 + 지원 + 제공 → P2a 발동"""
        title = "에이비씨(ABC), 중소기업 클라우드 전환 지원 서비스 제공"
        self.assertIn("P2a", get_fired(title))

    def test_p2a_english_company_name(self):
        """영문 기업명 + 지원 + 제공 → P2a 발동"""
        title = "CloudSecure, 소기업 보안 솔루션 무상 지원 및 점검 서비스 제공"
        self.assertIn("P2a", get_fired(title))

    def test_p2a_no_fire_single_char_company(self):
        """1자리 기업명(A,) → P2a 미발동 (최소 2자 요건)"""
        title = "A, 중소기업 보안 지원 서비스 제공"
        self.assertNotIn("P2a", get_fired(title))

    def test_p2a_feature_article_not_fp(self):
        """기획·분석 기사에서 P2a FP 미발생"""
        title = "[전문가 기고] 중소기업 IT 지원 정책 변화와 공급 생태계 제공 방향"
        result = classify(title, "")
        # 칼럼 마커 → 기획·분석, P2a 규칙 실행 전 반환됨
        self.assertEqual(result, "기획·분석")


# ══════════════════════════════════════════════════════════════
# P2b: 제목 시작 기업·기관명, + 개최 + 회차/따옴표
# ══════════════════════════════════════════════════════════════
class TestP2b(unittest.TestCase):

    def test_p2b_fires_with_ordinal(self):
        """기관명 + 개최 + 제N차 회차 → P2b 발동"""
        title = "중기중앙회, '2026년 제1차 식품산업위원회' 개최"
        self.assertIn("P2b", get_fired(title))

    def test_p2b_fires_with_quote(self):
        """기관명 + 개최 + 따옴표 행사명 → P2b 발동"""
        title = "한국ICT협회, '2026 AI 혁신 컨퍼런스' 개최"
        self.assertIn("P2b", get_fired(title))

    def test_p2b_result_is_pr_type(self):
        """P2b 발동 시 classify = 보도자료형"""
        title = "중기중앙회, '2026년 제1차 식품산업위원회' 개최"
        self.assertEqual(classify(title, ""), "보도자료형")

    def test_p2b_no_fire_without_event_marker(self):
        """개최 없으면 P2b 미발동"""
        title = "중기중앙회, 제1차 식품산업위원회 발표"
        self.assertNotIn("P2b", get_fired(title))

    def test_p2b_no_fire_without_company_start(self):
        """기관명이 제목 시작이 아니면 P2b 미발동"""
        title = "2026년 제1차 AI 컨퍼런스 중기중앙회 개최"
        self.assertNotIn("P2b", get_fired(title))

    def test_p2b_no_fire_without_quote_or_ordinal(self):
        """개최는 있지만 따옴표·회차 없으면 P2b 미발동"""
        title = "중기중앙회, 식품산업위원회 정기회의 개최"
        self.assertNotIn("P2b", get_fired(title))

    def test_p2b_fires_n_stage(self):
        """N단계 회차 표현 + 개최 → P2b 발동"""
        title = "한국IT산업협회, 2단계 AI 교육 프로그램 개최"
        self.assertIn("P2b", get_fired(title))

    def test_p2b_mixed_english_korean_company(self):
        """영한 혼합 기관명 + 개최 + 회차 → P2b 발동"""
        title = "KDI한국개발연구원, '2026 AI 일자리 포럼' 개최"
        self.assertIn("P2b", get_fired(title))

    def test_p2b_analysis_article_not_fp(self):
        """기획·분석 마커 있는 기사에서 P2b FP 미발생"""
        title = "[사례연구] 중기중앙회 제1차 행사 개최 결과 분석"
        result = classify(title, "")
        self.assertEqual(result, "기획·분석")


# ══════════════════════════════════════════════════════════════
# P2c: N종 + 공개 (미공개 제외) + 전략·방안 등 제외
# ══════════════════════════════════════════════════════════════
class TestP2c(unittest.TestCase):

    def test_p2c_fires_n_types_reveal(self):
        """N종 + 공개 → P2c 발동"""
        title = "고성능 '프로' 대신 효율… 구글, '제미나이 플래시' 3종 공개"
        self.assertIn("P2c", get_fired(title))

    def test_p2c_result_is_pr_type(self):
        """P2c 발동 시 classify = 보도자료형"""
        title = "고성능 '프로' 대신 효율… 구글, '제미나이 플래시' 3종 공개"
        self.assertEqual(classify(title, ""), "보도자료형")

    def test_p2c_excluded_by_strategy(self):
        """전략 포함 → P2c 미발동"""
        title = "구글, AI 모델 3종 공개 전략 발표"
        self.assertNotIn("P2c", get_fired(title))

    def test_p2c_excluded_by_without(self):
        """없이 포함 → P2c 미발동"""
        title = "구글, '프로' 없이 '플래시' 3종 공개"
        self.assertNotIn("P2c", get_fired(title))

    def test_p2c_excluded_by_plan(self):
        """방안 포함 → P2c 미발동"""
        title = "정부, AI 규제 3단계 공개 방안 마련"
        self.assertNotIn("P2c", get_fired(title))

    def test_p2c_no_fire_without_reveal(self):
        """N종 있지만 공개 없으면 P2c 미발동"""
        title = "삼성, 갤럭시 3종 출시 예정"
        self.assertNotIn("P2c", get_fired(title))

    def test_p2c_migongae_not_trigger(self):
        """미공개는 공개로 보지 않음 — P2c 미발동"""
        title = "구글, 제미나이 경량모델 3종 출시···'프로'는 미공개"
        self.assertNotIn("P2c", get_fired(title))

    def test_p2c_excluded_by_analysis(self):
        """분석 포함 → P2c 미발동"""
        title = "정부, AI 법안 3종 공개 배경 분석"
        self.assertNotIn("P2c", get_fired(title))

    def test_p2c_n_stage_reveal(self):
        """제N차 + 공개 → P2c 발동"""
        title = "과기부, 디지털 혁신 제2차 지원 대상 공개"
        self.assertIn("P2c", get_fired(title))


# ══════════════════════════════════════════════════════════════
# P2d: 제목 중간 기업명+쉼표 + 따옴표 제품명 + 말미 출시
# ══════════════════════════════════════════════════════════════
class TestP2d(unittest.TestCase):

    def test_p2d_fires_mid_company_quote_launch(self):
        """중간 기업명+쉼표 + 따옴표 제품명 + 말미 출시 → P2d 발동"""
        title = "AI가 캠페인 기획·발송까지… 인비토, '한국형 Braze' 한줄로AI 출시"
        self.assertIn("P2d", get_fired(title))

    def test_p2d_result_is_pr_type(self):
        """P2d 발동 시 classify = 보도자료형"""
        title = "AI가 캠페인 기획·발송까지… 인비토, '한국형 Braze' 한줄로AI 출시"
        self.assertEqual(classify(title, ""), "보도자료형")

    def test_p2d_no_fire_without_launch_at_end(self):
        """출시가 말미(12자 내)에 없으면 P2d 미발동"""
        title = "인비토, '한줄로AI' 출시 예정…연내 베타 서비스 확장 계획"
        self.assertNotIn("P2d", get_fired(title))

    def test_p2d_no_fire_without_quote(self):
        """따옴표 제품명 없으면 P2d 미발동"""
        title = "인비토, 한줄로AI 마케팅 자동화 솔루션 출시"
        self.assertNotIn("P2d", get_fired(title))

    def test_p2d_no_fire_without_company_comma(self):
        """기업명+쉼표 없으면 P2d 미발동"""
        title = "'한줄로AI' 마케팅 솔루션 출시"
        self.assertNotIn("P2d", get_fired(title))

    def test_p2d_no_fire_when_launch_in_middle(self):
        """출시가 제목 중간에만 있고 말미에 없으면 P2d 미발동"""
        title = "구글, 제미나이 '프로' 없이 '플래시' 모델들만 출시...'가성비' 전략"
        self.assertNotIn("P2d", get_fired(title))

    def test_p2d_fires_with_double_quote(self):
        """쌍따옴표 제품명 + 말미 출시 → P2d 발동"""
        title = "스타트업 넥스트AI, \"AI 자동화 플랫폼\" 정식 출시"
        self.assertIn("P2d", get_fired(title))

    def test_p2d_no_fire_general_article(self):
        """일반 보도 기사 형태에서 P2d FP 미발생"""
        title = "삼성전자, 대표 직속 'RX사업추진실' 출범...세계 최고 '로봇 손' 탄생"
        self.assertNotIn("P2d", get_fired(title))


# ══════════════════════════════════════════════════════════════
# 기존 FP 비악화 확인
# ══════════════════════════════════════════════════════════════
class TestNoNewFP(unittest.TestCase):

    def test_no22_not_pr_from_p2(self):
        """#22 [보안 칼럼] 기사 — P2 규칙이 보도자료형으로 오분류하지 않음"""
        title = "[보안 칼럼] AI를 빠르게 도입할수록, 아무것도 믿지 말아야 하는 이유"
        # 칼럼 마커 → 기획·분석 (P2 규칙 실행 전 조기 반환)
        self.assertEqual(classify(title, ""), "기획·분석")
        # P2 규칙 자체도 미발동 확인
        self.assertEqual(get_fired(title), set())

    def test_strategy_article_not_p2c_fp(self):
        """전략 기사 — P2c 제외어로 FP 미발생"""
        title = "구글, 제미나이 '프로' 없이 '플래시' 모델들만 출시...'가성비' 전략"
        self.assertNotIn("P2c", get_fired(title))

    def test_general_news_no_p2_fp(self):
        """일반 기사 — P2 규칙 모두 미발동"""
        title = "AI로 10년 뒤 일자리 25.6만 개 감소…KDI 전문직 사무직 영향"
        fired = get_fired(title)
        self.assertEqual(fired, set(), f"일반 기사에서 P2 발동됨: {fired}")

    def test_interview_no_p2_fp(self):
        """인터뷰 기사 — P2 규칙 미발동"""
        title = 'KDI "AI 확산 10년 뒤 일자리 25.6만개 감소…생산성은 향상"'
        fired = get_fired(title)
        self.assertEqual(fired, set(), f"인터뷰 기사에서 P2 발동됨: {fired}")

    def test_event_article_no_p2a_fp(self):
        """행사 기사 — P2a 미발동"""
        title = "'K-디스플레이 2026' 개막…삼성·LG 총출동, AI 품은 OLED 한곳에"
        self.assertNotIn("P2a", get_fired(title))

    def test_analysis_no_p2_fp(self):
        """기획·분석 기사 — P2 발동해도 분류 결과는 기획·분석 유지"""
        title = "[보안 칼럼] 외교부 해킹이 드러낸 국가 보안의 민낯"
        self.assertEqual(classify(title, ""), "기획·분석")

    def test_p2c_exclusion_words_prevent_fp(self):
        """P2c 제외어(전략·없이·방안·계획·전망·해설) — FP 방지"""
        exclusion_cases = [
            "정부, AI 규제 3종 공개 전략 발표",
            "구글, AI 모델 3종 없이 공개 방침",
            "금융위, 핀테크 3단계 공개 방안 마련",
            "과기부, 디지털 혁신 3단계 공개 계획 확정",
            "연구원, AI 일자리 3종 공개 전망 발표",
            "IT협회, 사이버보안 3단계 공개 해설 강좌",
        ]
        for t in exclusion_cases:
            with self.subTest(title=t):
                self.assertNotIn("P2c", get_fired(t),
                    f"제외어 포함 제목에서 P2c 오발동: {t}")


# ══════════════════════════════════════════════════════════════
# get_compound_pr_rules_fired 공개 함수
# ══════════════════════════════════════════════════════════════
class TestGetCompoundRulesFired(unittest.TestCase):

    def test_returns_empty_set_for_plain_news(self):
        """일반 뉴스 → 빈 집합 반환"""
        title = "AI 에이전트 시장 동향 전망 보고서"
        self.assertEqual(get_fired(title), set())

    def test_returns_set_with_rule_name(self):
        """P2c 발동 → {'P2c'} 반환"""
        title = "오라클, 클라우드 AI 서비스 3종 공개"
        result = get_fired(title)
        self.assertIn("P2c", result)

    def test_multiple_rules_can_fire(self):
        """여러 규칙 동시 발동 가능"""
        # P2a (지원+제공) + P2c (N종+공개) 조합
        title = "ABC솔루션, AI 보안 솔루션 3종 공개 및 중소기업 지원 서비스 제공"
        result = get_fired(title)
        self.assertGreaterEqual(len(result), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
