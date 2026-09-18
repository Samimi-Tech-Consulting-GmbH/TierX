"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Building2, Check, ChevronsUpDown, Globe, Search } from "lucide-react";

import { ALL_TENANTS, useSelectedTenant } from "@/lib/selected-tenant";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

export function TenantSwitcher({
  onNavigate,
  placement = "up",
}: {
  onNavigate?: () => void;
  placement?: "up" | "down";
}) {
  const {
    tenants,
    selectedTenant,
    selectedTenantId,
    isAllTenants,
    canSwitch,
    loading,
    selectTenant,
  } = useSelectedTenant();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: MouseEvent) {
      if (rootRef.current?.contains(event.target as Node)) return;
      setOpen(false);
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  useEffect(() => {
    if (!open) setQuery("");
  }, [open]);

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return tenants;
    return tenants.filter(
      (t) =>
        t.display_name.toLowerCase().includes(q) ||
        t.name.toLowerCase().includes(q),
    );
  }, [query, tenants]);

  const label = isAllTenants
    ? "All tenants"
    : (selectedTenant?.display_name ??
      (loading ? "Loading tenants…" : (selectedTenantId ?? "No tenant")));

  if (!canSwitch) {
    return (
      <div>
        <p className="px-3 pb-1 text-[11px] font-bold uppercase tracking-wide text-muted-foreground">
          Tenant
        </p>
        <div className="flex items-center gap-3 rounded-md px-3 py-2 text-base font-bold text-foreground">
          <Building2 className="size-5 shrink-0 text-primary" />
          <span className="truncate" title={label}>
            {label}
          </span>
        </div>
      </div>
    );
  }

  return (
    <div className="relative" ref={rootRef}>
      <p className="px-3 pb-1 text-[11px] font-bold uppercase tracking-wide text-muted-foreground">
        Current tenant
      </p>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="listbox"
        className={cn(
          "flex w-full items-center gap-3 rounded-md px-3 py-2 text-base font-bold transition-colors",
          open
            ? "bg-white/10 text-foreground"
            : "text-foreground hover:bg-white/5",
        )}
      >
        {isAllTenants ? (
          <Globe className="size-5 shrink-0 text-primary" />
        ) : (
          <Building2 className="size-5 shrink-0 text-primary" />
        )}
        <span className="min-w-0 flex-1 truncate text-left" title={label}>
          {label}
        </span>
        <ChevronsUpDown className="size-4 shrink-0 text-muted-foreground" />
      </button>

      {open && (
        <div
          role="listbox"
          className={cn(
            "absolute left-0 z-30 w-full overflow-hidden rounded-lg border border-[#404040] bg-card shadow-lg",
            placement === "up" ? "bottom-full mb-2" : "top-full mt-2",
          )}
        >
          <div className="relative border-b border-white/5 p-2">
            <Search className="pointer-events-none absolute left-5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              autoFocus
              className="h-9 bg-[#404040] pl-9"
              placeholder="Search tenants…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
          <div className="max-h-[280px] overflow-y-auto p-1">
            {/* Platform-wide scope: every list and its search span all tenants. */}
            {query.trim() === "" ? (
              <button
                type="button"
                role="option"
                aria-selected={isAllTenants}
                onClick={() => {
                  selectTenant(ALL_TENANTS);
                  setOpen(false);
                  onNavigate?.();
                }}
                className={cn(
                  "mb-1 flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm transition-colors",
                  isAllTenants
                    ? "bg-primary/20 text-foreground"
                    : "text-[#d4d4d4] hover:bg-white/5 hover:text-foreground",
                )}
              >
                <Globe className="size-4 shrink-0 text-primary" />
                <span className="min-w-0 flex-1 font-bold">All tenants</span>
                {isAllTenants ? (
                  <Check className="size-4 shrink-0 text-primary" />
                ) : null}
              </button>
            ) : null}
            {matches.length === 0 ? (
              <p className="px-3 py-6 text-center text-xs text-muted-foreground">
                {loading ? "Loading tenants…" : "No tenants match."}
              </p>
            ) : (
              matches.map((tenant) => {
                const active = tenant.tenant_id === selectedTenantId;
                return (
                  <button
                    key={tenant.tenant_id}
                    type="button"
                    role="option"
                    aria-selected={active}
                    onClick={() => {
                      selectTenant(tenant.tenant_id);
                      setOpen(false);
                      onNavigate?.();
                    }}
                    className={cn(
                      "flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm transition-colors",
                      active
                        ? "bg-primary/20 text-foreground"
                        : "text-[#d4d4d4] hover:bg-white/5 hover:text-foreground",
                    )}
                  >
                    <span className="min-w-0 flex-1">
                      <span className="block truncate">
                        {tenant.display_name}
                      </span>
                      <span className="block truncate font-mono text-[10px] text-muted-foreground">
                        {tenant.name}
                      </span>
                    </span>
                    {active ? (
                      <Check className="size-4 shrink-0 text-primary" />
                    ) : null}
                  </button>
                );
              })
            )}
          </div>
        </div>
      )}
    </div>
  );
}
