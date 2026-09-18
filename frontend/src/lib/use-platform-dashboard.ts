"use client";

import { useCallback, useEffect, useState } from "react";

import { getPlatformDashboardSummary } from "./api";
import type { PlatformDashboardSummary } from "./types";

export function usePlatformDashboard() {
  const [summary, setSummary] = useState<PlatformDashboardSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setSummary(await getPlatformDashboardSummary());
    } catch (value) {
      setSummary(null);
      setError(value instanceof Error ? value.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return { summary, loading, error, reload: load };
}
