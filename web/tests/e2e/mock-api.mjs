// TEST-ONLY mock of the Food Lens API for browser checks of UI states. Its predictions are
// hand-written fixtures, not model output; never use it in production or report its numbers as results.
// /api/ingredients/* and the "real" scenario are proxied to the real API (REAL_API, default :8002).
// Control: POST /__scenario {"name": "..."}; GET /__last -> size and SHA-256 of the last predict body.
import { createHash } from "node:crypto";
import http from "node:http";

const PORT = Number(process.env.PORT ?? 8000);
const REAL_API = process.env.REAL_API ?? "http://127.0.0.1:8002";
const BOUNDS = { threshold: 0.6, high_threshold: 0.8, non_food_reason: null, fallback_available: true };
const SCENARIOS = {
  real: null,
  confident: [200, { ...BOUNDS, tier: "high", predictions: [{ class: "kebab", confidence: 0.81 }, { class: "pizza", confidence: 0.1 },
    { class: "hot_dog", confidence: 0.05 }] }],
  low: [200, { ...BOUNDS, tier: "low", predictions: [{ class: "dessert", confidence: 0.68 }, { class: "pizza", confidence: 0.2 },
    { class: "hamburger", confidence: 0.06 }] }],
  abstain: [200, { ...BOUNDS, tier: "abstain", predictions: [] }],
  "non-food": [200, { ...BOUNDS, tier: "non_food", predictions: [], non_food_reason: "blank_image" }],
  busy: [503, { code: "SERVER_BUSY", detail: "mock" }],
  "server-error": [500, { detail: "mock failure" }],
  invalid: [415, { code: "unsupported_format", detail: "mock" }],
};
// POST /api/fallback answers with the scenario named in FALLBACK (control: POST /__fallback {"name": "..."}).
const FALLBACKS = {
  used: [200, { status: "used", verdict: "food", dish: "pizza" }],
  "not-food": [200, { status: "used", verdict: "not_food", dish: null }],
  unavailable: [200, { status: "unavailable", reason: "timeout" }],
};
let fallbackScenario = "used";
let scenario = "real";
let last = null;

const readBody = (req) => new Promise((resolve) => {
  const chunks = [];
  req.on("data", (c) => chunks.push(c));
  req.on("end", () => resolve(Buffer.concat(chunks)));
});

async function proxy(req, res, body) {
  const r = await fetch(REAL_API + req.url, { method: req.method, body: body?.length ? body : undefined,
    headers: { "content-type": req.headers["content-type"] ?? "application/octet-stream" } });
  res.writeHead(r.status, { "content-type": r.headers.get("content-type") ?? "application/json" });
  res.end(Buffer.from(await r.arrayBuffer()));
}

http.createServer(async (req, res) => {
  const body = await readBody(req);
  const json = (status, obj) => { res.writeHead(status, { "content-type": "application/json" }); res.end(JSON.stringify(obj)); };
  if (req.url === "/__scenario" && req.method === "POST") {
    const name = JSON.parse(body.toString() || "{}").name;
    if (!(name in SCENARIOS)) return json(400, { error: "unknown scenario" });
    scenario = name;
    return json(200, { scenario });
  }
  if (req.url === "/__fallback" && req.method === "POST") {
    const name = JSON.parse(body.toString() || "{}").name;
    if (!(name in FALLBACKS)) return json(400, { error: "unknown fallback scenario" });
    fallbackScenario = name;
    return json(200, { fallback: fallbackScenario });
  }
  if (req.url === "/api/fallback" && req.method === "POST") return json(...FALLBACKS[fallbackScenario]);
  if (req.url === "/__last") return json(200, last ?? {});
  if (req.url === "/api/predict" && req.method === "POST") {
    last = { bytes: body.length, sha256: createHash("sha256").update(body).digest("hex"),
             content_type: req.headers["content-type"], head: body.subarray(0, 3).toString("hex"), scenario };
    if (scenario === "real") return proxy(req, res, body);
    const [status, payload] = SCENARIOS[scenario];
    return json(status, payload);
  }
  return proxy(req, res, body).catch(() => json(502, { detail: "real API unreachable" }));
}).listen(PORT, "127.0.0.1", () => console.log(`mock API on :${PORT} (scenario ${scenario}), real API ${REAL_API}`));
