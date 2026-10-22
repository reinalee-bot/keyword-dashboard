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

from keywords import KEYWORDS as _BASE_KEYWORDS

# 터미널 한글 출력 설정
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

load_dotenv()
CLIENT_ID     = os.getenv("NAVER_CLIENT_ID",     "").strip()
CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET", "").strip()

DATA_DIR       = os.path.join(os.path.dirname(__file__), "data")
TRENDS_CSV     = os.path.join(DATA_DIR, "trends.csv")
DERIVED_CSV    = os.path.join(DATA_DIR, "tracked_keywords.csv")
COLS           = ["keyword", "date", "ratio", "source", "collected_at"]
API_URL        = "https://openapi.naver.com/v1/datalab/search"
BATCH          = 5   # 네이버 API 한 번 요청에 최대 5개

# 한글 표기만으로는 Naver DataLab 검색량이 0인 키워드 → 영문·복합표기 함께 묶어 수집
KEYWORD_SYNONYMS: dict[str, list[str]] = {
    "섀도우AI": ["섀도우AI", "Shadow AI", "섀도우 AI"],
}


def _naver_kw_group(kw: str) -> dict:
    return {"groupName": kw, "keywords": KEYWORD_SYNONYMS.get(kw, [kw])}


def _load_all_keywords() -> list:
    """기본 KEYWORDS + derived_keywords.csv 추적 키워드를 합산해 반환."""
    all_kws: list = list(_BASE_KEYWORDS)
    if os.path.exists(DERIVED_CSV):
        try:
            df = pd.read_csv(DERIVED_CSV, dtype=str)
            if "keyword" in df.columns:
                for kw in df["keyword"].dropna():
                    kw = kw.strip()
                    if kw and kw not in all_kws:
                        all_kws.append(kw)
        except Exception:
            pass
    return all_kws


KEYWORDS = _load_all_keywords()


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
        "keywordGroups": [_naver_kw_group(kw) for kw in keywords_batch],
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


# ══════════════════════════════════════════════
# 임시 비교용 수집 (trends.csv 비저장, 세션 전용)
# ══════════════════════════════════════════════
def fetch_trends_temp(
    keywords_tuple: tuple,
    ref_keyword: str = "생성형AI",
) -> tuple:
    """
    임시 키워드 비교 전용 수집 — trends.csv 에 저장하지 않는다.
    Google 트렌드는 ref_keyword 기준 정규화 (ratio_norm 컬럼 추가).
    반환: (df_trends, related_dict, google_error_msg)
      df_trends  cols : keyword, date, ratio, ratio_norm, source, collected_at
      related_dict     : {kw: {"top": DataFrame|None, "rising": DataFrame|None}}
      google_error_msg : "" = 정상, 문자열 = 오류 메시지
    """
    now_str  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    user_kws = list(keywords_tuple)

    # ── 네이버 ───────────────────────────────────────────────
    naver_records = []
    if CLIENT_ID and CLIENT_SECRET:
        try:
            end_dt   = datetime.today()
            start_dt = end_dt - timedelta(days=90)
            s_str, e_str = start_dt.strftime("%Y-%m-%d"), end_dt.strftime("%Y-%m-%d")
            for i in range(0, len(user_kws), BATCH):
                batch   = user_kws[i:i + BATCH]
                results = _naver_fetch_batch(batch, s_str, e_str)
                for r in results:
                    for pt in r.get("data", []):
                        naver_records.append({
                            "keyword":      r["title"],
                            "date":         str(pt["period"])[:10],
                            "ratio":        float(pt["ratio"]),
                            "ratio_norm":   float(pt["ratio"]),   # 네이버: 배치 내 상대값 그대로
                            "source":       "naver",
                            "collected_at": now_str,
                        })
                if i + BATCH < len(user_kws):
                    time.sleep(0.5)
        except Exception:
            pass  # 네이버 실패는 조용히 처리

    # ── 구글 ────────────────────────────────────────────────
    google_records = []
    related_dict   = {kw: {"top": None, "rising": None} for kw in user_kws}
    google_err     = ""

    try:
        from pytrends.request import TrendReq
        pytrends = TrendReq(hl="ko-KR", tz=540, timeout=(10, 25), retries=1, backoff_factor=1.0)

        # ref_keyword 를 배치에 포함 (중복 방지, 최대 5개)
        if ref_keyword in user_kws:
            payload = user_kws[:5]
        else:
            payload = ([ref_keyword] + user_kws)[:5]

        pytrends.build_payload(payload, timeframe="today 3-m", geo="KR")
        time.sleep(0.5)

        df_iot = pytrends.interest_over_time()
        if "isPartial" in df_iot.columns:
            df_iot = df_iot.drop(columns=["isPartial"])

        if not df_iot.empty:
            ref_series = df_iot[ref_keyword] if ref_keyword in df_iot.columns else None
            for kw in user_kws:
                if kw not in df_iot.columns:
                    continue
                for dt_idx, ratio in df_iot[kw].items():
                    r_raw  = float(ratio)
                    if ref_series is not None:
                        ref_val = float(ref_series.get(dt_idx, 0))
                        r_norm  = (r_raw / ref_val * 100.0) if ref_val > 0 else float("nan")
                    else:
                        r_norm = r_raw
                    google_records.append({
                        "keyword":      kw,
                        "date":         dt_idx.strftime("%Y-%m-%d"),
                        "ratio":        r_raw,
                        "ratio_norm":   r_norm,
                        "source":       "google",
                        "collected_at": now_str,
                    })

        time.sleep(1.0)

        # 관련 검색어 (별도 요청, 실패해도 비치명적)
        try:
            rq = pytrends.related_queries()
            for kw in user_kws:
                if kw not in rq:
                    continue
                top_df    = rq[kw].get("top")
                rising_df = rq[kw].get("rising")
                related_dict[kw] = {
                    "top":    top_df.head(10)    if top_df    is not None and not top_df.empty    else None,
                    "rising": rising_df.head(10) if rising_df is not None and not rising_df.empty else None,
                }
        except Exception:
            pass

    except Exception as e:
        msg = str(e)
        if "429" in msg or "Too Many Requests" in msg:
            google_err = "구글이 일시적으로 요청을 막았습니다 (429). 30분 후 다시 시도해 주세요."
        elif "timeout" in msg.lower():
            google_err = "구글 응답 시간 초과. 잠시 후 다시 시도해 주세요."
        else:
            google_err = f"구글 데이터를 가져오지 못했습니다. ({msg[:80]})"

    # ── 결합 ────────────────────────────────────────────────
    all_records = naver_records + google_records
    if all_records:
        df = pd.DataFrame(all_records)
        df["date"] = pd.to_datetime(df["date"])
    else:
        df = pd.DataFrame(columns=["keyword", "date", "ratio", "ratio_norm", "source", "collected_at"])

    return df, related_dict, google_err


if __name__ == "__main__":
    collect_all()
