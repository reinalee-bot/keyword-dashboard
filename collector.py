"""
검색 트렌드 수집기 — CSV 저장 방식
- 네이버 데이터랩 검색어트렌드 API → source = 'naver'
- 구글 트렌드 (pytrends)           → source = 'google'
결과는 모두 data/trends.csv 에 쌓입니다.
"""

import os
import sys
import time
from datetime import datetime, timedelta

import pandas as pd
import requests
from dotenv import load_dotenv

from keywords import KEYWORDS

# 터미널 한글 출력 설정
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

load_dotenv()
CLIENT_ID     = os.getenv("NAVER_CLIENT_ID",     "").strip()
CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET", "").strip()

DATA_DIR   = os.path.join(os.path.dirname(__file__), "data")
TRENDS_CSV = os.path.join(DATA_DIR, "trends.csv")
COLS       = ["keyword", "date", "ratio", "source", "collected_at"]
API_URL    = "https://openapi.naver.com/v1/datalab/search"
BATCH      = 5   # 네이버 API 한 번 요청에 최대 5개


# ══════════════════════════════════════════════
# CSV 저장 (중복 자동 방지)
# ══════════════════════════════════════════════
def _ensure_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def save(records: list) -> tuple:
    """
    records: [(keyword, date_str, ratio, source), ...]
    반환: (새로 저장 건수, 중복 건너뜀 건수)
    """
    _ensure_dir()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 기존 데이터 로드 → 중복 키 셋 구성
    if os.path.exists(TRENDS_CSV):
        existing = pd.read_csv(TRENDS_CSV, dtype=str)
        existing_keys = set(
            zip(existing["keyword"], existing["date"], existing["source"])
        )
    else:
        existing = pd.DataFrame(columns=COLS)
        existing_keys = set()

    new_rows = []
    inserted = skipped = 0

    for keyword, date, ratio, source in records:
        key = (str(keyword), str(date)[:10], str(source))
        if key in existing_keys:
            skipped += 1
        else:
            new_rows.append([keyword, str(date)[:10], float(ratio), source, now])
            existing_keys.add(key)
            inserted += 1

    if new_rows:
        new_df  = pd.DataFrame(new_rows, columns=COLS)
        full_df = pd.concat([existing, new_df], ignore_index=True)
        full_df.to_csv(TRENDS_CSV, index=False, encoding="utf-8-sig")

    return inserted, skipped


# ══════════════════════════════════════════════
# 네이버 데이터랩 수집
# ══════════════════════════════════════════════
def _naver_fetch_batch(keywords_batch, start_date, end_date):
    headers = {
        "X-Naver-Client-Id":     CLIENT_ID,
        "X-Naver-Client-Secret": CLIENT_SECRET,
        "Content-Type":          "application/json",
    }
    body = {
        "startDate":     start_date,
        "endDate":       end_date,
        "timeUnit":      "date",
        "keywordGroups": [{"groupName": kw, "keywords": [kw]} for kw in keywords_batch],
    }
    resp = requests.post(API_URL, headers=headers, json=body, timeout=15)

    if resp.status_code == 401:
        raise RuntimeError("API 키 오류 — .env 파일의 NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 확인")
    if resp.status_code == 429:
        raise RuntimeError("요청 한도 초과 — 잠시 후 다시 실행해 주세요")
    if resp.status_code != 200:
        raise RuntimeError(f"네이버 서버 오류 (HTTP {resp.status_code})")

    return resp.json().get("results", [])


def collect_naver(days_back=30):
    print("\n[네이버] 수집 시작")

    if not CLIENT_ID or not CLIENT_SECRET:
        print("  ❌ 네이버 API 키가 없습니다. .env 파일을 확인해 주세요.")
        return 0, 0

    end_dt    = datetime.today()
    start_dt  = end_dt - timedelta(days=days_back)
    start_str = start_dt.strftime("%Y-%m-%d")
    end_str   = end_dt.strftime("%Y-%m-%d")
    print(f"  기간: {start_str} ~ {end_str}  /  키워드: {', '.join(KEYWORDS)}")

    all_results = []
    for i in range(0, len(KEYWORDS), BATCH):
        batch   = KEYWORDS[i: i + BATCH]
        results = _naver_fetch_batch(batch, start_str, end_str)
        all_results.extend(results)

    records = [
        (r["title"], pt["period"], pt["ratio"], "naver")
        for r in all_results
        for pt in r.get("data", [])
    ]
    ins, skip = save(records)
    print(f"  ✅ 완료 — 새 데이터 {ins}건  /  중복 {skip}건")
    return ins, skip


# ══════════════════════════════════════════════
# 구글 트렌드 수집
# ══════════════════════════════════════════════
def collect_google(months_back=3):
    print("\n[구글] 수집 시작")
    print("  ※ 구글은 공식 API가 아니라 가끔 차단될 수 있습니다. 실패해도 네이버 데이터는 유지됩니다.")

    try:
        from pytrends.request import TrendReq
    except ImportError:
        print("  ❌ pytrends 가 설치되지 않았습니다. 'pip install pytrends' 를 실행해 주세요.")
        return 0, 0

    try:
        pytrends = TrendReq(hl="ko-KR", tz=540, timeout=(10, 25), retries=2, backoff_factor=0.5)
        records  = []

        for i in range(0, len(KEYWORDS), BATCH):
            batch = KEYWORDS[i: i + BATCH]
            pytrends.build_payload(batch, timeframe=f"today {months_back}-m", geo="KR")
            df = pytrends.interest_over_time()

            if df.empty:
                print("  ⚠️  구글에서 데이터를 받아오지 못했습니다 (빈 응답).")
                return 0, 0

            if "isPartial" in df.columns:
                df = df.drop(columns=["isPartial"])

            for kw in batch:
                if kw not in df.columns:
                    continue
                for date_idx, ratio in df[kw].items():
                    records.append((kw, date_idx.strftime("%Y-%m-%d"), float(ratio), "google"))

            if i + BATCH < len(KEYWORDS):
                time.sleep(1)

        if not records:
            print("  ⚠️  구글 데이터가 없습니다.")
            return 0, 0

        ins, skip = save(records)
        print(f"  ✅ 완료 — 새 데이터 {ins}건  /  중복 {skip}건")
        return ins, skip

    except Exception as e:
        msg = str(e)
        if "429" in msg or "Too Many Requests" in msg:
            print("  ⚠️  구글이 일시적으로 요청을 막았습니다 (429). 내일 다시 시도해 주세요.")
        elif "timeout" in msg.lower():
            print("  ⚠️  구글 응답 시간 초과. 네트워크를 확인하거나 나중에 다시 시도해 주세요.")
        else:
            print(f"  ⚠️  구글 데이터를 오늘 받아오지 못했습니다. (오류: {msg[:80]})")
        return 0, 0


# ══════════════════════════════════════════════
# 미리보기 출력
# ══════════════════════════════════════════════
def show_preview(limit=20):
    if not os.path.exists(TRENDS_CSV):
        print("  (저장된 데이터가 없습니다)")
        return

    df = pd.read_csv(TRENDS_CSV)
    df = df.sort_values(["date", "source", "keyword"], ascending=False).head(limit)

    print(f"\n{'출처':<8}  {'키워드':<10}  {'날짜':<12}  {'관심도':>6}")
    print("─" * 44)
    for _, row in df.iterrows():
        bar   = "█" * max(0, int(float(row["ratio"]) / 8))
        label = "네이버" if row["source"] == "naver" else "구글  "
        print(f"{label:<8}  {str(row['keyword']):<10}  {str(row['date']):<12}  {float(row['ratio']):>6.1f}  {bar}")


# ══════════════════════════════════════════════
# 전체 실행
# ══════════════════════════════════════════════
def collect_all():
    print("=" * 50)
    print("  검색 트렌드 수집 시작  (네이버 + 구글)")
    print("=" * 50)

    _ensure_dir()
    collect_naver(days_back=30)
    collect_google(months_back=3)

    print("\n" + "─" * 50)
    print("  최근 수집 데이터 미리보기")
    print("─" * 50)
    show_preview(limit=20)
    print()


def collect_single_keyword(keyword: str) -> tuple:
    """
    단일 키워드를 즉시 수집합니다 (새 추적 키워드 추가 시 사용).
    반환: (naver_ok: bool, google_ok: bool)
    """
    naver_ok  = False
    google_ok = False

    # ── 네이버 ──────────────────────────────────────────
    if CLIENT_ID and CLIENT_SECRET:
        try:
            end_dt   = datetime.today()
            start_dt = end_dt - timedelta(days=30)
            results  = _naver_fetch_batch(
                [keyword],
                start_dt.strftime("%Y-%m-%d"),
                end_dt.strftime("%Y-%m-%d"),
            )
            records = [
                (r["title"], pt["period"], pt["ratio"], "naver")
                for r in results
                for pt in r.get("data", [])
            ]
            if records:
                ins, _ = save(records)
                naver_ok = ins > 0
        except Exception:
            pass

    # ── 구글 (차단될 수 있어 예외를 조용히 처리) ──────────
    try:
        from pytrends.request import TrendReq
        pytrends = TrendReq(hl="ko-KR", tz=540, timeout=(10, 25), retries=1, backoff_factor=0.5)
        pytrends.build_payload([keyword], timeframe="today 3-m", geo="KR")
        df = pytrends.interest_over_time()
        if not df.empty:
            if "isPartial" in df.columns:
                df = df.drop(columns=["isPartial"])
            if keyword in df.columns:
                records = [
                    (keyword, idx.strftime("%Y-%m-%d"), float(val), "google")
                    for idx, val in df[keyword].items()
                ]
                if records:
                    ins, _ = save(records)
                    google_ok = ins > 0
    except Exception:
        pass

    return naver_ok, google_ok


if __name__ == "__main__":
    collect_all()
