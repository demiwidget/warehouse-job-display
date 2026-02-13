#!/usr/bin/env bash
set -euo pipefail

# Warehouse Job Display bootstrap script
# - Installs dependencies
# - Optionally creates .env from template
# - Runs DB migration generation/migrate
# - Optionally runs checks/tests/build
# - Starts dev or production server

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

MODE="dev"
RUN_CHECKS=true
RUN_TESTS=true
RUN_BUILD=false
RUN_DB_PUSH=true
AUTO_ENV=false
FORCE=false

usage() {
  cat <<'USAGE'
Usage: ./scripts/bootstrap.sh [options]

Options:
  --prod              Build and run production server (pnpm build && pnpm start)
  --dev               Run development server (default, pnpm dev)
  --skip-check        Skip TypeScript check (pnpm check)
  --skip-test         Skip tests (pnpm test)
  --build             Run build step before starting server
  --skip-db           Skip database migration/generation step (pnpm db:push)
  --auto-env          Create .env from .env.example if .env is missing
  --force             Overwrite .env when used with --auto-env
  -h, --help          Show this help

Examples:
  ./scripts/bootstrap.sh
  ./scripts/bootstrap.sh --auto-env --build
  ./scripts/bootstrap.sh --prod --auto-env
USAGE
}

log() {
  printf "\n[bootstrap] %s\n" "$1"
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Error: required command '$1' is not installed or not in PATH." >&2
    exit 1
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --prod)
      MODE="prod"
      RUN_BUILD=true
      shift
      ;;
    --dev)
      MODE="dev"
      shift
      ;;
    --skip-check)
      RUN_CHECKS=false
      shift
      ;;
    --skip-test)
      RUN_TESTS=false
      shift
      ;;
    --build)
      RUN_BUILD=true
      shift
      ;;
    --skip-db)
      RUN_DB_PUSH=false
      shift
      ;;
    --auto-env)
      AUTO_ENV=true
      shift
      ;;
    --force)
      FORCE=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 1
      ;;
  esac
done

require_cmd node
require_cmd pnpm

log "Node version: $(node -v)"
log "pnpm version: $(pnpm -v)"

if [[ "$AUTO_ENV" == true ]]; then
  if [[ ! -f .env.example ]]; then
    log "No .env.example found; skipping .env creation"
  else
    if [[ -f .env && "$FORCE" != true ]]; then
      log ".env already exists; not overwriting (use --force with --auto-env to overwrite)"
    else
      cp .env.example .env
      log "Created .env from .env.example"
    fi
  fi
fi

log "Installing dependencies"
pnpm install

if [[ "$RUN_DB_PUSH" == true ]]; then
  log "Running database schema generation/migrations (pnpm db:push)"
  pnpm db:push
else
  log "Skipping database migration step"
fi

if [[ "$RUN_CHECKS" == true ]]; then
  log "Running TypeScript check"
  pnpm check
else
  log "Skipping TypeScript check"
fi

if [[ "$RUN_TESTS" == true ]]; then
  log "Running tests"
  pnpm test
else
  log "Skipping tests"
fi

if [[ "$RUN_BUILD" == true ]]; then
  log "Running build"
  pnpm build
fi

if [[ "$MODE" == "prod" ]]; then
  log "Starting production server"
  exec pnpm start
else
  log "Starting development server"
  exec pnpm dev
fi
