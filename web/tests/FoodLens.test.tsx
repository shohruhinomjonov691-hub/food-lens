// Component tests with mocked dependencies. The mocked predictions below are test fixtures only;
// they are not model results and must not be reported as such.
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { EvaluationOutcome, FallbackOutcome, IngredientsOutcome, PredictOutcome } from "@/lib/api";
import FoodLens, { type Deps } from "@/components/FoodLens";

function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => { resolve = r; });
  return { promise, resolve };
}

const MOCK_OK: PredictOutcome = {
  kind: "ok", tier: "high", threshold: 0.6, highThreshold: 0.8, nonFoodReason: null, fallbackAvailable: false,
  predictions: [{ dish: "kebab", confidence: 0.81 }, { dish: "pizza", confidence: 0.1 }, { dish: "hot_dog", confidence: 0.05 }],
};
const ingredients = (variant: string | null, item: string): IngredientsOutcome => ({
  kind: "ok", data: { dish: "kebab", variant, name: "Kebab", ingredients: [item],
    disclaimer: "Typical ingredients; not identified from your photo.", variantNote: "You choose the kind.",
    sources: [{ url: "https://en.wikipedia.org/wiki/Shish_kebab", title: "Shish kebab — Wikipedia" }], translated: false, guard: null },
});

function setup() {
  const predicts: { blob: Blob; signal: AbortSignal; d: ReturnType<typeof deferred<PredictOutcome>> }[] = [];
  const ingredientCalls: { args: unknown[]; avoid: unknown; signal: AbortSignal; d: ReturnType<typeof deferred<IngredientsOutcome>> }[] = [];
  const fallbackCalls: { blob: Blob; signal: AbortSignal; d: ReturnType<typeof deferred<FallbackOutcome>> }[] = [];
  const evalCalls: { signal: AbortSignal; d: ReturnType<typeof deferred<EvaluationOutcome>> }[] = [];
  let cropN = 0;
  const deps: Deps = {
    api: {
      predict: vi.fn((blob: Blob, signal: AbortSignal) => {
        const d = deferred<PredictOutcome>();
        predicts.push({ blob, signal, d });
        return d.promise;
      }),
      fetchIngredients: vi.fn((dish, variant, lang, avoid, signal: AbortSignal) => {
        const d = deferred<IngredientsOutcome>();
        ingredientCalls.push({ args: [dish, variant, lang], avoid, signal, d });
        return d.promise;
      }),
      fallback: vi.fn((blob: Blob, signal: AbortSignal) => {
        const d = deferred<FallbackOutcome>();
        fallbackCalls.push({ blob, signal, d });
        return d.promise;
      }),
      fetchEvaluation: vi.fn((signal: AbortSignal) => {
        const d = deferred<EvaluationOutcome>();
        evalCalls.push({ signal, d });
        return d.promise;
      }),
    } as unknown as Deps["api"],
    crop: {
      cropToBlob: vi.fn(async () => new Blob([`crop-${++cropN}`], { type: "image/jpeg" })),
      rotateBlob: vi.fn(async () => new Blob(["rotated"], { type: "image/png" })),
    },
    loadImage: vi.fn(async () => ({ naturalWidth: 800, naturalHeight: 600 }) as HTMLImageElement),
  };
  const view = render(<FoodLens deps={deps} />);
  return { deps, predicts, ingredientCalls, fallbackCalls, evalCalls, view };
}

const jpeg = (name = "a.jpg") => new File([new Uint8Array([0xff, 0xd8, 0xff, 0xe0, ...new Array(64).fill(1)])], name, { type: "image/jpeg" });

// FileReader (used to sniff the first bytes) finishes on a macrotask in jsdom.
const flush = () => act(() => new Promise((r) => setTimeout(r, 10)));

async function upload(file: File = jpeg()) {
  await act(async () => {
    fireEvent.change(screen.getByTestId("file-input"), { target: { files: [file] } });
  });
  await flush();
  await flush();
}
async function analyze() {
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Analyze" })); });
}

describe("FoodLens flow (mocked API)", () => {
  it("sends exactly the confirmed crop and shows the top-3", async () => {
    const { deps, predicts } = setup();
    expect(screen.getByText("No photo yet")).toBeTruthy();
    await upload();
    expect(screen.getByText("Crop to the dish")).toBeTruthy();
    await analyze();
    const sentCrop = await (deps.crop.cropToBlob as ReturnType<typeof vi.fn>).mock.results[0].value;
    expect(predicts).toHaveLength(1);
    expect(predicts[0].blob).toBe(sentCrop);                          // the very blob that was confirmed
    expect(screen.getByText("Analyzing…")).toBeTruthy();
    await act(async () => predicts[0].d.resolve(MOCK_OK));
    expect(screen.getByText("Top matches")).toBeTruthy();
    expect(screen.getByText("81%")).toBeTruthy();
    expect(screen.getByText("Is this Kebab?")).toBeTruthy();
  });

  it("kebab: no kind is preselected; ingredients only after the user's choice", async () => {
    const { predicts, ingredientCalls } = setup();
    await upload();
    await analyze();
    await act(async () => predicts[0].d.resolve(MOCK_OK));
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Yes, show ingredients" })); });
    const radios = screen.getAllByRole("radio") as HTMLInputElement[];
    expect(radios).toHaveLength(3);
    expect(radios.every((r) => !r.checked)).toBe(true);
    const show = screen.getByRole("button", { name: "Show ingredients" }) as HTMLButtonElement;
    expect(show.disabled).toBe(true);
    expect(ingredientCalls).toHaveLength(0);
    await act(async () => { fireEvent.click(screen.getByRole("radio", { name: "Döner / shawarma" })); });
    expect(ingredientCalls).toHaveLength(0);                           // choosing is not confirming
    await act(async () => { fireEvent.click(show); });
    expect(ingredientCalls[0].args).toEqual(["kebab", "doner_shawarma", "en"]);
    await act(async () => ingredientCalls[0].d.resolve(ingredients("doner_shawarma", "Thin slices")));
    expect(screen.getByTestId("disclaimer").textContent).toContain("not identified from your photo");
    expect(screen.getByRole("link", { name: "Shish kebab — Wikipedia" }).getAttribute("href")).toMatch(/^https:/);
  });

  it("a new photo aborts the old request and its late answer is ignored", async () => {
    const { predicts } = setup();
    await upload();
    await analyze();
    await upload(jpeg("b.jpg"));                                       // user changes the photo
    expect(predicts[0].signal.aborted).toBe(true);
    await act(async () => predicts[0].d.resolve(MOCK_OK));             // the old answer arrives late
    expect(screen.queryByText("Top matches")).toBeNull();
    expect(screen.getByText("Crop to the dish")).toBeTruthy();
  });

  it("editing the crop during analysis aborts and ignores the old answer", async () => {
    const { predicts } = setup();
    await upload();
    await analyze();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Edit crop" })); });
    expect(predicts[0].signal.aborted).toBe(true);
    await act(async () => predicts[0].d.resolve(MOCK_OK));
    expect(screen.queryByText("Top matches")).toBeNull();
    await analyze();
    await act(async () => predicts[1].d.resolve({ kind: "not-ready" }));
    expect(screen.getByText("The recognizer is not ready yet")).toBeTruthy();
  });

  it("an old ingredient answer cannot overwrite the newly chosen kind", async () => {
    const { predicts, ingredientCalls } = setup();
    await upload();
    await analyze();
    await act(async () => predicts[0].d.resolve(MOCK_OK));
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Yes, show ingredients" })); });
    await act(async () => { fireEvent.click(screen.getByRole("radio", { name: "Shish / shashlik" })); });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Show ingredients" })); });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Change kind" })); });
    expect(ingredientCalls[0].signal.aborted).toBe(true);
    await act(async () => { fireEvent.click(screen.getByRole("radio", { name: "Adana / koobideh" })); });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Show ingredients" })); });
    await act(async () => ingredientCalls[1].d.resolve(ingredients("minced_skewer", "Minced lamb")));
    await act(async () => ingredientCalls[0].d.resolve(ingredients("skewered", "Cubes of meat")));   // late, old
    expect(screen.getByText("Minced lamb")).toBeTruthy();
    expect(screen.queryByText("Cubes of meat")).toBeNull();
  });

  it("MODEL_NOT_READY shows a clear state and still allows picking a dish", async () => {
    const { predicts, ingredientCalls } = setup();
    await upload();
    await analyze();
    await act(async () => predicts[0].d.resolve({ kind: "not-ready" }));
    expect(screen.getByText("The recognizer is not ready yet")).toBeTruthy();
    expect(screen.queryByText("Top matches")).toBeNull();
    expect(screen.queryByText(/%$/)).toBeNull();                       // no confidence numbers at all
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: /Pizza/ })); });
    expect(ingredientCalls[0].args).toEqual(["pizza", null, "en"]);
  });

  it("network and server errors offer a retry with the same crop", async () => {
    const { predicts } = setup();
    await upload();
    await analyze();
    await act(async () => predicts[0].d.resolve({ kind: "network" }));
    expect(screen.getByText("No connection")).toBeTruthy();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Try again" })); });
    expect(predicts).toHaveLength(2);
    await act(async () => predicts[1].d.resolve({ kind: "server", status: 500 }));
    expect(screen.getByText("Something went wrong")).toBeTruthy();
  });

  it("rejects a non-image file before uploading anything", async () => {
    const { predicts, deps } = setup();
    await upload(new File(["<html>"], "x.jpg", { type: "image/jpeg" }));
    expect(screen.getByRole("alert").textContent).toContain("Please choose a JPG, PNG or WebP image.");
    expect(deps.loadImage).not.toHaveBeenCalled();
    expect(predicts).toHaveLength(0);
  });

  it("rejects an image that cannot be decoded", async () => {
    const { deps } = setup();
    (deps.loadImage as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error("decode"));
    await upload();
    expect(screen.getByRole("alert").textContent).toContain("could not be opened");
  });

  it("revokes object URLs that are no longer shown, and all on unmount", async () => {
    const { predicts, view } = setup();
    const create = URL.createObjectURL as ReturnType<typeof vi.fn>;
    const revoke = URL.revokeObjectURL as ReturnType<typeof vi.fn>;
    create.mockClear();
    revoke.mockClear();
    await upload();
    const first = create.mock.results[0].value as string;
    await analyze();
    const cropUrl = create.mock.results[1].value as string;
    await act(async () => predicts[0].d.resolve(MOCK_OK));
    await upload(jpeg("b.jpg"));
    expect(revoke).toHaveBeenCalledWith(first);
    expect(revoke).toHaveBeenCalledWith(cropUrl);
    const second = create.mock.results[2].value as string;
    view.unmount();
    expect(revoke).toHaveBeenCalledWith(second);
    expect(new Set(revoke.mock.calls.map((c) => c[0]))).toEqual(new Set(create.mock.results.map((r) => r.value)));
  });

  it("English by default; Korean choice is saved and restored", async () => {
    const first = setup();
    expect(screen.getByText("Add a food photo")).toBeTruthy();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "한국어" })); });
    expect(screen.getByText("음식 사진 추가")).toBeTruthy();
    expect(window.localStorage.getItem("fl.lang")).toBe("ko");
    first.view.unmount();
    await act(async () => { render(<FoodLens deps={first.deps} />); });
    expect(screen.getByText("음식 사진 추가")).toBeTruthy();
    expect(document.documentElement.lang).toBe("ko");
  });

  it("changing the language reloads ingredients in that language", async () => {
    const { predicts, ingredientCalls } = setup();
    await upload();
    await analyze();
    await act(async () => predicts[0].d.resolve({ kind: "not-ready" }));
    await act(async () => { fireEvent.click(within(screen.getAllByRole("group")[0]).getByRole("button", { name: "한국어" })); });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: /피자/ })); });
    expect(ingredientCalls.at(-1)?.args).toEqual(["pizza", null, "ko"]);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "EN" })); });
    expect(ingredientCalls.at(-1)?.args).toEqual(["pizza", null, "en"]);
    expect(ingredientCalls.at(-2)?.signal.aborted).toBe(true);
  });
});

describe("FoodLens: feedback for a bad file after a photo was analyzed (browser finding)", () => {
  it("shows the file error next to the analyzed crop and keeps the result", async () => {
    const { predicts } = setup();
    await upload();
    await analyze();
    await act(async () => predicts[0].d.resolve(MOCK_OK));
    await upload(new File(["<html>"], "x.jpg", { type: "image/jpeg" }));
    expect(screen.getByRole("alert").textContent).toContain("Please choose a JPG, PNG or WebP image.");
    expect(screen.getByText("Top matches")).toBeTruthy();
    expect(screen.getAllByText("Cropped photo sent for analysis")).toHaveLength(1);
  });
});


// Regressions for the Codex review of develop@6598c7a.
describe("review fixes", () => {
  it("1) Not sure stays Not sure after going back (API tier kept, not recomputed)", async () => {
    const { predicts, ingredientCalls } = setup();
    await upload();
    await analyze();
    await act(async () => predicts[0].d.resolve({ ...MOCK_OK, tier: "abstain", predictions: [] }));
    expect(screen.getByTestId("tier-badge").getAttribute("data-tier")).toBe("abstain");
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: /Pizza/ })); });
    expect(ingredientCalls).toHaveLength(1);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Back to results" })); });
    expect(screen.getByTestId("tier-badge").getAttribute("data-tier")).toBe("abstain");
    expect(screen.queryByText("Top matches")).toBeNull();
  });

  it("2) a throwing localStorage getter: English page, language switch still works", async () => {
    const desc = Object.getOwnPropertyDescriptor(window, "localStorage")!;
    Object.defineProperty(window, "localStorage", { configurable: true,
      get() { throw new DOMException("blocked", "SecurityError"); } });
    try {
      setup();
      expect(screen.getByText("Add a food photo")).toBeTruthy();
      await act(async () => { fireEvent.click(screen.getByRole("button", { name: "한국어" })); });
      expect(screen.getByText("음식 사진 추가")).toBeTruthy();
    } finally {
      Object.defineProperty(window, "localStorage", desc);
    }
  });

  it("3) a crop export that finishes after unmount creates no object URL", async () => {
    const { deps, view } = setup();
    await upload();
    const late = deferred<Blob>();
    (deps.crop.cropToBlob as ReturnType<typeof vi.fn>).mockReturnValueOnce(late.promise);
    const create = URL.createObjectURL as ReturnType<typeof vi.fn>;
    const revoke = URL.revokeObjectURL as ReturnType<typeof vi.fn>;
    fireEvent.click(screen.getByRole("button", { name: "Analyze" }));
    const before = create.mock.calls.length;
    view.unmount();
    await act(async () => late.resolve(new Blob(["late"], { type: "image/jpeg" })));
    await flush();
    expect(create.mock.calls.length).toBe(before);                       // no URL after unmount
    const made = new Set(create.mock.results.map((r) => r.value));
    for (const url of made) expect(revoke).toHaveBeenCalledWith(url);   // nothing left behind
  });

  it("3) an upload that finishes decoding after unmount revokes its URL", async () => {
    const { deps, view } = setup();
    const late = deferred<HTMLImageElement>();
    (deps.loadImage as ReturnType<typeof vi.fn>).mockReturnValueOnce(late.promise);
    const create = URL.createObjectURL as ReturnType<typeof vi.fn>;
    const revoke = URL.revokeObjectURL as ReturnType<typeof vi.fn>;
    create.mockClear();
    revoke.mockClear();
    await upload();                                                      // waits in loadImage
    view.unmount();
    await act(async () => late.resolve({ naturalWidth: 800, naturalHeight: 600 } as HTMLImageElement));
    await flush();
    const made = create.mock.results.map((r) => r.value);
    expect(made.length).toBeLessThanOrEqual(1);
    for (const url of made) expect(revoke).toHaveBeenCalledWith(url);
  });

  it("4) the kind is a native radio group: one name, nothing checked, labels select", async () => {
    const { predicts } = setup();
    await upload();
    await analyze();
    await act(async () => predicts[0].d.resolve(MOCK_OK));
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Yes, show ingredients" })); });
    const radios = screen.getAllByRole("radio") as HTMLInputElement[];
    expect(radios.every((r) => r.tagName === "INPUT" && r.type === "radio")).toBe(true);
    expect(new Set(radios.map((r) => r.name)).size).toBe(1);             // one group: arrow keys move within it
    expect(radios.some((r) => r.checked)).toBe(false);
    expect(radios.every((r) => r.tabIndex === 0)).toBe(true);            // browser does the roving focus
    await act(async () => { fireEvent.click(screen.getByText("Adana / koobideh")); });   // the visible label
    expect((screen.getByRole("radio", { name: "Adana / koobideh" }) as HTMLInputElement).checked).toBe(true);
    expect((screen.getByRole("button", { name: "Show ingredients" }) as HTMLButtonElement).disabled).toBe(false);
  });
});


// ---------- result tiers, extra check, dietary guard, evaluation ----------
const pred = (over: Partial<Extract<PredictOutcome, { kind: "ok" }>>): PredictOutcome => ({ ...(MOCK_OK as Extract<PredictOutcome, { kind: "ok" }>), ...over });
const LOW_PREDS = [{ dish: "pizza" as const, confidence: 0.55 }, { dish: "kebab" as const, confidence: 0.25 }, { dish: "hot_dog" as const, confidence: 0.1 }];
const tierOf = () => screen.getByTestId("tier-badge").getAttribute("data-tier");

async function reach(outcome: PredictOutcome) {
  const s = setup();
  await upload();
  await analyze();
  await act(async () => s.predicts[0].d.resolve(outcome));
  return s;
}
const click = (name: string | RegExp, role = "button") => act(async () => { fireEvent.click(screen.getByRole(role, { name })); });

describe("result tiers", () => {
  it("High / Confident: main dish and percentage", async () => {
    await reach(MOCK_OK);
    expect(tierOf()).toBe("high");
    expect(screen.getByText("Confident match")).toBeTruthy();
    expect(screen.getByText("Is this Kebab?")).toBeTruthy();
    expect(screen.getByText("81%")).toBeTruthy();
  });

  it("Low Confidence / Uncertain: warns, shows the top 3 as unconfirmed guesses, no 'Is this …?' winner", async () => {
    await reach(pred({ tier: "low", predictions: LOW_PREDS }));
    expect(tierOf()).toBe("low");
    expect(screen.getByText("Low confidence — not confirmed")).toBeTruthy();
    expect(screen.getByText("Top 3 guesses (unconfirmed)")).toBeTruthy();
    expect(screen.getAllByRole("listitem").filter((li) => li.classList.contains("match"))).toHaveLength(3);
    expect(screen.getByText("55%")).toBeTruthy();
    expect(screen.queryByText(/^Is this/)).toBeNull();
    expect(document.querySelector(".match.top")).toBeNull();
  });

  it("Not Sure / Abstain: no guess, no percentage, no dish list from the model; the user can still pick", async () => {
    const { ingredientCalls } = await reach(pred({ tier: "abstain", predictions: [] }));
    expect(tierOf()).toBe("abstain");
    expect(screen.getByText("No guess for this photo")).toBeTruthy();
    expect(screen.queryByText(/%$/)).toBeNull();
    expect(document.querySelector(".match")).toBeNull();
    await click(/Pizza/);
    expect(ingredientCalls[0].args).toEqual(["pizza", null, "en"]);
  });

  it("Non-Food / Invalid: its own warning state, with no dish picker and no numbers", async () => {
    await reach(pred({ tier: "non_food", predictions: [], nonFoodReason: "blank_image" }));
    expect(tierOf()).toBe("non_food");
    expect(screen.getByText("This doesn’t look like food")).toBeTruthy();
    expect(screen.getByText(/blank or one flat color/)).toBeTruthy();
    expect(screen.queryByText(/%$/)).toBeNull();
    expect(screen.queryByRole("button", { name: /Pizza/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Show the first result anyway" })).toBeNull();
  });

  it("server busy is its own message with a retry", async () => {
    const s = setup();
    await upload();
    await analyze();
    await act(async () => s.predicts[0].d.resolve({ kind: "busy" }));
    expect(screen.getByText("Busy right now")).toBeTruthy();
    await click("Try again");
    expect(s.predicts).toHaveLength(2);
  });

  it("the tier labels are translated", async () => {
    await reach(pred({ tier: "abstain", predictions: [] }));
    await click("한국어");
    expect(screen.getByText("확실하지 않음")).toBeTruthy();
    expect(screen.getByText("이 사진은 추측하지 않아요")).toBeTruthy();
  });
});

describe("extra check (vision fallback)", () => {
  it("shows the privacy notice and only enables the extra check when configured", async () => {
    const off = await reach(MOCK_OK);
    const disabled = screen.getByRole<HTMLButtonElement>("button", { name: "Run extra check" });
    expect(disabled.disabled).toBe(true);
    expect(screen.getByTestId("fallback-unavailable").textContent).toContain("It is not set up on this server.");
    expect(screen.getByText(/sends this cropped photo to Anthropic/)).toBeTruthy();
    expect(screen.getByText("Confident match")).toBeTruthy();
    await click("Run extra check");
    expect(off.fallbackCalls).toHaveLength(0);
    document.body.innerHTML = "";
    const on = await reach(pred({ tier: "low", predictions: LOW_PREDS, fallbackAvailable: true }));
    expect(screen.getByRole<HTMLButtonElement>("button", { name: "Run extra check" }).disabled).toBe(false);
    expect(screen.getByText(/sends this cropped photo to Anthropic/)).toBeTruthy();   // the privacy cost is stated up front
    expect(on.fallbackCalls).toHaveLength(0);
  });

  it("Fallback Used: shows the suggestion, says if it agrees, and the user can adopt it", async () => {
    const { fallbackCalls, ingredientCalls, deps, predicts } = await reach(pred({ tier: "low", predictions: LOW_PREDS, fallbackAvailable: true }));
    await click("Run extra check");
    expect(screen.getByText("Running the extra check…")).toBeTruthy();
    expect(fallbackCalls).toHaveLength(1);
    const sent = await (deps.crop.cropToBlob as ReturnType<typeof vi.fn>).mock.results[0].value;
    expect(fallbackCalls[0].blob).toBe(sent);                                    // the same confirmed crop
    expect(predicts).toHaveLength(1);
    await act(async () => fallbackCalls[0].d.resolve({ kind: "used", verdict: "food", dish: "pizza" }));
    expect(screen.getByText("Extra check used")).toBeTruthy();
    expect(screen.getByText(/Suggests: Pizza/).textContent).toContain("It agrees with the first result.");
    expect(tierOf()).toBe("low");                                                // the first result is not replaced
    await click("Use Pizza");
    expect(ingredientCalls[0].args).toEqual(["pizza", null, "en"]);
  });

  it("says when the extra check disagrees, finds another food, or cannot tell", async () => {
    const { fallbackCalls } = await reach(pred({ tier: "low", predictions: LOW_PREDS, fallbackAvailable: true }));
    await click("Run extra check");
    await act(async () => fallbackCalls[0].d.resolve({ kind: "used", verdict: "food", dish: "kebab" }));
    expect(screen.getByText(/Suggests: Kebab/).textContent).toContain("It differs from the first result.");
    document.body.innerHTML = "";
    const b = await reach(pred({ tier: "abstain", predictions: [], fallbackAvailable: true }));
    await click("Run extra check");
    await act(async () => b.fallbackCalls[0].d.resolve({ kind: "used", verdict: "food", dish: "other_food" }));
    expect(screen.getByText(/not one of the 5 dishes/)).toBeTruthy();
    document.body.innerHTML = "";
    const c = await reach(pred({ tier: "abstain", predictions: [], fallbackAvailable: true }));
    await click("Run extra check");
    await act(async () => c.fallbackCalls[0].d.resolve({ kind: "used", verdict: "unclear", dish: null }));
    expect(screen.getByText("The extra check could not tell what this is.")).toBeTruthy();
  });

  it("Fallback Unavailable / Error: the earlier result stays and the reason is shown (timeout, rate limit, network)", async () => {
    const { fallbackCalls } = await reach(pred({ tier: "low", predictions: LOW_PREDS, fallbackAvailable: true }));
    await click("Run extra check");
    await act(async () => fallbackCalls[0].d.resolve({ kind: "unavailable", reason: "timeout" }));
    expect(screen.getByTestId("fallback-unavailable").textContent).toContain("It took too long to answer.");
    expect(screen.getByTestId("fallback-unavailable").textContent).toContain("Your earlier result is unchanged.");
    expect(tierOf()).toBe("low");
    expect(screen.getByText("Top 3 guesses (unconfirmed)")).toBeTruthy();       // guesses still on screen
    expect(screen.getByText("55%")).toBeTruthy();
    await click("Try the extra check again");
    expect(fallbackCalls).toHaveLength(2);
    await act(async () => fallbackCalls[1].d.resolve({ kind: "unavailable", reason: "rate_limited" }));
    expect(screen.getByTestId("fallback-unavailable").textContent).toContain("Too many extra checks");
    await click("Try the extra check again");
    await act(async () => fallbackCalls[2].d.resolve({ kind: "unavailable", reason: "network" }));
    expect(screen.getByTestId("fallback-unavailable").textContent).toContain("could not be reached");
  });

  it("'not food' from the extra check opens the Non-Food state and can go back to the first result", async () => {
    const { fallbackCalls } = await reach(pred({ fallbackAvailable: true }));    // a confident result that is actually not food
    await click("Run extra check");
    await act(async () => fallbackCalls[0].d.resolve({ kind: "used", verdict: "not_food", dish: null }));
    expect(tierOf()).toBe("non_food");
    expect(screen.getByText(/The extra check says this photo doesn’t show food/)).toBeTruthy();
    await click("Show the first result anyway");
    expect(tierOf()).toBe("high");
    expect(screen.getByText("81%")).toBeTruthy();
  });

  it("a new photo aborts the pending extra check and ignores its late answer", async () => {
    const { fallbackCalls } = await reach(pred({ fallbackAvailable: true }));
    await click("Run extra check");
    await upload(jpeg("b.jpg"));
    expect(fallbackCalls[0].signal.aborted).toBe(true);
    await act(async () => fallbackCalls[0].d.resolve({ kind: "used", verdict: "not_food", dish: null }));
    expect(screen.getByText("Crop to the dish")).toBeTruthy();
    expect(screen.queryByText("This doesn’t look like food")).toBeNull();
  });
});

describe("allergen & dietary guard", () => {
  const guardData = (avoid: string[]): IngredientsOutcome => ({
    kind: "ok", data: {
      dish: "pizza", variant: null, name: "Pizza", ingredients: ["Leavened wheat-based dough", "Other toppings, which vary"],
      disclaimer: "Typical ingredients; not identified from your photo.", variantNote: null, translated: false,
      sources: [{ url: "https://en.wikipedia.org/wiki/Pizza", title: "Pizza — Wikipedia" }],
      guard: avoid.length === 0 ? null : { basis: "Derived from the typical-ingredient text.", restrictions: avoid.map((id) => {
        if (id === "gluten") return { id, label: "Gluten", status: "warning", message: "A typical ingredient may match.", note: null,
          matches: [{ ingredient: "Leavened wheat-based dough", kind: "contains" }], unverified: [] };
        if (id === "nuts") return { id, label: "Nuts", status: "unknown", message: "Not verified: check.", note: null,
          matches: [], unverified: ["Other toppings, which vary"] };
        return { id, label: "Sesame", status: "safe", message: "No listed typical ingredient matches.", note: null, matches: [], unverified: [] };
      }) as never },
    },
  });
  async function toIngredients() {
    const s = await reach(pred({ tier: "abstain", predictions: [] }));
    await click(/Pizza/);
    return s;
  }

  it("asks for nothing extra until a restriction is chosen, then shows all three states with the reason", async () => {
    const { ingredientCalls } = await toIngredients();
    expect(ingredientCalls[0].avoid).toEqual([]);
    await act(async () => ingredientCalls[0].d.resolve(guardData([])));
    expect(screen.getByText("Select a restriction to check this dish against it.")).toBeTruthy();
    expect(screen.queryByTestId("guard-gluten")).toBeNull();

    await click("Gluten", "checkbox");
    expect(ingredientCalls[1].avoid).toEqual(["gluten"]);
    expect(ingredientCalls[0].signal.aborted).toBe(true);
    await click("Nuts", "checkbox");
    await click("Sesame", "checkbox");
    expect(ingredientCalls.at(-1)?.avoid).toEqual(["nuts", "gluten", "sesame"].sort((a, b) => ["halal", "nuts", "gluten", "dairy", "egg", "soy", "sesame"].indexOf(a) - ["halal", "nuts", "gluten", "dairy", "egg", "soy", "sesame"].indexOf(b)));
    await act(async () => ingredientCalls.at(-1)!.d.resolve(guardData(["nuts", "gluten", "sesame"])));

    const gluten = screen.getByTestId("guard-gluten");
    expect(gluten.getAttribute("data-status")).toBe("warning");
    expect(gluten.textContent).toContain("Warning / Potential Match");
    expect(gluten.textContent).toContain("Leavened wheat-based dough");        // which ingredient caused it
    expect(gluten.textContent).toContain("typically contains");
    const nuts = screen.getByTestId("guard-nuts");
    expect(nuts.getAttribute("data-status")).toBe("unknown");
    expect(nuts.textContent).toContain("Unknown / Unverified");
    expect(nuts.textContent).toContain("Other toppings, which vary");
    const sesame = screen.getByTestId("guard-sesame");
    expect(sesame.getAttribute("data-status")).toBe("safe");
    expect(sesame.textContent).toContain("Safe / No Match");
    expect(sesame.textContent).toContain("No listed typical ingredient matches.");   // the reminder text accompanies "safe"
    expect(screen.getByText("Derived from the typical-ingredient text.")).toBeTruthy();
    expect(screen.getByTestId("disclaimer").textContent).toContain("not identified from your photo");
  });

  it("the choice is saved on this device and restored", async () => {
    const { ingredientCalls, view } = await toIngredients();
    await act(async () => ingredientCalls[0].d.resolve(guardData([])));
    await click("Gluten", "checkbox");
    expect(JSON.parse(window.localStorage.getItem("fl.avoid")!)).toEqual(["gluten"]);
    view.unmount();
    const again = setup();
    await upload();
    await analyze();
    await act(async () => again.predicts[0].d.resolve(pred({ tier: "abstain", predictions: [] })));
    await click(/Pizza/);
    expect(again.ingredientCalls[0].avoid).toEqual(["gluten"]);
    expect((screen.getByRole("checkbox", { name: "Gluten" }) as HTMLInputElement).checked).toBe(true);
  });

  it("a failed check is an error with a retry, not a silent 'safe'", async () => {
    const { ingredientCalls } = await toIngredients();
    await act(async () => ingredientCalls[0].d.resolve(guardData([])));
    await click("Nuts", "checkbox");
    await act(async () => ingredientCalls[1].d.resolve({ kind: "error" }));
    expect(screen.getByText("Ingredients could not be loaded. Please try again.")).toBeTruthy();
    expect(screen.queryByTestId("guard-nuts")).toBeNull();
    expect(screen.queryByText("Safe / No Match")).toBeNull();
  });

  it("works in Korean", async () => {
    const { ingredientCalls } = await toIngredients();
    await click("한국어");
    await act(async () => ingredientCalls.at(-1)!.d.resolve(guardData([])));
    expect(screen.getByRole("checkbox", { name: "할랄 / 돼지고기 제외" })).toBeTruthy();
    expect(screen.getByText("내 제한 사항으로 확인")).toBeTruthy();
  });
});

describe("evaluation / how reliable is this", () => {
  const evalOk: EvaluationOutcome = {
    kind: "ok", data: {
      n: 806, accuracy: 0.935, macroF1: 0.928, ci: { accuracy: [0.918, 0.953], macroF1: [0.907, 0.947] },
      perClass: [
        { dish: "dessert", precision: 0.936, recall: 0.977, f1: 0.956, support: 300, smallN: false },
        { dish: "hamburger", precision: 0.951, recall: 0.913, f1: 0.932, support: 150, smallN: false },
        { dish: "hot_dog", precision: 0.892, recall: 0.88, f1: 0.886, support: 150, smallN: false },
        { dish: "kebab", precision: 0.926, recall: 0.893, f1: 0.909, support: 56, smallN: false },
        { dish: "pizza", precision: 0.966, recall: 0.947, f1: 0.956, support: 150, smallN: false },
      ],
      perVariant: [
        { target: "kebab", variant: "minced_skewer", n: 13, recall: 0.769, smallN: true },
        { target: "kebab", variant: "doner_shawarma", n: 9, recall: 0.889, smallN: true },
        { target: "pizza", variant: "pizza", n: 150, recall: 0.947, smallN: false },     // not a user-chosen kind: not listed
      ],
      abstainBelow: 0.462, highFrom: 0.8,
      tiers: { high: { n: 700, share: 0.868, accuracy: 0.97 }, low: { n: 94, share: 0.117, accuracy: 0.6 }, abstain: { n: 12, share: 0.015, accuracy: 0.4 } },
      limits: ["five_classes_only", "non_food_not_evaluated", "small_variant_test"],
    },
  };
  const open = () => act(async () => {
    const d = document.querySelector("details")!;
    d.open = true;
    fireEvent(d, new Event("toggle"));
  });

  it("is fetched only when opened, and shows the numbers it was given, small samples and limits", async () => {
    const { evalCalls } = setup();
    expect(evalCalls).toHaveLength(0);
    await open();
    expect(evalCalls).toHaveLength(1);
    expect(screen.getByText("Loading test results…")).toBeTruthy();
    await act(async () => evalCalls[0].d.resolve(evalOk));
    const ev = screen.getByTestId("evaluation");
    expect(ev.textContent).toContain("806 held-out test photos");
    expect(ev.textContent).toContain("93.5%");
    expect(ev.textContent).toContain("92.8%");
    expect(screen.getByTestId("eval-class-kebab").textContent).toContain("56");
    expect(screen.getByTestId("eval-variant-minced_skewer").textContent).toContain("13 · few photos — not a reliable estimate");
    expect(screen.getByTestId("eval-variant-doner_shawarma").textContent).toContain("9 · few photos");
    expect(screen.queryByTestId("eval-variant-pizza")).toBeNull();
    expect(screen.getByTestId("eval-tier-high").textContent).toContain("86.8%");
    expect(screen.getByTestId("eval-tier-abstain").textContent).toContain("12");
    expect(ev.textContent).toContain("at least 80%");                           // boundaries come from the API
    expect(ev.textContent).toContain("below 46%");
    expect(ev.textContent).toContain("Non-food photos were not part of the test");
    expect(ev.textContent).toContain("Some kebab kinds have very few test photos");
    expect(ev.textContent).toContain("were not tuned on the test photos");
  });

  it("an error shows a message (never made-up numbers) and re-opening retries", async () => {
    const { evalCalls } = setup();
    await open();
    await act(async () => evalCalls[0].d.resolve({ kind: "error" }));
    expect(screen.getByText("Test results are not available right now.")).toBeTruthy();
    expect(screen.queryByTestId("evaluation")).toBeNull();
    await open();
    expect(evalCalls).toHaveLength(2);
    await act(async () => evalCalls[1].d.resolve(evalOk));
    expect(screen.getByTestId("evaluation")).toBeTruthy();
  });
});
