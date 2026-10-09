// Checks done in the browser before anything is sent (the API repeats them).
export const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;
export const MAX_SIDE = 8000;
export const MAX_PIXELS = 25_000_000;

export type FileCheck = { ok: true; format: "JPEG" | "PNG" | "WEBP" } | { ok: false; code: string };

export function sniff(head: Uint8Array): "JPEG" | "PNG" | "WEBP" | null {
  const at = (i: number, bytes: number[]) => bytes.every((b, j) => head[i + j] === b);
  if (at(0, [0xff, 0xd8, 0xff])) return "JPEG";
  if (at(0, [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])) return "PNG";
  if (at(0, [0x52, 0x49, 0x46, 0x46]) && at(8, [0x57, 0x45, 0x42, 0x50])) return "WEBP";
  return null;
}

export async function checkFile(file: Blob): Promise<FileCheck> {
  if (file.size === 0) return { ok: false, code: "empty_file" };
  if (file.size > MAX_UPLOAD_BYTES) return { ok: false, code: "file_too_large" };
  const format = sniff(new Uint8Array(await file.slice(0, 16).arrayBuffer()));
  return format ? { ok: true, format } : { ok: false, code: "unsupported_format" };
}

export function checkDimensions(width: number, height: number): string | null {
  if (!(width > 0 && height > 0)) return "corrupt_image";
  if (Math.max(width, height) > MAX_SIDE || width * height > MAX_PIXELS) return "image_too_large";
  return null;
}
