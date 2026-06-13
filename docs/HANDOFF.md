# DropAgent 핸드오프 가이드

이 문서는 작업을 **다른 환경(로컬 등)의 새 Claude Code 세션**으로 이어받기 위한 것이다.
아래 "초기 프롬프트" 블록을 새 세션의 첫 메시지로 그대로 붙여넣으면 된다.
(상세 배포/운영은 `docs/RUNBOOK.md`, 설계 배경은 `docs/PLAN_v3.md`, 발굴 리서치는 `docs/RESEARCH_discovery.md`.)

---

## 초기 프롬프트 (복사해서 붙여넣기)

````
너는 내 드랍쉬핑 자동화 프로젝트(DropAgent)를 이어받아 개발한다. 아래 맥락을 먼저 숙지하고, 끝의 "첫 번째 할 일"부터 수행해라.

## 0. 목표 (수요 우선 demand-first)
네이버 쇼핑/검색 트렌드에서 "지금 뜨고, 경쟁 약하고, 알리익스프레스 대비 소싱 차익이 큰" 상품 기회를 자동 발굴 →
알리에서 동일 상품 매칭 → 상세페이지 자동 생성 → 네이버 스마트스토어 등록 → 주문 들어오면 알리에서 드랍쉬핑(결제는 사람).

## 1. 저장소 & 로컬 셋업
- 저장소: github.com/YechanAhn/Dropshipping-e2e-agent-system, 작업 브랜치: claude/funny-dirac-gf9p0l
- Python 3.11, 패키지 매니저는 uv.

```bash
git clone https://github.com/YechanAhn/Dropshipping-e2e-agent-system.git
cd Dropshipping-e2e-agent-system
git checkout claude/funny-dirac-gf9p0l
uv venv .venv && source .venv/bin/activate
uv pip install -e ".[dev]"
python -m pytest -q          # 395개 통과해야 정상 (크리덴셜 불필요, 목/페이크 기반)
```

- 라이브 실행엔 크리덴셜 필요 → `cp .env.example .env` 후 docs/RUNBOOK.md §2의 선행작업(검색광고/커머스 API 승인, 고정 IP, VPS, Anthropic/텔레그램 키)을 채운 뒤.

## 2. 먼저 읽을 문서 (이 순서대로)
1. docs/PLAN_v3.md — 재설계 방향(공급 우선→수요 우선), 무엇을 살리고 새로 지었는지.
2. docs/RESEARCH_discovery.md — 발굴 딥리서치(출처 명시). 검색광고=절대 검색량, 경쟁강도=상품수÷검색량, 데이터랩 한계, 소싱/법적 제약, 발굴 파이프라인 설계.
3. docs/RUNBOOK.md — 아키텍처 한눈에 + 배포/운영/실행 명령 + 남은 작업.
(구 docs/PRD.md는 비전 참고용. 일부는 PLAN_v3가 갱신함.)

## 3. 현재 상태 (이미 구현·테스트됨)
- 발굴: clients/naver/searchad_api.py(절대 검색량, HMAC, "<10" 파서), core/discovery/{competition,momentum}.py, pipeline/discovery.py.
- 매칭(핵심): core/matching/(네이버↔알리, 신뢰도 auto/review/reject).
- 가격: core/pricing.py(경쟁밴드 언더컷 + 마진하한 + 심리가).
- 상세페이지: core/content_generator.py(LLM SEO + 등록 페이로드).
- 소싱 오케스트레이터: pipeline/sourcing.py(발굴후보→매칭→가격→상세→등록페이로드).
- 주문: agents/order_manager.py(결제 HITL, 자동결제 금지).
- 표면/런루프: api/(FastAPI create_app), scheduler/jobs.py+runner.py, main.py(스케줄러+API 동시).
- 빠른 확인: python scripts/run_discovery.py 무선이어폰 차량용거치대 --top 15 (검색광고+쇼핑 키 필요).

## 4. 아직 비어있는 것 / 다음 작업 (우선순위)
중요: src/dropagent/agents/{collector,analyzer,content,registrar,monitor,orchestrator}.py와 agents/tools/*는 구 LangGraph 설계의 "잔재 빈 파일"이다. 현재 아키텍처는 결정론 파이프라인(pipeline/+scheduler/jobs.py)으로 대체됐으니 거기에 코드를 채우지 말고, 무시하거나 삭제해라(헷갈림 방지).

실제 다음 작업(우선순위순):
1) 데이터랩 모멘텀 provider 결선 — pipeline/discovery.py의 DiscoveryPipeline(momentum_provider=...)에 clients/naver/datalab_api.py의 get_keyword_trend를 어댑터로 연결(반환 NaverTrendResult.results[].data[].ratio → list[float]). 단, datalab get_keyword_trend가 쇼핑 URL/카테고리 의존이 맞는지 먼저 점검.
2) 발굴 결과 DB 영속화 강화 — 현재 AnalyticsRepository.add_trend_data로 저장. 발굴 후보를 products(status=candidate)로도 적재하고 승인→등록 흐름과 연결. 필요시 신규 테이블 + alembic 마이그레이션.
3) 멀티모달 매칭 검증 — core/matching의 verifier 기본이 텍스트 비교. 고가치(마진 50%+) 상품에 한해 LLM 이미지 비교로 업그레이드(core/image_processor.py도 채움).
4) 텔레그램 인라인 승인 워크플로우 — /products/{id}/approve를 텔레그램 버튼으로.
5) 피드백 루프 — feedback/{model_retrainer,ab_tester}.py 구현(성과→가중치 재조정).
6) /settings DB 영속화(현재 인메모리 스텁).
7) (나중) 테무 소스 — SupplierSource 어댑터로 추가(공개 API 없음 → 스크래핑/서드파티).

## 5. 반드시 지킬 원칙
- 수요 우선: 네이버 트렌드에서 출발해 알리로 역탐색(반대 아님).
- 공식 API 우선: 네이버 페이지 무단 스크래핑 금지(DB제작자권리 침해 판례 있음). TOP500 스크래핑 옵션은 기본 OFF.
- 결제 무인 자동화 금지: 주문은 결제 직전까지만(HITL).
- 멱등성/레이트리밋 준수: 스케줄 작업은 IdempotencyManager, 검색광고/커머스/데이터랩 쿼터 준수.
- ★ 안티-포템킨(이 코드베이스의 핵심 교훈): 존재하지 않는 클래스/메서드 이름을 호출하는 코드를 절대 쓰지 마라. 새 코드가 의존하는 이름은 실제 파일을 열어 시그니처를 확인하고, eager import로 작성해 누락 시 즉시 실패하게 하라. 통합 시 tests/unit/test_jobs_wiring.py처럼 "참조 이름이 실존하는지" 확인하는 테스트를 추가하라. 원래 이 레포의 scheduler/jobs.py가 가짜 이름을 try/except로 감싸 조용히 아무 것도 안 하는 버그였다.
- 모든 외부 의존은 주입(DI)해서 목/페이크로 단위테스트 가능하게. 작업 후 python -m pytest -q(그린)와 ruff check(클린) 유지. 레포 스타일(타입힌트, 절대 import, 라인 120) 따르기.

## 6. 첫 번째 할 일
1. 위 셋업 명령으로 python -m pytest -q가 395개 통과하는지 확인하고 결과를 보고하라.
2. docs/PLAN_v3.md, docs/RESEARCH_discovery.md, docs/RUNBOOK.md를 읽고 현재 아키텍처를 3~5문장으로 요약하라.
3. §4의 1번 작업(데이터랩 모멘텀 provider 결선)에 대해, clients/naver/datalab_api.py를 점검한 뒤 구현 계획(어떤 함수/반환형/엣지케이스/테스트)을 제시하라. 승인 전엔 코드를 바꾸지 말고 계획만.
이 세 가지를 마치면 멈추고 내 확인을 기다려라.
````

---

## 사용 팁
- 새 로컬 Claude Code 세션을 `Dropshipping-e2e-agent-system` 폴더에서 열고 위 블록을 첫 메시지로 붙여넣는다. 이미 클론돼 있으면 clone 줄은 건너뛴다.
- 라이브 테스트까지 가려면 `.env`만 채우면 되고, 발굴부터 빠르게 확인하려면 검색광고+쇼핑 키만으로 `scripts/run_discovery.py`가 돈다.
- 최신을 받으려면: `git fetch && git checkout claude/funny-dirac-gf9p0l && git pull`.
- 현재 기준 커밋 히스토리(브랜치 `claude/funny-dirac-gf9p0l`): Plan v3 → rate-limiter fix → discovery research → discovery pipeline → downstream value chain → scheduler de-Potemkin → runbook → (이 문서) handoff.
