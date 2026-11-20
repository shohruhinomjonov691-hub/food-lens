// The whole user flow as a pure reducer. Every new photo, crop change and analysis gets a new
// sequence number; a response carries the number of the request that produced it and is ignored
// when it is not the latest one, so an old prediction, extra check or ingredient list can never overwrite a
// newer choice. (The component also aborts the superseded fetch.)
import type { FallbackDish, FallbackOutcome, FallbackVerdict, IngredientsOutcome, PredictOutcome, Prediction, Tier } from "./api";
import { DEFAULT_RECT, type Rect } from "./crop";
import { type Dish, variantsOf } from "./dishes";
import type { Restriction } from "./restrictions";

export type Photo = { url: string; width: number; height: number };

export type Stage =
  | "empty"        // no photo (maybe a file error)
  | "crop"         // photo loaded, user adjusts the frame
  | "analyzing"    // confirmed crop sent to the API
  | "result"       // tier high: confident top-3
  | "low"          // tier low: not confirmed, top-3 guesses
  | "abstain"      // tier abstain: the model does not guess
  | "non-food"     // tier non_food (blank photo), or the extra check says there is no food
  | "not-ready"    // API has no trained model (MODEL_NOT_READY)
  | "error"        // server, network or busy
  | "variant"      // dish confirmed; kebab/dessert need the user's kind
  | "ingredients"; // typical ingredients of the confirmed dish (and kind)

/** The optional extra check. "unavailable" keeps whatever result is already shown. */
export type FallbackState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "used"; verdict: FallbackVerdict; dish: FallbackDish | null }
  | { status: "unavailable"; reason: string };

export type State = {
  stage: Stage;
  photo: Photo | null;
  crop: Rect;
  fileError: string | null;
  busy: boolean;                 // reading / rotating a photo
  seq: number;                   // latest photo/crop/analysis request
  sentCrop: Photo | null;        // preview of exactly the crop that was sent
  tier: Tier | null;             // exactly as the API said; never recomputed from rounded numbers
  predictions: Prediction[] | null;   // top-3 for tiers high and low, empty otherwise
  threshold: number | null;
  nonFoodReason: string | null;
  fallbackAvailable: boolean;
  fallback: FallbackState;
  fallbackDismissed: boolean;    // the user went back from "no food" (extra check) to the first result
  error: "server" | "network" | "busy" | null;
  dish: Dish | null;
  variant: string | null;        // chosen by the user, never preselected
  avoid: Restriction[];          // dietary restrictions to check the typical ingredients against
  ingredientsSeq: number;
  ingredients: IngredientsOutcome | null;   // null while loading
};

export const initialState: State = {
  stage: "empty", photo: null, crop: DEFAULT_RECT, fileError: null, busy: false, seq: 0, sentCrop: null,
  tier: null, predictions: null, threshold: null, nonFoodReason: null, fallbackAvailable: false,
  fallback: { status: "idle" }, fallbackDismissed: false, error: null, dish: null, variant: null, avoid: [],
  ingredientsSeq: 0, ingredients: null,
};

export type Action =
  | { type: "READING" }
  | { type: "FILE_REJECTED"; code: string }
  | { type: "PHOTO_LOADED"; photo: Photo }
  | { type: "CROP_CHANGED"; crop: Rect }
  | { type: "CROP_RESET" }
  | { type: "EDIT_CROP" }
  | { type: "ANALYZE"; sentCrop: Photo }
  | { type: "PREDICTED"; seq: number; outcome: PredictOutcome }
  | { type: "FALLBACK_ASK" }
  | { type: "FALLBACK_DONE"; seq: number; outcome: FallbackOutcome }
  | { type: "FALLBACK_DISMISS" }
  | { type: "CONFIRM_DISH"; dish: Dish }
  | { type: "PICK_VARIANT"; variant: string }
  | { type: "CONFIRM_VARIANT" }
  | { type: "CHANGE_VARIANT" }
  | { type: "SET_AVOID"; avoid: Restriction[] }
  | { type: "INGREDIENTS"; seq: number; outcome: IngredientsOutcome }
  | { type: "RELOAD_INGREDIENTS" }
  | { type: "BACK_TO_RESULT" }
  | { type: "RESET" };

/** Object URLs a state owns; the component revokes those that are no longer referenced. */
export function ownedUrls(s: State): string[] {
  return [s.photo?.url, s.sentCrop?.url].filter((u): u is string => Boolean(u));
}

const TIER_STAGE: Record<Tier, Stage> = { high: "result", low: "low", abstain: "abstain", non_food: "non-food" };

/** True when the extra check (not the model) is the reason for the "no food" screen. */
export function noFoodFromFallback(s: State): boolean {
  return s.tier !== null && s.tier !== "non_food" && s.fallback.status === "used" && s.fallback.verdict === "not_food"
    && !s.fallbackDismissed;
}

function resultStage(s: State): Stage {
  if (s.tier) return noFoodFromFallback(s) ? "non-food" : TIER_STAGE[s.tier];
  return s.error ? "error" : "not-ready";
}

const freshAnalysis = {
  sentCrop: null, tier: null, predictions: null, threshold: null, nonFoodReason: null, fallbackAvailable: false,
  fallback: { status: "idle" }, fallbackDismissed: false, error: null, dish: null, variant: null, ingredients: null,
} as const;

const SHOWS_RESULT: readonly Stage[] = ["result", "low", "abstain", "non-food"];

export function reducer(s: State, a: Action): State {
  switch (a.type) {
    case "READING":
      return { ...s, busy: true, fileError: null };
    case "FILE_REJECTED":
      // A bad file never replaces a good photo the user is working on.
      return s.photo ? { ...s, busy: false, fileError: a.code } : { ...initialState, avoid: s.avoid, seq: s.seq + 1, fileError: a.code };
    case "PHOTO_LOADED":
      return { ...initialState, avoid: s.avoid, stage: "crop", photo: a.photo, seq: s.seq + 1, ingredientsSeq: s.ingredientsSeq + 1 };
    case "CROP_CHANGED":
      if (!s.photo) return s;
      return { ...s, ...freshAnalysis, stage: "crop", crop: a.crop, seq: s.stage === "crop" ? s.seq : s.seq + 1 };
    case "CROP_RESET":
      return s.photo ? { ...s, ...freshAnalysis, stage: "crop", crop: DEFAULT_RECT, seq: s.seq + 1 } : s;
    case "EDIT_CROP":
      return s.photo ? { ...s, ...freshAnalysis, stage: "crop", seq: s.seq + 1 } : s;
    case "ANALYZE":
      if (!s.photo) return s;
      return { ...s, ...freshAnalysis, stage: "analyzing", sentCrop: a.sentCrop, seq: s.seq + 1,
               ingredientsSeq: s.ingredientsSeq + 1 };
    case "PREDICTED": {
      if (a.seq !== s.seq || s.stage !== "analyzing") return s;          // stale or superseded
      const o = a.outcome;
      switch (o.kind) {
        case "aborted": return s;
        case "ok": {
          const next = { ...s, tier: o.tier, predictions: o.predictions, threshold: o.threshold,
                         nonFoodReason: o.nonFoodReason, fallbackAvailable: o.fallbackAvailable, error: null };
          return { ...next, stage: TIER_STAGE[o.tier] };
        }
        case "not-ready": return { ...s, stage: "not-ready" };
        case "invalid": return { ...s, stage: "crop", fileError: o.code };
        case "busy": return { ...s, stage: "error", error: "busy" };
        case "server": return { ...s, stage: "error", error: "server" };
        case "network": return { ...s, stage: "error", error: "network" };
      }
      return s;
    }
    case "FALLBACK_ASK":
      // Only from a shown result, and only one at a time; the earlier result stays on screen.
      if (!s.fallbackAvailable || !SHOWS_RESULT.includes(s.stage) || s.fallback.status === "loading") return s;
      return { ...s, fallback: { status: "loading" }, fallbackDismissed: false };
    case "FALLBACK_DONE": {
      if (a.seq !== s.seq || s.fallback.status !== "loading" || a.outcome.kind === "aborted") return s;
      const o = a.outcome;
      const fallback: FallbackState = o.kind === "used"
        ? { status: "used", verdict: o.verdict, dish: o.dish } : { status: "unavailable", reason: o.reason };
      const next = { ...s, fallback };
      return { ...next, stage: SHOWS_RESULT.includes(s.stage) ? resultStage(next) : s.stage };
    }
    case "FALLBACK_DISMISS": {
      if (!noFoodFromFallback(s)) return s;
      const next = { ...s, fallbackDismissed: true };
      return { ...next, stage: resultStage(next) };
    }
    case "CONFIRM_DISH": {
      const needsKind = variantsOf(a.dish).length > 0;
      return { ...s, dish: a.dish, variant: null, ingredients: null, ingredientsSeq: s.ingredientsSeq + 1,
               stage: needsKind ? "variant" : "ingredients" };
    }
    case "PICK_VARIANT":
      if (s.stage !== "variant" || !s.dish || !variantsOf(s.dish).includes(a.variant)) return s;
      return { ...s, variant: a.variant };
    case "CONFIRM_VARIANT":
      if (s.stage !== "variant" || !s.variant) return s;                // no kind chosen: nothing happens
      return { ...s, stage: "ingredients", ingredients: null, ingredientsSeq: s.ingredientsSeq + 1 };
    case "CHANGE_VARIANT":
      if (!s.dish || variantsOf(s.dish).length === 0) return s;
      return { ...s, stage: "variant", ingredients: null, ingredientsSeq: s.ingredientsSeq + 1 };
    case "SET_AVOID":
      if (a.avoid.length === s.avoid.length && a.avoid.every((r, i) => r === s.avoid[i])) return s;
      // A changed selection needs a new answer for the same dish; the old list is not shown meanwhile.
      return s.stage === "ingredients"
        ? { ...s, avoid: a.avoid, ingredients: null, ingredientsSeq: s.ingredientsSeq + 1 }
        : { ...s, avoid: a.avoid };
    case "INGREDIENTS":
      if (a.seq !== s.ingredientsSeq || s.stage !== "ingredients" || a.outcome.kind === "aborted") return s;
      return { ...s, ingredients: a.outcome };
    case "RELOAD_INGREDIENTS":
      return s.stage === "ingredients" ? { ...s, ingredients: null, ingredientsSeq: s.ingredientsSeq + 1 } : s;
    case "BACK_TO_RESULT":
      return { ...s, dish: null, variant: null, ingredients: null, ingredientsSeq: s.ingredientsSeq + 1,
               stage: resultStage(s) };
    case "RESET":
      return { ...initialState, avoid: s.avoid, seq: s.seq + 1, ingredientsSeq: s.ingredientsSeq + 1 };
  }
}
