"""deploy/smoke/lib.sh with a stub `docker`: a failed docker command, a missing asset directory or a grep error must
make the smoke check fail (status 2), never pass as "nothing found"; a clean state passes."""
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LIB = ROOT / "deploy/smoke/lib.sh"
BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(BASH is None, reason="bash not available")

# Stub for `docker compose -f compose.yaml <cmd> ...`:
#   exec -T <service> CMD...  -> runs CMD locally (or fails like a stopped container when STUB_EXEC_FAIL=1,
#                                or prints $STUB_EXEC_OUTPUT instead)
#   logs --no-color nginx     -> prints $STUB_NGINX_LOG (or fails when STUB_LOGS_FAIL=1)
STUB = """#!/usr/bin/env bash
shift 3   # compose -f compose.yaml
cmd=$1; shift
case "$cmd" in
  exec)
    [ "${STUB_EXEC_FAIL:-0}" = 1 ] && { echo "service \\"web\\" is not running" >&2; exit 1; }
    [ -n "${STUB_EXEC_OUTPUT:-}" ] && { printf '%s\\n' "$STUB_EXEC_OUTPUT"; exit 0; }
    shift 2   # -T <service>
    exec "$@" ;;
  logs)
    [ "${STUB_LOGS_FAIL:-0}" = 1 ] && { echo "Error response from daemon: No such container" >&2; exit 1; }
    cat "$STUB_NGINX_LOG" ;;
  *) echo "unexpected: $cmd" >&2; exit 99 ;;
esac
"""


@pytest.fixture
def env(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    stub = bindir / "docker"
    stub.write_text(STUB)
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    static, public = tmp_path / "static", tmp_path / "public"
    static.mkdir()
    public.mkdir()
    (static / "app.js").write_text('if("localhost"===s.host){s.host=""}fetch("/api/predict")')  # URL parser word only
    (public / "icon.svg").write_text("<svg/>")
    log = tmp_path / "nginx.log"
    log.write_text("nginx: ready\n")
    e = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "ASSET_DIRS": f"{static} {public}",
         "STUB_NGINX_LOG": str(log)}
    return {"env": e, "static": static, "public": public, "log": log, "tmp": tmp_path}


def run(env, call, **extra):
    script = (f'set -euo pipefail; compose=(docker compose -f compose.yaml); . "{LIB}"; '
              f'rc=0; out=$({call}) || rc=$?; printf "%s\\n" "$out"; echo "rc=$rc"')
    p = subprocess.run([BASH, "-c", script], env={**env["env"], **extra}, capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    lines = p.stdout.strip().splitlines()
    return int(lines[-1].removeprefix("rc=")), "\n".join(lines[:-1]).strip(), p.stderr


def test_clean_assets_pass(env):
    assert run(env, "asset_leaks")[0] == 0


def test_loopback_url_in_assets_is_reported(env):
    (env["static"] / "chunk.js").write_text('fetch("http://127.0.0.1:8000/api/predict")')
    rc, out, _ = run(env, "asset_leaks")
    assert rc == 1 and out.endswith("chunk.js")
    (env["static"] / "chunk.js").write_text('const u="http://api:8000/x"')
    assert run(env, "asset_leaks")[0] == 1


def test_missing_asset_directory_fails_the_check(env):
    shutil.rmtree(env["public"])
    rc, _, err = run(env, "asset_leaks")
    assert rc == 2 and "grep exit 2" in err


def test_docker_exec_failure_fails_the_check(env):
    rc, _, err = run(env, "asset_leaks", STUB_EXEC_FAIL="1")
    assert rc == 2 and "docker exec failed" in err


def broken_helpers(env):
    """Host-side text helpers that fail: grep -v (the old status filter), sed and tail. Recursive grep (the scan
    itself, run by the stub's exec) still works, so only a helper failure is simulated."""
    bindir = env["tmp"] / "broken"
    bindir.mkdir()
    real_grep = shutil.which("grep")
    (bindir / "grep").write_text(f"""#!/usr/bin/env bash
for a in "$@"; do [ "$a" = -v ] && {{ echo "grep: helper failure" >&2; exit 2; }}; done
exec {real_grep} "$@"
""")
    for tool in ("sed", "tail"):
        (bindir / tool).write_text(f"#!/usr/bin/env bash\necho '{tool}: helper failure' >&2\nexit 2\n")
    for f in bindir.iterdir():
        f.chmod(0o755)
    return {"PATH": f"{bindir}:{env['env']['PATH']}"}


def test_helper_filter_failure_cannot_hide_results(env):
    path = broken_helpers(env)
    assert run(env, "asset_leaks", **path)[0] == 0                       # clean stays PASS
    (env["static"] / "chunk.js").write_text('fetch("http://127.0.0.1:8000/api/predict")')
    rc, out, _ = run(env, "asset_leaks", **path)
    assert rc == 1 and out.endswith("chunk.js")                          # leak and its file name survive


def test_missing_or_invalid_grep_status_fails_the_check(env):
    for output in ("/srv/x/chunk.js", "grep-exit=", "grep-exit=abc", "grep-exit=2"):
        rc, _, err = run(env, "asset_leaks", STUB_EXEC_OUTPUT=output)
        assert rc == 2, (output, err)
    rc, out, _ = run(env, "asset_leaks", STUB_EXEC_OUTPUT="/srv/a.js\n/srv/b.js\ngrep-exit=0")
    assert rc == 1 and out.splitlines() == ["/srv/a.js", "/srv/b.js"]   # file list kept, status line removed


def test_served_html_scan(env):
    page = env["tmp"] / "index.html"
    page.write_text('<script src="/_next/static/app.js"></script>')
    assert run(env, f'file_leaks "{page}"')[0] == 0
    page.write_text('<a href="http://localhost:3000/">')
    assert run(env, f'file_leaks "{page}"')[0] == 1
    assert run(env, f'file_leaks "{env["tmp"]}/missing.html"')[0] == 2


def test_nginx_warning_count(env):
    assert run(env, "nginx_temp_warnings")[:2] == (0, "0")
    env["log"].write_text("a client request body is buffered to a temporary file /x\n" * 2 + "ok\n")
    assert run(env, "nginx_temp_warnings")[:2] == (0, "2")


def test_docker_logs_failure_fails_the_check(env):
    rc, out, err = run(env, "nginx_temp_warnings", STUB_LOGS_FAIL="1")
    assert rc == 2 and out == "" and "docker compose logs failed" in err


def test_check_script_uses_the_strict_helpers():
    text = (ROOT / "deploy/smoke/check.sh").read_text(encoding="utf-8")
    assert ". ./lib.sh" in text
    assert "temp=$(nginx_temp_warnings) || fail" in text
    assert 'leaks=$(asset_leaks) || rc=$?' in text and '[ "$rc" -eq 2 ] && fail' in text
    assert "| grep -c" not in text and "grep -rlE" not in text   # no unchecked greps over docker output left
