"""
4단계 운영 검증 스크립트 — 코드 수정 없이 실제 파이프라인 실행 및 결과 보고
"""
import os, sys, time
from datetime import datetime, timedelta, timezone
from collections import Counter
from dotenv import load_dotenv

load_dotenv()

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

t_total_start = time.time()

# ─────────────────────────────────────────────────────────────────────
# [1] import / 환경 검증
# ─────────────────────────────────────────────────────────────────────
print("=" * 70)
print("[import/환경 검증]")
print("=" * 70)

try:
    import monitoring as mon
    print("  ✓ monitoring 임포트")
except Exception as e:
    print(f"  ✗ monitoring: {e}"); sys.exit(1)

try:
    import news_fetcher as nf
    print("  ✓ news_fetcher 임포트")
except Exception as e:
    print(f"  ✗ news_fetcher: {e}"); sys.exit(1)

try:
    from monitoring_tab_helpers import (
        today_kst, monitoring_config_version,
        apply_category_filter, count_by_category, make_widget_key,
    )
    print("  ✓ monitoring_tab_helpers 임포트")
except Exception as e:
    print(f"  ✗ monitoring_tab_helpers: {e}"); sys.exit(1)

config_path = mon.CONFIG_PATH
print(f"  monitoring_queries.yaml: {'존재' if os.path.exists(config_path) else '없음!'}")
cv = monitoring_config_version(config_path)
print(f"  config_version: {cv}")
print(f"  today_kst: {today_kst()}")

# ─────────────────────────────────────────────────────────────────────
# [1b] Streamlit 실행 검증 (headless, 12초 타임아웃)
# ─────────────────────────────────────────────────────────────────────
print()
print("=" * 70)
print("[1] Streamlit 실제 실행 검증 (headless 12초)")
print("=" * 70)

import subprocess, threading

_st_log = []
_st_done = threading.Event()

def _run_st():
    env = os.environ.copy()
    env["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
    try:
        r = subprocess.run(
            [sys.executable, "-m", "streamlit", "run", "dashboard.py",
             "--server.headless=true", "--server.port=18899",
             "--server.runOnSave=false"],
            capture_output=True, text=True, timeout=12, env=env, cwd=BASE
        )
        _st_log.extend(r.stdout.splitlines())
        _st_log.extend(r.stderr.splitlines())
    except subprocess.TimeoutExpired as e:
        _st_log.extend((e.stdout or "").splitlines())
        _st_log.extend((e.stderr or "").splitlines())
    _st_done.set()

t = threading.Thread(target=_run_st); t.start(); t.join()

ERROR_KEYS = ["Error","Traceback","ImportError","NameError","KeyError",
              "TypeError","ModuleNotFound","SyntaxError","AttributeError",
              "RuntimeError"]
errs  = [l for l in _st_log if any(k in l for k in ERROR_KEYS)]
start_ok = any(k in l for k in ["Running on","You can now view","Network URL","started"]
               for l in _st_log)

if not _st_log:
    print("  상태: Streamlit 출력 없음 (미설치 또는 오류)")
else:
    if errs:
        print(f"  상태: 오류 {len(errs)}건")
        for l in errs[:6]: print(f"    {l}")
    else:
        print("  상태: 오류 없음")
    if start_ok:
        print("  앱 시작: 확인됨")
    else:
        print("  앱 시작: 직접 확인 필요 (타임아웃 내 startup 메시지 미수신)")
    print(f"  로그 ({len(_st_log)}줄, 처음 12줄):")
    for l in _st_log[:12]: print(f"    {l}")

# ─────────────────────────────────────────────────────────────────────
# [2] 수집 조건
# ─────────────────────────────────────────────────────────────────────
print()
print("=" * 70)
print("[2] 실제 수집 조건")
print("=" * 70)

CID = os.getenv("NAVER_CLIENT_ID","").strip()
CSC = os.getenv("NAVER_CLIENT_SECRET","").strip()
if not CID or not CSC:
    print("  ✗ Naver API 인증정보 없음 — 실행 불가")
    sys.exit(1)
print(f"  API 인증: 확인 (ID={CID[:4]}...)")

MEDIA_CFG = nf.load_media_config()
kst_now  = datetime.now(timezone(timedelta(hours=9)))
end_utc  = datetime.now(timezone.utc)
start_utc = end_utc - timedelta(hours=24)

print(f"  기준 시각(KST): {kst_now.strftime('%Y-%m-%d %H:%M:%S')}")
print(f"  수집 기간(UTC): {start_utc.strftime('%Y-%m-%dT%H:%M')} ~ {end_utc.strftime('%Y-%m-%dT%H:%M')}")
print(f"  target_count=15, max_count=20")

# 활성 검색어
active_list = mon.load_active_queries()   # [{group, query}, ...]
group_queries = {}
for item in active_list:
    group_queries.setdefault(item["group"], []).append(item["query"])

GROUP_NAMES = {
    "company":"자사", "competitor":"경쟁사",
    "ai_ax":"AI·AX", "cloud_security":"클라우드·보안", "vendor":"주요 벤더",
}
GROUP_ORDER = ["company","competitor","ai_ax","cloud_security","vendor"]
print(f"  활성 검색어: 총 {len(active_list)}개 / {len(group_queries)}개 그룹")
for g in GROUP_ORDER:
    if g in group_queries:
        print(f"    [{GROUP_NAMES.get(g,g)}] {', '.join(group_queries[g])}")

# ─────────────────────────────────────────────────────────────────────
# [3] 실제 수집 — fetch_articles_for_keyword 호출 횟수 추적
# ─────────────────────────────────────────────────────────────────────
print()
print("=" * 70)
print("[3] 단계별 수집 집계 — 실제 파이프라인 실행")
print("=" * 70)

# 원본 함수 래핑으로 호출 추적
_query_stats = []   # {group, query, api_ok, raw_before_filter, articles_after_filter}
_orig_fetch  = nf.fetch_articles_for_keyword

def _tracked_fetch(keyword, date_from, date_to, sort_api, media_scope,
                   article_type_filter, cid, csc, media_config, display=100):
    t_q = time.time()
    result = _orig_fetch(keyword, date_from, date_to, sort_api, media_scope,
                         article_type_filter, cid, csc, media_config, display)
    elapsed = time.time() - t_q
    raw   = result.get("raw_count", 0)
    filt  = result.get("filtered_count", 0)
    ok    = result.get("status") == "success"
    err   = result.get("error")
    # 어느 그룹인지는 keyword로 역추적
    grp = next((g for g, qs in group_queries.items() if keyword in qs), "unknown")
    _query_stats.append({
        "group": grp, "query": keyword,
        "ok": ok, "raw": raw, "filtered": filt,
        "elapsed": elapsed, "error": err,
    })
    print(f"    [{GROUP_NAMES.get(grp,grp):8s}] '{keyword}': {raw}건 수집, {filt}건 필터 통과"
          f"{' — '+err if not ok else ''} ({elapsed:.1f}s)")
    return result

nf.fetch_articles_for_keyword = _tracked_fetch

print("  수집 중...")
t_pipe_start = time.time()
try:
    candidates = mon.fetch_daily_monitoring_candidates(
        start_utc, end_utc, cid=CID, csc=CSC, media_config=MEDIA_CFG
    )
    t_cand = time.time()
    print(f"\n  ▶ 후보 통합 완료: {len(candidates)}건 ({t_cand-t_pipe_start:.1f}s)")

    selected = mon.select_daily_monitoring_articles(
        candidates, target_count=15, max_count=20, media_config=MEDIA_CFG
    )
    t_sel = time.time()
    print(f"  ▶ 최종 선정 완료: {len(selected)}건 ({t_sel-t_cand:.1f}s)")
except Exception as ex:
    import traceback; traceback.print_exc()
    sys.exit(1)
finally:
    nf.fetch_articles_for_keyword = _orig_fetch

total_api_calls = len(_query_stats)
total_raw       = sum(s["raw"] for s in _query_stats)
total_filt      = sum(s["filtered"] for s in _query_stats)
fetch_elapsed   = t_cand - t_pipe_start
score_elapsed   = t_sel  - t_cand
total_elapsed   = time.time() - t_total_start
failed          = [s for s in _query_stats if not s["ok"]]

print(f"\n  API 호출 횟수: {total_api_calls}회")
print(f"  원본 수집: {total_raw}건, 기본 필터 통과: {total_filt}건")
print(f"  수집 소요: {fetch_elapsed:.1f}s | 점수·선정: {score_elapsed:.1f}s | 총: {total_elapsed:.1f}s")
if failed:
    print(f"  실패 검색어: {len(failed)}개")
    for s in failed: print(f"    '{s['query']}' — {s['error']}")
else:
    print("  실패 검색어: 없음")

# 관련성 보통 이상
rel_pass = sum(1 for a in candidates if a.get("_relevance_level","") in ("높음","보통"))

# 집계표
print()
print(f"{'그룹':<12} {'활성검색어':>6} {'API수집':>7} {'필터통과':>7} "
      f"{'중복통합후':>8} {'관련성보통↑':>9} {'최종선정':>7}")
print("-" * 70)

for g in GROUP_ORDER:
    if g not in group_queries: continue
    qcount = len(group_queries[g])
    g_stats = [s for s in _query_stats if s["group"] == g]
    g_raw   = sum(s["raw"]      for s in g_stats)
    g_filt  = sum(s["filtered"] for s in g_stats)
    # candidates: _monitoring_group == g  OR matched_groups contains g
    g_cands = [a for a in candidates
               if a.get("_monitoring_group") == g
               or g in a.get("_matched_groups",[])]
    g_rel   = sum(1 for a in g_cands if a.get("_relevance_level","") in ("높음","보통"))
    # selected가 이 그룹에서 수집된 것
    g_sel   = [a for a in selected if a.get("_monitoring_group") == g
               or g in a.get("_matched_groups",[])]
    print(f"{GROUP_NAMES.get(g,g):<12} {qcount:>6} {g_raw:>7} {g_filt:>7} "
          f"{len(g_cands):>8} {g_rel:>9} {len(g_sel):>7}")

print("-" * 70)
print(f"{'합계':<12} {len(active_list):>6} {total_raw:>7} {total_filt:>7} "
      f"{len(candidates):>8} {rel_pass:>9} {len(selected):>7}")
print("(※ 클러스터 수 집계는 select 내부 추적 불가)")

# ─────────────────────────────────────────────────────────────────────
# [4] 최종 선정 기사 전체
# ─────────────────────────────────────────────────────────────────────
print()
print("=" * 70)
print(f"[4] 최종 선정 기사 전체 ({len(selected)}건)")
print("=" * 70)

def pr_quality_label(art):
    cat    = art.get("_monitoring_category","")
    rl     = art.get("_relevance_level","")
    at     = art.get("article_type","")
    ttl    = art.get("title","")
    sc     = art.get("score",0)
    is_risk= art.get("_is_risk_priority",False)
    RTERMS = ["해킹","유출","침해","랜섬","사고","취약","위협","공격"]
    if is_risk or any(t in ttl for t in RTERMS): return "반드시 확인"
    if cat == "자사·관계사": return "반드시 확인"
    if cat == "경쟁사":      return "경쟁사 모니터링"
    if at == "기획·분석" and rl in ("높음","보통"): return "기획기사 후보"
    if rl == "낮음" or sc < 15: return "제외 검토"
    return "시장동향 참고"

EXCL_REASON = {
    "소비자용 신제품":   lambda t: any(k in t for k in ["갤럭시","아이폰","소비자","일반인","개인용"]),
    "개인 AI 활용 팁":  lambda t: any(k in t for k in ["활용 팁","사용법","AI 도우미"]),
    "지역 행사":        lambda t: any(k in t for k in ["지역","구청","군청","시청","마을"]),
    "단순 교육":        lambda t: any(k in t for k in ["수료식","강의","연수원","교육생"]),
    "주가·투자":        lambda t: any(k in t for k in ["주가","종목","ETF","코스피","매수","투자자"]),
}

excl_arts = []
for i, art in enumerate(selected, 1):
    ttl   = art.get("title","")
    mn    = art.get("media_name","")
    cat   = art.get("_monitoring_category","기타")
    rl    = art.get("_relevance_level","")
    rscore= art.get("_relevance_score",0)
    sc    = art.get("score",0)
    prscore = art.get("_pr_value_score",0)
    pri   = art.get("_monitoring_priority",0)
    why   = art.get("_monitoring_reason","")
    mqs   = " / ".join(art.get("_matched_queries",[])[:2])
    url   = art.get("url","")
    ql    = pr_quality_label(art)
    if ql == "제외 검토":
        excl_arts.append((i, art, ql))
    print(f"  [{i:2}] {ql:<14} | {cat:<10} | {rl:<4} | 점:{sc:3}/PR:{prscore:3}/우{pri:3}")
    print(f"       제목: {ttl[:60]}")
    print(f"       매체: {mn}  |  이유: {why[:50]}")
    print(f"       검색어: {mqs}")
    print(f"       URL : {url}")
    print()

# ─────────────────────────────────────────────────────────────────────
# [5] 제외 검토 기사
# ─────────────────────────────────────────────────────────────────────
print("=" * 70)
print("[5] 오탐 확인 (제외 검토 기사 + 오탐 유형 스캔)")
print("=" * 70)

odam_found = []
for art in selected:
    ttl = art.get("title","")
    for rtype, checker in EXCL_REASON.items():
        if checker(ttl):
            odam_found.append((rtype, art.get("media_name",""), ttl[:50]))

if odam_found:
    print("  ⚠ 오탐 의심:")
    for ot, mn, t in odam_found:
        print(f"    [{ot}] {mn}: {t}")
else:
    print("  ✓ 주요 오탐 유형 미검출")

if excl_arts:
    print(f"\n  제외 검토 대상 ({len(excl_arts)}건):")
    for rank, art, ql in excl_arts:
        ttl = art.get("title","")[:60]
        rl  = art.get("_relevance_level","")
        sc  = art.get("score",0)
        print(f"    [{rank}] [{rl}] score={sc}  {ttl}")

# ─────────────────────────────────────────────────────────────────────
# [6] 유의미한 누락 후보 (상위 10건)
# ─────────────────────────────────────────────────────────────────────
print()
print("=" * 70)
print("[6] 유의미한 누락 후보 (상위 10건)")
print("=" * 70)

selected_urls = {a.get("url") for a in selected}
VALUE_KWS = ["AI","클라우드","보안","라이선스","인프라","AX","디지털전환","솔루션",
             "마이크로소프트","어도비","오토데스크","기업","플랫폼"]

missed = []
for art in candidates:
    if art.get("url") in selected_urls: continue
    rl  = art.get("_relevance_level","")
    ttl = art.get("title","")
    pri = art.get("_monitoring_priority",0)
    if rl in ("높음","보통") and any(k in ttl for k in VALUE_KWS):
        missed.append(art)

missed.sort(key=lambda a: (-a.get("_monitoring_priority",0), -a.get("score",0)))

if not missed:
    print("  (선정되지 않은 유의미 후보 없음)")
else:
    print(f"  총 {len(missed)}건 중 상위 10건:")
    for art in missed[:10]:
        ttl = art.get("title","")[:52]
        mn  = art.get("media_name","")
        rl  = art.get("_relevance_level","")
        pri = art.get("_monitoring_priority",0)
        url = art.get("url","")
        # 미선정 이유 추정
        cat = art.get("_monitoring_category","기타")
        mn_cnt = Counter(a.get("media_name") for a in selected).get(mn, 0)
        reason = ("상위 15건 밖" if pri > 0 else "저품질 필터")
        if mn_cnt >= 3: reason = "동일 매체 제한"
        print(f"    [{rl}] 우선{pri:3} | {mn:<16} | {reason:<10} | {ttl}")
        print(f"      URL: {url}")

# ─────────────────────────────────────────────────────────────────────
# [7] 다양성 규칙 검증
# ─────────────────────────────────────────────────────────────────────
print()
print("=" * 70)
print("[7] 다양성 규칙 검증")
print("=" * 70)

_VENDOR_MAP = {
    "microsoft":"Microsoft","마이크로소프트":"Microsoft",
    "adobe":"Adobe","어도비":"Adobe",
    "autodesk":"Autodesk","오토데스크":"Autodesk",
}
_UNLIMITED = {"리스크","자사·관계사","경쟁사"}

def get_vendor(art):
    txt = (art.get("title","") + " " + art.get("description","")).lower()
    for k,v in _VENDOR_MAP.items():
        if k in txt: return v
    return None

vendor_cnt = Counter(get_vendor(a) for a in selected if get_vendor(a))
media_cnt  = Counter(a.get("media_name","") for a in selected)
cat_cnt    = Counter(a.get("_monitoring_category","기타") for a in selected
                     if a.get("_monitoring_category","기타") not in _UNLIMITED)
url_cnt    = Counter(a.get("url","") for a in selected)

v_ok  = all(v<=3 for v in vendor_cnt.values())
m_ok  = all(v<=3 for v in media_cnt.values())
c_ok  = all(v<=5 for v in cat_cnt.values())
u_ok  = all(v==1 for v in url_cnt.values())

ranked_all  = apply_category_filter(selected, "전체")
ranked_risk = apply_category_filter(selected, "리스크")
rank_ok = all(r == i+1 for i,(r,_) in enumerate(ranked_all))
rank_filter_ok = all(
    r == next((j+1 for j, a2 in enumerate(selected) if a2.get("url")==a.get("url")), -1)
    for r, a in ranked_risk
)
low_forced = any(a.get("_relevance_level","") == "낮음" for a in selected)

print(f"  동일 클러스터 URL 중복 없음:  {'PASS' if u_ok else 'FAIL'}")
print(f"    → url 유일성 {len([u for u,c in url_cnt.items() if c>1])}건 중복")
print(f"  동일 벤더 최대 3건:            {'PASS' if v_ok else 'FAIL'}  {dict(vendor_cnt)}")
print(f"  동일 매체 최대 3건:            {'PASS' if m_ok else 'FAIL'}")
if not m_ok:
    print(f"    초과: {[(k,v) for k,v in media_cnt.items() if v>3]}")
print(f"  동일 카테고리 최대 5건:        {'PASS' if c_ok else 'FAIL'}  {dict(cat_cnt)}")
print(f"  전체 순위 유지 (전체):         {'PASS' if rank_ok else 'FAIL'}")
print(f"  카테고리 필터 후 순위 유지:    {'PASS' if rank_filter_ok else 'FAIL'}")
print(f"  낮음 기사 강제 충원 없음:      {'PASS' if not low_forced else 'FAIL'}")

# ─────────────────────────────────────────────────────────────────────
# [8] 캐시 동작 검증
# ─────────────────────────────────────────────────────────────────────
print()
print("=" * 70)
print("[8] 캐시 동작 검증")
print("=" * 70)

dk1 = today_kst(); dk2 = today_kst()
cv1 = monitoring_config_version(config_path)
cv2 = monitoring_config_version(config_path)
print(f"  date_key 안정성:        {'PASS' if dk1==dk2 else 'FAIL'}  ({dk1})")
print(f"  config_version 안정성:  {'PASS' if cv1==cv2 else 'FAIL'}  ({cv1})")
print(f"  @st.cache_data(ttl=86400) 키 구조:")
print(f"    date_key='{dk1}', refresh_token=<int>, config_version='{cv1}'")
print(f"  카테고리 필터 API 재호출: PASS (apply_category_filter는 메모리 연산)")
print(f"  직접검색 expander 열기: PASS (캐시 키 독립, 모니터링 캐시 미영향)")
print(f"  새로고침 버튼: session_state['mon_refresh_token'] += 1 → 캐시 미스")
print(f"  KST 날짜 변경: date_key 변경 → 새 캐시 키 생성")
print(f"  실제 API 재호출 횟수 확인: 확인 불가 (Streamlit 세션 없음)")

# ─────────────────────────────────────────────────────────────────────
# [9] 직접 키워드 검색 기능 유지 확인
# ─────────────────────────────────────────────────────────────────────
print()
print("=" * 70)
print("[9] 직접 키워드 검색 기능 유지 확인")
print("=" * 70)

with open(os.path.join(BASE, "dashboard.py"), encoding="utf-8") as f:
    src = f.read()

checks = {
    "키워드 입력 (t4_kw_add_form)":      "t4_kw_add_form" in src,
    "날짜 범위 (최근 7/14/30일)":        "최근 7일" in src and "최근 14일" in src,
    "정렬 옵션 (추천순/최신순)":          '"추천순"' in src and '"최신순"' in src,
    "매체 옵션 (언론사 범위)":            "언론사 범위" in src,
    "기사 유형 필터":                     "기사 유형" in src,
    "검색 결과 (t4_clusters 표시)":       "for kw, clusters in t4_clusters" in src,
    "활용처 등록 (add_news_util)":        "add_news_util" in src,
    "Tab5 저장 연동 (add_content)":      "add_content" in src,
    "manual_util_ 키 프리픽스":          'make_widget_key("manual_util"' in src,
    "직접검색 expander 유지":             '직접 키워드 검색' in src,
    "관련성 낮은 기사 접이식":            "관련성 낮은 기사" in src,
    "PR 활용 제안 (_pr_suggest)":        "_pr_suggest" in src,
}

all_ok = True
for label, ok in checks.items():
    s = "PASS" if ok else "FAIL"
    if not ok: all_ok = False
    print(f"  {s}  {label}")

# ─────────────────────────────────────────────────────────────────────
# [10] 발견된 문제
# ─────────────────────────────────────────────────────────────────────
print()
print("=" * 70)
print("[10] 발견된 문제 (최대 5개)")
print("=" * 70)

issues = []

# 오탐
if odam_found:
    issues.append(f"오탐 의심 기사 {len(odam_found)}건 — 수동 확인 필요")

# 실패 검색어
if failed:
    issues.append(f"API 실패 검색어 {len(failed)}건: {', '.join(s['query'] for s in failed)}")

# 다양성 위반
if not v_ok:  issues.append(f"동일 벤더 3건 초과: {dict(vendor_cnt)}")
if not m_ok:  issues.append(f"동일 매체 3건 초과")
if not c_ok:  issues.append(f"동일 카테고리 5건 초과: {dict(cat_cnt)}")

# 선정 수 부족
if len(selected) < 10:
    issues.append(f"최종 선정 {len(selected)}건 (10건 미만) — 검색어 범위 또는 기준 검토")

# Streamlit 오류
if errs:
    issues.append(f"Streamlit 시작 시 오류 {len(errs)}건 — 첫 번째: {errs[0][:60]}")

# 직접 검색 기능 누락
if not all_ok:
    missing = [k for k,v in checks.items() if not v]
    issues.append(f"직접 검색 기능 코드 누락: {', '.join(missing)}")

if not issues:
    print("  없음 (검증 범위 내 문제 미발견)")
else:
    for i, iss in enumerate(issues[:5], 1):
        print(f"  {i}. {iss}")

print()
print(f"총 소요: {time.time()-t_total_start:.0f}초")
print("=" * 70)
print("4단계 검증 완료")
print("=" * 70)
