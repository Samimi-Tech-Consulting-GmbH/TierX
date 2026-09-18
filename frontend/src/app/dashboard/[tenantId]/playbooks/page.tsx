"use client";

import { Suspense } from "react";
import { useParams } from "next/navigation";
import { Loader2 } from "lucide-react";

import { PlaybooksView } from "@/components/playbooks-view";

export default function TenantPlaybooksPage() {
  return (
    <Suspense
      fallback={
        <div className="flex h-48 items-center justify-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-5 w-5 animate-spin" />
          Loading…
        </div>
      }
    >
      <TenantPlaybooksPageContent />
    </Suspense>
  );
}

function TenantPlaybooksPageContent() {
  const { tenantId } = useParams<{ tenantId: string }>();
  return <PlaybooksView tenantId={tenantId} />;
}
