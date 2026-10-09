// Crop rectangle in normalized image coordinates (0..1), and exporting the confirmed crop.
export type Rect = { x: number; y: number; w: number; h: number };
export type Corner = "nw" | "ne" | "sw" | "se";

export const MIN_SIZE = 0.1;            // the frame never gets smaller than 10% of a side
export const DEFAULT_RECT: Rect = { x: 0.05, y: 0.05, w: 0.9, h: 0.9 };
export const OUTPUT_MAX_SIDE = 2048;    // the API resizes to 256 px anyway; keeps uploads small
export const OUTPUT_TYPE = "image/jpeg";
export const OUTPUT_QUALITY = 0.92;

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

export function clampRect(r: Rect): Rect {
  const w = clamp(r.w, MIN_SIZE, 1);
  const h = clamp(r.h, MIN_SIZE, 1);
  return { x: clamp(r.x, 0, 1 - w), y: clamp(r.y, 0, 1 - h), w, h };
}

export function moveRect(r: Rect, dx: number, dy: number): Rect {
  return clampRect({ ...r, x: r.x + dx, y: r.y + dy });
}

export function resizeCorner(r: Rect, corner: Corner, dx: number, dy: number): Rect {
  let left = r.x, top = r.y, right = r.x + r.w, bottom = r.y + r.h;
  if (corner === "nw" || corner === "sw") left = clamp(left + dx, 0, right - MIN_SIZE);
  else right = clamp(right + dx, left + MIN_SIZE, 1);
  if (corner === "nw" || corner === "ne") top = clamp(top + dy, 0, bottom - MIN_SIZE);
  else bottom = clamp(bottom + dy, top + MIN_SIZE, 1);
  return { x: left, y: top, w: right - left, h: bottom - top };
}

export function toPixels(r: Rect, width: number, height: number) {
  const sx = Math.round(r.x * width), sy = Math.round(r.y * height);
  const sw = Math.max(1, Math.min(width - sx, Math.round(r.w * width)));
  const sh = Math.max(1, Math.min(height - sy, Math.round(r.h * height)));
  return { sx, sy, sw, sh };
}

export function outputSize(sw: number, sh: number, maxSide = OUTPUT_MAX_SIDE) {
  const s = Math.min(1, maxSide / Math.max(sw, sh));
  return { width: Math.max(1, Math.round(sw * s)), height: Math.max(1, Math.round(sh * s)) };
}

function canvasToBlob(canvas: HTMLCanvasElement, type: string, quality?: number): Promise<Blob> {
  return new Promise((resolve, reject) =>
    canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("canvas export failed"))), type, quality));
}

function releaseCanvas(canvas: HTMLCanvasElement) {
  canvas.width = 0;   // frees the pixel buffer right away (important on phones)
  canvas.height = 0;
}

/** Draws the confirmed crop of an (EXIF-oriented) image into a new JPEG blob. */
export async function cropToBlob(image: CanvasImageSource, width: number, height: number, rect: Rect): Promise<Blob> {
  const { sx, sy, sw, sh } = toPixels(clampRect(rect), width, height);
  const out = outputSize(sw, sh);
  const canvas = document.createElement("canvas");
  canvas.width = out.width;
  canvas.height = out.height;
  try {
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("no 2d context");
    ctx.imageSmoothingQuality = "high";
    ctx.drawImage(image, sx, sy, sw, sh, 0, 0, out.width, out.height);
    return await canvasToBlob(canvas, OUTPUT_TYPE, OUTPUT_QUALITY);
  } finally {
    releaseCanvas(canvas);
  }
}

/** Returns the image rotated 90° clockwise as a PNG blob (lossless). */
export async function rotateBlob(image: CanvasImageSource, width: number, height: number): Promise<Blob> {
  const canvas = document.createElement("canvas");
  canvas.width = height;
  canvas.height = width;
  try {
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("no 2d context");
    ctx.translate(height, 0);
    ctx.rotate(Math.PI / 2);
    ctx.drawImage(image, 0, 0);
    return await canvasToBlob(canvas, "image/png");
  } finally {
    releaseCanvas(canvas);
  }
}
