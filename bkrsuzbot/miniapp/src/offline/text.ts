// Порт backend/app/text/* для автономного режима (без сервера).

export const HAN_RE = /[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]/;
const HAN_G = /[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]/g;
const CYR_G = /[а-яёА-ЯЁўқғҳЎҚҒҲ]/g;
const LAT_G = /[a-zA-Zāáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜü]/g;
const TONE_MARK_RE = /[āáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜ]/i;

let SYL = new Set<string>();
export function setSyllables(list: string[]) { SYL = new Set(list); }

export interface Syl { text: string; tone: number | null }

const MARKS: Record<string, number> = { "\u0304": 1, "\u0301": 2, "\u030c": 3, "\u0300": 4 };

function stripMarks(chunk: string): [string, (number | null)[]] {
  const out: string[] = [];
  const tones: (number | null)[] = [];
  for (const ch of chunk.normalize("NFD")) {
    if (MARKS[ch]) { if (tones.length) tones[tones.length - 1] = MARKS[ch]; continue; }
    if (ch === "\u0308") { if (out[out.length - 1] === "u") out[out.length - 1] = "v"; continue; }
    out.push(ch); tones.push(null);
  }
  return [out.join(""), tones];
}

function segment(word: string): [number, number][] | null {
  const n = word.length;
  const best: ([number, number][] | null)[] = new Array(n + 1).fill(null);
  best[0] = [];
  for (let i = 0; i < n; i++) {
    if (!best[i]) continue;
    for (let j = Math.min(n, i + 6); j > i; j--) {
      if (SYL.has(word.slice(i, j))) {
        const cand = [...best[i]!, [i, j] as [number, number]];
        if (!best[j] || cand.length < best[j]!.length) best[j] = cand;
      }
    }
  }
  return best[n];
}

export function parsePinyin(text: string): Syl[] | null {
  text = text.trim().toLowerCase().replace(/u:/g, "v").replace(/ü/g, "v");
  if (!text) return null;
  const result: Syl[] = [];
  for (const chunk of text.split(/[\s'’-]+/)) {
    if (!chunk) continue;
    const [plain, markTones] = stripMarks(chunk);
    const parts = [...plain.matchAll(/([a-z]+)([1-5]?)/g)];
    if (parts.map((m) => m[0]).join("") !== plain) return null;
    let pos = 0;
    for (const [, letters, digit] of parts) {
      const seg = segment(letters);
      if (!seg) return null;
      seg.forEach(([a, b], k) => {
        let tone: number | null = markTones.slice(pos + a, pos + b).find((x) => x) ?? null;
        if (digit && k === seg.length - 1) tone = Number(digit);
        result.push({ text: letters.slice(a, b), tone });
      });
      pos += letters.length + digit.length;
    }
  }
  return result.length ? result : null;
}

export const tonelessKey = (s: Syl[]) => s.map((x) => x.text).join("");
export const toneKey = (s: Syl[]) => s.map((x) => x.text + (x.tone ?? "")).join("");
export const hasTones = (s: Syl[]) => s.some((x) => x.tone);

export function keysFromNumbered(p: string): [string, string] {
  const s = p.toLowerCase().replace(/u:/g, "v").replace(/[^a-z0-9]/g, "");
  return [s, s.replace(/\d/g, "")];
}

const TONED: Record<string, string[]> = {
  a: ["ā", "á", "ǎ", "à"], e: ["ē", "é", "ě", "è"], i: ["ī", "í", "ǐ", "ì"],
  o: ["ō", "ó", "ǒ", "ò"], u: ["ū", "ú", "ǔ", "ù"], ü: ["ǖ", "ǘ", "ǚ", "ǜ"],
};

function syllableMarks(base: string, tone: number): string {
  const s = base.replace(/v/g, "ü");
  if (tone === 5) return s;
  let idx = s.search(/[ae]/);
  if (idx < 0) idx = s.indexOf("ou");
  if (idx < 0) {
    for (let i = s.length - 1; i >= 0; i--) if ("iouü".includes(s[i])) { idx = i; break; }
  }
  if (idx < 0) return s;
  return s.slice(0, idx) + TONED[s[idx]][tone - 1] + s.slice(idx + 1);
}

export function numberedToMarks(p: string): string {
  return p.split(" ").map((token) => {
    const m = token.replace(/u:/g, "v").replace(/U:/g, "V").match(/^([A-Za-zv]+)([1-5])$/);
    if (!m) return token;
    let out = syllableMarks(m[1].toLowerCase(), Number(m[2]));
    if (m[1][0] !== m[1][0].toLowerCase()) out = out[0].toUpperCase() + out.slice(1);
    return out;
  }).join(" ");
}

export function wordMarks(p: string): string {
  const parts = numberedToMarks(p).split(" ");
  if (parts.length > 1 && parts.every((x) => /^\p{L}+$/u.test(x))) {
    let joined = parts[0];
    for (const x of parts.slice(1)) {
      if (x[0] !== x[0].toLowerCase()) joined += " " + x;
      else joined += ("aāáǎàoōóǒòeēéěè".includes(x[0]) ? "'" : "") + x;
    }
    return joined;
  }
  return parts.join(" ");
}

const INITIALS: [string, string][] = [
  ["zh", "j"], ["ch", "ch"], ["sh", "sh"], ["b", "b"], ["p", "p"], ["m", "m"], ["f", "f"],
  ["d", "d"], ["t", "t"], ["n", "n"], ["l", "l"], ["g", "g"], ["k", "k"], ["h", "x"],
  ["j", "dj"], ["q", "ch"], ["x", "sh"], ["r", "r"], ["z", "dz"], ["c", "ts"], ["s", "s"],
  ["y", "y"], ["w", "v"],
];
const FINALS: Record<string, string> = {
  ian: "yan", ie: "ye", iu: "yu", ui: "uey", ong: "ung", iong: "yung", ei: "ey", ai: "ay",
  v: "yu", ve: "yue", van: "yuan", vn: "yun",
};

/** Очень приблизительная запись звучания узбекскими буквами (только подсказка). */
export function approxUz(p: string): string {
  return p.toLowerCase().replace(/u:/g, "v").split(" ").map((token) => {
    const base = token.replace(/\d/g, "");
    let init = "", rest = base;
    for (const [a, b] of INITIALS) if (base.startsWith(a)) { init = b; rest = base.slice(a.length); break; }
    if ("jqx".includes(base[0]) && rest.startsWith("u")) rest = "v" + rest.slice(1);
    return init + (FINALS[rest] ?? rest);
  }).join(" ");
}

// --- Узбекский текст ---
const APOS = /[ʻ‘'`´’ʼ′]/g;
const CYR: Record<string, string> = {
  а: "a", б: "b", в: "v", г: "g", д: "d", ё: "yo", ж: "j", з: "z", и: "i", й: "y", к: "k",
  л: "l", м: "m", н: "n", о: "o", п: "p", р: "r", с: "s", т: "t", у: "u", ф: "f", х: "x",
  ц: "ts", ч: "ch", ш: "sh", щ: "sh", ъ: "'", ь: "", э: "e", ю: "yu", я: "ya", ў: "o'",
  қ: "q", ғ: "g'", ҳ: "h",
};
const VOWELS = "аеёиоуэюяўАЕЁИОУЭЮЯЎ";

export function cyrToLat(text: string): string {
  let out = "";
  [...text].forEach((ch, i) => {
    const low = ch.toLowerCase();
    let lat: string;
    if (low === "е") {
      const prev = i ? text[i - 1] : " ";
      lat = !/\p{L}/u.test(prev) || VOWELS.includes(prev) || "ъЪ".includes(prev) ? "ye" : "e";
    } else if (low in CYR) lat = CYR[low];
    else { out += ch; return; }
    if (ch !== low && lat) lat = lat[0].toUpperCase() + lat.slice(1);
    out += lat;
  });
  return out;
}

export function normUz(text: string): string {
  if (/[а-яА-ЯёЁўқғҳЎҚҒҲ]/.test(text)) text = cyrToLat(text);
  return text.toLowerCase().replace(APOS, "'").replace(/\s+/g, " ").replace(/^[ .,!?;:]+|[ .,!?;:]+$/g, "");
}
export const normRu = (t: string) => t.toLowerCase().replace(/ё/g, "е").replace(/^[ .,!?]+|[ .,!?]+$/g, "");

// --- Определение языка ---
export interface Detection { lang: string | null; options: string[]; alternatives: string[] }

export function detect(text: string): Detection {
  const t = text.trim();
  const han = (t.match(HAN_G) ?? []).length;
  const cyr = (t.match(CYR_G) ?? []).length;
  const lat = (t.match(LAT_G) ?? []).length;
  if (han && han >= (cyr + lat) / 3) return { lang: "zh", options: [], alternatives: [] };
  if (cyr > lat) {
    if (/[ўқғҳЎҚҒҲ]/.test(t)) return { lang: "uz", options: [], alternatives: ["ru"] };
    if (/[ыщЫЩ]/.test(t)) return { lang: "ru", options: [], alternatives: ["uz"] };
    return { lang: null, options: ["ru", "uz"], alternatives: [] };
  }
  if (lat) {
    if (/[og][ʻ‘'`´’ʼ′]/i.test(t)) return { lang: "uz", options: [], alternatives: [] };
    if (!parsePinyin(t)) return { lang: "uz", options: [], alternatives: [] };
    if (TONE_MARK_RE.test(t) || /[a-z][1-5](\b|[a-z])/i.test(t)) return { lang: "pinyin", options: [], alternatives: [] };
    return { lang: null, options: ["pinyin", "uz"], alternatives: [] };
  }
  return { lang: null, options: ["zh", "uz", "ru"], alternatives: [] };
}
