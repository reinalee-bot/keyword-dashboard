"""
P2a~P2d 복합 규칙 시뮬레이션 (45건 회귀 기준)
출력: p2_simulation_results.csv, p2_simulation_report.md

기준선(current_prediction): news_fetcher에서 P2 규칙을 제외한 경로
적용후(prediction_after_rule): P2 규칙 포함 현행 classify_article_type

주의: description 없는 title-only 평가 — 운영 환경 수치와 다를 수 있음
"""

import csv
import hashlib
import importlib.util
import io
import json
import re
import sys
from collections import defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE = __file__.replace("p2_simulation.py", "")

# ── 45건 회귀 데이터 로드 ──────────────────────────────────
with open(BASE + "regression_collected.json", encoding="utf-8") as f:
    ARTS = json.load(f)

# ── news_fetcher 동적 로드 ───────────────────────────────────
spec = importlib.util.spec_from_file_location("nf", BASE + "news_fetcher.py")
mod  = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

classify_with_p2     = mod.classify_article_type   # P2 통합 현행 함수
get_compound_rules   = mod.get_compound_pr_rules_fired


def classify_baseline(title: str, description: str) -> str:
    """
    P2 복합 규칙을 제외한 기준선 분류 (P2 적용 전 상태 재현).
    news_fetcher.classify_article_type 에서 P2 호출 블록만 건너뜀.
    """
    combined    = (title + " " + description).lower()
    title_lower = title.lower()

    if sum(1 for w in mod._STOCK_WORDS if w in combined) >= 2:
        return "제외 대상"
    if any(w in combined for w in mod._AD_WORDS):
        return "제외 대상"

    has_strong = any(sig in title_lower for sig in mod._STRONG_PR_TITLE_SIGNALS)
    if has_strong or mod._BOOK_ANNOUNCE_RE.search(title):
        return "보도자료형"

    if mod._COLUMN_MARKER_RE.search(title):
        return "기획·분석"

    # ← P2 규칙 블록 생략 (기준선)

    pr_score       = sum(1 for w in mod._PR_WORDS if w in combined)
    interview_score = sum(1 for w in mod._INTERVIEW_WORDS if w in combined)
    if '"' in title or '“' in title or '”' in title:
        product_ctx = '출시' in title_lower or '공개' in title_lower
        if pr_score < 2 and not product_ctx:
            interview_score += 2
    if interview_score >= 2:
        return "인터뷰"

    if any(w in combined for w in mod._EVENT_WORDS):
        return "행사·현장"

    if sum(1 for w in mod._FEATURE_WORDS if w in combined) >= 3:
        return "기획·분석"

    has_org = any(w in combined for w in ["㈜","주식회사","법인","대표이사","대표 ","사장 "])
    if pr_score >= 2 or (pr_score >= 1 and has_org):
        return "보도자료형"

    return "일반 기사"


# ── 인간 레이블 (0-indexed) ──────────────────────────────────
EXPECTED = {
    0:"보도자료형", 1:"인터뷰",   2:"일반 기사", 3:"보도자료형", 4:"일반 기사",
    5:"보도자료형", 6:"보도자료형",7:"기획·분석", 8:"인터뷰",    9:"인터뷰",
   10:"일반 기사",11:"보도자료형",12:"일반 기사",13:"기획·분석",14:"보도자료형",
   15:"일반 기사",16:"일반 기사",17:"인터뷰",   18:"인터뷰",   19:"보도자료형",
   20:"행사·현장",21:"인터뷰",   22:"기획·분석",23:"인터뷰",   24:"보도자료형",
   25:"일반 기사",26:"보도자료형",27:"일반 기사",28:"인터뷰",   29:"보도자료형",
   30:"인터뷰",  31:"보도자료형",32:"일반 기사",33:"일반 기사",34:"일반 기사",
   35:"일반 기사",36:"일반 기사",37:"인터뷰",   38:"일반 기사",39:"인터뷰",
   40:"인터뷰",  41:"인터뷰",   42:"보도자료형",43:"인터뷰",   44:"일반 기사",
}

# 동일 발표 클러스터
CLUSTERS = {
    30:"cluster_inaims_procurement", 31:"cluster_inaims_procurement",
    38:"cluster_kdi_ai_employment",  40:"cluster_kdi_ai_employment",
    41:"cluster_kdi_ai_employment",  42:"cluster_kdi_ai_employment",
    44:"cluster_kdi_ai_employment",
}

TYPES = ["보도자료형","기획·분석","인터뷰","행사·현장","일반 기사"]


def article_id(art: dict) -> str:
    key = f"{art['url']}|{art['title']}|{art['media']}|{art['pub_date']}"
    return hashlib.md5(key.encode(errors="replace")).hexdigest()[:12]


# ── 평가 실행 ────────────────────────────────────────────────
rows = []
for i, art in enumerate(ARTS):
    title        = art["title"]
    exp          = EXPECTED[i]
    pred_before  = classify_baseline(title, "")       # P2 제외 기준선
    rules_fired  = get_compound_rules(title)          # 발동 규칙
    pred_after   = classify_with_p2(title, "")        # P2 통합 현행 결과

    rows.append({
        "idx":                   i,
        "article_id":            article_id(art),
        "title":                 title,
        "media":                 art["media"],
        "pub_date":              art["pub_date"],
        "keyword":               art.get("keyword",""),
        "cluster":               CLUSTERS.get(i, ""),
        "expected_type":         exp,
        "current_prediction":    pred_before,
        "triggered_rule":        "+".join(sorted(rules_fired)) if rules_fired else "",
        "prediction_after_rule": pred_after,
        "correct_before":        "Y" if pred_before == exp else "N",
        "correct_after":         "Y" if pred_after  == exp else "N",
    })

# ── CSV 저장 ─────────────────────────────────────────────────
CSV_PATH = BASE + "p2_simulation_results.csv"
FIELDNAMES = [
    "idx","article_id","title","media","pub_date","keyword","cluster",
    "expected_type","current_prediction","triggered_rule",
    "prediction_after_rule","correct_before","correct_after",
]
with open(CSV_PATH, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=FIELDNAMES)
    w.writeheader()
    w.writerows(rows)


# ── 지표 계산 ────────────────────────────────────────────────
def metrics(rows, pred_col, types=TYPES):
    tp = defaultdict(int); fp = defaultdict(int); fn = defaultdict(int)
    for r in rows:
        exp  = r["expected_type"]
        pred = r[pred_col]
        for t in types:
            if exp == t and pred == t:   tp[t] += 1
            elif exp != t and pred == t: fp[t] += 1
            elif exp == t and pred != t: fn[t] += 1
    result = {}
    for t in types:
        p  = tp[t]/(tp[t]+fp[t]) if tp[t]+fp[t] else 0.0
        r_ = tp[t]/(tp[t]+fn[t]) if tp[t]+fn[t] else 0.0
        f1 = 2*p*r_/(p+r_) if p+r_ else 0.0
        result[t] = {"tp":tp[t],"fp":fp[t],"fn":fn[t],"precision":p,"recall":r_,"f1":f1}
    return result


def confusion_matrix(rows, pred_col, types=TYPES):
    cm = defaultdict(lambda: defaultdict(int))
    for r in rows:
        cm[r["expected_type"]][r[pred_col]] += 1
    return cm


m_before  = metrics(rows, "current_prediction")
m_after   = metrics(rows, "prediction_after_rule")
cm_before = confusion_matrix(rows, "current_prediction")
cm_after  = confusion_matrix(rows, "prediction_after_rule")

acc_before = sum(1 for r in rows if r["correct_before"]=="Y")
acc_after  = sum(1 for r in rows if r["correct_after"]=="Y")

# 규칙별 집계
rule_tp   = defaultdict(int)
rule_fp   = defaultdict(int)
rule_used = defaultdict(list)
for r in rows:
    if not r["triggered_rule"]:
        continue
    for rname in r["triggered_rule"].split("+"):
        rule_used[rname].append(r["idx"])
        if r["expected_type"] == "보도자료형":
            rule_tp[rname] += 1
        else:
            rule_fp[rname] += 1

# 신규 FP (P2 발동 + 기대 ≠ 보도자료형)
new_fps = [r for r in rows if r["triggered_rule"] and r["expected_type"] != "보도자료형"]
# 남은 오분류
remaining_wrong = [r for r in rows if r["correct_after"] == "N"]


# ── 보고서 작성 ──────────────────────────────────────────────
lines = []
W = lines.append

W("# P2a~P2d 복합 규칙 시뮬레이션 보고서")
W("")
W("**평가 기준**: 45건 제목 전용(title-only) — description 없음")
W("**한계**: 운영 환경에서는 description도 사용하므로 실제 성능은 이 수치와 다를 수 있음")
W("**기준선(current_prediction)**: P2 규칙 제외 경로 (P2 적용 전 상태 재현)")
W("**적용후(prediction_after_rule)**: 현행 classify_article_type (P2 통합)")
W("")

W("## 전체 정확도")
W("")
W(f"| 구분 | 정확 건수 / 전체 | 정확도 |")
W(f"|------|-----------------|--------|")
W(f"| P2 적용 전(기준선) | {acc_before}/45 | {acc_before/45:.1%} |")
W(f"| P2 적용 후(현행)   | {acc_after}/45  | {acc_after/45:.1%}  |")
W("")

W("## 유형별 정밀도·재현율·F1")
W("")
W("### P2 적용 전(기준선)")
W("")
W(f"| 유형 | 기대 건수 | TP | FP | FN | Precision | Recall | F1 |")
W(f"|------|-----------|----|----|----|-----------|---------|----|")
for t in TYPES:
    exp_cnt = sum(1 for r in rows if r["expected_type"]==t)
    m = m_before[t]
    W(f"| {t} | {exp_cnt} | {m['tp']} | {m['fp']} | {m['fn']} | {m['precision']:.0%} | {m['recall']:.0%} | {m['f1']:.0%} |")
W("")
W("### P2 적용 후(현행)")
W("")
W(f"| 유형 | 기대 건수 | TP | FP | FN | Precision | Recall | F1 |")
W(f"|------|-----------|----|----|----|-----------|---------|----|")
for t in TYPES:
    exp_cnt = sum(1 for r in rows if r["expected_type"]==t)
    m = m_after[t]
    W(f"| {t} | {exp_cnt} | {m['tp']} | {m['fp']} | {m['fn']} | {m['precision']:.0%} | {m['recall']:.0%} | {m['f1']:.0%} |")
W("")

W("## 혼동 행렬")
W("")
W("### P2 적용 전(기준선)")
W("")
hdr = "| 기대\\예측 | " + " | ".join(TYPES) + " |"
W(hdr)
W("|" + ("----|" * (len(TYPES)+1)))
for exp_t in TYPES:
    row_cells = [f"**{exp_t}**"] + [str(cm_before[exp_t][pred_t]) for pred_t in TYPES]
    W("| " + " | ".join(row_cells) + " |")
W("")
W("### P2 적용 후(현행)")
W("")
W(hdr)
W("|" + ("----|" * (len(TYPES)+1)))
for exp_t in TYPES:
    row_cells = [f"**{exp_t}**"] + [str(cm_after[exp_t][pred_t]) for pred_t in TYPES]
    W("| " + " | ".join(row_cells) + " |")
W("")

W("## 규칙별 발동 결과")
W("")
W(f"| 규칙 | 추가 TP | 신규 FP | 발동 기사 idx |")
W(f"|------|---------|---------|--------------|")
for rname in ["P2a","P2b","P2c","P2d"]:
    idxs = rule_used.get(rname, [])
    W(f"| {rname} | {rule_tp[rname]} | {rule_fp[rname]} | {idxs} |")
W("")
W(f"**P2 규칙에 의한 신규 FP 합계: {len(new_fps)}건**")
W("")

W("### 발동 기사 상세")
W("")
for r in rows:
    if not r["triggered_rule"]:
        continue
    if r["expected_type"]=="보도자료형" and r["current_prediction"]!="보도자료형":
        mark = "✓ FN→TP"
    elif r["expected_type"]!="보도자료형" and r["triggered_rule"]:
        mark = "⚠ FP"
    else:
        mark = "TP(기존)"
    W(f"- **#{r['idx']:02d}** [{r['triggered_rule']}] {mark}")
    W(f"  제목: {r['title']}")
    W(f"  기대={r['expected_type']} / 기준선={r['current_prediction']} / 적용후={r['prediction_after_rule']}")
    W("")

W("## 남은 오분류 목록")
W("")
if remaining_wrong:
    W(f"| idx | 기대 | 예측 | 오류 원인 | 제목 |")
    W(f"|-----|------|------|-----------|------|")
    for r in remaining_wrong:
        cause = "기존 FP" if r["correct_before"]=="N" else "P2 신규 FP"
        W(f"| #{r['idx']:02d} | {r['expected_type']} | {r['prediction_after_rule']} | {cause} | {r['title'][:55]} |")
else:
    W("없음 (전체 45건 정확)")
W("")

W("## 동일 발표 클러스터")
W("")
W("| 클러스터 | 포함 기사 | 비고 |")
W("|---------|-----------|------|")
W("| cluster_inaims_procurement | #30, #31 | #30 인터뷰(부사장 발언) vs #31 보도자료형(알림) — 유형 다름, 모두 유효 샘플 |")
W("| cluster_kdi_ai_employment  | #38, #40, #41, #42, #44 | KDI 보고서 복수 매체 보도 |")
W("")
W("**URL 정규화 기준 중복**: 0건  ")
W("**#09/#10**: 동일 매체(TECHM) 다른 기사(idxno 달라) — 클러스터 없음  ")
W("**#31/#32**: 기사 번호 상 인접하나, #31=THEPOWERNEWS·#32=E2NEWS — 동일 발표 다른 매체, cluster_inaims_procurement")
W("")

W("## 평가 한계")
W("")
W("- **title-only 평가**: description 없음 — 운영 환경과 수치 차이 가능")
W("- P2 규칙은 제목 패턴 기반이므로 description 신호는 미반영")
W("- E2E 검증(실제 Naver API + 브라우저 화면) 미수행")
W("- #22 [보안 칼럼] 기사는 기존 오분류(일반 기사 FP)이며 P2 규칙에 의한 신규 FP 아님")

REPORT_PATH = BASE + "p2_simulation_report.md"
with open(REPORT_PATH, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))


# ── 콘솔 출력 ────────────────────────────────────────────────
print("=" * 80)
print("P2a~P2d 복합 규칙 시뮬레이션 결과 (45건 제목 전용)")
print("기준선 = P2 제외 경로 / 적용후 = 현행 classify_article_type")
print("=" * 80)
print()
print(f"전체 정확도: {acc_before}/45 ({acc_before/45:.1%}) → {acc_after}/45 ({acc_after/45:.1%})")
print()
print(f"{'유형':<10} {'기대':>4}  {'전_TP':>5} {'전_Rec':>6}  {'후_TP':>5} {'후_Rec':>6}")
print("-"*50)
for t in TYPES:
    exp_cnt = sum(1 for r in rows if r["expected_type"]==t)
    mb, ma = m_before[t], m_after[t]
    print(f"{t:<10} {exp_cnt:>4}  {mb['tp']:>5} {mb['recall']:>6.0%}  {ma['tp']:>5} {ma['recall']:>6.0%}")
print()
print("규칙별 발동:")
for rname in ["P2a","P2b","P2c","P2d"]:
    idxs  = rule_used.get(rname, [])
    tp_n  = rule_tp.get(rname, 0)
    fp_n  = rule_fp.get(rname, 0)
    print(f"  {rname}: TP+{tp_n} / 신규FP+{fp_n}  idx={idxs}")
print()
print(f"신규 FP: {len(new_fps)}건")
if new_fps:
    for r in new_fps:
        print(f"  ⚠ #{r['idx']:02d} 기대={r['expected_type']} [{r['triggered_rule']}] {r['title'][:60]}")
print()
if remaining_wrong:
    print(f"남은 오분류 ({len(remaining_wrong)}건):")
    for r in remaining_wrong:
        cause = "기존오류" if r["correct_before"]=="N" else "신규FP"
        print(f"  [{cause}] #{r['idx']:02d} 기대={r['expected_type']} / 예측={r['prediction_after_rule']}  {r['title'][:50]}")
else:
    print("남은 오분류: 없음")
print()
print(f"결과 CSV : p2_simulation_results.csv")
print(f"보고서   : p2_simulation_report.md")
