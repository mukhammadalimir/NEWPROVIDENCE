import { api } from "../api";
import { useApp } from "../ctx";
import { confirmDialog, tg } from "../telegram";
import type { Lang } from "../types";

export function SettingsScreen() {
  const { t, me, setMe, toast } = useApp();
  const update = async (patch: Partial<{ ui_lang: Lang; target_lang: Lang; voice: string }>) => {
    setMe({ ...me, ...patch });
    try { await api.settings(patch); } catch { toast(t("netError")); }
  };
  const seg = (value: Lang, on: (v: Lang) => void) => (
    <div className="segmented">
      {(["uz", "ru"] as Lang[]).map((l) => (
        <button key={l} className={value === l ? "on" : ""} onClick={() => on(l)}>{t(l)}</button>
      ))}
    </div>
  );
  return (
    <div className="screen">
      <div className="card settings">
        <label>{t("uiLang")}</label>
        {seg(me.ui_lang, (v) => update({ ui_lang: v }))}
        <label>{t("targetLang")}</label>
        {seg(me.target_lang, (v) => update({ target_lang: v }))}
        {me.services.tts && me.voices.length > 1 && (
          <>
            <label>{t("voice")}</label>
            <select className="input" value={me.voice} onChange={(e) => update({ voice: e.target.value })}>
              <option value="">{t("voiceDefault")}</option>
              {me.voices.map((v) => <option key={v} value={v}>{v}</option>)}
            </select>
          </>
        )}
      </div>

      <div className="card settings">
        <label>{t("services")}</label>
        <ul className="svc">
          {(["translate", "tts", "ai"] as const).map((k) => (
            <li key={k}><span>{k === "translate" ? "Google Translate" : k === "tts" ? (me.offline ? t("deviceVoice") : "Text-to-Speech") : "AI"}</span>
              <b className={me.services[k] ? "ok" : "off"}>{me.services[k] ? t("on") : t("off")}</b></li>
          ))}
        </ul>
        {me.offline && <p className="hint">{t("offlineNote")}</p>}
      </div>

      <div className="card settings">
        <label>{t("data")}</label>
        <button className="btn secondary wide" onClick={async () => { await api.clearHistory(); toast(t("deleted")); }}>{t("clearHistory")}</button>
        <button className="btn danger wide" onClick={async () => {
          if (!(await confirmDialog(t("confirmDeleteAll")))) return;
          await api.deleteMe();
          toast(t("deleted"));
          setMe({ ...(await api.me()) });
        }}>{t("deleteAll")}</button>
      </div>

      <div className="card settings">
        <label>{t("sources")}</label>
        <p className="hint">{t("sourcesText")}</p>
        <p className="hint">ID: {me.id}{tg ? "" : " · dev"}</p>
      </div>
    </div>
  );
}
