import { createContext, useContext } from "react";
import type { T } from "./i18n";
import type { Me } from "./types";

export interface AppCtx {
  me: Me;
  setMe: (m: Me) => void;
  t: T;
  toast: (msg: string) => void;
  openSearch: (q: string, source?: string) => void;
}

export const Ctx = createContext<AppCtx>(null as unknown as AppCtx);
export const useApp = () => useContext(Ctx);
