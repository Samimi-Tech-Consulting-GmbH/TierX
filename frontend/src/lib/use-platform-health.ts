"use client";

import {
  createContext,
  createElement,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { getPlatformHealth } from "./api";
import type { PlatformHealth } from "./types";

const POLL_INTERVAL_MS = 30_000;

interface PlatformHealthState {
  health: PlatformHealth | null;
  loading: boolean;
  failed: boolean;
  reload: () => Promise<void>;
}

const PlatformHealthContext = createContext<PlatformHealthState | null>(null);

export function PlatformHealthProvider({ children }: { children: ReactNode }) {
  const [health, setHealth] = useState<PlatformHealth | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);

  const load = useCallback(async () => {
    try {
      setHealth(await getPlatformHealth());
      setFailed(false);
    } catch {
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const id = setInterval(() => void load(), POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [load]);

  const value = useMemo(
    () => ({ health, loading, failed, reload: load }),
    [health, loading, failed, load],
  );

  return createElement(PlatformHealthContext.Provider, { value }, children);
}

export function usePlatformHealth() {
  const value = useContext(PlatformHealthContext);
  if (!value) {
    throw new Error("usePlatformHealth must be used inside PlatformHealthProvider");
  }
  return value;
}
