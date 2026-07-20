"""
실제 운영 파이프라인 검증 스크립트
fetch_articles_for_keyword() 를 직접 호출해 단계별 기사 수를 집계한다.

실행: python verify_pipeline.py
"""

import os
import sys
from datetime import datetime, timedelta, timezone

# 경로 설정
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv()

import news_fetcher as nf
import relevance_scorer as rs
rs._load_config.cache_clear()

CID = os.getenv("NAVER_CLIENT_ID", "").strip()
CSC = os.getenv("NAVER_CLIENT_SECRET", "").strip()

KEYWORDS   = ["AI", "AX", "Microsoft", "Adobe", "디모아"]
DATE_TO    = datetime.now(timezone.utc).strftime("%Y-%m-%d")
DATE_FROM  = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
MEDIA_CFG  = nf.load_media_config()

print("=" * 72)
print("SCK 뉴스 파이프라인 검증 (fetch_articles_for_keyword 직접 호출)")
print(f"기간: {DATE_FROM} ~ {DATE_TO}  |  매체범위: all")
print("=" * 72)
print()

rows = []

for kw in KEYWORDS:
    res = nf.fetch_articles_for_keyword(
        keyword=kw,
        date_from=DATE_FROM,
        date_to=DATE_TO,
        sort_api="date",
        media_scope="all",
        article_type_filter="",
        cid=CID,
        csc=CSC,
        media_config=MEDIA_CFG,
        display=100,
    )

    status     = res.get("status", "?")
    raw        = res.get("raw_count", 0)
    foreign    = res.get("foreign_count", 0)
    final      = res.get("filtered_count", 0)
    articles   = res.get("articles", [])

    high   = sum(1 for a in articles if a.get("_relevance_level") == "높음")
    medium = sum(1 for a in articles if a.get("_relevance_level") == "보통")
    low    = sum(1 for a in articles if a.get("_relevance_level") == "낮음")
    check  = high + medium + low  # 검산: 이 값 == final 이어야 함

    rows.append({
        "keyword": kw, "status": status,
        "raw": raw, "foreign": foreign, "final": final,
        "high": high, "medium": medium, "low": low,
        "ok": (check == final and status == "success"),
    })

# ── 테이블 출력 ──────────────────────────────────────────────────────────────
W = 10
head = (f"{'키워드':8}  {'상태':8}  {'API원본':>6}  {'외국어제외':>6}  "
        f"{'최종':>5}  {'높음':>4}  {'보통':>4}  {'낮음':>4}  {'검산':5}")
print(head)
print("-" * len(head))

all_pass = True
for r in rows:
    flag = "✓" if r["ok"] else "✗"
    if not r["ok"]:
        all_pass = False
    line = (f"{r['keyword']:8}  {r['status']:8}  {r['raw']:>6}  {r['foreign']:>6}  "
            f"{r['final']:>5}  {r['high']:>4}  {r['medium']:>4}  {r['low']:>4}  {flag}")
    print(line)

print()
print(f"검증 결과: {'전체 PASS' if all_pass else '일부 FAIL'}")
print()

# ── 이상 기사 샘플 (높음 예시) ───────────────────────────────────────────────
print("=" * 72)
print("[높음/보통 기사 샘플 — 최대 3건씩]")
print("=" * 72)
for r in rows:
    kw = r["keyword"]
    res2 = nf.fetch_articles_for_keyword(
        keyword=kw, date_from=DATE_FROM, date_to=DATE_TO,
        sort_api="date", media_scope="all", article_type_filter="",
        cid=CID, csc=CSC, media_config=MEDIA_CFG, display=100,
    )
    arts = res2.get("articles", [])
    relevant = [a for a in arts if a.get("_relevance_level") in ("높음", "보통")][:3]
    if not relevant:
        print(f"\n[{kw}] 높음/보통 기사 없음")
        continue
    print(f"\n[{kw}]")
    for a in relevant:
        lvl   = a.get("_relevance_level", "?")
        score = a.get("_relevance_score", 0)
        title = a.get("title", "")[:60]
        reas  = " / ".join(a.get("_relevance_reasons", [])[:2])
        print(f"  [{lvl}:{score:3d}] {title}")
        print(f"         → {reas}")
