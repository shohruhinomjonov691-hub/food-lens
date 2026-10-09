"use client";
import { type DragEvent, type ReactNode, useCallback, useEffect, useReducer, useRef, useState } from "react";
import * as api from "@/lib/api";
import * as cropLib from "@/lib/crop";
import { DISPLAY_ORDER, EMOJI, variantsOf } from "@/lib/dishes";
import { initialState, ownedUrls, reducer, type Stage } from "@/lib/flow";
import { browserStorage, type Key, type Lang, LANGS, loadLang, saveLang, translate } from "@/lib/i18n";
import { checkDimensions, checkFile } from "@/lib/upload";
import { CropEditor } from "./CropEditor";
import { ImageIcon, Logo, Shield } from "./icons";
import {
  dishName, EmptyPanel, ErrorPanel, FileErrorNotice, IngredientsPanel, LoadingPanel, NotReadyPanel, ResultPanel,
  UncertainPanel, VariantPanel,
} from "./panels";

const STEPS: Key[] = ["steps.upload", "steps.crop", "steps.result", "steps.ingredients"];
const STEP_OF: Record<Stage, number> = {
  empty: 0, crop: 1, analyzing: 1, result: 2, uncertain: 2, "not-ready": 2, error: 2, variant: 2, ingredients: 3,
};
const ACCEPT = "image/jpeg,image/png,image/webp";

function loadImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("decode failed"));
    img.src = url;
  });
}

/** Injected for tests; production uses the real API client and canvas helpers. */
export type Deps = { api: typeof api; crop: Pick<typeof cropLib, "cropToBlob" | "rotateBlob">; loadImage: typeof loadImage };
const realDeps: Deps = { api, crop: cropLib, loadImage };

export default function FoodLens({ deps = realDeps }: { deps?: Deps }) {
  const [state, dispatch] = useReducer(reducer, initialState);
  const [lang, setLang] = useState<Lang>("en");
  const [dragOver, setDragOver] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const cameraInput = useRef<HTMLInputElement>(null);
  const rightPanel = useRef<HTMLElement>(null);
  const stateRef = useRef(state);
  stateRef.current = state;
  const pick = useRef(0);                              // latest file selection
  const sentBlob = useRef<{ url: string; blob: Blob } | null>(null);
  const created = useRef(new Set<string>());           // object URLs this component made

  const t = useCallback((key: Key, vars?: Record<string, string>) => translate(lang, key, vars), [lang]);

  // Language: English by default, the choice survives reloads (and blocked storage).
  useEffect(() => { setLang(loadLang(browserStorage())); }, []);
  useEffect(() => { document.documentElement.lang = lang; }, [lang]);
  const chooseLang = (l: Lang) => { setLang(l); saveLang(browserStorage(), l); };

  const makeUrl = (blob: Blob) => {
    const url = URL.createObjectURL(blob);
    created.current.add(url);
    return url;
  };
  const revoke = (url: string) => {
    if (created.current.delete(url)) URL.revokeObjectURL(url);
  };

  // Release object URLs the state no longer references, and all of them on unmount.
  useEffect(() => {
    const live = new Set(ownedUrls(state));
    for (const url of [...created.current]) if (!live.has(url)) revoke(url);
    if (sentBlob.current && !live.has(sentBlob.current.url)) sentBlob.current = null;
  }, [state]);
  // Unmount: invalidate pending upload/rotate/crop work (each checks `pick` before creating a URL) and
  // revoke every URL that still exists.
  useEffect(() => () => {
    pick.current++;
    for (const url of [...created.current]) revoke(url);
  }, []);

  const openFile = useCallback(async (file: File | undefined | null) => {
    if (!file) return;
    const mine = ++pick.current;
    dispatch({ type: "READING" });
    const check = await checkFile(file);
    if (mine !== pick.current) return;
    if (!check.ok) return dispatch({ type: "FILE_REJECTED", code: check.code });
    if (mine !== pick.current) return;
    const url = makeUrl(file);
    try {
      const img = await deps.loadImage(url);
      if (mine !== pick.current) return revoke(url);
      const bad = checkDimensions(img.naturalWidth, img.naturalHeight);
      if (bad) {
        revoke(url);
        return dispatch({ type: "FILE_REJECTED", code: bad });
      }
      dispatch({ type: "PHOTO_LOADED", photo: { url, width: img.naturalWidth, height: img.naturalHeight } });
    } catch {
      revoke(url);
      if (mine === pick.current) dispatch({ type: "FILE_REJECTED", code: "corrupt_image" });
    }
  }, [deps]);

  const rotate = async () => {
    const photo = stateRef.current.photo;
    if (!photo) return;
    const mine = ++pick.current;
    dispatch({ type: "READING" });
    try {
      const img = await deps.loadImage(photo.url);
      const blob = await deps.crop.rotateBlob(img, photo.width, photo.height);
      if (mine !== pick.current) return;
      dispatch({ type: "PHOTO_LOADED", photo: { url: makeUrl(blob), width: photo.height, height: photo.width } });
    } catch {
      if (mine === pick.current) dispatch({ type: "FILE_REJECTED", code: "corrupt_image" });
    }
  };

  // Analyze: the confirmed crop is exported once; exactly that blob is shown and sent.
  const analyze = async () => {
    const { photo, crop } = stateRef.current;
    if (!photo) return;
    const mine = ++pick.current;
    try {
      const img = await deps.loadImage(photo.url);
      const blob = await deps.crop.cropToBlob(img, photo.width, photo.height, crop);
      const now = stateRef.current;
      if (mine !== pick.current || now.photo?.url !== photo.url || now.crop !== crop) return;   // changed meanwhile
      const url = makeUrl(blob);
      sentBlob.current = { url, blob };
      dispatch({ type: "ANALYZE", sentCrop: { url, width: 0, height: 0 } });
    } catch {
      if (mine === pick.current) dispatch({ type: "FILE_REJECTED", code: "corrupt_image" });
    }
  };

  // The prediction request belongs to one `seq`; a newer photo/crop/analysis aborts it.
  useEffect(() => {
    if (state.stage !== "analyzing" || !state.sentCrop || sentBlob.current?.url !== state.sentCrop.url) return;
    const controller = new AbortController();
    const seq = state.seq;
    deps.api.predict(sentBlob.current.blob, controller.signal).then((outcome) => {
      if (!controller.signal.aborted) dispatch({ type: "PREDICTED", seq, outcome });
    });
    return () => controller.abort();
  }, [state.stage, state.seq, state.sentCrop, deps]);

  // Ingredients belong to one `ingredientsSeq` (dish + user-chosen kind + language).
  useEffect(() => {
    if (state.stage !== "ingredients" || !state.dish || state.ingredients !== null) return;
    const controller = new AbortController();
    const seq = state.ingredientsSeq;
    deps.api.fetchIngredients(state.dish, state.variant, lang, controller.signal).then((outcome) => {
      if (!controller.signal.aborted) dispatch({ type: "INGREDIENTS", seq, outcome });
    });
    return () => controller.abort();
  }, [state.stage, state.dish, state.variant, state.ingredientsSeq, state.ingredients, lang, deps]);

  const firstLang = useRef(true);
  useEffect(() => {
    if (firstLang.current) { firstLang.current = false; return; }
    dispatch({ type: "RELOAD_INGREDIENTS" });
  }, [lang]);

  // Phones show one column: bring the result card into view when its content changes.
  useEffect(() => {
    if (state.stage === "empty" || state.stage === "crop") return;
    if (!window.matchMedia?.("(max-width: 860px)").matches) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    rightPanel.current?.scrollIntoView?.({ behavior: reduce ? "auto" : "smooth", block: "start" });
  }, [state.stage]);

  const reset = () => { pick.current++; dispatch({ type: "RESET" }); };
  const chooseAnother = () => { reset(); fileInput.current?.click(); };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    void openFile(e.dataTransfer.files?.[0]);
  };

  const s = state;
  const step = STEP_OF[s.stage];
  const confirmDish = (d: Parameters<typeof dishName>[1]) => dispatch({ type: "CONFIRM_DISH", dish: d });

  let right: ReactNode;
  switch (s.stage) {
    case "empty": right = <EmptyPanel t={t} title="empty.title" body="empty.body" />; break;
    case "crop": right = <EmptyPanel t={t} title="pending.title" body="pending.body" crop />; break;
    case "analyzing": right = <LoadingPanel t={t} />; break;
    case "result": right = <ResultPanel t={t} predictions={s.predictions!} onConfirm={confirmDish} />; break;
    case "uncertain":
      right = <UncertainPanel t={t} predictions={s.predictions!} onPick={confirmDish} onRetry={chooseAnother} />; break;
    case "not-ready": right = <NotReadyPanel t={t} onPick={confirmDish} />; break;
    case "error":
      right = <ErrorPanel t={t} kind={s.error ?? "server"} onRetry={() => void analyze()} onChoose={chooseAnother} />; break;
    case "variant":
      right = <VariantPanel t={t} dish={s.dish!} variant={s.variant}
        onPick={(v) => dispatch({ type: "PICK_VARIANT", variant: v })}
        onConfirm={() => dispatch({ type: "CONFIRM_VARIANT" })} onBack={() => dispatch({ type: "BACK_TO_RESULT" })} />;
      break;
    case "ingredients":
      right = <IngredientsPanel t={t} dish={s.dish!} variant={s.variant} lang={lang}
        data={s.ingredients?.kind === "ok" ? s.ingredients.data : null} failed={s.ingredients?.kind === "error"}
        onRetry={() => dispatch({ type: "RELOAD_INGREDIENTS" })}
        onChangeVariant={variantsOf(s.dish!).length ? () => dispatch({ type: "CHANGE_VARIANT" }) : null}
        onBack={() => dispatch({ type: "BACK_TO_RESULT" })} onNew={chooseAnother} />;
      break;
  }

  return (
    <>
      <header>
        <div className="wrap">
          <span className="brand"><Logo /><b>{t("app.name")}</b></span>
          <span className="tagline">{t("app.tagline")}</span>
          <div className="lang" role="group" aria-label={t("lang.label")}>
            {LANGS.map((l) => (
              <button key={l} type="button" aria-pressed={lang === l} lang={l} onClick={() => chooseLang(l)}>
                {l === "en" ? "EN" : "한국어"}
              </button>
            ))}
          </div>
        </div>
      </header>
      <main>
        <div className="wrap">
          <ol className="steps" aria-label={t("steps.label")}>
            {STEPS.map((k, i) => (
              <li key={k} className={i < step ? "done" : i === step ? "now" : ""} aria-current={i === step ? "step" : undefined}>
                <span className="n">{i + 1}</span><span className="label">{t(k)}</span>
              </li>
            ))}
          </ol>
        </div>
        <div className="wrap layout">
          <section className="card pane" aria-labelledby="left-title">
            <input ref={fileInput} type="file" accept={ACCEPT} hidden data-testid="file-input"
              onChange={(e) => { void openFile(e.target.files?.[0]); e.target.value = ""; }} />
            <input ref={cameraInput} type="file" accept={ACCEPT} capture="environment" hidden
              onChange={(e) => { void openFile(e.target.files?.[0]); e.target.value = ""; }} />
            {!s.photo ? (
              <div>
                <h2 id="left-title">{t("upload.title")}</h2>
                <div className={`drop${dragOver ? " over" : ""}`} style={{ marginTop: 14 }}
                  onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
                  onDragLeave={() => setDragOver(false)} onDrop={onDrop}>
                  <div className="icon"><ImageIcon /></div>
                  <b>{t("upload.drop")}</b>
                  <span className="or">{t("upload.or")}</span>
                  <div className="row">
                    <button type="button" className="btn primary" disabled={s.busy} onClick={() => fileInput.current?.click()}>
                      {t("upload.choose")}
                    </button>
                    <button type="button" className="btn" disabled={s.busy} onClick={() => cameraInput.current?.click()}>
                      {t("upload.camera")}
                    </button>
                  </div>
                  <p className="small" style={{ marginTop: 12 }} aria-live="polite">{s.busy ? t("upload.reading") : t("upload.hint")}</p>
                </div>
                {s.fileError && <FileErrorNotice t={t} code={s.fileError} />}
                <h3 style={{ marginTop: 18 }}>{t("supported.title")}</h3>
                <div className="dishes">
                  {DISPLAY_ORDER.map((d) => (
                    <div key={d} className="dish"><span className="emoji" aria-hidden="true">{EMOJI[d]}</span>{dishName(t, d)}</div>
                  ))}
                </div>
              </div>
            ) : s.stage === "crop" ? (
              <div>
                <h2 id="left-title">{t("crop.title")}</h2>
                <p style={{ marginBottom: 14 }}>{t("crop.body")}</p>
                <CropEditor photo={s.photo} crop={s.crop} label={t("crop.frame")}
                  onChange={(r) => dispatch({ type: "CROP_CHANGED", crop: r })} />
                {s.fileError && <FileErrorNotice t={t} code={s.fileError} />}
                <div className="toolbar">
                  <button type="button" className="btn" onClick={() => dispatch({ type: "CROP_RESET" })}>{t("crop.reset")}</button>
                  <button type="button" className="btn" disabled={s.busy} onClick={() => void rotate()}>{t("crop.rotate")}</button>
                  <button type="button" className="btn ghost" onClick={chooseAnother}>{t("crop.change")}</button>
                </div>
                <div className="row">
                  <button type="button" className="btn primary" style={{ minWidth: 160 }} disabled={s.busy}
                    onClick={() => void analyze()}>{t("crop.analyze")}</button>
                </div>
              </div>
            ) : (
              <div>
                {s.sentCrop && (
                  <figure style={{ margin: 0 }}>
                    <div className="photo" style={{ maxWidth: 420 }}>
                      {/* eslint-disable-next-line @next/next/no-img-element -- local object URL of the sent crop */}
                      <img src={s.sentCrop.url} alt="" data-testid="sent-crop" />
                      {s.stage === "analyzing" && <div className="scan" aria-hidden="true" />}
                    </div>
                    <figcaption id="left-title" className="caption">{t("crop.preview")}</figcaption>
                  </figure>
                )}
                {s.fileError && <FileErrorNotice t={t} code={s.fileError} />}
                <div className="toolbar" style={{ justifyContent: "center" }}>
                  <button type="button" className="btn" onClick={() => dispatch({ type: "EDIT_CROP" })}>{t("crop.edit")}</button>
                  <button type="button" className="btn ghost" onClick={chooseAnother}>{t("crop.change")}</button>
                </div>
              </div>
            )}
            <div className="privacy"><Shield /><span>{t("privacy")}</span></div>
          </section>
          <section ref={rightPanel} className="card pane" aria-live="polite" style={{ scrollMarginTop: 12 }}>{right}</section>
        </div>
      </main>
      <footer><div className="wrap">{t("footer")}</div></footer>
    </>
  );
}
