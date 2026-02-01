# DropAgent 셋업 가이드

> 알리익스프레스 → 네이버 스마트스토어 드롭쉬핑 자동화 시스템

---

## 목차

1. [선행 조건](#1-선행-조건)
2. [Phase 0: API 등록 (가장 중요)](#2-phase-0-api-등록)
3. [인프라 설치 (PostgreSQL, Redis)](#3-인프라-설치)
4. [프로젝트 설치](#4-프로젝트-설치)
5. [환경변수 설정 (.env)](#5-환경변수-설정)
6. [데이터베이스 마이그레이션](#6-데이터베이스-마이그레이션)
7. [실행](#7-실행)
8. [테스트](#8-테스트)
9. [Docker 배포 (프로덕션)](#9-docker-배포)
10. [트러블슈팅](#10-트러블슈팅)

---

## 1. 선행 조건

### 필수 소프트웨어

| 소프트웨어 | 최소 버전 | 확인 명령어 |
|-----------|----------|------------|
| Python | 3.11+ | `python --version` |
| PostgreSQL | 15+ | `psql --version` |
| Redis | 7+ | `redis-cli --version` |
| Git | 2.30+ | `git --version` |

### 필수 계정 및 자격증명

**이것이 가장 중요합니다.** 코드를 실행하기 전에 반드시 아래 API 등록을 모두 완료해야 합니다.

| 서비스 | 필요 여부 | 발급 소요 시간 | 비용 |
|-------|----------|---------------|------|
| 네이버 커머스 API | **필수** | 1~3 영업일 (심사) | 무료 |
| 네이버 검색/데이터랩 API | **필수** | 즉시 | 무료 |
| AliExpress Affiliate API | **필수** | 1~5 영업일 (심사) | 무료 |
| Anthropic API (Claude) | **필수** | 즉시 | 종량제 |
| Telegram Bot | **필수** | 즉시 | 무료 |
| 환율 API | 권장 | 즉시 | 무료 (기본) |

---

## 2. Phase 0: API 등록

> **경고:** 이 단계를 건너뛰면 시스템이 동작하지 않습니다.
> API 등록은 최소 **1주일 전**에 시작하세요. 특히 네이버 커머스 API는 사업자등록증이 필요합니다.

### 2.1 네이버 커머스 API (스마트스토어)

**이것이 가장 까다롭고 시간이 오래 걸립니다.**

#### 사전 요구사항
- **사업자등록증** (개인/법인 모두 가능)
- **네이버 스마트스토어** 개설 완료
- **고정 IP 주소** (최대 3개까지 등록 가능)

#### 등록 절차

1. [네이버 커머스 API 센터](https://apicenter.commerce.naver.com) 접속
2. 네이버 스마트스토어 판매자 계정으로 로그인
3. **애플리케이션 등록**
   - 애플리케이션 이름: `dropagent` (자유)
   - API 권한 선택:
     - `상품 관리` (상품 등록/수정/삭제)
     - `주문 관리` (주문 조회/발주)
     - `채널 상품 관리`
   - **고정 IP 등록** (필수 - 등록하지 않으면 API 호출 차단)
4. 승인 대기 (1~3 영업일)
5. 승인 후 `Client ID`와 `Client Secret` 발급

```
# .env에 넣을 값
NAVER_COMMERCE_CLIENT_ID=발급받은_client_id
NAVER_COMMERCE_CLIENT_SECRET=발급받은_client_secret
```

#### 고정 IP 확인 방법

로컬 개발 시:
```bash
curl -s https://api.ipify.org
```

VPS 사용 시 (Hetzner 등):
```bash
# VPS의 공인 IP 사용
ip addr show eth0
```

#### Rate Limit 주의
- **초당 2회** (100ms 간격)
- 시스템의 `TokenBucketRateLimiter`가 자동으로 조절하지만, 초과 시 24시간 차단될 수 있음

### 2.2 네이버 검색 API + 데이터랩 API

1. [네이버 개발자 센터](https://developers.naver.com) 접속
2. 네이버 계정으로 로그인
3. **Application 등록** → "검색", "데이터랩" 선택
4. 즉시 발급됨

```
# .env에 넣을 값
NAVER_CLIENT_ID=발급받은_client_id
NAVER_CLIENT_SECRET=발급받은_client_secret
```

#### 일일 호출 한도
- 네이버 쇼핑 검색 API: **25,000회/일**
- 데이터랩 쇼핑인사이트 API: **1,000회/일**

### 2.3 AliExpress Affiliate API

1. [AliExpress Portals](https://portals.aliexpress.com) 접속
2. AliExpress 계정으로 가입/로그인
3. **Affiliate 프로그램** 가입 (승인 필요, 1~5 영업일)
4. 승인 후 **App Key** 발급:
   - Settings → API Settings → Create New App
   - API 권한: `affiliate/product/query`, `affiliate/product/detail`
   - Tracking ID 자동 생성

```
# .env에 넣을 값
ALI_APP_KEY=발급받은_app_key
ALI_APP_SECRET=발급받은_app_secret
ALI_TRACKING_ID=발급받은_tracking_id
```

#### API 호출 한도
- **일 5,000건** (상품 조회)
- HMAC-SHA256 서명 필요 (시스템에서 자동 처리)

### 2.4 Anthropic API (Claude)

1. [Anthropic Console](https://console.anthropic.com) 접속
2. 계정 생성 및 결제 수단 등록
3. API Keys → Create Key

```
# .env에 넣을 값
ANTHROPIC_API_KEY=sk-ant-api03-xxxxx
```

#### 예상 비용 (월간)
| 모델 | 용도 | 예상 호출 | 월 비용 |
|------|------|----------|--------|
| Claude Sonnet 4 | 상품설명 생성, 번역 | ~500건/일 | $15-30 |
| Claude Haiku 3.5 | 카테고리 매칭, 키워드 | ~2,000건/일 | $3-8 |
| **합계** | | | **$18-38** |

> LLM 캐시가 활성화되어 있어 동일 요청 반복 시 API 호출 없이 캐시에서 응답합니다.

### 2.5 Telegram Bot

1. Telegram에서 [@BotFather](https://t.me/BotFather)에게 메시지
2. `/newbot` 명령어 입력
3. 봇 이름, username 설정
4. **Bot Token** 발급됨

Chat ID 확인:
```bash
# 봇에게 아무 메시지를 보낸 후:
curl "https://api.telegram.org/bot{YOUR_BOT_TOKEN}/getUpdates"
# 응답에서 "chat":{"id": 123456789} 확인
```

```
# .env에 넣을 값
TELEGRAM_BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
TELEGRAM_CHAT_ID=123456789
```

### 2.6 환율 API

[ExchangeRate-API](https://www.exchangerate-api.com/) (무료 플랜: 1,500회/월):

1. 가입 → API Key 즉시 발급

```
# .env에 넣을 값
EXCHANGE_RATE_API_KEY=발급받은_key
```

> 시스템은 1시간마다 환율을 캐싱하므로 무료 플랜으로 충분합니다.

---

## 3. 인프라 설치

### Option A: 로컬 직접 설치

#### PostgreSQL

```bash
# Ubuntu/Debian
sudo apt update
sudo apt install postgresql postgresql-contrib

# macOS (Homebrew)
brew install postgresql@15
brew services start postgresql@15

# DB 생성
sudo -u postgres psql -c "CREATE USER dropagent WITH PASSWORD 'your_secure_password';"
sudo -u postgres psql -c "CREATE DATABASE dropagent OWNER dropagent;"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE dropagent TO dropagent;"
```

#### Redis

```bash
# Ubuntu/Debian
sudo apt install redis-server
sudo systemctl enable redis-server
sudo systemctl start redis-server

# macOS (Homebrew)
brew install redis
brew services start redis

# 확인
redis-cli ping  # PONG 이 출력되면 정상
```

### Option B: Docker Compose (권장)

프로젝트 루트에 `docker-compose.yml` 생성:

```yaml
version: "3.9"

services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: dropagent
      POSTGRES_PASSWORD: your_secure_password
      POSTGRES_DB: dropagent
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U dropagent"]
      interval: 10s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redisdata:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

volumes:
  pgdata:
  redisdata:
```

```bash
docker compose up -d
```

---

## 4. 프로젝트 설치

```bash
# 1. 리포지토리 클론
git clone https://github.com/YechanAhn/Dropshipping-e2e-agent-system.git
cd Dropshipping-e2e-agent-system

# 2. Python 가상환경 생성 (uv 권장)
# uv 사용 시:
pip install uv
uv venv --python 3.11
source .venv/bin/activate

# 또는 venv 사용 시:
python -m venv .venv
source .venv/bin/activate

# 3. 의존성 설치
pip install -e ".[dev]"

# 4. 설치 확인
python -c "import dropagent; print(f'DropAgent v{dropagent.__version__}')"
# 출력: DropAgent v0.1.0
```

---

## 5. 환경변수 설정

```bash
# .env.example을 복사하여 .env 생성
cp .env.example .env
```

`.env` 파일을 편집하여 **실제 값**으로 교체:

```bash
# ============================================
# DropAgent Environment Variables
# ============================================

# --- Anthropic (Claude) ---
ANTHROPIC_API_KEY=sk-ant-api03-실제키를넣으세요

# --- 네이버 검색/데이터랩 API ---
NAVER_CLIENT_ID=실제_client_id
NAVER_CLIENT_SECRET=실제_client_secret

# --- 네이버 커머스 API (스마트스토어) ---
NAVER_COMMERCE_CLIENT_ID=실제_commerce_client_id
NAVER_COMMERCE_CLIENT_SECRET=실제_commerce_client_secret

# --- AliExpress Affiliate API ---
ALI_APP_KEY=실제_app_key
ALI_APP_SECRET=실제_app_secret
ALI_TRACKING_ID=실제_tracking_id

# --- Database ---
DATABASE_URL=postgresql+asyncpg://dropagent:your_secure_password@localhost:5432/dropagent

# --- Redis ---
REDIS_URL=redis://localhost:6379/0

# --- Telegram ---
TELEGRAM_BOT_TOKEN=실제_bot_token
TELEGRAM_CHAT_ID=실제_chat_id

# --- Exchange Rate ---
EXCHANGE_RATE_API_KEY=실제_key

# --- System ---
LOG_LEVEL=INFO
ENVIRONMENT=development
```

### 설정 검증

```bash
python -c "
from dropagent.config import get_settings
s = get_settings()
print(f'Environment: {s.app.environment}')
print(f'DB URL: {str(s.database.url)[:40]}...')
print(f'Anthropic key: {s.anthropic.api_key[:12]}...')
print(f'Naver Client ID: {s.naver.client_id[:8]}...')
print(f'Ali App Key: {s.aliexpress.app_key[:8]}...')
print(f'Telegram Chat: {s.telegram.chat_id}')
print('All settings loaded successfully')
"
```

> 에러가 나면 `.env` 파일에서 빠진 값이 없는지 확인하세요.

---

## 6. 데이터베이스 마이그레이션

### Alembic 초기 설정 (최초 1회)

```bash
# alembic 초기화 (이미 alembic.ini가 있으면 스킵)
alembic init src/dropagent/db/migrations

# alembic.ini 수정 - sqlalchemy.url 을 .env의 DATABASE_URL과 맞춤
# 또는 env.py에서 config에서 읽도록 설정
```

### 마이그레이션 생성 및 실행

```bash
# 현재 모델 기반으로 마이그레이션 파일 자동 생성
alembic revision --autogenerate -m "initial_schema"

# 마이그레이션 실행 (테이블 생성)
alembic upgrade head
```

### 수동 테이블 생성 (Alembic 없이 빠르게 시작하기)

```bash
python -c "
import asyncio
from dropagent.db.session import init_db
asyncio.run(init_db())
print('Tables created successfully')
"
```

> `init_db()`는 `Base.metadata.create_all()`을 실행하여 모든 테이블을 생성합니다.

### 생성되는 테이블 (9개)

| 테이블 | 용도 |
|-------|------|
| `products` | 상품 정보 (알리/네이버 통합) |
| `orders` | 주문 내역 |
| `price_history` | 가격 변동 이력 |
| `trend_data` | 네이버 검색 트렌드 |
| `agent_logs` | 에이전트 실행 로그 |
| `job_runs` | 스케줄러 작업 멱등성 추적 |
| `audit_logs` | 변경 감사 로그 |
| `product_performance` | 상품 성과 지표 (일별) |

---

## 7. 실행

### 메인 애플리케이션 (스케줄러 + 전체 시스템)

```bash
python -m dropagent.main
```

출력 예시:
```
{"event":"application_starting","environment":"development","log_level":"INFO"}
{"event":"database_initializing"}
{"event":"database_initialized"}
{"event":"scheduler_starting"}
{"event":"scheduler_started","jobs":8}
{"event":"application_ready"}
```

정상 구동되면 **APScheduler가 8개 작업을 자동 실행**합니다:

| 작업 | 실행 주기 |
|------|----------|
| `collect_ali_products_job` | 6시간마다 |
| `collect_naver_trends_job` | 12시간마다 |
| `update_scores_job` | 6시간마다 |
| `auto_register_products_job` | 1시간마다 |
| `check_orders_job` | 5분마다 |
| `monitor_price_changes_job` | 3시간마다 |
| `health_check_job` | 1분마다 |
| `daily_report_job` | 매일 오전 9시 (KST) |

### 종료

```bash
# Ctrl+C 또는
kill -SIGTERM <PID>
```

> SIGINT/SIGTERM 수신 시 스케줄러 정지 → DB 연결 해제 순으로 정상 종료됩니다.

---

## 8. 테스트

### 유닛 테스트 (외부 의존성 불필요)

```bash
# 전체 유닛 테스트 실행
python -m pytest tests/unit/ -v

# 특정 모듈만 테스트
python -m pytest tests/unit/test_margin_calculator.py -v
python -m pytest tests/unit/test_priority_scorer.py -v

# 커버리지 측정
python -m pytest tests/unit/ --cov=dropagent.core --cov-report=term-missing
```

현재 유닛 테스트 현황:

| 테스트 파일 | 테스트 수 | 대상 모듈 |
|------------|----------|----------|
| `test_margin_calculator.py` | 30 | 마진율 계산기 |
| `test_priority_scorer.py` | 30 | 우선순위 스코어러 |
| `test_risk_scorer.py` | 33 | 리스크 스코어러 |
| `test_ops_cost_scorer.py` | 30 | 운영비용 스코어러 |
| `test_demand_estimator.py` | 33 | 수요 추정기 |
| `test_category_mapper.py` | 31 | 카테고리 매퍼 |
| `test_idempotency.py` | 15 | 멱등성 관리자 |
| `test_rate_limiter.py` | 17 | Rate Limiter |
| `conftest.py` | - | 공유 fixture |
| **합계** | **249** | |

### 린트 검사

```bash
python -m ruff check src/dropagent/
```

---

## 9. Docker 배포 (프로덕션)

### Dockerfile

프로젝트 루트에 `Dockerfile` 생성:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# 시스템 의존성
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Python 의존성
COPY pyproject.toml ./
RUN pip install --no-cache-dir .

# 소스 코드
COPY src/ src/

# 비root 사용자
RUN useradd -m appuser
USER appuser

CMD ["python", "-m", "dropagent.main"]
```

### 전체 docker-compose.yml (프로덕션)

```yaml
version: "3.9"

services:
  app:
    build: .
    env_file: .env
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    restart: unless-stopped
    networks:
      - dropagent

  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: dropagent
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-changeme}
      POSTGRES_DB: dropagent
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U dropagent"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped
    networks:
      - dropagent

  redis:
    image: redis:7-alpine
    command: redis-server --appendonly yes
    volumes:
      - redisdata:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped
    networks:
      - dropagent

volumes:
  pgdata:
  redisdata:

networks:
  dropagent:
    driver: bridge
```

```bash
# 프로덕션 실행
docker compose up -d --build

# 로그 확인
docker compose logs -f app

# 중지
docker compose down
```

### Hetzner VPS 배포 (권장)

```bash
# 1. Hetzner Cloud에서 CX21 (2vCPU, 4GB RAM) 생성 - ~$7/월
#    고정 IP 자동 할당됨

# 2. SSH 접속
ssh root@YOUR_VPS_IP

# 3. Docker 설치
curl -fsSL https://get.docker.com | sh

# 4. 프로젝트 클론 + .env 설정
git clone https://github.com/YechanAhn/Dropshipping-e2e-agent-system.git
cd Dropshipping-e2e-agent-system
cp .env.example .env
nano .env  # 실제 값 입력

# 5. 실행
docker compose up -d --build

# 6. 네이버 커머스 API에 이 VPS의 고정 IP 등록
echo "네이버 커머스 API 센터에서 $(curl -s https://api.ipify.org) 등록하세요"
```

---

## 10. 트러블슈팅

### ".env 로딩 실패" / ValidationError

```
pydantic_core._pydantic_core.ValidationError: 1 validation error for AnthropicSettings
```

**원인:** `.env` 파일에 필수 값이 빠져 있음.
**해결:** `.env.example`과 비교하여 모든 키가 있는지 확인.

### "connection refused" (PostgreSQL)

```
asyncpg.exceptions.ConnectionRefusedError
```

**해결:**
```bash
# PostgreSQL이 실행 중인지 확인
sudo systemctl status postgresql
# 또는
docker compose ps postgres

# DATABASE_URL이 올바른지 확인
# 형식: postgresql+asyncpg://USER:PASSWORD@HOST:PORT/DBNAME
```

### "connection refused" (Redis)

```bash
# Redis 실행 확인
redis-cli ping  # PONG이면 정상

# Docker 사용 시
docker compose ps redis
```

### 네이버 커머스 API "403 Forbidden"

**원인:** 고정 IP가 등록되지 않았거나, 등록된 IP와 현재 IP가 다름.
**해결:**
```bash
# 현재 공인 IP 확인
curl -s https://api.ipify.org

# 네이버 커머스 API 센터에서 이 IP가 등록되어 있는지 확인
# https://apicenter.commerce.naver.com → 애플리케이션 관리 → IP 설정
```

### 네이버 커머스 API Rate Limit 초과

```
{"errorCode":"024","message":"Rate limit exceeded"}
```

**원인:** 초당 2회 제한 초과.
**해결:** 시스템이 자동 조절하지만, 수동 호출 시 100ms 이상 간격을 두세요. 초과 시 **최대 24시간 차단**될 수 있습니다.

### AliExpress API "Invalid Sign"

**원인:** App Secret이 잘못되었거나, 시스템 시간이 맞지 않음.
**해결:**
```bash
# 시스템 시간 확인 (UTC 기준)
date -u

# NTP 동기화
sudo timedatectl set-ntp true
```

### Telegram 봇 메시지 미수신

```bash
# Bot Token이 유효한지 확인
curl "https://api.telegram.org/bot{TOKEN}/getMe"

# Chat ID가 올바른지 확인
curl "https://api.telegram.org/bot{TOKEN}/getUpdates"
# 봇에게 먼저 메시지를 보내야 chat ID가 나옵니다
```

### 메모리 부족 (Health Check 경고)

```
{"event":"health_check_high_memory","memory_mb":600}
```

**해결:** VPS RAM 업그레이드 또는 `BATCH_SIZE` 환경변수를 줄여 한 번에 처리하는 상품 수를 감소.

---

## 부록: 전체 환경변수 레퍼런스

| 변수 | 필수 | 기본값 | 설명 |
|------|------|-------|------|
| `ANTHROPIC_API_KEY` | Y | - | Claude API 키 |
| `NAVER_CLIENT_ID` | Y | - | 네이버 검색 API Client ID |
| `NAVER_CLIENT_SECRET` | Y | - | 네이버 검색 API Client Secret |
| `NAVER_COMMERCE_CLIENT_ID` | Y | - | 네이버 커머스 API Client ID |
| `NAVER_COMMERCE_CLIENT_SECRET` | Y | - | 네이버 커머스 API Client Secret |
| `ALI_APP_KEY` | Y | - | AliExpress App Key |
| `ALI_APP_SECRET` | Y | - | AliExpress App Secret |
| `ALI_TRACKING_ID` | Y | - | AliExpress Tracking ID |
| `DATABASE_URL` | Y | - | PostgreSQL 연결 URL |
| `REDIS_URL` | Y | - | Redis 연결 URL |
| `TELEGRAM_BOT_TOKEN` | Y | - | Telegram Bot Token |
| `TELEGRAM_CHAT_ID` | Y | - | Telegram Chat ID |
| `EXCHANGE_RATE_API_KEY` | Y | - | 환율 API 키 |
| `LOG_LEVEL` | N | `INFO` | 로그 레벨 (DEBUG/INFO/WARNING/ERROR) |
| `ENVIRONMENT` | N | `development` | 환경 (development/staging/production) |
| `DEBUG` | N | `false` | 디버그 모드 |
| `DATABASE_ECHO` | N | `false` | SQL 쿼리 로깅 |
| `DATABASE_POOL_SIZE` | N | `5` | DB 커넥션 풀 크기 |
| `BATCH_SIZE` | N | `10` | 작업당 처리 상품 수 |
| `MAX_RETRIES` | N | `3` | 실패 시 최대 재시도 횟수 |

---

## 부록: API 등록 체크리스트

Phase 0을 체계적으로 진행하기 위한 체크리스트:

- [ ] 사업자등록증 준비
- [ ] 네이버 스마트스토어 개설
- [ ] 네이버 커머스 API 애플리케이션 등록 + 고정 IP 등록
- [ ] 네이버 개발자센터 애플리케이션 등록 (검색 + 데이터랩)
- [ ] AliExpress Affiliate 프로그램 가입 + App 생성
- [ ] Anthropic API 키 발급 + 결제 수단 등록
- [ ] Telegram Bot 생성 + Chat ID 확인
- [ ] ExchangeRate-API 키 발급
- [ ] VPS 준비 (Hetzner 권장) + 고정 IP 확인
- [ ] PostgreSQL + Redis 설치/구동 확인
- [ ] `.env` 파일 작성 완료
- [ ] `python -c "from dropagent.config import get_settings; get_settings()"` 성공
- [ ] DB 마이그레이션 완료
- [ ] `python -m pytest tests/unit/` 전체 통과
- [ ] `python -m dropagent.main` 정상 구동 확인
