import { useState } from "react";
import { api, ApiError } from "../api";
import { useApp } from "../ctx";
import { haptic, tg } from "../telegram";
import type { BkrsItem, Card, Explain, Reading } from "../types";
import { Icon } from "./Icon";
import { Audio, copyText, Legend, MiniSource, SourceBadge } from "./ui";
import { ReportSheet } from "./ReportSheet";

export function shareText(text: string, botUsername: string) {
  const url = `https://t.me/${botUsername || ""}`;
  const link = `https://t.me/share/url?url=${encodeURIComponent(url)}&text=${encodeURIComponent(text)}`;
  if (tg) tg.openTelegramLink(link);
  else window.open(link, "_blank");
}

export function cardPlainText(card: Card, lang: string): string {
  const lines = [card.headword + (card.traditional ? ` (${card.traditional})` : "")];
  for (const r of card.readings) {
    if (r.bkrs?.length) {
      lines.push(r.pinyin);
      for (const it of r.bkrs) lines.push(it.kind === "ex" ? `  ${it.zh} — ${it.tr}` : it.text);
      continue;
    }
    const meaning = r.senses.flatMap((s) => s.items).join(", ") || (r.english_mt ?? r.english).slice(0, 3).join("; ");
    lines.push(`${r.pinyin} — ${meaning}`);
  }
  void lang;
  return lines.join("\n");
}

export function WordCard({ card, lang, query }: { card: Card; lang: string; query: string }) {
  const { t, toast, me } = useApp();
  const [report, setReport] = useState(false);
  return (
    <article className="card word">
      <header className="word-head">
        <div>
          <div className="hanzi" lang="zh-CN">{card.headword}</div>
          {card.traditional && (
            <div className="trad" lang="zh-TW">{card.traditional} <span>· {t("trad")}</span></div>
          )}
        </div>
        <Audio text={card.headword} />
      </header>

      {card.readings.map((r) => (
        <ReadingBlock key={`${r.entry_id ?? "b"}-${r.key}`} r={r} card={card} lang={lang} multi={card.readings.length > 1} />
      ))}

      <footer className="card-actions">
        <button className="chip-btn" onClick={async () => {
          if (await copyText(cardPlainText(card, lang))) toast(t("copied"));
        }}><Icon name="copy" size={16} /> {t("copy")}</button>
        <button className="chip-btn" onClick={() => shareText(cardPlainText(card, lang), me.bot_username)}>
          <Icon name="share" size={16} /> {t("share")}
        </button>
        {!me.offline && <button className="chip-btn subtle" onClick={() => setReport(true)}>
          <Icon name="flag" size={16} /> {t("report")}
        </button>}
      </footer>
      {report && <ReportSheet query={query} entryId={card.readings[0]?.entry_id} onClose={() => setReport(false)} />}
    </article>
  );
}

function ReadingBlock({ r, card, lang, multi }: { r: Reading; card: Card; lang: string; multi: boolean }) {
  const { t, toast, me, openSearch } = useApp();
  const [favId, setFavId] = useState<number | null>(r.favorite_id ?? null);
  const [ai, setAi] = useState<Explain | null>(null);
  const [aiBusy, setAiBusy] = useState(false);
  const gloss = bkrsShort(r.bkrs) || r.senses.flatMap((s) => s.items).join(", ")
    || (r.english_mt ?? r.english).slice(0, 2).join("; ");
  // при статье БКРС: узбекские значения редакции (написаны человеком) показываем над ней
  const senses = r.bkrs?.length ? (lang === "uz" ? r.senses.filter((s) => s.kind === "curated") : []) : r.senses;
  const verified = senses.every((s) => s.verified);

  const toggleFav = async () => {
    haptic();
    try {
      if (favId) {
        await api.removeFavorite(favId);
        setFavId(null);
      } else {
        const f = await api.addFavorite({ headword: card.headword, pinyin: r.pinyin, gloss, entry_id: r.entry_id });
        setFavId(f.id);
        haptic("success");
      }
    } catch {
      toast(t("netError"));
    }
  };

  const loadAi = async () => {
    setAiBusy(true);
    try {
      if (r.entry_id == null) return;
      setAi(await api.explain(r.entry_id, lang === "ru" ? "ru" : "uz"));
    } catch (e) {
      toast(e instanceof ApiError && e.code === "rate_limited" ? t("rateLimited") : t("aiFailed"));
    } finally {
      setAiBusy(false);
    }
  };

  return (
    <section className="reading">
      <div className="reading-head">
        <div>
          <span className="pinyin">{r.pinyin}</span>
          {r.proper && <span className="tag">{t("proper")}</span>}
          {r.approx && <div className="approx">{t("approx")}: «{r.approx}»</div>}
        </div>
        <div className="row-gap">
          {multi && <Audio text={card.headword} small />}
          <button className={`icon-btn star ${favId ? "on" : ""}`} onClick={toggleFav}
            aria-label={favId ? t("saved") : t("save")}>
            <Icon name="star" fill={Boolean(favId)} />
          </button>
        </div>
      </div>

      {r.measure_word && <div className="meta"><span>{t("measure")}</span> <b lang="zh-CN">{r.measure_word}</b></div>}

      {senses.length > 0 && (
        <div className="block">
          <div className="block-title">{t("meanings")} <SourceBadge kind={senses.every((s) => s.kind === "wikt") ? "wikt" : "curated"} verified={verified} /></div>
          <ol className="senses">
            {senses.map((s, i) => (
              <li key={i}>{s.pos && <em>{s.pos}</em>} {s.items.join(", ")}</li>
            ))}
          </ol>
        </div>
      )}

      {r.bkrs && r.bkrs.length > 0 && (
        <div className="block">
          <div className="block-title">{senses.length ? "大БКРС" : t("meanings")} <SourceBadge kind={r.bkrs_kind ?? "bkrs"} /></div>
          <BkrsList items={r.bkrs} />
        </div>
      )}

      {!r.bkrs?.length && r.english_mt && r.english_mt.length > 0 && (
        <div className="block">
          <div className="block-title">{t(r.senses.length ? "english" : "meanings")} <SourceBadge kind="mt" /></div>
          <p className="defs">{r.english_mt.slice(0, 8).join("; ")}</p>
        </div>
      )}
      {!r.bkrs?.length && r.english.length > 0 && (
        <details className="block" open={!r.senses.length && !r.english_mt}>
          <summary className="block-title">{t("english")} <SourceBadge kind="cedict_en" /></summary>
          <p className="defs" lang="en">{r.english.join("; ")}</p>
        </details>
      )}
      {!r.bkrs?.length && !r.senses.length && !r.english_mt && <p className="hint">{t("noTarget")}</p>}

      {r.usage && (
        <div className="block">
          <div className="block-title">{t("usage")}</div>
          <p>{r.usage.text}</p>
        </div>
      )}

      {r.collocations.length > 0 && (
        <div className="block">
          <div className="block-title">{t("colloc")}</div>
          <ul className="list">
            {r.collocations.map((c) => (
              <li key={c.zh}>
                <button className="list-row" onClick={() => openSearch(c.zh, "zh")}>
                  <span className="zh" lang="zh-CN">{c.zh}</span>
                  <span className="py">{c.pinyin}</span>
                  <span className="gl">{c.gloss}<MiniSource kind={c.gloss_kind} /></span>
                </button>
              </li>
            ))}
          </ul>
          <Legend kinds={r.collocations.map((c) => c.gloss_kind)} />
        </div>
      )}

      {r.examples.length > 0 && (
        <div className="block">
          <div className="block-title">{t("examples")}</div>
          {r.examples.map((x, i) => <ExampleRow key={i} x={x} />)}
        </div>
      )}

      {me.services.ai && !ai && r.entry_id != null && (
        <button className="ai-btn" disabled={aiBusy} onClick={loadAi}>
          <Icon name="sparkles" size={16} /> {aiBusy ? t("loading") : t("aiExplain")}
        </button>
      )}
      {ai && (
        <div className="block ai-block">
          <div className="block-title"><SourceBadge kind="ai" /></div>
          {!ai.known && <p className="hint">{t("aiUnknown")}</p>}
          {ai.usage && <p>{ai.usage}</p>}
          {ai.examples.map((x, i) => <ExampleRow key={i} x={x} />)}
        </div>
      )}
    </section>
  );
}

/** Первое значение БКРС без нумерации — для избранного. */
function bkrsShort(items?: BkrsItem[]): string {
  const s = items?.find((it) => it.kind === "sense");
  return s ? s.text.replace(/^\s*(?:[IVXL]+\s+)?(?:\d+\)|[а-яa-z]\))\s*/, "").slice(0, 80) : "";
}

/** Статья 大БКРС: значения по порядку словаря, под каждым — примеры. */
function BkrsList({ items }: { items: BkrsItem[] }) {
  return (
    <div className="bkrs">
      {items.map((it, i) =>
        it.kind === "head" ? <div key={i} className="bk-head">{it.text}</div>
        : it.kind === "ex" ? (
          <div key={i} className="bk-ex">
            <span lang="zh-CN">{it.zh || it.text}</span>
            {it.tr && <span className="bk-tr"> — {it.tr}</span>}
          </div>
        ) : <div key={i} className="bk-sense">{it.text}</div>)}
    </div>
  );
}

function ExampleRow({ x }: { x: { zh: string; pinyin: string; translation: string | null } }) {
  return (
    <div className="example">
      <div className="ex-top">
        <span className="ex-zh" lang="zh-CN">{x.zh}</span>
        <Audio text={x.zh} small />
      </div>
      <div className="ex-py">{x.pinyin}</div>
      {x.translation && <div className="ex-tr">{x.translation}</div>}
    </div>
  );
}
