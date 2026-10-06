"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { X } from "lucide-react";

import { cn } from "@/lib/utils";
import { PlatformHealthProvider } from "@/lib/use-platform-health";
import { LatestReleaseProvider } from "@/lib/use-latest-release";
import { SelectedTenantProvider } from "@/lib/selected-tenant";

import { DashboardHeader } from "./dashboard-header";
import { Sidebar } from "../sidebar";

export function DashboardShell({ children }: { children: React.ReactNode }) {
  const [navOpen, setNavOpen] = useState(false);
  const pathname = usePathname();

  useEffect(() => setNavOpen(false), [pathname]);

  return (
    <PlatformHealthProvider>
      <LatestReleaseProvider>
      <SelectedTenantProvider>
        <div className="dark brand-dark flex h-dvh w-full flex-col overflow-hidden bg-background text-foreground">
          <DashboardHeader onMenuClick={() => setNavOpen(true)} />

          <div className="flex min-h-0 flex-1">
            <Sidebar className="hidden w-[270px] shrink-0 lg:flex" />

            <div
              className={cn(
                "fixed inset-0 z-50 lg:hidden",
                !navOpen && "pointer-events-none",
              )}
              inert={!navOpen}
            >
              <div
                className={cn(
                  "absolute inset-0 bg-black/60 transition-opacity duration-300 ease-out motion-reduce:transition-none",
                  navOpen ? "opacity-100" : "opacity-0",
                )}
                onClick={() => setNavOpen(false)}
                aria-hidden="true"
              />
              <div
                className={cn(
                  "absolute inset-y-0 left-0 flex w-[270px] max-w-[85vw] flex-col bg-background shadow-xl transition-transform duration-300 ease-out motion-reduce:transition-none",
                  navOpen ? "translate-x-0" : "-translate-x-full",
                )}
              >
                <div className="flex justify-end p-2">
                  <button
                    type="button"
                    onClick={() => setNavOpen(false)}
                    aria-label="Close navigation"
                    className="rounded-md p-2 text-[#d4d4d4] hover:bg-white/5"
                  >
                    <X className="size-5" />
                  </button>
                </div>
                <Sidebar
                  className="min-h-0 flex-1"
                  onNavigate={() => setNavOpen(false)}
                />
              </div>
            </div>

            <main className="min-w-0 flex-1 overflow-y-auto">
              <div className="px-4 py-6 lg:px-8 lg:py-8">{children}</div>
            </main>
          </div>
        </div>
      </SelectedTenantProvider>
      </LatestReleaseProvider>
    </PlatformHealthProvider>
  );
}
