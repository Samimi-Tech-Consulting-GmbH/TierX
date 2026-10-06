"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { useAuth } from "@/lib/auth";
import {
  ALL_TENANTS,
  sectionHref,
  useSelectedTenant,
} from "@/lib/selected-tenant";
import { TenantSwitcher } from "@/components/dashboard/tenant-switcher";
import { ProductLinks } from "@/components/product-links";
import {
  SettingsMenu,
  type SettingsMenuItem,
} from "@/components/dashboard/settings-menu";
import { UserRole } from "@/lib/types";
import {
  Bell,
  Book,
  Building2,
  CircleArrowRight,
  Database,
  FileCode2,
  LayoutDashboard,
  Network,
  LibraryBig,
  Plug,
  ScanSearch,
  Settings,
  SlidersHorizontal,
  Users,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

const GROUPS = ["Analyst", "Configuration", "Operations", "Settings"] as const;
type NavGroup = (typeof GROUPS)[number];

interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  group: NavGroup;
  roles?: UserRole[];
  exact?: boolean;
}

function navItemActive(pathname: string, item: NavItem): boolean {
  const { href, exact } = item;
  if (exact) {
    return pathname === href || pathname === `${href}/`;
  }
  if (href === "/dashboard/admin") {
    return pathname === "/dashboard/admin" || pathname === "/dashboard/admin/";
  }
  if (href === "/dashboard/admin/tenants") {
    return /^\/dashboard\/admin\/tenants(\/[^/]+)?\/?$/.test(pathname);
  }
  if (href.endsWith("/alerts")) {
    return (
      pathname.startsWith(href) ||
      pathname.startsWith("/dashboard/admin/alerts")
    );
  }
  if (href.endsWith("/clusters")) {
    return (
      pathname.startsWith(href) ||
      pathname.startsWith("/dashboard/admin/clusters")
    );
  }
  if (href.endsWith("/schema-registry")) {
    return (
      pathname.startsWith(href) ||
      pathname.startsWith("/dashboard/admin/schema-registry")
    );
  }
  if (href.endsWith("/playbooks")) {
    return (
      pathname.startsWith(href) ||
      pathname.startsWith("/dashboard/admin/playbooks")
    );
  }
  return pathname.startsWith(href);
}

const navItems: NavItem[] = [
  {
    href: "/dashboard/admin",
    label: "Dashboard",
    icon: LayoutDashboard,
    group: "Analyst",
    roles: [UserRole.PLATFORM_ADMIN],
  },
  {
    href: "/dashboard/admin/debug",
    label: "Debug",
    icon: ScanSearch,
    group: "Operations",
    roles: [UserRole.PLATFORM_ADMIN],
  },
];

function settingsMenuItems(
  role: UserRole | undefined,
  tenantId: string | null,
): SettingsMenuItem[] {
  if (role === UserRole.PLATFORM_ADMIN) {
    return [
      tenantId && tenantId !== ALL_TENANTS
        ? {
            href: `/dashboard/admin/tenants/${tenantId}`,
            label: "Tenant details",
            icon: SlidersHorizontal,
          }
        : {
            href: "/dashboard/admin/tenants",
            label: "Tenants management",
            icon: Building2,
          },
      { href: "/users", label: "Users", icon: Users },
      {
        href: "/dashboard/admin/integrations/jira",
        label: "Jira integration",
        icon: Plug,
      },
      {
        href: "/dashboard/admin/integrations/enrichment-actions",
        label: "Enrichment actions",
        icon: Plug,
      },
    ];
  }

  if (role === UserRole.TENANT_ADMIN && tenantId) {
    return [
      {
        href: `/dashboard/${tenantId}/settings`,
        label: "Tenant settings",
        icon: Settings,
      },
      { href: "/users", label: "Users", icon: Users },
    ];
  }

  return [];
}

function tenantNavItems(tenantId: string, isPlatformAdmin: boolean): NavItem[] {
  return [
    ...(isPlatformAdmin
      ? []
      : [
          {
            href: `/dashboard/${tenantId}`,
            label: "Dashboard",
            icon: LayoutDashboard,
            group: "Analyst" as NavGroup,
            exact: true,
          },
        ]),
    {
      href: sectionHref("alerts", tenantId, isPlatformAdmin),
      label: "Alerts",
      icon: Bell,
      group: "Analyst",
    },
    {
      href: sectionHref("clusters", tenantId, isPlatformAdmin),
      label: "Clusters",
      icon: Network,
      group: "Analyst",
    },
    {
      href: sectionHref("schema-registry", tenantId, isPlatformAdmin),
      label: "Schema Registry",
      icon: Database,
      group: "Configuration",
    },
    {
      href: sectionHref("playbooks", tenantId, isPlatformAdmin),
      label: "Playbooks",
      icon: Book,
      group: "Configuration",
    },
    {
      href: sectionHref("knowledge-base", tenantId, isPlatformAdmin),
      label: "Knowledge Base",
      icon: LibraryBig,
      group: "Configuration",
    },
  ];
}

const ROW =
  "flex items-center gap-3 rounded-md px-3 py-2.5 text-sm transition-colors";

export function Sidebar({
  className,
  onNavigate,
}: {
  className?: string;
  onNavigate?: () => void;
}) {
  const pathname = usePathname();
  const { user, logout } = useAuth();
  const { selectedTenantId } = useSelectedTenant();
  const role = user?.role as UserRole | undefined;
  const isPlatformAdmin = role === UserRole.PLATFORM_ADMIN;

  const isTenantUser =
    !!user?.tenant_id &&
    !isPlatformAdmin &&
    ([UserRole.TENANT_ADMIN, UserRole.TENANT_OPERATOR] as UserRole[]).includes(
      role as UserRole,
    );

  const scopedTenantId = isPlatformAdmin
    ? selectedTenantId
    : isTenantUser
      ? user.tenant_id
      : null;

  const items = [
    ...navItems.filter(
      (item) => !item.roles || item.roles.includes(role as UserRole),
    ),
    ...(scopedTenantId ? tenantNavItems(scopedTenantId, isPlatformAdmin) : []),
  ];

  const settingsItems = settingsMenuItems(role, scopedTenantId);

  const groups = GROUPS.map((group) => ({
    group,
    items: items.filter((item) => item.group === group),
  })).filter((entry) => entry.items.length > 0);

  const releaseVersion =
    process.env.NEXT_PUBLIC_TIERX_RELEASE_VERSION ??
    process.env.NEXT_PUBLIC_APP_RELEASE_VERSION ??
    "development";
  const releaseSha =
    process.env.NEXT_PUBLIC_TIERX_RELEASE_SHA ??
    process.env.NEXT_PUBLIC_APP_RELEASE_SHA ??
    "development";

  return (
    <aside className={cn("flex flex-col", className)}>
      <div className="shrink-0 px-4 pt-4">
        <div className="border-b border-[#404040] pb-4">
          <TenantSwitcher onNavigate={onNavigate} placement="down" />
        </div>
      </div>

      <nav className="min-h-0 flex-1 space-y-7 overflow-y-auto px-4 py-6">
        {groups.map(({ group, items: groupItems }) => (
          <div key={group}>
            <p className="px-3 pb-2 text-xs text-muted-foreground">{group}</p>
            <div className="space-y-1">
              {groupItems.map((item) => {
                const active = navItemActive(pathname, item);
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    onClick={onNavigate}
                    aria-current={active ? "page" : undefined}
                    className={cn(
                      ROW,
                      active
                        ? "bg-primary font-medium text-primary-foreground"
                        : "text-[#d4d4d4] hover:bg-white/5 hover:text-foreground",
                    )}
                  >
                    <item.icon className="size-4 shrink-0" />
                    <span className="truncate">{item.label}</span>
                  </Link>
                );
              })}
            </div>
          </div>
        ))}
      </nav>

      {/* Padding sits outside the rule so it stops short of the sidebar edges. */}
      <div className="shrink-0 px-4 pb-6">
        <div className="border-t border-[#404040] pt-3">
          <SettingsMenu items={settingsItems} onNavigate={onNavigate} />

          <ProductLinks version={releaseVersion} sha={releaseSha} />
          <Link href="/legal/source" className={cn(ROW, "text-[#d4d4d4] hover:bg-white/5")}>
            <FileCode2 className="size-4 shrink-0" />
            <span>Source code (AGPL)</span>
          </Link>
          <button
            type="button"
            onClick={logout}
            className={cn(ROW, "w-full text-[#f87171] hover:bg-white/5")}
          >
            <CircleArrowRight className="size-4 shrink-0" />
            <span>Logout</span>
          </button>
        </div>
      </div>
    </aside>
  );
}
