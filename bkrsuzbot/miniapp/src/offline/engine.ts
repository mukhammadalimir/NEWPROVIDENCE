// Автономный поиск по словарю прямо в Mini App (порт backend/app/services/search.py).
// Данные: data/cedict.json (CC-CEDICT, CC BY-SA 4.0) и data/meta.json (редакционные карточки).
// Машинного перевода и AI здесь нет — фразы разбираются по словам, это честно помечается.

import type { Candidate, Card, Kind, Reading, SearchResult, Source } from "../types";
import * as tx from "./text";

interface Entry {
  id: number;
  source: "cedict" | "curated";
  simp: string;
  trad: string;
  pin: string;
  toneKey: string;
  key: string;
  senses: { pos?: unknown; en?: string[]; uz?: string[]; ru?: string[] }[];
  mw: string | null;
  usage: Record<string, string>;
  coll: { zh: string; pinyin?: string; uz?: string; ru?: string }[];
  ex: { zh: string; pinyin?: string; uz?: string; ru?: string }[];
  verified: boolean;
  freq: number;
}

let entries: Entry[] = [];
const bySimp = new Map<string, Entry[]>();
const byTrad = new Map<string, Entry[]>();
const byKey = new Map<string, Entry[]>();
const byToneKey = new Map<string, Entry[]>();
const gloss = { uz: new Map<string, Entry[]>(), ru: new Map<string, Entry[]>() };
let loading: Promise<void> | null = null;

const push = <K,>(m: Map<K, Entry[]>, k: K, e: Entry) => {
  const list = m.get(k);
  if (list) list.push(e); else m.set(k, [e]);
};

export function loadDictionary(base = "./data/"): Promise<void> {
  if (loading) return loading;
  loading = (async () => {
    const [meta, cedict] = await Promise.all([
      fetch(base + "meta.json").then((r) => { if (!r.ok) throw new Error("meta"); return r.json(); }),
      fetch(base + "cedict.json").then((r) => { if (!r.ok) throw new Error("cedict"); return r.json(); }),
    ]);
    tx.setSyllables(meta.syllables);
    const freq = new Map<string, number>();
    (cedict as [string, string, string, string, string, number][]).forEach(([simp, trad, pin, defs, mw, f]) => {
      const [toneKey, key] = tx.keysFromNumbered(pin);
      entries.push({ id: entries.length, source: "cedict", simp, trad: trad || simp, pin, toneKey, key,
        senses: [{ en: defs ? defs.split("/") : [] }], mw: mw || null, usage: {}, coll: [], ex: [],
        verified: false, freq: f });
      if (f) freq.set(simp, f);
    });
    for (const c of meta.curated) {
      const [toneKey, key] = tx.keysFromNumbered(c.pinyin);
      const e: Entry = { id: entries.length, source: "curated", simp: c.simplified, trad: c.traditional || c.simplified,
        pin: c.pinyin, toneKey, key, senses: c.senses ?? [], mw: c.measure_word ?? null, usage: c.usage ?? {},
        coll: c.collocations ?? [], ex: c.examples ?? [], verified: Boolean(c.verified), freq: freq.get(c.simplified) ?? 0 };
      entries.push(e);
      for (const lang of ["uz", "ru"] as const) {
        const terms = new Set<string>();
        for (const s of e.senses) for (const item of s[lang] ?? []) for (const part of item.split(",")) {
          const t = lang === "uz" ? tx.normUz(part) : tx.normRu(part.trim());
          if (t) terms.add(t);
        }
        terms.forEach((t) => push(gloss[lang], t, e));
      }
    }
    for (const e of entries) {
      push(bySimp, e.simp, e);
      if (e.trad !== e.simp) push(byTrad, e.trad, e);
      push(byKey, e.key, e);
      push(byToneKey, e.toneKey, e);
    }
  })();
  loading.catch(() => { loading = null; entries = []; });
  return loading;
}

const findHead = (t: string) => [...(bySimp.get(t) ?? []), ...(byTrad.get(t) ?? [])];
const isProper = (e: Entry) => e.pin[0] !== e.pin[0].toLowerCase();
const pos = (p: unknown, lang: string) => (p && typeof p === "object" ? (p as Record<string, string>)[lang] : (p as string)) ?? null;

function group(list: Entry[]): Map<string, Entry[]> {
  const m = new Map<string, Entry[]>();
  for (const e of list) push(m, e.simp, e);
  return m;
}

const WEAK = /^(old |archaic )?(variant of|surname|used in|see )/i;

function shortGloss(list: Entry[], lang: string): [string, Kind | ""] {
  for (const e of list) if (e.source === "curated") for (const s of e.senses) {
    const items = (s as Record<string, string[]>)[lang];
    if (items?.length) return [items.slice(0, 3).join(", "), "curated"];
  }
  const defs = [...list].sort((a, b) => Number(isProper(a)) - Number(isProper(b))).flatMap((e) => e.senses.flatMap((s) => s.en ?? []));
  const good = defs.filter((d) => !WEAK.test(d));
  const pick = good.length ? good : defs;
  return pick.length ? [pick.slice(0, 2).join("; "), "cedict_en"] : ["", ""];
}

function matchesReading(c: Entry, head: string, toneKey: string): boolean {
  const parts = c.pin.toLowerCase().replace(/u:/g, "v").split(" ");
  if (parts.length !== [...c.simp].length) return false;
  const i = [...c.simp].findIndex((_, k) => [...c.simp].slice(k, k + [...head].length).join("") === head);
  const sub = parts.slice(i, i + [...head].length).join("");
  const s5 = (s: string) => s.replace(/5/g, "");
  return sub === toneKey || s5(sub) === s5(toneKey) || (tx.keysFromNumbered(sub)[1] === tx.keysFromNumbered(toneKey)[1] && sub.includes("5"));
}

function collocationPool(head: string): Entry[] {
  const n = [...head].length;
  const out: Entry[] = [];
  for (const e of entries) {
    if (e.source !== "cedict" || !e.freq || e.simp === head) continue;
    const len = [...e.simp].length;
    if (len > n && len <= n + 3 && e.simp.includes(head)) out.push(e);
  }
  return out.sort((a, b) => b.freq - a.freq).slice(0, 80);
}

function buildCards(list: Entry[], lang: string): Card[] {
  const cards: Card[] = [];
  for (const [head, items] of group(list)) {
    const trad = items.find((e) => e.trad !== head)?.trad ?? null;
    const readings = new Map<string, Entry[]>();
    [...items].sort((a, b) => Number(a.source !== "curated") - Number(b.source !== "curated") || Number(isProper(a)) - Number(isProper(b)) || a.id - b.id)
      .forEach((e) => push(readings, `${e.toneKey}|${isProper(e)}`, e));
    const pool = collocationPool(head);
    const out: Reading[] = [];
    for (const [k, rs] of readings) {
      const toneKey = k.split("|")[0];
      const curated = rs.filter((e) => e.source === "curated");
      const cedict = rs.filter((e) => e.source === "cedict");
      const main = curated[0] ?? rs[0];
      const coll = curated.flatMap((e) => e.coll.map((c) => ({ zh: c.zh, pinyin: c.pinyin ?? "", gloss: (c as Record<string, string>)[lang] ?? "", gloss_kind: "curated" as Kind })));
      const seen = new Set(coll.map((c) => c.zh));
      for (const c of pool) {
        if (coll.length >= 6) break;
        if (seen.has(c.simp) || !matchesReading(c, head, toneKey)) continue;
        seen.add(c.simp);
        coll.push({ zh: c.simp, pinyin: tx.wordMarks(c.pin), gloss: (c.senses[0].en ?? []).slice(0, 2).join("; "), gloss_kind: "cedict_en" });
      }
      out.push({
        entry_id: main.id, key: toneKey, pinyin: tx.wordMarks(main.pin), pinyin_num: main.pin,
        approx: tx.approxUz(main.pin), proper: isProper(main),
        measure_word: [...curated, ...cedict].find((e) => e.mw)?.mw ?? null,
        senses: curated.flatMap((e) => e.senses.filter((s) => (s as Record<string, string[]>)[lang]?.length).map((s) => ({
          pos: pos(s.pos, lang), items: (s as Record<string, string[]>)[lang], kind: "curated" as Kind, verified: e.verified }))),
        english: [...cedict, ...curated].flatMap((e) => e.senses.flatMap((s) => s.en ?? [])),
        english_mt: null,
        usage: curated.find((e) => e.usage[lang]) ? { text: curated.find((e) => e.usage[lang])!.usage[lang], kind: "curated" } : null,
        examples: curated.flatMap((e) => e.ex.map((x) => ({ zh: x.zh, pinyin: x.pinyin ?? sentencePinyin(x.zh), translation: (x as Record<string, string>)[lang] ?? null, kind: "curated" as Kind }))),
        collocations: coll,
        has_curated: curated.length > 0,
      });
    }
    cards.push({ headword: head, traditional: trad, readings: out });
  }
  return cards;
}

function candidates(groups: Map<string, Entry[]>, lang: string, want?: string): Candidate[] {
  const out: (Candidate & { r: [number, number] })[] = [];
  for (const [head, all] of groups) {
    const items = want ? (all.filter((e) => e.key === want).length ? all.filter((e) => e.key === want) : all) : all;
    const [g, kind] = shortGloss(items, lang);
    let py = [...new Set(items.filter((e) => !isProper(e)).map((e) => tx.wordMarks(e.pin)))];
    if (!py.length) py = [...new Set(items.map((e) => tx.wordMarks(e.pin)))];
    out.push({ headword: head, pinyin: py.slice(0, 3).join(", "), gloss: g, gloss_kind: (kind || "cedict_en") as Kind,
      entry_id: items[0].id, r: [kind === "curated" ? 0 : 1, -Math.max(...items.map((e) => e.freq))] });
  }
  return out.sort((a, b) => a.r[0] - b.r[0] || a.r[1] - b.r[1]).map(({ r: _r, ...c }) => c);
}

/** Разбор китайского текста: прямой максимальный поиск по словарю. */
function segmentZh(text: string): string[] {
  const chars = [...text];
  const words: string[] = [];
  for (let i = 0; i < chars.length;) {
    let len = 1;
    if (tx.HAN_RE.test(chars[i])) {
      for (let l = Math.min(6, chars.length - i); l > 1; l--) {
        if (findHead(chars.slice(i, i + l).join("")).length) { len = l; break; }
      }
    }
    words.push(chars.slice(i, i + len).join(""));
    i += len;
  }
  return words;
}

function readingFor(word: string): string {
  const list = findHead(word).filter((e) => !isProper(e));
  const best = list.find((e) => e.source === "curated") ?? list.sort((a, b) => b.freq - a.freq)[0];
  return best ? tx.wordMarks(best.pin) : word;
}

export function sentencePinyin(text: string): string {
  return segmentZh(text).map((w) => (tx.HAN_RE.test(w) ? readingFor(w) : w)).join(" ")
    .replace(/\s+([，。！？、,.!?;:])/g, "$1");
}

export function entryById(id: number) {
  return entries[id];
}

export async function search(query: string, opts: { userTarget: string; source?: string; target?: string }): Promise<SearchResult> {
  await loadDictionary();
  const q = query.trim().replace(/\s+/g, " ").slice(0, 500);
  const base: SearchResult = { type: "not_found", query: q, notices: [], alternatives: [] };
  if (!q) return base;
  let source = opts.source;
  if (!source || !["zh", "pinyin", "uz", "ru"].includes(source)) {
    const d = tx.detect(q);
    if (!d.lang) return { ...base, type: "choose", options: d.options as Source[] };
    source = d.lang;
    base.alternatives = d.alternatives as Source[];
  }
  const lang = source === "zh" || source === "pinyin" ? (opts.target === "ru" || opts.target === "uz" ? opts.target : opts.userTarget) : "zh";
  Object.assign(base, { source_lang: source, target_lang: lang });
  const meaningLang = source === "uz" || source === "ru" ? source : lang;

  if (source === "zh") {
    const han = q.replace(/[\s，。！？、,.!?]/g, "");
    if ([...han].length <= 6) {
      const found = findHead(han);
      if (found.length) return { ...base, type: "word", cards: buildCards(found, meaningLang) };
    }
    const words = segmentZh(q);
    const seen = new Set<string>();
    const breakdown = [];
    for (const w of words) {
      if (seen.has(w) || !tx.HAN_RE.test(w)) continue;
      seen.add(w);
      const list = findHead(w);
      if (!list.length) continue;
      const [g, kind] = shortGloss(list, meaningLang);
      breakdown.push({ zh: w, pinyin: readingFor(w), gloss: g, gloss_kind: (kind || "cedict_en") as Kind });
    }
    return { ...base, type: "text", notices: ["translate_unavailable"], text: {
      source: q, translation: null, zh: q, pinyin: sentencePinyin(q), words: breakdown.slice(0, 15), provider: null } };
  }

  if (source === "pinyin") {
    const syls = tx.parsePinyin(q);
    if (!syls) return base;
    let list = (syls.every((s) => s.tone) ? byToneKey.get(tx.toneKey(syls)) : byKey.get(tx.tonelessKey(syls))) ?? [];
    if (tx.hasTones(syls) && !syls.every((s) => s.tone)) {
      list = list.filter((e) => {
        const p = tx.parsePinyin(e.toneKey);
        return p && p.length === syls.length && syls.every((s, i) => !s.tone || s.tone === (p[i].tone ?? 5));
      });
    }
    const groups = group([...list].sort((a, b) => b.freq - a.freq));
    if (!groups.size) return base;
    if (groups.size === 1) return { ...base, type: "word", cards: buildCards(list, meaningLang) };
    return { ...base, type: "candidates", candidates: candidates(groups, meaningLang, tx.tonelessKey(syls)).slice(0, 20) };
  }

  // Узбекский / русский → китайский (только по словарю редакции)
  const term = source === "uz" ? tx.normUz(q) : tx.normRu(q);
  const found = gloss[source as "uz" | "ru"].get(term) ?? [];
  const groups = group(found);
  if (groups.size === 1) {
    const keys = new Set(found.map((e) => `${e.simp}|${e.toneKey}|${isProper(e)}`));
    const extra = (bySimp.get(found[0].simp) ?? []).filter((e) => e.source === "cedict" && keys.has(`${e.simp}|${e.toneKey}|${isProper(e)}`));
    return { ...base, type: "word", cards: buildCards([...found, ...extra], meaningLang) };
  }
  if (groups.size > 1) return { ...base, type: "candidates", candidates: candidates(groups, meaningLang) };
  return { ...base, notices: ["translate_unavailable"] };
}
