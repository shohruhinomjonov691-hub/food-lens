// Client for the Food Lens API (proxied by Next.js under /api). Responses are checked strictly:
// anything that is not a well-formed result is treated as an error, never shown as a prediction.
import { type Dish, isDish, variantsOf } from "./dishes";
import type { Lang } from "./i18n";

export type Prediction = { dish: Dish; confidence: number };

export type PredictOutcome =
  | { kind: "ok"; predictions: Prediction[]; uncertain: boolean; threshold: number }
  | { kind: "not-ready" }
  | { kind: "invalid"; code: string }
  | { kind: "server"; status: number }
  | { kind: "network" }
  | { kind: "aborted" };

export type Source = { url: string; title: string };
export type Ingredients = {
  dish: Dish; variant: string | null; name: string; ingredients: string[]; disclaimer: string;
  variantNote: string | null; sources: Source[]; translated: boolean;
};
export type IngredientsOutcome =
  | { kind: "ok"; data: Ingredients }
  | { kind: "error" }
  | { kind: "aborted" };

const INVALID_IMAGE_CODES = new Set([
  "empty_file", "file_too_large", "unsupported_format", "animated_image", "corrupt_image", "image_too_large",
]);

type Fetch = typeof fetch;

function isAbort(err: unknown): boolean {
  return err instanceof DOMException && err.name === "AbortError";
}

function finite01(x: unknown): x is number {
  return typeof x === "number" && Number.isFinite(x) && x >= 0 && x <= 1;
}

export function parsePrediction(body: unknown): PredictOutcome | null {
  if (!body || typeof body !== "object") return null;
  const b = body as Record<string, unknown>;
  if (!Array.isArray(b.predictions) || b.predictions.length !== 3) return null;
  const predictions: Prediction[] = [];
  for (const p of b.predictions) {
    if (!p || typeof p !== "object") return null;
    const { class: dish, confidence } = p as Record<string, unknown>;
    if (!isDish(dish) || !finite01(confidence)) return null;
    predictions.push({ dish, confidence });
  }
  if (new Set(predictions.map((p) => p.dish)).size !== 3) return null;
  for (let i = 1; i < 3; i++) if (predictions[i].confidence > predictions[i - 1].confidence) return null;
  if (typeof b.uncertain !== "boolean" || !finite01(b.threshold)) return null;
  return { kind: "ok", predictions, uncertain: b.uncertain, threshold: b.threshold };
}

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
  let body: unknown = null;
  try {
    body = await res.json();
  } catch (err) {
    if (isAbort(err) || signal.aborted) return { kind: "aborted" };
  }
  if (signal.aborted) return { kind: "aborted" };
  const code = body && typeof body === "object" ? (body as Record<string, unknown>).code : undefined;
  if (res.status === 503 && code === "MODEL_NOT_READY") return { kind: "not-ready" };
  if (res.status >= 400 && res.status < 500 && typeof code === "string" && INVALID_IMAGE_CODES.has(code)) {
    return { kind: "invalid", code };
  }
  if (!res.ok) return { kind: "server", status: res.status };
  return parsePrediction(body) ?? { kind: "server", status: res.status };
}

export function parseIngredients(body: unknown, dish: Dish, variant: string | null): Ingredients | null {
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
  return {
    dish, variant, name: b.name, ingredients: b.ingredients, disclaimer: b.disclaimer,
    variantNote: typeof b.variant_note === "string" ? b.variant_note : null, sources, translated: b.translated === true,
  };
}

export async function fetchIngredients(
  dish: Dish, variant: string | null, lang: Lang, signal: AbortSignal, fetchImpl: Fetch = fetch,
): Promise<IngredientsOutcome> {
  if (variantsOf(dish).length > 0 && (variant === null || !variantsOf(dish).includes(variant))) {
    return { kind: "error" };   // never ask for a grouped dish without the user's kind
  }
  const params = new URLSearchParams({ lang, ...(variant ? { variant } : {}) });
  try {
    const res = await fetchImpl(`/api/ingredients/${dish}?${params}`, { signal });
    if (!res.ok) return { kind: "error" };
    const data = parseIngredients(await res.json(), dish, variant);
    if (signal.aborted) return { kind: "aborted" };
    return data ? { kind: "ok", data } : { kind: "error" };
  } catch (err) {
    return isAbort(err) || signal.aborted ? { kind: "aborted" } : { kind: "error" };
  }
}
