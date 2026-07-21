"""
5단계 재검증 스크립트 — commit 47c1b0d 기준 실제 수집·선정 실행
코드 수정 없음. 결과 보고 전용.
"""
import os, sys, re, time
from datetime import datetime, timedelta, timezone
from collections import Counter
from dotenv import load_dotenv

load_dotenv()

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import monitoring as mon
import news_fetcher as nf
from monitoring_tab_helpers import today_kst, monitoring_config_version

# ─────────────────────────────────────────────────────────────
# [1] 실제 실행 기준 시각과 수집 조건
# ─────────────────────────────────────────────────────────────
print("=" * 72)
print("[1] 실제 실행 기준 시각과 수집 조건")
print("=" * 72)

CID = os.getenv("NAVER_CLIENT_ID", "").strip()
CSC = os.getenv("NAVER_CLIENT_SECRET", "").strip()
if not CID or not CSC:
    print("  ERROR: Naver API 인증정보 없음")
    sys.exit(1)

MEDIA_CFG = nf.load_media_config()
kst_now   = datetime.now(timezone(timedelta(hours=9)))
end_utc   = datetime.now(timezone.utc)
start_utc = end_utc - timedelta(hours=24)

print(f"  실행 시각(KST)   : {kst_now.strftime('%Y-%m-%d %H:%M:%S KST')}")
print(f"  수집 기간(UTC)   : {start_utc.strftime('%Y-%m-%dT%H:%M')} ~ {end_utc.strftime('%Y-%m-%dT%H:%M')}")
print(f"  target_count     : 15")
print(f"  max_count        : 20")
print(f"  API 인증         : OK (ID={CID[:4]}...)")
print(f"  config_version   : {monitoring_config_version(mon.CONFIG_PATH)}")

active_list = mon.load_active_queries()
group_queries: dict = {}
for item in active_list:
    group_queries.setdefault(item["group"], []).append(item["query"])

GNAME = {"company":"자사","competitor":"경쟁사",
         "ai_ax":"AI·AX","cloud_security":"클라우드·보안","vendor":"주요 벤더"}
GORDER = ["company","competitor","ai_ax","cloud_security","vendor"]

print(f"  활성 검색어      : 총 {len(active_list)}개 / {len(group_queries)}개 그룹")
for g in GORDER:
    qs = group_queries.get(g, [])
    if qs:
        print(f"    [{GNAME.get(g,g)}] {', '.join(qs)}")

# ─────────────────────────────────────────────────────────────
# 실제 수집 실행
# ─────────────────────────────────────────────────────────────
_query_stats = []
_orig = nf.fetch_articles_for_keyword

def _tracked(keyword, date_from, date_to, sort_api, media_scope,
             article_type_filter, cid, csc, media_config, display=100):
    t0 = time.time()
    r  = _orig(keyword, date_from, date_to, sort_api, media_scope,
               article_type_filter, cid, csc, media_config, display)
    grp = next((g for g, qs in group_queries.items() if keyword in qs), "unknown")
    _query_stats.append({
        "group": grp, "query": keyword,
        "ok": r.get("status") == "success",
        "raw": r.get("raw_count", 0),
        "filtered": r.get("filtered_count", 0),
        "elapsed": time.time() - t0,
        "error": r.get("error"),
    })
    return r

nf.fetch_articles_for_keyword = _tracked
t_pipe = time.time()

try:
    candidates = mon.fetch_daily_monitoring_candidates(
        start_utc, end_utc, cid=CID, csc=CSC, media_config=MEDIA_CFG
    )
    t_cand = time.time()
    selected = mon.select_daily_monitoring_articles(
        candidates, target_count=15, max_count=20, media_config=MEDIA_CFG
    )
    t_sel = time.time()
finally:
    nf.fetch_articles_for_keyword = _orig

# ─────────────────────────────────────────────────────────────
# [2] 카테고리 분포 비교 (수정 전 vs 수정 후)
# ─────────────────────────────────────────────────────────────
print()
print("=" * 72)
print("[2] 수정 전 20건 vs 수정 후 카테고리 분포 비교")
print("=" * 72)

BEFORE = {"리스크": 20}   # 4단계 실행 결과: 20건 전부 리스크
after_dist = Counter(a.get("_monitoring_category", "기타") for a in selected)

ALL_CATS = ["리스크", "자사·관계사", "경쟁사", "기획기사 후보",
            "AI·AX 시장동향", "클라우드·보안", "주요 벤더", "기타"]

print(f"  {'카테고리':<14} {'수정 전':>6} {'수정 후':>6}  {'변화':>8}")
print(f"  {'-'*42}")
for cat in ALL_CATS:
    b = BEFORE.get(cat, 0)
    a = after_dist.get(cat, 0)
    diff = a - b
    diff_s = f"+{diff}" if diff > 0 else str(diff) if diff < 0 else "0"
    if b or a:
        print(f"  {cat:<14} {b:>6} {a:>6}  {diff_s:>8}")
print(f"  {'-'*42}")
print(f"  {'합계':<14} {sum(BEFORE.values()):>6} {len(selected):>6}")

risk_count = after_dist.get("리스크", 0)
print(f"\n  리스크 상한 적용: {risk_count}/5건")

# ─────────────────────────────────────────────────────────────
# [3] 최종 선정 건수
# ─────────────────────────────────────────────────────────────
print()
print("=" * 72)
print("[3] 수정 후 최종 선정 건수")
print("=" * 72)
print(f"  후보 수집: {len(candidates)}건  →  최종 선정: {len(selected)}건")
print(f"  (목표 15건, 최대 20건 / 수집 소요 {t_cand-t_pipe:.1f}s, 선정 {t_sel-t_cand:.1f}s)")

# ─────────────────────────────────────────────────────────────
# [4] 최종 선정 기사 전체
# ─────────────────────────────────────────────────────────────
print()
print("=" * 72)
print(f"[4] 수정 후 최종 선정 기사 전체 ({len(selected)}건)")
print("=" * 72)

for i, art in enumerate(selected, 1):
    title  = art.get("title", "")
    media  = art.get("media_name", "")
    cat    = art.get("_monitoring_category", "기타")
    is_urg = art.get("_is_risk_priority", False)
    rl     = art.get("_relevance_level", "")
    rscore = art.get("_relevance_score", 0)
    buzz   = art.get("score", 0)
    prscore= art.get("_pr_value_score", 0)
    pri    = art.get("_monitoring_priority", 0)
    reason = art.get("_monitoring_reason", "")

    print(f"  [{i:2}] 제목     : {title}")
    print(f"       매체     : {media}")
    print(f"       카테고리 : {cat}")
    print(f"       긴급리스크: {'YES' if is_urg else 'no'}")
    print(f"       관련성   : {rl} ({rscore}점)")
    print(f"       뉴스중요도: {buzz}점")
    print(f"       PR활용도 : {prscore}점")
    print(f"       선정이유 : {reason}")
    print()

# ─────────────────────────────────────────────────────────────
# [5] 특정 기사 반영 결과
# ─────────────────────────────────────────────────────────────
print("=" * 72)
print("[5] 기사별 반영 결과")
print("=" * 72)

# 후보 전체 + 선정 목록에서 키워드로 검색
def find_in(pool, *keywords):
    result = []
    for art in pool:
        text = (art.get("title","") + " " + art.get("description","")).lower()
        if any(k.lower() in text for k in keywords):
            result.append(art)
    return result

def classify_and_show(label, arts_cand, arts_sel):
    selected_urls = {a.get("url") for a in arts_sel}
    print(f"\n  ■ {label}")
    if not arts_cand:
        print("    → 후보에서 미수집 (수집 기간 내 해당 기사 없음)")
        return
    for art in arts_cand:
        url    = art.get("url","")
        title  = art.get("title","")
        cat    = art.get("_monitoring_category","기타")
        rl     = art.get("_relevance_level","")
        rc     = mon._classify_monitoring_risk(art)
        is_sel = url in selected_urls
        print(f"    {'[선정]' if is_sel else '[제외]'}  {title[:60]}")
        print(f"           카테고리={cat}  관련성={rl}  리스크분류={rc}")
        reason = art.get("_monitoring_reason","")
        if not is_sel:
            # 이유 추정
            if rc == "not_risk" and art.get("_relevance_type","") == "리스크":
                sig_match = next(
                    (s for s in mon._NON_INCIDENT_SIGNALS
                     if s in (art.get("title","")+" "+art.get("description","")).lower()),
                    None
                )
                if sig_match:
                    reason += f"  (비사건 시그널: '{sig_match}')"
        print(f"           이유: {reason[:70]}")

# 1. 허깅페이스 데이터·인증정보 탈취
hf = find_in(candidates, "허깅페이스", "HuggingFace", "Hugging Face")
classify_and_show("허깅페이스 데이터·인증정보 탈취", hf, selected)

# 2. 소닉월 제로데이 공격
sw = find_in(candidates, "소닉월", "SonicWall", "제로데이")
# 제로데이가 너무 많으면 소닉월로만 한정
sw_sonic = [a for a in sw if any(k in (a.get("title","")+" "+a.get("description","")).lower()
                                  for k in ["소닉월","sonicwall"])]
if not sw_sonic:
    sw_sonic = sw[:3]
classify_and_show("소닉월 제로데이 공격", sw_sonic, selected)

# 3. SGA솔루션즈 동일 지원사업 5건
sga = find_in(candidates, "SGA솔루션즈", "SGA 솔루션즈", "SGA")
classify_and_show("SGA솔루션즈 동일 지원사업 5건", sga, selected)

# 4. 코드게이트 파생 기사
cg = find_in(candidates, "코드게이트", "CODEGATE")
classify_and_show("코드게이트 파생 기사", cg, selected)

# 5. 클루커스·스트라이커 파트너십
cs = find_in(candidates, "클루커스", "스트라이커", "스트레이커")
classify_and_show("클루커스·스트라이커 파트너십", cs, selected)

# 6. SAP 라이선스 최적화
sap = find_in(candidates, "SAP", "라이선스 최적화")
classify_and_show("SAP 라이선스 최적화", sap, selected)

# 7. 미국 AI 규제 분석
ai_reg = find_in(candidates, "AI 규제", "ai 규제", "미국 AI")
classify_and_show("미국 AI 규제 분석", ai_reg, selected)

# 8. AI 안전 측정·검증 분석
ai_safe = find_in(candidates, "AI 안전", "ai 안전", "안전 측정", "안전 검증")
classify_and_show("AI 안전 측정·검증 분석", ai_safe, selected)

# ─────────────────────────────────────────────────────────────
# [6] 제거된 기존 오탐
# ─────────────────────────────────────────────────────────────
print()
print("=" * 72)
print("[6] 제거된 기존 오탐")
print("=" * 72)

# 수정 전 기준: _relevance_type=="리스크" 이면 무조건 category=리스크였음
# 수정 후: _classify_monitoring_risk == "not_risk" 이면 리스크 카테고리 제외됨
removed_from_risk = []
for art in candidates:
    if art.get("_relevance_type","") == "리스크":
        rc = mon._classify_monitoring_risk(art)
        if rc == "not_risk":
            removed_from_risk.append((art, rc))

removed_not_selected = [(a, rc) for a, rc in removed_from_risk
                        if a.get("url") not in {s.get("url") for s in selected}]

if removed_not_selected:
    print(f"  수정 전에는 리스크 카테고리에 포함됐을 기사 중 수정 후 제외된 기사: {len(removed_not_selected)}건")
    for art, rc in removed_not_selected[:15]:
        sig = next(
            (s for s in mon._NON_INCIDENT_SIGNALS
             if s in (art.get("title","")+" "+art.get("description","")).lower()),
            art.get("article_type","")
        )
        print(f"  - {art.get('title','')[:60]}")
        print(f"    리스크분류={rc}  비사건근거: '{sig}'")
else:
    print("  (제거된 오탐 없음)")

# ─────────────────────────────────────────────────────────────
# [7] 새롭게 포함된 기사
# ─────────────────────────────────────────────────────────────
print()
print("=" * 72)
print("[7] 새롭게 포함된 기사")
print("=" * 72)

# 수정 전에는 전부 리스크로 채워져서 다른 카테고리는 0건이었음
# 수정 후에 리스크 외 카테고리에서 선정된 기사 = 새롭게 포함된 기사
new_cats = [a for a in selected if a.get("_monitoring_category","기타") != "리스크"]

if new_cats:
    print(f"  리스크 외 카테고리에서 새롭게 선정: {len(new_cats)}건")
    for art in new_cats:
        cat  = art.get("_monitoring_category","기타")
        rl   = art.get("_relevance_level","")
        print(f"  - [{cat}] [{rl}] {art.get('title','')[:60]}")
        print(f"           매체: {art.get('media_name','')}  PR활용도: {art.get('_pr_value_score',0)}")
else:
    print("  없음")

# ─────────────────────────────────────────────────────────────
# [8] 남아 있는 오탐·누락
# ─────────────────────────────────────────────────────────────
print()
print("=" * 72)
print("[8] 남아 있는 오탐·누락")
print("=" * 72)

ODAM_SIGNALS = {
    "홍보성 출시 기사":    ["정식 출시","베타 출시","제품 출시","솔루션 출시","론칭"],
    "컨퍼런스·행사 기사":  ["컨퍼런스","전시회","세미나","포럼","행사"],
    "지원사업 기사":       ["지원사업","공급기업 선정","사업 선정"],
    "규제·정책 분석":      ["규제 강화","ai 규제","정책 발표"],
    "트렌드 전망 기사":    ["보안 전망","트렌드 분석","방어 전략","예방 전략"],
}

odam_selected = []
for art in selected:
    text = (art.get("title","")+" "+art.get("description","")).lower()
    for odam_type, sigs in ODAM_SIGNALS.items():
        if any(s in text for s in sigs):
            cat = art.get("_monitoring_category","기타")
            odam_selected.append((odam_type, cat, art))
            break

if odam_selected:
    print(f"  오탐 의심 기사 (선정됨): {len(odam_selected)}건")
    for otype, cat, art in odam_selected:
        print(f"  - [{otype}] [{cat}] {art.get('title','')[:60]}")
else:
    print("  오탐 의심 기사: 없음")

# 유의미 누락 후보
selected_urls = {a.get("url") for a in selected}
VALUE_KWS = ["AI","클라우드","보안","라이선스","인프라","AX","디지털전환",
             "마이크로소프트","어도비","오토데스크","기업","침해"]
missed_high = []
for art in candidates:
    if art.get("url") in selected_urls:
        continue
    if art.get("_relevance_level","") in ("높음","보통"):
        title = art.get("title","")
        if any(k in title for k in VALUE_KWS):
            missed_high.append(art)
missed_high.sort(key=lambda a: -a.get("_monitoring_priority",0))

if missed_high:
    print(f"\n  유의미 누락 후보: {len(missed_high)}건 중 상위 5건")
    media_cnt_sel = Counter(a.get("media_name","") for a in selected)
    for art in missed_high[:5]:
        mn  = art.get("media_name","")
        cat = art.get("_monitoring_category","기타")
        pri = art.get("_monitoring_priority",0)
        rl  = art.get("_relevance_level","")
        # 미선정 이유
        mn_cnt = media_cnt_sel.get(mn, 0)
        cat_cnt_sel = Counter(a.get("_monitoring_category","") for a in selected)
        cat_c = cat_cnt_sel.get(cat,0)
        if mn_cnt >= 3:
            exc_reason = "동일 매체 상한(3)"
        elif cat == "리스크" and cat_c >= 5:
            exc_reason = "리스크 상한(5)"
        elif cat not in mon._UNLIMITED_CATS and cat != "리스크" and cat_c >= 5:
            exc_reason = f"카테고리 상한(5)"
        else:
            exc_reason = "target_count 초과"
        print(f"  - [{rl}] 우선{pri:3} | {mn:<16} | {exc_reason:<18} | {art.get('title','')[:45]}")
else:
    print("  유의미 누락: 없음")

# ─────────────────────────────────────────────────────────────
# [9] 동일 사건 중복 건수
# ─────────────────────────────────────────────────────────────
print()
print("=" * 72)
print("[9] 동일 사건 중복 건수 (2차 이벤트 클러스터링 효과)")
print("=" * 72)

# score 계산 후 2차 클러스터링 전 상태 재현
import copy
from news_fetcher import cluster_articles, calculate_article_score

temp_cands = copy.deepcopy(candidates)
clusters = cluster_articles(temp_cands, threshold=0.75)
after_primary = []
for cl in clusters:
    rep  = cl["rep"]
    size = cl["size"]
    for member in cl["cluster"]:
        if member is rep: continue
        for mq in member.get("_matched_queries", []):
            if mq not in rep.setdefault("_matched_queries", []):
                rep["_matched_queries"].append(mq)
        for mg in member.get("_matched_groups", []):
            if mg not in rep.setdefault("_matched_groups", []):
                rep["_matched_groups"].append(mg)
    rep["score"] = calculate_article_score(rep, size, {})
    after_primary.append(rep)

for art in after_primary:
    mon.score_monitoring_candidate(art)

after_secondary = mon._merge_monitoring_event_clusters(after_primary)

merged_count = len(after_primary) - len(after_secondary)
print(f"  1차 클러스터링 후: {len(after_primary)}건")
print(f"  2차 이벤트 클러스터링 후: {len(after_secondary)}건")
print(f"  2차에서 병합된 기사 수: {merged_count}건")

if merged_count > 0:
    # 어떤 기사들이 병합됐는지 찾기
    primary_urls = {a.get("url") for a in after_primary}
    secondary_urls = {a.get("url") for a in after_secondary}
    # secondary에는 없는 URL = 병합되어 사라진 기사들
    merged_away = [a for a in after_primary if a.get("url") not in secondary_urls]
    if merged_away:
        print(f"\n  병합 제거된 기사 ({len(merged_away)}건):")
        for art in merged_away:
            print(f"  - {art.get('title','')[:65]}")
else:
    print("  (동일 이벤트 병합 없음 — 수집 기간 내 중복 보도 없음)")

# SGA솔루션즈 특정 확인
sga_primary  = [a for a in after_primary  if "sga" in (a.get("title","")).lower()]
sga_secondary= [a for a in after_secondary if "sga" in (a.get("title","")).lower()]
if sga_primary:
    print(f"\n  SGA솔루션즈: 1차 후 {len(sga_primary)}건 → 2차 후 {len(sga_secondary)}건")
    for art in sga_primary:
        print(f"  - {art.get('title','')[:65]}")

# ─────────────────────────────────────────────────────────────
# [10] git status & 최종 커밋 해시
# ─────────────────────────────────────────────────────────────
print()
print("=" * 72)
print("[10] git status & 최종 커밋 해시")
print("=" * 72)

import subprocess
try:
    git_log = subprocess.check_output(
        ["git", "-C", BASE, "log", "--oneline", "-3"],
        text=True, encoding="utf-8", errors="replace"
    ).strip()
    git_st = subprocess.check_output(
        ["git", "-C", BASE, "status", "--short"],
        text=True, encoding="utf-8", errors="replace"
    ).strip()
    print("  최근 커밋 3건:")
    for line in git_log.splitlines():
        print(f"    {line}")
    print(f"  git status: {'(clean)' if not git_st else git_st}")
except Exception as e:
    print(f"  git 정보 조회 실패: {e}")

print()
print("=" * 72)
print("5단계 재검증 완료")
print("=" * 72)
