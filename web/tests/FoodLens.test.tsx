// Component tests with mocked dependencies. The mocked predictions below are test fixtures only;
// they are not model results and must not be reported as such.
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { IngredientsOutcome, PredictOutcome } from "@/lib/api";
import FoodLens, { type Deps } from "@/components/FoodLens";

function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => { resolve = r; });
  return { promise, resolve };
}

const MOCK_OK: PredictOutcome = {
  kind: "ok", uncertain: false, threshold: 0.6,
  predictions: [{ dish: "kebab", confidence: 0.81 }, { dish: "pizza", confidence: 0.1 }, { dish: "hot_dog", confidence: 0.05 }],
};
const ingredients = (variant: string | null, item: string): IngredientsOutcome => ({
  kind: "ok", data: { dish: "kebab", variant, name: "Kebab", ingredients: [item],
    disclaimer: "Typical ingredients; not identified from your photo.", variantNote: "You choose the kind.",
    sources: [{ url: "https://en.wikipedia.org/wiki/Shish_kebab", title: "Shish kebab — Wikipedia" }], translated: false },
});

function setup() {
  const predicts: { blob: Blob; signal: AbortSignal; d: ReturnType<typeof deferred<PredictOutcome>> }[] = [];
  const ingredientCalls: { args: unknown[]; signal: AbortSignal; d: ReturnType<typeof deferred<IngredientsOutcome>> }[] = [];
  let cropN = 0;
  const deps: Deps = {
    api: {
      predict: vi.fn((blob: Blob, signal: AbortSignal) => {
        const d = deferred<PredictOutcome>();
        predicts.push({ blob, signal, d });
        return d.promise;
      }),
      fetchIngredients: vi.fn((dish, variant, lang, signal: AbortSignal) => {
        const d = deferred<IngredientsOutcome>();
        ingredientCalls.push({ args: [dish, variant, lang], signal, d });
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
  return { deps, predicts, ingredientCalls, view };
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
  it("1) Not sure stays Not sure after going back (API flag kept, not recomputed)", async () => {
    const { predicts, ingredientCalls } = setup();
    await upload();
    await analyze();
    // Rounded numbers that would look confident if recomputed: confidence == threshold, API says uncertain.
    await act(async () => predicts[0].d.resolve({ kind: "ok", uncertain: true, threshold: 0.6,
      predictions: [{ dish: "pizza", confidence: 0.6 }, { dish: "kebab", confidence: 0.3 }, { dish: "hot_dog", confidence: 0.1 }] }));
    expect(screen.getByText("Not sure")).toBeTruthy();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: /Pizza/ })); });
    expect(ingredientCalls).toHaveLength(1);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Back to results" })); });
    expect(screen.getByText("Not sure")).toBeTruthy();
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
