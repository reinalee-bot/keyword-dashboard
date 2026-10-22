"""
naver_searchad.py — 네이버 검색광고 API 키워드 도구

월간 PC·모바일 검색수(절대 검색량)를 조회한다.
네이버 데이터랩의 상대값(0~100)을 보완하는 용도.

Secrets 설정 (secrets.toml 또는 Streamlit Cloud):
  NAVER_SEARCHAD_CUSTOMER_ID = "1234567"
  NAVER_SEARCHAD_API_KEY     = "your-api-key"
  NAVER_SEARCHAD_SECRET_KEY  = "your-secret-key"

API 제한:
  - 1초당 10회, 일일 약 1,000회
  - 키워드 1회 요청당 최대 5개
  - 본 모듈: 배치 5개, 배치 간 sleep(0.2), 24h 캐시
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time

import requests


_BASE_URL = "https://api.naver.com"
_PATH     = "/keywordstool"


# ══════════════════════════════════════════════════════════════════════
# 설정 확인
# ══════════════════════════════════════════════════════════════════════

def _get_creds() -> tuple[str, str, str]:
    """(customer_id, api_key, secret_key) 반환. 미설정이면 빈 문자열."""
    try:
        import streamlit as st
        cid = st.secrets.get("NAVER_SEARCHAD_CUSTOMER_ID", "")
        akey = st.secrets.get("NAVER_SEARCHAD_API_KEY", "")
        skey = st.secrets.get("NAVER_SEARCHAD_SECRET_KEY", "")
    except Exception:
        import os
        cid  = os.getenv("NAVER_SEARCHAD_CUSTOMER_ID", "")
        akey = os.getenv("NAVER_SEARCHAD_API_KEY", "")
        skey = os.getenv("NAVER_SEARCHAD_SECRET_KEY", "")
    return str(cid).strip(), str(akey).strip(), str(skey).strip()


def is_configured() -> bool:
    """Secrets 3종이 모두 설정돼 있는지 확인."""
    cid, akey, skey = _get_creds()
    return bool(cid and akey and skey)


# ══════════════════════════════════════════════════════════════════════
# 서명
# ══════════════════════════════════════════════════════════════════════

def _sign(timestamp_ms: int, method: str, path: str, secret_key: str) -> str:
    """
    HMAC-SHA256(timestamp_ms + "." + method + "." + path, secret_key) → Base64
    네이버 검색광고 API 공식 서명 방식.
    """
    message = f"{timestamp_ms}.{method}.{path}".encode("utf-8")
    key     = secret_key.encode("utf-8")
    sig     = hmac.new(key, message, hashlib.sha256).digest()
    return base64.b64encode(sig).decode("utf-8")


# ══════════════════════════════════════════════════════════════════════
# 단일 배치 요청 (최대 5개 키워드)
# ══════════════════════════════════════════════════════════════════════

def _fetch_batch(keywords: list[str], cid: str, akey: str, skey: str) -> dict:
    """
    키워드 최대 5개를 한 번에 조회해 {keyword: {"pc": int, "mobile": int}} dict 반환.
    "< 10" 응답은 5로 처리 (하한 추정).
    """
    ts  = int(time.time() * 1000)
    sig = _sign(ts, "GET", _PATH, skey)

    headers = {
        "X-Timestamp":    str(ts),
        "X-API-KEY":      akey,
        "X-Customer":     str(cid),
        "X-Signature":    sig,
        "Content-Type":   "application/json; charset=UTF-8",
    }
    params = {
        "hintKeywords": ",".join(keywords[:5]),
        "showDetail":   "1",
    }

    resp = requests.get(
        _BASE_URL + _PATH,
        headers=headers,
        params=params,
        timeout=10,
    )
    resp.raise_for_status()

    result: dict = {}
    for item in resp.json().get("keywordList", []):
        kw  = item.get("relKeyword", "")
        pc  = item.get("monthlyPcQcCnt",     0)
        mob = item.get("monthlyMobileQcCnt", 0)

        def _parse(v) -> int:
            if isinstance(v, (int, float)):
                return int(v)
            s = str(v).strip()
            if s in ("< 10", "<10", "미미"):
                return 5
            try:
                return int(s.replace(",", ""))
            except ValueError:
                return 0

        result[kw] = {"pc": _parse(pc), "mobile": _parse(mob)}

    return result


# ══════════════════════════════════════════════════════════════════════
# 공개 함수
# ══════════════════════════════════════════════════════════════════════

def fetch_monthly_searchvol(keywords: list[str]) -> dict:
    """
    키워드 목록의 네이버 월간 검색수(PC+모바일)를 반환한다.

    반환:
      {keyword: {"pc": int, "mobile": int, "total": int}}

    키 미설정, 오류, 응답 없음 → 해당 키워드 제외 (빈 dict 반환 가능).
    배치 크기: 5 / 배치 간 sleep: 0.2초
    """
    if not is_configured():
        return {}

    cid, akey, skey = _get_creds()
    result: dict = {}

    for i in range(0, len(keywords), 5):
        batch = [k for k in keywords[i : i + 5] if k]
        if not batch:
            continue
        try:
            batch_result = _fetch_batch(batch, cid, akey, skey)
            for kw, vals in batch_result.items():
                vals["total"] = vals["pc"] + vals["mobile"]
                result[kw] = vals
        except Exception:
            pass
        if i + 5 < len(keywords):
            time.sleep(0.2)

    return result


def fmt_searchvol(vol_dict: dict, keyword: str) -> str:
    """
    검색량 dict에서 키워드의 월간 검색수를 포맷 문자열로 반환.
    없으면 "—".
    """
    entry = vol_dict.get(keyword)
    if entry is None:
        return "—"
    t = entry.get("total", 0)
    if t == 0:
        return "< 10"
    return f"{t:,}"
