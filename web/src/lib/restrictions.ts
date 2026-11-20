// Dietary restrictions the user can check a dish against. Mirrors content/allergens.json (tested: the ids and
// their order must match the API). The check looks at the TYPICAL ingredients of the confirmed dish, not the photo.
export const RESTRICTIONS = ["halal", "nuts", "gluten", "dairy", "egg", "soy", "sesame", "fish_shellfish"] as const;
export type Restriction = (typeof RESTRICTIONS)[number];

export const AVOID_STORAGE_KEY = "fl.avoid";

export function isRestriction(value: unknown): value is Restriction {
  return typeof value === "string" && (RESTRICTIONS as readonly string[]).includes(value);
}

/** Keeps only known ids, once each, in the canonical order (so the same selection always produces the same request). */
export function normalizeAvoid(values: readonly unknown[]): Restriction[] {
  return RESTRICTIONS.filter((r) => values.includes(r));
}

// Storage can be blocked or hold garbage: the app must still work, with nothing selected.
export function loadAvoid(storage: Pick<Storage, "getItem"> | undefined): Restriction[] {
  try {
    const raw = storage?.getItem(AVOID_STORAGE_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? normalizeAvoid(parsed) : [];
  } catch {
    return [];
  }
}

export function saveAvoid(storage: Pick<Storage, "setItem"> | undefined, avoid: readonly Restriction[]): void {
  try {
    storage?.setItem(AVOID_STORAGE_KEY, JSON.stringify(avoid));
  } catch {
    /* storage blocked: keep the in-memory choice */
  }
}
