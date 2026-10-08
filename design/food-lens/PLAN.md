# Food Lens — design mockup

Static mockup for batch 6 (Next.js/TypeScript frontend). Nothing here uploads files, calls a model
or a server: every state is fake and is selected with the URL hash.

- `mockup.html` — the app screen; `#state=<state>&lang=<en|ko>`.
- `review.html` — design-review tool only (state, language, desktop/390 px switcher). Never ship it.
- `i18n/en.js`, `i18n/ko.js` — all UI strings, identical keys. English is the default; the choice is
  saved in `localStorage` (`fl.lang`) and the page still works when storage is blocked.

Run locally: `python3 -m http.server 8798 --bind 127.0.0.1 --directory design/food-lens`, then open
`http://127.0.0.1:8798/review.html`.

## Flow and states

| Step | State (`#state=`) | What the user sees |
| --- | --- | --- |
| 1 Upload | `empty` | Drop zone, "Choose a photo" / "Take a photo", file hint (JPG/PNG/WebP, ≤10 MB), the 5 supported dishes, privacy line. Right panel: empty state |
| 1 Upload | `error-file` | Wrong type / too large: error notice + "Choose another photo" |
| 2 Crop | `crop` | Photo with crop frame (reset, rotate, change photo) and "Analyze". Right panel: "Ready to analyze" (hidden on phones) |
| 2 Crop | `loading` | Scan animation on the photo, skeleton rows, "Analyzing…" (`prefers-reduced-motion` respected) |
| 3 Result | `result` | Top 3 with confidence bars, top match highlighted, "Is this Pizza?" → "Yes, show ingredients"; alternatives from the top 3 + "None of these" |
| 3 Result | `uncertain` | Top-1 below threshold: "Not sure" notice, low-confidence guesses, user can pick one of the 5 dishes or try another photo |
| 3 Result | `error-server` | Server error: "your photo was not saved", retry / choose another photo |
| 4 Ingredients | `confirmed` | Only after confirmation: "Typical ingredients of …", disclaimer that this is **not what was detected in the photo**, source list, back / analyze another |

Product rules carried into the app:

- Ingredients appear only after the user confirms (or picks) the dish.
- The disclaimer is always visible next to the list, in both languages.
- Each ingredient list has source links and the source language (batch 5). The mockup list is a
  labelled sample without sources.
- No calories or allergens, and no claims about the exact contents of the photo (out of scope).
- The photo is never stored; error copy repeats this.

## Visual decisions

- Warm light theme: cream background `#fbf6ef`, white cards, dark brown ink, terracotta accent `#b93d0b`.
- Contrast (WCAG formula): ink 15.7:1, secondary 7.8:1, muted 5.3:1 (4.6:1 on `#f6eee3`), accent
  and white-on-accent 5.6:1, warning/error/success notices 6.3–7.0:1.
- Targets ≥ 40–44 px; visible focus ring; `aria-live` on the result panel; `aria-current` on the step.
- Desktop: photo left, result right. ≤ 860 px: one column. ≤ 480 px: 3-column dish grid, one-column
  ingredients, buttons stretch.
- Class labels: "Dessert (cake)" with hint "cheesecake, chocolate cake"; "Kebab (skewered)" with hint
  "shish, shashlik, Adana" — matches the training data (Commons skewered kebabs, döner excluded).

## Open points for batch 6

- Final upload limit and accepted types come from the API (batch 4); the mockup says 10 MB.
- Uncertainty threshold comes from validation calibration (batch 3).
- On phones the result card is below the photo; the app should scroll it into view after analysis.
- Korean copy has not been reviewed by a native speaker.
- Emoji icons are placeholders; final icons should be SVG.
