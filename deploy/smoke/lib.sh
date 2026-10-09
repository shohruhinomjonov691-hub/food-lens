# Checks used by deploy/smoke/check.sh (sourced; also exercised by tests/test_smoke_lib.py with a stub docker).
# grep exit codes are kept apart: 0 = match, 1 = no match, 2+ = the check itself failed. A failing docker command
# or grep is never read as "nothing found".
#
# Requires: the array compose=(docker compose -f ...) in the caller.

# Container paths of everything the browser downloads (overridable for tests).
ASSET_DIRS=${ASSET_DIRS:-"/srv/food-lens-web/.next/static /srv/food-lens-web/public"}
# URL forms only: Next's client runtime contains a WHATWG URL parser with the bare word "localhost" in it.
URL_RE='//(localhost|\[::1\]|api)([:/"'"'"'`]|$)|127\.0\.0\.1|api:8000'

# asset_leaks: prints files with a loopback/internal URL. Returns 0 if none, 1 if found, 2 if the check failed.
asset_leaks() {
  local out rc
  # shellcheck disable=SC2086 # ASSET_DIRS is a space-separated list of paths without spaces
  out=$("${compose[@]}" exec -T web sh -c 'grep -rlE -e "$0" -- "$@"; echo "grep-exit=$?"' "$URL_RE" $ASSET_DIRS) || {
    echo "docker exec failed (exit $?)" >&2; return 2; }
  rc=$(printf '%s\n' "$out" | sed -n 's/^grep-exit=\([0-9][0-9]*\)$/\1/p' | tail -n 1)
  out=$(printf '%s\n' "$out" | grep -v '^grep-exit=' || true)
  case "$rc" in
    0) printf '%s\n' "$out"; return 1 ;;
    1) return 0 ;;
    "") echo "asset scan produced no grep status" >&2; return 2 ;;
    *) echo "asset scan failed (grep exit $rc)" >&2; return 2 ;;
  esac
}

# file_leaks FILE: same contract for a file on the host (e.g. the served HTML).
file_leaks() {
  local rc=0
  grep -qE -e "$URL_RE" -- "$1" || rc=$?
  case "$rc" in
    0) echo "$1"; return 1 ;;
    1) return 0 ;;
    *) echo "scan of $1 failed (grep exit $rc)" >&2; return 2 ;;
  esac
}

# nginx_temp_warnings: prints how many times Nginx buffered to a temp file. Returns 2 if logs could not be read.
nginx_temp_warnings() {
  local logs rc=0 n
  logs=$("${compose[@]}" logs --no-color nginx) || { echo "docker compose logs failed (exit $?)" >&2; return 2; }
  n=$(printf '%s\n' "$logs" | grep -c "buffered to a temporary file") || rc=$?
  if [ "$rc" -gt 1 ]; then echo "grep on nginx logs failed (exit $rc)" >&2; return 2; fi
  echo "$n"
}
