"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { toast } from "sonner";
import { useAuth, getHomeRoute } from "@/lib/auth";
import { DashboardShell } from "./dashboard/dashboard-shell";
import { hasSeenOnboarding } from "@/lib/storage";
import { Shield } from "lucide-react";

const PUBLIC_PATHS = ["/login", "/installation", "/legal/source"];
const FULL_BLEED_PATHS = ["/onboarding"];

/** Config / admin routes restricted to platform admins. */
function isPlatformAdminOnlyPath(pathname: string): boolean {
  return pathname.startsWith("/dashboard/admin");
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const { user, isLoading } = useAuth();
  const pathname = usePathname();
  const router = useRouter();

  const isPublicPath = PUBLIC_PATHS.some((p) => pathname === p || pathname.startsWith(`${p}/`));

  const adminOnly = isPlatformAdminOnlyPath(pathname);

  const isFullBleedPath = FULL_BLEED_PATHS.some((p) => pathname.startsWith(p));

  useEffect(() => {
    if (isLoading) return;
    if (!user && !isPublicPath) {
      router.replace("/login");
      return;
    }
    if (user && !isPublicPath && !isFullBleedPath && !hasSeenOnboarding()) {
      router.replace("/onboarding");
      return;
    }
    if (user && adminOnly && user.role !== "PLATFORM_ADMIN") {
      const dest = getHomeRoute(user);
      toast.error("You do not have permission to access this page");
      router.replace(dest);
    }
  }, [isLoading, user, isPublicPath, isFullBleedPath, adminOnly, pathname, router]);

  if (isLoading) {
    return (
      <div className="flex h-screen w-screen items-center justify-center gap-3 text-muted-foreground">
        <Shield className="h-6 w-6 animate-pulse" />
        <span className="text-sm">Loading...</span>
      </div>
    );
  }

  if (isPublicPath) {
    return <div className="w-screen">{children}</div>;
  }

  if (!user) {
    return null;
  }

  if (isFullBleedPath) {
    return <div className="w-screen">{children}</div>;
  }

  return <DashboardShell>{children}</DashboardShell>;
}
