// Client for the Food Lens API (proxied by Next.js under /api). Responses are checked strictly:
// anything that is not a well-formed result is treated as an error, never shown as a prediction.
import { DISHES, type Dish, isDish, variantsOf } from "./dishes";
import type { Lang } from "./i18n";
import { isRestriction, type Restriction } from "./restrictions";

export type Prediction = { dish: Dish; confidence: number };

/** high: confident · low: not confirmed, top-3 guesses · abstain: the model does not guess · non_food: not food. */
export const TIERS = ["high", "low", "abstain", "non_food"] as const;
export type Tier = (typeof TIERS)[number];

export type PredictOutcome =
  | { kind: "ok"; tier: Tier; predictions: Prediction[]; threshold: number; highThreshold: number;
      nonFoodReason: string | null; fallbackAvailable: boolean }
  | { kind: "not-ready" }
  | { kind: "busy" }
  | { kind: "invalid"; code: string }
  | { kind: "server"; status: number }
  | { kind: "network" }
  | { kind: "aborted" };

export type Source = { url: string; title: string };
export type GuardStatus = "safe" | "warning" | "unknown";
export type GuardResult = {
  id: Restriction; label: string; status: GuardStatus; message: string; note: string | null;
  matches: { ingredient: string; kind: "contains" | "may" }[]; unverified: string[];
};
export type Guard = { restrictions: GuardResult[]; basis: string };
export type Ingredients = {
  dish: Dish; variant: string | null; name: string; ingredients: string[]; disclaimer: string;
  variantNote: string | null; sources: Source[]; translated: boolean; guard: Guard | null;
};
export type IngredientsOutcome =
  | { kind: "ok"; data: Ingredients }
  | { kind: "error" }
  | { kind: "aborted" };

export type FallbackVerdict = "food" | "not_food" | "unclear";
export type FallbackDish = Dish | "other_food";
export type FallbackOutcome =
  | { kind: "used"; verdict: FallbackVerdict; dish: FallbackDish | null }
  | { kind: "unavailable"; reason: string }
  | { kind: "aborted" };

export type EvalClass = { dish: Dish; precision: number; recall: number; f1: number; support: number; smallN: boolean };
export type EvalVariant = { target: Dish; variant: string; n: number; recall: number; smallN: boolean };
export type EvalTier = { n: number; share: number | null; accuracy: number | null };
export type Evaluation = {
  n: number; accuracy: number; macroF1: number; ci: { accuracy: [number, number] | null; macroF1: [number, number] | null };
  perClass: EvalClass[]; perVariant: EvalVariant[]; abstainBelow: number; highFrom: number;
  tiers: Record<"high" | "low" | "abstain", EvalTier> | null; limits: string[];
};
export type EvaluationOutcome = { kind: "ok"; data: Evaluation } | { kind: "error" } | { kind: "aborted" };

const INVALID_IMAGE_CODES = new Set([
  "empty_file", "file_too_large", "unsupported_format", "animated_image", "corrupt_image", "image_too_large",
]);
const FALLBACK_REASONS = new Set([
  "not_configured", "rate_limited", "busy", "timeout", "provider_error", "refused", "bad_response", "image_too_large",
]);

type Fetch = typeof fetch;

function isAbort(err: unknown): boolean {
  return err instanceof DOMException && err.name === "AbortError";
}

function finite01(x: unknown): x is number {
  return typeof x === "number" && Number.isFinite(x) && x >= 0 && x <= 1;
}

const isTier = (v: unknown): v is Tier => (TIERS as readonly unknown[]).includes(v);

export function parsePrediction(body: unknown): PredictOutcome | null {
  if (!body || typeof body !== "object") return null;
  const b = body as Record<string, unknown>;
  if (!isTier(b.tier) || !Array.isArray(b.predictions)) return null;
  if (!finite01(b.threshold) || !finite01(b.high_threshold) || b.high_threshold < b.threshold) return null;
  if (typeof b.fallback_available !== "boolean") return null;
  const predictions: Prediction[] = [];
  if (b.tier === "high" || b.tier === "low") {
    if (b.predictions.length !== 3) return null;
    for (const p of b.predictions) {
      if (!p || typeof p !== "object") return null;
      const { class: dish, confidence } = p as Record<string, unknown>;
      if (!isDish(dish) || !finite01(confidence)) return null;
      predictions.push({ dish, confidence });
    }
    if (new Set(predictions.map((p) => p.dish)).size !== 3) return null;
    for (let i = 1; i < 3; i++) if (predictions[i].confidence > predictions[i - 1].confidence) return null;
  } else if (b.predictions.length !== 0) {
    return null;                                    // abstain / non_food: the server must not send a guess
  }
  const reason = b.non_food_reason;
  if (!(reason === null || reason === undefined || typeof reason === "string")) return null;
  return {
    kind: "ok", tier: b.tier, predictions, threshold: b.threshold, highThreshold: b.high_threshold,
    nonFoodReason: typeof reason === "string" ? reason : null, fallbackAvailable: b.fallback_available,
  };
}

async function readJson(res: Response, signal: AbortSignal): Promise<{ body: unknown; aborted: boolean }> {
  let body: unknown = null;
  try {
    body = await res.json();
  } catch (err) {
    if (isAbort(err) || signal.aborted) return { body, aborted: true };
  }
  return { body, aborted: signal.aborted };
}

const codeOf = (body: unknown) =>
  body && typeof body === "object" ? (body as Record<string, unknown>).code : undefined;

export async function predict(image: Blob, signal: AbortSignal, fetchImpl: Fetch = fetch): Promise<PredictOutcome> {
  let res: Response;
  try {
    res = await fetchImpl("/api/predict", {
      method: "POST", body: image, signal,
      headers: { "Content-Type": image.type || "application/octet-stream" },
    });
  } catch (err) {
    return isAbort(err) || signal.aborted ? { kind: "aborted" } : { kind: "network" };
  }
  const { body, aborted } = await readJson(res, signal);
  if (aborted) return { kind: "aborted" };
  const code = codeOf(body);
  if (res.status === 503 && code === "MODEL_NOT_READY") return { kind: "not-ready" };
  if (res.status === 503 && code === "SERVER_BUSY") return { kind: "busy" };
  if (res.status >= 400 && res.status < 500 && typeof code === "string" && INVALID_IMAGE_CODES.has(code)) {
    return { kind: "invalid", code };
  }
  if (!res.ok) return { kind: "server", status: res.status };
  return parsePrediction(body) ?? { kind: "server", status: res.status };
}

/** The extra check. Any failure is an "unavailable" answer: the page keeps the earlier result. */
export function parseFallback(body: unknown): FallbackOutcome | null {
  if (!body || typeof body !== "object") return null;
  const b = body as Record<string, unknown>;
  if (b.status === "unavailable") {
    return { kind: "unavailable", reason: typeof b.reason === "string" && FALLBACK_REASONS.has(b.reason) ? b.reason : "provider_error" };
  }
  if (b.status !== "used") return null;
  const { verdict, dish } = b;
  if (verdict !== "food" && verdict !== "not_food" && verdict !== "unclear") return null;
  if (!(dish === null || dish === "other_food" || isDish(dish))) return null;
  if ((verdict === "food") !== (dish !== null)) return null;       // food names a dish; the others do not
  return { kind: "used", verdict, dish };
}

export async function fallback(image: Blob, signal: AbortSignal, fetchImpl: Fetch = fetch): Promise<FallbackOutcome> {
  let res: Response;
  try {
    res = await fetchImpl("/api/fallback", {
      method: "POST", body: image, signal,
      headers: { "Content-Type": image.type || "application/octet-stream" },
    });
  } catch (err) {
    return isAbort(err) || signal.aborted ? { kind: "aborted" } : { kind: "unavailable", reason: "network" };
  }
  const { body, aborted } = await readJson(res, signal);
  if (aborted) return { kind: "aborted" };
  const code = codeOf(body);
  if (res.status >= 400 && res.status < 500 && typeof code === "string" && INVALID_IMAGE_CODES.has(code)) {
    return { kind: "unavailable", reason: "invalid_image" };
  }
  if (!res.ok) return { kind: "unavailable", reason: "server" };
  return parseFallback(body) ?? { kind: "unavailable", reason: "bad_response" };
}

function parseGuard(value: unknown, avoid: readonly Restriction[]): Guard | null {
  if (!value || typeof value !== "object") return null;
  const g = value as Record<string, unknown>;
  if (!Array.isArray(g.restrictions) || g.restrictions.length !== avoid.length || typeof g.basis !== "string") return null;
  const out: GuardResult[] = [];
  for (const [i, r] of g.restrictions.entries()) {
    if (!r || typeof r !== "object") return null;
    const x = r as Record<string, unknown>;
    if (x.id !== avoid[i] || !isRestriction(x.id) || typeof x.label !== "string" || typeof x.message !== "string") return null;
    if (x.status !== "safe" && x.status !== "warning" && x.status !== "unknown") return null;
    if (!(x.note === null || typeof x.note === "string") || !Array.isArray(x.matches) || !Array.isArray(x.unverified)) return null;
    const matches: GuardResult["matches"] = [];
    for (const m of x.matches) {
      const { ingredient, kind } = (m ?? {}) as Record<string, unknown>;
      if (typeof ingredient !== "string" || (kind !== "contains" && kind !== "may")) return null;
      matches.push({ ingredient, kind });
    }
    const unverified: string[] = [];
    for (const u of x.unverified) {
      const { ingredient } = (u ?? {}) as Record<string, unknown>;
      if (typeof ingredient !== "string") return null;
      unverified.push(ingredient);
    }
    // The status must agree with the evidence it comes with, so a badge can never contradict its list.
    if ((x.status === "warning") !== (matches.length > 0)) return null;
    if (x.status === "unknown" && unverified.length === 0) return null;
    if (x.status === "safe" && (matches.length > 0 || unverified.length > 0)) return null;
    out.push({ id: x.id, label: x.label, status: x.status, message: x.message, note: x.note, matches, unverified });
  }
  return { restrictions: out, basis: g.basis };
}

export function parseIngredients(
  body: unknown, dish: Dish, variant: string | null, avoid: readonly Restriction[] = [],
): Ingredients | null {
  if (!body || typeof body !== "object") return null;
  const b = body as Record<string, unknown>;
  const strings = (v: unknown): v is string[] => Array.isArray(v) && v.length > 0 && v.every((s) => typeof s === "string");
  if (b.dish !== dish || (b.variant ?? null) !== variant || typeof b.name !== "string" || !strings(b.ingredients)
      || typeof b.disclaimer !== "string" || !Array.isArray(b.sources) || b.sources.length === 0) return null;
  const sources: Source[] = [];
  for (const s of b.sources) {
    const { url, title } = (s ?? {}) as Record<string, unknown>;
    if (typeof url !== "string" || !url.startsWith("https://") || typeof title !== "string") return null;
    sources.push({ url, title });
  }
  let guard: Guard | null = null;
  if (avoid.length > 0) {
    guard = parseGuard(b.guard, avoid);
    if (!guard) return null;                       // asked for a check, got something unusable: an error, not a silent "safe"
  }
  return {
    dish, variant, name: b.name, ingredients: b.ingredients, disclaimer: b.disclaimer,
    variantNote: typeof b.variant_note === "string" ? b.variant_note : null, sources, translated: b.translated === true,
    guard,
  };
}

export async function fetchIngredients(
  dish: Dish, variant: string | null, lang: Lang, avoid: readonly Restriction[], signal: AbortSignal,
  fetchImpl: Fetch = fetch,
): Promise<IngredientsOutcome> {
  if (variantsOf(dish).length > 0 && (variant === null || !variantsOf(dish).includes(variant))) {
    return { kind: "error" };   // never ask for a grouped dish without the user's kind
  }
  const params = new URLSearchParams({
    lang, ...(variant ? { variant } : {}), ...(avoid.length ? { avoid: avoid.join(",") } : {}),
  });
  try {
    const res = await fetchImpl(`/api/ingredients/${dish}?${params}`, { signal });
    if (!res.ok) return { kind: "error" };
    const data = parseIngredients(await res.json(), dish, variant, avoid);
    if (signal.aborted) return { kind: "aborted" };
    return data ? { kind: "ok", data } : { kind: "error" };
  } catch (err) {
    return isAbort(err) || signal.aborted ? { kind: "aborted" } : { kind: "error" };
  }
}

const pair = (v: unknown): [number, number] | null =>
  Array.isArray(v) && v.length === 2 && v.every((x) => finite01(x)) ? [v[0], v[1]] : null;

export function parseEvaluation(body: unknown): Evaluation | null {
  if (!body || typeof body !== "object") return null;
  const b = body as Record<string, unknown>;
  if (typeof b.n !== "number" || !(b.n > 0) || !finite01(b.accuracy) || !finite01(b.macro_f1)) return null;
  if (!Array.isArray(b.per_class) || b.per_class.length !== DISHES.length) return null;
  const perClass: EvalClass[] = [];
  for (const c of b.per_class) {
    const x = (c ?? {}) as Record<string, unknown>;
    if (!isDish(x.class) || !finite01(x.precision) || !finite01(x.recall) || !finite01(x.f1)
        || typeof x.support !== "number" || typeof x.small_n !== "boolean") return null;
    perClass.push({ dish: x.class, precision: x.precision, recall: x.recall, f1: x.f1, support: x.support, smallN: x.small_n });
  }
  if (new Set(perClass.map((c) => c.dish)).size !== DISHES.length) return null;
  const perVariant: EvalVariant[] = [];
  for (const v of Array.isArray(b.per_variant) ? b.per_variant : []) {
    const x = (v ?? {}) as Record<string, unknown>;
    if (!isDish(x.target) || typeof x.variant !== "string" || typeof x.n !== "number" || !finite01(x.recall)
        || typeof x.small_n !== "boolean") return null;
    perVariant.push({ target: x.target, variant: x.variant, n: x.n, recall: x.recall, smallN: x.small_n });
  }
  const th = (b.thresholds ?? {}) as Record<string, unknown>;
  if (!finite01(th.abstain_below) || !finite01(th.high_from)) return null;
  let tiers: Evaluation["tiers"] = null;
  if (b.tiers !== null && b.tiers !== undefined) {
    const t = b.tiers as Record<string, Record<string, unknown>>;
    const one = (k: string): EvalTier | null => {
      const x = t[k];
      if (!x || typeof x.n !== "number" || !(x.share === null || finite01(x.share)) || !(x.accuracy === null || finite01(x.accuracy))) return null;
      return { n: x.n, share: x.share as number | null, accuracy: x.accuracy as number | null };
    };
    const high = one("high"), low = one("low"), abstain = one("abstain");
    if (!high || !low || !abstain) return null;
    tiers = { high, low, abstain };
  }
  if (!Array.isArray(b.limits) || !b.limits.every((l) => typeof l === "string")) return null;
  const ci = (b.ci ?? {}) as Record<string, unknown>;
  return {
    n: b.n, accuracy: b.accuracy, macroF1: b.macro_f1, ci: { accuracy: pair(ci.accuracy), macroF1: pair(ci.macro_f1) },
    perClass, perVariant, abstainBelow: th.abstain_below, highFrom: th.high_from, tiers, limits: b.limits as string[],
  };
}

export async function fetchEvaluation(signal: AbortSignal, fetchImpl: Fetch = fetch): Promise<EvaluationOutcome> {
  try {
    const res = await fetchImpl("/api/evaluation", { signal });
    if (!res.ok) return { kind: "error" };
    const data = parseEvaluation(await res.json());
    if (signal.aborted) return { kind: "aborted" };
    return data ? { kind: "ok", data } : { kind: "error" };
  } catch (err) {
    return isAbort(err) || signal.aborted ? { kind: "aborted" } : { kind: "error" };
  }
}
