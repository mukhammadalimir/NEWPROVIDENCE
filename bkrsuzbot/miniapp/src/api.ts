import { tg } from "./telegram";
import type { Favorite, Me, SearchResult, Explain } from "./types";

export class ApiError extends Error {
  constructor(public status: number, public code: string) {
    super(code);
  }
}

function headers(): Record<string, string> {
  const h: Record<string, string> = { "Content-Type": "application/json" };
  if (tg?.initData) h["Authorization"] = `tma ${tg.initData}`;
  // Вне Telegram — только для локальной разработки (сервер принимает это лишь при APP_ENV=dev).
  else h["X-Dev-User"] = "1";
  return h;
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  let r: Response;
  try {
    r = await fetch(path, { method, headers: headers(), body: body ? JSON.stringify(body) : undefined });
  } catch {
    throw new ApiError(0, "network");
  }
  if (!r.ok) {
    let code = "server";
    try {
      code = (await r.json()).detail?.code ?? code;
    } catch {
      /* не JSON */
    }
    throw new ApiError(r.status, code);
  }
  return r.json() as Promise<T>;
}

export const api = {
  me: () => request<Me>("GET", "/api/me"),
  settings: (s: Partial<Pick<Me, "ui_lang" | "target_lang" | "voice">>) => request("PUT", "/api/me/settings", s),
  deleteMe: () => request("DELETE", "/api/me"),
  search: (q: string, source?: string, target?: string) =>
    request<SearchResult>("POST", "/api/search", { q, source, target }),
  explain: (entryId: number, lang: string) =>
    request<Explain>("GET", `/api/explain?entry_id=${entryId}&lang=${lang}`),
  history: () => request<{ query: string; kind: string }[]>("GET", "/api/history"),
  clearHistory: () => request("DELETE", "/api/history"),
  favorites: () => request<Favorite[]>("GET", "/api/favorites"),
  addFavorite: (f: { headword: string; pinyin: string; gloss: string; entry_id: number | null }) =>
    request<Favorite>("POST", "/api/favorites", f),
  removeFavorite: (id: number) => request("DELETE", `/api/favorites/${id}`),
  clearFavorites: () => request("DELETE", "/api/favorites"),
  reviewNext: () => request<(Favorite & { due_count: number }) | null>("GET", "/api/review/next"),
  reviewAnswer: (id: number, knew: boolean) => request("POST", `/api/review/${id}`, { knew }),
  report: (query: string, message: string, entry_id?: number | null) =>
    request("POST", "/api/report", { query, message, entry_id }),
  admin: {
    stats: () => request<any>("GET", "/api/admin/stats"),
    reports: () => request<any[]>("GET", "/api/admin/reports"),
    resolve: (id: number) => request("POST", `/api/admin/reports/${id}/resolve`),
    entries: (q: string) => request<any[]>("GET", `/api/admin/entries?q=${encodeURIComponent(q)}`),
    create: (e: any) => request<any>("POST", "/api/admin/entries", e),
    update: (id: number, e: any) => request<any>("PUT", `/api/admin/entries/${id}`, e),
    remove: (id: number) => request("DELETE", `/api/admin/entries/${id}`),
    flags: (flags: Record<string, boolean>) => request<Record<string, boolean>>("PUT", "/api/admin/flags", { flags }),
  },
};

/** Аудио загружается с авторизацией и проигрывается из blob. */
const audioCache = new Map<string, string>();
let current: HTMLAudioElement | null = null;

export async function playAudio(text: string, slow: boolean, voice?: string): Promise<void> {
  const key = `${voice ?? ""}|${slow}|${text}`;
  let url = audioCache.get(key);
  if (!url) {
    const qs = new URLSearchParams({ text, slow: String(slow) });
    if (voice) qs.set("voice", voice);
    let r: Response;
    try {
      r = await fetch(`/api/tts?${qs}`, { headers: headers() });
    } catch {
      throw new ApiError(0, "network");
    }
    if (!r.ok) {
      let code = "tts_failed";
      try {
        code = (await r.json()).detail?.code ?? code;
      } catch {
        /* ignore */
      }
      throw new ApiError(r.status, code);
    }
    url = URL.createObjectURL(await r.blob());
    audioCache.set(key, url);
  }
  current?.pause();
  current = new Audio(url);
  await current.play();
}
