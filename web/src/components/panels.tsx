"use client";
import { useState } from "react";
import type { Ingredients, Prediction } from "@/lib/api";
import { DISPLAY_ORDER, type Dish, EMOJI, variantsOf } from "@/lib/dishes";
import type { Key } from "@/lib/i18n";
import { Alert, CropIcon, FileX, Info, Question, Search } from "./icons";

export type T = (key: Key, vars?: Record<string, string>) => string;

export const dishName = (t: T, d: Dish) => t(`dish.${d}` as Key);
const hint = (t: T, d: Dish) => (d === "dessert" || d === "kebab" ? t(`dish.${d}.hint` as Key) : "");
const variantName = (t: T, d: Dish, v: string) => t(`variant.${d}.${v}` as Key);

export function Matches({ t, predictions, highlight }: { t: T; predictions: Prediction[]; highlight: boolean }) {
  return (
    <ol className="matches">
      {predictions.map((p, i) => {
        const pct = Math.round(p.confidence * 100);
        return (
          <li key={p.dish} className={`match${highlight && i === 0 ? " top" : ""}`}>
            <div className="head">
              <span className="name">{dishName(t, p.dish)}</span>
              <span className="small">{hint(t, p.dish)}</span>
              <span className="pct" aria-label={`${t("result.confidence")} ${pct}%`}>{pct}%</span>
            </div>
            <div className="bar" aria-hidden="true"><span style={{ width: `${Math.max(2, pct)}%` }} /></div>
          </li>
        );
      })}
    </ol>
  );
}

export function DishPicker({ t, onPick, exclude = [] }: { t: T; onPick: (d: Dish) => void; exclude?: Dish[] }) {
  return (
    <div className="chips">
      {DISPLAY_ORDER.filter((d) => !exclude.includes(d)).map((d) => (
        <button key={d} type="button" className="chip" onClick={() => onPick(d)}>
          <span aria-hidden="true">{EMOJI[d]}</span> {dishName(t, d)}
        </button>
      ))}
    </div>
  );
}

export function EmptyPanel({ t, title, body, crop }: { t: T; title: Key; body: Key; crop?: boolean }) {
  return (
    <div className="empty">
      <div className="icon">{crop ? <CropIcon /> : <Search />}</div>
      <b style={{ color: "var(--ink-2)" }}>{t(title)}</b>
      <p className="small">{t(body)}</p>
    </div>
  );
}

export function LoadingPanel({ t }: { t: T }) {
  return (
    <div aria-busy="true">
      <h2><span className="spinner" aria-hidden="true" /> {t("loading.title")}</h2>
      <p>{t("loading.body")}</p>
      <div style={{ display: "grid", gap: 10, marginTop: 14 }}>
        <div className="skel" /><div className="skel" /><div className="skel" />
      </div>
    </div>
  );
}

export function ResultPanel({ t, predictions, onConfirm }: { t: T; predictions: Prediction[]; onConfirm: (d: Dish) => void }) {
  const [showAll, setShowAll] = useState(false);
  const top = predictions[0].dish;
  return (
    <div>
      <h2>{t("result.title")}</h2>
      <Matches t={t} predictions={predictions} highlight />
      <p className="small" style={{ marginTop: 10 }}>{t("result.note")}</p>
      <div className="ask">
        <h3>{t("result.ask", { dish: dishName(t, top) })}</h3>
        <div className="row" style={{ marginTop: 10 }}>
          <button type="button" className="btn primary" onClick={() => onConfirm(top)}>{t("result.confirm")}</button>
        </div>
        <p className="small" style={{ marginTop: 14 }}>{t("result.other")}</p>
        {showAll ? (
          <DishPicker t={t} onPick={onConfirm} exclude={[top]} />
        ) : (
          <div className="chips">
            {predictions.slice(1).map((p) => (
              <button key={p.dish} type="button" className="chip" onClick={() => onConfirm(p.dish)}>{dishName(t, p.dish)}</button>
            ))}
            <button type="button" className="chip muted" onClick={() => setShowAll(true)}>{t("result.none")}</button>
          </div>
        )}
      </div>
    </div>
  );
}

export function UncertainPanel({ t, predictions, onPick, onRetry }: {
  t: T; predictions: Prediction[]; onPick: (d: Dish) => void; onRetry: () => void;
}) {
  return (
    <div>
      <div className="notice warn" role="status">
        <Question />
        <div><b>{t("uncertain.title")}</b><p>{t("uncertain.body")}</p></div>
      </div>
      <h3 style={{ marginTop: 18 }}>{t("uncertain.best")}</h3>
      <Matches t={t} predictions={predictions} highlight={false} />
      <div className="ask">
        <h3>{t("uncertain.pick")}</h3>
        <DishPicker t={t} onPick={onPick} />
        <div className="row"><button type="button" className="btn" onClick={onRetry}>{t("uncertain.retry")}</button></div>
      </div>
    </div>
  );
}

export function NotReadyPanel({ t, onPick }: { t: T; onPick: (d: Dish) => void }) {
  return (
    <div>
      <div className="notice info" role="status">
        <Info />
        <div><b>{t("notReady.title")}</b><p>{t("notReady.body")}</p></div>
      </div>
      <div className="ask">
        <h3>{t("uncertain.pick")}</h3>
        <DishPicker t={t} onPick={onPick} />
      </div>
    </div>
  );
}

export function ErrorPanel({ t, kind, onRetry, onChoose }: {
  t: T; kind: "server" | "network"; onRetry: () => void; onChoose: () => void;
}) {
  return (
    <div>
      <div className="notice err" role="alert">
        <Alert />
        <div><b>{t(`error.${kind}.title`)}</b><p>{t(`error.${kind}.body`)}</p></div>
      </div>
      <div className="row">
        <button type="button" className="btn primary" onClick={onRetry}>{t("error.retry")}</button>
        <button type="button" className="btn" onClick={onChoose}>{t("error.choose")}</button>
      </div>
    </div>
  );
}

export function FileErrorNotice({ t, code }: { t: T; code: string }) {
  const known: Key = (`error.file.${code}` as Key);
  return (
    <div className="notice err" role="alert" style={{ marginTop: 14 }}>
      <FileX />
      <div><b>{t("error.file.title")}</b><p>{t(known in MESSAGE_KEYS ? known : "error.file.corrupt_image")}</p></div>
    </div>
  );
}
const MESSAGE_KEYS: Record<string, true> = Object.fromEntries(
  ["unsupported_format", "file_too_large", "image_too_large", "corrupt_image", "empty_file", "animated_image"]
    .map((c) => [`error.file.${c}`, true]));

export function VariantPanel({ t, dish, variant, onPick, onConfirm, onBack }: {
  t: T; dish: Dish; variant: string | null; onPick: (v: string) => void; onConfirm: () => void; onBack: () => void;
}) {
  return (
    <div>
      <div className="confirmed"><span className="tag" aria-hidden="true">✓</span><h2>{dishName(t, dish)}</h2></div>
      {/* Native radios: Tab enters the group, arrow keys move and select, Space selects. Nothing is
          preselected; the browser handles focus within the group. */}
      <fieldset className="variant-group">
        <legend><h3 style={{ marginTop: 16 }}>{t("variant.pick")}</h3></legend>
        <div className="chips">
          {variantsOf(dish).map((v) => (
            <label key={v} className="chip radio">
              <input type="radio" name={`variant-${dish}`} value={v} checked={variant === v}
                onChange={() => onPick(v)} />
              <span>{variantName(t, dish, v)}</span>
            </label>
          ))}
        </div>
      </fieldset>
      <p className="small" style={{ marginTop: 8 }}>{t("variant.required")}</p>
      <div className="row">
        <button type="button" className="btn primary" disabled={!variant} onClick={onConfirm}>{t("variant.confirm")}</button>
        <button type="button" className="btn" onClick={onBack}>{t("ingredients.back")}</button>
      </div>
    </div>
  );
}

export function IngredientsPanel({ t, dish, variant, data, failed, lang, onRetry, onChangeVariant, onBack, onNew }: {
  t: T; dish: Dish; variant: string | null; data: Ingredients | null; failed: boolean; lang: string;
  onRetry: () => void; onChangeVariant: (() => void) | null; onBack: () => void; onNew: () => void;
}) {
  const title = variant ? `${dishName(t, dish)} · ${variantName(t, dish, variant)}` : dishName(t, dish);
  return (
    <div>
      <div className="confirmed"><span className="tag" aria-hidden="true">✓</span>
        <h2>{t("ingredients.title", { dish: title })}</h2></div>
      {failed ? (
        <div className="notice err" role="alert" style={{ marginTop: 14 }}>
          <Alert /><div><p style={{ marginTop: 0 }}>{t("ingredients.error")}</p>
            <button type="button" className="btn" style={{ marginTop: 10 }} onClick={onRetry}>{t("error.retry")}</button></div>
        </div>
      ) : !data ? (
        <div aria-busy="true" style={{ display: "grid", gap: 10, marginTop: 14 }}>
          <span className="sr-only">{t("ingredients.loading")}</span>
          <div className="skel" /><div className="skel" />
        </div>
      ) : (
        <>
          <div className="notice info" style={{ marginTop: 14 }}>
            <Info /><p style={{ margin: 0 }} data-testid="disclaimer">{data.disclaimer}</p>
          </div>
          {data.variantNote && <p className="small" style={{ marginTop: 10 }}>{data.variantNote}</p>}
          <ul className="ing">{data.ingredients.map((x) => <li key={x}>{x}</li>)}</ul>
          <div className="sources">
            <h3>{t("ingredients.sources")}</h3>
            <ol>
              {data.sources.map((s) => (
                <li key={s.url}><a href={s.url} target="_blank" rel="noopener noreferrer">{s.title}</a></li>
              ))}
            </ol>
            {lang !== "en" && <p className="small">{t("ingredients.sourceLang")}</p>}
          </div>
        </>
      )}
      <div className="row">
        {onChangeVariant && <button type="button" className="btn" onClick={onChangeVariant}>{t("variant.change")}</button>}
        <button type="button" className="btn" onClick={onBack}>{t("ingredients.back")}</button>
        <button type="button" className="btn primary" onClick={onNew}>{t("ingredients.new")}</button>
      </div>
    </div>
  );
}
