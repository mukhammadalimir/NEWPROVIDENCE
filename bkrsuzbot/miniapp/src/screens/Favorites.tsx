import { useEffect, useState } from "react";
import { api } from "../api";
import { Icon } from "../components/Icon";
import { Audio, State } from "../components/ui";
import { useApp } from "../ctx";
import { confirmDialog } from "../telegram";
import type { Favorite } from "../types";

export function FavoritesScreen({ onReview }: { onReview: () => void }) {
  const { t, toast, openSearch } = useApp();
  const [items, setItems] = useState<Favorite[] | null>(null);
  const [err, setErr] = useState(false);

  const load = () => api.favorites().then(setItems).catch(() => setErr(true));
  useEffect(() => { load(); }, []);

  if (err) return <State icon="wifi" title={t("netError")} action={<button className="btn secondary" onClick={() => { setErr(false); load(); }}>{t("retry")}</button>} />;
  if (!items) return <div className="screen"><div className="card skeleton"><div className="sk sk-line w80" /><div className="sk sk-line w60" /></div></div>;
  if (!items.length) return <State icon="star" title={t("favEmpty")} hint={t("favEmptyHint")} />;

  return (
    <div className="screen">
      <div className="section-head">
        <span>{t("favorites")} · {items.length}</span>
        <button className="link danger" onClick={async () => {
          if (await confirmDialog(t("confirmClearFav"))) { await api.clearFavorites(); setItems([]); }
        }}>{t("clearFav")}</button>
      </div>
      <button className="btn wide" onClick={onReview}><Icon name="cards" size={18} /> {t("review")}</button>
      <ul className="card list fav-list">
        {items.map((f) => (
          <li key={f.id} className="fav">
            <button className="list-row" onClick={() => openSearch(f.headword, "zh")}>
              <span className="zh big" lang="zh-CN">{f.headword}</span>
              <span className="py">{f.pinyin}</span>
              <span className="gl">{f.gloss}</span>
            </button>
            <Audio text={f.headword} small />
            <button className="icon-btn" aria-label="delete" onClick={async () => {
              await api.removeFavorite(f.id);
              setItems(items.filter((x) => x.id !== f.id));
              toast(t("deleted"));
            }}><Icon name="trash" size={18} /></button>
          </li>
        ))}
      </ul>
    </div>
  );
}
