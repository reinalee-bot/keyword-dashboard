"""
IT 뉴스에서 이번 주 급상승 키워드 자동 추출
Google News RSS (한국판)를 사용 — 별도 API 키 없이 작동
"""

import re
import feedparser
import requests
from collections import Counter

# ── 구글 뉴스 RSS 검색 쿼리 목록 ─────────────────────────
# IT·보안·디지털 분야를 폭넓게 커버
GOOGLE_NEWS_QUERIES = [
    "IT보안 인공지능",
    "사이버보안 클라우드",
    "생성형AI 디지털",
    "정보보안 랜섬웨어",
]
GOOGLE_NEWS_BASE = "https://news.google.com/rss/search?q={q}&hl=ko&gl=KR&ceid=KR:ko"

# ── IT 키워드 가중치 목록 ─────────────────────────────────
IT_BOOST = {
    "AI", "인공지능", "생성형", "LLM", "GPT", "챗GPT", "클라우드",
    "보안", "사이버", "랜섬웨어", "해킹", "데이터", "디지털",
    "자동화", "SaaS", "플랫폼", "반도체", "로봇", "스마트",
    "IoT", "빅데이터", "머신러닝", "딥러닝", "엔비디아",
    "마이크로소프트", "오픈AI", "AWS", "Azure", "핀테크",
    "블록체인", "5G", "6G", "양자", "GPU", "솔루션", "취약점",
    "침해", "제로트러스트", "DevSecOps", "SIEM", "SOC",
}

# ── 한국어 불용어 ────────────────────────────────────────
STOP_WORDS = {
    # 조사·접속사
    "이", "가", "을", "를", "은", "는", "의", "에", "와", "과",
    "으로", "로", "에서", "도", "만", "까지", "부터",
    "한", "하는", "하고", "하여", "또한", "따라", "위해",
    "통해", "대한", "관련", "대해", "있는", "위한", "된",
    # 시간 부사
    "더", "이번", "올해", "지난", "최근", "현재", "통한",
    "따른", "관한", "기반", "국내", "해외", "글로벌",
    "이후", "이전", "이상", "이하", "내년", "올해도",
    "지난해", "이번에", "오는", "지난달", "다음달", "이달",
    "이번주", "다음주",
    # 너무 일반적인 단어
    "뉴스", "기자", "기사", "제공", "서울", "정부", "업계",
    "기업", "회사", "공개", "발표", "출시", "시장", "서비스",
    "운영", "전환", "오픈", "지원", "강화", "확대", "추진",
    # URL 조각 (구글 뉴스 제목에 도메인이 섞이는 경우)
    "daum", "naver", "net", "co", "kr", "com", "www",
    "http", "https", "html", "rss",
}


def _fetch_google_news(query: str, max_items: int = 30) -> list:
    """구글 뉴스 RSS에서 기사 제목을 가져옵니다."""
    try:
        url = GOOGLE_NEWS_BASE.format(q=requests.utils.quote(query))
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        resp = requests.get(url, timeout=10, headers=headers)
        if resp.status_code != 200:
            return []
        feed = feedparser.parse(resp.content)
        return [e.title.strip() for e in feed.entries[:max_items] if e.get("title")]
    except Exception:
        return []


def fetch_news_keywords(top_n: int = 20) -> tuple:
    """
    IT 뉴스에서 자주 등장하는 키워드를 추출합니다.
    반환: (키워드 목록, 성공 여부 메시지)
      - 키워드 목록: [(키워드, 등장횟수), ...]
    """
    all_titles = []

    # 여러 검색어로 구글 뉴스 수집 (중복 제목 제거)
    seen_titles = set()
    for query in GOOGLE_NEWS_QUERIES:
        titles = _fetch_google_news(query, max_items=20)
        for t in titles:
            if t not in seen_titles:
                seen_titles.add(t)
                all_titles.append(t)

    if not all_titles:
        return [], "뉴스 연결 실패"

    # 한글 2글자 이상, 영문 2글자 이상 단어 추출
    word_count = Counter()
    for title in all_titles:
        tokens = re.findall(r"[가-힣]{2,}|[A-Za-z]{2,}[0-9]*", title)
        for word in tokens:
            if word in STOP_WORDS:
                continue
            word_count[word] += 1

    # 2번 이상 등장 + IT 가중치 적용
    scored = {}
    for word, count in word_count.items():
        if count < 2:
            continue
        is_it = any(b in word or word in b for b in IT_BOOST)
        scored[word] = count * (2 if is_it else 1)

    if not scored:
        return [], f"구글 뉴스 {len(all_titles)}건 분석 완료 (2회 이상 키워드 없음)"

    # 점수 순 정렬 → 실제 등장 횟수로 반환
    top = sorted(scored.items(), key=lambda x: x[1], reverse=True)
    result = [(w, word_count[w]) for w, _ in top[:top_n]]
    source_msg = f"구글 뉴스 (IT·보안·AI 관련 기사 {len(all_titles)}건 분석)"
    return result, source_msg
