"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";

/** Legacy URL; tenant home lives under `/dashboard/[tenantId]`. */
export default function MyTenantRedirectPage() {
  const { user, isLoading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (isLoading) return;
    if (!user?.tenant_id) {
      router.replace("/login");
      return;
    }
    router.replace(`/dashboard/${user.tenant_id}`);
  }, [user, isLoading, router]);

  return (
    <div className="flex h-64 items-center justify-center text-muted-foreground">
      Redirecting…
    </div>
  );
}
