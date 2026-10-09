// UI strings, English (default) and Korean. Keys must match (tested). Ingredient lists, their
// disclaimer and sources come from the API (content/ingredients.json), not from here.
export const LANGS = ["en", "ko"] as const;
export type Lang = (typeof LANGS)[number];
export const STORAGE_KEY = "fl.lang";

const en = {
  "app.name": "Food Lens",
  "app.tagline": "Snap a dish, see what it usually contains.",
  "lang.label": "Language",
  "privacy": "Your photo is analyzed in memory and never stored.",
  "steps.label": "Progress",
  "steps.upload": "Upload", "steps.crop": "Crop", "steps.result": "Result", "steps.ingredients": "Ingredients",
  "upload.title": "Add a food photo",
  "upload.drop": "Drop a photo here",
  "upload.or": "or",
  "upload.choose": "Choose a photo",
  "upload.camera": "Take a photo",
  "upload.hint": "JPG, PNG or WebP · up to 10 MB · one dish per photo works best",
  "upload.reading": "Opening the photo…",
  "supported.title": "Food Lens recognizes 5 dishes",
  "empty.title": "No photo yet",
  "empty.body": "Results appear here after you add a photo.",
  "pending.title": "Ready to analyze",
  "pending.body": "Press Analyze to see the top 3 matches.",
  "crop.title": "Crop to the dish",
  "crop.body": "Drag the frame or its corners so it shows only the food. Arrow keys move it; Shift + arrows resize.",
  "crop.frame": "Crop frame",
  "crop.reset": "Reset", "crop.rotate": "Rotate", "crop.analyze": "Analyze", "crop.change": "Change photo",
  "crop.edit": "Edit crop",
  "crop.preview": "Cropped photo sent for analysis",
  "loading.title": "Analyzing…",
  "loading.body": "Comparing your photo with 5 dishes.",
  "result.title": "Top matches",
  "result.ask": "Is this {dish}?",
  "result.confirm": "Yes, show ingredients",
  "result.other": "No — it’s one of these",
  "result.none": "None of these",
  "result.confidence": "confidence",
  "result.note": "Confidence is the model’s estimate, not a guarantee.",
  "uncertain.title": "Not sure",
  "uncertain.body": "This photo doesn’t clearly match any of the 5 dishes. Try a closer, brighter photo of one dish, or pick the dish yourself.",
  "uncertain.pick": "Pick the dish",
  "uncertain.retry": "Try another photo",
  "uncertain.best": "Closest guesses (low confidence)",
  "variant.pick": "Which kind is it?",
  "variant.required": "Choose the kind to see its typical ingredients.",
  "variant.confirm": "Show ingredients",
  "variant.change": "Change kind",
  "variant.kebab.skewered": "Shish / shashlik",
  "variant.kebab.minced_skewer": "Adana / koobideh",
  "variant.kebab.doner_shawarma": "Döner / shawarma",
  "variant.dessert.cheesecake": "Cheesecake",
  "variant.dessert.chocolate_cake": "Chocolate cake",
  "ingredients.title": "Typical ingredients of {dish}",
  "ingredients.loading": "Loading ingredients…",
  "ingredients.error": "Ingredients could not be loaded. Please try again.",
  "ingredients.sources": "Sources",
  "ingredients.sourceLang": "Source language: English. Korean text is a translation.",
  "ingredients.back": "Back to results",
  "ingredients.new": "Analyze another photo",
  "error.file.title": "This file can’t be used",
  "error.file.unsupported_format": "Please choose a JPG, PNG or WebP image.",
  "error.file.file_too_large": "The photo must be at most 10 MB.",
  "error.file.image_too_large": "The photo is too large (max. 8000 px side, 25 megapixels).",
  "error.file.corrupt_image": "This photo could not be opened. It may be damaged.",
  "error.file.empty_file": "The file is empty.",
  "error.file.animated_image": "Animated images are not supported.",
  "error.server.title": "Something went wrong",
  "error.server.body": "We couldn’t analyze the photo. Your photo was not saved. Please try again.",
  "error.network.title": "No connection",
  "error.network.body": "The analysis service could not be reached. Check your connection and try again.",
  "error.retry": "Try again",
  "error.choose": "Choose another photo",
  "notReady.title": "The recognizer is not ready yet",
  "notReady.body": "The model is still being trained, so photos can’t be analyzed right now. You can still pick a dish to see its typical ingredients.",
  "dish.dessert": "Dessert (cake)",
  "dish.dessert.hint": "cheesecake, chocolate cake",
  "dish.hamburger": "Hamburger",
  "dish.hot_dog": "Hot dog",
  "dish.kebab": "Kebab",
  "dish.kebab.hint": "shish, Adana/koobideh, döner/shawarma",
  "dish.pizza": "Pizza",
  "footer": "Portfolio demo · 5 dishes · not for dietary or medical decisions",
};

export type Key = keyof typeof en;

const ko: Record<Key, string> = {
  "app.name": "Food Lens",
  "app.tagline": "음식을 찍으면 보통 들어가는 재료를 알려 드려요.",
  "lang.label": "언어",
  "privacy": "사진은 메모리에서만 분석되며 저장되지 않습니다.",
  "steps.label": "진행 단계",
  "steps.upload": "업로드", "steps.crop": "자르기", "steps.result": "결과", "steps.ingredients": "재료",
  "upload.title": "음식 사진 추가",
  "upload.drop": "여기에 사진을 끌어다 놓으세요",
  "upload.or": "또는",
  "upload.choose": "사진 선택",
  "upload.camera": "사진 찍기",
  "upload.hint": "JPG, PNG, WebP · 최대 10MB · 한 장에 한 가지 음식이 가장 정확해요",
  "upload.reading": "사진을 여는 중…",
  "supported.title": "Food Lens가 인식하는 음식 5가지",
  "empty.title": "아직 사진이 없어요",
  "empty.body": "사진을 추가하면 여기에 결과가 표시됩니다.",
  "pending.title": "분석 준비 완료",
  "pending.body": "분석하기를 누르면 가장 비슷한 음식 3가지를 보여 드려요.",
  "crop.title": "음식 부분만 자르기",
  "crop.body": "프레임이나 모서리를 끌어 음식만 보이도록 맞춰 주세요. 방향키로 이동, Shift+방향키로 크기를 조절해요.",
  "crop.frame": "자르기 프레임",
  "crop.reset": "초기화", "crop.rotate": "회전", "crop.analyze": "분석하기", "crop.change": "사진 변경",
  "crop.edit": "자르기 수정",
  "crop.preview": "분석에 보낸 자른 사진",
  "loading.title": "분석 중…",
  "loading.body": "사진을 5가지 음식과 비교하고 있어요.",
  "result.title": "가장 비슷한 음식",
  "result.ask": "{dish} 맞나요?",
  "result.confirm": "네, 재료 보기",
  "result.other": "아니요 — 이 중 하나예요",
  "result.none": "해당 없음",
  "result.confidence": "신뢰도",
  "result.note": "신뢰도는 모델의 추정치이며 정답을 보장하지 않습니다.",
  "uncertain.title": "확실하지 않아요",
  "uncertain.body": "이 사진은 5가지 음식 중 어느 것과도 뚜렷하게 일치하지 않아요. 음식 하나를 더 가깝고 밝게 찍어 보시거나 직접 선택해 주세요.",
  "uncertain.pick": "음식 직접 선택",
  "uncertain.retry": "다른 사진으로 시도",
  "uncertain.best": "가장 가까운 추정 (낮은 신뢰도)",
  "variant.pick": "어떤 종류인가요?",
  "variant.required": "종류를 선택하면 일반적인 재료를 보여 드려요.",
  "variant.confirm": "재료 보기",
  "variant.change": "종류 변경",
  "variant.kebab.skewered": "시시 / 샤슬릭",
  "variant.kebab.minced_skewer": "아다나 / 쿠비데",
  "variant.kebab.doner_shawarma": "되네르 / 샤와르마",
  "variant.dessert.cheesecake": "치즈케이크",
  "variant.dessert.chocolate_cake": "초콜릿 케이크",
  "ingredients.title": "{dish}의 일반적인 재료",
  "ingredients.loading": "재료를 불러오는 중…",
  "ingredients.error": "재료를 불러오지 못했습니다. 다시 시도해 주세요.",
  "ingredients.sources": "출처",
  "ingredients.sourceLang": "출처 언어: 영어. 한국어는 번역입니다.",
  "ingredients.back": "결과로 돌아가기",
  "ingredients.new": "다른 사진 분석",
  "error.file.title": "이 파일은 사용할 수 없어요",
  "error.file.unsupported_format": "JPG, PNG, WebP 이미지를 선택해 주세요.",
  "error.file.file_too_large": "사진은 최대 10MB까지 가능합니다.",
  "error.file.image_too_large": "사진이 너무 큽니다(한 변 최대 8000px, 2500만 화소).",
  "error.file.corrupt_image": "사진을 열 수 없습니다. 파일이 손상되었을 수 있어요.",
  "error.file.empty_file": "빈 파일입니다.",
  "error.file.animated_image": "움직이는 이미지는 지원하지 않습니다.",
  "error.server.title": "문제가 발생했어요",
  "error.server.body": "사진을 분석하지 못했습니다. 사진은 저장되지 않았어요. 다시 시도해 주세요.",
  "error.network.title": "연결할 수 없어요",
  "error.network.body": "분석 서비스에 연결하지 못했습니다. 연결 상태를 확인하고 다시 시도해 주세요.",
  "error.retry": "다시 시도",
  "error.choose": "다른 사진 선택",
  "notReady.title": "인식 기능이 아직 준비되지 않았어요",
  "notReady.body": "모델을 학습하는 중이라 지금은 사진을 분석할 수 없습니다. 음식을 직접 선택하면 일반적인 재료를 볼 수 있어요.",
  "dish.dessert": "디저트 (케이크)",
  "dish.dessert.hint": "치즈케이크, 초콜릿 케이크",
  "dish.hamburger": "햄버거",
  "dish.hot_dog": "핫도그",
  "dish.kebab": "케밥",
  "dish.kebab.hint": "시시, 아다나/쿠비데, 되네르/샤와르마",
  "dish.pizza": "피자",
  "footer": "포트폴리오 데모 · 음식 5가지 · 식단이나 의료 판단용이 아닙니다",
};

export const MESSAGES: Record<Lang, Record<Key, string>> = { en, ko };

export function translate(lang: Lang, key: Key, vars?: Record<string, string>): string {
  return MESSAGES[lang][key].replace(/\{(\w+)\}/g, (_, v: string) => vars?.[v] ?? "");
}

export function isLang(value: unknown): value is Lang {
  return value === "en" || value === "ko";
}

// Storage can be blocked (private mode, settings): the app must still work, in English.
export function loadLang(storage: Pick<Storage, "getItem"> | undefined): Lang {
  try {
    const v = storage?.getItem(STORAGE_KEY);
    return isLang(v) ? v : "en";
  } catch {
    return "en";
  }
}

export function saveLang(storage: Pick<Storage, "setItem"> | undefined, lang: Lang): void {
  try {
    storage?.setItem(STORAGE_KEY, lang);
  } catch {
    /* storage blocked: keep the in-memory choice */
  }
}
