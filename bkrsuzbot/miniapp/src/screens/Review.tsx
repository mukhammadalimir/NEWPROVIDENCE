import { useEffect, useState } from "react";
import { api } from "../api";
import { Audio, State } from "../components/ui";
import { useApp } from "../ctx";
import { haptic } from "../telegram";
import type { Favorite } from "../types";

export function ReviewScreen() {
  const { t } = useApp();
  const [card, setCard] = useState<(Favorite & { due_count: number }) | null | undefined>(undefined);
  const [shown, setShown] = useState(false);

  const next = () => { setShown(false); api.reviewNext().then(setCard).catch(() => setCard(null)); };
  useEffect(next, []);

  if (card === undefined) return <div className="screen"><div className="card skeleton"><div className="sk sk-hanzi" /></div></div>;
  if (card === null) return <State icon="cards" title={t("reviewEmpty")} />;

  const answer = async (knew: boolean) => {
    haptic(knew ? "success" : "tap");
    await api.reviewAnswer(card.id, knew);
    next();
  };

  return (
    <div className="screen">
      <div className="hint center">{t("reviewDue", { n: card.due_count })}</div>
      <div className="card flash" onClick={() => setShown(true)}>
        <div className="hanzi xl" lang="zh-CN">{card.headword}</div>
        {shown ? (
          <>
            <div className="pinyin">{card.pinyin}</div>
            <div className="flash-gloss">{card.gloss}</div>
            <Audio text={card.headword} />
          </>
        ) : (
          <button className="btn secondary">{t("showAnswer")}</button>
        )}
      </div>
      {shown && (
        <div className="review-actions">
          <button className="btn secondary" onClick={() => answer(false)}>{t("didnt")}</button>
          <button className="btn" onClick={() => answer(true)}>{t("knew")}</button>
        </div>
      )}
    </div>
  );
}
