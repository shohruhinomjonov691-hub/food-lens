"""Static checks of the deployment files (no Docker needed). deploy/smoke/check.sh exercises them for real."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPOSE = (ROOT / "compose.yaml").read_text(encoding="utf-8")
SITE = (ROOT / "deploy/nginx/food-lens.conf.example").read_text(encoding="utf-8")
PROXY = (ROOT / "deploy/nginx/food-lens-proxy.conf").read_text(encoding="utf-8")
LIMITS = (ROOT / "deploy/nginx/food-lens-limits.conf").read_text(encoding="utf-8")


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
    assert re.search(r"location /api/ \{\n(    [^\n]+\n)+    proxy_pass http://food_lens_api;\n\}", PROXY)
    assert "location / {\n    proxy_pass http://food_lens_web;" in PROXY
    for setting in ("client_max_body_size 11m;", "proxy_request_buffering off;", "proxy_buffering off;",
                    "proxy_max_temp_file_size 0;"):
        assert setting in PROXY, setting


def _code(text):
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def test_nginx_limits_cover_the_api_paths_and_every_zone_is_defined():
    api = re.search(r"location /api/ \{(.*?)\n\}", PROXY, re.S).group(1)
    used_req = re.findall(r"limit_req zone=(\w+) burst=(\d+) nodelay;", api)
    used_conn = re.findall(r"limit_conn (\w+) (\d+);", api)
    assert {z for z, _ in used_req} == {"food_lens_upload", "food_lens_api"} and used_conn == [("food_lens_conn", "4")]
    assert "limit_req_status 429;" in api and "limit_conn_status 429;" in api
    code = _code(LIMITS)
    for zone, _ in used_req:
        assert re.search(rf"^limit_req_zone \S+\s+zone={zone}:\d+m\s+rate=\d+r/m;", code, re.M), zone
    assert re.search(r"^limit_conn_zone \$binary_remote_addr\s+zone=food_lens_conn:\d+m;", code, re.M)


def test_only_post_requests_count_for_the_strict_upload_zone():
    code = _code(LIMITS)
    assert re.search(r"map \$request_method \$food_lens_upload_key \{\s+POST\s+\$binary_remote_addr;\s+default\s+\"\";", code)
    assert "zone=food_lens_upload" in code and "$food_lens_upload_key" in code.split("limit_req_zone", 1)[1]


def test_zones_are_defined_outside_server_blocks_and_the_site_includes_them_first():
    assert "include /etc/nginx/snippets/food-lens-limits.conf;" in SITE
    assert SITE.index("food-lens-limits.conf") < SITE.index("upstream food_lens_web")      # http level, before any server
    assert "server" not in re.sub(r"server_name|# .*", "", _code(LIMITS))                  # zones file has no server block
    smoke = (ROOT / "deploy/smoke/nginx-smoke.conf").read_text(encoding="utf-8")
    smoke_compose = (ROOT / "deploy/smoke/compose.yaml").read_text(encoding="utf-8")
    assert "include /etc/nginx/snippets/food-lens-limits.conf;" in smoke
    assert "../nginx/food-lens-limits.conf:/etc/nginx/snippets/food-lens-limits.conf:ro" in smoke_compose
    assert "food-lens-limits.conf:/etc/nginx/snippets/food-lens-limits.conf:ro" in (ROOT / "deploy/nginx/check-config.sh").read_text(encoding="utf-8")


def test_zone_names_are_unique_to_food_lens():
    for name in re.findall(r"zone=(\w+):", LIMITS) + re.findall(r"\$(food_lens_\w+)", LIMITS):
        assert name.startswith("food_lens_"), name
