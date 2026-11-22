export type Lang = "uz" | "ru";
export type Source = "auto" | "zh" | "pinyin" | "uz" | "ru";
export type Kind = "curated" | "cedict_en" | "wikt" | "mt" | "ai";

export interface Me {
  id: number;
  first_name: string;
  ui_lang: Lang;
  target_lang: Lang;
  voice: string;
  is_admin: boolean;
  services: { translate: boolean; tts: boolean; ai: boolean; collocations: boolean };
  voices: string[];
  bot_username: string;
  offline?: boolean;
}

export interface Sense { pos: string | null; items: string[]; kind: Kind; verified: boolean }
export interface Example { zh: string; pinyin: string; translation: string | null; kind: Kind }
export interface Colloc { zh: string; pinyin: string; gloss: string; gloss_kind: Kind }

export interface Reading {
  entry_id: number;
  key: string;
  pinyin: string;
  pinyin_num: string;
  approx: string;
  proper: boolean;
  measure_word: string | null;
  senses: Sense[];
  english: string[];
  english_mt: string[] | null;
  usage: { text: string; kind: Kind } | null;
  examples: Example[];
  collocations: Colloc[];
  has_curated: boolean;
  favorite_id?: number | null;
}

export interface Card { headword: string; traditional: string | null; readings: Reading[] }

export interface Candidate { headword: string; pinyin: string; gloss: string; gloss_kind: Kind; entry_id: number }

export interface TextResult {
  source: string;
  translation: string | null;
  zh: string;
  pinyin: string;
  words: { zh: string; pinyin: string; gloss: string; gloss_kind: Kind }[];
  provider: string | null;
}

export interface SearchResult {
  type: "word" | "candidates" | "text" | "choose" | "not_found";
  query: string;
  source_lang?: Source;
  target_lang?: string;
  notices: string[];
  alternatives: Source[];
  options?: Source[];
  cards?: Card[];
  candidates?: Candidate[];
  text?: TextResult;
  mt_headword?: string;
}

export interface Favorite {
  id: number;
  headword: string;
  pinyin: string;
  gloss: string;
  entry_id: number | null;
  box: number;
  due_at: string;
}

export interface Explain { known: boolean; usage: string; examples: Example[]; kind: "ai" }
