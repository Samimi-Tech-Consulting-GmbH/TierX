"use client";

import { useState } from "react";
import { toast } from "sonner";
import { updateTenantStatus } from "@/lib/api";
import { TenantStatus, VALID_TRANSITIONS } from "@/lib/types";
import type { TenantDocument } from "@/lib/types";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { StatusBadge } from "@/components/status-badge";

const transitionDescriptions: Record<string, string> = {
  [`${TenantStatus.ONBOARDING}→${TenantStatus.ACTIVE}`]:
    "Tenant becomes operational and can ingest data.",
  [`${TenantStatus.ACTIVE}→${TenantStatus.SUSPENDED}`]:
    "Ingestion returns 403. All API access is blocked.",
  [`${TenantStatus.SUSPENDED}→${TenantStatus.ACTIVE}`]:
    "Tenant is re-enabled and can resume operations.",
  [`${TenantStatus.ONBOARDING}→${TenantStatus.DELETED}`]:
    "Soft delete. Data retained but API access blocked.",
  [`${TenantStatus.ACTIVE}→${TenantStatus.DELETED}`]:
    "Soft delete. Data retained but API access blocked.",
  [`${TenantStatus.SUSPENDED}→${TenantStatus.DELETED}`]:
    "Soft delete. Data retained but API access blocked.",
};

interface Props {
  tenant: TenantDocument;
  onUpdated: (updated: TenantDocument) => void;
}

export function StatusTransitionDialog({ tenant, onUpdated }: Props) {
  const [open, setOpen] = useState(false);
  const [target, setTarget] = useState<TenantStatus | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const validTargets = VALID_TRANSITIONS[tenant.status] ?? [];

  function openFor(status: TenantStatus) {
    setTarget(status);
    setOpen(true);
  }

  async function handleConfirm() {
    if (!target) return;
    setSubmitting(true);
    try {
      const updated = await updateTenantStatus(tenant.tenant_id, {
        status: target,
      });
      toast.success(`Status changed to ${target}`);
      onUpdated(updated);
      setOpen(false);
      setTarget(null);
    } catch {
      toast.error("Failed to update status");
    } finally {
      setSubmitting(false);
    }
  }

  if (validTargets.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No status transitions available.
      </p>
    );
  }

  return (
    <>
      <div className="flex flex-wrap gap-2">
        {validTargets.map((s) => (
          <Button
            key={s}
            variant={s === TenantStatus.DELETED ? "destructive" : "outline"}
            size="sm"
            onClick={() => openFor(s)}
          >
            Transition to {s}
          </Button>
        ))}
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Confirm Status Change</DialogTitle>
            <DialogDescription>
              {target &&
                transitionDescriptions[`${tenant.status}→${target}`]}
            </DialogDescription>
          </DialogHeader>

          <div className="flex items-center gap-3 py-4">
            <StatusBadge status={tenant.status} />
            <span className="text-muted-foreground">→</span>
            {target && <StatusBadge status={target} />}
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button
              variant={
                target === TenantStatus.DELETED ? "destructive" : "default"
              }
              onClick={handleConfirm}
              disabled={submitting}
            >
              {submitting ? "Updating..." : "Confirm"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
