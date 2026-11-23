import { useState, type ReactNode } from "react";
import { ApiError, playAudio } from "../api";
import { useApp } from "../ctx";
import type { TKey } from "../i18n";
import { haptic } from "../telegram";
import type { Kind } from "../types";
import { Icon } from "./Icon";

export function SourceBadge({ kind, verified = true }: { kind: Kind; verified?: boolean }) {
  const { t } = useApp();
  const map: Record<Kind, TKey> = {
    curated: verified ? "srcCuratedOk" : "srcCurated",
    cedict_en: "srcCedict",
    wikt: "srcWikt",
    mt: "srcMt",
    ai: "srcAi",
    bkrs: "srcBkrs",
    bkrs_mt: "srcBkrsMt",
    bkrs_part: "srcBkrsPart",
    bkrs_ru: "srcBkrsRu",
  };
  const cls = kind === "curated" && verified ? "ok" : kind.startsWith("bkrs") ? "bkrs" : kind;
  return <span className={`badge badge-${cls}`}>{t(map[kind])}</span>;
}

/** Короткая метка источника для строк списков: EN (CC-CEDICT) или MT (машинный перевод). */
export function MiniSource({ kind }: { kind: Kind }) {
  const { t } = useApp();
  if (kind === "cedict_en") return <sup className="mini" title={t("srcCedict")}>EN</sup>;
  if (kind === "mt") return <sup className="mini mt" title={t("srcMt")}>MT</sup>;
  if (kind === "wikt") return <sup className="mini" title={t("srcWikt")}>W</sup>;
  if (kind === "bkrs") return <sup className="mini bkrs" title={t("srcBkrs")}>БКРС</sup>;
  if (kind === "bkrs_mt") return <sup className="mini bkrs" title={t("srcBkrsMt")}>БКРС·MT</sup>;
  if (kind === "bkrs_ru") return <sup className="mini bkrs" title={t("srcBkrsRu")}>БКРС·RU</sup>;
  return null;
}

export function Legend({ kinds }: { kinds: Kind[] }) {
  const { t } = useApp();
  const parts = [];
  if (kinds.includes("cedict_en")) parts.push(`EN — ${t("srcCedict")}`);
  if (kinds.includes("wikt")) parts.push(`W — ${t("srcWikt")}`);
  if (kinds.includes("mt")) parts.push(`MT — ${t("srcMt")}`);
  if (kinds.includes("bkrs")) parts.push(`БКРС — ${t("srcBkrs")}`);
  if (kinds.includes("bkrs_mt")) parts.push(`БКРС·MT — ${t("srcBkrsMt")}`);
  if (kinds.includes("bkrs_ru")) parts.push(`БКРС·RU — ${t("srcBkrsRu")}`);
  return parts.length ? <div className="legend">{parts.join(" · ")}</div> : null;
}

/** Кнопки озвучки. Не показываются, если сервис не подключён. */
export function Audio({ text, small }: { text: string; small?: boolean }) {
  const { me, t, toast } = useApp();
  const [busy, setBusy] = useState<"" | "n" | "s">("");
  if (!me.services.tts) return null;
  const play = async (slow: boolean) => {
    haptic();
    setBusy(slow ? "s" : "n");
    try {
      await playAudio(text, slow, me.voice || undefined);
    } catch (e) {
      const code = e instanceof ApiError ? e.code : "";
      toast(code === "rate_limited" ? t("rateLimited") : code === "tts_unavailable" ? t("ttsOff") : t("ttsFailed"));
    } finally {
      setBusy("");
    }
  };
  return (
    <span className={`audio ${small ? "audio-sm" : ""}`}>
      <button className={`icon-btn ${busy === "n" ? "busy" : ""}`} onClick={() => play(false)} aria-label={t("listen")}>
        <Icon name="speaker" size={small ? 16 : 20} />
      </button>
      <button className={`icon-btn ${busy === "s" ? "busy" : ""}`} onClick={() => play(true)} aria-label={t("slow")}>
        <span className="slow-label">0.7×</span>
      </button>
    </span>
  );
}

export function State({ icon, title, hint, action }: { icon: string; title: string; hint?: string; action?: ReactNode }) {
  return (
    <div className="state">
      <div className="state-icon"><Icon name={icon} size={28} /></div>
      <div className="state-title">{title}</div>
      {hint && <div className="state-hint">{hint}</div>}
      {action}
    </div>
  );
}

export function Skeleton() {
  return (
    <div className="card skeleton" aria-busy="true">
      <div className="sk sk-hanzi" />
      <div className="sk sk-line w40" />
      <div className="sk sk-line w80" />
      <div className="sk sk-line w60" />
    </div>
  );
}

export function Sheet({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  return (
    <div className="sheet-backdrop" onClick={onClose}>
      <div className="sheet" onClick={(e) => e.stopPropagation()} role="dialog" aria-label={title}>
        <div className="sheet-head">
          <b>{title}</b>
          <button className="icon-btn" onClick={onClose} aria-label="close"><Icon name="x" /></button>
        </div>
        {children}
      </div>
    </div>
  );
}

export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const ta = document.createElement("textarea");
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand("copy");
    ta.remove();
    return ok;
  }
}
