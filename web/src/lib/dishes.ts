// Mirrors config/classes.json (model output classes) and its variants. The model predicts the class
// only; for kebab and dessert the user chooses the kind.
export const DISHES = ["dessert", "hamburger", "hot_dog", "kebab", "pizza"] as const;
export type Dish = (typeof DISHES)[number];

export const VARIANTS: Partial<Record<Dish, readonly string[]>> = {
  dessert: ["cheesecake", "chocolate_cake"],
  kebab: ["skewered", "minced_skewer", "doner_shawarma"],
};

export const DISPLAY_ORDER: readonly Dish[] = ["pizza", "hamburger", "hot_dog", "kebab", "dessert"];
export const EMOJI: Record<Dish, string> = { pizza: "🍕", hamburger: "🍔", hot_dog: "🌭", kebab: "🍢", dessert: "🍰" };

export function isDish(value: unknown): value is Dish {
  return typeof value === "string" && (DISHES as readonly string[]).includes(value);
}

export function variantsOf(dish: Dish): readonly string[] {
  return VARIANTS[dish] ?? [];
}
