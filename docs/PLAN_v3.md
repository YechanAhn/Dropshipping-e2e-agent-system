# DropAgent Plan v3 — 수요 우선(Demand-First) 재설계

> **이 문서의 위치**
> - `docs/PRD.md` (v2)는 보존한다. 비전·요구사항·용어는 여전히 유효하다.
> - 이 문서(v3)는 **흐름을 뒤집고(공급 우선 → 수요 우선), 끊어진 통합을 새로 잇고, 핵심 누락 컴포넌트(매칭·상세페이지·주문·가격책정)를 새로 짓는** 실행 계획이다.
> - 작성일: 2026-06-13

---

## 0. 한 줄 요약

기존 코드는 **버리지 않는다. 흐름을 뒤집는다.** 검증된 `clients`/`core`/`db` 로직은 살리고, 비어있거나 깨진 레이어를 새로 지어 **"네이버 트렌드 발굴 → 알리 역탐색·매칭 → 마진/가격 검증 → 상세페이지 생성 → 등록 → 주문 드랍쉬핑 → 성과 피드백"** 의 수요 우선 파이프라인을 완성한다. 소스는 **알리 먼저**, 테무는 동일 인터페이스의 어댑터로 **나중에**.

---

## 1. 현재 코드베이스 진단

### 1.1 진짜로 구현된 부분 (재활용)

| 레이어 | 파일 | 상태 |
|--------|------|------|
| 알리 클라이언트 | `clients/aliexpress/affiliate_api.py` (`AliExpressAffiliateClient`) | HMAC-SHA256 서명, 재시도/백오프, 429 처리. **실동작 가능** |
| 네이버 클라이언트 | `clients/naver/{commerce,shopping,datalab,auth}_api.py` | 커머스 등록/주문, 쇼핑 경쟁가 추출, 데이터랩 트렌드. **양질** |
| 환율/알림/LLM | `clients/exchange_rate.py`, `telegram_bot.py`, `llm/{router,cache,prompts}.py` | 태스크별 모델 라우팅 + 캐시 + 이미지분석 경로 존재 |
| 핵심 로직 | `core/{margin_calculator,priority_scorer,demand_estimator,risk_scorer,ops_cost_scorer,category_mapper,idempotency,rate_limiter}.py` | PRD 공식 구현 + 단위테스트 존재 |
| DB | `db/models/*`, `db/repositories/*`, Alembic 마이그레이션 1개 | SQLAlchemy 2.0 async |

### 1.2 빈 껍데기 (0 바이트) — 하필 핵심 기능

- `core/content_generator.py`, `core/image_processor.py` → **상세페이지 자동 생성**
- `agents/order_manager.py` → **주문 자동 드랍쉬핑**
- `agents/{orchestrator,collector,analyzer,content,registrar,monitor}.py` + `agents/tools/*` → **오케스트레이션 전부**
- `api/routes/*`, `api/{deps,middleware}.py`, `dashboard/app.py` → **API·대시보드 표면 전부**
- `clients/aliexpress/scraper.py` → 판매량/리뷰 보조 수집
- `feedback/{ab_tester,model_retrainer}.py` → 피드백 루프 일부

### 1.3 치명적 결함 — 한 번도 같이 돌아간 적이 없음

`scheduler/jobs.py`(793줄, 최대 파일)가 **존재하지 않는 클래스/메서드**를 호출한다:

| jobs.py가 부르는 이름 | 실제 정의된 이름 |
|---|---|
| `AliExpressAffiliateAPI` | `AliExpressAffiliateClient` |
| `.get_trending_products()` | `.get_hot_products()` |
| `.get_product_price()` | `.get_product_detail()` |
| `NaverDatalabAPI` | `NaverDataLabClient` |
| `NaverCommerceAPI` | `NaverCommerceClient` |
| `send_telegram_message` (함수) | `TelegramNotifier` (클래스) |

전부 `try/except ImportError`로 감싸 **조용히 no-op으로 빠진다**. 화려해 보이지만 실행하면 아무 일도 일어나지 않는 "포템킨 코드". 의존성도 미설치 상태라 **전체가 한 번도 실행된 적 없음**.

### 1.4 새 요구사항 대비 통째로 빠진 것

1. **테무** — 전혀 없음 (알리 전용)
2. **수요 우선 소싱** — 기존은 정반대(알리 카탈로그 스캔 → 네이버 수요 추정)
3. **상품 매칭 엔진** — 네이버 상품 ↔ 알리 동일 상품 매칭. 아이디어의 기술적 핵심인데 부재 (PRD도 "공통 식별자 부재"라고 인정만 함)
4. **가격 책정 모듈** — 마진 *계산*은 있으나 최적가 *결정*은 없음

---

## 2. 확정된 방향 (사용자 결정)

| 결정 | 선택 |
|------|------|
| **소싱 방향** | **수요 우선** — 네이버 트렌드/검색량 상위 → 알리 역탐색 → 마진 검증 |
| **소스 범위** | **알리 먼저**, 테무는 `SupplierSource` 어댑터로 나중에 플러그인 |
| **기존 코드** | **선별 재활용 + 재설계** — clients/core/db 유지, 빈/깨진 레이어 신축 |

---

## 3. 타깃 아키텍처 (수요 우선)

```
[1] 수요 발굴 (Demand Discovery)
    네이버 데이터랩 쇼핑인사이트 + 쇼핑검색 + (검색광고 키워드량)
    → 트렌드 상위 키워드/상품 랭킹  → naver_trend_items
        │
        ▼
[2] 소스 역탐색 + 매칭 (Source Matching)   ★ 신규 핵심 컴포넌트
    네이버 상품(한글 제목+이미지+가격) → 알리 후보 검색
    → 멀티모달 LLM 동일성 검증 → match_confidence
        │
        ▼
[3] 마진 검증 (Margin Validation)
    랜딩원가(알리가+배송+환율+수수료+CS/반품 적립) vs 네이버 경쟁가
    → 마진율 → 가격차 임계 통과분만
        │
        ▼
[4] 가격 책정 (Pricing)   ★ 신규
    경쟁가 밴드 언더컷 + 목표마진 하한 + 심리가 반올림
        │
        ▼
[5] 우선순위 스코어링 (재활용: priority_scorer)
    MarginScore + DemandScore − RiskScore − OpsCostScore
        │
        ▼
[6] 상세페이지 생성 (Content)   ★ 신규
    LLM SEO 제목/설명 + 카테고리 매칭 + 이미지 정제(워터마크/리사이즈)
        │
        ▼  ┌─ HITL 승인 게이트 (텔레그램 approve/reject) ─┐
[7] 등록 (Registrar)
    네이버 커머스 API 상품 등록  (멱등성 + AuditLog)
        │
        ▼
[8] 주문 드랍쉬핑 (Order Fulfillment)   ★ 신규
    네이버 신규주문 감시(5분) → 알리 자동주문(결제 전까지)
    → HITL 결제 승인 → 송장 역연동 → 상태 동기화
        │
        ▼
[9] 성과 피드백 (Feedback)
    노출/클릭/전환 추적 → 스코어 가중치 재조정
```

### 3.1 매칭 엔진 — 전체 성패를 가르는 핵심

네이버 상품과 알리 상품은 **공통 식별자(UPC/EAN)가 없다.** 다단계 휴리스틱 + LLM 검증으로 푼다:

1. **번역/속성 추출** (Haiku, 저비용): 한글 제목 → 영문 검색어 + 브랜드/모델/핵심 스펙 추출
2. **후보 검색**: 기존 `AliExpressAffiliateClient.search_products()`로 상위 K개 후보
3. **거친 필터**: 가격비 타당성(알리 랜딩원가 ≪ 네이버가), 카테고리 정합성
4. **멀티모달 검증** (Sonnet, 후보 3~5개만): 네이버 이미지+제목 vs 알리 이미지+제목 비교 → "동일 상품?" 신뢰도 0~1 + 근거. `llm/router.py`의 `image_analysis` 경로 재활용, 비용 통제
5. **임계 처리**: `≥0.85` 자동 채택 / `0.6~0.85` 사람 검토 큐 / `<0.6` 기각
6. **산출물**: 최적 매칭 + 증거(좌우 이미지 + 가격 분해표)
7. **캐싱**: 제목·이미지 해시로 재계산 방지 (비용/속도)

> 정확도가 낮으면 전부 무너진다. Phase 1의 DoD는 "마진 계산"이 아니라 **"검증된 동일 상품 매칭"** 이다.

### 3.2 소스 어댑터 추상화 (알리 먼저 → 테무 나중)

```python
class SupplierSource(Protocol):
    name: str  # "aliexpress" | "temu"
    async def search(self, query, ...) -> list[SourceProduct]: ...
    async def get_detail(self, product_id) -> SourceProductDetail: ...
    async def get_price(self, product_id) -> Price: ...
    async def place_order(self, ...) -> OrderDraft: ...   # Phase 3
```

- `AliExpressSource` = 기존 `AliExpressAffiliateClient` 래핑 (이름 정리)
- `TemuSource` = Phase 4. 공개 API 부재 → 스크래핑/서드파티. 동일 인터페이스라 파이프라인 무변경
- 매칭/마진은 소스 중립. 한 수요 상품에 알리·테무 둘 다 붙여 **더 싼 쪽 선택** 가능

### 3.3 오케스트레이션 — PRD 과설계 단순화

PRD는 LangGraph + MCP + 자율 6에이전트를 요구하나, 1인 셀러 MVP엔 과하다. **결정론 파이프라인 우선, LLM은 도구로**:

- 6개 "에이전트" → **결정론적 파이프라인 스테이지(함수)** 로 구현, APScheduler가 **실제** 클라이언트를 호출
- **LangGraph는 HITL 인터럽트 2곳에만** 도입: ① 상품 등록 승인 ② 주문 결제 승인
- **MCP는 당장 도입 안 함** (불필요한 간접층). 필요해지면 추가
- LLM = 매칭 검증·콘텐츠·카테고리 매칭의 **도구**. 자율 루프 아님

---

## 4. 살린다 / 고친다 / 새로 짓는다

### 살린다 (수정 최소)
`clients/aliexpress/affiliate_api.py`, `clients/naver/*`, `clients/exchange_rate.py`, `clients/telegram_bot.py`, `clients/llm/*`, `core/{margin_calculator,priority_scorer,demand_estimator,risk_scorer,ops_cost_scorer,category_mapper,idempotency,rate_limiter}.py`, `db/models/*`, `db/repositories/*`, `tests/unit/*`, `config.py`, `utils/*`

### 고친다
- `scheduler/jobs.py` — 가상 클래스명 → 실제 클래스명으로 재배선(또는 파이프라인 호출로 교체)
- `core/demand_estimator.py` — 수요 우선 신호(트렌드·검색량 직접) 중심으로 재정렬
- DB 스키마 확장 — `products.source`(ali/temu) 추가, `ali_product_id`→`source_product_id` 일반화, `match_confidence` 추가, 신규 테이블(아래)

### 새로 짓는다
- `core/matcher.py` ★ — 매칭 엔진 (3.1)
- `core/pricing.py` ★ — 최적가 결정
- `core/content_generator.py`, `core/image_processor.py` — 상세페이지/이미지
- `sources/base.py`(`SupplierSource`), `sources/aliexpress.py`, (나중)`sources/temu.py` ★
- `pipeline/` — discovery → match → validate → price → score → content → register → fulfill 스테이지
- `agents/order_manager.py` — 주문 드랍쉬핑
- HITL 그래프 — 등록/결제 승인 (LangGraph interrupt + 텔레그램)
- `api/` (FastAPI) + 최소 대시보드
- 신규 DB 테이블: `naver_trend_items`, `source_candidates`(수요상품별 후보+신뢰도), `match_reviews`(검토 큐)

---

## 5. 단계별 로드맵

### Phase 0 — 정합성 복구 & 토대 (작게, 먼저)
**목표:** 레포가 *실제로 돈다.*
- `uv`로 의존성 설치, `pytest` 그린(살린 core 단위테스트 기준)
- 임포트 타임 깨짐 제거, `scheduler/jobs.py`의 가상 이름 → 실제 이름 정리
- `SupplierSource` 프로토콜 + `AliExpressSource` 어댑터(기존 클라이언트 래핑)
- 로컬 개발 DB 한 방 기동(docker-compose Postgres) + 마이그레이션
- **DoD:** `pytest` 통과 · 앱 부팅 · (키 있으면)알리 검색 1회 + 네이버 쇼핑검색 1회 실호출 성공

### Phase 1 — 발굴 → 매칭 → 마진 (심장)
**목표:** 수요 우선 발굴 루프가 검증된 후보를 뱉는다.
- 수요 발굴 잡(데이터랩 + 쇼핑검색 + 선택적 검색광고 키워드량) → `naver_trend_items`
- **매칭 엔진**(`core/matcher.py`) — 번역→검색→필터→멀티모달검증→신뢰도→검토큐
- 마진 검증(랜딩원가 vs 경쟁가, `margin_calculator` 재활용) + 가격차 임계
- 우선순위 스코어링 재활용 → Top N 발굴 리스트
- 텔레그램/CLI로 결과 + 증거(좌우 이미지·가격분해) 전달
- **DoD:** seed 카테고리 N개 → **검증된 마진 상품 후보**가 증거와 함께 산출

### Phase 2 — 상세페이지 + 가격 + 등록
**목표:** 승인 후 후보 → 네이버 라이브 상품.
- `core/pricing.py` — 경쟁밴드 언더컷 + 목표마진 하한 + 심리가
- `core/content_generator.py` + `image_processor.py` — SEO 제목/설명, 카테고리 매칭, 이미지 정제(워터마크/리사이즈/네이버 규격)
- `commerce_api.register_product` 페이로드 결선
- **HITL 등록 승인**(LangGraph interrupt + 텔레그램) + 멱등성 + AuditLog
- **DoD:** 승인 한 번 → 후보가 (스테이징)네이버 리스팅으로

### Phase 3 — 주문 드랍쉬핑 자동화
**목표:** 주문이 알리로 자동 흐른다(결제만 사람).
- 네이버 주문 감시(5분) → 소스 상품 매핑 → 알리 자동주문 **결제 직전까지**
- **HITL 결제 승인** → 송장 네이버 역연동 → 상태 동기화
- 모든 금전/주문 액션에 멱등성 + AuditLog
- **DoD:** 테스트 주문이 네이버→알리 초안→(수동결제)→송장 동기화까지 흐름

### Phase 4 — 운영 표면 + 피드백 + 테무
- FastAPI + 최소 대시보드(빈 `api/`·`dashboard/` 채움)
- 성과 추적 → 가중치 재조정(피드백 루프)
- **테무 소스 어댑터** 동일 인터페이스로 플러그인, 수요상품별 알리 vs 테무 최저가 선택
- 환율/경쟁가 변동 시 가격 자동 조정

---

## 6. 리스크 & 미결 결정 (별도 합의 필요)

| 항목 | 내용 | 시점 |
|------|------|------|
| **알리 주문 자동화 경로** | Affiliate API는 *주문을 못 넣는다.* 합법 경로는 ① **AE Dropshipping(DS) API**(승인 필요) ② 브라우저 자동화(취약·ToS 회색). 기본값: **결제는 사람(HITL)** | Phase 3 진입 전 |
| **테무 데이터 취득** | 공개 API 없음 + 안티봇. 스크래핑/서드파티 비용·법적 리스크 | Phase 4 |
| **매칭 정확도** | 오매칭 = 엉뚱한 상품 발주. 임계·사람검토 큐로 방어, 초기엔 보수적 임계 | Phase 1 |
| **네이버 커머스 승인 + 고정 IP** | 커머스 API 승인 3~5영업일, 고정 IP 최대 3개. 등록(Phase 2) 전 선행 | Phase 0~2 |
| **이 실행환경 제약** | 의존성 미설치 · API 키 없음 · 아웃바운드 네트워크 정책. 단위/통합은 목/픽스처로, 실호출은 키·정책 필요 | 전반 |
| **LLM 매칭 비용** | 멀티모달 검증을 후보 3~5개로 제한 + 캐싱. 상품 1건 등록당 $0.05 이하 목표 유지 | Phase 1~2 |

---

## 7. 기술 스택 — v2 대비 조정

| 영역 | PRD v2 | v3 결정 | 이유 |
|------|--------|---------|------|
| 오케스트레이션 | LangGraph + MCP + 6에이전트 | 결정론 파이프라인 + HITL만 LangGraph, MCP 보류 | MVP 단순화 |
| 소스 | 알리 전용 | `SupplierSource` 추상화(알리→테무) | 멀티소스 확장 |
| 매칭 | (없음) | `core/matcher.py` 멀티모달 검증 | 수요 우선의 핵심 |
| 대시보드 | Streamlit→Reflex | 텔레그램+CLI 우선 → FastAPI 최소 대시보드 | 표면 최후순위 |
| DB | Supabase→PG+Timescale | 로컬 docker Postgres, Timescale 보류 | 마찰 최소 |
| 유지 | — | LangGraph/Anthropic/SQLAlchemy/httpx/APScheduler/structlog | 그대로 |

---

## 8. 승인 후 즉시 할 일 (Phase 0)

1. 이 문서 커밋·푸시 (완료 시)
2. `uv` 의존성 설치 + `pytest` 그린 만들기
3. `scheduler/jobs.py` 가상 이름 → 실제 클래스명 결선(또는 파이프라인 호출로 교체)
4. `sources/base.py`(`SupplierSource`) + `sources/aliexpress.py` 어댑터
5. docker-compose Postgres + 마이그레이션 적용 확인
6. Phase 0 DoD 보고 후 Phase 1(매칭 엔진) 착수 합의

> **요청:** 위 계획에서 (a) 단계 순서, (b) 오케스트레이션 단순화(LangGraph 축소), (c) 알리 주문 자동화의 결제 HITL 기본값 — 이 세 가지에 이견 없으면 Phase 0부터 시작하겠습니다.
