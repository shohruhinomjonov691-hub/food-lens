# Deploying behind the existing Nginx (food.gotrips.cloud)

> **Deployed on 2026-10-10** with these steps, from commit `e681f1b`: <https://food.gotrips.cloud>. The owner
> ran the commands on the server. The Food-101 public-use question in “Data → Licenses” (`README.md`) is
> still open; making the site public was the owner's decision and does not settle it.
>
> Differences from the templates on that server: `listen [::]:443 ssl;` was removed from the installed
> `food-lens.conf` (step 3), because no site there listens on IPv6 port 443. Paths were `/opt/food-lens`
> and `/opt/food-lens-runs/<run>`.

Target: an x86_64 server with 2 CPU / 8 GB RAM, Docker + Compose, Nginx 1.24.0 already running with sites in
`/etc/nginx/conf.d/`, HTTPS via Let’s Encrypt (certbot webroot). Live Camera Studio (`127.0.0.1:18765`), GoTrip
and Kervan already run there. These steps add one Compose project, one site file, one snippet and one
certificate; they do not modify the other sites, their certificates or their deploy procedures.

| Item | Food Lens | Must not clash with |
| --- | --- | --- |
| Compose project / containers | `food-lens` / `food-lens-api`, `food-lens-web` | `live-camera-studio`, GoTrip, Kervan |
| Host ports (loopback only) | web `127.0.0.1:18775`, api `127.0.0.1:18776` | 18765 (Camera Studio); check the rest with `ss -ltnp` |
| Nginx | `conf.d/food-lens.conf`, `snippets/food-lens-proxy.conf` | `gotrip.conf`, `kervan.conf`, `live-camera-studio.conf` |
| ACME webroot / logs | `/var/www/food-lens-acme`, `/var/log/nginx/food-lens.*.log` | other sites’ |

Limits in `compose.yaml`: api `mem_limit 1g`, `cpus 2`; web `512m`, `cpus 1`; `pids_limit 256`; logs
json-file 10 MB × 3. CPU limits are caps, not reservations: the containers share the 2 CPUs with the other apps.

## 0. Prerequisites (read-only checks first)

- DNS `A` record for `food.gotrips.cloud` → the server (`dig +short food.gotrips.cloud`).
- `nginx -v` (expect 1.24.0); `ls /etc/nginx/conf.d/`; `grep -RIn "listen .*443" /etc/nginx/` (the existing sites
  use `listen 443 ssl` without `http2`; this site does the same); `ss -ltnp | grep -E ':1877[56]\b'` (expect nothing).
- The trained run folder copied to the server **outside the repository**, e.g.
  `/opt/food-lens-runs/20261009T124948Z_9ab1801_seed42/`, owned by root, readable by uid 10001
  (directory 755, files 644), with every file's SHA-256 checked against the copy it came from
  (`best.pt` against `final.json`).

## 1. Build and start the containers

```bash
cd /opt/food-lens   # the repository checkout
# .env is git-ignored and holds only this path, so later `docker compose` commands find it too
printf 'FOOD_LENS_RUN_DIR_HOST=%s\n' /opt/food-lens-runs/20261009T124948Z_9ab1801_seed42 > .env
docker compose up -d --build --wait
curl -s http://127.0.0.1:18776/health      # "model_ready": true and the expected checkpoint_sha256
curl -sI http://127.0.0.1:18775/ | head -1  # HTTP/1.1 200
```

The API container only becomes healthy when the verified model is loaded; without the run folder Compose refuses
to start (`FOOD_LENS_RUN_DIR_HOST` is required).

## 2. HTTP bootstrap and certificate (webroot mode)

```bash
sudo install -d -m 755 /var/www/food-lens-acme
sudo install -m 644 deploy/nginx/food-lens-proxy.conf /etc/nginx/snippets/food-lens-proxy.conf
sudo install -m 644 deploy/nginx/food-lens-limits.conf /etc/nginx/snippets/food-lens-limits.conf
sudo install -m 644 deploy/nginx/food-lens.bootstrap.conf.example /etc/nginx/conf.d/food-lens.conf
sudo nginx -t && sudo systemctl reload nginx
sudo certbot certonly --webroot -w /var/www/food-lens-acme -d food.gotrips.cloud \
  --deploy-hook "systemctl reload nginx"
```

Do not use `certbot --nginx`, which rewrites server blocks.

## 3. Final HTTPS site

```bash
sudo install -m 644 deploy/nginx/food-lens.conf.example /etc/nginx/conf.d/food-lens.conf
# only if no other site listens on [::]:443 (check: sudo grep -RIn 'listen \[::\]:443' /etc/nginx/):
sudo sed -i '/listen \[::\]:443 ssl;/d' /etc/nginx/conf.d/food-lens.conf
sudo nginx -t && sudo systemctl reload nginx
```

`systemctl reload` returns before the old Nginx workers have finished, so a check run immediately afterwards
can still get the previous configuration (404, or another site's certificate). Wait a few seconds before
verifying.

For an access-restricted launch, create `/etc/nginx/food-lens.htpasswd` on the server (never in git) and
uncomment the two `auth_basic` lines before installing.

## Request limits (`/api/` only)

`deploy/nginx/food-lens-limits.conf` (installed as `/etc/nginx/snippets/food-lens-limits.conf` and included at the top of
`conf.d/food-lens.conf`, outside any server block) defines three zones; `food-lens-proxy.conf` applies them to
`location /api/`. All limits are per client IP:

| Limit | Value | Meaning |
| --- | --- | --- |
| `food_lens_upload` (`limit_req`) | 12 requests/minute, burst 10 | only POST requests: photo analysis and the extra check, the costly ones |
| `food_lens_api` (`limit_req`) | 120 requests/minute, burst 30 | every `/api/` request (ingredients, health, ...) |
| `food_lens_conn` (`limit_conn`) | 4 simultaneous requests | also stops many slow uploads (request buffering is off) |

Over a limit Nginx answers **HTTP 429** (the API's own "busy" answer stays 503 `SERVER_BUSY`; the page shows its generic
server-error message for a 429). The API still protects itself behind this (at most 2 photos decoded or analysed at once,
8 waiting, then 503), and the extra check keeps its own service-wide limit of 10 per minute. The pages and `/_next/static/`
are not limited here.

Limits are per `$binary_remote_addr`. This Nginx is the edge, so that is the real visitor. If a CDN or another proxy is
put in front, configure `ngx_http_realip_module` first, or all visitors share one limit. Visitors behind one NAT also
share one limit; raise the rates in `food-lens-limits.conf` if that matters. Other sites in `conf.d/` are not affected:
the zone and variable names all start with `food_lens_`. The 429s appear in `/var/log/nginx/food-lens.error.log`
(`limiting requests` / `limiting connections`, level warn).

Try it after installing (each line counts against your own address, so wait a minute afterwards):

```bash
for i in $(seq 1 60); do curl -s -o /dev/null -w '%{http_code}\n' https://food.gotrips.cloud/api/ingredients/pizza; done | sort | uniq -c
# expect a mix of 200 and 429 (about 31 allowed at once, then roughly 2 per second)
```

Static checks of these files run in `tests/test_deploy_config.py`; `deploy/nginx/check-config.sh` runs `nginx -t` with
Nginx 1.24.0 in Docker, and `deploy/smoke/check.sh` runs the same zones in front of the containers.

## 4. Verify

```bash
curl -sI https://food.gotrips.cloud/ | head -1
curl -s https://food.gotrips.cloud/api/ingredients/pizza | head -c 200
sudo grep -c "buffered to a temporary file" /var/log/nginx/food-lens.error.log   # expect 0 after uploads
```

Then upload a photo in the browser and check that the other sites still answer as before.

## Rollback

Move the site file aside (nothing is deleted), reload Nginx, then stop the containers if wanted:

```bash
sudo mkdir -p /root/food-lens-rollback && sudo mv /etc/nginx/conf.d/food-lens.conf /root/food-lens-rollback/
sudo nginx -t && sudo systemctl reload nginx
cd /opt/food-lens && docker compose down
```

The other sites are unaffected. The certificate, checkout, run folder and images stay in place.

## Local checks (no server needed)

- `deploy/nginx/check-config.sh` — `nginx -t` with Nginx 1.24.0 in Docker for both site files (with the proxy and limits snippets).
- `deploy/smoke/check.sh` — both containers with a real run folder mounted read-only, behind Nginx 1.24.0 with the
  production snippet (see the script header for what it checks).
