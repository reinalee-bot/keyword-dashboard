"""
SCK 관련성 판정 회귀 테스트 (16개)
실행: python test_relevance.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# lru_cache 초기화 (재로드 없이 YAML 변경 반영)
import relevance_scorer as rs
rs._load_config.cache_clear()

from relevance_scorer import score_relevance

PASS = "[PASS]"
FAIL = "[FAIL]"

cases = [
    # ── 오탐 수정 (낮음이어야 함) ─────────────────────────────────────────
    {
        "id": 1,
        "name": "한국예탁결제원 차세대시스템",
        "title": "한국예탁결제원, 차세대 결제시스템 클라우드 전환 본격화",
        "desc": "한국예탁결제원이 차세대 결제시스템을 클라우드 기반으로 전환한다. 시스템 안정성과 장애 복구 속도를 높이기 위한 인프라 전환 프로젝트로, 금융결제원과 협력해 추진한다.",
        "query": "AI",
        "expect_level": "낮음",
        "expect_max_score": 34,
    },
    {
        "id": 2,
        "name": "청주시 적극행정 우수공무원",
        "title": "청주시, 생성형AI 활용 적극행정 우수공무원 선발",
        "desc": "청주시는 생성형AI를 활용한 행정 혁신으로 성과를 낸 공무원 5명을 우수공무원으로 선발하고 예산을 지원한다. 장애인 직업재활 분야에도 AI가 도입됐다.",
        "query": "AI",
        "expect_level": "낮음",
        "expect_max_score": 34,
    },
    {
        "id": 3,
        "name": "중소기업계 총리 오찬 간담회",
        "title": "중소기업계, 총리와 오찬 간담회 개최… AI 규제 완화 건의",
        "desc": "중소기업중앙회가 총리와 오찬 간담회를 열고 AI 규제 완화를 건의했다. 소상공인 지원 예산 증액도 논의됐다.",
        "query": "AI",
        "expect_level": "낮음",
        "expect_max_score": 34,
    },
    {
        "id": 4,
        "name": "어선원보험 전자청구 도입",
        "title": "수협, 어선원보험 전자청구 시스템 도입으로 디지털전환 가속",
        "desc": "수협중앙회가 어선원보험 청구를 전자화해 디지털전환을 추진한다. 민원 처리 속도 개선과 비용 절감이 기대된다.",
        "query": "AX",
        "expect_level": "낮음",
        "expect_max_score": 34,
    },
    {
        "id": 5,
        "name": "RSA 기사 Microsoft 단순 언급",
        "title": "RSA 컨퍼런스 2026, 패스워드리스 인증 확산 주목",
        "desc": "올해 RSA 컨퍼런스에서 패스워드리스 인증이 핵심 주제로 떠올랐다. Microsoft, Google 등이 FIDO2 기반 보안 강화를 발표했다.",
        "query": "Microsoft",
        "expect_level": "낮음",
        "expect_max_score": 34,
    },
    {
        "id": 6,
        "name": "ESG·AX·DX 장애인직업재활 기사",
        "title": "AX·DX 시대, ESG 경영과 장애인직업재활 연계 사례 증가",
        "desc": "기업들이 AX(AI 전환)와 DX(디지털 전환) 추진 과정에서 ESG 경영의 일환으로 장애인직업재활 프로그램을 운영하는 사례가 늘고 있다.",
        "query": "AX",
        "expect_level": "낮음",
        "expect_max_score": 34,
    },
    {
        "id": 7,
        "name": "옴니사 윈도우 서버 출시",
        "title": "옴니사, Windows Server 2026 기반 스토리지 솔루션 출시",
        "desc": "옴니사가 Microsoft Windows Server 2026을 기반으로 한 신규 스토리지 솔루션을 출시했다. 비용 절감 효과가 기대된다고 밝혔다.",
        "query": "Microsoft",
        "expect_level": "낮음",
        "expect_max_score": 34,
    },
    {
        "id": 8,
        "name": "삼성 갤럭시 XR Adobe 단순 언급",
        "title": "삼성전자, 갤럭시 XR 헤드셋 공개… 몰입형 콘텐츠 생태계 구축",
        "desc": "삼성전자가 갤럭시 XR 헤드셋을 공개하며 몰입형 콘텐츠 시장에 진출했다. Adobe Aero, ROI 측면에서 크리에이터 생태계와의 연계가 주목된다.",
        "query": "Adobe",
        "expect_level": "낮음",
        "expect_max_score": 34,
    },

    # ── 누락 수정 (보통 이상이어야 함) ──────────────────────────────────────
    {
        "id": 9,
        "name": "최태원 제조업 AI",
        "title": "최태원 SK 회장 '제조업에 AI 전환이 기업 경쟁력의 핵심'",
        "desc": "최태원 SK그룹 회장은 기업의 AI 전환(AX)이 제조업 경쟁력을 좌우한다며 기업AI 도입 사례를 공유했다. 기업 AI 투자와 비용 효율화가 주요 의제였다.",
        "query": "AX",
        "expect_level_not": "낮음",
        "expect_min_score": 35,
    },
    {
        "id": 10,
        "name": "삼성SDS NPUaaS 출시",
        "title": "삼성SDS, AI 추론 NPUaaS 서비스 출시… 기업 AI 인프라 확대",
        "desc": "삼성SDS가 기업 대상 NPUaaS(신경망처리장치 서비스)를 출시했다. 기업 AI 도입 사례를 확대하고 클라우드 기반 AI 인프라를 제공한다.",
        "query": "AI",
        "expect_level_not": "낮음",
        "expect_min_score": 35,
    },
    {
        "id": 11,
        "name": "KTL 제조기업 AX 경쟁력",
        "title": "KTL, 제조기업 AX(AI 전환) 경쟁력 강화 지원 사업 본격화",
        "desc": "한국산업기술시험원(KTL)이 제조 중소기업의 AI 전환(AX)을 지원하는 사업을 시작했다. 기업 AI 도입 사례 확산과 업무 효율 향상이 목표다.",
        "query": "AX",
        "expect_level_not": "낮음",
        "expect_min_score": 35,
    },
    {
        "id": 12,
        "name": "SAP코리아 자율형 기업 AI",
        "title": "SAP코리아, 자율형 기업 AI 에이전트 솔루션 공개",
        "desc": "SAP코리아가 ERP 기반의 자율형 기업 AI 에이전트를 공개했다. 도입 사례와 라이선스 비용 체계도 함께 발표했다.",
        "query": "AI",
        "expect_level_not": "낮음",
        "expect_min_score": 35,
    },

    # ── 정상 높음 유지 ───────────────────────────────────────────────────
    {
        "id": 13,
        "name": "Microsoft 라이선스·총판",
        "title": "마이크로소프트, 국내 총판 라이선스 체계 개편 발표",
        "desc": "마이크로소프트(Microsoft)가 국내 총판과 파트너를 대상으로 M365 라이선스 체계를 개편한다. 기업 고객 비용 절감과 IT 예산 효율화가 주요 골자다.",
        "query": "Microsoft",
        "expect_level": "높음",
        "expect_min_score": 65,
    },
    {
        "id": 14,
        "name": "Microsoft 보안 정책·인증서 탈취",
        "title": "마이크로소프트, 보안 정책 강화… 인증서 탈취 공격 대응 방안 발표",
        "desc": "Microsoft가 최근 증가하는 인증서 탈취 해킹 공격에 대응해 보안 정책을 강화했다. 컴플라이언스 요구사항과 기업 보안 투자 가이드도 공개했다.",
        "query": "Microsoft",
        "expect_level": "높음",
        "expect_min_score": 65,
    },
    {
        "id": 15,
        "name": "디모아 제목 사업·행사 당사자",
        "title": "디모아, 2026 상반기 파트너 데이 개최… 신규 사업 발표",
        "desc": "디모아가 2026 상반기 파트너 데이를 개최하고 신규 마케팅 솔루션과 총판 파트너십 계획을 발표했다.",
        "query": "디모아",
        "expect_level": "높음",
        "expect_min_score": 65,
    },
    {
        "id": 16,
        "name": "디모아 본문 참석사 목록만",
        "title": "2026 마케테크 서밋, 국내 주요 마테크 기업 총출동",
        "desc": "2026 마케테크 서밋에 디모아, 카카오비즈니스, 메조미디어, 이노션, 덴츠 등 국내외 주요 마케팅 테크 기업이 참석했다.",
        "query": "디모아",
        "expect_level": "낮음",
        "expect_max_score": 34,
    },

    # ── 신규 T17~T23 ──────────────────────────────────────────────────────
    {
        "id": 17,
        "name": "AX 제목 독립 단어 + 제조기업 문맥 → 보통 이상",
        "title": "KTL, 산업 AI 국제인증으로 제조기업 AX 경쟁력 강화 지원",
        "desc": "한국산업기술시험원(KTL)이 산업 AI 국제인증 체계를 통해 제조기업의 AX(AI 전환) 경쟁력 강화를 지원한다. 도입 사례 컨설팅과 라이선스 비용 가이드도 제공한다.",
        "query": "AX",
        "expect_level_not": "낮음",
        "expect_min_score": 35,
    },
    {
        "id": 18,
        "name": "TAX/MAX만 존재 → AX로 인식 안 함",
        "title": "소득세(Income TAX)·법인세 제도 개편 논의",
        "desc": "국세청이 소득세와 법인세 제도를 개편한다. 세수 확보와 TAX 부담 형평성이 핵심이다.",
        "query": "AX",
        "expect_level": "낮음",
        "expect_max_score": 20,
    },
    {
        "id": 19,
        "name": "AX desc 단순 언급 → 낮음",
        "title": "삼성전자 폴더블폰 신제품 발표",
        "desc": "삼성전자가 AI와 AX 기술을 적용한 폴더블폰을 출시했다.",
        "query": "AX",
        "expect_level": "낮음",
        "expect_max_score": 34,
    },
    {
        "id": 20,
        "name": "RSA+Microsoft Entra 통합 (Microsoft query) → 최대 30점",
        "title": "RSA, AI 도입 기업 위한 패스워드리스 인증 솔루션 발표",
        "desc": "RSA ID Plus와 Microsoft Entra를 통합하면 IT 사용자를 위한 다중 인증(MFA)을 지원할 수 있다. 보안 정책 준수와 컴플라이언스 요구사항을 충족한다.",
        "query": "Microsoft",
        "expect_level": "낮음",
        "expect_max_score": 30,
    },
    {
        "id": 21,
        "name": "Microsoft Entra 정책 변경 (Microsoft 주체) → 높음",
        "title": "마이크로소프트, Entra 보안 정책 변경 및 파트너 가이드라인 발표",
        "desc": "Microsoft가 Entra 보안 정책을 강화하고 파트너 라이선스 가이드라인을 개편했다. 기업 컴플라이언스 준수와 IT 예산 계획에 영향을 준다.",
        "query": "Microsoft",
        "expect_level": "높음",
        "expect_min_score": 65,
    },
    {
        "id": 22,
        "name": "순수 영어 기사 → 외국어 플래그 + 낮음",
        "title": "Microsoft announces new AI features for enterprise customers",
        "desc": "Microsoft has unveiled new AI-powered features targeting enterprise productivity, including advanced Copilot integrations.",
        "query": "Microsoft",
        "expect_level": "낮음",
        "expect_max_score": 10,
        "expect_foreign": True,
    },
    {
        "id": 23,
        "name": "영문 제품명 포함 한국어 기사 → 외국어 제외 안 함",
        "title": "마이크로소프트 Teams 활용한 기업 업무 협업 솔루션 M365 도입 사례 발표",
        "desc": "마이크로소프트가 기업 고객을 대상으로 Teams와 M365 라이선스 도입 사례를 발표했다. 국내 총판 파트너십 확대도 함께 공개했다.",
        "query": "Microsoft",
        "expect_foreign": False,
        "expect_level": "높음",
        "expect_min_score": 65,
    },
]

passed = 0
failed = 0

print("=" * 72)
print("SCK 관련성 판정 회귀 테스트")
print("=" * 72)

for c in cases:
    result = score_relevance(c["title"], c["desc"], query_keyword=c.get("query"))
    level = result["_relevance_level"]
    score = result["_relevance_score"]
    reasons = result.get("_relevance_reasons", [])

    ok = True
    fail_msg = ""

    if "expect_level" in c:
        if level != c["expect_level"]:
            ok = False
            fail_msg = f"레벨 {level} (기대: {c['expect_level']})"
    if "expect_level_not" in c:
        if level == c["expect_level_not"]:
            ok = False
            fail_msg = f"레벨이 {level}이면 안 됨 (기대: {c['expect_level_not']} 아님)"
    if "expect_max_score" in c and score > c["expect_max_score"]:
        ok = False
        fail_msg += f" 점수 {score} > 상한 {c['expect_max_score']}"
    if "expect_min_score" in c and score < c["expect_min_score"]:
        ok = False
        fail_msg += f" 점수 {score} < 하한 {c['expect_min_score']}"
    if "expect_foreign" in c:
        actual_foreign = result.get("_foreign_language", False)
        if actual_foreign != c["expect_foreign"]:
            ok = False
            fail_msg += f" _foreign_language={actual_foreign} (기대: {c['expect_foreign']})"

    status = PASS if ok else FAIL
    if ok:
        passed += 1
    else:
        failed += 1

    reason_str = " / ".join(reasons[:2]) if reasons else result.get("_low_relevance_reason", "")
    print(f"{status} [{c['id']:02d}] {c['name']}")
    print(f"       점수={score:3d}  레벨={level}  유형={result['_relevance_type']}")
    print(f"       근거: {reason_str}")
    if not ok:
        print(f"       >> {fail_msg}")
    print()

print("=" * 72)
print(f"결과: {passed}/{len(cases)} PASS,  {failed} FAIL")
print("=" * 72)

if failed > 0:
    sys.exit(1)
