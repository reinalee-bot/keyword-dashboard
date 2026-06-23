"""
IT 뉴스에서 이번 주 급상승 키워드 자동 추출
출처: 구글 뉴스 RSS (한국판) — 별도 API 키 없이 작동
결과에 '구글 뉴스 기사 빈도 기반'이라고 표시하세요.

개선 사항:
- 일반 불용어 대폭 확장 (교육·대상·활용 등 제거)
- 2단어 IT 묶음(바이그램) 우선 표시 ('랜섬웨어 대응', '제로트러스트' 등)
- IT 전문어 가중치 3배 적용
"""

import re
import feedparser
import requests
from collections import Counter

# ── 구글 뉴스 RSS 검색 쿼리 ───────────────────────────────
GOOGLE_NEWS_QUERIES = [
    "IT보안 인공지능",
    "사이버보안 클라우드",
    "생성형AI 디지털전환",
    "정보보안 랜섬웨어",
    "제로트러스트 사이버위협",
]
GOOGLE_NEWS_BASE = "https://news.google.com/rss/search?q={q}&hl=ko&gl=KR&ceid=KR:ko"

# ── IT 핵심 단어 (등장 시 점수 3배) ──────────────────────
IT_BOOST = {
    "AI", "인공지능", "생성형", "LLM", "GPT", "챗GPT",
    "클라우드", "AWS", "Azure", "GCP",
    "보안", "사이버", "랜섬웨어", "해킹", "악성코드", "피싱", "침해",
    "취약점", "CVE", "패치", "암호화", "인증",
    "제로트러스트", "ZTA", "ZTNA", "SASE", "XDR", "EDR", "SOAR", "SIEM", "SOC",
    "DevSecOps", "DevOps", "컨테이너", "쿠버네티스",
    "IoT", "OT", "ICS", "SCADA",
    "블록체인", "양자", "반도체", "GPU", "엔비디아",
    "빅데이터", "머신러닝", "딥러닝",
    "핀테크", "마이크로서비스", "API",
}

# ── 불용어 (검색 결과에서 제거할 단어) ───────────────────
# 일반 조사·접속사·지나치게 흔한 단어는 모두 제외
STOP_WORDS = {
    # 조사·접속사·어미
    "이", "가", "을", "를", "은", "는", "의", "에", "와", "과",
    "으로", "로", "에서", "도", "만", "까지", "부터", "한",
    "하는", "하고", "하여", "또한", "따라", "위해", "통해",
    "대한", "관련", "대해", "있는", "위한", "된", "되는", "되어",
    "위해서", "때문", "경우", "통하여", "의해", "으로서",

    # 시간·장소 부사
    "더", "이번", "올해", "지난", "최근", "현재", "통한",
    "따른", "관한", "기반", "국내", "해외", "글로벌", "국제",
    "이후", "이전", "이상", "이하", "내년", "지난해",
    "이번에", "오는", "지난달", "다음달", "이달", "다음",

    # 너무 일반적인 IT·비즈니스 단어 (의미 없는 맥락)
    "교육", "대상", "활용", "역량", "직원", "인력", "인재",
    "전문", "전문가", "기술사", "관련", "강화", "필요", "중요",
    "이용", "현황", "방안", "추진", "환경", "전략", "개요",
    "소개", "확인", "구축", "운영", "관리", "도입", "적용",
    "확대", "증가", "감소", "향상", "개선", "효율", "효과",
    "성과", "목표", "사용", "제공", "지원", "협력", "협업",
    "공유", "활성화", "예방", "분석", "처리", "구현", "설계",
    "조직", "정책", "제도", "규정", "법안", "규제", "표준",
    "시장", "경쟁", "성장", "투자", "비용", "예산",
    "프로젝트", "과제", "업그레이드", "최신", "신규",
    "기업", "기관", "정부", "사회", "산업", "분야", "사업",
    "발전", "개발",
    "업계", "회사", "조직", "서울", "대기업", "중소기업",

    # 언론사·기관·지역 고유명사 (IT 키워드 아님)
    "조선", "한국", "미국", "중국", "일본", "유럽", "아시아",
    "삼성", "LG", "현대", "SK", "롯데", "카카오", "네이버",
    "구글", "마이크로소프트", "애플", "아마존", "메타",
    "경찰", "검찰", "법원", "국회", "청와대", "정부",
    "대학", "연구소", "협회", "재단", "위원회",

    # 단독으로는 의미 없는 동사·형용사 파생어
    "수행", "실시", "완료", "진행", "달성", "추진중",
    "가능", "불가", "중요성", "필요성", "효과적",
    "선정", "수상", "발표", "발간", "공표",
    "통합", "연동", "연계", "업무", "기능", "기반",

    # 시간·수량 표현
    "올해", "내년", "작년", "상반기", "하반기", "분기",
    "전망", "예측", "계획", "일정", "기간", "이후",
    "대비", "동기", "대폭", "급증", "급감",

    # 뉴스 메타 단어
    "뉴스", "기자", "기사", "제공", "발표", "출시", "공개",
    "보고서", "세미나", "컨퍼런스", "행사",
    "서비스", "시스템", "솔루션",  # 단독으로는 의미 없음

    # URL 조각
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


def _tokenize(title: str) -> list:
    """제목에서 한글 2자 이상 / 영문+숫자 2자 이상 토큰을 추출합니다."""
    return re.findall(r"[가-힣]{2,}|[A-Za-z][A-Za-z0-9]{1,}", title)


def _extract_bigrams(titles: list) -> Counter:
    """
    연속된 2단어 IT 묶음(바이그램)을 추출합니다.
    두 단어 모두 불용어가 아니고, 적어도 하나는 IT_BOOST 단어이어야 합니다.
    """
    bigram_count = Counter()
    for title in titles:
        tokens = _tokenize(title)
        for i in range(len(tokens) - 1):
            w1, w2 = tokens[i], tokens[i + 1]
            if w1 in STOP_WORDS or w2 in STOP_WORDS:
                continue
            if w1 in IT_BOOST or w2 in IT_BOOST:
                bigram_count[f"{w1} {w2}"] += 1
    return bigram_count


def fetch_news_keywords(top_n: int = 20) -> tuple:
    """
    IT 뉴스에서 자주 등장하는 키워드를 추출합니다.
    바이그램(2단어 묶음)을 단일어보다 우선 표시합니다.

    반환: ([(키워드, 등장횟수), ...], 출처 메시지 문자열)
    """
    # 중복 제목 제거하며 수집
    seen_titles: set = set()
    all_titles:  list = []
    success = 0

    for query in GOOGLE_NEWS_QUERIES:
        titles = _fetch_google_news(query, max_items=25)
        if titles:
            success += 1
        for t in titles:
            if t not in seen_titles:
                seen_titles.add(t)
                all_titles.append(t)

    if not all_titles:
        return [], "뉴스 연결 실패"

    # 단일어 집계
    word_count = Counter()
    for title in all_titles:
        for w in _tokenize(title):
            if w not in STOP_WORDS:
                word_count[w] += 1

    # 바이그램 집계
    bigram_count = _extract_bigrams(all_titles)

    # 점수 계산
    scored: list = []
    used_words: set = set()  # 바이그램에 포함된 단어 — 단독 재출력 방지

    # ① 바이그램 (2단어 묶음 우선)
    for bg, cnt in bigram_count.most_common(top_n * 2):
        if cnt < 2:
            continue
        boost = 3.0 if any(b in bg for b in IT_BOOST) else 1.5
        scored.append((bg, cnt, cnt * boost * 2.0))
        for w in bg.split():
            used_words.add(w)

    # ② 단일어 (바이그램에 이미 포함된 단어는 제외)
    for w, cnt in word_count.most_common(top_n * 3):
        if w in used_words or cnt < 2:
            continue
        boost = 3.0 if any(b in w or w in b for b in IT_BOOST) else 1.0
        scored.append((w, cnt, cnt * boost))

    if not scored:
        return [], f"구글 뉴스 {len(all_titles)}건 분석 완료 (조건에 맞는 키워드 없음)"

    # 점수 내림차순 정렬 후 상위 top_n
    scored.sort(key=lambda x: x[2], reverse=True)
    result = [(w, cnt) for w, cnt, _ in scored[:top_n]]

    source_msg = (
        f"구글 뉴스 기사 빈도 기반 — "
        f"{success}개 쿼리, 기사 {len(all_titles)}건 분석"
    )
    return result, source_msg
