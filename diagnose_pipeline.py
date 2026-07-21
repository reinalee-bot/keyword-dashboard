"""
관련성 판정 진단 스크립트 — 코드 수정 없이 원인만 분석
실행: python diagnose_pipeline.py > diag_out.txt 2>&1
"""

import os, sys, re
from datetime import datetime, timedelta, timezone
from functools import lru_cache

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv()

import news_fetcher as nf
import relevance_scorer as rs
rs._load_config.cache_clear()

CID       = os.getenv("NAVER_CLIENT_ID",     "").strip()
CSC       = os.getenv("NAVER_CLIENT_SECRET", "").strip()
MEDIA_CFG = nf.load_media_config()
DATE_TO   = datetime.now(timezone.utc).strftime("%Y-%m-%d")
DATE_FROM = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")

cfg = rs._load_config()

# ─── 내부 로직 재현 함수 ──────────────────────────────────────────────────────
def _lower(lst):
    return [str(x).lower() for x in (lst or [])]

def _hits(text, terms):
    return [t for t in terms if t in text]

def _check_ambiguous(term_key, text):
    ambig = cfg.get("ambiguous_terms", {})
    if term_key not in ambig: return True
    entry = ambig[term_key]
    inv_list = [str(x).lower() for x in (entry.get("invalid_context") or [])]
    vld_list = [str(x).lower() for x in (entry.get("valid_context")   or [])]
    for inv in inv_list:
        if inv in text: return False
    for vld in vld_list:
        if vld in text: return True
    return False

def _cosentence_check(tl, dl, topic_h, impact_h):
    for imp in impact_h:
        if imp in tl: return True
    for sent in re.split(r"[.!?\n。…]", dl):
        sl = sent.strip()
        if any(t in sl for t in topic_h) and any(imp in sl for imp in impact_h):
            return True
    return False

def _keyword_in_title(keyword, tl):
    if not keyword: return False
    kl = re.escape(keyword.lower())
    return bool(re.search(r'(?<![a-zA-Z가-힣])' + kl + r'(?![a-zA-Z가-힣])', tl))

AMBIG_MAP = {"예산": "예산", "규제": "규제", "비용": "비용", "비용 절감": "비용"}

def _filter_impacts(imp_list, cx):
    result = []
    for imp in imp_list:
        if imp in AMBIG_MAP:
            if _check_ambiguous(AMBIG_MAP[imp], cx): result.append(imp)
        else:
            result.append(imp)
    return result

VENDORS = _lower(cfg.get("vendor_entities", []))
TOPICS  = _lower(cfg.get("business_topics", []))
IMPACTS = _lower(cfg.get("enterprise_impact", []))
RISKS   = _lower(cfg.get("risk_terms", []))
BROAD_CTX = _lower(cfg.get("broad_context_terms", []))

QT = cfg.get("query_types", {})
def get_query_type(kw):
    kl = (kw or "").lower().strip()
    for qtype, kws in QT.items():
        for k in (kws or []):
            if str(k).lower() == kl: return qtype
    return "unknown"

def trace(title, desc, query_keyword):
    """기사 하나의 판정 경로를 모두 추적해 dict 반환."""
    tl = (title or "").lower()
    dl = (desc  or "").lower()
    cx = tl + " " + dl

    q_type = get_query_type(query_keyword)

    vendor_h  = _hits(cx, VENDORS)
    topic_h   = _hits(cx, TOPICS)
    impact_h  = _hits(cx, IMPACTS)
    risk_h    = _hits(cx, RISKS)

    mid = len(tl) // 2
    vendor_is_title_subj = bool(vendor_h and any(
        tl.find(v) != -1 and tl.find(v) <= mid for v in vendor_h
    ))

    valid_impacts = _filter_impacts(impact_h, cx)

    kw_in_tl     = _keyword_in_title(query_keyword, tl)
    topic_in_tl  = any(t in tl for t in topic_h) or kw_in_tl

    topic_for_cosent = list(topic_h)
    if query_keyword:
        topic_for_cosent.append(query_keyword.lower())
    cosentence = _cosentence_check(tl, dl, topic_for_cosent, valid_impacts) if valid_impacts else False
    broad_ctx_hit = kw_in_tl and any(b in tl for b in BROAD_CTX)

    # valid_risks
    valid_risks = []
    for r in risk_h:
        if r == "장애":
            if _check_ambiguous("장애", cx): valid_risks.append(r)
        else:
            valid_risks.append(r)

    # 점수 경로별 계산 (감점·캡 이전)
    v_raw = 0
    if vendor_h:
        if valid_impacts:
            if q_type == "vendor" and not vendor_is_title_subj:
                v_raw = min(30, 20 + len(valid_impacts) * 5)
            else:
                v_raw = 70 if len(valid_impacts) >= 2 else 65
        else:
            v_raw = 15 if _hits(cx, _lower(cfg.get("promotional_terms", []))) else 20

    t_raw = 0
    if topic_h:
        n_t = len(topic_h); n_i = len(valid_impacts)
        if q_type == "broad_topic":
            if n_i >= 2 and topic_in_tl and cosentence: t_raw = 55
            elif n_i == 1 and topic_in_tl and cosentence: t_raw = 40
            elif n_t >= 3 and topic_in_tl: t_raw = 35
            elif broad_ctx_hit: t_raw = 35
            elif topic_in_tl: t_raw = 20
            else: t_raw = 10
        else:
            if n_i >= 2: t_raw = 70
            elif n_i == 1: t_raw = 55
            elif n_t >= 2: t_raw = 35
            else: t_raw = 20

    r_raw = 0
    if valid_risks:
        has_ctx = bool(vendor_h or topic_h)
        if q_type == "broad_topic": r_raw = 30 if has_ctx else 10
        elif has_ctx: r_raw = 70
        else: r_raw = 40

    pre_cap = max(v_raw, t_raw, r_raw)

    # vendor 최종 상한 적용 여부
    cap_applied = (q_type == "vendor" and bool(vendor_h) and not vendor_is_title_subj
                   and pre_cap > 30)
    post_cap = min(pre_cap, 30) if cap_applied else pre_cap

    return {
        "q_type": q_type,
        "vendor_h": vendor_h,
        "vendor_is_title_subj": vendor_is_title_subj,
        "topic_h": topic_h,
        "topic_in_tl": topic_in_tl,
        "kw_in_tl": kw_in_tl,
        "broad_ctx_hit": broad_ctx_hit,
        "impact_h": impact_h,
        "valid_impacts": valid_impacts,
        "valid_risks": valid_risks,
        "cosentence": cosentence,
        "v_raw": v_raw, "t_raw": t_raw, "r_raw": r_raw,
        "pre_cap": pre_cap,
        "cap_applied": cap_applied,
        "post_cap": post_cap,
    }

# ─── 수집 ────────────────────────────────────────────────────────────────────
def fetch(kw, display=100):
    return nf.fetch_articles_for_keyword(
        keyword=kw, date_from=DATE_FROM, date_to=DATE_TO,
        sort_api="date", media_scope="all", article_type_filter="",
        cid=CID, csc=CSC, media_config=MEDIA_CFG, display=display,
    )

print(f"진단 기간: {DATE_FROM} ~ {DATE_TO}\n")

KW_CONFIGS = {
    "AI":        {"sample_low": 15, "sample_mode": "score_desc"},
    "AX":        {"sample_low": 10, "sample_mode": "score_desc"},
    "Microsoft": {"sample_low": 15, "sample_mode": "score_desc"},
    "Adobe":     {"sample_low": 99, "sample_mode": "score_desc"},
    "디모아":     {"sample_low": 99, "sample_mode": "score_desc"},
}

all_results = {}
for kw in KW_CONFIGS:
    all_results[kw] = fetch(kw)

# ─── 규칙별 통계 집계 ────────────────────────────────────────────────────────
def count_stats(kw, arts):
    stats = {
        "vendor_cap_applied": 0,
        "precap_ge35_capped": 0,
        "no_kw_in_tl_낮음":  0,
        "no_cosentence_낮음": 0,
        "consumer_deduct":    0,
        "promo_deduct":       0,
        "foreign_excluded":   all_results[kw].get("foreign_count", 0),
        "quality_excluded":   all_results[kw].get("raw_count", 0)
                              - all_results[kw].get("filtered_count", 0)
                              - all_results[kw].get("foreign_count", 0),
    }
    local_  = _lower(cfg.get("consumer_or_local_terms", []))
    promos_ = _lower(cfg.get("promotional_terms", []))

    for a in arts:
        t = trace(a["title"], a["description"], kw)
        cx = (a["title"] + " " + a["description"]).lower()
        lvl = a.get("_relevance_level", "낮음")
        if t["cap_applied"]:
            stats["vendor_cap_applied"] += 1
            if t["pre_cap"] >= 35:
                stats["precap_ge35_capped"] += 1
        if t["q_type"] == "broad_topic" and not t["kw_in_tl"] and not t["topic_h"] and lvl == "낮음":
            stats["no_kw_in_tl_낮음"] += 1
        if (t["q_type"] == "broad_topic" and t["topic_in_tl"] and t["valid_impacts"]
                and not t["cosentence"] and lvl == "낮음"):
            stats["no_cosentence_낮음"] += 1
        if any(l in cx for l in local_):
            stats["consumer_deduct"] += 1
        if any(p in cx for p in promos_) and not t["valid_impacts"]:
            stats["promo_deduct"] += 1
    return stats

# ─── 헤더 출력 ───────────────────────────────────────────────────────────────
SEP  = "=" * 100
SEP2 = "-" * 100

def truncate(s, n): return (s[:n] + "…") if len(s) > n else s

def print_table_header():
    print(f"{'제목':40}  {'매체':14}  {'점수':>4}  {'레벨':4}  "
          f"{'q_type':10}  {'kw제목':5}  {'tsubj':5}  {'cosent':6}  "
          f"{'precap':>6}  {'cap':3}  {'비고'}")
    print(SEP2)

def print_row(a, kw):
    t = trace(a["title"], a["description"], kw)
    title    = truncate(a.get("title", ""), 40)
    media    = truncate(a.get("media_name", ""), 14)
    score    = a.get("_relevance_score", 0)
    lvl      = a.get("_relevance_level", "?")
    pre      = t["pre_cap"]
    cap_str  = "Y" if t["cap_applied"] else " "
    kw_tl    = "Y" if t["kw_in_tl"] else " "
    ts       = "Y" if t["vendor_is_title_subj"] else " "
    cos_str  = "Y" if t["cosentence"] else " "
    q        = t["q_type"]

    # 비고: 핵심 원인
    note = []
    if t["cap_applied"]:      note.append(f"CAP({pre}→30)")
    if not t["topic_h"] and t["q_type"] == "broad_topic": note.append("주제없음")
    if t["topic_in_tl"] and t["valid_impacts"] and not t["cosentence"]:
        note.append("동문장X")
    if t["vendor_h"] and not t["valid_impacts"] and t["q_type"] == "vendor":
        note.append("impact없음")
    if not t["vendor_is_title_subj"] and t["vendor_h"] and t["q_type"] == "vendor":
        note.append("타사")
    if t["valid_impacts"]:    note.append(f"impact:{','.join(t['valid_impacts'][:2])}")
    if t["valid_risks"]:      note.append(f"risk:{t['valid_risks'][0]}")
    note_str = " | ".join(note)[:60]

    url = a.get("url", "")[:80]
    print(f"{title:40}  {media:14}  {score:>4}  {lvl:4}  "
          f"{q:10}  {kw_tl:5}  {ts:5}  {cos_str:6}  "
          f"{pre:>6}  {cap_str:3}  {note_str}")
    if url:
        print(f"  URL: {url}")

# ═════════════════════════════════════════════════════════════════════════════
# 1. AI
# ═════════════════════════════════════════════════════════════════════════════
print(SEP)
print("▶ 키워드: AI")
print(SEP)
ai_arts = all_results["AI"]["articles"]
ai_low  = [a for a in ai_arts if a.get("_relevance_level") == "낮음"]

# 유의미 후보 선별: vendor_h 있거나, topic_h 있고 점수 높은 순
def relevance_signal(a, kw):
    t = trace(a["title"], a["description"], kw)
    return (len(t["vendor_h"]) * 20 + len(t["topic_h"]) * 10
            + len(t["valid_impacts"]) * 15 + a.get("_relevance_score", 0))

ai_low_sorted = sorted(ai_low, key=lambda a: relevance_signal(a, "AI"), reverse=True)[:15]

print(f"\n[AI] 총 {len(ai_arts)}건 → 높음:{sum(1 for a in ai_arts if a.get('_relevance_level')=='높음')} "
      f"보통:{sum(1 for a in ai_arts if a.get('_relevance_level')=='보통')} "
      f"낮음:{len(ai_low)}")
print("\n◆ 낮음 기사 중 유의미 후보 상위 15건")
print_table_header()
for a in ai_low_sorted:
    print_row(a, "AI")
print()

# ═════════════════════════════════════════════════════════════════════════════
# 2. AX
# ═════════════════════════════════════════════════════════════════════════════
print(SEP)
print("▶ 키워드: AX")
print(SEP)
ax_arts = all_results["AX"]["articles"]
ax_med  = [a for a in ax_arts if a.get("_relevance_level") in ("높음","보통")]
ax_low  = [a for a in ax_arts if a.get("_relevance_level") == "낮음"]
ax_low_top = sorted(ax_low, key=lambda a: relevance_signal(a, "AX"), reverse=True)[:10]

print(f"\n[AX] 총 {len(ax_arts)}건 → 보통:{len(ax_med)} 낮음:{len(ax_low)}")
print("\n◆ 보통 이상 전체")
print_table_header()
for a in ax_med: print_row(a, "AX")
print("\n◆ 낮음 상위 10건")
print_table_header()
for a in ax_low_top: print_row(a, "AX")
print()

# ═════════════════════════════════════════════════════════════════════════════
# 3. Microsoft
# ═════════════════════════════════════════════════════════════════════════════
print(SEP)
print("▶ 키워드: Microsoft")
print(SEP)
ms_arts = all_results["Microsoft"]["articles"]
ms_low  = [a for a in ms_arts if a.get("_relevance_level") == "낮음"]
ms_low_sorted = sorted(ms_low, key=lambda a: relevance_signal(a, "Microsoft"), reverse=True)[:15]

print(f"\n[Microsoft] 총 {len(ms_arts)}건 → 높음:{sum(1 for a in ms_arts if a.get('_relevance_level')=='높음')} "
      f"보통:{sum(1 for a in ms_arts if a.get('_relevance_level')=='보통')} "
      f"낮음:{len(ms_low)}")
print("\n◆ 낮음 기사 중 유의미 후보 상위 15건")
print_table_header()
for a in ms_low_sorted:
    print_row(a, "Microsoft")
print()

# ═════════════════════════════════════════════════════════════════════════════
# 4. Adobe
# ═════════════════════════════════════════════════════════════════════════════
print(SEP)
print("▶ 키워드: Adobe")
print(SEP)
ab_arts = all_results["Adobe"]["articles"]
print(f"\n[Adobe] 총 {len(ab_arts)}건")
print_table_header()
for a in ab_arts: print_row(a, "Adobe")
print()

# ═════════════════════════════════════════════════════════════════════════════
# 5. 디모아
# ═════════════════════════════════════════════════════════════════════════════
print(SEP)
print("▶ 키워드: 디모아")
print(SEP)
dm_arts = all_results["디모아"]["articles"]
print(f"\n[디모아] 총 {len(dm_arts)}건")
print_table_header()
for a in dm_arts: print_row(a, "디모아")
print()

# ═════════════════════════════════════════════════════════════════════════════
# 6. 규칙별 영향 건수 집계
# ═════════════════════════════════════════════════════════════════════════════
print(SEP)
print("▶ [규칙별 영향 건수]")
print(SEP)
print(f"\n{'규칙':36}  {'AI':>5}  {'AX':>5}  {'MS':>5}  {'Adobe':>5}  {'디모아':>6}")
print("-" * 72)
for kw, label in [("AI","AI"),("AX","AX"),("Microsoft","MS"),("Adobe","Adobe"),("디모아","디모아")]:
    pass

stats_all = {}
for kw in KW_CONFIGS:
    stats_all[kw] = count_stats(kw, all_results[kw]["articles"])

rows_stat = [
    ("vendor 상한 적용 건수",      "vendor_cap_applied"),
    ("  └ pre_cap≥35 → 30으로 낮아짐", "precap_ge35_capped"),
    ("쿼리어 제목 없어 낮음",       "no_kw_in_tl_낮음"),
    ("동일문장 미검출로 낮음",       "no_cosentence_낮음"),
    ("소비자·지역 감점",            "consumer_deduct"),
    ("홍보성 감점",                 "promo_deduct"),
    ("외국어 제외",                 "foreign_excluded"),
    ("저품질·날짜·기타 제외",       "quality_excluded"),
]

kws = list(KW_CONFIGS.keys())
header = f"{'규칙':36}  " + "  ".join(f"{k[:6]:>6}" for k in kws)
print(header)
print("-" * (len(header) + 4))
for label, key in rows_stat:
    vals = "  ".join(f"{stats_all[k].get(key,0):>6}" for k in kws)
    print(f"{label:36}  {vals}")

# ═════════════════════════════════════════════════════════════════════════════
# 7. 이전 유의미 기사 유형 추적
# ═════════════════════════════════════════════════════════════════════════════
print()
print(SEP)
print("▶ [이전 유의미 기사 유형 추적]")
print(SEP)

EXPECTED_TYPES = {
    "SAP 기업 AI·라이선스":          {"kw": "AI",        "kw_in": ["sap"],          "topic_in": ["라이선스","기업 ai"]},
    "Microsoft 라이선스·총판":        {"kw": "Microsoft", "kw_in": ["라이선스","총판"], "topic_in": []},
    "Microsoft 보안정책·취약점":      {"kw": "Microsoft", "kw_in": ["보안","취약점","취약"], "topic_in": []},
    "Microsoft 클라우드비용·AI투자":  {"kw": "Microsoft", "kw_in": ["클라우드","비용","투자"], "topic_in": []},
    "Adobe 취약점 패치":             {"kw": "Adobe",     "kw_in": ["취약점","취약","패치"], "topic_in": []},
    "Adobe 구독료·파트너십":         {"kw": "Adobe",     "kw_in": ["구독","파트너"], "topic_in": []},
    "Adobe 기업 도입·활용":          {"kw": "Adobe",     "kw_in": ["도입","활용"], "topic_in": []},
    "삼성SDS·NPUaaS":               {"kw": "AI",        "kw_in": ["삼성sds","npuaas","npu"], "topic_in": []},
    "최태원 제조업 AI 전략":          {"kw": "AX",        "kw_in": ["최태원","sk","제조업"], "topic_in": []},
    "KTL 산업AI·제조기업AX":         {"kw": "AX",        "kw_in": ["ktl","제조","제조기업"], "topic_in": []},
}

def find_in_arts(arts, kw_in_list):
    kw_in_lower = [k.lower() for k in kw_in_list]
    return [a for a in arts if any(k in (a.get("title","") + " " + a.get("description","")).lower()
                                   for k in kw_in_lower)]

print()
for label, crit in EXPECTED_TYPES.items():
    arts = all_results[crit["kw"]]["articles"]
    matches = find_in_arts(arts, crit["kw_in"])
    if not matches:
        print(f"[{label}]  → API 검색 결과에 없음 (7일 이내 해당 기사 없음)")
    else:
        for a in matches[:3]:
            lvl   = a.get("_relevance_level", "?")
            score = a.get("_relevance_score", 0)
            t_info= trace(a["title"], a["description"], crit["kw"])
            cap_note = f" CAP({t_info['pre_cap']}→30)" if t_info["cap_applied"] else ""
            why_low = ""
            if lvl == "낮음":
                if not t_info["topic_h"] and not t_info["vendor_h"]:
                    why_low = " [SCK맥락없음]"
                elif t_info["cap_applied"]:
                    why_low = f" [vendor상한{cap_note}]"
                elif t_info["vendor_h"] and not t_info["valid_impacts"]:
                    why_low = " [impact없음]"
                elif t_info["topic_in_tl"] and t_info["valid_impacts"] and not t_info["cosentence"]:
                    why_low = " [동일문장X]"
                else:
                    reasons = a.get("_low_relevance_reason","")
                    why_low = f" [{reasons[:40]}]"
            title_s = truncate(a.get("title",""), 55)
            print(f"[{label}]  {lvl}({score}){cap_note}{why_low}")
            print(f"  제목: {title_s}")
            print(f"  근거: {'; '.join(a.get('_relevance_reasons',[])[:2])}")
            print(f"  URL:  {a.get('url','')[:90]}")
    print()

# ═════════════════════════════════════════════════════════════════════════════
# 8. 상세 원인 분석 — Microsoft 상한 적용 전 점수 분포
# ═════════════════════════════════════════════════════════════════════════════
print(SEP)
print("▶ [Microsoft 판정 경로 분포]")
print(SEP)

ms_dist = {
    "vendor_subj_with_impact":    [],
    "vendor_subj_no_impact":      [],
    "vendor_nonsubj_with_impact": [],
    "vendor_nonsubj_no_impact":   [],
    "no_vendor_topic_only":       [],
    "no_vendor_no_topic":         [],
}

for a in ms_arts:
    t = trace(a["title"], a["description"], "Microsoft")
    if t["vendor_h"]:
        if t["vendor_is_title_subj"]:
            if t["valid_impacts"]: ms_dist["vendor_subj_with_impact"].append(a)
            else:                  ms_dist["vendor_subj_no_impact"].append(a)
        else:
            if t["valid_impacts"]: ms_dist["vendor_nonsubj_with_impact"].append(a)
            else:                  ms_dist["vendor_nonsubj_no_impact"].append(a)
    elif t["topic_h"]:             ms_dist["no_vendor_topic_only"].append(a)
    else:                          ms_dist["no_vendor_no_topic"].append(a)

labels_ms = {
    "vendor_subj_with_impact":    "벤더=주체 + impact 있음 (→65~70 기대)",
    "vendor_subj_no_impact":      "벤더=주체 + impact 없음 (→20)",
    "vendor_nonsubj_with_impact": "벤더=타사 + impact 있음 (→30, 상한)",
    "vendor_nonsubj_no_impact":   "벤더=타사 + impact 없음 (→20)",
    "no_vendor_topic_only":       "벤더 미검출, 주제어만 (→20~55)",
    "no_vendor_no_topic":         "벤더·주제 모두 없음 (→0)",
}
for key, lbl in labels_ms.items():
    n = len(ms_dist[key])
    sample_titles = " / ".join(truncate(a.get("title",""),30) for a in ms_dist[key][:2])
    print(f"  {lbl}: {n}건")
    if sample_titles: print(f"     예) {sample_titles}")
print()

# ─── AI 원인 분석
print(SEP)
print("▶ [AI 판정 경로 분포]")
print(SEP)

ai_dist = {
    "topic_in_tl_impact_cosent":   0,
    "topic_in_tl_impact_no_cosent":0,
    "topic_in_tl_no_impact":       0,
    "kw_broad_ctx":                0,
    "kw_no_broad_ctx":             0,
    "no_topic_no_kw":              0,
}
for a in ai_arts:
    t = trace(a["title"], a["description"], "AI")
    if not t["topic_h"]:
        if t["kw_in_tl"] and t["broad_ctx_hit"]: ai_dist["kw_broad_ctx"] += 1
        elif t["kw_in_tl"]:                      ai_dist["kw_no_broad_ctx"] += 1
        else:                                     ai_dist["no_topic_no_kw"] += 1
    else:
        if t["topic_in_tl"] and t["valid_impacts"] and t["cosentence"]:
            ai_dist["topic_in_tl_impact_cosent"] += 1
        elif t["topic_in_tl"] and t["valid_impacts"] and not t["cosentence"]:
            ai_dist["topic_in_tl_impact_no_cosent"] += 1
        else:
            ai_dist["topic_in_tl_no_impact"] += 1

labels_ai = {
    "topic_in_tl_impact_cosent":    "주제+impact+동일문장 (→40~55)",
    "topic_in_tl_impact_no_cosent": "주제+impact 있으나 동일문장X (→20, 낮음)",
    "topic_in_tl_no_impact":        "주제 제목, impact 없음 (→20)",
    "kw_broad_ctx":                 "topic없음, kw_in_tl+broad_ctx (→35)",
    "kw_no_broad_ctx":              "topic없음, kw_in_tl만 (→진입X, 0)",
    "no_topic_no_kw":               "topic·kw 모두 없음 (→0)",
}
for key, lbl in labels_ai.items():
    print(f"  {lbl}: {ai_dist[key]}건")
print()

print(SEP)
print("▶ [진단 완료]")
print(SEP)
