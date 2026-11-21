import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api";
import { Icon } from "../components/Icon";
import { Results } from "../components/Results";
import { Skeleton, State } from "../components/ui";
import { useApp } from "../ctx";
import { tg } from "../telegram";
import type { SearchResult, Source } from "../types";

type Target = "uz" | "ru" | "zh";
export interface Pending { q: string; source?: string; n: number }

const SOURCES: Source[] = ["auto", "zh", "pinyin", "uz", "ru"];

export function SearchScreen({ pending }: { pending: Pending | null }) {
  const { t, me } = useApp();
  const [q, setQ] = useState("");
  const [src, setSrc] = useState<Source>("auto");
  const [tgt, setTgt] = useState<Target>(me.target_lang);
  const [result, setResult] = useState<SearchResult | null>(null);
  const [status, setStatus] = useState<"idle" | "loading" | "error" | "done">("idle");
  const [error, setError] = useState("");
  const [history, setHistory] = useState<string[]>([]);
  const last = useRef<{ q: string; source?: string }>({ q: "" });
  const inputRef = useRef<HTMLInputElement>(null);

  const loadHistory = useCallback(() => {
    api.history().then((h) => setHistory(h.map((x) => x.query))).catch(() => {});
  }, []);
  useEffect(loadHistory, [loadHistory]);

  // Ограничения направления: с китайского/пиньиня — на uz/ru; с uz/ru — на китайский.
  const targets: Target[] = src === "uz" || src === "ru" ? ["zh"] : src === "auto" ? ["uz", "ru", "zh"] : ["uz", "ru"];
  useEffect(() => {
    if (!targets.includes(tgt)) setTgt(targets[0]);
  }, [src]); // eslint-disable-line react-hooks/exhaustive-deps

  const run = useCallback(async (query: string, source?: string) => {
    query = query.trim();
    if (!query) return;
    last.current = { q: query, source };
    setQ(query);
    setStatus("loading");
    inputRef.current?.blur();
    const target = tgt === "zh" ? undefined : tgt;
    try {
      const r = await api.search(query, source, target);
      setResult(r);
      setStatus("done");
      loadHistory();
    } catch (e) {
      setError(e instanceof ApiError ? e.code : "network");
      setStatus("error");
    }
  }, [tgt, loadHistory]);

  useEffect(() => {
    if (pending) run(pending.q, pending.source);
  }, [pending]); // eslint-disable-line react-hooks/exhaustive-deps

  // Кнопка «Назад» Telegram возвращает к главному экрану поиска.
  useEffect(() => {
    const app = tg;
    if (!app || status === "idle") return;
    const back = () => { setStatus("idle"); setResult(null); };
    app.BackButton.show();
    app.BackButton.onClick(back);
    return () => { app.BackButton.offClick(back); app.BackButton.hide(); };
  }, [status]);

  const swap = () => {
    if (src === "uz" || src === "ru") { setSrc("zh"); setTgt(src); }
    else if (src === "zh" || src === "pinyin") { if (tgt !== "zh") { setSrc(tgt); setTgt("zh"); } }
    else if (tgt === "zh") { setSrc("zh"); setTgt(me.target_lang); }
    else { setSrc(tgt); setTgt("zh"); }
  };

  const submit = (e?: React.FormEvent) => {
    e?.preventDefault();
    run(q, src === "auto" ? undefined : src);
  };

  return (
    <div className="screen">
      <form className="search" onSubmit={submit}>
        <div className="search-box">
          <Icon name="search" />
          <input ref={inputRef} value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("placeholder")}
            enterKeyHint="search" autoCapitalize="off" autoCorrect="off" spellCheck={false} maxLength={500} />
          {q && <button type="button" className="icon-btn" onClick={() => { setQ(""); inputRef.current?.focus(); }}
            aria-label={t("clear")}><Icon name="x" size={18} /></button>}
        </div>
        <div className="dir">
          <select value={src} onChange={(e) => setSrc(e.target.value as Source)} aria-label="from">
            {SOURCES.map((s) => <option key={s} value={s}>{t(s === "pinyin" ? "pinyin" : s)}</option>)}
          </select>
          <button type="button" className="icon-btn swap" onClick={swap} aria-label={t("swap")}><Icon name="swap" /></button>
          <select value={tgt} onChange={(e) => setTgt(e.target.value as Target)} aria-label="to">
            {targets.map((s) => <option key={s} value={s}>{t(s)}</option>)}
          </select>
        </div>
        <button className="btn wide" disabled={!q.trim() || status === "loading"}>{t("translate")}</button>
      </form>

      {status === "loading" && <Skeleton />}
      {status === "error" && (
        error === "rate_limited" ? <State icon="clock" title={t("rateLimited")} /> :
        <State icon="wifi" title={t("netError")} hint={t("netErrorHint")}
          action={<button className="btn secondary" onClick={() => run(last.current.q, last.current.source)}>{t("retry")}</button>} />
      )}
      {status === "done" && result && (
        <Results r={result} onSearchAs={(s) => run(result.query, s)} />
      )}

      {status === "idle" && history.length > 0 && (
        <section className="section">
          <div className="section-head">
            <span><Icon name="clock" size={16} /> {t("history")}</span>
            <button className="link" onClick={async () => { await api.clearHistory(); setHistory([]); }}>{t("clear")}</button>
          </div>
          <div className="chips">
            {history.slice(0, 15).map((h) => (
              <button key={h} className="chip" onClick={() => run(h)} lang="zh-CN">{h}</button>
            ))}
          </div>
        </section>
      )}
      {status === "idle" && !history.length && (
        <section className="section">
          <div className="chips">
            {["鱼", "baliq", "nǐ hǎo", "我喜欢吃鱼。", "рыба"].map((h) => (
              <button key={h} className="chip" onClick={() => run(h)}>{h}</button>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
