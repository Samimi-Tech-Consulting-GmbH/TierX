"use client";

import { useEffect, useState, type ReactNode } from "react";
import { ArrowLeft, ArrowUpRight, Plus, Search, Workflow } from "lucide-react";
import { listTenantPage } from "@/lib/api";
import type { TenantDocument } from "@/lib/types";

export const studioButton =
  "inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border border-border bg-card px-3 py-2 text-sm font-medium transition-colors hover:bg-muted focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary disabled:cursor-not-allowed disabled:opacity-50";
export const studioPrimary = `${studioButton} !border-primary !bg-primary !text-primary-foreground hover:!bg-primary/90`;

export function ResourceLibrary({
  title,
  description,
  createLabel,
  onCreate,
  items,
  loading,
  error,
  children,
}: {
  title: string;
  description: string;
  createLabel: string;
  onCreate: () => void;
  items: {
    id: string;
    name: string;
    description: string;
    metadata: string;
    status: string;
    onOpen: () => void;
  }[];
  loading?: boolean;
  error?: string;
  children?: ReactNode;
}) {
  const [query, setQuery] = useState("");
  const filtered = items.filter((item) =>
    `${item.name} ${item.description} ${item.id}`
      .toLowerCase()
      .includes(query.trim().toLowerCase()),
  );
  return (
    <main className="mx-auto max-w-7xl space-y-7 p-4 md:p-8">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">{title}</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
            {description}
          </p>
        </div>
        <button className={studioPrimary} onClick={onCreate}>
          <Plus size={16} />
          {createLabel}
        </button>
      </header>
      {error && (
        <p
          role="alert"
          className="rounded-lg border border-destructive/40 p-4 text-sm"
        >
          {error}
        </p>
      )}
      <div className="flex flex-wrap items-center gap-4">
        <label className="relative w-full max-w-md">
          <Search
            className="absolute left-3 top-3 text-muted-foreground"
            size={16}
          />
          <input
            aria-label={`Search ${title.toLowerCase()}`}
            placeholder={`Search ${title.toLowerCase()}…`}
            className="h-10 w-full rounded-lg border bg-card pl-10 pr-3 text-sm"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
        {!loading && (
          <span className="text-sm text-muted-foreground">
            {filtered.length} {filtered.length === 1 ? "item" : "items"}
          </span>
        )}
      </div>
      {loading ? (
        <p role="status" className="py-20 text-center text-muted-foreground">
          Loading {title.toLowerCase()}…
        </p>
      ) : error && !items.length ? (
        <p className="py-12 text-center text-sm text-muted-foreground">
          The library could not be loaded. Refresh to try again.
        </p>
      ) : filtered.length ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {filtered.map((item) => (
            <button
              key={item.id}
              onClick={item.onOpen}
              className="group flex min-h-48 flex-col rounded-xl border bg-card p-5 text-left transition-colors hover:border-primary/60 focus-visible:outline-2 focus-visible:outline-primary"
            >
              <div className="mb-4 flex w-full items-center gap-3">
                <span className="rounded-lg bg-primary/10 p-2 text-primary">
                  <Workflow size={20} />
                </span>
                <span className="ml-auto rounded-full bg-muted px-2.5 py-1 text-xs">
                  {item.status}
                </span>
                <ArrowUpRight
                  size={16}
                  className="text-muted-foreground group-hover:text-primary"
                />
              </div>
              <h2 className="font-semibold">{item.name}</h2>
              <p className="mt-2 line-clamp-2 text-sm leading-6 text-muted-foreground">
                {item.description || "Open to view and configure."}
              </p>
              <p className="mt-auto pt-5 text-xs text-muted-foreground">
                {item.metadata}
              </p>
            </button>
          ))}
        </div>
      ) : (
        <section className="rounded-xl border border-dashed py-16 text-center">
          <Workflow className="mx-auto mb-4 text-muted-foreground" size={30} />
          <h2 className="font-medium">
            {query ? "No matching results" : `No ${title.toLowerCase()} yet`}
          </h2>
          <p className="mt-2 text-sm text-muted-foreground">
            {query
              ? "Try another name or clear your search."
              : "Create your first item to get started."}
          </p>
        </section>
      )}
      {children}
    </main>
  );
}

export function EditorBack({
  onClick,
  label,
}: {
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      className="inline-flex min-h-10 items-center gap-2 text-sm text-muted-foreground hover:text-foreground focus-visible:outline-2 focus-visible:outline-primary"
      onClick={onClick}
    >
      <ArrowLeft size={16} />
      {label}
    </button>
  );
}

/** Paged lookup keeps UUIDs out of the normal editing task without truncating tenants. */
export function TenantSelection({
  value,
  onChange,
  multiple = false,
  disabled = false,
  label = "Tenant access",
}: {
  value: string[];
  onChange: (ids: string[]) => void;
  multiple?: boolean;
  disabled?: boolean;
  label?: string;
}) {
  const [query, setQuery] = useState(""),
    [page, setPage] = useState(0),
    [total, setTotal] = useState(0);
  const [rows, setRows] = useState<TenantDocument[]>([]),
    [known, setKnown] = useState<Record<string, string>>({}),
    [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    const timer = setTimeout(() => {
      listTenantPage({ search: query || undefined, skip: page * 25, limit: 25 })
        .then((result) => {
          if (active) {
            setRows(result.items);
            setTotal(result.total);
            setKnown((old) => ({
              ...old,
              ...Object.fromEntries(
                result.items.map((t) => [
                  t.tenant_id,
                  t.display_name || t.name,
                ]),
              ),
            }));
            setError("");
          }
        })
        .catch(() => {
          if (active)
            setError(
              "Tenant lookup unavailable. Existing selection is preserved.",
            );
        });
    }, 200);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [query, page]);
  return (
    <fieldset
      disabled={disabled}
      className="space-y-3 rounded-xl border bg-card p-4"
    >
      <legend className="px-1 text-sm font-medium">{label}</legend>
      <label className="block text-xs text-muted-foreground">
        Find a tenant
        <input
          aria-label={`Search ${label.toLowerCase()}`}
          className="mt-1 h-10 w-full rounded-lg border bg-background px-3 text-sm"
          placeholder="Search by name…"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setPage(0);
          }}
        />
      </label>
      {error && (
        <p role="alert" className="text-xs text-amber-500">
          {error}
        </p>
      )}
      <select
        aria-label={label}
        className="h-10 w-full rounded-lg border bg-background px-2 text-sm"
        value={multiple ? "" : value[0] || ""}
        onChange={(e) => {
          if (e.target.value)
            onChange(
              multiple
                ? [...new Set([...value, e.target.value])]
                : [e.target.value],
            );
        }}
      >
        <option value="">{multiple ? "Add tenant…" : "Select tenant…"}</option>
        {value
          .filter((id) => !rows.some((t) => t.tenant_id === id))
          .map((id) => (
            <option key={id} value={id}>
              {known[id] || `Selected tenant · ${id.slice(0, 8)}`}
            </option>
          ))}
        {rows.map((t) => (
          <option key={t.tenant_id} value={t.tenant_id}>
            {t.display_name || t.name}
          </option>
        ))}
      </select>
      {multiple && (
        <div className="flex flex-wrap gap-2">
          {value.map((id) => (
            <span
              key={id}
              className="inline-flex items-center gap-2 rounded-md bg-muted px-2 py-1 text-xs"
            >
              {known[id] || `Tenant · ${id.slice(0, 8)}`}
              <button
                type="button"
                aria-label={`Remove tenant ${known[id] || id}`}
                onClick={() => onChange(value.filter((v) => v !== id))}
              >
                ×
              </button>
            </span>
          ))}
        </div>
      )}
      {total > 25 && (
        <div className="flex items-center gap-3 text-xs">
          <button
            className="underline disabled:opacity-40"
            disabled={page === 0}
            onClick={() => setPage(page - 1)}
          >
            Previous tenants
          </button>
          <span>
            {page + 1} / {Math.ceil(total / 25)}
          </span>
          <button
            className="underline disabled:opacity-40"
            disabled={(page + 1) * 25 >= total}
            onClick={() => setPage(page + 1)}
          >
            Next tenants
          </button>
        </div>
      )}
      {multiple && !value.length && (
        <p className="text-xs text-muted-foreground">
          No tenants authorized yet. Add at least one before publishing.
        </p>
      )}
    </fieldset>
  );
}
