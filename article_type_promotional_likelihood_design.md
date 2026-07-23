# article_type / promotional_likelihood 분리 설계 문서

**작성일**: 2026-07-23  
**작성 근거**: P2a~P2d 시뮬레이션 완료(45건, 96% 정확도) 후 남은 구조적 문제 해소  
**이 문서의 범위**: 설계만 수행. 운영 코드·저장 스키마·UI는 구현하지 않는다.  
**구현 금지 목록**: classify_article_type() 반환 타입 변경, dashboard.py 수정, CSV·Sheets 스키마 변경, 데이터 마이그레이션 실행, 즉흥 규칙 추가, Google Sheets 동기화 코드 변경

---

## A. 현행 문제

### 보도자료형이 두 가지 의미를 동시에 담고 있다

현행 `classify_article_type()`이 반환하는 **"보도자료형"** 은 아래 두 독립 차원을 단일 레이블로 표현한다.

| 차원 | 의미 | 예시 |
|------|------|------|
| **형식(Format)** | 기업·기관이 발표한 단편 알림 위주 기사 | "인엠스 VPN 조달등록 완료" |
| **홍보 활용 가능성(Promotional)** | PR 팀이 보도자료·기획·후속 대응 등에 활용할 가능성 | 출시 발표, 파트너십 체결 |

두 차원이 항상 일치하지 않기 때문에 분류 오류가 발생한다.

### 구체적 증거 (시뮬레이션 45건 기준)

**오류 ①**: display_no **#22** (dataset_index=21) — 삼성디스플레이 "AI 비전 'O.P.E.N.' 공개… 엔비디아 협력해 자율공장…"
- 기대: 인터뷰 (임원의 발언·비전 제시 = 인터뷰 형식)
- 예측: 보도자료형 → **기존 FP**
- 원인: title에 "공개"라는 PR 단어가 있어 `_is_promotional_article()` 기준 보도자료형으로 처리됨
- 형식: 인터뷰, 홍보성: 보통 (자사 전략 발표이므로 PR 소재 가능)

**오류 ②**: display_no **#24** (dataset_index=23) — 구글 사이버 보안 전용 모델 첫 출시
- 기대: 인터뷰 ("미소스의 가성비 대안" 발언 포함)
- 예측: 일반 기사 → **기존 FN**
- 원인: 강한 PR 신호는 없고 인터뷰 신호(따옴표)는 낮게 평가됨
- 형식: 인터뷰, 홍보성: 높음 (구글 신제품 발표 맥락)

**구조적 한계**: P2a~P2d 규칙도 현재 "보도자료형"을 반환하는데, 이 규칙들이 판단하는 것은 홍보성(기업·기관이 발표한 내용)이지 형식이 아니다. 규칙이 발동해도 article_type을 오염시킨다.

---

## B. 새 데이터 모델

### B-1. article_type (4종 — 형식 기준)

| 값 | 정의 | 대표 신호 |
|----|------|-----------|
| **기획·분석** | 현상·원인·영향을 구조적으로 다루는 심층 기사 | [칼럼] [기고] [분석] 브래킷, 기획 단어 ≥ 3 |
| **인터뷰** | 특정 인물의 발언·견해 중심 기사 | 따옴표 발언 + 인터뷰 단어 ≥ 2 |
| **행사·현장** | 컨퍼런스·세미나·전시 현장 보도 | 행사 단어(컨퍼런스, 세미나, 전시회…) |
| **일반 기사** | 위 세 유형 외 모든 기사 (발표 기사 포함) | (기본값) |

> **보도자료형 제거**: 현재 보도자료형으로 분류되던 기사는 대부분 "일반 기사"(단편 발표)로 재분류된다. 발표 기사는 article_type이 아니라 promotional_likelihood로 표현한다.

### B-2. promotional_likelihood (3단계 — 홍보 활용 가능성 기준)

| 값 | 정의 | 대표 조건 |
|----|------|-----------|
| **높음** | PR 팀 즉시 활용 가능한 강한 발표·출시 기사 | 강한 PR 신호 발동 OR P2 복합 규칙 발동 OR PR 단어 ≥ 2 |
| **보통** | 조건부 PR 활용 가능 (수정 후 활용, 후속 기획 소재) | PR 단어 = 1 OR 기관 언급 + 약한 신호 |
| **낮음** | 홍보 직접 활용 불가 (시장 동향, 분석, 경쟁사 기사) | PR 신호 없음, 칼럼·분석 중심 |

### B-3. 분류 근거 보조 필드 (6개, article dict 내부 저장용)

| 필드명 | 타입 | 설명 |
|--------|------|------|
| `has_strong_pr_signal` | bool | `_STRONG_PR_TITLE_SIGNALS` 또는 `_BOOK_ANNOUNCE_RE` 발동 여부 |
| `pr_word_count` | int | `_PR_WORDS` 매칭 수 |
| `interview_word_count` | int | `_INTERVIEW_WORDS` 매칭 수 |
| `p2_rules_fired` | str | 발동된 P2 규칙 이름 (없으면 "") |
| `column_marker` | bool | `_COLUMN_MARKER_RE` 발동 여부 |
| `classification_basis` | str | 판정 근거 약어: "strong_pr" / "p2" / "pr_words" / "interview" / "event" / "feature" / "default" |

---

## C. 독립 판정 원칙

**article_type과 promotional_likelihood는 완전히 독립적으로 판정한다.**

- article_type 판정에 promotional_likelihood를 참조하지 않는다.
- promotional_likelihood 판정에 article_type을 참조하지 않는다.
- 두 차원의 조합이 실제 기사 성격을 더 정확히 표현한다.

| article_type | promotional_likelihood | 해석 예시 |
|---|---|---|
| 기획·분석 | 낮음 | 순수 시장 분석 기사 (KDI 보고서 관련 리포트) |
| 기획·분석 | 높음 | SCK 솔루션 홍보가 들어간 기고 |
| 인터뷰 | 높음 | 구글 신제품 출시 임원 인터뷰 |
| 일반 기사 | 높음 | 인엠스 조달등록 완료 알림 (현 보도자료형) |
| 일반 기사 | 낮음 | HD현대 AI 전략 뉴스 (단순 시장 기사) |

---

## D. 판정 우선순위 및 충돌 케이스

### D-1. article_type 판정 순서

```
① 제외 대상 필터  → 스톡 단어 ≥ 2 OR 광고 단어 존재  → 기사 자체 제외 (타입 없음)
② 칼럼 마커 우선  → [칼럼] [기고] [사례연구] RE 발동  → "기획·분석"
③ 인터뷰 신호    → 따옴표 발언 + interview_words ≥ 2  → "인터뷰"
④ 행사 신호      → event_words 존재               → "행사·현장"
⑤ 기획 신호      → feature_words ≥ 3             → "기획·분석"
⑥ 기본값         → (이상 없음)                   → "일반 기사"
```

> **P2 규칙 위치**: article_type 판정 흐름에서 **제거**된다. P2는 promotional_likelihood 판정에만 관여한다.

### D-2. promotional_likelihood 판정 순서

```
① 강한 PR 신호   → _STRONG_PR_TITLE_SIGNALS OR _BOOK_ANNOUNCE_RE  → "높음"
② P2 복합 규칙   → get_compound_pr_rules_fired(title) 비어있지 않음  → "높음"
③ PR 단어 ≥ 2   → pr_word_count ≥ 2                              → "높음"
④ PR 단어 = 1 + 기관 → pr_word_count ≥ 1 AND has_org             → "높음"
⑤ PR 단어 = 1   →                                                → "보통"
⑥ 기본값         →                                                → "낮음"
```

### D-3. 충돌 케이스 처리 규칙

| 상황 | article_type | promotional_likelihood | 근거 |
|------|---|---|------|
| [보안 칼럼] + "출시" 단어 | 기획·분석 | 낮음 | 칼럼 마커는 홍보성을 낮춤; 편집자가 붙인 [칼럼] 레이블 신뢰 |
| 따옴표 발언 + 강한 PR 신호 | 인터뷰 | 높음 | 형식은 인터뷰지만 내용이 발표임 (#22 케이스 해결) |
| KDI 보고서 기관 발표 | 인터뷰/일반 기사 | 보통 | 기관 발표이나 PR 직접 활용 제한적 |
| P2c 발동 + 기획 신호 | 기획·분석 | 높음 | 두 차원 독립 판정 원칙 적용 |

---

## E. P2 규칙 마이그레이션

### 현재 (P2 → article_type)
```python
# news_fetcher.py 현행
if get_compound_pr_rules_fired(title):
    return "보도자료형"   ← article_type을 오염시킴
```

### 변경 후 (P2 → promotional_likelihood)
```python
# news_fetcher.py 이후 (설계 — 구현 미수행)
def classify_article_type(title, description, ...):
    # ... 형식만 판정 (P2 참조 없음) ...
    return article_type_value   # 4종 중 하나

def determine_promotional_likelihood(title, description, ...):
    if has_strong_pr_signal or get_compound_pr_rules_fired(title):
        return "높음"
    if pr_word_count >= 2 or (pr_word_count >= 1 and has_org):
        return "높음"
    if pr_word_count >= 1:
        return "보통"
    return "낮음"
```

### P2 규칙별 역할 재정의

| 규칙 | 현재 의미 | 이후 의미 |
|------|-----------|-----------|
| P2a | 기업명 + 지원 + 제공 = 보도자료형 | promotional_likelihood = "높음" |
| P2b | 기관명 + 개최 + 서수 = 보도자료형 | promotional_likelihood = "높음" |
| P2c | N종/제N차 + 공개 = 보도자료형 | promotional_likelihood = "높음" |
| P2d | 기업명,따옴표제품 + 출시 = 보도자료형 | promotional_likelihood = "높음" |

> **결과**: 회귀 테스트 보도자료형 Recall 100%가 promotional_likelihood="높음" Recall 100%로 재정의된다. 성능 수치 자체는 유지된다.

---

## F. 운영 정책

### F-1. 기획기사 후보 판정

**현재**:
```python
# monitoring.py:456
if (atype == "기획·분석"
        and rlevel in {"높음", "보통"}
        and not _is_promotional_article(article)
        and confidence != "낮음"):
    return "기획기사 후보"
```

**변경 후 설계**:
```python
# 설계만 — 구현 미수행
if (atype == "기획·분석"
        and rlevel in {"높음", "보통"}
        and article.get("promotional_likelihood", "낮음") != "높음"
        and confidence != "낮음"):
    return "기획기사 후보"
```

> **의미 변화**: "보도자료성 아닌 기획 기사"에서 "홍보성 높지 않은 기획 기사"로 정밀화. KDI 보고서 관련 분석 기사는 promotional_likelihood="보통"이면 기획기사 후보가 된다.

### F-2. `_is_promotional_article()` 대체

**현재**:
```python
def _is_promotional_article(article):
    if article.get("article_type", "") == "보도자료형":
        return True
    # ... 패턴 기반 fallback ...
```

**변경 후 설계**:
```python
# 설계만 — 구현 미수행
def _is_promotional_article(article):
    return article.get("promotional_likelihood", "낮음") == "높음"
```

패턴 기반 fallback 중 `_STRONG_PR_TITLE_SIGNALS`, `파트너십 체결`, `mou 체결` 등은 promotional_likelihood 계산에 흡수되므로 이 함수 자체가 단순화된다.

### F-3. 자사·리스크 기사 처리

- 카테고리 결정 (`_determine_category()`)에서 자사·관계사 및 리스크는 promotional_likelihood 값에 무관하게 최우선 처리한다.
- 이 부분의 판정 로직은 변경하지 않는다.

### F-4. 스코어 배분 (`score_monitoring_candidate()`)

**현재**: `type_pts = {"기획·분석": 10, "인터뷰": 8, "보도자료형": 6, "행사·현장": 4, "일반 기사": 2}`

**변경 후 설계**:
- `type_pts`는 4-type 기준으로 재정의
- promotional_likelihood 점수는 별도 항목으로 추가 (설계만, 수치 미확정)

---

## G. 데이터 마이그레이션

### G-1. 마이그레이션 필요 항목

| 데이터 | article_type 저장 여부 | 마이그레이션 필요 |
|--------|----------------------|-----------------|
| `monitoring_reviews.csv` | **저장 안 함** (REVIEW_COLS에 없음) | **불필요** |
| Google Sheets monitoring_reviews 시트 | **저장 안 함** | **불필요** |
| 실시간 article dict (메모리) | 매번 재계산 | 코드 변경 시 자동 반영 |
| `regression_collected.json` | **저장 안 함** (URL+제목만 저장) | **불필요** |
| `build_regression.py` EXPECTED_MAP | 수동 레이블 (Python 코드) | **필요**: promotional_likelihood 레이블 추가 |
| `regression_set.csv` | 이전 실험 데이터 | 읽기 전용, 수정 불필요 |

### G-2. 현 보도자료형 → 새 레이블 매핑 정책

| 현재 article_type | 이후 article_type | promotional_likelihood |
|---|---|---|
| 보도자료형 (강한 PR 신호) | 일반 기사 | 높음 |
| 보도자료형 (P2 규칙 발동) | 일반 기사 | 높음 |
| 보도자료형 (행사 개최) | 행사·현장 | 높음 |
| 보도자료형 (신간 발표) | 일반 기사 | 높음 |

> **기본 원칙**: 현 "보도자료형" 기사는 모두 promotional_likelihood="높음"을 부여한다. article_type은 형식 기준으로 재판정한다.

### G-3. 45건 회귀 세트 재레이블 계획 (구현 미수행)

- build_regression.py의 EXPECTED_MAP에 `promotional_likelihood` 필드를 추가
- 현재 `("보도자료형", "AI·AX 시장동향", "", "...")` → `("일반 기사", "AI·AX 시장동향", "", "...", "높음")`
- P2 규칙 발동 4건: `("일반 기사", ..., "높음")` — promotional_likelihood="높음" 확인
- FP 2건 (#22 삼성디스플레이, #24 구글): 새 article_type 레이블 재검토 필요

---

## H. 저장 스키마

### H-1. article dict 필드 비교

| 필드 | 현재 | 변경 후 | 타입 | 기본값 | nullable | 마이그레이션 |
|------|------|---------|------|--------|----------|------------|
| `article_type` | 보도자료형/기획·분석/인터뷰/행사·현장/일반 기사/제외 대상 (6종) | 기획·분석/인터뷰/행사·현장/일반 기사 (4종) | str | "일반 기사" | N | 코드 변경 시 자동 재계산 |
| `promotional_likelihood` | **없음** | 높음/보통/낮음 | str | "낮음" | N | 코드 추가 후 자동 계산 |
| `has_strong_pr_signal` | **없음** | bool | bool | False | N | 새 필드 |
| `pr_word_count` | **없음** | int | int | 0 | N | 새 필드 |
| `interview_word_count` | **없음** | int | int | 0 | N | 새 필드 |
| `p2_rules_fired` | **없음** | str | str | "" | Y | 새 필드 |
| `column_marker` | **없음** | bool | bool | False | N | 새 필드 |
| `classification_basis` | **없음** | str | str | "default" | N | 새 필드 |

### H-2. monitoring_reviews.csv / Google Sheets — 변경 없음

`REVIEW_COLS` = `["article_id", "title", "url", "media", "published_at", "category", "monitoring_priority", "relevance_score", "news_importance_score", "pr_usability_score", "selection_reason", "pr_suggestion", "review_status", "usage_type", "exclusion_reason", "follow_up_required", "reviewer_memo", "reviewed_at"]`

**article_type / promotional_likelihood 모두 이 스키마에 없다.** 저장 스키마 변경 없음.

---

## I. UI 표시 설계

### I-1. 현재 배지

```html
<!-- dashboard.py _art_type_html() -->
<span class='art-type-pr'>보도자료형</span>
<span class='art-type-feat'>기획·분석</span>
<span class='art-type-int'>인터뷰</span>
<span class='art-type-ev'>행사·현장</span>
<span class='art-type-gen'>일반 기사</span>
```

### I-2. 변경 후 배지 (설계 — 구현 미수행)

```html
<!-- 유형 배지 (4종) -->
<span class='art-type-feat'>기획·분석</span>
<span class='art-type-int'>인터뷰</span>
<span class='art-type-ev'>행사·현장</span>
<span class='art-type-gen'>일반 기사</span>

<!-- 홍보성 배지 (3단계, 유형 배지 오른쪽에 추가) -->
<span class='promo-high'>홍보성 높음</span>
<span class='promo-mid'>홍보성 보통</span>
<!-- 낮음은 표시 생략 (기본값) -->
```

### I-3. 기사 유형 필터 변경 (설계)

| 현재 selectbox 옵션 | 변경 후 유형 필터 | 홍보성 필터 (신규) |
|---|---|---|
| 전체 | 전체 | 전체 |
| 보도자료형 | 기획·분석 | 높음 |
| 기획·분석 | 인터뷰 | 보통 |
| 인터뷰 | 행사·현장 | 낮음 |
| 행사·현장 | 일반 기사 | |
| 일반 기사 | | |

---

## J. 영향 파일 목록

코드 검색 결과(`grep -rn "article_type|보도자료형"`) 기준.

### J-1. 변경 필요 파일

| 파일 | 현재 사용 위치 | 변경 내용 |
|------|--------------|----------|
| `news_fetcher.py` | `classify_article_type()` (line 254), `score_article()` type_pts (line 422), `fetch_news()` 필터 (line 568) | `promotional_likelihood` 계산 추가; `article_type` 반환을 4종으로 제한 |
| `monitoring.py` | `_NON_INCIDENT_ARTICLE_TYPES` (line 97), `_is_promotional_article()` (line 473), `_determine_category()` (line 456), `score_monitoring_candidate()` (line 612) | `promotional_likelihood` 소비 로직으로 전환 |
| `dashboard.py` | `_art_type_html()` (line 671), `_pr_suggest()` (line 1411), 필터 selectbox (line 1966), article_type 표시 (line 2090) | 배지 추가, 필터 옵션 변경, PR 제안 로직 수정 |
| `test_article_quality.py` | `classify_article_type` 호출 (line 50 등) | 보도자료형 기대값 → 새 2-field 기대값으로 수정 |
| `build_regression.py` | EXPECTED_MAP (line 85~) | `promotional_likelihood` 필드 추가 |
| `test_p2_rules.py` | P2 규칙 반환값 검증 (보도자료형) | promotional_likelihood="높음" 검증으로 전환 |

### J-2. 변경 불필요 파일

| 파일 | 이유 |
|------|------|
| `monitoring_review_store.py` | REVIEW_COLS에 article_type 없음; 직접 사용 없음 |
| `sheets_sync.py` | article_type 사용 없음 (keyword trend 동기화 모듈) |
| `monitoring_tab_helpers.py` | article_type 사용 없음 |
| `relevance_scorer.py` | promotional_terms는 별도 config 키워드 (article_type 무관) |
| `data/monitoring_reviews.csv` | 저장 스키마에 article_type 없음 |

---

## K. 하위 호환 단계적 전환 계획 (6단계)

각 단계는 독립적으로 커밋·배포·검증 가능하다.

### 1단계: 기반 구축

**진입 조건**: 이 설계 문서 승인  
**종료 조건**: news_fetcher.py 변경, 77개 기존 테스트 전부 통과

작업:
- `classify_article_type()` 내부에서 `promotional_likelihood`도 계산
- `article["promotional_likelihood"]` 필드 추가 (article dict에 추가)
- article_type 반환은 유지 (보도자료형 포함 6종 — 하위 호환)
- 새 `determine_promotional_likelihood()` 함수를 별도로 추가

주의: 이 단계에서는 `classify_article_type()`의 보도자료형 반환을 제거하지 않는다.

---

### 2단계: 소비자 적응 (monitoring.py)

**진입 조건**: 1단계 완료 + 배포 확인  
**종료 조건**: monitoring.py 변경, `_is_promotional_article()` 이중 모드 지원

작업:
- `_is_promotional_article(article)` 에 fallback 로직 추가:
  ```
  if "promotional_likelihood" in article:
      return article["promotional_likelihood"] == "높음"
  # fallback (1단계 이전 데이터)
  return article.get("article_type", "") == "보도자료형"
  ```
- `_determine_category()`의 기획기사 후보 조건에도 동일 패턴 적용

---

### 3단계: UI 추가 배지 (dashboard.py)

**진입 조건**: 2단계 완료  
**종료 조건**: promotional_likelihood 배지 표시 확인 (기존 보도자료형 배지 유지)

작업:
- `_art_type_html()` 옆에 `_promo_html(promotional_likelihood)` 배지 추가
- 기존 보도자료형 배지 그대로 유지 (제거 금지)
- 기사 유형 필터 selectbox는 아직 변경 안 함

---

### 4단계: 보도자료형 반환 제거 준비

**진입 조건**: 3단계 완료 + 담당자 확인  
**종료 조건**: 회귀 테스트 2-field 기준으로 전환, CI 통과

작업:
- `build_regression.py` EXPECTED_MAP에 `promotional_likelihood` 레이블 추가 (45건)
- `test_article_quality.py` 보도자료형 기대값을 새 2-field로 수정
- `test_p2_rules.py` P2 규칙 테스트를 promotional_likelihood="높음" 기준으로 수정
- `classify_article_type()` 에서 보도자료형 반환 → 일반 기사/행사·현장으로 변경

**주의**: 이 단계부터 기존 보도자료형 반환이 사라진다. 이전에 보도자료형을 기대하던 모든 코드 경로를 반드시 확인한다.

---

### 5단계: 소비자 전환

**진입 조건**: 4단계 CI 통과  
**종료 조건**: monitoring.py, dashboard.py에서 보도자료형 하드코딩 완전 제거

작업:
- `monitoring.py` `_NON_INCIDENT_ARTICLE_TYPES`에서 "보도자료형" 제거
- `_is_promotional_article()` fallback 제거 (promotional_likelihood만 사용)
- `dashboard.py` `_pr_suggest()` 에서 `article_type == "보도자료형"` 조건 제거

---

### 6단계: 클린업

**진입 조건**: 5단계 완료 + 1주 운영 모니터링  
**종료 조건**: 코드에 "보도자료형" 하드코딩 없음 (레이블 텍스트 제외)

작업:
- 기사 유형 필터 selectbox에서 "보도자료형" 항목 제거
- `_art_type_html()` 에서 보도자료형 → `art-type-pr` CSS 클래스 제거
- CSS 정리
- 미사용 코드 정리

---

## L. 롤백 계획

각 단계 시작 전 **git tag** 생성 (`pre-stage-1`, `pre-stage-2`, …).

| 단계 | 롤백 복잡도 | 방법 |
|------|------------|------|
| 1단계 | **낮음** | news_fetcher.py 하나만 변경. `git revert` 또는 stage-0 tag로 복구 |
| 2단계 | **낮음** | monitoring.py fallback 있음. `git revert` 가능 |
| 3단계 | **낮음** | UI 배지만 추가. 기존 배지 유지 → 가시적 차이 없음 |
| 4단계 | **중간** | 회귀 테스트 레이블 변경 포함. pre-stage-4 tag로 복구 |
| 5단계 | **중간** | 하드코딩 제거. 보도자료형 기대 경로 확인 필요 |
| 6단계 | **낮음** | 텍스트·CSS 정리. revert 가능 |

**공통 원칙**: 운영 데이터(`data/monitoring_reviews.csv`, Google Sheets)는 스키마 변경 없음. 롤백 시 데이터 손실 없다.

---

## M. 테스트 계획

### M-1. 단계별 진입 전 통과 필수 (기존)

- 기존 77개 테스트 (test_article_quality.py × 32, test_p2_rules.py × 45) 모두 통과
- 새 분류 함수를 추가해도 기존 테스트 실패 금지

### M-2. 신규 테스트 (1단계 작성)

```python
# TestPromotionalLikelihood (신규)
# 강한 PR 신호 → 높음
def test_strong_pr_signal_gives_high():
    assert determine_promotional_likelihood("아이티언, '인그레스 투 엔지에프' 선봬…", "") == "높음"

# P2 규칙 발동 → 높음
def test_p2a_fires_gives_high():
    result = determine_promotional_likelihood(
        "SGA솔루션즈, 호남 중소기업 PC 보안 지원…악성코드·패치 관리 제공", "")
    assert result == "높음"  # P2a 발동 케이스

# 칼럼 기사 → 낮음
def test_column_article_gives_low():
    assert determine_promotional_likelihood("[보안 칼럼] 외교부 해킹이 드러낸 국가 보안의 민낯", "") == "낮음"

# 미공개 단어 → P2c 비발동 → 낮음
def test_migongae_gives_low_promo():
    assert determine_promotional_likelihood("구글, 제미나이 경량모델 3종 출시···'프로'는 미공개", "") != "높음"
```

### M-3. 4단계 회귀 테스트 재레이블 기준

45건 회귀 세트에서 현재 "보도자료형" 12건:
- **12건 모두**: 이후 article_type ≠ 보도자료형, promotional_likelihood = 높음 확인
- **P2 발동 4건** (display_no #04, #12, #20, #43): article_type 재판정 + promotional_likelihood="높음"
- **남은 오분류 2건** (#22, #24): 새 2-field 레이블 재검토 (담당자 확인 필요)

### M-4. 성능 목표 (재정의)

| 지표 | 현재 (article_type=보도자료형 기준) | 목표 (promotional_likelihood="높음" 기준) |
|------|-----|-----|
| 발표 기사 Recall | 100% (P2 적용 후) | 100% 유지 |
| 신규 FP | 0건 | 0건 유지 |
| 전체 정확도 (45건) | 95.6% (43/45) | 95.6% 이상 |

### M-5. 단계별 검증 체크리스트

- [ ] 1단계: `article["promotional_likelihood"]` 필드 존재 확인
- [ ] 1단계: 기존 77 테스트 통과
- [ ] 2단계: `_is_promotional_article()` 신·구 경로 동일 결과 확인 (shadowing 테스트)
- [ ] 3단계: Streamlit 앱에서 홍보성 배지 표시 확인
- [ ] 4단계: CI에서 새 2-field 회귀 테스트 통과
- [ ] 5단계: `grep -rn "보도자료형"` 결과가 레이블 텍스트 외에는 없음 확인
- [ ] 6단계: 필터에서 "보도자료형" 제거 후 기존 검토 기록 검색 무결성 확인

---

## 참고: 현행 코드 위치 요약

| 함수/상수 | 파일 | 라인 | 역할 |
|-----------|------|------|------|
| `classify_article_type()` | news_fetcher.py | 254 | 유형 분류 진입점 |
| `get_compound_pr_rules_fired()` | news_fetcher.py | 249 | P2 규칙 발동 세트 반환 |
| `_STRONG_PR_TITLE_SIGNALS` | news_fetcher.py | 48 | 강한 PR 신호 집합 |
| `_is_promotional_article()` | monitoring.py | 473 | 홍보성 판정 (현재) |
| `_determine_category()` | monitoring.py | 432 | 모니터링 카테고리 결정 |
| `score_monitoring_candidate()` | monitoring.py | 600 | 9축 스코어 계산 |
| `_art_type_html()` | dashboard.py | 670 | 유형 배지 HTML |
| `_pr_suggest()` | dashboard.py | 1396 | PR 제안 문구 |
| 유형 필터 selectbox | dashboard.py | 1966 | 기사 유형 필터 UI |
| `REVIEW_COLS` | monitoring_review_store.py | 34 | 리뷰 저장 스키마 |
