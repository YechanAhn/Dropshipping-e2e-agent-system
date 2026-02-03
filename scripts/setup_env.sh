#!/usr/bin/env bash
set -euo pipefail

# ============================================
# DropAgent 환경 셋업 스크립트
#
# 사용법:
#   chmod +x scripts/setup_env.sh
#   ./scripts/setup_env.sh
#
# 수행 작업:
#   1. Python 가상환경 생성 (없으면)
#   2. 의존성 설치
#   3. .env 파일 생성 (없으면)
#   4. PostgreSQL DB/유저 생성
#   5. DB 마이그레이션 실행
#   6. 유닛 테스트 실행
# ============================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# -------------------------------------------
# 1. Python virtual environment
# -------------------------------------------
info "=== Step 1: Python 가상환경 ==="

if [ ! -d ".venv" ]; then
    info "가상환경 생성 중..."
    python3 -m venv .venv
    info "가상환경 생성 완료: .venv/"
else
    info "가상환경 이미 존재: .venv/"
fi

source .venv/bin/activate
info "Python: $(python --version)"

# -------------------------------------------
# 2. Dependencies
# -------------------------------------------
info "=== Step 2: 의존성 설치 ==="
pip install -q --upgrade pip
pip install -q -e ".[dev]"
info "의존성 설치 완료"

# -------------------------------------------
# 3. .env file
# -------------------------------------------
info "=== Step 3: .env 파일 ==="

if [ ! -f ".env" ]; then
    cp .env.example .env
    warn ".env 파일이 생성되었습니다. 실제 API 키를 입력해주세요:"
    warn "  nano .env"
else
    info ".env 파일 이미 존재"
fi

# -------------------------------------------
# 4. PostgreSQL setup
# -------------------------------------------
info "=== Step 4: PostgreSQL 셋업 ==="

DB_USER="dropagent"
DB_PASS="dropagent_dev_2024"
DB_NAME="dropagent"

# Check if PostgreSQL is running
if pg_isready -q 2>/dev/null; then
    info "PostgreSQL 실행 중"

    # Create user if not exists
    if sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'" 2>/dev/null | grep -q 1; then
        info "유저 '$DB_USER' 이미 존재"
    else
        sudo -u postgres psql -c "CREATE USER $DB_USER WITH PASSWORD '$DB_PASS';" 2>/dev/null
        info "유저 '$DB_USER' 생성 완료"
    fi

    # Create database if not exists
    if sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" 2>/dev/null | grep -q 1; then
        info "데이터베이스 '$DB_NAME' 이미 존재"
    else
        sudo -u postgres psql -c "CREATE DATABASE $DB_NAME OWNER $DB_USER;" 2>/dev/null
        sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;" 2>/dev/null
        info "데이터베이스 '$DB_NAME' 생성 완료"
    fi
else
    warn "PostgreSQL이 실행되고 있지 않습니다."
    warn "  sudo pg_ctlcluster 16 main start"
    warn "  또는: docker compose up -d postgres"
fi

# -------------------------------------------
# 5. Redis check
# -------------------------------------------
info "=== Step 5: Redis 확인 ==="

if redis-cli ping 2>/dev/null | grep -q PONG; then
    info "Redis 실행 중"
else
    warn "Redis가 실행되고 있지 않습니다."
    warn "  redis-server --daemonize yes"
    warn "  또는: docker compose up -d redis"
fi

# -------------------------------------------
# 6. Database migration
# -------------------------------------------
info "=== Step 6: DB 마이그레이션 ==="

if [ -f "alembic.ini" ]; then
    # Check if any migration versions exist
    VERSION_DIR="src/dropagent/db/migrations/versions"
    if [ -z "$(ls -A $VERSION_DIR 2>/dev/null)" ]; then
        info "초기 마이그레이션 생성 중..."
        alembic revision --autogenerate -m "initial_schema" 2>/dev/null || warn "마이그레이션 생성 실패 - DB 연결 확인 필요"
    fi

    info "마이그레이션 실행 중..."
    alembic upgrade head 2>/dev/null || warn "마이그레이션 실행 실패 - DB 연결 확인 필요"
    info "마이그레이션 완료"
else
    warn "alembic.ini 없음 - 마이그레이션 스킵"
fi

# -------------------------------------------
# 7. Run tests
# -------------------------------------------
info "=== Step 7: 유닛 테스트 ==="
python -m pytest tests/unit/ -q --tb=short 2>&1
info "테스트 완료"

# -------------------------------------------
# Done
# -------------------------------------------
echo ""
info "============================================"
info " DropAgent 셋업 완료!"
info "============================================"
echo ""
info "다음 단계:"
info "  1. .env 파일에 실제 API 키를 입력하세요"
info "  2. python -m dropagent.main 으로 실행하세요"
echo ""
