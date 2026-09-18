"use client";

import { useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft, Loader2, Search } from "lucide-react";

import { useAuth } from "@/lib/auth";
import { UserRole } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PANEL, PANEL_NOTE, PANEL_TITLE, PILL } from "@/lib/cluster-display";
import {
  SchemaFieldsPanel,
  useSchemaDetail,
} from "@/components/schema-detail-view";
import { cn } from "@/lib/utils";


export default function AlertTypeSchemaFieldsPage() {
  const { tenantId, schemaId } = useParams<{
    tenantId: string;
    schemaId: string;
  }>();
  const { user } = useAuth();
  const [query, setQuery] = useState("");

  const canWrite =
    user?.role === UserRole.PLATFORM_ADMIN ||
    user?.role === UserRole.TENANT_ADMIN;

  const detail = useSchemaDetail({ tenantId, schemaId, canWrite });
  const { displayDoc, loading } = detail;

  const backHref = `/dashboard/${tenantId}/schema-registry?schema=${encodeURIComponent(schemaId)}`;

  function accessDenied(): boolean {
    if (!user) return true;
    if (user.role === UserRole.PLATFORM_ADMIN) return false;
    return user.tenant_id !== tenantId;
  }

  if (accessDenied()) {
    return (
      <div className={PANEL}>
        <h3 className={PANEL_TITLE}>Access denied</h3>
        <p className={PANEL_NOTE}>
          You can only view schemas for your own tenant.
        </p>
      </div>
    );
  }

  if (loading && !displayDoc) {
    return (
      <div className="flex h-48 items-center justify-center gap-2 text-muted-foreground">
        <Loader2 className="h-5 w-5 animate-spin" />
        Loading fields…
      </div>
    );
  }

  if (!displayDoc) {
    return (
      <div className={PANEL}>
        <h3 className={PANEL_TITLE}>Schema not found</h3>
        <p className={PANEL_NOTE}>
          It may have been removed, or it belongs to another tenant.{" "}
          <Link
            href={`/dashboard/${tenantId}/schema-registry`}
            className="font-bold text-primary underline-offset-4 hover:underline"
          >
            Back to the registry
          </Link>
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-start gap-3">
          <Button
            variant="ghost"
            size="icon"
            nativeButton={false}
            render={<Link href={backHref} />}
          >
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <div className="min-w-0">
            <h1 className="truncate font-mono text-2xl font-bold tracking-tight">
              {displayDoc.alert_type}
            </h1>
            <div className="mt-2 flex flex-wrap items-center gap-3">
              <span className="text-sm text-muted-foreground">
                Version{" "}
                <span className="font-bold tabular-nums text-foreground">
                  v{displayDoc.version}
                </span>
              </span>
              <span
                className={cn(
                  PILL,
                  displayDoc.is_active ? "bg-[#16a34a]" : "bg-[#525252]",
                )}
              >
                {displayDoc.is_active ? "Active" : "Draft"}
              </span>
              {displayDoc.description ? (
                <span className="text-sm text-muted-foreground">
                  {displayDoc.description}
                </span>
              ) : null}
            </div>
          </div>
        </div>

        <div className="relative w-full shrink-0 sm:w-[280px]">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            className="h-10 bg-[#404040] pl-9"
            placeholder="Filter fields…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            autoComplete="off"
          />
        </div>
      </div>

      <SchemaFieldsPanel detail={detail} query={query} />
    </div>
  );
}
