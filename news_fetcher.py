"""
키워드 관련 기사 수집·필터링·분류·점수 산출 모듈
Naver News 검색 API 기반 / config/media_allowlist.csv 화이트리스트 방식 적용

주요 설계 원칙:
- 각 키워드 결과를 완전히 독립 처리 (키워드 간 상태 공유 없음)
- 모든 외부 HTTP 요청에 명시적 timeout 적용
- 캐시 키에 모든 검색 파라미터 포함
"""

import hashlib
import os
import re
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import pandas as pd
import requests

try:
    import relevance_scorer as _rs
    _HAS_RELEVANCE = True
except Exception:
    _HAS_RELEVANCE = False

_REL_FALLBACK = {
    "_relevance_score": 50, "_relevance_level": "보통",
    "_relevance_type": "일반", "_relevance_reasons": [],
    "_low_relevance_reason": "", "_foreign_language": False,
}

# ── 경로 ─────────────────────────────────────────────────
BASE_DIR       = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR     = os.path.join(BASE_DIR, "config")
ALLOWLIST_PATH = os.path.join(CONFIG_DIR, "media_allowlist.csv")
NAVER_NEWS_URL = "https://openapi.naver.com/v1/search/news.json"

# ── 분류 사전 ─────────────────────────────────────────────
_PR_WORDS       = {"출시","발표","공개","체결","선정","공급","협력","파트너십","개최",
                   "선보여","도입","오픈","총판","업무협약","신규 서비스","수주","계약","론칭"}
_FEATURE_WORDS  = {"기획","분석","진단","전망","전략","과제","해법","왜","어떻게","시장",
                   "트렌드","확산","변화","핵심","경쟁","생태계","현황","동향","심층","리포트"}
_INTERVIEW_WORDS= {"인터뷰","만나다","만났다","대표이사","지사장","임원","강조했다","말했다",
                   "피력했다","밝혔다","설명했다","답했다","주장했다","전했다"}
_EVENT_WORDS    = {"세미나","컨퍼런스","포럼","파트너데이","간담회","현장","설명회","전시회",
                   "박람회","이벤트","데모데이","해커톤","서밋","밋업"}
_STOCK_WORDS    = {"급등","급락","주가","종목","매수","매도","투자의견","목표주가",
                   "테마주","관련주","수혜주","상한가","하한가","코스피","코스닥"}
_AD_WORDS       = {"채용공고","구인","공개채용","쇼핑몰","할인쿠폰","경품이벤트"}
_BLOG_DOMAINS   = {"blog.naver.com","cafe.naver.com","post.naver.com",
                   "tistory.com","brunch.co.kr","medium.com","velog.io",
                   "blog.daum.net","blog.kakao.com"}


# ══════════════════════════════════════════════════════════
# 매체 화이트리스트
# ══════════════════════════════════════════════════════════
def load_media_config() -> dict:
    """
    config/media_allowlist.csv 에서 매체 화이트리스트 로드.
    반환: {domain_str: {media_name, priority_tier, media_type, enabled}}
    복수 도메인은 | 구분자로 나열.
    """
    config: dict = {}
    if not os.path.exists(ALLOWLIST_PATH):
        return config
    try:
        df = pd.read_csv(ALLOWLIST_PATH, dtype=str).fillna("")
        for _, row in df.iterrows():
            enabled = str(row.get("enabled", "true")).lower() in ("1", "true", "yes")
            try:
                tier = int(str(row.get("priority_tier", "4")).strip())
            except ValueError:
                tier = 4
            for raw in str(row.get("domains", "")).split("|"):
                d = _clean_domain(raw.strip())
                if d:
                    config[d] = {
                        "media_name":    row.get("media_name", ""),
                        "priority_tier": tier,
                        "media_type":    row.get("media_type", ""),
                        "enabled":       enabled,
                    }
    except Exception:
        pass
    return config


def _clean_domain(raw: str) -> str:
    d = raw.lower().strip()
    for prefix in ("https://", "http://", "www.", "m.", "news.", "mobile.", "v."):
        if d.startswith(prefix):
            d = d[len(prefix):]
    return d.split("/")[0].split("?")[0]


def extract_domain(url: str) -> str:
    try:
        return _clean_domain(urlparse(url).netloc)
    except Exception:
        return ""


def get_media_info(url: str, config: dict) -> dict:
    d = extract_domain(url)
    return config.get(d, {})


# ══════════════════════════════════════════════════════════
# 텍스트 유틸
# ══════════════════════════════════════════════════════════
def strip_html(text: str) -> str:
    if not text:
        return ""
    t = re.sub(r"<[^>]+>", "", text)
    for esc, ch in [("&quot;",'"'),("&amp;","&"),("&lt;","<"),("&gt;",">"),
                    ("&apos;","'"),("&#39;","'"),("&nbsp;"," ")]:
        t = t.replace(esc, ch)
    return " ".join(t.split())


def normalize_title(title: str) -> str:
    t = re.sub(r"[^\w가-힣]", " ", title.lower())
    return " ".join(t.split())


def _parse_pubdate(s: str) -> datetime:
    try:
        dt = parsedate_to_datetime(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return datetime.min.replace(tzinfo=timezone.utc)


def _guess_media_name(domain: str) -> str:
    _MAP = {
        "chosun.com":"조선일보","donga.com":"동아일보","joongang.co.kr":"중앙일보",
        "mk.co.kr":"매일경제","hankyung.com":"한국경제","heraldcorp.com":"헤럴드경제",
        "sedaily.com":"서울경제","etoday.co.kr":"이투데이","mt.co.kr":"머니투데이",
        "fnnews.com":"파이낸셜뉴스","asiae.co.kr":"아시아경제","yna.co.kr":"연합뉴스",
        "yonhapnews.co.kr":"연합뉴스","newsis.com":"뉴시스","news1.kr":"뉴스1",
        "etnews.com":"전자신문","zdnet.co.kr":"ZDNet","dt.co.kr":"디지털타임스",
        "inews24.com":"아이뉴스24","bloter.net":"블로터","boannews.com":"보안뉴스",
        "dailysecu.com":"데일리시큐","itdaily.kr":"IT데일리","aitimes.com":"AI타임스",
        "itworld.co.kr":"IT월드","ciokorea.com":"CIO Korea","kbs.co.kr":"KBS",
        "ytn.co.kr":"YTN","hankookilbo.com":"한국일보","khan.co.kr":"경향신문",
    }
    if not domain:
        return ""
    return _MAP.get(domain, domain.split(".")[0].upper())


# ══════════════════════════════════════════════════════════
# 기사 유형 분류
# ══════════════════════════════════════════════════════════
def classify_article_type(title: str, description: str,
                           media_name: str = "", url: str = "") -> str:
    """
    보도자료형 / 기획·분석 / 인터뷰 / 행사·현장 / 일반 기사 / 제외 대상
    """
    combined = (title + " " + description).lower()

    # 제외 대상
    if sum(1 for w in _STOCK_WORDS if w in combined) >= 2:
        return "제외 대상"
    if any(w in combined for w in _AD_WORDS):
        return "제외 대상"

    # 인터뷰 — 따옴표 패턴 또는 2개 이상 단서
    interview_score = sum(1 for w in _INTERVIEW_WORDS if w in combined)
    if '"' in title or '“' in title or '”' in title:
        interview_score += 2
    if interview_score >= 2:
        return "인터뷰"

    # 행사·현장
    if any(w in combined for w in _EVENT_WORDS):
        return "행사·현장"

    # 기획·분석 (2개 이상 단서)
    if sum(1 for w in _FEATURE_WORDS if w in combined) >= 2:
        return "기획·분석"

    # 보도자료형
    pr_score = sum(1 for w in _PR_WORDS if w in combined)
    has_org  = any(w in combined for w in ["㈜", "주식회사", "법인", "대표이사", "대표 ", "사장 "])
    if pr_score >= 2 or (pr_score >= 1 and has_org):
        return "보도자료형"

    return "일반 기사"


# ══════════════════════════════════════════════════════════
# 저품질 기사 필터
# ══════════════════════════════════════════════════════════
def is_low_quality(article: dict, media_config: dict) -> tuple:
    """
    반환: (is_low: bool, reason: str)
    reason 목록: no_title / no_url / invalid_url / blog_domain /
                 stock_spam / ad_content / empty_description / forbidden_domain
    """
    title  = article.get("title", "").strip()
    url    = article.get("url", "").strip()
    desc   = article.get("description", "").strip()
    domain = article.get("domain", "")

    if not title:                        return True, "no_title"
    if not url:                          return True, "no_url"
    if not domain:                       return True, "invalid_url"
    if any(domain == d or domain.endswith("." + d) for d in _BLOG_DOMAINS):
        return True, "blog_domain"

    combined = (title + " " + desc).lower()
    if sum(1 for w in _STOCK_WORDS if w in combined) >= 2:
        return True, "stock_spam"
    if any(w in combined for w in _AD_WORDS):
        return True, "ad_content"
    if len(desc) < 15:
        return True, "empty_description"
    return False, ""


# ══════════════════════════════════════════════════════════
# 중복 감지 및 클러스터링
# ══════════════════════════════════════════════════════════
def _title_similarity(t1: str, t2: str) -> float:
    n1, n2 = normalize_title(t1), normalize_title(t2)
    if not n1 or not n2:
        return 0.0
    return SequenceMatcher(None, n1, n2).ratio()


def cluster_articles(articles: list, threshold: float = 0.75) -> list:
    """
    유사 제목 기사를 그룹화.
    반환: [{"rep": article, "cluster": [articles], "size": int}, ...]
    대표 기사: priority_tier 높음 → 키워드 관련성 → 최신순
    """
    if not articles:
        return []
    assigned = [False] * len(articles)
    clusters = []
    for i, a in enumerate(articles):
        if assigned[i]:
            continue
        group = [a]; assigned[i] = True
        for j in range(i + 1, len(articles)):
            if not assigned[j]:
                if _title_similarity(a.get("title",""), articles[j].get("title","")) >= threshold:
                    group.append(articles[j]); assigned[j] = True
        rep = sorted(
            group,
            key=lambda x: (
                x.get("_media_tier", 99),                   # 낮을수록 우선 (tier 1 > 4)
                -x.get("_kw_title_score", 0),
                -(x.get("_dt") or datetime.min.replace(tzinfo=timezone.utc)).timestamp(),
            ),
        )[0]
        clusters.append({"rep": rep, "cluster": group, "size": len(group)})
    return clusters


# ══════════════════════════════════════════════════════════
# 화제성 추정 점수 (0–100)
# ══════════════════════════════════════════════════════════
def calculate_article_score(article: dict, cluster_size: int, media_config: dict) -> int:
    """
    구성: 키워드 관련성(30) + 확산도(25) + 매체등급(20) + 최신성(15) + 기사유형(10)
    클릭수·조회수가 아닌 내부 참고 점수임을 명확히 한다.
    """
    score = 0

    # 1. 키워드 관련성 (0-30)
    kw    = (article.get("search_keyword") or "").lower()
    title = (article.get("title") or "").lower()
    desc  = (article.get("description") or "").lower()
    parts = [p for p in kw.split() if len(p) > 1]
    if parts:
        tm = sum(1 for p in parts if p in title) / len(parts)
        dm = sum(1 for p in parts if p in desc)  / len(parts)
    else:
        tm = dm = 0.0
    multi = min(article.get("_multi_kw_count", 1), 3)
    score += min(int(tm * 18 + dm * 7 + (multi - 1) * 2.5), 30)

    # 2. 확산도 (0-25) — 클러스터 내 기사 수 반영
    score += min(int((cluster_size - 1) * 2.8), 25)

    # 3. 매체 우선등급 (0-20)
    tier_pts = {1: 20, 2: 15, 3: 10, 4: 5}
    info = get_media_info(article.get("url", ""), media_config)
    tier = info.get("priority_tier", 0) if info.get("enabled") else 0
    score += tier_pts.get(tier, 0)

    # 4. 최신성 (0-15)
    dt = article.get("_dt")
    if dt:
        hours = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
        if hours <= 24:    score += 15
        elif hours <= 72:  score += 10
        elif hours <= 168: score += 5

    # 5. 기사 유형 (0-10) — PR 활용 적합도 기준
    type_pts = {"기획·분석": 10, "인터뷰": 8, "보도자료형": 6, "행사·현장": 4, "일반 기사": 2}
    score += type_pts.get(article.get("article_type", ""), 0)

    return min(score, 100)


# ══════════════════════════════════════════════════════════
# 기사 수집 (키워드별 완전 독립)
# ══════════════════════════════════════════════════════════
def fetch_articles_for_keyword(
    keyword: str,
    date_from: str,       # "YYYY-MM-DD"
    date_to:   str,       # "YYYY-MM-DD"
    sort_api:  str,       # "sim" | "date"
    media_scope: str,     # "whitelist" | "all"
    article_type_filter: str,  # "" | 유형명
    cid: str,
    csc: str,
    media_config: dict,
    display: int = 100,
) -> dict:
    """
    단일 키워드에 대한 기사 수집 + 필터 + 분류.
    반환 구조 (results_by_keyword[keyword_id]):
        {
          "articles": [...],
          "raw_count": int,
          "filtered_count": int,
          "status": str,   # success|auth_missing|auth_failed|rate_limit|timeout|api_error|exception
          "error": str|None,
        }
    """
    out = {
        "articles": [],
        "raw_count": 0,
        "filtered_count": 0,
        "status": "success",
        "error": None,
        "foreign_count": 0,
    }

    if not cid or not csc:
        out.update(status="auth_missing", error="API 키 없음")
        return out

    # ── Naver API 호출 ────────────────────────────────────
    try:
        resp = requests.get(
            NAVER_NEWS_URL,
            headers={"X-Naver-Client-Id": cid, "X-Naver-Client-Secret": csc},
            params={"query": keyword, "display": display, "sort": sort_api},
            timeout=(5, 20),
        )
    except requests.exceptions.Timeout:
        out.update(status="timeout", error="API 응답 시간 초과 (20초)")
        return out
    except Exception as e:
        out.update(status="exception", error=str(e)[:120])
        return out

    if resp.status_code == 401:
        out.update(status="auth_failed",  error="API 인증 실패 (401)")
        return out
    if resp.status_code == 429:
        out.update(status="rate_limit",   error="API 호출 한도 초과 (429)")
        return out
    if resp.status_code != 200:
        out.update(status="api_error",    error=f"HTTP {resp.status_code}")
        return out

    items = resp.json().get("items", [])
    out["raw_count"] = len(items)

    # ── 날짜 범위 파싱 ─────────────────────────────────────
    try:
        dt_from = datetime.strptime(date_from, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        dt_to   = (datetime.strptime(date_to, "%Y-%m-%d")
                   + timedelta(days=1)).replace(tzinfo=timezone.utc)
    except Exception:
        dt_from = dt_to = None

    seen_urls, seen_titles = set(), []
    articles: list = []

    for item in items:
        # ── 개별 기사 처리 (완전 독립 로컬 변수) ──────────
        _title  = strip_html(item.get("title", ""))
        _desc   = strip_html(item.get("description", ""))
        _url    = item.get("originallink", "") or item.get("link", "")
        _dt     = _parse_pubdate(item.get("pubDate", ""))
        _domain = extract_domain(_url)
        _info   = get_media_info(_url, media_config)
        _mname  = _info.get("media_name") or _guess_media_name(_domain)

        art: dict = {
            "title":          _title,
            "description":    _desc,
            "url":            _url,
            "domain":         _domain,
            "media_name":     _mname,
            "pub_date":       _dt.strftime("%Y-%m-%d")    if _dt != datetime.min.replace(tzinfo=timezone.utc) else "",
            "pub_datetime":   _dt.strftime("%Y-%m-%d %H:%M") if _dt != datetime.min.replace(tzinfo=timezone.utc) else "",
            "_dt":            _dt,
            "_media_tier":    _info.get("priority_tier", 99),
            "_in_whitelist":  bool(_info and _info.get("enabled")),
            "search_keyword": keyword,
            "article_type":   "",
            "_multi_kw_count":1,
            "_kw_title_score":1 if keyword.lower() in _title.lower() else 0,
            "_filter_reason": "",
        }

        # 날짜 필터
        if dt_from and dt_to and not (dt_from <= _dt < dt_to):
            continue

        # 매체 범위 필터
        if media_scope == "whitelist" and not art["_in_whitelist"]:
            art["_filter_reason"] = "not_in_whitelist"
            continue

        # 저품질 필터
        lq, reason = is_low_quality(art, media_config)
        if lq:
            art["_filter_reason"] = reason
            continue

        # 중복 URL
        if _url in seen_urls:
            art["_filter_reason"] = "duplicate_url"
            continue
        seen_urls.add(_url)

        # 중복 제목 (90% 이상 유사)
        if any(_title_similarity(_title, st) >= 0.90 for st in seen_titles):
            art["_filter_reason"] = "duplicate_title"
            continue
        seen_titles.append(_title)

        # 기사 유형 분류
        art["article_type"] = classify_article_type(_title, _desc, _mname, _url)
        if art["article_type"] == "제외 대상":
            art["_filter_reason"] = "classified_exclude"
            continue

        # 기사 유형 필터
        if article_type_filter and article_type_filter not in ("전체", ""):
            if art["article_type"] != article_type_filter:
                continue

        # SCK 관련성 판정
        art.update(_rs.score_relevance(art["title"], art["description"], query_keyword=keyword)
                   if _HAS_RELEVANCE else _REL_FALLBACK)

        # 외국어 기사 제외 — 높음/보통/낮음 어디에도 포함하지 않음
        if art.get("_foreign_language"):
            out["foreign_count"] += 1
            continue

        articles.append(art)

    out["articles"]       = articles
    out["filtered_count"] = len(articles)
    return out


def process_and_score(articles: list, media_config: dict, sort_mode: str) -> list:
    """
    클러스터링 → 점수 계산 → 정렬.
    sort_mode: 추천순 | 화제성순 | 최신순
    반환: cluster list [{"rep":art, "cluster":[arts], "size":int}, ...]
    """
    if not articles:
        return []
    clusters = cluster_articles(articles)
    for cl in clusters:
        size = cl["size"]
        cl["rep"]["_score"] = calculate_article_score(cl["rep"], size, media_config)
        for a in cl["cluster"]:
            a["_score"] = calculate_article_score(a, size, media_config)
    if sort_mode == "최신순":
        clusters.sort(
            key=lambda c: c["rep"].get("_dt") or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
    else:
        clusters.sort(key=lambda c: c["rep"].get("_score", 0), reverse=True)
    return clusters


def article_key(url: str) -> str:
    """기사 URL에서 고유 8자리 해시 키 생성 (widget key용)."""
    return hashlib.md5(url.encode(errors="replace")).hexdigest()[:8]
