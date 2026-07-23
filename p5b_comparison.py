"""
p5b_comparison.py

45건 회귀 데이터에 대해 기존 판정(classify_article_type)과
신규 판정(classify_article_extended)을 비교한다.

입력 : regression_collected.json
        build_regression.py (EXPECTED_MAP 참조)
출력 : p5b_comparison_results.csv  (재현 가능한 상세 결과)
      콘솔 요약 (분포·교차 분석·오분류 목록)

운영 데이터(monitoring_reviews.csv)를 읽거나 쓰지 않는다.
실제 Google Sheets API를 호출하지 않는다.
"""
import csv
import importlib.util
import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ── 모듈 동적 로드 ────────────────────────────────────────────────────────────

def _load_mod(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


nf  = _load_mod("news_fetcher",    os.path.join(BASE_DIR, "news_fetcher.py"))
br  = _load_mod("build_regression", os.path.join(BASE_DIR, "build_regression.py"))

classify_old = nf.classify_article_type
classify_ext = nf.classify_article_extended
EXPECTED_MAP = br.EXPECTED_MAP   # {idx: (type, category, cluster, reason)}

# ── 데이터 로드 ───────────────────────────────────────────────────────────────

_JSON = os.path.join(BASE_DIR, "regression_collected.json")
with open(_JSON, encoding="utf-8") as f:
    articles = json.load(f)

# ── 비교 실행 ─────────────────────────────────────────────────────────────────

rows = []
for idx, art in enumerate(articles):
    title = art.get("title", "")
    desc  = ""                          # regression_collected.json 에 description 없음

    old_type = classify_old(title, desc)
    ext_r    = classify_ext(title, desc)

    expected_tuple = EXPECTED_MAP.get(idx)
    expected_type  = expected_tuple[0] if expected_tuple else ""

    old_diff = (old_type != expected_type)
    ext_diff = (ext_r["article_type"] != expected_type and expected_type != "보도자료형")
    # 주의: extended 에는 "보도자료형"이 없으므로 보도자료형 기대 기사와의 diff 는 별도 컬럼

    rows.append({
        "display_no":         f"#{idx+1:02d}",
        "idx":                idx,
        "title":              title,
        "expected_type":      expected_type,
        "old_type":           old_type,
        "ext_article_type":   ext_r["article_type"],
        "promotional_likelihood": ext_r["promotional_likelihood"],
        "matched_rule":       ext_r["matched_rule"],
        "promotional_score":  ext_r["promotional_score"],
        "classification_basis": ext_r["classification_basis"],
        "title_signal":       ext_r["title_signal"],
        "description_signal": ext_r["description_signal"],
        "old_correct":        not old_diff,
        "old_changed_from_expected": old_diff,
        "pr_expected_high":   (expected_type == "보도자료형"),
        "pr_got_high":        (ext_r["promotional_likelihood"] == "높음"),
    })

# ── CSV 출력 ─────────────────────────────────────────────────────────────────

OUT_CSV = os.path.join(BASE_DIR, "p5b_comparison_results.csv")
FIELDNAMES = [
    "display_no", "idx", "title", "expected_type",
    "old_type", "ext_article_type",
    "promotional_likelihood", "matched_rule", "promotional_score",
    "classification_basis", "title_signal", "description_signal",
    "old_correct", "old_changed_from_expected",
    "pr_expected_high", "pr_got_high",
]
with open(OUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=FIELDNAMES)
    w.writeheader()
    w.writerows(rows)

# ── 콘솔 요약 ─────────────────────────────────────────────────────────────────

def _sep(ch="─", n=72): print(ch * n)

_sep("═")
print("P5B 비교 분석: 기존 article_type vs 신규 classify_article_extended")
print("입력: regression_collected.json (45건, title-only 환경)")
_sep("═")

# 1. 신규 article_type 4종 분포
ext_dist: dict = {}
for r in rows:
    k = r["ext_article_type"]
    ext_dist[k] = ext_dist.get(k, 0) + 1
print("\n[1] 신규 article_type 4종 분포")
for t, c in sorted(ext_dist.items(), key=lambda x: -x[1]):
    print(f"  {t:<12}: {c:2}건")

# 2. promotional_likelihood 분포
pl_dist: dict = {}
for r in rows:
    k = r["promotional_likelihood"]
    pl_dist[k] = pl_dist.get(k, 0) + 1
print("\n[2] promotional_likelihood 분포")
for k in ("높음", "보통", "낮음"):
    print(f"  {k}: {pl_dist.get(k, 0):2}건")

# 3. 기존 보도자료형 → 신규 article_type 교차
pr_rows = [r for r in rows if r["expected_type"] == "보도자료형"]
print(f"\n[3] 기존 '보도자료형'({len(pr_rows)}건) → 신규 article_type 분포")
pr_ext: dict = {}
for r in pr_rows:
    k = r["ext_article_type"]
    pr_ext[k] = pr_ext.get(k, 0) + 1
for t, c in sorted(pr_ext.items(), key=lambda x: -x[1]):
    print(f"  → {t:<12}: {c:2}건")

# 4. 기존 보도자료형 중 promotional_likelihood ≠ 높음인 사례
pr_not_high = [r for r in pr_rows if r["promotional_likelihood"] != "높음"]
print(f"\n[4] 기존 '보도자료형' 중 promotional_likelihood≠높음: {len(pr_not_high)}건")
for r in pr_not_high:
    print(f"  {r['display_no']} [{r['promotional_likelihood']}] {r['title'][:55]}")

# 5. 기존 비보도자료형 중 promotional_likelihood=높음인 사례
non_pr_high = [r for r in rows if r["expected_type"] != "보도자료형"
               and r["promotional_likelihood"] == "높음"]
print(f"\n[5] 비보도자료형 중 promotional_likelihood=높음: {len(non_pr_high)}건")
for r in non_pr_high:
    print(f"  {r['display_no']} expected={r['expected_type']:<8} old={r['old_type']:<8} {r['title'][:45]}")

# 6. P2 발동 건수
p2_counts: dict = {"P2a": 0, "P2b": 0, "P2c": 0, "P2d": 0}
multi_p2: list = []
for r in rows:
    rules = [x for x in r["matched_rule"].split(",") if x]
    for rule in rules:
        if rule in p2_counts:
            p2_counts[rule] += 1
    if len(rules) >= 2:
        multi_p2.append(r)
print("\n[6] P2 규칙별 발동 건수")
for rule, cnt in sorted(p2_counts.items()):
    print(f"  {rule}: {cnt}건")
print(f"  P2 복수 발동: {len(multi_p2)}건")
for r in multi_p2:
    print(f"    {r['display_no']} matched_rule={r['matched_rule']} {r['title'][:45]}")

# 7. classification_basis 분포
basis_dist: dict = {}
for r in rows:
    k = r["classification_basis"]
    basis_dist[k] = basis_dist.get(k, 0) + 1
print("\n[7] classification_basis 분포 (45건 title-only 환경)")
for k, c in sorted(basis_dist.items()):
    print(f"  {k}: {c}건")

# 8. #22, #24 상세
print("\n[8] 기존 오분류 케이스 상세")
for r in rows:
    if r["display_no"] in ("#22", "#24"):
        print(f"  {r['display_no']} 기대={r['expected_type']}")
        print(f"     기존 판정  : {r['old_type']}")
        print(f"     신규 type  : {r['ext_article_type']}")
        print(f"     promo      : {r['promotional_likelihood']}")
        print(f"     matched    : {r['matched_rule'] or '(없음)'}")
        print(f"     title_sig  : {r['title_signal'] or '(없음)'}")
        print(f"     title      : {r['title'][:60]}")

# 9. 요약
old_tp = sum(1 for r in rows if r["old_correct"])
print(f"\n[9] 요약")
print(f"  기존 classify_article_type 정확도: {old_tp}/45")
print(f"  기존 '보도자료형' 기대 중 promotional='높음': "
      f"{sum(r['pr_got_high'] for r in pr_rows)}/{len(pr_rows)}")
print(f"\n결과 CSV: {OUT_CSV}")
_sep("═")
