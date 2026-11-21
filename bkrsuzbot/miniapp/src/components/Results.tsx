import { useState } from "react";
import { useApp } from "../ctx";
import type { TKey } from "../i18n";
import type { SearchResult, Source } from "../types";
import { Icon } from "./Icon";
import { ReportSheet } from "./ReportSheet";
import { Audio, copyText, Legend, MiniSource, SourceBadge, State } from "./ui";
import { shareText, WordCard } from "./WordCard";

const SRC_LABEL: Record<string, TKey> = { zh: "zh", pinyin: "pinyinOpt", uz: "uz", ru: "ru" };

export function Results({ r, onSearchAs }: { r: SearchResult; onSearchAs: (source: Source) => void }) {
  const { t, openSearch } = useApp();
  const lang = r.source_lang === "uz" || r.source_lang === "ru" ? r.source_lang : r.target_lang ?? "uz";

  if (r.type === "choose") {
    return (
      <div className="card">
        <div className="block-title">«{r.query}» — {t("chooseDir")}</div>
        <div className="choose">
          {r.options!.map((o) => (
            <button key={o} className="btn secondary" onClick={() => onSearchAs(o)}>{t(SRC_LABEL[o])}</button>
          ))}
        </div>
      </div>
    );
  }

  return (
    <>
      <Notices r={r} />
      {r.type === "not_found" && <State icon="search" title={t("notFound")} hint={t("notFoundHint")} />}

      {r.type === "candidates" && (
        <div className="card">
          <div className="block-title">{t("candidates")}</div>
          <ul className="list">
            {r.candidates!.map((c) => (
              <li key={c.entry_id}>
                <button className="list-row cand" onClick={() => openSearch(c.headword, "zh")}>
                  <span className="zh big" lang="zh-CN">{c.headword}</span>
                  <span className="py">{c.pinyin}</span>
                  <span className="gl">{c.gloss}<MiniSource kind={c.gloss_kind} /></span>
                  <Icon name="chevron" size={16} />
                </button>
              </li>
            ))}
          </ul>
          <Legend kinds={r.candidates!.map((c) => c.gloss_kind)} />
        </div>
      )}

      {r.type === "word" && r.cards!.map((c) => <WordCard key={c.headword} card={c} lang={lang} query={r.query} />)}

      {r.type === "text" && <TextCard r={r} />}

      {r.alternatives.length > 0 && (
        <div className="alts">
          <span>{t("searchAs")}</span>
          {r.alternatives.map((a) => (
            <button key={a} className="chip-btn" onClick={() => onSearchAs(a)}>{t(SRC_LABEL[a])}</button>
          ))}
        </div>
      )}
    </>
  );
}

function Notices({ r }: { r: SearchResult }) {
  const { t } = useApp();
  const msgs: string[] = [];
  for (const n of r.notices) {
    if (n === "mt_used" && r.mt_headword) msgs.push(t("mtHeadword", { q: r.query, zh: r.mt_headword }));
    else if (n === "mt_used" && r.type === "text") msgs.push(t("mtUsed"));
    else if (n === "translate_unavailable") msgs.push(t("translateUnavailable"));
    else if (n === "translate_failed") msgs.push(t("translateFailed"));
  }
  if (!msgs.length) return null;
  return <>{msgs.map((m) => <div key={m} className={`notice ${m === t("translateFailed") ? "warn" : ""}`}>{m}</div>)}</>;
}

function TextCard({ r }: { r: SearchResult }) {
  const { t, toast, me, openSearch } = useApp();
  const [report, setReport] = useState(false);
  const tx = r.text!;
  const fromZh = r.source_lang === "zh";
  const plain = [tx.source, tx.translation ?? "", fromZh ? tx.pinyin : `${tx.zh}\n${tx.pinyin}`].filter(Boolean).join("\n");
  return (
    <article className="card">
      <div className="block">
        <div className="block-title">{t("original")}</div>
        <p className={fromZh ? "text-zh" : ""} lang={fromZh ? "zh-CN" : undefined}>{tx.source}</p>
        {fromZh && <div className="row-gap"><span className="ex-py">{tx.pinyin}</span><Audio text={tx.zh} small /></div>}
      </div>
      <div className="block">
        <div className="block-title">{t("translation")} {tx.translation && <SourceBadge kind="mt" />}</div>
        {tx.translation ? (
          fromZh ? <p className="text-tr">{tx.translation}</p> : (
            <>
              <p className="text-zh" lang="zh-CN">{tx.zh}</p>
              <div className="row-gap"><span className="ex-py">{tx.pinyin}</span><Audio text={tx.zh} small /></div>
            </>
          )
        ) : <p className="hint">—</p>}
      </div>
      {tx.words.length > 0 && (
        <div className="block">
          <div className="block-title">{t("words")}</div>
          <ul className="list">
            {tx.words.map((w) => (
              <li key={w.zh}>
                <button className="list-row" onClick={() => openSearch(w.zh, "zh")}>
                  <span className="zh" lang="zh-CN">{w.zh}</span>
                  <span className="py">{w.pinyin}</span>
                  <span className="gl">{w.gloss}<MiniSource kind={w.gloss_kind} /></span>
                </button>
              </li>
            ))}
          </ul>
          <Legend kinds={tx.words.map((w) => w.gloss_kind)} />
        </div>
      )}
      <footer className="card-actions">
        <button className="chip-btn" onClick={async () => { if (await copyText(plain)) toast(t("copied")); }}>
          <Icon name="copy" size={16} /> {t("copy")}
        </button>
        <button className="chip-btn" onClick={() => shareText(plain, me.bot_username)}>
          <Icon name="share" size={16} /> {t("share")}
        </button>
        <button className="chip-btn subtle" onClick={() => setReport(true)}>
          <Icon name="flag" size={16} /> {t("report")}
        </button>
      </footer>
      {report && <ReportSheet query={r.query} onClose={() => setReport(false)} />}
    </article>
  );
}
