import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

// jsdom has no object URLs; tests can inspect these spies.
let n = 0;
Object.defineProperty(URL, "createObjectURL", { configurable: true, writable: true, value: vi.fn(() => `blob:test/${++n}`) });
Object.defineProperty(URL, "revokeObjectURL", { configurable: true, writable: true, value: vi.fn() });

// Node 25 ships its own (file-backed, here unusable) localStorage that shadows jsdom's: use memory.
class MemoryStorage {
  private m = new Map<string, string>();
  get length() { return this.m.size; }
  clear() { this.m.clear(); }
  getItem(k: string) { return this.m.has(k) ? this.m.get(k)! : null; }
  key(i: number) { return [...this.m.keys()][i] ?? null; }
  removeItem(k: string) { this.m.delete(k); }
  setItem(k: string, v: string) { this.m.set(k, String(v)); }
}
const storage = new MemoryStorage();
Object.defineProperty(window, "localStorage", { configurable: true, value: storage });
Object.defineProperty(globalThis, "localStorage", { configurable: true, value: storage });

// jsdom's Blob lacks arrayBuffer(); browsers have it.
if (!Blob.prototype.arrayBuffer) {
  Blob.prototype.arrayBuffer = function arrayBuffer(this: Blob) {
    return new Promise<ArrayBuffer>((resolve, reject) => {
      const r = new FileReader();
      r.onload = () => resolve(r.result as ArrayBuffer);
      r.onerror = () => reject(r.error);
      r.readAsArrayBuffer(this);
    });
  };
}

afterEach(() => {
  cleanup();
  storage.clear();
});
