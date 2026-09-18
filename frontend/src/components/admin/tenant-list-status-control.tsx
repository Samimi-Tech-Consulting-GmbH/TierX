"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ChevronDown } from "lucide-react";

import { updateTenantStatus, ApiError } from "@/lib/api";
import type { TenantDocument } from "@/lib/types";
import { TenantStatus, VALID_TRANSITIONS } from "@/lib/types";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

function needsConfirmation(target: TenantStatus): boolean {
  return (
    target === TenantStatus.SUSPENDED || target === TenantStatus.DELETED
  );
}

function confirmMessage(target: TenantStatus): string {
  if (target === TenantStatus.SUSPENDED) {
    return "Suspending this tenant will immediately block all alert ingestion and pipeline processing. Are you sure?";
  }
  if (target === TenantStatus.DELETED) {
    return "This will mark the tenant as deleted. Data will be retained but the tenant will be inaccessible. This cannot be undone via the dashboard.";
  }
  return "";
}

interface Props {
  tenant: TenantDocument;
  menuOpen: boolean;
  onMenuOpenChange: (open: boolean) => void;
  onTenantUpdated: (t: TenantDocument) => void;
}

export function TenantListStatusControl({
  tenant,
  menuOpen,
  onMenuOpenChange,
  onTenantUpdated,
}: Props) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const menuPortalRef = useRef<HTMLUListElement>(null);
  const [menuPos, setMenuPos] = useState<{
    top: number;
    left: number;
  } | null>(null);
  const [confirmTarget, setConfirmTarget] = useState<TenantStatus | null>(
    null,
  );
  const [errorDetail, setErrorDetail] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const options = VALID_TRANSITIONS[tenant.status] ?? [];

  useLayoutEffect(() => {
    if (!menuOpen) {
      setMenuPos(null);
      return;
    }
    function updatePosition() {
      const el = wrapRef.current;
      if (!el) return;
      const r = el.getBoundingClientRect();
      const gap = 8;
      const itemH = 40;
      const menuH = Math.min(
        12 + options.length * itemH,
        window.innerHeight - 24,
      );
      const spaceBelow = window.innerHeight - r.bottom - gap;
      let top: number;
      if (spaceBelow >= menuH || r.top < menuH + gap) {
        top = r.bottom + gap;
      } else {
        top = Math.max(gap, r.top - gap - menuH);
      }
      const menuMinW = 176;
      const left = Math.min(
        Math.max(8, r.left),
        Math.max(8, window.innerWidth - menuMinW - 8),
      );
      setMenuPos({ top, left });
    }
    updatePosition();
    window.addEventListener("scroll", updatePosition, true);
    window.addEventListener("resize", updatePosition);
    return () => {
      window.removeEventListener("scroll", updatePosition, true);
      window.removeEventListener("resize", updatePosition);
    };
  }, [menuOpen, options.length, tenant.status]);

  useEffect(() => {
    if (!menuOpen) return;
    function close(e: MouseEvent) {
      const t = e.target as Node;
      if (wrapRef.current?.contains(t)) return;
      if (menuPortalRef.current?.contains(t)) return;
      onMenuOpenChange(false);
    }
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [menuOpen, onMenuOpenChange]);

  async function applyTransition(next: TenantStatus) {
    setPending(true);
    try {
      const updated = await updateTenantStatus(tenant.tenant_id, {
        status: next,
      });
      onTenantUpdated(updated);
      setConfirmTarget(null);
      onMenuOpenChange(false);
    } catch (e) {
      const msg =
        e instanceof ApiError ? e.detail : "Status update failed";
      setErrorDetail(msg);
      setConfirmTarget(null);
      onMenuOpenChange(false);
    } finally {
      setPending(false);
    }
  }

  function choose(next: TenantStatus) {
    if (needsConfirmation(next)) {
      setConfirmTarget(next);
      onMenuOpenChange(false);
      return;
    }
    void applyTransition(next);
  }

  return (
    <>
      <div
        ref={wrapRef}
        className="relative inline-flex"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          type="button"
          className={cn(
            "inline-flex items-center gap-1 rounded-md outline-none ring-offset-background focus-visible:ring-2 focus-visible:ring-ring",
          )}
          onClick={() => onMenuOpenChange(!menuOpen)}
          aria-expanded={menuOpen}
          aria-haspopup="listbox"
        >
          <StatusBadge status={tenant.status} />
          <ChevronDown className="h-4 w-4 text-muted-foreground" />
        </button>
        {menuOpen &&
          options.length > 0 &&
          menuPos &&
          typeof document !== "undefined" &&
          createPortal(
            <ul
              ref={menuPortalRef}
              className="fixed z-[300] min-w-[11rem] max-h-[min(22rem,calc(100vh-1rem))] overflow-y-auto rounded-md border bg-popover py-1 text-sm shadow-lg outline-none"
              style={{ top: menuPos.top, left: menuPos.left }}
              role="listbox"
            >
              {options.map((s) => (
                <li key={s}>
                  <button
                    type="button"
                    className="w-full px-3 py-2 text-left hover:bg-muted"
                    onClick={() => choose(s)}
                  >
                    Set to {s}
                  </button>
                </li>
              ))}
            </ul>,
            document.body,
          )}
      </div>

      <Dialog
        open={confirmTarget != null}
        onOpenChange={(o) => !o && setConfirmTarget(null)}
      >
        <DialogContent showCloseButton={false}>
          <DialogHeader>
            <DialogTitle>Confirm status change</DialogTitle>
            <DialogDescription>
              {confirmTarget ? confirmMessage(confirmTarget) : null}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setConfirmTarget(null)}
              disabled={pending}
            >
              Cancel
            </Button>
            <Button
              variant={
                confirmTarget === TenantStatus.DELETED
                  ? "destructive"
                  : "default"
              }
              disabled={pending || !confirmTarget}
              onClick={() =>
                confirmTarget && void applyTransition(confirmTarget)
              }
            >
              {pending ? "Updating…" : "Confirm"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={errorDetail != null} onOpenChange={() => setErrorDetail(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Could not update status</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-destructive">{errorDetail}</p>
          <DialogFooter>
            <Button onClick={() => setErrorDetail(null)}>Close</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
