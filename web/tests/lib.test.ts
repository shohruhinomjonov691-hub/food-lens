import { describe, expect, it, vi } from "vitest";
import { fallback, fetchEvaluation, fetchIngredients, parseEvaluation, parseFallback, parsePrediction, predict } from "@/lib/api";
import { clampRect, DEFAULT_RECT, MIN_SIZE, moveRect, outputSize, resizeCorner, toPixels } from "@/lib/crop";
import { DISHES, VARIANTS } from "@/lib/dishes";
import { initialState, reducer, type State } from "@/lib/flow";
import { browserStorage, loadLang, MESSAGES, saveLang, translate } from "@/lib/i18n";
import { loadAvoid, normalizeAvoid, RESTRICTIONS, saveAvoid } from "@/lib/restrictions";
import { checkDimensions, checkFile, sniff } from "@/lib/upload";

const PREDS = [{ class: "kebab", confidence: 0.81 }, { class: "pizza", confidence: 0.1 }, { class: "hot_dog", confidence: 0.05 }];
const okBody = { tier: "high", predictions: PREDS, threshold: 0.6, high_threshold: 0.8, non_food_reason: null, fallback_available: false };
const photo = (url = "blob:p1") => ({ url, width: 800, height: 600 });
const ok = { kind: "ok" as const, tier: "high" as const, predictions: [{ dish: "kebab" as const, confidence: 0.81 },
  { dish: "pizza" as const, confidence: 0.1 }, { dish: "hot_dog" as const, confidence: 0.05 }], threshold: 0.6,
  highThreshold: 0.8, nonFoodReason: null, fallbackAvailable: false };

function analyzing(): State {
  let s = reducer(initialState, { type: "PHOTO_LOADED", photo: photo() });
  s = reducer(s, { type: "ANALYZE", sentCrop: photo("blob:c1") });
  return s;
}

describe("flow reducer: stale responses never win", () => {
  it("applies the current prediction", () => {
    const s = analyzing();
    const r = reducer(s, { type: "PREDICTED", seq: s.seq, outcome: ok });
    expect(r.stage).toBe("result");
    expect(r.predictions?.[0].dish).toBe("kebab");
  });
  it.each([
    ["a new photo", { type: "PHOTO_LOADED", photo: photo("blob:p2") }],
    ["a crop change", { type: "CROP_CHANGED", crop: { x: 0, y: 0, w: 0.5, h: 0.5 } }],
    ["edit crop", { type: "EDIT_CROP" }],
    ["reset", { type: "RESET" }],
  ] as const)("ignores the old prediction after %s", (_, action) => {
    const s = analyzing();
    const old = s.seq;
    const next = reducer(s, action);
    expect(reducer(next, { type: "PREDICTED", seq: old, outcome: ok })).toBe(next);
  });
  it("ignores the old prediction after a second analysis", () => {
    const s = analyzing();
    const again = reducer(reducer(s, { type: "EDIT_CROP" }), { type: "ANALYZE", sentCrop: photo("blob:c2") });
    expect(reducer(again, { type: "PREDICTED", seq: s.seq, outcome: ok })).toBe(again);
    expect(reducer(again, { type: "PREDICTED", seq: again.seq, outcome: { kind: "not-ready" } }).stage).toBe("not-ready");
  });
  it("maps outcomes to stages", () => {
    const s = analyzing();
    const p = (outcome: Parameters<typeof reducer>[1] & { type: "PREDICTED" }) => reducer(s, outcome);
    expect(p({ type: "PREDICTED", seq: s.seq, outcome: { ...ok, tier: "low" } }).stage).toBe("low");
    expect(p({ type: "PREDICTED", seq: s.seq, outcome: { ...ok, tier: "abstain", predictions: [] } }).stage).toBe("abstain");
    expect(p({ type: "PREDICTED", seq: s.seq, outcome: { ...ok, tier: "non_food", predictions: [], nonFoodReason: "blank_image" } }).stage).toBe("non-food");
    expect(p({ type: "PREDICTED", seq: s.seq, outcome: { kind: "busy" } })).toMatchObject({ stage: "error", error: "busy" });
    expect(p({ type: "PREDICTED", seq: s.seq, outcome: { kind: "network" } })).toMatchObject({ stage: "error", error: "network" });
    expect(p({ type: "PREDICTED", seq: s.seq, outcome: { kind: "server", status: 500 } }).error).toBe("server");
    expect(p({ type: "PREDICTED", seq: s.seq, outcome: { kind: "aborted" } })).toBe(s);
  });
});

describe("flow reducer: the user chooses the kind", () => {
  const confirmed = (dish: "kebab" | "dessert" | "pizza") => {
    const s = analyzing();
    return reducer(reducer(s, { type: "PREDICTED", seq: s.seq, outcome: ok }), { type: "CONFIRM_DISH", dish });
  };
  it("kebab and dessert ask for the kind and preselect nothing", () => {
    for (const dish of ["kebab", "dessert"] as const) {
      const s = confirmed(dish);
      expect(s.stage).toBe("variant");
      expect(s.variant).toBeNull();
      expect(reducer(s, { type: "CONFIRM_VARIANT" })).toBe(s);               // no kind -> nothing happens
      expect(reducer(s, { type: "PICK_VARIANT", variant: "pizza" })).toBe(s);  // not a kind of this dish
    }
  });
  it("pizza goes straight to ingredients", () => {
    expect(confirmed("pizza")).toMatchObject({ stage: "ingredients", variant: null });
  });
  it("an old ingredient response cannot replace the new kind", () => {
    let s = reducer(confirmed("kebab"), { type: "PICK_VARIANT", variant: "skewered" });
    s = reducer(s, { type: "CONFIRM_VARIANT" });
    const oldSeq = s.ingredientsSeq;
    s = reducer(s, { type: "CHANGE_VARIANT" });
    s = reducer(reducer(s, { type: "PICK_VARIANT", variant: "doner_shawarma" }), { type: "CONFIRM_VARIANT" });
    const stale = reducer(s, { type: "INGREDIENTS", seq: oldSeq, outcome: { kind: "error" } });
    expect(stale).toBe(s);
    const reload = reducer(s, { type: "RELOAD_INGREDIENTS" });   // language change
    expect(reducer(reload, { type: "INGREDIENTS", seq: s.ingredientsSeq, outcome: { kind: "error" } })).toBe(reload);
  });
  it("back keeps the API's tier (no recomputation from rounded numbers)", () => {
    const s = analyzing();
    const back = (outcome: Parameters<typeof reducer>[1] & { type: "PREDICTED" }) =>
      reducer(reducer(reducer(s, outcome), { type: "CONFIRM_DISH", dish: "pizza" }), { type: "BACK_TO_RESULT" }).stage;
    // Rounded numbers that would look confident if recomputed: confidence == threshold, but the API said abstain / low.
    const preds = [{ dish: "pizza" as const, confidence: 0.6 }, { dish: "kebab" as const, confidence: 0.3 }, { dish: "hot_dog" as const, confidence: 0.1 }];
    expect(back({ type: "PREDICTED", seq: s.seq, outcome: { ...ok, tier: "abstain", predictions: [] } })).toBe("abstain");
    expect(back({ type: "PREDICTED", seq: s.seq, outcome: { ...ok, tier: "low", predictions: preds } })).toBe("low");
    expect(back({ type: "PREDICTED", seq: s.seq, outcome: { ...ok, tier: "high", predictions: preds } })).toBe("result");
  });
  it("browserStorage() swallows a throwing getter", () => {
    const desc = Object.getOwnPropertyDescriptor(window, "localStorage")!;
    Object.defineProperty(window, "localStorage", { configurable: true, get() { throw new DOMException("x", "SecurityError"); } });
    try {
      expect(browserStorage()).toBeUndefined();
      expect(loadLang(browserStorage())).toBe("en");
    } finally {
      Object.defineProperty(window, "localStorage", desc);
    }
  });
  it("back returns to the result, or to not-ready for a manual pick", () => {
    expect(reducer(confirmed("kebab"), { type: "BACK_TO_RESULT" }).stage).toBe("result");
    const s = analyzing();
    const nr = reducer(reducer(s, { type: "PREDICTED", seq: s.seq, outcome: { kind: "not-ready" } }), { type: "CONFIRM_DISH", dish: "pizza" });
    expect(reducer(nr, { type: "BACK_TO_RESULT" }).stage).toBe("not-ready");
  });
  it("a bad file never replaces the current photo", () => {
    const s = reducer(initialState, { type: "PHOTO_LOADED", photo: photo() });
    const r = reducer(s, { type: "FILE_REJECTED", code: "unsupported_format" });
    expect(r.photo?.url).toBe("blob:p1");
    expect(r.fileError).toBe("unsupported_format");
  });
});

describe("api client", () => {
  const res = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
  const signal = () => new AbortController().signal;

  it("sends exactly the given blob and parses a result", async () => {
    const blob = new Blob(["crop"], { type: "image/jpeg" });
    const f = vi.fn(async () => res(200, okBody));
    expect(await predict(blob, signal(), f)).toMatchObject({ kind: "ok", tier: "high", threshold: 0.6, highThreshold: 0.8, fallbackAvailable: false });
    const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/predict");
    expect(init.body).toBe(blob);
  });
  it.each([
    [503, { code: "MODEL_NOT_READY", detail: "no model" }, "not-ready"],
    [415, { code: "unsupported_format" }, "invalid"],
    [422, { code: "corrupt_image" }, "invalid"],
    [500, { detail: "boom" }, "server"],
    [503, { code: "OTHER" }, "server"],
    [503, { code: "SERVER_BUSY" }, "busy"],
    [200, { ...okBody, predictions: PREDS.slice(0, 2) }, "server"],
    [200, { ...okBody, predictions: [PREDS[1], PREDS[0], PREDS[2]] }, "server"],
    [200, { ...okBody, predictions: [{ class: "sushi", confidence: 0.9 }, PREDS[1], PREDS[2]] }, "server"],
    [200, { ...okBody, threshold: "0.6" }, "server"],
    [200, { ...okBody, tier: "maybe" }, "server"],
    [200, { ...okBody, high_threshold: 0.5 }, "server"],                           // high below the abstain threshold
    [200, { ...okBody, fallback_available: "yes" }, "server"],
    [200, { ...okBody, tier: "abstain" }, "server"],                               // abstain must not carry guesses
    [200, { ...okBody, tier: "non_food" }, "server"],
    [200, { ...okBody, predictions: [] }, "server"],                               // high needs the top 3
    [200, { ...okBody, tier: "abstain", predictions: [] }, "ok"],
    [200, { ...okBody, tier: "non_food", predictions: [], non_food_reason: "blank_image" }, "ok"],
    [200, { ...okBody, tier: "low" }, "ok"],
  ])("status %i %j -> %s", async (status, body, kind) => {
    expect((await predict(new Blob(["x"]), signal(), async () => res(status, body))).kind).toBe(kind);
  });
  it("network failure and abort", async () => {
    expect((await predict(new Blob(["x"]), signal(), async () => { throw new TypeError("offline"); })).kind).toBe("network");
    const c = new AbortController();
    c.abort();
    const f = async () => { throw new DOMException("aborted", "AbortError"); };
    expect((await predict(new Blob(["x"]), c.signal, f)).kind).toBe("aborted");
  });
  it("parsePrediction rejects duplicates and NaN", () => {
    expect(parsePrediction({ ...okBody, predictions: [PREDS[0], PREDS[0], PREDS[2]] })).toBeNull();
    expect(parsePrediction({ ...okBody, predictions: [{ class: "kebab", confidence: Number.NaN }, PREDS[1], PREDS[2]] })).toBeNull();
  });
  const ing = { dish: "kebab", variant: "skewered", name: "Kebab · Shish", ingredients: ["Meat"], guard: null,
    disclaimer: "Typical ingredients; not identified from your photo.", variant_note: "You choose the kind.",
    sources: [{ url: "https://en.wikipedia.org/wiki/Shish_kebab", title: "Shish kebab" }], translated: false };
  it("ingredients: grouped dishes need the user's kind; responses are checked", async () => {
    const f = vi.fn(async () => res(200, ing));
    expect((await fetchIngredients("kebab", null, "en", [], signal(), f)).kind).toBe("error");
    expect(f).not.toHaveBeenCalled();
    const r = await fetchIngredients("kebab", "skewered", "ko", [], signal(), f);
    expect(r.kind).toBe("ok");
    expect((f.mock.calls[0] as unknown as [string])[0]).toBe("/api/ingredients/kebab?lang=ko&variant=skewered");
    const bad = async () => res(200, { ...ing, sources: [{ url: "http://insecure", title: "x" }] });
    expect((await fetchIngredients("kebab", "skewered", "en", [], signal(), bad)).kind).toBe("error");
    const other = async () => res(200, { ...ing, variant: "doner_shawarma" });
    expect((await fetchIngredients("kebab", "skewered", "en", [], signal(), other)).kind).toBe("error");
  });
});

describe("crop math", () => {
  it("clamps, moves and resizes inside the image", () => {
    expect(clampRect({ x: -1, y: 2, w: 3, h: 0 })).toEqual({ x: 0, y: 1 - MIN_SIZE, w: 1, h: MIN_SIZE });
    const moved = moveRect(DEFAULT_RECT, 1, 1);
    expect([moved.x, moved.y, moved.w, moved.h].map((v) => +v.toFixed(9))).toEqual([0.1, 0.1, 0.9, 0.9]);
    const r = resizeCorner(DEFAULT_RECT, "nw", 2, 2);
    expect(r.w).toBeCloseTo(MIN_SIZE);
    expect(r.x + r.w).toBeCloseTo(0.95);
    expect(resizeCorner(DEFAULT_RECT, "se", 1, 1)).toEqual({ x: 0.05, y: 0.05, w: 0.95, h: 0.95 });
  });
  it("converts to pixels and limits the output size", () => {
    expect(toPixels({ x: 0.5, y: 0.5, w: 0.5, h: 0.5 }, 801, 601)).toEqual({ sx: 401, sy: 301, sw: 400, sh: 300 });
    expect(outputSize(4000, 3000)).toEqual({ width: 2048, height: 1536 });
    expect(outputSize(300, 200)).toEqual({ width: 300, height: 200 });
  });
});

describe("i18n", () => {
  it("English and Korean have the same keys, incl. every dish and kind", () => {
    expect(Object.keys(MESSAGES.ko).sort()).toEqual(Object.keys(MESSAGES.en).sort());
    for (const d of DISHES) expect(MESSAGES.en).toHaveProperty(`dish.${d}`);
    for (const [d, vs] of Object.entries(VARIANTS)) for (const v of vs ?? []) expect(MESSAGES.ko).toHaveProperty(`variant.${d}.${v}`);
    expect(translate("en", "result.ask", { dish: "Pizza" })).toBe("Is this Pizza?");
  });
  it("defaults to English and survives blocked storage", () => {
    expect(loadLang(undefined)).toBe("en");
    expect(loadLang({ getItem: () => "ko" })).toBe("ko");
    expect(loadLang({ getItem: () => "fr" })).toBe("en");
    expect(loadLang({ getItem: () => { throw new Error("blocked"); } })).toBe("en");
    expect(() => saveLang({ setItem: () => { throw new Error("blocked"); } }, "ko")).not.toThrow();
  });
});

describe("upload checks", () => {
  const bytes = (...b: number[]) => new Uint8Array([...b, ...new Array(16).fill(0)]);
  it("sniffs the real format", () => {
    expect(sniff(bytes(0xff, 0xd8, 0xff))).toBe("JPEG");
    expect(sniff(bytes(0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a))).toBe("PNG");
    expect(sniff(bytes(0x52, 0x49, 0x46, 0x46, 0, 0, 0, 0, 0x57, 0x45, 0x42, 0x50))).toBe("WEBP");
    expect(sniff(bytes(0x47, 0x49, 0x46))).toBeNull();
  });
  it("checks size and type", async () => {
    expect(await checkFile(new Blob([]))).toEqual({ ok: false, code: "empty_file" });
    expect(await checkFile(new Blob([new Uint8Array(10 * 1024 * 1024 + 1)]))).toEqual({ ok: false, code: "file_too_large" });
    expect(await checkFile(new Blob(["<html>"]))).toEqual({ ok: false, code: "unsupported_format" });
    expect(await checkFile(new Blob([bytes(0xff, 0xd8, 0xff)]))).toEqual({ ok: true, format: "JPEG" });
    expect(checkDimensions(9000, 10)).toBe("image_too_large");
    expect(checkDimensions(6000, 5000)).toBe("image_too_large");
    expect(checkDimensions(0, 10)).toBe("corrupt_image");
    expect(checkDimensions(4000, 3000)).toBeNull();
  });
});


const res2 = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const sig = () => new AbortController().signal;

describe("extra check client (fallback)", () => {
  it.each([
    [{ status: "used", verdict: "food", dish: "pizza" }, { kind: "used", verdict: "food", dish: "pizza" }],
    [{ status: "used", verdict: "food", dish: "other_food" }, { kind: "used", verdict: "food", dish: "other_food" }],
    [{ status: "used", verdict: "not_food", dish: null }, { kind: "used", verdict: "not_food", dish: null }],
    [{ status: "used", verdict: "unclear", dish: null }, { kind: "used", verdict: "unclear", dish: null }],
    [{ status: "unavailable", reason: "timeout" }, { kind: "unavailable", reason: "timeout" }],
    [{ status: "unavailable", reason: "<script>" }, { kind: "unavailable", reason: "provider_error" }],   // unknown reason -> generic
  ])("parses %j", (body, expected) => expect(parseFallback(body)).toEqual(expected));

  it.each([
    null, "x", {}, { status: "ok" }, { status: "used", verdict: "food", dish: null }, { status: "used", verdict: "not_food", dish: "pizza" },
    { status: "used", verdict: "food", dish: "sushi" }, { status: "used", verdict: "maybe", dish: null },
  ])("rejects %j", (body) => expect(parseFallback(body)).toBeNull());

  it("sends the blob and maps every failure to unavailable (the earlier result stays)", async () => {
    const blob = new Blob(["crop"], { type: "image/jpeg" });
    const f = vi.fn(async () => res2(200, { status: "used", verdict: "food", dish: "kebab" }));
    expect(await fallback(blob, sig(), f)).toEqual({ kind: "used", verdict: "food", dish: "kebab" });
    const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/fallback");
    expect(init.method).toBe("POST");
    expect(init.body).toBe(blob);
    const cases: [() => Promise<Response>, string][] = [
      [async () => { throw new TypeError("offline"); }, "network"],
      [async () => res2(500, { detail: "x" }), "server"],
      [async () => res2(415, { code: "unsupported_format" }), "invalid_image"],
      [async () => res2(200, { status: "used", verdict: "food", dish: null }), "bad_response"],
      [async () => new Response("not json", { status: 200 }), "bad_response"],
      [async () => res2(200, { status: "unavailable", reason: "rate_limited" }), "rate_limited"],
    ];
    for (const [impl, reason] of cases) expect(await fallback(blob, sig(), impl)).toEqual({ kind: "unavailable", reason });
    const c = new AbortController();
    c.abort();
    expect((await fallback(blob, c.signal, async () => { throw new DOMException("a", "AbortError"); })).kind).toBe("aborted");
  });
});

describe("dietary guard client", () => {
  const base = { dish: "pizza", variant: null, name: "Pizza", ingredients: ["Dough"], disclaimer: "Typical ingredients; not identified from your photo.",
    sources: [{ url: "https://en.wikipedia.org/wiki/Pizza", title: "Pizza" }], translated: false };
  const item = (over: object) => ({ id: "gluten", label: "Gluten", status: "warning", message: "m", note: null,
    matches: [{ ingredient: "Dough", kind: "contains", tags: ["gluten"] }], unverified: [], ...over });
  const withGuard = (restrictions: object[]) => ({ ...base, guard: { restrictions, basis: "basis" } });

  it("asks with the canonical, comma-separated list", async () => {
    const f = vi.fn(async () => res2(200, withGuard([item({ id: "halal", label: "H", status: "safe", matches: [] }), item({})])));
    const r = await fetchIngredients("pizza", null, "en", ["halal", "gluten"], sig(), f);
    expect(r.kind).toBe("ok");
    expect((f.mock.calls[0] as unknown as [string])[0]).toBe("/api/ingredients/pizza?lang=en&avoid=halal%2Cgluten");
    expect(r.kind === "ok" && r.data.guard?.restrictions.map((x) => x.status)).toEqual(["safe", "warning"]);
  });
  it.each([
    ["missing guard", base],
    ["wrong number of results", withGuard([])],
    ["wrong id", withGuard([item({ id: "nuts" })])],
    ["unknown status", withGuard([item({ status: "fine" })])],
    ["warning without a reason", withGuard([item({ matches: [] })])],
    ["safe with a match", withGuard([item({ status: "safe" })])],
    ["unknown without an unverified line", withGuard([item({ status: "unknown", matches: [] })])],
    ["bad kind", withGuard([item({ matches: [{ ingredient: "x", kind: "sure" }] })])],
  ])("asked for a check but got %s -> error (never a silent 'safe')", async (_, body) => {
    expect((await fetchIngredients("pizza", null, "en", ["gluten"], sig(), async () => res2(200, body))).kind).toBe("error");
  });
  it("unknown status with its unverified lines is accepted", async () => {
    const body = withGuard([item({ id: "nuts", label: "Nuts", status: "unknown", matches: [], unverified: [{ ingredient: "Toppings" }] })]);
    const r = await fetchIngredients("pizza", null, "en", ["nuts"], sig(), async () => res2(200, body));
    expect(r.kind === "ok" && r.data.guard?.restrictions[0].unverified).toEqual(["Toppings"]);
  });
  it("restriction ids: canonical order, junk dropped, storage failures swallowed", () => {
    expect(normalizeAvoid(["gluten", "x", "halal", "gluten", 5])).toEqual(["halal", "gluten"]);
    expect(RESTRICTIONS).toHaveLength(8);
    expect(loadAvoid(undefined)).toEqual([]);
    expect(loadAvoid({ getItem: () => "not json" })).toEqual([]);
    expect(loadAvoid({ getItem: () => '{"a":1}' })).toEqual([]);
    expect(loadAvoid({ getItem: () => '["nuts","evil","halal"]' })).toEqual(["halal", "nuts"]);
    expect(loadAvoid({ getItem: () => { throw new Error("blocked"); } })).toEqual([]);
    expect(() => saveAvoid({ setItem: () => { throw new Error("blocked"); } }, ["halal"])).not.toThrow();
  });
});

describe("evaluation client", () => {
  const cls = (dish: string, support = 150, small = false) => ({ class: dish, precision: 0.9, recall: 0.9, f1: 0.9, support, small_n: small });
  const body = { n: 806, accuracy: 0.935, macro_f1: 0.928, ci: { accuracy: [0.9, 0.95], macro_f1: [0.9, 0.94], subset_recall: null },
    per_class: ["dessert", "hamburger", "hot_dog", "kebab", "pizza"].map((d) => cls(d, d === "kebab" ? 56 : 150)),
    per_variant: [{ target: "kebab", variant: "minced_skewer", n: 13, recall: 0.77, small_n: true }],
    thresholds: { abstain_below: 0.462, high_from: 0.8 },
    tiers: { high: { n: 700, share: 0.87, accuracy: 0.97 }, low: { n: 94, share: 0.12, accuracy: 0.6 }, abstain: { n: 12, share: 0.015, accuracy: 0.4 } },
    limits: ["five_classes_only", "small_variant_test"] };
  it("parses a complete result and rejects malformed ones", () => {
    const e = parseEvaluation(body)!;
    expect(e.n).toBe(806);
    expect(e.perVariant[0]).toMatchObject({ variant: "minced_skewer", n: 13, smallN: true });
    expect(e.tiers?.low.n).toBe(94);
    expect(parseEvaluation({ ...body, tiers: null })?.tiers).toBeNull();
    for (const bad of [null, {}, { ...body, n: 0 }, { ...body, accuracy: 2 }, { ...body, per_class: body.per_class.slice(1) },
      { ...body, per_class: [...body.per_class.slice(1), cls("sushi")] }, { ...body, thresholds: {} }, { ...body, limits: [1] },
      { ...body, tiers: { high: body.tiers.high } }]) expect(parseEvaluation(bad)).toBeNull();
  });
  it("fetches /api/evaluation; failures are an error, not made-up numbers", async () => {
    const f = vi.fn(async () => res2(200, body));
    expect((await fetchEvaluation(sig(), f)).kind).toBe("ok");
    expect((f.mock.calls[0] as unknown as [string])[0]).toBe("/api/evaluation");
    expect((await fetchEvaluation(sig(), async () => res2(503, { code: "MODEL_NOT_READY" }))).kind).toBe("error");
    expect((await fetchEvaluation(sig(), async () => res2(200, { n: 1 }))).kind).toBe("error");
    expect((await fetchEvaluation(sig(), async () => { throw new TypeError("offline"); })).kind).toBe("error");
  });
});

describe("flow reducer: extra check and restrictions", () => {
  const shown = (tier: "high" | "low" | "abstain", fallbackAvailable = true) => {
    const s = analyzing();
    return reducer(s, { type: "PREDICTED", seq: s.seq, outcome: { ...ok, tier, predictions: tier === "abstain" ? [] : ok.predictions, fallbackAvailable } });
  };
  it("the extra check keeps the earlier result when it is unavailable", () => {
    for (const tier of ["high", "low", "abstain"] as const) {
      const s = shown(tier);
      const asked = reducer(s, { type: "FALLBACK_ASK" });
      expect(asked.fallback).toEqual({ status: "loading" });
      expect(asked.stage).toBe(s.stage);
      const failed = reducer(asked, { type: "FALLBACK_DONE", seq: asked.seq, outcome: { kind: "unavailable", reason: "timeout" } });
      expect(failed.fallback).toEqual({ status: "unavailable", reason: "timeout" });
      expect(failed.stage).toBe(s.stage);
      expect(failed.predictions).toBe(s.predictions);
      expect(failed.tier).toBe(tier);
    }
  });
  it("only one extra check at a time, and only from a shown result", () => {
    const s = shown("low");
    const asked = reducer(s, { type: "FALLBACK_ASK" });
    expect(reducer(asked, { type: "FALLBACK_ASK" })).toBe(asked);
    expect(reducer(analyzing(), { type: "FALLBACK_ASK" }).fallback.status).toBe("idle");
    expect(reducer(initialState, { type: "FALLBACK_ASK" })).toBe(initialState);
  });
  it("'not food' from the extra check shows the no-food screen; dismissing returns to the first result", () => {
    const s = reducer(shown("high"), { type: "FALLBACK_ASK" });
    const r = reducer(s, { type: "FALLBACK_DONE", seq: s.seq, outcome: { kind: "used", verdict: "not_food", dish: null } });
    expect(r.stage).toBe("non-food");
    expect(r.tier).toBe("high");
    const back = reducer(r, { type: "FALLBACK_DISMISS" });
    expect(back.stage).toBe("result");
    expect(reducer(back, { type: "CONFIRM_DISH", dish: "pizza" }).stage).toBe("ingredients");
    const again = reducer(reducer(back, { type: "CONFIRM_DISH", dish: "pizza" }), { type: "BACK_TO_RESULT" });
    expect(again.stage).toBe("result");                                           // dismissal is remembered
  });
  it("other verdicts never change the first result's screen", () => {
    for (const [verdict, dish] of [["food", "kebab"], ["food", "other_food"], ["unclear", null]] as const) {
      const s = reducer(shown("low"), { type: "FALLBACK_ASK" });
      const r = reducer(s, { type: "FALLBACK_DONE", seq: s.seq, outcome: { kind: "used", verdict, dish } });
      expect(r.stage).toBe("low");
      expect(r.fallback).toEqual({ status: "used", verdict, dish });
    }
  });
  it("a late answer for an older photo is ignored", () => {
    const s = reducer(shown("high"), { type: "FALLBACK_ASK" });
    const newer = reducer(s, { type: "EDIT_CROP" });
    expect(reducer(newer, { type: "FALLBACK_DONE", seq: s.seq, outcome: { kind: "used", verdict: "not_food", dish: null } })).toBe(newer);
    expect(newer.fallback.status).toBe("idle");
    expect(reducer(s, { type: "FALLBACK_DONE", seq: s.seq, outcome: { kind: "aborted" } })).toBe(s);
  });
  it("a blank-photo tier cannot be dismissed (the model, not the extra check, said so)", () => {
    const a = analyzing();
    const blank = reducer(a, { type: "PREDICTED", seq: a.seq, outcome: { ...ok, tier: "non_food", predictions: [], nonFoodReason: "blank_image" } });
    expect(blank.stage).toBe("non-food");
    expect(reducer(blank, { type: "FALLBACK_DISMISS" })).toBe(blank);
  });
  it("changing restrictions on the ingredient screen asks for a new answer; elsewhere it only remembers", () => {
    let s = reducer(shown("high"), { type: "CONFIRM_DISH", dish: "pizza" });
    const before = s.ingredientsSeq;
    s = reducer(s, { type: "SET_AVOID", avoid: ["halal"] });
    expect(s.avoid).toEqual(["halal"]);
    expect(s.ingredients).toBeNull();
    expect(s.ingredientsSeq).toBe(before + 1);
    expect(reducer(s, { type: "SET_AVOID", avoid: ["halal"] })).toBe(s);          // unchanged: nothing happens
    const on = shown("high");
    expect(reducer(on, { type: "SET_AVOID", avoid: ["nuts"] })).toMatchObject({ stage: "result", avoid: ["nuts"] });
    expect(reducer(reducer(s, { type: "RESET" }), { type: "PHOTO_LOADED", photo: photo("blob:z") }).avoid).toEqual(["halal"]);
  });
});
