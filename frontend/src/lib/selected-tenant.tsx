"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { usePathname, useRouter } from "next/navigation";

import { getMyTenant, listTenants } from "@/lib/api";
import type { TenantDocument } from "@/lib/types";
import { UserRole } from "@/lib/types";
import { useAuth } from "@/lib/auth";
import { readSelectedTenant, writeSelectedTenant } from "@/lib/storage";

export const ALL_TENANTS = "all";

const SECTIONS = {
  alerts: {
    all: "/dashboard/admin/alerts",
    admin: (id: string) => `/dashboard/admin/tenants/${id}/alerts`,
    tenant: (id: string) => `/dashboard/${id}/alerts`,
  },
  clusters: {
    all: "/dashboard/admin/clusters",
    admin: (id: string) => `/dashboard/admin/tenants/${id}/clusters`,
    tenant: (id: string) => `/dashboard/${id}/clusters`,
  },
  "schema-registry": {
    all: "/dashboard/admin/schema-registry",
    admin: (id: string) => `/dashboard/${id}/schema-registry`,
    tenant: (id: string) => `/dashboard/${id}/schema-registry`,
  },
  playbooks: {
    all: "/dashboard/admin/playbooks",
    admin: (id: string) => `/dashboard/${id}/playbooks`,
    tenant: (id: string) => `/dashboard/${id}/playbooks`,
  },
  "knowledge-base": {
    all: "/dashboard/admin/knowledge-base",
    admin: (id: string) => `/dashboard/${id}/knowledge-base`,
    tenant: (id: string) => `/dashboard/${id}/knowledge-base`,
  },
} as const;

export type SectionKey = keyof typeof SECTIONS;

export function sectionHref(
  section: SectionKey,
  tenantId: string,
  isPlatformAdmin = true,
): string {
  const entry = SECTIONS[section];
  if (tenantId === ALL_TENANTS) return entry.all;
  return isPlatformAdmin ? entry.admin(tenantId) : entry.tenant(tenantId);
}

interface SelectedTenantContextValue {
  tenants: TenantDocument[];
  selectedTenantId: string | null;
  selectedTenant: TenantDocument | null;
  isAllTenants: boolean;
  canSwitch: boolean;
  loading: boolean;
  selectTenant: (tenantId: string) => void;
}

const SelectedTenantContext = createContext<SelectedTenantContextValue | null>(
  null,
);

export function tenantIdFromPath(pathname: string): string | null {
  for (const entry of Object.values(SECTIONS)) {
    if (pathname === entry.all || pathname.startsWith(`${entry.all}/`)) {
      return ALL_TENANTS;
    }
  }
  const adminMatch = pathname.match(/^\/dashboard\/admin\/tenants\/([^/]+)/);
  if (adminMatch) return adminMatch[1];
  const match = pathname.match(/^\/dashboard\/([^/]+)/);
  if (!match || match[1] === "admin") return null;
  return match[1];
}

function sectionFromPath(pathname: string): SectionKey | null {
  for (const [key, entry] of Object.entries(SECTIONS) as [
    SectionKey,
    (typeof SECTIONS)[SectionKey],
  ][]) {
    if (pathname === entry.all || pathname.startsWith(`${entry.all}/`)) {
      return key;
    }
  }
  const rest =
    pathname.match(/^\/dashboard\/admin\/tenants\/[^/]+\/([^/]+)/)?.[1] ??
    pathname.match(/^\/dashboard\/(?!admin\/)[^/]+\/([^/]+)/)?.[1];
  return rest && rest in SECTIONS ? (rest as SectionKey) : null;
}

export function pathForTenant(
  pathname: string,
  tenantId: string,
): string | null {
  const section = sectionFromPath(pathname);
  return section ? sectionHref(section, tenantId, true) : null;
}

export function SelectedTenantProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const { user } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  const isPlatformAdmin = user?.role === UserRole.PLATFORM_ADMIN;

  const [tenants, setTenants] = useState<TenantDocument[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedTenantId, setSelectedTenantId] = useState<string | null>(null);

  const pendingScopeRef = useRef<string | null>(null);

  useEffect(() => {
    if (isPlatformAdmin || !user?.tenant_id) return;
    const ownTenantId = user.tenant_id;
    let cancelled = false;
    setSelectedTenantId(ownTenantId);
    setLoading(true);
    getMyTenant(ownTenantId)
      .then((tenant) => {
        if (!cancelled && tenant) setTenants([tenant]);
      })
      .catch(() => {
        if (!cancelled) setTenants([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [isPlatformAdmin, user?.tenant_id]);

  useEffect(() => {
    if (!isPlatformAdmin) return;
    let cancelled = false;
    setLoading(true);
    listTenants({ limit: 500 })
      .then((rows) => {
        if (cancelled) return;
        setTenants(rows);
        const stored = readSelectedTenant();
        const fromPath = tenantIdFromPath(window.location.pathname);
        const valid = (id: string | null) =>
          id === ALL_TENANTS || (id && rows.some((t) => t.tenant_id === id))
            ? id
            : null;
        const next = valid(fromPath) ?? valid(stored) ?? ALL_TENANTS;
        setSelectedTenantId(next);
        writeSelectedTenant(next);
      })
      .catch(() => {
        if (!cancelled) setTenants([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [isPlatformAdmin]);

  useEffect(() => {
    if (!isPlatformAdmin) return;
    const fromPath = tenantIdFromPath(pathname);

    if (pendingScopeRef.current !== null) {
      if (fromPath === null || fromPath === pendingScopeRef.current) {
        pendingScopeRef.current = null;
      }
      return;
    }

    if (!fromPath || fromPath === selectedTenantId) return;
    if (
      fromPath !== ALL_TENANTS &&
      tenants.length > 0 &&
      !tenants.some((t) => t.tenant_id === fromPath)
    ) {
      return;
    }
    setSelectedTenantId(fromPath);
    writeSelectedTenant(fromPath);
  }, [isPlatformAdmin, pathname, selectedTenantId, tenants]);

  const selectTenant = useCallback(
    (tenantId: string) => {
      if (!isPlatformAdmin || tenantId === selectedTenantId) return;
      setSelectedTenantId(tenantId);
      writeSelectedTenant(tenantId);
      pendingScopeRef.current = tenantId;
      const next = pathForTenant(pathname, tenantId);
      if (next && next !== pathname) router.push(next);
    },
    [isPlatformAdmin, pathname, router, selectedTenantId],
  );

  const value = useMemo<SelectedTenantContextValue>(() => {
    const ownTenant =
      !isPlatformAdmin && user?.tenant_id
        ? (tenants.find((t) => t.tenant_id === user.tenant_id) ?? null)
        : null;
    return {
      tenants,
      selectedTenantId,
      selectedTenant:
        tenants.find((t) => t.tenant_id === selectedTenantId) ?? ownTenant,
      isAllTenants: selectedTenantId === ALL_TENANTS,
      canSwitch: Boolean(isPlatformAdmin),
      loading,
      selectTenant,
    };
  }, [
    isPlatformAdmin,
    loading,
    selectTenant,
    selectedTenantId,
    tenants,
    user?.tenant_id,
  ]);

  return (
    <SelectedTenantContext.Provider value={value}>
      {children}
    </SelectedTenantContext.Provider>
  );
}

export function useSelectedTenant(): SelectedTenantContextValue {
  const ctx = useContext(SelectedTenantContext);
  if (!ctx) {
    throw new Error(
      "useSelectedTenant must be used within a SelectedTenantProvider",
    );
  }
  return ctx;
}
