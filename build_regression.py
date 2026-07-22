"""
회귀 세트 생성 스크립트 (build_regression.py)

입력 : regression_collected.json  (Naver API 실제 수집 데이터, 2026-07-19~22)
출력 : regression_set.csv         (기대값·라벨 포함 평가표)

※ regression_collected.json 에는 description 필드가 없습니다.
   따라서 현재 분류기를 title-only 로 재평가합니다.
   제목 기반 시그널(강한 PR 신호어, 칼럼 마커, 따옴표 인터뷰, 행사어)은 정상 동작하지만,
   description 의존 pr_score 는 과소평가될 수 있으므로 이 결과를 "45건 회귀 기준" 으로만
   사용하고, "운영 검증 완료"로 보지 마십시오.

라벨링 절차
  1. 제목·출처·날짜를 보고 기사 유형을 1인 판단으로 결정
  2. 아래 EXPECTED_MAP에 (기대 유형, 기대 카테고리, 클러스터, 라벨 이유)를 기록
  3. 이 스크립트를 실행하면 regression_set.csv 가 재생성됨

유형 판정 기준
  보도자료형 — 기업·기관이 자사 제품/서비스/행사/수상/계약을 발표하는 기사.
               제목 또는 내용에 "출시", "체결", "수상", "론칭", "선봬", "선정" 등이 있거나
               기업명 + 행동어 구조의 단편 알림성 기사. [신간]/[출간] 브래킷도 포함.
  기획·분석  — 전문가 분석, 칼럼, 사례연구, 심층 진단.
               [칼럼], [기고], [사례연구], [보안 칼럼] 등 편집 마커가 있거나,
               복수 출처·데이터·원인 설명 구조.
  인터뷰     — 특정 인물 발언이 기사의 핵심 콘텐츠.
               제목에 따옴표+발언 또는 "만나다·말했다·강조했다" 등 직화법 패턴.
  행사·현장  — 전시회, 세미나, 컨퍼런스 개막·현장 보도.
               제목에 행사명 + "개막", "총출동", "현장" 등.
  일반 기사  — 위 어느 것에도 해당하지 않는 사실 전달형 뉴스.
               정책, 시장 동향, 기업 전략, 사건·사고 보도.

동일 발표 클러스터 표시
  cluster 필드: 동일 발표·보고서를 다른 매체가 보도한 묶음.
               분류기 평가에 두 건 모두 포함하되,
               recall 계산 시 클러스터 내 오류가 반복될 경우 가중치 참고 가능.
  현재 클러스터:
    cluster_inaims_procurement : 인엠스 VPN 조달등록 (#31 THEPOWERNEWS, #32 E2NEWS)
    cluster_kdi_ai_employment  : KDI AI 고용 보고서 (#38 서울경제, #40 비욘드포스트,
                                  #41 이코노빌, #42 YTN, #44 TJB)
"""

import csv
import importlib.util
import json
import os
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# ──────────────────────────────────────────────────────────────────────────────
# 분류기 동적 로드 (keyword-dashboard/news_fetcher.py)
# ──────────────────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _load_classifier():
    spec = importlib.util.spec_from_file_location(
        "news_fetcher",
        os.path.join(BASE_DIR, "news_fetcher.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
        return getattr(mod, "classify_article_type", None)
    except Exception as e:
        print(f"[경고] news_fetcher.py 로드 실패: {e}", file=sys.stderr)
        return None


_classify = _load_classifier()


def classify(title: str, description: str = "") -> str:
    if _classify:
        return _classify(title, description)
    return "(분류기 로드 실패)"


# ──────────────────────────────────────────────────────────────────────────────
# 기대값 정의 (human label)
# idx = JSON 배열 0-index = article_number - 1
# ──────────────────────────────────────────────────────────────────────────────
EXPECTED_MAP = {
    0:  ("보도자료형", "AI·AX 시장동향", "",
         "니어솔루션 '3년 연속 수상' 알림. 수상·기업 행사 발표 = 보도자료형."),
    1:  ("인터뷰", "AI·AX 시장동향", "",
         "ARC리서치 애널리스트가 나무기술 주가에 코멘트. 특정인 발언 중심 = 인터뷰."),
    2:  ("일반 기사", "AI·AX 시장동향", "",
         "삼성전자 RX사업추진실 출범. 조직 개편 사실 전달 = 일반 기사."),
    3:  ("보도자료형", "AI·AX 시장동향", "",
         "구글 제미나이 플래시 3종 공개 발표. 신규 모델 라인업 출시 = 보도자료형."),
    4:  ("일반 기사", "AI·AX 시장동향", "",
         "구글 플래시 전략 해석 후속 기사. 제품 발표 자체가 아닌 전략 각도 = 일반 기사."),
    5:  ("보도자료형", "AI·AX 시장동향", "",
         "[신간] 브래킷 + 박사 신간 발간. 출판사·저자 PR = 보도자료형."),
    6:  ("보도자료형", "AI·AX 시장동향", "",
         "웹케시 IBK 공급계약 체결. '공급계약' = 강한 PR 신호."),
    7:  ("기획·분석", "리스크", "",
         "[박나룡 보안칼럼] 편집 마커. 외교부 해킹 분석 칼럼 = 기획·분석."),
    8:  ("인터뷰", "클라우드·보안", "",
         "'늘 같은 곳을 노린다' 보안 전문가 발언 중심 = 인터뷰."),
    9:  ("인터뷰", "클라우드·보안", "",
         "KISA '공격 동선 따라 보안체계를' 발언 중심. #09와 동일 매체(TECHM) 다른 기사."),
    10: ("일반 기사", "리스크", "",
         "AI 에이전트 상호 공격 신세대 기법. 특정인 발언 없이 기술 트렌드 보도 = 일반 기사."),
    11: ("보도자료형", "클라우드·보안", "",
         "SGA솔루션즈 호남 중소기업 PC보안 지원 발표. 기업 CSR/서비스 발표 = 보도자료형. "
         "강한 PR 시그널 단어 없어 분류기 미탐지 가능."),
    12: ("일반 기사", "리스크", "",
         "허깅페이스 자율 AI 에이전트 공격 피해. 외부 사건 전달 = 일반 기사."),
    13: ("기획·분석", "클라우드·보안", "",
         "[사례연구] 편집 마커. 금융 A사 MDR 도입 사례 분석 = 기획·분석."),
    14: ("보도자료형", "AI·AX 시장동향", "",
         "한국타이어 '티봇' 론칭 프로모션. '론칭 프로모션' = 강한 PR 신호."),
    15: ("일반 기사", "AI·AX 시장동향", "",
         "충주시 피지컬AI 생태계 조성 정책. 지자체 정책 발표 = 일반 기사."),
    16: ("일반 기사", "AI·AX 시장동향", "",
         "카카오엔터프라이즈 신임 대표 내정. 임원 인사 사실 전달 = 일반 기사."),
    17: ("인터뷰", "AI·AX 시장동향", "",
         "윤진식 회장 '美 비자 개선 계속 건의' 발언 중심. 제목에 따옴표+발언 = 인터뷰."),
    18: ("인터뷰", "AI·AX 시장동향", "",
         "윤진식 회장 '美 비자·AX 지원 강화' 발언 중심. #18과 동일 사건 이투데이 보도 = 인터뷰."),
    19: ("보도자료형", "AI·AX 시장동향", "",
         "중기중앙회 식품산업위원회 개최 알림. 기관 주도 행사 개최 발표 = 보도자료형."),
    20: ("행사·현장", "AI·AX 시장동향", "",
         "K-디스플레이 2026 개막·삼성LG 총출동. '총출동' = 행사·현장 신호."),
    21: ("인터뷰", "AI·AX 시장동향", "",
         "삼성디스플레이 임원 엔비디아 협력 비전 발언. 제목에 따옴표+발언 = 인터뷰."),
    22: ("기획·분석", "리스크", "",
         "[보안 칼럼] 편집 마커. AI 도입과 제로트러스트 분석 칼럼 = 기획·분석."),
    23: ("인터뷰", "리스크", "",
         "구글 사이버보안 전용 모델 출시 '가성비 대안' 발언. 따옴표 인용 중심 = 인터뷰."),
    24: ("보도자료형", "클라우드·보안", "",
         "아이티언 '인그레스 투 엔지에프' 선봬. '선봬' = 강한 PR 신호."),
    25: ("일반 기사", "클라우드·보안", "",
         "AI스페라 PCI DSS 4년 연속 인증 유지. 인증 갱신(유지)은 PR 신호 아님 = 일반 기사."),
    26: ("보도자료형", "클라우드·보안", "",
         "구글 제미나이 경량모델 3종 출시. 신규 모델 라인업 발표 = 보도자료형."),
    27: ("일반 기사", "클라우드·보안", "",
         "휴네시온 N2SF·SBOM 사업 참여. 사업 참여 사실 전달 = 일반 기사."),
    28: ("인터뷰", "클라우드·보안", "",
         "[Global Security TOP 100] 이동범 지니언스 대표 수상 소감·비전 발언 = 인터뷰."),
    29: ("보도자료형", "클라우드·보안", "",
         "클루커스·Straiker 전략적 파트너십 체결. '전략적 파트너십' = 강한 PR 신호."),
    30: ("인터뷰", "주요 벤더", "cluster_inaims_procurement",
         "인엠스 조달청 등록. 김승태 부사장 발언 포함 = 인터뷰. "
         "#32 E2NEWS 와 동일 사건 다른 매체·다른 구성."),
    31: ("보도자료형", "주요 벤더", "cluster_inaims_procurement",
         "인엠스 조달등록 완료 알림. 발표 단편 구성 = 보도자료형. "
         "#31 THEPOWERNEWS 와 동일 사건 다른 매체."),
    32: ("일반 기사", "리스크", "",
         "RSA 패스워드리스 인증 솔루션 제안 보도. 보안 솔루션 전략 = 일반 기사."),
    33: ("일반 기사", "AI·AX 시장동향", "",
         "KT 18조 투자·AX 플랫폼 기업 전환 전략 보도 = 일반 기사."),
    34: ("일반 기사", "리스크", "",
         "RSA AI 업무 환경 보안 솔루션 제안 보도 = 일반 기사."),
    35: ("일반 기사", "클라우드·보안", "",
         "시큐리티플랫폼 제로트러스트 영상보안 공공시장 진출 전략 = 일반 기사."),
    36: ("일반 기사", "AI·AX 시장동향", "",
         "SKT 정재헌 CEO AI 전환 전략 기사. 전략 보도, 인터뷰 구조 아님 = 일반 기사."),
    37: ("인터뷰", "AI·AX 시장동향", "cluster_kdi_ai_employment",
         "KDI '10년 후 일자리 25.6만 개 감소' 발언 중심. 동일 보고서 클러스터."),
    38: ("일반 기사", "AI·AX 시장동향", "",
         "HD현대 AI 전략 가속 보도. 별도 기업 전략 기사 = 일반 기사."),
    39: ("인터뷰", "AI·AX 시장동향", "cluster_kdi_ai_employment",
         "KDI 보고서 '10년 후 25만개 이상 감소' 발언 중심. 동일 보고서 클러스터."),
    40: ("인터뷰", "AI·AX 시장동향", "cluster_kdi_ai_employment",
         "김용범 'AI는 기본권' 발언. KDI 보고서 발표 이후 정치인 반응 인터뷰. 동일 뉴스 사이클."),
    41: ("인터뷰", "AI·AX 시장동향", "cluster_kdi_ai_employment",
         "KDI 'AI로 일자리 25.6만 개 감소' YTN 보도. 동일 보고서 클러스터."),
    42: ("보도자료형", "AI·AX 시장동향", "",
         "인비토 '한줄로AI' 출시 홍보. 신규 서비스 출시 알림 = 보도자료형. "
         "'출시' 단독 미탐지 가능성 있어 A+B+C 복합 규칙 대상."),
    43: ("인터뷰", "AI·AX 시장동향", "cluster_kdi_ai_employment",
         "KDI 'AI 확산 10년 뒤 25.6만 개 감소' TJB 보도. 동일 보고서 클러스터."),
    44: ("일반 기사", "AI·AX 시장동향", "",
         "미래에셋생명 '공덕시대 개막'. '개막'은 비유적 표현, 행사 아님 = 일반 기사."),
}


# ──────────────────────────────────────────────────────────────────────────────
# URL 정규화 (중복 검사용)
# ──────────────────────────────────────────────────────────────────────────────
def normalize_url(url: str) -> str:
    from urllib.parse import urlparse, urlencode, parse_qs, urlunparse
    try:
        p = urlparse(url.strip())
        scheme = "https"
        netloc = p.netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        qs = {k: v for k, v in parse_qs(p.query).items()
              if not k.startswith("utm_") and k not in ("fbclid", "gclid", "ref")}
        new_qs = urlencode({k: v[0] for k, v in qs.items()})
        path = p.path.rstrip("/")
        return urlunparse((scheme, netloc, path, "", new_qs, ""))
    except Exception:
        return url.strip().rstrip("/")


# ──────────────────────────────────────────────────────────────────────────────
# 실행
# ──────────────────────────────────────────────────────────────────────────────
INPUT_JSON = os.path.join(BASE_DIR, "regression_collected.json")
OUTPUT_CSV  = os.path.join(BASE_DIR, "regression_set.csv")

FIELDNAMES = [
    "idx", "title", "url", "media", "pub_date", "keyword",
    "cluster",
    "expected_type", "expected_category", "human_label_reason",
    "pipeline_type",           # 현재 분류기 title-only 재평가
    "stale_pipeline_type",     # 수집 당시 JSON 임베딩값 (구 분류기)
    "confidence",              # 수집 당시 신뢰도 (참고용)
    "score",
    "ax1", "ax2", "ax3", "ax4", "ax5", "ax6", "deduct",
    "type_correct",
]


def main():
    with open(INPUT_JSON, encoding="utf-8") as f:
        articles = json.load(f)

    # URL 중복 검사
    seen_norm: dict = {}
    dup_pairs: list = []
    for i, art in enumerate(articles):
        nu = normalize_url(art.get("url", ""))
        if nu in seen_norm:
            dup_pairs.append((seen_norm[nu] + 1, i + 1, nu))
        else:
            seen_norm[nu] = i

    rows = []
    for i, art in enumerate(articles):
        exp = EXPECTED_MAP.get(i)
        if exp is None:
            print(f"[경고] EXPECTED_MAP에 idx={i} 없음", file=sys.stderr)
            exp = ("", "", "", "")

        exp_type, exp_cat, cluster, label_reason = exp
        title = art.get("title", "")

        current_type = classify(title, "")

        row = {
            "idx":      i + 1,
            "title":    title,
            "url":      art.get("url", ""),
            "media":    art.get("media", ""),
            "pub_date": art.get("pub_date", ""),
            "keyword":  art.get("keyword", ""),
            "cluster":  cluster,
            "expected_type":      exp_type,
            "expected_category":  exp_cat,
            "human_label_reason": label_reason,
            "pipeline_type":       current_type,
            "stale_pipeline_type": art.get("article_type", ""),
            "confidence": art.get("confidence", ""),
            "score":      art.get("score", 0),
            "ax1":  art.get("ax1", 0), "ax2":  art.get("ax2", 0),
            "ax3":  art.get("ax3", 0), "ax4":  art.get("ax4", 0),
            "ax5":  art.get("ax5", 0), "ax6":  art.get("ax6", 0),
            "deduct": art.get("deduct", 0),
            "type_correct": "Y" if current_type == exp_type else "N",
        }
        rows.append(row)

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    # 평가 리포트
    total = len(rows)
    correct = sum(1 for r in rows if r["type_correct"] == "Y")
    accuracy = correct / total if total else 0

    has_full_url = sum(1 for r in rows if r["url"].startswith("http"))
    clusters = sorted(set(r["cluster"] for r in rows if r["cluster"]))
    cluster_counts = {c: sum(1 for r in rows if r["cluster"] == c) for c in clusters}

    types = sorted(set(r["expected_type"] for r in rows))
    print("=" * 60)
    print(f"regression_set.csv 생성 완료 ({total}건)")
    print(f"  전체 URL 보유: {has_full_url}/{total}")
    print(f"  정규화 URL 중복: {len(dup_pairs)}건 {dup_pairs or ''}")
    print(f"  합성 데이터: 0건")
    print(f"  동일 발표 클러스터: {len(clusters)}개")
    for c, cnt in cluster_counts.items():
        print(f"    {c}: {cnt}건")
    print()
    print(f"  전체 정확도 (현재 분류기·title-only): {correct}/{total} ({accuracy:.0%})")
    print()
    print(f"  유형별 성능 (45건 회귀 기준, title-only 평가):")
    print(f"  {'유형':<10} {'기대':>4} {'TP':>4} {'FP':>4} {'FN':>4} {'Prec':>6} {'Rec':>6}")
    print(f"  {'-'*52}")
    for t in types:
        tp = sum(1 for r in rows if r["expected_type"] == t and r["pipeline_type"] == t)
        fp = sum(1 for r in rows if r["expected_type"] != t and r["pipeline_type"] == t)
        fn = sum(1 for r in rows if r["expected_type"] == t and r["pipeline_type"] != t)
        n  = tp + fn
        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec  = tp / n if n else 0.0
        print(f"  {t:<10} {n:>4} {tp:>4} {fp:>4} {fn:>4} {prec:>6.0%} {rec:>6.0%}")

    print()
    print("  오분류 목록:")
    for r in rows:
        if r["type_correct"] == "N":
            print(f"    #{r['idx']:02d} 기대={r['expected_type']:<8} "
                  f"현재={r['pipeline_type']:<8} [{r['media']}] {r['title'][:40]}")

    if dup_pairs:
        print()
        print("  [주의] 정규화 URL 중복 발견:")
        for a, b, url in dup_pairs:
            print(f"    #{a} vs #{b}: {url}")


if __name__ == "__main__":
    main()
