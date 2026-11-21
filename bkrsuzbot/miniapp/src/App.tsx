import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "./api";
import { Icon } from "./components/Icon";
import { State } from "./components/ui";
import { Ctx } from "./ctx";
import { makeT } from "./i18n";
import { AdminScreen } from "./screens/Admin";
import { FavoritesScreen } from "./screens/Favorites";
import { ReviewScreen } from "./screens/Review";
import { SearchScreen, type Pending } from "./screens/Search";
import { SettingsScreen } from "./screens/Settings";
import { initTelegram, tg } from "./telegram";
import type { Lang, Me } from "./types";

type Tab = "search" | "favorites" | "review" | "settings" | "admin";

export function App() {
  const [me, setMe] = useState<Me | null>(null);
  const [fatal, setFatal] = useState<"" | "auth" | "network">("");
  const [tab, setTab] = useState<Tab>("search");
  const [toastMsg, setToastMsg] = useState("");
  const toastTimer = useRef<number>();
  const counter = useRef(0);
  const initialQ = new URLSearchParams(location.search).get("q");
  const [pending, setPending] = useState<Pending | null>(initialQ ? { q: initialQ, n: 0 } : null);

  const uiLang: Lang = me?.ui_lang ?? (tg?.initDataUnsafe.user?.language_code?.startsWith("ru") ? "ru" : "uz");
  const t = useMemo(() => makeT(uiLang), [uiLang]);

  const load = useCallback(() => {
    setFatal("");
    api.me().then(setMe).catch((e) => setFatal(e instanceof ApiError && e.status === 401 ? "auth" : "network"));
  }, []);

  useEffect(() => { initTelegram(); load(); }, [load]);
  useEffect(() => { document.documentElement.lang = uiLang; }, [uiLang]);

  const toast = useCallback((msg: string) => {
    setToastMsg(msg);
    window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToastMsg(""), 2600);
  }, []);

  const openSearch = useCallback((q: string, source?: string) => {
    setTab("search");
    setPending({ q, source, n: ++counter.current });
    window.scrollTo({ top: 0, behavior: "smooth" });
  }, []);

  if (fatal === "auth") return <State icon="shield" title={t("openInTelegram")} hint={t("openInTelegramHint")} />;
  if (fatal === "network") {
    return <State icon="wifi" title={t("netError")} hint={t("netErrorHint")}
      action={<button className="btn secondary" onClick={load}>{t("retry")}</button>} />;
  }
  if (!me) return <div className="screen"><div className="card skeleton"><div className="sk sk-hanzi" /><div className="sk sk-line w60" /></div></div>;

  const tabs: { id: Tab; icon: string; label: string }[] = [
    { id: "search", icon: "search", label: t("search") },
    { id: "favorites", icon: "star", label: t("favorites") },
    { id: "review", icon: "cards", label: t("review") },
    { id: "settings", icon: "settings", label: t("settings") },
    ...(me.is_admin ? [{ id: "admin" as Tab, icon: "shield", label: t("admin") }] : []),
  ];

  return (
    <Ctx.Provider value={{ me, setMe, t, toast, openSearch }}>
      <header className="topbar">
        <span className="logo">汉</span>
        <div>
          <div className="title">{t("appName")}</div>
          <div className="subtitle">{t("tagline")}</div>
        </div>
      </header>
      <main>
        <div hidden={tab !== "search"}><SearchScreen pending={pending} /></div>
        {tab === "favorites" && <FavoritesScreen onReview={() => setTab("review")} />}
        {tab === "review" && <ReviewScreen />}
        {tab === "settings" && <SettingsScreen />}
        {tab === "admin" && me.is_admin && <AdminScreen />}
      </main>
      <nav className="tabbar">
        {tabs.map((x) => (
          <button key={x.id} className={tab === x.id ? "on" : ""} onClick={() => setTab(x.id)}>
            <Icon name={x.icon} size={22} />
            <span>{x.label}</span>
          </button>
        ))}
      </nav>
      {toastMsg && <div className="toast" role="status">{toastMsg}</div>}
    </Ctx.Provider>
  );
}
