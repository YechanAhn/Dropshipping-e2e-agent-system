# DropAgent PRD v2.0 (Final)
## 드롭쉬핑 E2E 자동화 에이전트 시스템

> **버전 이력**
> - v1.0: Gemini 기술스택 비판적 검토 + 초기 설계
> - v2.0 (현재): ChatGPT 비판 통합, Phase 0 추가, 스코어링 개선, Idempotency/AuditLog/피드백 루프 추가

---

## 목차

1. [Gemini 제안 기술스택 비판적 검토](#1-gemini-제안-기술스택-비판적-검토)
2. [알리-네이버 마진율 분석 실현 가능성](#2-알리-네이버-마진율-분석-실현-가능성)
3. [제품 개요](#3-제품-개요)
4. [목표 및 범위](#4-목표-및-범위)
5. [핵심 기능 요구사항 (FR)](#5-핵심-기능-요구사항)
6. [비기능 요구사항 (NFR)](#6-비기능-요구사항)
7. [데이터베이스 모델](#7-데이터베이스-모델)
8. [피드백 루프 및 재학습](#8-피드백-루프-및-재학습)
9. [리스크 매트릭스](#9-리스크-매트릭스)
10. [단계별 개발 계획](#10-단계별-개발-계획)
11. [최종 기술스택](#11-최종-기술스택)
12. [아키텍처 다이어그램](#12-아키텍처-다이어그램)
13. [프로젝트 디렉토리 구조](#13-프로젝트-디렉토리-구조)
14. [부록](#14-부록)

---

## 1. Gemini 제안 기술스택 비판적 검토

### 1.1 에이전트 프레임워크: CrewAI 또는 LangGraph

**Gemini 제안의 문제점:**

"CrewAI 또는 LangGraph"라고 병렬 제안한 것 자체가 두 프레임워크의 본질적 차이를 이해하지 못한 결과다.

| 구분 | CrewAI | LangGraph |
|------|--------|-----------|
| 추상화 수준 | 고수준 (역할 기반) | 저수준 (그래프 기반) |
| 상태 관리 | Task output 기반, 체크포인팅 없음 | 명시적 상태 그래프, 시간여행 디버깅 |
| 조건 분기 | 제한적 | 네이티브 조건부 엣지, 사이클 지원 |
| HITL (승인) | 가이드 존재하나 추가 설계 필요 | Interrupt 기반 중단/재개 네이티브 |
| 프로덕션 안정성 | 디버깅 어려움 | API 안정성 보장 |

**비판:**

드롭쉬핑 시스템은 "소싱 → 콘텐츠 생성 → 등록 → 주문 감시 → CS"라는 **명확한 상태 전이와 조건 분기**가 필요한 워크플로우다. "상품 등록 실패 시 재시도 → 3회 실패 시 스킵 후 알림" 같은 로직은 그래프 기반 상태 머신이 자연스럽다. CrewAI의 "역할 기반 협업"은 **과도한 자율성이 오히려 리스크**.

**최종 판단:**

> **LangGraph + MCP** 채택. LLM이 불필요한 결정론적 구간은 일반 Python 함수, LLM 필요한 노드만 에이전트로 구성하는 **하이브리드 접근**.
> - MCP (Model Context Protocol)로 외부 도구를 표준화하여 확장성 극대화
> - LangGraph의 Interrupt 기능으로 승인 워크플로우를 네이티브하게 구현

---

### 1.2 LLM: Claude 3.5 Sonnet

**문제점:** Claude 3.5 Sonnet은 레거시. 모든 태스크에 동일 모델은 비용 대비 효율 극히 낮음.

**최종 판단: 태스크별 모델 라우팅**

| 태스크 | 권장 모델 | 이유 |
|--------|-----------|------|
| 상품 설명 생성/번역 | Claude Sonnet 4 | 품질/비용 균형 |
| 마진율 분석 판단 | Claude Sonnet 4 | 구조화된 추론 |
| 카테고리 매칭 | Claude Haiku 3.5 | 단순 분류, 비용 절감 |
| 키워드 추출 | Claude Haiku 3.5 | 속도 우선 |
| 이미지 분석 | Claude Sonnet 4 | 멀티모달 (고가치 상품만) |

> **비용 전략**: 반복 작업은 캐싱 → 데이터 축적 후 scikit-learn 경량 모델로 전환

---

### 1.3 DB: Supabase 또는 PostgreSQL

**문제점:** "또는"이 문제. **Supabase IS PostgreSQL.** 호스팅 vs Self-hosted 선택의 문제.

**치명적 누락: Redis** — API 캐싱, Rate Limit, 큐에 **필수**.

**최종 판단:**
- Phase 0-2: **Supabase 호스팅** → 빠른 개발
- Phase 3+: **Self-hosted PostgreSQL + TimescaleDB** → 시계열 최적화, 비용 절감
- 전 Phase: **Redis** 캐시/큐/Rate Limit 레이어

---

### 1.4 브라우저 자동화: Playwright

**문제점:** 안티봇 탐지에 취약. 알리는 Cloudflare + 자체 안티봇 운영.

**최종 판단: 다층 전략**
1. **1차: 공식 API** (알리 Affiliate API, 일 5,000건)
2. **2차: nodriver** (API 불가 데이터)
3. **3차: 서드파티** (Apify/ScrapFly fallback)
4. **네이버는 공식 API만** (법적 리스크 회피)

---

### 1.5 메시징: Slack SDK / Discord Webhook

**문제점:** 한국 셀러 맥락에 부적합.

**최종 판단:**

| 우선순위 | 채널 | 이유 |
|---------|------|------|
| 1순위 | **텔레그램 Bot API** | 무료, 봇 API 완성도 높음, 셀러 커뮤니티 표준 |
| 2순위 | 카카오톡 알림톡 | 자연스러움, 건당 8-15원 |
| 3순위 | Slack Webhook | 내부 모니터링용으로만 |

---

### 1.6 대시보드: Streamlit / Retool

**문제점:** Streamlit은 전체 리로드, RAM 선형 증가, 백엔드 없음 등 프로덕션 한계.

**최종 판단:**
- Phase 1: **Streamlit** (MVP 프로토타입)
- Phase 4: **FastAPI + Reflex** (Python 풀스택)

---

### 1.7 인프라: Docker + AWS EC2 / VPS

**문제점:** 네이버 커머스 API 고정 IP 최대 3개 필요. AWS 비용 과도.

**최종 판단:**
- 초기: **Hetzner VPS** (고정 IP 포함, $7-15/월)
- Phase 3+: Docker Compose 단일 서버 컨테이너화

---

### 1.8 에이전트 구조: 3개 에이전트

**문제점:** 너무 거침. 단일 책임 원칙 위반.

**최종 판단: 5+1 에이전트**

```
[오케스트레이터]
    ├── [데이터 수집 에이전트] : 알리 크롤링, 네이버 가격/트렌드 수집
    ├── [분석 에이전트]       : 마진율 계산, 판매량 추정, 우선순위 스코어링
    ├── [콘텐츠 에이전트]     : 번역, SEO 최적화, 상세페이지 생성
    ├── [등록 에이전트]       : 네이버 커머스 API 상품 등록/수정/삭제
    ├── [주문/CS 에이전트]    : 주문 감시, 알리 자동 주문, 배송 추적
    └── [모니터링 에이전트]   : 헬스체크, 에러 알림, 성능 메트릭
```

---

### 1.9 스케줄링: Cron Job

**문제점:** Python 통합 어렵고 에러 핸들링/재시도/의존성 관리 불가.

**최종 판단: APScheduler + Redis**

| 태스크 | 주기 | 비고 |
|--------|------|------|
| 알리 상품 데이터 수집 | 6시간 | API 일 5,000건 |
| 네이버 트렌드 수집 | 12시간 | 데이터랩 API |
| 마진율 분석/우선순위 갱신 | 6시간 | 수집 후 트리거 |
| 상품 자동 등록 | 1시간 | 커머스 API 초당 2회 |
| 주문 확인 | 5분 | 커머스 API |
| 가격 변동 감시 | 3시간 | 알리 API |
| 시스템 헬스체크 | 1분 | 내부 |

---

## 2. 알리-네이버 마진율 분석 실현 가능성

### 2.1 핵심 도전: 공통 식별자 부재

알리 상품과 네이버 상품 사이에 UPC/EAN 같은 공통 키가 대부분 없다.

| 데이터 소스 | 확보 가능 데이터 | 방법 | 제한 |
|------------|----------------|------|------|
| 알리 Affiliate API | 상품명, 가격, 할인율, 이미지, 카테고리 | 공식 API | 일 5,000건 |
| 알리 웹 | 판매량, 리뷰 수, 평점, 배송비 | nodriver | 안티봇 리스크 |
| 네이버 쇼핑 검색 API | 상품명, 가격, 판매처, 브랜드 | 공식 API | 일 25,000건 |
| 네이버 데이터랩 | 카테고리 클릭 추이 (상대값), TOP 500 키워드 | 공식 API | **절대값 미제공** |
| 네이버 쇼핑파트너센터 | 자사 상품 노출수/클릭수 (절대값) | 로그인 조회 | 자사만 |

### 2.2 마진율 계산 알고리즘

```
마진율 = (네이버 판매 예상가 - 총 원가) / 네이버 판매 예상가 × 100

총 원가 = 알리 상품가
        + 알리 배송비
        + 환율 마진 (5%)
        + 네이버 수수료 (카테고리별 5.5~11%)
        + CS 리스크 비용 (3%)
        + 환불/반품 비용 (2%)
```

**네이버 판매 예상가 산정:**
1. 네이버 쇼핑 검색 API로 유사 상품 검색 (키워드 기반)
2. 상위 10개 결과의 가격 분포 분석
3. 중앙값 또는 25~50 백분위수를 "경쟁력 있는 가격"으로 설정
4. 목표 마진율(예: 30%)을 역산하여 소싱 가격 상한선 도출

### 2.3 판매량 추정 — "DemandScore"로 재정의

> **핵심 (ChatGPT 비판 반영):** 네이버에서 상품별 '실제 판매량'은 외부에 직접 제공되지 않는다. PRD에서 "판매량"을 **DemandScore (수요 점수)**로 재정의하여 구현한다.

**다층 프록시 모델:**

```
DemandScore = f(
    클릭 추이 상대값,      ← 네이버 데이터랩
    키워드 검색량,          ← 검색광고 API
    카테고리 경쟁도,        ← 쇼핑 검색 API
    리뷰 수 증가율,         ← 쇼핑 검색 API 주기적 추적
    자사 실측 데이터        ← 쇼핑파트너센터 (Phase 3+)
)
```

**ROI 순서 (무엇부터 넣을까):**
1. **1순위: 키워드 검색량** — 가장 직접적인 수요 지표, API로 즉시 확보
2. **2순위: 리뷰 수 증가율** — 구매자의 3-10%가 리뷰 작성, 판매량 프록시로 유의미
3. **3순위: 클릭 추이** — 데이터랩 상대값, 트렌드 방향성 파악
4. **4순위: 자사 실측** — Phase 3 이후 교차 검증으로 모델 정밀도 향상

### 2.4 우선순위 스코어링 공식 (v2, 개선)

> **v1 → v2 변경점:** 단순 가산에서 **감점 요소 (RiskScore, OpsCostScore)를 뺄셈으로 분리**하여 리스크가 높은 상품이 자동으로 후순위로 밀리게 개선.

```python
priority_score = (
    w1 * margin_score           # 마진율 (0~1)
    + w2 * demand_score         # 수요 점수 (0~1)
    - w3 * risk_score           # 리스크 감점 (0~1) ← v2 신규
    - w4 * ops_cost_score       # 운영비용 감점 (0~1) ← v2 신규
    + w5 * supplier_reliability # 공급자 신뢰도 (0~1)
)

# 초기 가중치 (실험적 조정, 피드백 루프로 자동 최적화)
w1, w2, w3, w4, w5 = 0.35, 0.25, 0.15, 0.15, 0.10
```

**RiskScore 구성 요소:**

| 팩터 | 감점 조건 | 비고 |
|------|----------|------|
| 배송 기간 | 30일 이상: 0.8, 20-30일: 0.4 | 고객 CS 급증 |
| 파손 리스크 | 유리/도자기: 0.9, 전자제품: 0.5 | 반품률 상승 |
| 통관 리스크 | 화장품: 0.7, 식품: 0.9, 전자: 0.4 | 인증/규제 |
| 무게/부피 | 2kg 초과: 0.5 | 배송비 급증 |

**OpsCostScore 구성 요소:**

| 팩터 | 감점 조건 | 비고 |
|------|----------|------|
| 옵션 수 | 5개+: 0.6, 10개+: 0.9 | 등록/관리 복잡도 |
| 상세페이지 난이도 | 사이즈 차트 필요: 0.5 | LLM 비용 증가 |
| 예상 CS량 | 카테고리별 히스토리 기반 | 의류: 높음 |
| 반품률 | 카테고리 평균 반품률 | 의류 15%+: 감점 |

### 2.5 실현 가능성 판정

| 기능 | 판정 | 비고 |
|------|------|------|
| 마진율 계산 | **실현 가능** | 알리 API + 네이버 쇼핑 검색 API |
| 판매량 추정 | **DemandScore로 대체** | ±30% 오차, 상대 순위 유의미 |
| 자동 우선순위 | **실현 가능** | 감점 포함 다중 팩터 스코어링 |
| "빅데이터 분석" | **과장된 표현** | "다중 소스 휴리스틱 스코어링"이 정확 |

---

## 3. 제품 개요

| 항목 | 내용 |
|------|------|
| **제품명** | DropAgent — 드롭쉬핑 E2E 자동화 에이전트 시스템 |
| **목적** | 알리익스프레스 → 네이버 스마트스토어 풀사이클 자동화 |
| **핵심 가치** | "높은 마진 + 검증된 수요" 상품을 데이터 기반 자동 발굴, 수작업 대비 10배+ 효율 |
| **사용자** | 네이버 스마트스토어 드롭쉬핑 셀러 (1인~소규모 팀) |
| **운영 모델** | Solo 셀러: 하루 30분~1시간 승인/수정 운영 |

---

## 4. 목표 및 범위

### 4.1 프로젝트 목표
1. 마진 30% 이상 상품을 자동 발굴하여 일 10개+ 추천
2. 상품 등록 프로세스를 수동 대비 90% 시간 절감
3. 주문 발생 시 5분 이내 자동 감지 및 알림
4. LLM 기반 콘텐츠로 네이버 SEO 점수 향상

### 4.2 In-Scope
- 알리 상품 데이터 수집 (공식 API + 제한적 nodriver)
- 네이버 시장 데이터 수집 (쇼핑 검색, 데이터랩)
- 마진율 계산 및 DemandScore 기반 우선순위 스코어링
- LLM 콘텐츠 자동 생성 (텍스트 우선, 이미지 선택적)
- 네이버 커머스 API 자동 등록
- 주문 감시 및 알리 반자동 주문 (결제 승인 필수)
- CS 문의 분류 및 응답 초안 생성
- 텔레그램 실시간 알림 및 승인 워크플로우
- 관리 대시보드
- 성과 추적 → 스코어링 모델 재학습 (피드백 루프)

### 4.3 Non-Goals

> **ChatGPT 비판 반영: 명시적으로 구현하지 않는 기능**

1. **판매량 공식 수치 보장 안 함**
   - 네이버 데이터랩은 절대값 미제공 → DemandScore (추정 지표)로 대체
   - ±30% 오차 범위 존재, 상대 순위 비교 목적

2. **결제 무인 자동화 안 함**
   - 알리 자동 주문 시 **결제는 수동 확인 필수** (HITL)
   - 계정 잠김, 리스크 룰, CS 분쟁, 자동결제 오류 등 운영비용 방지
   - Phase 5 이후 신뢰도 축적 시 검토

3. **불법 크롤링 안 함**
   - 공식 API 우선, nodriver는 API 불가 데이터만 제한적 수집
   - robots.txt 준수, Rate Limit 엄격 준수
   - 네이버는 공식 API만 사용

4. **다중 플랫폼 안 함 (Phase 1-4)**
   - 초기: 알리 → 네이버만
   - 타오바오, 쿠팡 등은 Phase 5 이후

5. **OCR/비전 무분별 적용 안 함**
   - 이미지 분석은 **토큰/비용 폭탄** 리스크
   - 텍스트 기반 콘텐츠 우선, 고가치 상품(마진 50%+)만 선택적 적용

---

## 5. 핵심 기능 요구사항

### FR-001: 상품 소싱 및 데이터 수집
- 알리 Affiliate API를 통한 상품 검색 (카테고리/키워드 seed 기반)
- 상품 상세 정보 수집 (가격, 배송비, 평점, 주문 수, 셀러 정보)
- nodriver로 판매량, 리뷰 수 보조 수집 (API 불가 시)
- 수집 데이터 DB 저장 및 이력 관리
- **Idempotency Key 기반 중복 수집 방지**

### FR-002: 네이버 시장 데이터 수집
- 쇼핑 검색 API로 동종 상품 가격 조사
- 데이터랩 쇼핑인사이트 API로 카테고리 트렌드 수집
- 키워드별 검색량 및 경쟁도 데이터 수집
- 시계열 저장 (TimescaleDB 활용)

### FR-003: 마진율 분석 및 우선순위 스코어링
- 실시간 환율 반영 원가 계산
- 카테고리별 네이버 수수료 자동 반영
- **개선된 스코어링: MarginScore + DemandScore - RiskScore - OpsCostScore**
- 가중치 사용자 조정 가능 (대시보드)
- 분석 결과 시각화 (차트, 테이블, Top N 추천)

### FR-004: 콘텐츠 자동 생성 (텍스트 우선 전략)

> **ChatGPT 비판 반영: "텍스트 우선 → 이미지 선택적" 비용 최적화**

**필수 (텍스트, 모든 상품):**
- LLM 상품명 번역 및 SEO 최적화 (Sonnet 4)
- 상세 설명 자동 생성 (네이버 가이드라인 준수)
- 카테고리 자동 매칭 (Haiku 3.5)
- 키워드 추출 (Haiku 3.5)

**선택적 (이미지, 고가치 상품만):**
- 이미지 다운로드 및 최적화
- 멀티모달 분석은 **마진 50%+ 상품만** 적용
- Draft 버전 관리 + 운영자 수정 피드백

### FR-005: 스마트스토어 상품 등록
- 네이버 커머스 API 자동 등록/수정/삭제
- Rate Limit 준수 (초당 2회, Token Bucket + Redis)
- 등록 실패 시 지수 백오프 재시도 (최대 3회)
- **Idempotency Key 기반 중복 등록 방지**
- 등록 상태 추적 및 텔레그램 알림
- 등록 전 사용자 승인 옵션 (기본값 설정 가능)

### FR-006: 주문 관리 및 반자동 처리
- 신규 주문 5분 단위 감시 (APScheduler)
- 알리 자동 주문: 장바구니/배송지 입력까지 자동
- **결제는 수동 확인 필수** (Non-Goal 반영)
- 배송 추적 번호 자동 연동
- 주문 상태 동기화 (알리 ↔ 네이버)
- 예외 알림 (품절, 가격 변동)

### FR-007: CS 지원
- 고객 문의 자동 분류 (배송/교환/환불/일반)
- LLM 응답 초안 생성 (Sonnet 4)
- 검토 요청 알림 (자동 발송은 선택적)
- 반품/환불 프로세스 트래킹
- CS 히스토리 기반 OpsCostScore 업데이트

### FR-008: 알림 및 승인 워크플로우
- 텔레그램 봇 실시간 알림 (주문, 에러, 일일 리포트)
- **승인 워크플로우** (LangGraph Interrupt 기반):
  - 상품 추천 → 승인/거절/보류/수정요청
  - 콘텐츠 검토 → 승인/수정
  - 주문 결제 → 결제 진행/보류
- 에이전트별 실행 이력 및 로그
- 일일/주간 매출/마진 리포트

### FR-009: 피드백 루프 및 재학습 (v2 신규)
- 등록 상품의 실제 성과 추적 (노출수, 클릭수, 전환율, 매출)
- 성과 데이터를 스코어링 가중치에 피드백
- 주기적 모델 재학습 (월 1회 배치)
- A/B 테스트 지원 (콘텐츠 버전, 가격 전략)

---

## 6. 비기능 요구사항

| NFR | 요구사항 | 목표치 | 우선순위 |
|-----|---------|--------|---------|
| NFR-001 | API Rate Limit 준수 | 429 에러 0.1% 미만 | P0 |
| NFR-002 | 시스템 가용성 | 99.5% (월 3.6h 이하 다운) | P0 |
| NFR-003 | 데이터 보존 | 6개월 이상 이력 | P1 |
| NFR-004 | 대시보드 응답 | 페이지 로드 3초 이내 | P1 |
| NFR-005 | LLM 비용 | 상품 1건 등록당 $0.05 이하 | P0 |
| NFR-006 | 보안 | API 키/토큰 암호화, 환경변수 관리 | P0 |
| NFR-007 | 법적 준수 | 공식 API 우선, robots.txt 준수 | P0 |
| **NFR-008** | **Idempotency (중복실행방지)** | **동일 작업 중복 실행 0건** | **P0** |
| **NFR-009** | **Audit Log (감사로그)** | **모든 중요 작업 100% 기록** | **P0** |
| NFR-010 | 테스트 커버리지 | 핵심 모듈 80% 이상 | P1 |

### NFR-008 상세: Idempotency

> **ChatGPT 비판 반영: 네트워크 재시도, 스케줄러 중복, 사용자 실수 등으로 인한 중복 실행 방지**

**구현:**
- JobRun 테이블에 `idempotency_key` (SHA256 해시) UNIQUE 제약
- 작업 시작 전 key 존재 확인 → 이미 실행 중/완료면 Skip
- Key 생성: `SHA256(job_type + entity_id + timestamp_truncated_to_hour)`

**적용 범위:** 상품 수집, 상품 등록/수정, 주문 처리, CS 응답 발송

### NFR-009 상세: Audit Log

> **ChatGPT 비판 반영: 승인/실행/실패 원인 추적, 법적 분쟁 시 증빙**

**기록 대상:**
- 상품 등록/수정/삭제 (변경 전후 데이터)
- 주문 처리 (알리-네이버 주문 ID 매핑)
- 승인/거절 이벤트 (누가, 언제, 사유)
- 설정 변경 (가중치, 자동화 옵션)
- API 호출 (요청/응답, 에러)

**구현:** AuditLog 테이블 + structlog 구조화 로깅, 보존 12개월

---

## 7. 데이터베이스 모델

### 7.1 주요 테이블

```sql
-- 상품 마스터
CREATE TABLE products (
    id BIGSERIAL PRIMARY KEY,
    ali_product_id VARCHAR(100) UNIQUE NOT NULL,
    naver_product_id VARCHAR(100) UNIQUE,
    product_name_en TEXT,
    product_name_ko TEXT,
    category_ali VARCHAR(100),
    category_naver VARCHAR(100),
    price_ali DECIMAL(10, 2),
    price_naver DECIMAL(10, 2),
    margin_rate DECIMAL(5, 2),
    priority_score DECIMAL(5, 2),
    risk_score DECIMAL(5, 2),            -- v2 신규
    ops_cost_score DECIMAL(5, 2),        -- v2 신규
    demand_score DECIMAL(5, 2),          -- v2 신규 (판매량 대체)
    status VARCHAR(50),                   -- pending, approved, registered, hidden
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 가격 이력 (시계열)
CREATE TABLE price_history (
    id BIGSERIAL PRIMARY KEY,
    product_id BIGINT REFERENCES products(id),
    price_ali DECIMAL(10, 2),
    price_naver DECIMAL(10, 2),
    exchange_rate DECIMAL(8, 4),
    recorded_at TIMESTAMP DEFAULT NOW()
);

-- 주문
CREATE TABLE orders (
    id BIGSERIAL PRIMARY KEY,
    naver_order_id VARCHAR(100) UNIQUE NOT NULL,
    ali_order_id VARCHAR(100),
    product_id BIGINT REFERENCES products(id),
    quantity INT,
    total_price DECIMAL(10, 2),
    status VARCHAR(50),                   -- new, approved, processing, shipped, delivered, cancelled
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 트렌드 데이터
CREATE TABLE trend_data (
    id BIGSERIAL PRIMARY KEY,
    keyword VARCHAR(255),
    category VARCHAR(100),
    click_ratio DECIMAL(5, 2),            -- 데이터랩 상대값
    search_volume INT,                    -- 검색광고 API
    collected_at TIMESTAMP DEFAULT NOW()
);

-- 에이전트 로그
CREATE TABLE agent_logs (
    id BIGSERIAL PRIMARY KEY,
    agent_name VARCHAR(100),
    job_type VARCHAR(100),
    status VARCHAR(50),
    message TEXT,
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

-- 상품 성과 (피드백 루프용, v2 신규)
CREATE TABLE product_performance (
    id BIGSERIAL PRIMARY KEY,
    product_id BIGINT REFERENCES products(id),
    impressions INT,
    clicks INT,
    conversions INT,
    revenue DECIMAL(10, 2),
    recorded_at DATE,
    UNIQUE(product_id, recorded_at)
);
```

### 7.2 JobRun 테이블 (v2 신규, Idempotency)

```sql
CREATE TABLE job_runs (
    id BIGSERIAL PRIMARY KEY,
    idempotency_key VARCHAR(64) UNIQUE NOT NULL,  -- SHA256
    job_type VARCHAR(100) NOT NULL,
    status VARCHAR(50) NOT NULL,                   -- running, completed, failed
    input_params JSONB,
    output_result JSONB,
    error_message TEXT,
    retry_count INT DEFAULT 0,
    started_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP,
    CONSTRAINT chk_status CHECK (status IN ('running', 'completed', 'failed'))
);

CREATE INDEX idx_job_runs_type_status ON job_runs(job_type, status);
```

### 7.3 AuditLog 테이블 (v2 신규, 감사로그)

```sql
CREATE TABLE audit_logs (
    id BIGSERIAL PRIMARY KEY,
    actor VARCHAR(100) NOT NULL,           -- 'system', 'user:telegram_id', etc.
    action VARCHAR(100) NOT NULL,          -- register_product, approve, process_order
    entity_type VARCHAR(100),              -- product, order, setting
    entity_id VARCHAR(100),
    changes JSONB,                         -- {"before": {...}, "after": {...}}
    metadata JSONB,                        -- 추가 컨텍스트
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_audit_entity ON audit_logs(entity_type, entity_id);
CREATE INDEX idx_audit_created ON audit_logs(created_at);
```

---

## 8. 피드백 루프 및 재학습

### 8.1 피드백 사이클

```
[1단계: 발굴/분석]
  │  분석 에이전트 → 우선순위 스코어 계산
  ▼
[2단계: 승인]
  │  텔레그램/대시보드에서 승인 (또는 자동 승인)
  ▼
[3단계: 등록/운영]
  │  등록 에이전트 → 커머스 API 등록
  │  주문/CS 에이전트 → 주문 감시
  ▼
[4단계: 성과 추적]
  │  일 1회 쇼핑파트너센터에서 성과 수집
  │  product_performance 테이블에 저장
  ▼
[5단계: 재학습]
  │  월 1회 배치: 실제 성과 vs 예측 스코어 비교
  │  가중치 자동 조정 (Bayesian Optimization)
  ▼
[반복] → 1단계로
```

### 8.2 운영 전략: 점진적 확장

> **ChatGPT 비판 반영: "빅데이터"가 처음부터 필요한 게 아니라 운영하면서 쌓는다**

1. **탐색 (Discovery):** 소수 seed 키워드/카테고리로 시작 (10-20개)
2. **확장 (Expansion):** 성과 좋은 카테고리만 폭을 늘림
3. **학습 (Feedback):** 등록 후 성과를 DB에 누적 → 스코어 보정
4. **반복 루프:** "승인→등록→성과→재학습"이 자동 순환
5. **해자 형성:** 데이터가 쌓일수록 스코어링 정밀도 향상 → 경쟁 우위

### 8.3 재학습 알고리즘

```python
from skopt import gp_minimize

def objective(weights):
    w1, w2, w3, w4, w5 = weights
    predicted = calculate_scores(products, w1, w2, w3, w4, w5)
    actual = get_actual_revenue_rank(products)
    return mean_squared_error(predicted, actual)

# 월 1회 최적화
result = gp_minimize(objective, dimensions=[(0.0, 1.0)] * 5, n_calls=50)
update_weights(result.x)
```

---

## 9. 리스크 매트릭스

| 리스크 | 영향도 | 확률 | 대응 |
|--------|--------|------|------|
| 네이버 커머스 API 변경/중단 | 치명적 | 낮음 | GitHub Discussion 모니터링, API 버전 관리 |
| 알리 안티봇 강화 | 높음 | 중간 | 공식 API 우선, 서드파티 fallback |
| LLM 비용 급증 | 중간 | 낮음 | 모델 라우팅, 캐싱, 경량 모델 전환 |
| 환율 급변동 | 중간 | 중간 | 안전 마진 5%, 환율 알림, 자동 가격 조정 |
| 네이버 IP 제한 변경 | 높음 | 낮음 | 고정 IP VPS, IP 자동 갱신 스크립트 |
| 크롤링 법적 리스크 | 치명적 | 낮음 | 공식 API 최대 활용, 법률 자문 |
| 중복 실행 (Idempotency 실패) | 중간 | 중간 | JobRun UNIQUE 제약, 트랜잭션 격리 |
| 데이터 유출 | 치명적 | 낮음 | 환경변수 암호화, 정기 보안 감사 |
| OCR/비전 비용 폭탄 | 중간 | 중간 | 텍스트 우선, 고가치 상품만 선택적 |

---

## 10. 단계별 개발 계획

### Phase 0: 선행 작업 (1-2주)

> **ChatGPT 비판 반영: 코딩 전 인프라/API 등록을 별도 Phase로 분리**

**체크리스트:**
- [ ] 네이버 개발자 센터 애플리케이션 등록
- [ ] 네이버 커머스 API 승인 신청 (영업일 3-5일)
- [ ] 네이버 커머스 API 고정 IP 등록 (최대 3개)
- [ ] 알리익스프레스 Affiliate API 승인 (1-2일)
- [ ] Hetzner VPS 프로비저닝 + 고정 IP 확인
- [ ] Anthropic API 키 발급
- [ ] 텔레그램 봇 생성 (BotFather)
- [ ] PostgreSQL + Redis 설치 (Docker Compose)
- [ ] .env 환경변수 구성

**DoD (Definition of Done):**
- 모든 외부 API 키 발급 완료
- VPS SSH 접속 + 고정 IP 확인
- 네이버 커머스 API 테스트 호출 성공
- 알리 Affiliate API 테스트 호출 성공
- PostgreSQL, Redis 헬스체크 통과

---

### Phase 1: Foundation & Data Pipeline (4주)

**목표:** 데이터 수집 파이프라인 구축, 마진율 계산 엔진 프로토타입

**산출물:**
- 프로젝트 기본 구조 (pyproject.toml, src/dropagent/)
- 알리 Affiliate API 클라이언트
- 네이버 쇼핑 검색 API 클라이언트
- 네이버 데이터랩 API 클라이언트
- 환율 API 클라이언트
- PostgreSQL 스키마 + Alembic 마이그레이션
- Redis 캐시 레이어
- 마진율 계산 엔진 v1
- Streamlit 간이 대시보드
- 텔레그램 봇 기본 알림
- APScheduler 기본 설정

**DoD:**
- 알리 API로 상품 100개+ DB 저장
- 네이버 쇼핑 검색 API로 동종 상품 가격 조회 성공
- 마진율 계산 단위 테스트 통과
- Streamlit에서 상품 목록 조회 가능
- 텔레그램 테스트 메시지 성공
- Redis 캐시 히트율 50%+

**선행:** Phase 0 완료

---

### Phase 2: Intelligence & Content (4주)

**목표:** DemandScore 기반 스코어링 엔진, LLM 콘텐츠 생성 (텍스트 우선)

**산출물:**
- 우선순위 스코어링 v2 (MarginScore + DemandScore - RiskScore - OpsCostScore)
- DemandScore 모듈 (다층 프록시)
- RiskScore, OpsCostScore 룰 테이블
- LangGraph 분석 워크플로우
- LLM 콘텐츠 생성 (텍스트 우선): 번역, SEO, 카테고리 매칭
- 이미지 다운로드/최적화 (Pillow)
- 알리→네이버 카테고리 매칭 테이블
- 스코어링 대시보드 (Top 20 추천)

**DoD:**
- 1,000개+ 상품에 대해 스코어 계산 완료
- RiskScore/OpsCostScore 단위 테스트 통과
- LLM 콘텐츠 100개 상품 생성 성공
- 상품 1건당 LLM 비용 $0.05 이하
- 대시보드에서 추천 20개 조회 가능
- "마진 높지만 수요 낮은" 상품이 자동 후순위 (스코어 로그 확인)

**선행:** Phase 1 완료 + 1-2주 데이터 축적

---

### Phase 3: Store Integration & Automation (4주)

**목표:** 네이버 등록 자동화, 주문 감시, Idempotency/AuditLog

**산출물:**
- 네이버 커머스 API 상품 등록/수정/삭제
- Rate Limit 큐 (Token Bucket + Redis)
- 등록 실패 지수 백오프 재시도
- **JobRun 테이블 + Idempotency Key**
- **AuditLog 테이블 + 감사 로깅**
- 주문 감시 데몬 (5분 주기)
- 주문 상태 동기화 엔진
- 알리 반자동 주문 (nodriver, 결제 전 승인 필수)
- 배송 추적 번호 연동
- LangGraph 전체 워크플로우 통합
- 승인 워크플로우 (LangGraph Interrupt + 텔레그램)

**DoD:**
- 상품 10개+ 네이버 자동 등록 성공
- Rate Limit 준수 (429 에러 0건)
- Idempotency로 중복 등록 방지 확인
- 주문 감지 5분 이내 텔레그램 알림
- AuditLog에 모든 등록/주문 이력 기록
- 승인→등록 E2E 워크플로우 동작

**선행:** Phase 2 완료 + 실제 네이버 스토어

---

### Phase 4: Dashboard & Operations (3주)

**목표:** 프로덕션 대시보드, 운영 도구, 모니터링

**산출물:**
- FastAPI REST API 서버
- Reflex 관리 대시보드 (Streamlit 교체)
  - 상품 목록 (필터/정렬/검색)
  - 마진율/스코어 차트
  - 주문 실시간 모니터링
  - 에이전트 로그/AuditLog 조회
  - 설정 관리 (가중치, 자동화 ON/OFF)
- 텔레그램 봇 고도화: /status, /top10, /approve [id]
- 자동 리포트 (일일, 주간)
- structlog 로깅 체계

**DoD:**
- Reflex 대시보드 3초 이내 로드
- FastAPI API 200ms 이내 응답
- 텔레그램 명령어 전체 동작
- 일일 리포트 자동 발송
- 시스템 메트릭 시각화

**선행:** Phase 3 완료

---

### Phase 5: Optimization & Scale (지속적)

**목표:** 성능 최적화, 비용 절감, 피드백 루프, 확장

**산출물:**
- LLM 호출 캐싱 (의미적 유사도 기반)
- 카테고리 매칭 경량 ML 모델 (scikit-learn)
- 가격 변동 감지/자동 조정
- **피드백 루프 자동화** (성과 추적 → 가중치 재학습)
- A/B 테스트 프레임워크
- 다중 스토어 지원
- 판매량 예측 모델 (자사 데이터 기반)
- DB 마이그레이션 → PostgreSQL + TimescaleDB
- Docker Compose 배포
- CI/CD (GitHub Actions)

**DoD:**
- LLM 호출 50% 감소
- 상품 1건당 LLM 비용 $0.03 이하
- 피드백 루프 월 1회 자동 실행
- 다중 스토어 2개+ 동시 운영
- CI/CD 자동화 완료

---

## 11. 최종 기술스택

| 영역 | Gemini 제안 | 최종 권장 | 이유 |
|------|------------|----------|------|
| 에이전트 | CrewAI 또는 LangGraph | **LangGraph + MCP** | 상태 관리, Interrupt, 안정성 |
| LLM | Claude 3.5 Sonnet | **Sonnet 4 + Haiku 3.5 라우팅** | 태스크별 비용 최적화 |
| DB | Supabase 또는 PostgreSQL | **Supabase → PG+TimescaleDB** | 단계적 진화 |
| 캐시 | (없음) | **Redis** | 캐싱, Rate Limit, 큐 |
| 브라우저 | Playwright | **nodriver + 공식 API 우선** | 안티봇 우회 |
| 메시징 | Slack/Discord | **텔레그램 Bot API** | 한국 셀러 생태계 |
| 대시보드 | Streamlit/Retool | **Streamlit → Reflex** | 점진적 고도화 |
| API 서버 | (없음) | **FastAPI** | 비동기, Pydantic |
| 인프라 | Docker + AWS EC2 | **Docker + Hetzner VPS** | 비용, 고정 IP |
| 스케줄러 | Cron Job | **APScheduler + Redis** | Python 통합, 재시도 |
| HTTP | (미지정) | **httpx (async)** | 비동기 병렬화 |
| ORM | (미지정) | **SQLAlchemy 2.0 + Alembic** | 비동기, 마이그레이션 |
| 로깅 | (미지정) | **structlog** | 구조화 로깅 |
| 패키지 | (미지정) | **uv** | 빠른 의존성 해결 |
| 테스트 | (미지정) | **pytest + pytest-asyncio** | 비동기 테스트 |

---

## 12. 아키텍처 다이어그램

```
                         ┌───────────────────┐
                         │   텔레그램 Bot     │
                         │  (알림/승인/명령)  │
                         └────────┬──────────┘
                                  │
┌──────────────────┐     ┌────────▼──────────┐     ┌──────────────────┐
│   Reflex         │     │   FastAPI         │     │   APScheduler    │
│   Dashboard      │◄───►│   REST API        │◄───►│   Job Runner     │
│   (Phase 4)      │     │   서버            │     │                  │
└──────────────────┘     └────────┬──────────┘     └────────┬─────────┘
                                  │                          │
                         ┌────────▼──────────────────────────▼─────────┐
                         │           LangGraph Orchestrator             │
                         │          (Interrupt 기반 승인 포함)          │
                         │                                              │
                         │  ┌──────────┐  ┌──────────┐  ┌──────────┐  │
                         │  │ 수집     │  │ 분석     │  │ 콘텐츠   │  │
                         │  │ 에이전트 │  │ 에이전트 │  │ 에이전트 │  │
                         │  └────┬─────┘  └────┬─────┘  └────┬─────┘  │
                         │       │             │             │         │
                         │  ┌────┴─────┐  ┌────┴─────┐  ┌──────────┐ │
                         │  │ 등록     │  │ 주문/CS  │  │ 모니터링 │ │
                         │  │ 에이전트 │  │ 에이전트 │  │ 에이전트 │ │
                         │  └──────────┘  └──────────┘  └──────────┘ │
                         └─────┬────────────────┬──────────────────────┘
                               │                │
              ┌────────────────▼──┐       ┌─────▼──────────────┐
              │  외부 API 클라이언트│       │  DB / 캐시 레이어   │
              │                    │       │                    │
              │ • 알리 Affiliate   │       │ • PostgreSQL       │
              │ • 네이버 커머스    │       │   - products       │
              │ • 네이버 쇼핑검색  │       │   - job_runs       │
              │ • 네이버 데이터랩  │       │   - audit_logs     │
              │ • 환율 API         │       │   - performance    │
              │ • nodriver (보조)  │       │ • Redis            │
              └────────────────────┘       │ • (TimescaleDB)    │
                                           └────────────────────┘
                         ┌────────────────────┐
                         │  피드백 루프        │
                         │  승인 → 등록 →     │
                         │  성과 → 재학습 →   │
                         │  스코어 갱신        │
                         └────────────────────┘
```

---

## 13. 프로젝트 디렉토리 구조

```
dropagent/
├── pyproject.toml
├── .env.example
├── .gitignore
├── docker-compose.yml
├── Dockerfile
├── alembic.ini
│
├── src/
│   └── dropagent/
│       ├── __init__.py
│       ├── config.py                     # pydantic-settings
│       ├── main.py
│       │
│       ├── api/                          # FastAPI (Phase 4)
│       │   ├── routes/
│       │   │   ├── products.py
│       │   │   ├── orders.py
│       │   │   ├── analytics.py
│       │   │   └── settings.py
│       │   ├── deps.py
│       │   └── middleware.py
│       │
│       ├── agents/                       # LangGraph 에이전트
│       │   ├── orchestrator.py           # 메인 오케스트레이터 (Interrupt 포함)
│       │   ├── collector.py
│       │   ├── analyzer.py
│       │   ├── content.py
│       │   ├── registrar.py
│       │   ├── order_manager.py
│       │   ├── monitor.py
│       │   ├── states.py
│       │   └── tools/                    # MCP 도구 래퍼
│       │       ├── ali_tools.py
│       │       ├── naver_tools.py
│       │       └── analysis_tools.py
│       │
│       ├── clients/                      # 외부 API
│       │   ├── aliexpress/
│       │   │   ├── affiliate_api.py
│       │   │   ├── scraper.py            # nodriver
│       │   │   └── models.py
│       │   ├── naver/
│       │   │   ├── commerce_api.py
│       │   │   ├── shopping_api.py
│       │   │   ├── datalab_api.py
│       │   │   ├── auth.py
│       │   │   └── models.py
│       │   ├── llm/
│       │   │   ├── router.py             # 태스크별 모델 라우팅
│       │   │   ├── prompts.py
│       │   │   └── cache.py
│       │   ├── exchange_rate.py
│       │   └── telegram_bot.py
│       │
│       ├── core/                         # 핵심 비즈니스 로직
│       │   ├── margin_calculator.py
│       │   ├── priority_scorer.py        # v2: 감점 포함 스코어링
│       │   ├── demand_estimator.py       # DemandScore (판매량 대체)
│       │   ├── risk_scorer.py            # v2 신규: RiskScore
│       │   ├── ops_cost_scorer.py        # v2 신규: OpsCostScore
│       │   ├── category_mapper.py
│       │   ├── content_generator.py
│       │   ├── rate_limiter.py
│       │   ├── idempotency.py            # v2 신규: 중복실행방지
│       │   └── image_processor.py
│       │
│       ├── db/
│       │   ├── session.py
│       │   ├── models/
│       │   │   ├── product.py
│       │   │   ├── order.py
│       │   │   ├── price_history.py
│       │   │   ├── trend_data.py
│       │   │   ├── agent_log.py
│       │   │   ├── job_run.py            # v2 신규
│       │   │   ├── audit_log.py          # v2 신규
│       │   │   └── product_performance.py # v2 신규
│       │   ├── repositories/
│       │   │   ├── product_repo.py
│       │   │   ├── order_repo.py
│       │   │   ├── analytics_repo.py
│       │   │   ├── job_run_repo.py       # v2 신규
│       │   │   └── audit_log_repo.py     # v2 신규
│       │   └── migrations/
│       │       └── versions/
│       │
│       ├── scheduler/
│       │   ├── jobs.py
│       │   └── runner.py
│       │
│       ├── dashboard/
│       │   ├── app.py
│       │   ├── pages/
│       │   └── components/
│       │
│       ├── feedback/                     # v2 신규: 피드백 루프
│       │   ├── performance_tracker.py
│       │   ├── model_retrainer.py
│       │   └── ab_tester.py
│       │
│       └── utils/
│           ├── logging.py
│           ├── exceptions.py
│           ├── currency.py
│           └── validators.py
│
├── tests/
│   ├── conftest.py
│   ├── unit/
│   │   ├── test_margin_calculator.py
│   │   ├── test_priority_scorer.py
│   │   ├── test_risk_scorer.py           # v2 신규
│   │   ├── test_ops_cost_scorer.py       # v2 신규
│   │   ├── test_idempotency.py           # v2 신규
│   │   └── test_category_mapper.py
│   ├── integration/
│   │   ├── test_ali_api.py
│   │   ├── test_naver_api.py
│   │   └── test_agent_workflow.py
│   └── fixtures/
│       ├── ali_products.json
│       └── naver_search_results.json
│
├── scripts/
│   ├── setup_env.sh
│   ├── seed_categories.py
│   ├── migrate_db.py
│   └── retrain_model.py                  # v2 신규: 재학습
│
└── docs/
    ├── PRD.md                             # 이 문서
    ├── architecture.md
    ├── api_reference.md
    ├── deployment.md
    └── phase_0_checklist.md               # v2 신규
```

---

## 14. 부록

### 14.1 v2 변경 요약 (ChatGPT 비판 통합)

| # | 개선점 | 반영 위치 |
|---|--------|----------|
| 1 | Phase 0 (선행작업) 추가 | §10 Phase 0 |
| 2 | Non-Goals 명시 | §4.3 |
| 3 | RiskScore + OpsCostScore 감점 | §2.4, §5 FR-003, §7 products 테이블 |
| 4 | Idempotency (NFR-008) | §6, §7.2 job_runs 테이블 |
| 5 | Audit Log (NFR-009) | §6, §7.3 audit_logs 테이블 |
| 6 | 텍스트 우선 콘텐츠 전략 | §4.3 Non-Goal #5, §5 FR-004 |
| 7 | 피드백 루프 | §8, §5 FR-009 |
| 8 | JobRun DB 모델 | §7.2 |
| 9 | Phase별 DoD | §10 각 Phase |
| 10 | "판매량" → DemandScore 재정의 | §2.3, §4.3 Non-Goal #1 |

### 14.2 용어 정리

| 용어 | 설명 |
|------|------|
| DemandScore | "판매량" 대체 지표. 클릭 추이/검색량/리뷰 증가율 등 다층 프록시 합산 |
| RiskScore | 배송기간, 파손, 통관 등 리스크 감점 (0~1) |
| OpsCostScore | 상세페이지 난이도, CS 예상량 등 운영 비용 감점 (0~1) |
| Idempotency Key | SHA256 해시 기반 중복 실행 방지 고유 식별자 |
| Audit Log | 모든 중요 작업의 실행 이력 (누가, 언제, 무엇을, 어떻게) |
| HITL | Human-in-the-Loop. 사람 승인이 포함된 워크플로우 |
| 피드백 루프 | 실제 성과 → 모델 재학습 → 스코어 갱신 자동 순환 |

### 14.3 참고 자료

- [네이버 커머스 API GitHub FAQ](https://github.com/commerce-api-naver/commerce-api/discussions/1)
- [네이버 데이터랩 쇼핑인사이트](https://datalab.naver.com/)
- [알리익스프레스 Affiliate API](https://portals.aliexpress.com/help/affiliate/api)
- [LangGraph 공식 문서](https://langchain-ai.github.io/langgraph/)
- [Anthropic Claude API](https://docs.anthropic.com/claude/reference)
- [MCP (Model Context Protocol)](https://modelcontextprotocol.io/)
