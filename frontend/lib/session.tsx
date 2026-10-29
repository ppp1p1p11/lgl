"use client";

import { createContext, useContext } from "react";

import type { Me } from "@/lib/api/client";

const SessionContext = createContext<Me | null>(null);

export const SessionProvider = SessionContext.Provider;

/** The signed-in user. Only usable inside the signed-in app shell. */
export function useSession(): Me {
  const me = useContext(SessionContext);
  if (!me) throw new Error("useSession must be used inside the app shell");
  return me;
}

export function useCan(permission: Me["permissions"][number]): boolean {
  return useSession().permissions.includes(permission);
}
