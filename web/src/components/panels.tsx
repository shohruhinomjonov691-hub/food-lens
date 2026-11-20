"use client";
import { useState } from "react";
import type { Evaluation, EvaluationOutcome, GuardResult, Ingredients, Prediction, Tier } from "@/lib/api";
import { DISPLAY_ORDER, type Dish, EMOJI, variantsOf } from "@/lib/dishes";
import type { FallbackState } from "@/lib/flow";
import type { Key } from "@/lib/i18n";
import { RESTRICTIONS, type Restriction } from "@/lib/restrictions";
import { Alert, CropIcon, FileX, Info, Question, Search } from "./icons";

export type T = (key: Key, vars?: Record<string, string>) => string;

export const dishName = (t: T, d: Dish) => t(`dish.${d}` as Key);
const hint = (t: T, d: Dish) => (d === "dessert" || d === "kebab" ? t(`dish.${d}.hint` as Key) : "");
const variantName = (t: T, d: Dish, v: string) => t(`variant.${d}.${v}` as Key);
const pct1 = (x: number) => `${(x * 100).toFixed(1)}%`;
const pct0 = (x: number) => String(Math.round(x * 100));

const TIER_GLYPH: Record<Tier, string> = { high: "✓", low: "!", abstain: "?", non_food: "✕" };

export function TierBadge({ t, tier }: { t: T; tier: Tier }) {
  return (
    <span className={`badge tier-${tier}`} data-testid="tier-badge" data-tier={tier}>
      <span aria-hidden="true">{TIER_GLYPH[tier]}</span> {t(`tier.${tier}` as Key)}
    </span>
  );
}

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

/** The optional extra check: offered on request only (it sends the photo to an outside service). A failure keeps the result. */
export function FallbackSection({ t, available, state, primary, onAsk, onUse }: {
  t: T; available: boolean; state: FallbackState; primary: Dish | null; onAsk: () => void; onUse: (d: Dish) => void;
}) {
  let body;
  if (state.status === "idle") {
    body = (
      <>
        {available ? <p>{t("fallback.offer")}</p> : (
          <div className="notice warn" role="status" data-testid="fallback-unavailable">
            <Alert />
            <div><b>{t("fallback.unavailable")}</b><p>{t("fallback.reason.not_configured")}</p></div>
          </div>
        )}
        <div className="row"><button type="button" className="btn" disabled={!available} onClick={onAsk}>{t("fallback.ask")}</button></div>
        <p className="small">{t("fallback.privacy")}</p>
      </>
    );
  } else if (state.status === "loading") {
    body = <p aria-busy="true"><span className="spinner" aria-hidden="true" /> {t("fallback.loading")}</p>;
  } else if (state.status === "unavailable") {
    body = (
      <div className="notice warn" role="status" data-testid="fallback-unavailable">
        <Alert />
        <div>
          <b>{t("fallback.unavailable")}</b>
          <p>{t(`fallback.reason.${state.reason}` as Key)} {t("fallback.keeps")}</p>
          {available && <button type="button" className="btn" style={{ marginTop: 10 }} onClick={onAsk}>{t("fallback.retry")}</button>}
        </div>
      </div>
    );
  } else {
    const { verdict, dish } = state;
    body = (
      <div data-testid="fallback-used">
        <b>{t("fallback.used")}</b>
        {verdict === "food" && dish && dish !== "other_food" && (
          <>
            <p>{t("fallback.suggest", { dish: dishName(t, dish) })} {primary ? t(dish === primary ? "fallback.agrees" : "fallback.differs") : ""}</p>
            <div className="row">
              <button type="button" className="btn primary" onClick={() => onUse(dish)}>{t("fallback.use", { dish: dishName(t, dish) })}</button>
            </div>
          </>
        )}
        {verdict === "food" && dish === "other_food" && <p>{t("fallback.otherFood")}</p>}
        {verdict === "unclear" && <p>{t("fallback.unclear")}</p>}
        {verdict === "not_food" && <p>{t("fallback.notFood")}</p>}
        <p className="small">{t("fallback.note")}</p>
      </div>
    );
  }
  return (
    <div className="ask fallback" aria-live="polite">
      <h3>{t("fallback.title")}</h3>
      {body}
    </div>
  );
}

type ExtraProps = { fallback: React.ReactNode };

export function ResultPanel({ t, predictions, onConfirm, fallback }: {
  t: T; predictions: Prediction[]; onConfirm: (d: Dish) => void } & ExtraProps) {
  const [showAll, setShowAll] = useState(false);
  const top = predictions[0].dish;
  return (
    <div>
      <TierBadge t={t} tier="high" />
      <h2 style={{ marginTop: 10 }}>{t("result.title")}</h2>
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
      {fallback}
    </div>
  );
}

/** Tier low: not confirmed. Shows the top-3 as guesses and never highlights a winner. */
export function LowConfidencePanel({ t, predictions, onPick, onRetry, fallback }: {
  t: T; predictions: Prediction[]; onPick: (d: Dish) => void; onRetry: () => void } & ExtraProps) {
  return (
    <div>
      <div className="notice warn" role="status">
        <Question />
        <div><TierBadge t={t} tier="low" /><b style={{ marginTop: 6 }}>{t("low.title")}</b><p>{t("low.body")}</p></div>
      </div>
      <h3 style={{ marginTop: 18 }}>{t("low.best")}</h3>
      <Matches t={t} predictions={predictions} highlight={false} />
      <div className="ask">
        <h3>{t("pick.title")}</h3>
        <DishPicker t={t} onPick={onPick} />
        <div className="row"><button type="button" className="btn" onClick={onRetry}>{t("photo.retry")}</button></div>
      </div>
      {fallback}
    </div>
  );
}

/** Tier abstain: the model does not guess, so no dish or percentage is on screen. */
export function AbstainPanel({ t, onPick, onRetry, fallback }: {
  t: T; onPick: (d: Dish) => void; onRetry: () => void } & ExtraProps) {
  return (
    <div>
      <div className="notice warn" role="status">
        <Question />
        <div><TierBadge t={t} tier="abstain" /><b style={{ marginTop: 6 }}>{t("abstain.title")}</b><p>{t("abstain.body")}</p></div>
      </div>
      <div className="ask">
        <h3>{t("pick.title")}</h3>
        <DishPicker t={t} onPick={onPick} />
        <div className="row"><button type="button" className="btn" onClick={onRetry}>{t("photo.retry")}</button></div>
      </div>
      {fallback}
    </div>
  );
}

export function NonFoodPanel({ t, byFallback, onRetry, onEarlier }: {
  t: T; byFallback: boolean; onRetry: () => void; onEarlier: (() => void) | null;
}) {
  return (
    <div>
      <div className="notice err" role="status">
        <Alert />
        <div>
          <TierBadge t={t} tier="non_food" />
          <b style={{ marginTop: 6 }}>{t("nonfood.title")}</b>
          <p>{t(byFallback ? "nonfood.fallback" : "nonfood.blank")}</p>
        </div>
      </div>
      <div className="row">
        <button type="button" className="btn primary" onClick={onRetry}>{t("photo.retry")}</button>
        {onEarlier && <button type="button" className="btn" onClick={onEarlier}>{t("nonfood.earlier")}</button>}
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
        <h3>{t("pick.title")}</h3>
        <DishPicker t={t} onPick={onPick} />
      </div>
    </div>
  );
}

export function ErrorPanel({ t, kind, onRetry, onChoose }: {
  t: T; kind: "server" | "network" | "busy"; onRetry: () => void; onChoose: () => void;
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

export function RestrictionPicker({ t, avoid, onChange }: { t: T; avoid: Restriction[]; onChange: (next: Restriction[]) => void }) {
  return (
    <fieldset className="variant-group guard-picker">
      <legend><h3 style={{ marginTop: 16 }}>{t("guard.title")}</h3></legend>
      <div className="chips">
        {RESTRICTIONS.map((r) => (
          <label key={r} className="chip radio">
            <input type="checkbox" name="avoid" value={r} checked={avoid.includes(r)}
              onChange={(e) => onChange(RESTRICTIONS.filter((x) => (x === r ? e.target.checked : avoid.includes(x))))} />
            <span>{t(`restriction.${r}` as Key)}</span>
          </label>
        ))}
      </div>
      <p className="small" style={{ marginTop: 8 }}>{avoid.length ? t("guard.hint") : t("guard.empty")}</p>
    </fieldset>
  );
}

const GUARD_GLYPH = { safe: "✓", warning: "!", unknown: "?" } as const;

export function GuardResults({ t, results }: { t: T; results: GuardResult[] }) {
  return (
    <ul className="guard-list" aria-label={t("guard.title")}>
      {results.map((r) => (
        <li key={r.id} className={`guard-item guard-${r.status}`} data-testid={`guard-${r.id}`} data-status={r.status}>
          <div className="head">
            <b>{r.label}</b>
            <span className={`badge guard-badge-${r.status}`}>
              <span aria-hidden="true">{GUARD_GLYPH[r.status]}</span> {t(`guard.${r.status}` as Key)}
            </span>
          </div>
          {r.matches.length > 0 && (
            <div className="small"><b>{t("guard.because")}</b>
              <ul>{r.matches.map((m) => (
                <li key={m.ingredient}>{m.ingredient} <i>({t(`guard.${m.kind}` as Key)})</i></li>
              ))}</ul>
            </div>
          )}
          {r.status === "unknown" && (
            <div className="small"><b>{t("guard.unverified")}</b>
              <ul>{r.unverified.map((u) => <li key={u}>{u}</li>)}</ul>
            </div>
          )}
          <p className="small">{r.message}</p>
          {r.note && <p className="small">{r.note}</p>}
        </li>
      ))}
    </ul>
  );
}

export function IngredientsPanel({ t, dish, variant, data, failed, lang, avoid, onAvoid, onRetry, onChangeVariant, onBack, onNew }: {
  t: T; dish: Dish; variant: string | null; data: Ingredients | null; failed: boolean; lang: string;
  avoid: Restriction[]; onAvoid: (next: Restriction[]) => void;
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
        </>
      )}
      <RestrictionPicker t={t} avoid={avoid} onChange={onAvoid} />
      {data?.guard && (
        <>
          <GuardResults t={t} results={data.guard.restrictions} />
          <p className="small" style={{ marginTop: 8 }}>{data.guard.basis}</p>
        </>
      )}
      {data && (
        <div className="sources">
          <h3>{t("ingredients.sources")}</h3>
          <ol>
            {data.sources.map((s) => (
              <li key={s.url}><a href={s.url} target="_blank" rel="noopener noreferrer">{s.title}</a></li>
            ))}
          </ol>
          {lang !== "en" && <p className="small">{t("ingredients.sourceLang")}</p>}
        </div>
      )}
      <div className="row">
        {onChangeVariant && <button type="button" className="btn" onClick={onChangeVariant}>{t("variant.change")}</button>}
        <button type="button" className="btn" onClick={onBack}>{t("ingredients.back")}</button>
        <button type="button" className="btn primary" onClick={onNew}>{t("ingredients.new")}</button>
      </div>
    </div>
  );
}

export type EvalState = { kind: "idle" } | { kind: "loading" } | EvaluationOutcome;

function EvaluationBody({ t, e }: { t: T; e: Evaluation }) {
  const vars = { n: String(e.n), high: pct0(e.highFrom), abstain: pct0(e.abstainBelow) };
  const range = (p: [number, number] | null) => (p ? ` (${t("eval.interval")} ${pct1(p[0])}–${pct1(p[1])})` : "");
  const kinds = e.perVariant.filter((v) => variantsOf(v.target).includes(v.variant));
  return (
    <div data-testid="evaluation">
      <p>{t("eval.intro", vars)}</p>
      <p><b>{t("eval.accuracy")}</b> {pct1(e.accuracy)}{range(e.ci.accuracy)} · <b>{t("eval.macroF1")}</b> {pct1(e.macroF1)}{range(e.ci.macroF1)}</p>
      <h3 style={{ marginTop: 14 }}>{t("eval.levels")}</h3>
      <ul className="eval-levels">
        {(["high", "low", "abstain", "non_food"] as const).map((k) => (
          <li key={k}><TierBadge t={t} tier={k} /> <span>{t(`eval.level.${k}` as Key, vars)}</span></li>
        ))}
      </ul>
      {e.tiers && (
        <>
          <h3 style={{ marginTop: 14 }}>{t("eval.tiers")}</h3>
          <div className="table-wrap">
            <table>
              <thead><tr><th scope="col">{t("eval.level")}</th><th scope="col">{t("eval.photos")}</th>
                <th scope="col">{t("eval.share")}</th><th scope="col">{t("eval.correct")}</th></tr></thead>
              <tbody>
                {(["high", "low", "abstain"] as const).map((k) => (
                  <tr key={k} data-testid={`eval-tier-${k}`}>
                    <th scope="row">{t(`tier.${k}` as Key)}</th><td>{e.tiers![k].n}</td>
                    <td>{e.tiers![k].share === null ? "–" : pct1(e.tiers![k].share!)}</td>
                    <td>{k === "abstain" || e.tiers![k].accuracy === null ? "–" : pct1(e.tiers![k].accuracy!)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="small">{t("eval.tiers.note")}</p>
        </>
      )}
      <h3 style={{ marginTop: 14 }}>{t("eval.class")}</h3>
      <div className="table-wrap">
        <table>
          <thead><tr><th scope="col">{t("eval.class")}</th><th scope="col">{t("eval.precision")}</th>
            <th scope="col">{t("eval.recall")}</th><th scope="col">{t("eval.f1")}</th><th scope="col">{t("eval.photos")}</th></tr></thead>
          <tbody>
            {e.perClass.map((c) => (
              <tr key={c.dish} data-testid={`eval-class-${c.dish}`}>
                <th scope="row">{dishName(t, c.dish)}</th><td>{pct1(c.precision)}</td><td>{pct1(c.recall)}</td>
                <td>{pct1(c.f1)}</td><td>{c.support}{c.smallN ? ` · ${t("eval.few")}` : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {kinds.length > 0 && (
        <>
          <h3 style={{ marginTop: 14 }}>{t("eval.variants")}</h3>
          <div className="table-wrap">
            <table>
              <tbody>
                {kinds.map((v) => (
                  <tr key={`${v.target}/${v.variant}`} data-testid={`eval-variant-${v.variant}`}>
                    <th scope="row">{dishName(t, v.target)} · {variantName(t, v.target, v.variant)}</th>
                    <td>{pct1(v.recall)}</td><td>{v.n}{v.smallN ? ` · ${t("eval.few")}` : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      <h3 style={{ marginTop: 14 }}>{t("eval.limits")}</h3>
      <ul className="eval-limits">
        {e.limits.map((l) => <li key={l}>{t(`limit.${l}` as Key)}</li>)}
      </ul>
    </div>
  );
}

/** Test results and what each level means; the numbers come from the API (the loaded run's own files). */
export function EvaluationSection({ t, state, onOpen }: { t: T; state: EvalState; onOpen: () => void }) {
  return (
    <details className="card pane eval" onToggle={(ev) => { if ((ev.currentTarget as HTMLDetailsElement).open) onOpen(); }}>
      <summary><b>{t("eval.title")}</b></summary>
      <div aria-live="polite">
        {(state.kind === "idle" || state.kind === "loading") && <p className="small">{t("eval.loading")}</p>}
        {state.kind === "error" && <p className="small" role="alert">{t("eval.error")}</p>}
        {state.kind === "ok" && <EvaluationBody t={t} e={state.data} />}
      </div>
    </details>
  );
}
