"use client";

import { useParams } from "next/navigation";

import { SchemaRegistryView } from "@/components/schema-registry-view";

export default function AlertTypeSchemaRegistryPage() {
  const { tenantId } = useParams<{ tenantId: string }>();
  return <SchemaRegistryView tenantId={tenantId} />;
}
