"""Static checks of the deployment files (no Docker needed). deploy/smoke/check.sh exercises them for real."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPOSE = (ROOT / "compose.yaml").read_text(encoding="utf-8")
SITE = (ROOT / "deploy/nginx/food-lens.conf.example").read_text(encoding="utf-8")
PROXY = (ROOT / "deploy/nginx/food-lens-proxy.conf").read_text(encoding="utf-8")


def test_published_ports_are_loopback_only_and_distinct_from_other_apps():
    ports = re.findall(r'^\s+- "([^"]+)"\s*$', COMPOSE, re.M)
    published = [p for p in ports if re.match(r"[\d.]+:", p) or p.startswith("${")]
    assert published == ["127.0.0.1:${FOOD_LENS_API_PORT:-18776}:8000", "127.0.0.1:${FOOD_LENS_WEB_PORT:-18775}:3000"]
    assert re.search(r"^name: food-lens$", COMPOSE, re.M)


def test_hardening_applies_to_both_services():
    assert COMPOSE.count("<<: *hardening") == 2
    for setting in ("read_only: true", "- ALL", "no-new-privileges:true", "pids_limit: 256",
                    'max-size: "10m"', 'max-file: "3"', "restart: unless-stopped"):
        assert setting in COMPOSE, setting
    assert COMPOSE.count("mem_limit:") == 2 and COMPOSE.count("cpus:") == 2


def test_model_is_a_required_read_only_mount_not_part_of_any_image():
    mount = COMPOSE[COMPOSE.index("type: bind"):COMPOSE.index("target: /run/food-lens-model") + 60]
    assert "${FOOD_LENS_RUN_DIR_HOST:?" in mount and "read_only: true" in mount
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert not re.search(r"^COPY .*(\.pt|runs|data|manifests)", dockerfile, re.M)
    rules = [l for l in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines() if l and not l.startswith("#")]
    assert rules[0] == "*"   # allowlist: only the files the API image copies
    assert not any(r.startswith("!") and re.search(r"data|runs|manifests|\.pt\b|audit|dist", r) for r in rules)
    assert "model_ready" in dockerfile   # healthy only with a loaded model


def test_images_run_as_non_root():
    for path in ("Dockerfile", "web/Dockerfile"):
        text = (ROOT / path).read_text(encoding="utf-8")
        assert "USER 10001:10001" in text and "HEALTHCHECK" in text, path
        assert re.search(r"^FROM \S+@sha256:[0-9a-f]{64}", text, re.M), f"{path}: base image not pinned by digest"


def test_web_build_bakes_the_internal_api_url_not_loopback():
    web = (ROOT / "web/Dockerfile").read_text(encoding="utf-8")
    assert "ARG FOOD_LENS_API_URL=http://api:8000" in web
    assert "FOOD_LENS_API_URL: http://api:8000" in COMPOSE


def test_nginx_site_is_separate_http11_and_routes_one_domain():
    assert "server_name food.gotrips.cloud;" in SITE
    assert not re.search(r"listen .*http2", SITE)          # existing sites on :443 stay HTTP/1.1
    assert "server 127.0.0.1:18775;" in SITE and "server 127.0.0.1:18776;" in SITE
    assert "/var/www/food-lens-acme" in SITE and "include /etc/nginx/snippets/food-lens-proxy.conf;" in SITE
    assert "location /api/ {\n    proxy_pass http://food_lens_api;" in PROXY
    assert "location / {\n    proxy_pass http://food_lens_web;" in PROXY
    for setting in ("client_max_body_size 11m;", "proxy_request_buffering off;", "proxy_buffering off;",
                    "proxy_max_temp_file_size 0;"):
        assert setting in PROXY, setting
