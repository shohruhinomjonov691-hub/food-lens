// The whole user flow as a pure reducer. Every new photo, crop change and analysis gets a new
// sequence number; a response carries the number of the request that produced it and is ignored
// when it is not the latest one, so an old prediction or ingredient list can never overwrite a newer
// choice. (The component also aborts the superseded fetch.)
import type { IngredientsOutcome, PredictOutcome, Prediction } from "./api";
import { DEFAULT_RECT, type Rect } from "./crop";
import { type Dish, variantsOf } from "./dishes";

export type Photo = { url: string; width: number; height: number };

export type Stage =
  | "empty"        // no photo (maybe a file error)
  | "crop"         // photo loaded, user adjusts the frame
  | "analyzing"    // confirmed crop sent to the API
  | "result"       // confident top-3
  | "uncertain"    // top-1 below the threshold
  | "not-ready"    // API has no trained model (MODEL_NOT_READY)
  | "error"        // server or network error
  | "variant"      // dish confirmed; kebab/dessert need the user's kind
  | "ingredients"; // typical ingredients of the confirmed dish (and kind)

export type State = {
  stage: Stage;
  photo: Photo | null;
  crop: Rect;
  fileError: string | null;
  busy: boolean;                 // reading / rotating a photo
  seq: number;                   // latest photo/crop/analysis request
  sentCrop: Photo | null;        // preview of exactly the crop that was sent
  predictions: Prediction[] | null;
  threshold: number | null;
  error: "server" | "network" | null;
  dish: Dish | null;
  variant: string | null;        // chosen by the user, never preselected
  ingredientsSeq: number;
  ingredients: IngredientsOutcome | null;   // null while loading
};

export const initialState: State = {
  stage: "empty", photo: null, crop: DEFAULT_RECT, fileError: null, busy: false, seq: 0, sentCrop: null,
  predictions: null, threshold: null, error: null, dish: null, variant: null, ingredientsSeq: 0, ingredients: null,
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
  | { type: "CONFIRM_DISH"; dish: Dish }
  | { type: "PICK_VARIANT"; variant: string }
  | { type: "CONFIRM_VARIANT" }
  | { type: "CHANGE_VARIANT" }
  | { type: "INGREDIENTS"; seq: number; outcome: IngredientsOutcome }
  | { type: "RELOAD_INGREDIENTS" }
  | { type: "BACK_TO_RESULT" }
  | { type: "RESET" };

/** Object URLs a state owns; the component revokes those that are no longer referenced. */
export function ownedUrls(s: State): string[] {
  return [s.photo?.url, s.sentCrop?.url].filter((u): u is string => Boolean(u));
}

function resultStage(s: State): Stage {
  if (s.predictions) return s.threshold !== null && s.predictions[0].confidence < s.threshold ? "uncertain" : "result";
  return s.error ? "error" : "not-ready";
}

const freshAnalysis = {
  sentCrop: null, predictions: null, threshold: null, error: null, dish: null, variant: null, ingredients: null,
} as const;

export function reducer(s: State, a: Action): State {
  switch (a.type) {
    case "READING":
      return { ...s, busy: true, fileError: null };
    case "FILE_REJECTED":
      // A bad file never replaces a good photo the user is working on.
      return s.photo ? { ...s, busy: false, fileError: a.code } : { ...initialState, seq: s.seq + 1, fileError: a.code };
    case "PHOTO_LOADED":
      return { ...initialState, stage: "crop", photo: a.photo, seq: s.seq + 1, ingredientsSeq: s.ingredientsSeq + 1 };
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
          const next = { ...s, predictions: o.predictions, threshold: o.threshold, error: null };
          return { ...next, stage: o.uncertain ? "uncertain" : "result" };
        }
        case "not-ready": return { ...s, stage: "not-ready" };
        case "invalid": return { ...s, stage: "crop", fileError: o.code };
        case "server": return { ...s, stage: "error", error: "server" };
        case "network": return { ...s, stage: "error", error: "network" };
      }
      return s;
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
    case "INGREDIENTS":
      if (a.seq !== s.ingredientsSeq || s.stage !== "ingredients" || a.outcome.kind === "aborted") return s;
      return { ...s, ingredients: a.outcome };
    case "RELOAD_INGREDIENTS":
      return s.stage === "ingredients" ? { ...s, ingredients: null, ingredientsSeq: s.ingredientsSeq + 1 } : s;
    case "BACK_TO_RESULT":
      return { ...s, dish: null, variant: null, ingredients: null, ingredientsSeq: s.ingredientsSeq + 1,
               stage: resultStage(s) };
    case "RESET":
      return { ...initialState, seq: s.seq + 1, ingredientsSeq: s.ingredientsSeq + 1 };
  }
}
