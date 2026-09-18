"use client";

import { useCallback, useEffect, useState } from "react";

import { getTenantDashboardSummary } from "./api";
import type { TenantDashboardSummary } from "./types";

export function useTenantDashboard(tenantId: string) {
  const [summary, setSummary] = useState<TenantDashboardSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setSummary(await getTenantDashboardSummary(tenantId));
    } catch (value) {
      setSummary(null);
      setError(value instanceof Error ? value.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }, [tenantId]);

  useEffect(() => {
    void load();
  }, [load]);

  return { summary, loading, error, reload: load };
}
