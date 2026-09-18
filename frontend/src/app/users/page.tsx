"use client";

import { useEffect, useState, useCallback } from "react";
import { toast } from "sonner";
import { useAuth } from "@/lib/auth";
import { listAllUsers, listTenantUsers, listTenants } from "@/lib/api";
import { UserRole } from "@/lib/types";
import type { UserDocument } from "@/lib/types";
import { CreateUserDialog } from "@/components/create-user-dialog";
import { formatLocaleDateTime } from "@/lib/datetime";
import { PILL, TABLE_HEAD, TABLE_ROW } from "@/lib/cluster-display";
import { cn } from "@/lib/utils";

const ROLE_TONE: Record<string, string> = {
  [UserRole.PLATFORM_ADMIN]: "bg-primary",
  [UserRole.TENANT_ADMIN]: "bg-[#2563eb]",
  [UserRole.TENANT_OPERATOR]: "bg-[#525252]",
};

export default function UsersPage() {
  const { user } = useAuth();
  const [users, setUsers] = useState<UserDocument[]>([]);
  const [tenantMap, setTenantMap] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);

  const isPlatformAdmin = user?.role === UserRole.PLATFORM_ADMIN;

  const fetchUsers = useCallback(async () => {
    setLoading(true);
    try {
      if (isPlatformAdmin) {
        const [usersData, tenantsData] = await Promise.all([
          listAllUsers(),
          listTenants(),
        ]);
        setUsers(usersData);
        const map: Record<string, string> = {};
        for (const t of tenantsData) {
          map[t.tenant_id] = t.display_name;
        }
        setTenantMap(map);
      } else if (user?.tenant_id) {
        setUsers(await listTenantUsers(user.tenant_id));
      }
    } catch {
      toast.error("Failed to load users");
    } finally {
      setLoading(false);
    }
  }, [isPlatformAdmin, user?.tenant_id]);

  useEffect(() => {
    fetchUsers();
  }, [fetchUsers]);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-2">
          <h1 className="text-3xl font-bold tracking-tight">Users</h1>
          <p className="text-base text-muted-foreground">
            {isPlatformAdmin
              ? "Manage all platform users across tenants."
              : "Manage operators in your tenant."}
          </p>
        </div>
        <CreateUserDialog onCreated={fetchUsers} />
      </div>

      <div className="overflow-hidden rounded-lg bg-card">
        {loading ? (
          <div className="space-y-3 p-6">
            {Array.from({ length: 5 }).map((_, index) => (
              <div
                key={index}
                className="h-10 w-full animate-pulse rounded bg-white/5"
              />
            ))}
          </div>
        ) : users.length === 0 ? (
          <p className="p-10 text-center text-sm text-muted-foreground">
            No users found.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-left">
              <thead className={TABLE_HEAD}>
                <tr>
                  <th className="px-6 py-4">Email</th>
                  <th className="px-6 py-4">Role</th>
                  {isPlatformAdmin && <th className="px-6 py-4">Tenant</th>}
                  <th className="px-6 py-4">Status</th>
                  <th className="px-6 py-4">Created</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.user_id} className={TABLE_ROW}>
                    <td className="px-6 py-4 text-sm font-medium text-foreground">
                      {u.email}
                    </td>
                    <td className="px-6 py-4">
                      <span
                        className={cn(
                          PILL,
                          ROLE_TONE[u.role] ?? "bg-[#525252]",
                        )}
                      >
                        {u.role.replace(/_/g, " ")}
                      </span>
                    </td>
                    {isPlatformAdmin && (
                      <td className="px-6 py-4 text-sm text-muted-foreground">
                        {u.tenant_id
                          ? (tenantMap[u.tenant_id] ?? u.tenant_id)
                          : "—"}
                      </td>
                    )}
                    <td className="px-6 py-4">
                      <span
                        className={cn(
                          PILL,
                          u.is_active ? "bg-[#16a34a]" : "bg-[#525252]",
                        )}
                      >
                        {u.is_active ? "Active" : "Inactive"}
                      </span>
                    </td>
                    <td className="whitespace-nowrap px-6 py-4 text-sm text-muted-foreground">
                      {formatLocaleDateTime(u.created_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
