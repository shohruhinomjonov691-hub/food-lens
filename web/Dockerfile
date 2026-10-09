# Food Lens web (Next.js) — production image. Build context: web/ (see compose.yaml).
# Tag and digest are pinned; update both together.
FROM node:24.21.0-bookworm-slim@sha256:d6aa754f16b3197301076f047b5def2f02ea1dbbc2ca920407d46d7ec7f87b20 AS build

ENV NEXT_TELEMETRY_DISABLED=1
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY . .
# Server-side rewrite target for /api/* (the Compose service name), baked in at build time. The browser itself
# only ever requests relative /api/... URLs on its own origin.
ARG FOOD_LENS_API_URL=http://api:8000
ENV FOOD_LENS_API_URL=${FOOD_LENS_API_URL} \
    FOOD_LENS_STANDALONE=1
RUN npm run build

FROM node:24.21.0-bookworm-slim@sha256:d6aa754f16b3197301076f047b5def2f02ea1dbbc2ca920407d46d7ec7f87b20

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

WORKDIR /srv/food-lens-web
COPY --from=build /src/.next/standalone ./
COPY --from=build /src/.next/static ./.next/static
COPY --from=build /src/public ./public

# Unprivileged user; the root filesystem is read-only at runtime (compose.yaml mounts a tmpfs for .next/cache;
# its mount point exists in the image, so `docker diff` of a running container stays empty).
RUN useradd --system --uid 10001 --user-group --no-create-home --shell /usr/sbin/nologin app \
 && mkdir -p .next/cache
USER 10001:10001

EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=3 \
  CMD ["node", "-e", "fetch('http://127.0.0.1:3000/').then(r => process.exit(r.status === 200 ? 0 : 1), () => process.exit(1))"]

CMD ["node", "server.js"]
