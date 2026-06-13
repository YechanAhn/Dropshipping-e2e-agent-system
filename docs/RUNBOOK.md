# DropAgent 운영 런북 (Production Runbook)

수요 우선(demand-first) 네이버 스마트스토어 × 알리익스프레스 드랍쉬핑 자동화 시스템의 배포·운영 가이드.
설계 배경은 `docs/PLAN_v3.md`(재설계)와 `docs/RESEARCH_discovery.md`(발굴 딥리서치) 참고.

---

## 1. 아키텍처 한눈에

```
[스케줄러 (APScheduler) ─ main.py] ── 동시 ── [FastAPI (create_app) :8000]
        │                                              │
        ├─ collect_naver_trends_job ──► DiscoveryPipeline (S1~S7)
        │     검색광고(절대 검색량) + 쇼핑(상품수) → 경쟁강도/기회점수 → DB
        ├─ auto_register_products_job ─► SourcingOrchestrator
        │     (approved 상품만) 매칭 → 가격 → 상세페이지 → 커머스 등록  ← HITL 승인
        ├─ check_orders_job ──────────► OrderManager.poll_new_orders → 주문 동기화
        ├─ monitor_price_changes_job ─► 알리 가격 추적
        └─ daily_report_job ──────────► 텔레그램 일일 리포트

핵심 흐름:  네이버 트렌드 발굴 → (승인) → 알리 매칭 → 상세페이지 → 등록 → 주문 드랍쉬핑(결제는 사람)
```

핵심 모듈
- 발굴: `clients/naver/searchad_api.py`(절대 검색량), `core/discovery/{competition,momentum}.py`, `pipeline/discovery.py`
- 소싱: `core/matching/`(네이버↔알리 매칭), `core/pricing.py`, `core/content_generator.py`, `pipeline/sourcing.py`
- 주문: `agents/order_manager.py` (결제 HITL)
- 표면: `api/`(FastAPI), `scheduler/`(런루프), `clients/telegram_bot.py`(알림)

---

## 2. 선행 작업 (당신만 할 수 있는 Phase-0 운영)

> 코드는 "크리덴셜만 꽂으면 도는" 상태입니다. 라이브 전 아래는 직접 처리해야 합니다.

- [ ] 네이버 개발자센터 앱 등록 → `NAVER_CLIENT_ID/SECRET` (쇼핑·데이터랩, 일 25,000 / 데이터랩 1,000회)
- [ ] **네이버 검색광고 API** 라이선스 발급(searchad.naver.com, 도구>API) → `NAVER_SEARCHAD_API_KEY/SECRET_KEY/CUSTOMER_ID` (절대 검색량의 유일 소스)
- [ ] 네이버 커머스 API 승인(영업일 3~5일) + **고정 IP 등록(최대 3개)** → `NAVER_COMMERCE_CLIENT_ID/SECRET`
- [ ] 알리 Affiliate API 승인 → `ALI_APP_KEY/SECRET/TRACKING_ID`
- [ ] Anthropic API 키 → `ANTHROPIC_API_KEY` (번역/상세페이지/매칭 검증)
- [ ] 텔레그램 봇(BotFather) → `TELEGRAM_BOT_TOKEN/CHAT_ID`
- [ ] 고정 IP VPS(예: Hetzner) + PostgreSQL + Redis
- [ ] **착수 전 확인**: `shopping.naver.com/robots.txt`·데이터랩 약관 — TOP500 스크래핑 옵션은 기본 OFF, 켤지 결정(네이버 DB 무단크롤링 판례 있음 — `RESEARCH_discovery.md` §6)

---

## 3. 환경 설정

```bash
cp .env.example .env          # 위 크리덴셜 채우기
uv venv .venv && source .venv/bin/activate
uv pip install -e ".[dev]"    # 의존성
```

DB(도커):
```bash
docker compose up -d db redis   # PostgreSQL + Redis
alembic upgrade head            # 스키마 마이그레이션
python scripts/seed_categories.py   # 알리→네이버 카테고리 시드(선택)
```

---

## 4. 실행

```bash
# 1) 테스트 (크리덴셜 불필요 — 395개 통과해야 정상)
python -m pytest -q

# 2) 발굴만 빠르게 확인 (검색광고+쇼핑 키 필요)
python scripts/run_discovery.py 무선이어폰 차량용거치대 --top 15 --max-competition 2.0

# 3) API 서버 단독
uvicorn dropagent.api.app:create_app --factory --host 0.0.0.0 --port 8000
#   GET /health, /products, /orders, /analytics/summary, /settings ; POST /products/{id}/approve|reject

# 4) 전체 서비스 (스케줄러 + API 동시) — 프로덕션 진입점
python -m dropagent.main
```

도커 전체 기동: `docker compose up -d` (Dockerfile/compose 포함).

---

## 5. 운영 사이클 (일 30분~1시간)

1. **발굴**: `collect_naver_trends_job`(12h)가 시드 키워드 → 기회 키워드를 DB에 적재.
2. **검토/승인(HITL)**: 대시보드/`POST /products/{id}/approve`로 등록할 상품 승인.
3. **등록**: `auto_register_products_job`(1h)이 `approved` + `priority_score≥60`만 매칭→가격→상세→커머스 등록.
4. **주문**: `check_orders_job`(5m)이 신규 주문 감지→알리 주문 초안. **결제는 당신이 승인**(자동 결제 안 함).
5. **모니터링**: 가격 추적 + 텔레그램 일일 리포트.

스코어링 가중치/자동화 토글은 `GET/PUT /settings`(현재 인메모리 스텁 → DB 영속화는 후속).

---

## 6. 안전장치 / 원칙 (코드에 반영됨)

- **결제 무인 자동화 안 함**: `OrderManager`는 결제 직전까지만, `needs_payment_approval=True`.
- **공식 API 우선**: 네이버 페이지 스크래핑은 법적 리스크(판례) → 기본 OFF.
- **멱등성**: 모든 스케줄 작업은 `IdempotencyManager` 키로 중복 실행 방지.
- **레이트리밋**: 검색광고(키워드도구 1/5~1/6 스로틀), 커머스(2 req/s 토큰버킷), 데이터랩(1,000/일은 shortlist에만).
- **소싱 회피**: 브랜드/인증(전안법·KC·식약처)·유아용품·카탈로그 매칭 상품은 페널티/제외.

---

## 7. 의도적으로 남긴 것 (다음 단계)

| 항목 | 상태 | 비고 |
|------|------|------|
| 데이터랩 모멘텀 provider 결선 | 인터페이스 분리됨 | `DiscoveryPipeline(momentum_provider=...)`에 datalab 백엔드 연결 |
| 멀티모달 매칭 검증 | 텍스트 verifier 기본 | 고가치 상품에 이미지 비교(LLM vision) 업그레이드 |
| 피드백 재학습/AB | 스텁 | `feedback/{model_retrainer,ab_tester}.py` |
| 설정 DB 영속화 | 인메모리 스텁 | `/settings` → DB |
| 텔레그램 승인 UX | 알림만 | 인라인 버튼 승인 워크플로우 |
| 테무 소스 | 미구현 | `SupplierSource` 어댑터로 추가(공개 API 부재) |

---

## 8. 트러블슈팅

- `python -m pytest`가 빨갛다 → 의존성 미설치(`uv pip install -e ".[dev]"`).
- 발굴이 빈 결과 → `--min-volume` 낮추거나 `--max-competition` 높이기; 검색광고 키 확인.
- 잡이 조용히 아무 것도 안 함 → 더 이상 발생하지 않음(포템킨 제거 + `test_jobs_wiring.py`가 가짜 이름/시그니처를 차단). 크리덴셜 누락 시 잡 로그에 명시적 경고.
- 커머스 등록 실패 → 고정 IP 등록 여부 + `productType`/카테고리 매핑 확인.
