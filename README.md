# 뉴스 & 트렌드 모니터링 대시보드

SCK·STK 커뮤니케이션팀의 키워드 트렌드 KPI 대시보드입니다.

---

## 기능 변경 이력

### 1단계 — 기본 트렌드 추이 (기존)
- 추적 키워드별 네이버·구글 트렌드 시계열 조회
- 주간/월간 KPI 요약, 스파크라인

### 2단계 — 관련 검색어 수집 (기존)
- Google Trends `related_queries()` 호출 → Top 10 / Rising 10
- 임시 키워드 비교 시 `related_dict` 반환

### 3단계 — 경고 배지 (2026-10-22)
- **뉴스성 급등**: 최근 7일 평균 ÷ 4주 평균 ≥ `spike_ratio` (기본 2.5배)
- **동음이의 혼재**: 영문 단일 단어 패턴 감지
- **검색 관심 거의 없음**: 90일 평균 정규화 관심도 < `low_interest` (기본 5)
- 모든 배지에 hover 툴팁 포함

### 4단계 — 구글 트렌드 정규화 + 키워드 후보 풀 (2026-10-22)
- 앵커 키워드(기본: `생성형AI`) 기준 정규화 관심도(`ratio_norm`) 산출
- 세션 내 키워드 후보 풀 누적 (CSV 다운로드 지원)
- `collector.py::fetch_trends_temp()` 추가 — CSV 저장 없는 임시 수집

### 5단계 — 해시태그 추천 (2026-10-22)
위치: 추이 분석·발굴 탭 > 해시태그 추천 섹션

- **입력**: 주제 키워드 1~3개 + 채널 선택(LinkedIn / Instagram)
- **후보 수집**: `fetch_trends_temp` 관련 검색어(top/rising)에서 자동 추출
- **후보 분류**: 넓은 노출용 / 타깃 표현용 / 브랜드·서비스명
- **경고 배지**: 3단계 배지 연동, 기본 제외(토글로 포함 가능)
- **추천 조합**:
  - LinkedIn: 해시태그 2~4개 + 본문 삽입 키워드 1~2개
  - Instagram: 기본 7개(슬라이더 3~15), 권장 3~5개 기준 안내
- **Instagram 해시태그 수 근거**: Meta 공식(2022~현재) 3~5개 / 업계 실무(Later, Hootsuite 2023~2024) 5~10개
- 복사용 text_area 제공

### 7단계 — 네이버 검색광고 API 월간 검색수 (2026-10-22)
위치: 추이 분석·발굴 탭 > 해시태그 추천 후보 표 / 임시 키워드 비교 카드

- **`naver_searchad.py`** 신규 모듈: HMAC-SHA256 서명, 배치 조회(최대 5개), 24h 캐시
- `is_configured()`: Secrets 3종(`NAVER_SEARCHAD_CUSTOMER_ID/API_KEY/SECRET_KEY`) 여부 확인
- **해시태그 추천 후보 표**: `네이버 월간 검색수` 컬럼 추가 (Secrets 미설정 시 컬럼 숨김)
- **임시 키워드 비교 카드**: `네이버 월간 검색: N,NNN` 행 추가 (Secrets 미설정 시 숨김)
- `"< 10"` 응답 → 5로 처리(하한 추정); API 오류 시 해당 키워드만 `—` 표기로 graceful degradation

### 6단계 — 해시태그-게시물 성과 연결 (2026-10-22)
#### LinkedIn (`linkedin_tab.py`)
- `hashtags` 컬럼은 기존 스키마에 이미 존재 — 기존 데이터 호환
- 게시물 목록 탭 > **해시태그 수동 편집** expander 추가
- 게시물 목록 탭 > **해시태그 일괄 업데이트 (CSV)** expander 추가
  - CSV 형식: `post_id, hashtags` (쉼표 구분)
- `load_posts()` 공개 함수 추가

#### Instagram (`instagram_tab.py`)
- `_COLS`에 `hashtags` 추가 (기존 데이터 자동 호환 — `_cast()` 가 빈 값으로 채움)
- CSV 업로드 시 `Description` 컬럼에서 `#태그` 자동 추출 → `hashtags` 컬럼 저장
- 게시물 목록 탭 > **해시태그 수동 편집** expander 추가
- 업로드 섹션 > **해시태그 일괄 업데이트 (CSV)** expander 추가
- **서브탭 신설**: `#️⃣ 해시태그 분석` — 해시태그별 사용 횟수·평균 도달·평균 반응률·평균 저장
- `load_posts()` 공개 함수 추가

#### dashboard.py (해시태그 추천 연동)
- `_get_hashtag_perf_map()`: LinkedIn + Instagram 게시물 로드 → 태그별 실적 dict (5분 캐시)
- `_fmt_perf()`: 채널별 실적 문자열 포맷 (`"LI 3회 / 중앙 노출 1,200"` 또는 `"미사용"`)
- 해시태그 추천 후보 표에 **우리 계정 실적** 열 추가

---

## LinkedIn / Instagram 공식 API 조사 결과

> **구현하지 않음** — 아래는 향후 자동 수집 도입 시 참고용 조사 결과입니다.

### LinkedIn Posts API
| 항목 | 내용 |
|---|---|
| 필요 권한 | `r_organization_social`, `r_1st_connections_size` |
| 엔드포인트 | `GET /posts?author=urn:li:organization:{id}&count=100` |
| 주요 제약 | 조직 계정 관리자 OAuth2 앱 등록 필요, 액세스 토큰 60일 만료, 재발급 자동화 필요 |
| 노출·클릭 | `r_organization_social_feed` scope 추가 시 impressions/clicks 조회 가능 |
| 결론 | 앱 등록(LinkedIn 개발자 포털) + 토큰 관리 인프라 필요. 수동 Excel 내보내기 대비 초기 구축 비용 큼 |

### Instagram Graph API
| 항목 | 내용 |
|---|---|
| 전제 조건 | Instagram **비즈니스 또는 크리에이터 계정** 전환 + Facebook 페이지 연동 필수 |
| 필요 권한 | `instagram_basic`, `instagram_manage_insights`, `pages_read_engagement` |
| 엔드포인트 | `GET /{ig-user-id}/media?fields=id,caption,like_count,reach,impressions,saves` |
| 주요 제약 | `reach`/`impressions` 히스토리는 최대 **93일치**만 조회, 이전 데이터는 API로 소급 불가 |
| 토큰 | 장기 액세스 토큰(60일) + 자동 갱신 로직 필요 |
| 결론 | 비즈니스 계정 + Facebook 페이지 연동이 이미 돼 있으면 구현 가능. `reach` 93일 제한으로 현행 수동 CSV 스냅샷 누적 방식이 장기 데이터 보존에 유리 |

---

## 환경변수 / Secrets 설정

`.streamlit/secrets.toml` 또는 Streamlit Cloud 앱 설정 > Secrets에 아래 항목을 입력합니다.  
예시 파일: `.streamlit/secrets.toml.example`

| 키 | 설명 | 필수 |
|---|---|---|
| `GITHUB_TOKEN` | GitHub Personal Access Token (repo 권한) | ✅ |
| `GITHUB_REPO` | `사용자명/저장소명` 형식 | ✅ |
| `GA4_MEASUREMENT_ID` | GA4 측정 ID (예: `G-XXXXXXXXXX`) | GA4 사용 시 |
| `GA4_API_SECRET` | Measurement Protocol API 보안 비밀 | 서버 측 이벤트 사용 시 |
| `NAVER_CLIENT_ID` | 네이버 데이터랩 API 클라이언트 ID | 트렌드 수집 시 |
| `NAVER_CLIENT_SECRET` | 네이버 데이터랩 API 클라이언트 시크릿 | 트렌드 수집 시 |
| `NAVER_SEARCHAD_CUSTOMER_ID` | 네이버 검색광고 API 고객 ID (숫자) | 월간 검색수 사용 시 |
| `NAVER_SEARCHAD_API_KEY` | 네이버 검색광고 API Access License | 월간 검색수 사용 시 |
| `NAVER_SEARCHAD_SECRET_KEY` | 네이버 검색광고 API Secret Key | 월간 검색수 사용 시 |

> `GA4_MEASUREMENT_ID` 미설정 시 GA4 기능 전체가 조용히 비활성화되며, 앱은 정상 동작합니다.

---

## GA4 설정 방법

### 1. 측정 ID 확인
GA4 관리 > 데이터 스트림 > 웹 스트림 선택 > **측정 ID** (`G-XXXXXXXXXX`) 복사

### 2. Measurement Protocol API 보안 비밀 생성
GA4 관리 > 데이터 스트림 > 스트림 선택 > **Measurement Protocol API 보안 비밀** > 만들기

### 3. 향상된 측정 활성화 (권장)
GA4 관리 > 데이터 스트림 > 스트림 선택 > **향상된 측정** 켜기  
- "아웃바운드 클릭" 항목을 활성화하면 뉴스 원문 링크 클릭이 자동 추적됩니다.

### 4. 커스텀 이벤트를 핵심 이벤트(Key Event)로 설정
GA4 관리 > 이벤트 > 이벤트 목록에서 아래 이벤트를 각각 **핵심 이벤트로 표시**:

| 이벤트명 | 의미 |
|---|---|
| `dashboard_view` | 앱 첫 진입 |
| `tab_view` | 탭 전환 |
| `keyword_search` | 키워드 추이 조회 |
| `filter_change` | 기간·소스 필터 변경 |
| `export_download` | 엑셀 내보내기 |
| `pr_action` | PR 활용 등록 |

---

## LinkedIn UTM 작성 규칙

형식:
```
https://keyword-dashboard-4dqkm8snau6crfozatwbcg.streamlit.app/?utm_source=linkedin&utm_medium=organic_social&utm_campaign=keyword_dashboard&utm_content={게시물_식별자}
```

`utm_content` 값은 `YYYYMMDD_주제_키워드` 형식으로 작성합니다.

### UTM 링크 예시

**예시 1 — AI 에이전트 키워드 게시물 (2026-10-21)**
```
https://keyword-dashboard-4dqkm8snau6crfozatwbcg.streamlit.app/?utm_source=linkedin&utm_medium=organic_social&utm_campaign=keyword_dashboard&utm_content=20261021_ai_agent
```

**예시 2 — 제로트러스트 보안 트렌드 게시물**
```
https://keyword-dashboard-4dqkm8snau6crfozatwbcg.streamlit.app/?utm_source=linkedin&utm_medium=organic_social&utm_campaign=keyword_dashboard&utm_content=20261101_zerotrust_security
```

**예시 3 — 월간 KPI 공유 게시물**
```
https://keyword-dashboard-4dqkm8snau6crfozatwbcg.streamlit.app/?utm_source=linkedin&utm_medium=organic_social&utm_campaign=keyword_dashboard&utm_content=20261115_monthly_kpi_oct
```

---

## GA4에서 확인할 보고서 및 측정항목

### LinkedIn 유입 확인
- **보고서 > 획득 > 트래픽 획득**
  - 기본 측정기준: 세션 소스/매체 → `linkedin / organic_social` 필터
  - 측정항목: 세션, 활성 사용자, 참여 세션, 평균 참여 시간

### 게시물별 유입 비교
- **보고서 > 획득 > 트래픽 획득**
  - 기본 측정기준: 세션 수동 광고 콘텐츠 → 게시물별 `utm_content` 값 비교

### 대시보드 실사용 이벤트
- **보고서 > 참여 > 이벤트**
  - `dashboard_view`: 실제 진입자 수
  - `tab_view`: 탭별 조회 분포 (tab_name 파라미터)
  - `keyword_search`: 어떤 키워드를 주로 조회하는지
  - `export_download`: 다운로드 횟수

### DebugView로 실시간 이벤트 확인
1. GA4 관리 > DebugView 메뉴 열기
2. 앱 URL에 `?ga_debug_mode=1` 추가해 접속
   ```
   https://keyword-dashboard-4dqkm8snau6crfozatwbcg.streamlit.app/?ga_debug_mode=1
   ```
3. DebugView에서 실시간으로 이벤트 확인 (보통 수 초 내 표시)
