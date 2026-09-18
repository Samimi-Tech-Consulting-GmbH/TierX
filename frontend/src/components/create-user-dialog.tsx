"use client";

import { useState, useEffect } from "react";
import { toast } from "sonner";
import { Plus } from "lucide-react";
import { useAuth } from "@/lib/auth";
import {
  createUserAdmin,
  createTenantUser,
  listTenants,
  ApiError,
} from "@/lib/api";
import { UserRole } from "@/lib/types";
import type { TenantDocument } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

interface Props {
  onCreated: () => void;
}

export function CreateUserDialog({ onCreated }: Props) {
  const { user } = useAuth();
  const isPlatformAdmin = user?.role === UserRole.PLATFORM_ADMIN;

  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<UserRole>(UserRole.TENANT_OPERATOR);
  const [tenantId, setTenantId] = useState("");
  const [tenants, setTenants] = useState<TenantDocument[]>([]);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (open && isPlatformAdmin) {
      listTenants().then(setTenants).catch(() => {});
    }
  }, [open, isPlatformAdmin]);

  function reset() {
    setEmail("");
    setPassword("");
    setRole(UserRole.TENANT_OPERATOR);
    setTenantId("");
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);

    try {
      if (isPlatformAdmin) {
        await createUserAdmin({
          email,
          password,
          role,
          tenant_id: role === UserRole.PLATFORM_ADMIN ? undefined : tenantId,
        });
      } else {
        await createTenantUser(user!.tenant_id!, {
          email,
          password,
          role: UserRole.TENANT_OPERATOR,
        });
      }
      toast.success("User created");
      reset();
      setOpen(false);
      onCreated();
    } catch (err) {
      toast.error(
        err instanceof ApiError ? err.detail : "Failed to create user",
      );
    } finally {
      setSubmitting(false);
    }
  }

  const availableRoles = [
    UserRole.PLATFORM_ADMIN,
    UserRole.TENANT_ADMIN,
    UserRole.TENANT_OPERATOR,
  ];

  const showTenantPicker =
    isPlatformAdmin && role !== UserRole.PLATFORM_ADMIN;

  return (
    <>
      <Button onClick={() => setOpen(true)}>
        <Plus className="mr-2 h-4 w-4" />
        New User
      </Button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Create User</DialogTitle>
            <DialogDescription>
              {isPlatformAdmin
                ? "Create a user with any role and assign to a tenant."
                : "Create a new operator for your tenant."}
            </DialogDescription>
          </DialogHeader>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="user_email">Email</Label>
              <Input
                id="user_email"
                type="email"
                placeholder="user@example.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="user_password">Password</Label>
              <Input
                id="user_password"
                type="password"
                placeholder="Min. 8 characters"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                minLength={8}
              />
            </div>

            {isPlatformAdmin && (
              <div className="space-y-2">
                <Label>Role</Label>
                <Select
                  value={role}
                  onValueChange={(v) => setRole(v as UserRole)}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {availableRoles.map((r) => (
                      <SelectItem key={r} value={r}>
                        {r.replace(/_/g, " ")}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}

            {showTenantPicker && (
              <div className="space-y-2">
                <Label>Tenant</Label>
                <Select value={tenantId} onValueChange={(v) => setTenantId(v ?? "")}>
                  <SelectTrigger>
                    <SelectValue placeholder="Select a tenant" />
                  </SelectTrigger>
                  <SelectContent>
                    {tenants.map((t) => (
                      <SelectItem key={t.tenant_id} value={t.tenant_id}>
                        {t.display_name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}

            <DialogFooter>
              <Button
                variant="outline"
                type="button"
                onClick={() => setOpen(false)}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                disabled={
                  submitting ||
                  !email ||
                  !password ||
                  (showTenantPicker && !tenantId)
                }
              >
                {submitting ? "Creating..." : "Create"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  );
}
