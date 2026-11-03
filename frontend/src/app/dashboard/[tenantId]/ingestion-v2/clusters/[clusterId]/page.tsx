"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { workflowRequest } from "@/lib/workflows";

export default function Page() {
  const { tenantId, clusterId } = useParams<{
    tenantId: string;
    clusterId: string;
  }>();
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    workflowRequest<Record<string, unknown>>(
      `/tenants/${encodeURIComponent(tenantId)}/clusters/${encodeURIComponent(clusterId)}`,
      "GET",
      undefined,
      controller.signal,
    )
      .then(setResult)
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      });
    return () => controller.abort();
  }, [tenantId, clusterId]);
  return (
    <main className="space-y-4 p-4">
      <Link
        className="underline"
        href={`/dashboard/${encodeURIComponent(tenantId)}/ingestion-v2`}
      >
        Back to Ingestion V2
      </Link>
      <h1 className="text-2xl font-bold">Experimental V2 cluster</h1>
      <p className="break-all">{clusterId}</p>
      <p className="text-sm text-muted-foreground">
        This cluster is isolated from V1. Analysis does not execute response
        actions or set an analyst verdict.
      </p>
      {error && <p role="alert">{error}</p>}
      {!result && !error && <p role="status">Loading cluster…</p>}
      {result &&
        Object.entries(result).map(([label, value]) => (
          <section key={label} className="rounded border p-3">
            <h2 className="font-semibold capitalize">{label}</h2>
            <pre className="mt-2 max-h-[600px] overflow-auto whitespace-pre-wrap break-words text-xs">
              {JSON.stringify(value, null, 2)}
            </pre>
          </section>
        ))}
    </main>
  );
}
