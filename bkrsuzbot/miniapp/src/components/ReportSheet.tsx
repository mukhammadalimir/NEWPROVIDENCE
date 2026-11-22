import { useState } from "react";
import { api } from "../api";
import { useApp } from "../ctx";
import { Sheet } from "./ui";

export function ReportSheet({ query, entryId, onClose }: { query: string; entryId?: number | null; onClose: () => void }) {
  const { t, toast } = useApp();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const send = async () => {
    setBusy(true);
    try {
      await api.report(query, text.trim(), entryId ?? null);
      toast(t("reportThanks"));
      onClose();
    } catch {
      toast(t("netError"));
      setBusy(false);
    }
  };
  return (
    <Sheet title={t("reportTitle")} onClose={onClose}>
      <p className="hint">«{query}»</p>
      <textarea className="input" rows={4} autoFocus placeholder={t("reportHint")} value={text}
        maxLength={2000} onChange={(e) => setText(e.target.value)} />
      <div className="sheet-actions">
        <button className="btn secondary" onClick={onClose}>{t("cancel")}</button>
        <button className="btn" disabled={busy || text.trim().length < 2} onClick={send}>{t("send")}</button>
      </div>
    </Sheet>
  );
}
