# Deploying behind the existing Nginx (food.gotrips.cloud)

> **Not deployed.** Before a public launch, the Food-101 question in “Data → Licenses” (`README.md`) must be
> decided. These files only prepare the deployment.

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
  `/srv/food-lens-runs/20261009T124948Z_9ab1801_seed42/`, owned by root, readable by uid 10001
  (`chmod -R a+rX`), and its `best.pt` SHA-256 checked against `final.json`.

## 1. Build and start the containers

```bash
cd /srv/food-lens   # the repository checkout
export FOOD_LENS_RUN_DIR_HOST=/srv/food-lens-runs/20261009T124948Z_9ab1801_seed42
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
sudo install -m 644 deploy/nginx/food-lens.bootstrap.conf.example /etc/nginx/conf.d/food-lens.conf
sudo nginx -t && sudo systemctl reload nginx
sudo certbot certonly --webroot -w /var/www/food-lens-acme -d food.gotrips.cloud \
  --deploy-hook "systemctl reload nginx"
```

Do not use `certbot --nginx`, which rewrites server blocks.

## 3. Final HTTPS site

```bash
sudo install -m 644 deploy/nginx/food-lens.conf.example /etc/nginx/conf.d/food-lens.conf
sudo nginx -t && sudo systemctl reload nginx
```

For an access-restricted launch, create `/etc/nginx/food-lens.htpasswd` on the server (never in git) and
uncomment the two `auth_basic` lines before installing.

## 4. Verify

```bash
curl -sI https://food.gotrips.cloud/ | head -1
curl -s https://food.gotrips.cloud/api/ingredients/pizza | head -c 200
sudo grep -c "buffered to a temporary file" /var/log/nginx/food-lens.error.log   # expect 0 after uploads
```

Then upload a photo in the browser and check that the other sites still answer as before.

## Rollback

Remove `/etc/nginx/conf.d/food-lens.conf`, reload Nginx, then `docker compose down` in the checkout. The other
sites are unaffected.

## Local checks (no server needed)

- `deploy/nginx/check-config.sh` — `nginx -t` with Nginx 1.24.0 in Docker for both site files.
- `deploy/smoke/check.sh` — both containers with a real run folder mounted read-only, behind Nginx 1.24.0 with the
  production snippet (see the script header for what it checks).
