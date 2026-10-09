#!/usr/bin/env bash
# Builds both images and runs them behind Nginx 1.24.0 with the production proxy snippet, with a REAL training run
# mounted read-only. Fails unless:
# (1) the API has loaded exactly the mounted best.pt (SHA-256 compared with the host file);
# (2) through Nginx, / serves the app and /api/predict returns a valid top-3 for a real photo; the same request
#     through the web container's own /api rewrite returns the same answer;
# (3) /api/ingredients works; oversized uploads get 413; Nginx writes no request/response temp files;
# (4) the browser bundle contains no loopback or internal API URL;
# (5) both containers are read-only, non-root (uid 10001), healthy, unchanged, and the model mount is read-only.
#
# Usage: FOOD_LENS_RUN_DIR_HOST=/abs/path/to/run SMOKE_IMAGE=/abs/photo.jpg [SMOKE_EXPECT=pizza] deploy/smoke/check.sh
set -euo pipefail
cd "$(dirname "$0")"
: "${FOOD_LENS_RUN_DIR_HOST:?set FOOD_LENS_RUN_DIR_HOST to the training run folder}"
: "${SMOKE_IMAGE:?set SMOKE_IMAGE to a JPEG/PNG/WebP food photo}"
compose=(docker compose -f compose.yaml)
work="$(mktemp -d)"
cleanup() { "${compose[@]}" down --remove-orphans >/dev/null 2>&1 || true; rm -rf "$work"; }
trap cleanup EXIT
fail() { echo "FAIL: $*"; exit 1; }

"${compose[@]}" up -d --build --wait >/dev/null
base=http://127.0.0.1:18085
py() { "${compose[@]}" exec -T api python -c "$@"; }

# (1) The verified checkpoint is the mounted one.
expected_sha=$(shasum -a 256 "$FOOD_LENS_RUN_DIR_HOST/best.pt" | cut -d' ' -f1)
health=$(py "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health').read().decode())")
py "import json, sys; h = json.loads(sys.argv[1]); assert h['model_ready'] is True, h['model_reason']; \
assert h['model']['checkpoint_sha256'] == sys.argv[2], 'checkpoint mismatch'; \
print('api: model_ready, run', h['model']['run'], 'threshold', round(h['model']['threshold'], 4))" "$health" "$expected_sha" \
  || fail "API did not load the mounted checkpoint"

# (2) Pages and predictions through Nginx (same origin) and through the web container's rewrite.
read -r status ctype <<<"$(curl -sS -o "$work/index.html" -w '%{http_code} %{content_type}' "$base/")"
echo "GET /: $status $ctype"
[ "$status" = 200 ] && [[ "$ctype" == text/html* ]] || fail "web page"
grep -q "Food Lens" "$work/index.html" || fail "page does not look like Food Lens"

ctype_for() { case "$1" in *.png) echo image/png ;; *.webp) echo image/webp ;; *) echo image/jpeg ;; esac; }
mime=$(ctype_for "$SMOKE_IMAGE")
status=$(curl -sS -o "$work/predict.json" -w '%{http_code}' -H "Content-Type: $mime" --data-binary @"$SMOKE_IMAGE" "$base/api/predict")
[ "$status" = 200 ] || fail "POST /api/predict via Nginx returned $status: $(cat "$work/predict.json")"
read -r -d '' CHECK_PREDICT <<'PY' || true
import json, sys
body = json.loads(sys.argv[1]); expect = sys.argv[2]
preds = body["predictions"]
assert len(preds) == 3 and all(0.0 <= p["confidence"] <= 1.0 for p in preds), "top-3"
assert isinstance(body["uncertain"], bool), "uncertain flag"
assert not expect or preds[0]["class"] == expect, f"expected {expect}, got {preds[0]['class']}"
print(" / ".join(f"{p['class']} {p['confidence']:.4f}" for p in preds), "| uncertain:", body["uncertain"])
PY
echo -n "predict via nginx: "; py "$CHECK_PREDICT" "$(cat "$work/predict.json")" "${SMOKE_EXPECT:-}" || fail "predict result"

# Same photo through http://web:3000/api/predict (Next.js rewrite to http://api:8000) — must give the same answer.
via_web=$("${compose[@]}" exec -T api python -c "import sys, urllib.request
req = urllib.request.Request('http://web:3000/api/predict', data=sys.stdin.buffer.read(), headers={'Content-Type': sys.argv[1]})
print(urllib.request.urlopen(req, timeout=30).read().decode())" "$mime" < "$SMOKE_IMAGE")
py "import json, sys; a, b = json.loads(sys.argv[1]), json.loads(sys.argv[2]); \
assert a['predictions'] == b['predictions'] and a['uncertain'] == b['uncertain'], 'rewrite path differs'; \
print('predict via web rewrite: identical')" "$(cat "$work/predict.json")" "$via_web" || fail "web rewrite path"

# (3) Ingredients, size limits, no Nginx temp files.
status=$(curl -sS -o "$work/ingr.json" -w '%{http_code}' "$base/api/ingredients/kebab?variant=doner_shawarma&lang=ko")
[ "$status" = 200 ] || fail "ingredients returned $status"
py "import json, sys; b = json.loads(sys.argv[1]); assert b['ingredients'] and b['disclaimer']; print('ingredients ko:', b['name'])" \
  "$(cat "$work/ingr.json")" || fail "ingredients body"

warnings() { "${compose[@]}" logs nginx 2>&1 | grep -c "buffered to a temporary file" || true; }
head -c $((10 * 1024 * 1024 + 512 * 1024)) /dev/zero > "$work/big.bin"     # 10.5 MB: over the API limit
status=$(curl -sS -o "$work/big.json" -w '%{http_code}' -H "Content-Type: image/jpeg" --data-binary @"$work/big.bin" "$base/api/predict")
echo "10.5 MB upload: $status $(cat "$work/big.json")"
[ "$status" = 413 ] && grep -q file_too_large "$work/big.json" || fail "API size limit through Nginx"
head -c $((12 * 1024 * 1024)) /dev/zero > "$work/huge.bin"                # 12 MB: over Nginx's 11m
status=$(curl -sS -o /dev/null -w '%{http_code}' -H "Content-Type: image/jpeg" --data-binary @"$work/huge.bin" "$base/api/predict")
echo "12 MB upload: $status"
[ "$status" = 413 ] || fail "Nginx size limit"
temp=$(warnings)
echo "nginx temp-file warnings: $temp"
[ "$temp" -eq 0 ] || fail "Nginx buffered traffic to disk"

# (4) No loopback or internal API URL in anything the browser downloads (static assets, public files, served HTML).
# URL forms only: Next's client runtime contains a WHATWG URL parser with the bare word "localhost" in it.
url_re='//(localhost|\[::1\]|api)([:/"'"'"'`]|$)|127\.0\.0\.1|api:8000'
leaks=$("${compose[@]}" exec -T web grep -rlE "$url_re" /srv/food-lens-web/.next/static /srv/food-lens-web/public || true)
grep -qE "$url_re" "$work/index.html" && leaks="$leaks index.html"
[ -z "$leaks" ] || fail "internal URL in browser assets: $leaks"
echo "browser bundle: no loopback or internal API URL"

# (5) Hardening.
for svc in api web; do
  id=$("${compose[@]}" ps -q "$svc")
  ro=$(docker inspect -f '{{.HostConfig.ReadonlyRootfs}}' "$id")
  uid=$("${compose[@]}" exec -T "$svc" id -u | tr -d '\r')
  hl=$(docker inspect -f '{{.State.Health.Status}}' "$id")
  diff=$(docker diff "$id" | wc -l | tr -d ' ')
  echo "$svc: read-only=$ro uid=$uid health=$hl filesystem-changes=$diff"
  [ "$ro" = true ] && [ "$uid" = 10001 ] && [ "$hl" = healthy ] && [ "$diff" = 0 ] || fail "$svc hardening"
done
mount_rw=$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/run/food-lens-model"}}{{.RW}}{{end}}{{end}}' \
  "$("${compose[@]}" ps -q api)")
echo "model mount writable: $mount_rw"
[ "$mount_rw" = false ] || fail "model mount is not read-only"

echo "PASS"
