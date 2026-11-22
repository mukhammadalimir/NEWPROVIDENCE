// Автономный режим Mini App (без сервера): тот же интерфейс, что и api.ts.
// Данные пользователя: Telegram CloudStorage (привязано к пользователю и боту,
// синхронизируется между устройствами) + копия в localStorage.
// Озвучка: встроенный китайский голос устройства (Web Speech API), если он есть.

import { ApiError } from "../errors";
import { tg } from "../telegram";
import type { Favorite, Lang, Me } from "../types";
import { entryById, loadDictionary, search } from "./engine";

interface StateData {
  settings: { ui_lang?: Lang; target_lang?: Lang; voice?: string };
  fav: Favorite[];
  hist: { query: string; kind: string }[];
  nextId: number;
}

const KEY = "bk";
const CHUNK = 4000; // лимит CloudStorage — 4096 символов на значение
let state: StateData = { settings: {}, fav: [], hist: [], nextId: 1 };
let ready: Promise<void> | null = null;

interface Cloud {
  getItem(k: string, cb: (e: string | null, v?: string) => void): void;
  setItem(k: string, v: string, cb?: (e: string | null) => void): void;
  removeItem(k: string, cb?: (e: string | null) => void): void;
}
const cloud = (): Cloud | null => {
  const w = tg as unknown as { CloudStorage?: Cloud; isVersionAtLeast?: (v: string) => boolean } | null;
  return w?.CloudStorage && w.isVersionAtLeast?.("6.9") ? w.CloudStorage : null;
};
const cget = (c: Cloud, k: string) => new Promise<string>((res) => c.getItem(k, (e, v) => res(e ? "" : v ?? "")));

async function load() {
  try {
    const local = localStorage.getItem(KEY);
    if (local) state = { ...state, ...JSON.parse(local) };
  } catch { /* приватный режим */ }
  const c = cloud();
  if (!c) return;
  const n = Number(await cget(c, `${KEY}_n`)) || 0;
  if (!n) return;
  const parts = await Promise.all([...Array(n).keys()].map((i) => cget(c, `${KEY}_${i}`)));
  try { state = { ...state, ...JSON.parse(parts.join("")) }; } catch { /* повреждено — оставляем локальную копию */ }
}

let saveTimer: number | undefined;
function save() {
  const json = JSON.stringify(state);
  try { localStorage.setItem(KEY, json); } catch { /* ignore */ }
  window.clearTimeout(saveTimer);
  saveTimer = window.setTimeout(() => {
    const c = cloud();
    if (!c) return;
    const n = Math.ceil(json.length / CHUNK);
    for (let i = 0; i < n; i++) c.setItem(`${KEY}_${i}`, json.slice(i * CHUNK, (i + 1) * CHUNK));
    c.setItem(`${KEY}_n`, String(n));
  }, 400);
}

const init = () => (ready ??= load());

// --- Голос устройства ---
function zhVoices(): Promise<SpeechSynthesisVoice[]> {
  if (!("speechSynthesis" in window)) return Promise.resolve([]);
  const pick = () => speechSynthesis.getVoices().filter((v) => /^(zh|cmn)/i.test(v.lang) && !/HK|yue/i.test(v.lang));
  const now = pick();
  if (now.length) return Promise.resolve(now);
  return new Promise((res) => {
    const done = () => res(pick());
    speechSynthesis.addEventListener("voiceschanged", done, { once: true });
    setTimeout(done, 1200);
  });
}

export async function speak(text: string, slow: boolean, voice?: string): Promise<void> {
  const voices = await zhVoices();
  if (!voices.length) throw new ApiError(503, "tts_unavailable");
  speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.lang = "zh-CN";
  u.voice = voices.find((v) => v.name === voice) ?? voices.find((v) => /zh[-_]CN/i.test(v.lang)) ?? voices[0];
  u.rate = slow ? 0.6 : 0.9;
  speechSynthesis.speak(u);
}

const user = () => tg?.initDataUnsafe.user;
const ok = { ok: true };

export const offlineApi = {
  me: async (): Promise<Me> => {
    await init();
    const voices = await zhVoices();
    const hint: Lang = user()?.language_code?.startsWith("ru") ? "ru" : "uz";
    return {
      id: user()?.id ?? 0, first_name: "", ui_lang: state.settings.ui_lang ?? hint,
      target_lang: state.settings.target_lang ?? hint, voice: state.settings.voice ?? "",
      is_admin: false, offline: true,
      services: { translate: false, tts: voices.length > 0, ai: false, collocations: true },
      voices: voices.map((v) => v.name), bot_username: import.meta.env.VITE_BOT_USERNAME ?? "",
    };
  },
  settings: async (s: Partial<StateData["settings"]>) => { state.settings = { ...state.settings, ...s }; save(); return ok; },
  deleteMe: async () => { state = { settings: {}, fav: [], hist: [], nextId: 1 }; save(); return ok; },
  search: async (q: string, source?: string, target?: string) => {
    await init();
    const r = await search(q, { userTarget: state.settings.target_lang ?? "uz", source, target });
    if (["word", "candidates", "text"].includes(r.type)) {
      state.hist = [{ query: r.query, kind: r.type }, ...state.hist.filter((h) => h.query !== r.query)].slice(0, 50);
      save();
    }
    for (const c of r.cards ?? []) for (const rd of c.readings) {
      rd.favorite_id = state.fav.find((f) => f.headword === c.headword && f.pinyin === rd.pinyin)?.id ?? null;
    }
    return r;
  },
  explain: async () => { throw new ApiError(503, "ai_unavailable"); },
  history: async () => { await init(); return state.hist.slice(0, 30); },
  clearHistory: async () => { state.hist = []; save(); return ok; },
  favorites: async () => { await init(); return [...state.fav].reverse(); },
  addFavorite: async (f: { headword: string; pinyin: string; gloss: string; entry_id: number | null }) => {
    const existing = state.fav.find((x) => x.headword === f.headword && x.pinyin === f.pinyin);
    if (existing) return existing;
    const fav: Favorite = { ...f, id: state.nextId++, box: 1, due_at: new Date().toISOString() };
    state.fav.push(fav);
    save();
    return fav;
  },
  removeFavorite: async (id: number) => { state.fav = state.fav.filter((f) => f.id !== id); save(); return ok; },
  clearFavorites: async () => { state.fav = []; save(); return ok; },
  reviewNext: async () => {
    await init();
    if (!state.fav.length) return null;
    const now = Date.now();
    const due = state.fav.filter((f) => Date.parse(f.due_at) <= now).sort((a, b) => a.box - b.box || Date.parse(a.due_at) - Date.parse(b.due_at));
    const card = due[0] ?? [...state.fav].sort((a, b) => Date.parse(a.due_at) - Date.parse(b.due_at))[0];
    return { ...card, due_count: due.length };
  },
  reviewAnswer: async (id: number, knew: boolean) => {
    const f = state.fav.find((x) => x.id === id);
    if (f) {
      const days = [0, 1, 3, 7, 14, 30];
      f.box = knew ? Math.min(f.box + 1, days.length - 1) : 1;
      f.due_at = new Date(Date.now() + days[f.box] * 86400000).toISOString();
      save();
    }
    return ok;
  },
  report: async () => ok,
  admin: {} as never,
  preload: () => loadDictionary(),
  entry: entryById,
};
