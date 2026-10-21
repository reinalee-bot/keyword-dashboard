# 뉴스 & 트렌드 모니터링 대시보드

SCK·STK 커뮤니케이션팀의 키워드 트렌드 KPI 대시보드입니다.

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
