#!/usr/bin/env bash
# scripts/odoo-test.sh [--install-only] [module,module,...]
#
# Installs this repo's Odoo modules on a fresh Odoo 19 database in Docker (odoo:19.0 and
# postgres:16) and runs the tests of every module that has a tests/ folder. Exit 0 only when
# every module installed cleanly and every test passed.
#
#   scripts/odoo-test.sh                        every module except ebarimt_demo
#   scripts/odoo-test.sh pos_ebarimt            one module (Odoo installs its dependencies)
#   scripts/odoo-test.sh --install-only ebarimt_demo
#                                               install check only. ebarimt_demo renames the main
#                                               company, so it gets a database of its own
#
# The same script runs in CI (.github/workflows/odoo-tests.yml) and in Claude Code sessions.
# A cloud session has Docker installed but not running; run as root, the script starts it.
# The first run pulls about 900 MB of images; a run then takes 2 to 3 minutes.
# Env: ODOO_IMAGE (default odoo:19.0), PG_IMAGE (postgres:16), ODOO_TEST_LOG (full Odoo log,
#      default $TMPDIR/odoo-test.log).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ODOO_IMAGE="${ODOO_IMAGE:-odoo:19.0}"
PG_IMAGE="${PG_IMAGE:-postgres:16}"
LOG="${ODOO_TEST_LOG:-${TMPDIR:-/tmp}/odoo-test.log}"
INSTALL_ONLY=0
MODULES=""
for a in "$@"; do
  case "$a" in
    --install-only) INSTALL_ONLY=1 ;;
    -h|--help) sed -n '2,19p' "$0"; exit 0 ;;
    -*) echo "odoo-test: unknown option $a" >&2; exit 2 ;;
    *) MODULES="$a" ;;
  esac
done
if [ -z "$MODULES" ]; then
  MODULES="$(for m in "$ROOT"/*/__manifest__.py; do basename "$(dirname "$m")"; done | grep -vx ebarimt_demo | paste -sd, -)"
fi
TESTED=""
for m in ${MODULES//,/ }; do
  [ -f "$ROOT/$m/__manifest__.py" ] || { echo "odoo-test: no module $m in $ROOT" >&2; exit 2; }
  [ -d "$ROOT/$m/tests" ] && TESTED="${TESTED:+$TESTED,}/$m"
done
if [ "$INSTALL_ONLY" -eq 0 ] && [ -z "$TESTED" ]; then
  echo "odoo-test: none of $MODULES has a tests/ folder: checking that they install"
  INSTALL_ONLY=1
fi

if ! docker info >/dev/null 2>&1; then
  if [ "$(id -u)" -eq 0 ] && command -v dockerd >/dev/null 2>&1; then
    echo "odoo-test: starting dockerd (log: ${TMPDIR:-/tmp}/dockerd.log)"
    (dockerd > "${TMPDIR:-/tmp}/dockerd.log" 2>&1 &)
    for _ in $(seq 1 30); do docker info >/dev/null 2>&1 && break; sleep 1; done
  fi
  docker info >/dev/null 2>&1 || { echo "odoo-test: no Docker daemon. Start Docker, or let CI run the tests." >&2; exit 2; }
fi

NAME="odoo-test-$$"
cleanup() { docker rm -f "$NAME-db" >/dev/null 2>&1 || true; docker network rm "$NAME" >/dev/null 2>&1 || true; }
trap cleanup EXIT
docker network create "$NAME" >/dev/null
docker run -d --name "$NAME-db" --network "$NAME" \
  -e POSTGRES_USER=odoo -e POSTGRES_PASSWORD=odoo -e POSTGRES_DB=postgres "$PG_IMAGE" >/dev/null
for _ in $(seq 1 60); do docker exec "$NAME-db" pg_isready -q -U odoo 2>/dev/null && break; sleep 1; done

ARGS=(odoo -d test -i "$MODULES" --stop-after-init)
if [ "$INSTALL_ONLY" -eq 1 ]; then
  echo "odoo-test: installing $MODULES on a fresh database ($ODOO_IMAGE)"
else
  ARGS+=(--test-enable --test-tags "$TESTED" --log-level=test)
  echo "odoo-test: installing $MODULES and running the tests of ${TESTED//\//} ($ODOO_IMAGE)"
fi
set +e
docker run --rm --network "$NAME" -e HOST="$NAME-db" -e USER=odoo -e PASSWORD=odoo \
  -v "$ROOT:/mnt/extra-addons:ro" "$ODOO_IMAGE" "${ARGS[@]}" > "$LOG" 2>&1
RC=$?
set -e

# Odoo log lines: "<date> <time>,<ms> <pid> <LEVEL> <db> <logger>: <message>"
PROBLEMS="$(grep -E '^[0-9-]{10} [0-9:,]{12} [0-9]+ (ERROR|CRITICAL) ' "$LOG" || true)"
RESULT="$(grep -E 'odoo\.tests\.result: [0-9]+ failed, [0-9]+ error\(s\) of [0-9]+ tests' "$LOG" | tail -1 \
          | sed -e 's/.*odoo\.tests\.result: //' -e 's/ when loading database.*//' || true)"
[ -z "$PROBLEMS" ] || { echo "$PROBLEMS" | cut -c1-300; echo; }
if [ "$RC" -ne 0 ] || [ -n "$PROBLEMS" ]; then
  echo "odoo-test: FAILED (odoo exit $RC${RESULT:+; $RESULT}). Last lines of the log ($LOG):"
  grep -vE ' (INFO|DEBUG) ' "$LOG" | tail -n 40
  exit 1
fi
if [ "$INSTALL_ONLY" -eq 0 ]; then
  case "$RESULT" in
    "0 failed, 0 error(s) of 0 tests"*|"") echo "odoo-test: FAILED: no test ran (log: $LOG)"; exit 1 ;;
    "0 failed, 0 error(s) of "*) echo "odoo-test: $RESULT (log: $LOG)" ;;
    *) echo "odoo-test: FAILED: $RESULT (log: $LOG)"; exit 1 ;;
  esac
else
  echo "odoo-test: $MODULES installed cleanly (log: $LOG)"
fi
