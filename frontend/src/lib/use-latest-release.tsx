"use client";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { getLatestRelease } from "./api";
import type { LatestRelease } from "./types";

interface ReleaseState { release: LatestRelease | null; loading: boolean }
const Context = createContext<ReleaseState>({ release: null, loading: true });
export function LatestReleaseProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<ReleaseState>({ release: null, loading: true });
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = async () => {
      try {
        const release = await getLatestRelease();
        if (active) setState({ release, loading: false });
      } catch {
        if (active) setState({ release: null, loading: false });
      } finally {
        // The backend TTL starts after its fetch completes. Wait a full hour
        // after our response, not after the previous request started.
        if (active) timer = setTimeout(() => void load(), 3_600_000);
      }
    };
    void load();
    return () => { active = false; clearTimeout(timer); };
  }, []);
  return <Context.Provider value={state}>{children}</Context.Provider>;
}
export const useLatestRelease = () => useContext(Context);
