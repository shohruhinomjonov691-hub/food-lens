"use client";
import { useRef, type KeyboardEvent, type PointerEvent } from "react";
import { type Corner, moveRect, type Rect, resizeCorner } from "@/lib/crop";
import type { Photo } from "@/lib/flow";

const CORNERS: Corner[] = ["nw", "ne", "sw", "se"];
const STEP = 0.02;

type Drag = { mode: "move" | Corner; x: number; y: number; start: Rect; pointer: number };

export function CropEditor({ photo, crop, onChange, label }: {
  photo: Photo; crop: Rect; onChange: (r: Rect) => void; label: string;
}) {
  const box = useRef<HTMLDivElement>(null);
  const drag = useRef<Drag | null>(null);

  const begin = (mode: Drag["mode"]) => (e: PointerEvent<HTMLElement>) => {
    e.preventDefault();
    e.stopPropagation();
    (e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId);
    drag.current = { mode, x: e.clientX, y: e.clientY, start: crop, pointer: e.pointerId };
  };
  const move = (e: PointerEvent<HTMLElement>) => {
    const d = drag.current;
    const r = box.current?.getBoundingClientRect();
    if (!d || !r || d.pointer !== e.pointerId || r.width === 0) return;
    e.stopPropagation();
    const dx = (e.clientX - d.x) / r.width, dy = (e.clientY - d.y) / r.height;
    onChange(d.mode === "move" ? moveRect(d.start, dx, dy) : resizeCorner(d.start, d.mode, dx, dy));
  };
  const end = (e: PointerEvent<HTMLElement>) => {
    if (drag.current?.pointer === e.pointerId) drag.current = null;
  };
  const key = (e: KeyboardEvent<HTMLDivElement>) => {
    const dir: Record<string, [number, number]> = {
      ArrowLeft: [-STEP, 0], ArrowRight: [STEP, 0], ArrowUp: [0, -STEP], ArrowDown: [0, STEP] };
    const v = dir[e.key];
    if (!v) return;
    e.preventDefault();
    onChange(e.shiftKey ? resizeCorner(crop, "se", v[0], v[1]) : moveRect(crop, v[0], v[1]));
  };

  const ratio = photo.width / photo.height;
  return (
    <div ref={box} className="photo" style={{ aspectRatio: `${photo.width} / ${photo.height}`,
      width: `min(100%, calc(62vh * ${ratio}))` }}>
      {/* eslint-disable-next-line @next/next/no-img-element -- local object URL, never optimized */}
      <img src={photo.url} alt="" draggable={false} />
      <div className="frame" role="group" aria-label={label} tabIndex={0} onKeyDown={key}
        style={{ left: `${crop.x * 100}%`, top: `${crop.y * 100}%`, width: `${crop.w * 100}%`, height: `${crop.h * 100}%` }}
        onPointerDown={begin("move")} onPointerMove={move} onPointerUp={end} onPointerCancel={end}>
        {CORNERS.map((c) => (
          <span key={c} className={`handle ${c}`} data-corner={c} aria-hidden="true"
            onPointerDown={begin(c)} onPointerMove={move} onPointerUp={end} onPointerCancel={end} />
        ))}
      </div>
    </div>
  );
}
