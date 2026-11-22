// Минимальная обёртка над Telegram WebApp SDK (telegram-web-app.js).
type HapticStyle = "light" | "medium" | "heavy";

interface TgWebApp {
  initData: string;
  initDataUnsafe: { user?: { id: number; language_code?: string } };
  colorScheme: "light" | "dark";
  ready(): void;
  expand(): void;
  BackButton: { show(): void; hide(): void; onClick(cb: () => void): void; offClick(cb: () => void): void };
  HapticFeedback?: { impactOccurred(s: HapticStyle): void; notificationOccurred(t: "success" | "error"): void };
  openTelegramLink(url: string): void;
  showConfirm?(message: string, cb: (ok: boolean) => void): void;
  setHeaderColor?(color: string): void;
  isVersionAtLeast?(v: string): boolean;
}

declare global {
  interface Window {
    Telegram?: { WebApp: TgWebApp };
  }
}

export const tg: TgWebApp | null = window.Telegram?.WebApp ?? null;
export const insideTelegram = Boolean(tg && tg.initData);

export function initTelegram() {
  if (!tg) return;
  if (tg.initData) document.documentElement.dataset.tg = "1"; // цвета берём из темы Telegram
  tg.ready();
  tg.expand();
  try {
    tg.setHeaderColor?.("secondary_bg_color");
  } catch {
    /* старые клиенты */
  }
}

export function haptic(kind: "tap" | "success" | "error" = "tap") {
  const h = tg?.HapticFeedback;
  if (!h) return;
  if (kind === "tap") h.impactOccurred("light");
  else h.notificationOccurred(kind);
}

export function confirmDialog(message: string): Promise<boolean> {
  return new Promise((resolve) => {
    if (tg?.showConfirm && tg.isVersionAtLeast?.("6.2")) tg.showConfirm(message, resolve);
    else resolve(window.confirm(message));
  });
}
