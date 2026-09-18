"use client";

import { useState } from "react";
import { Copy } from "lucide-react";
import { toast } from "sonner";

import { createTenant, ApiError } from "@/lib/api";
import {
  ALLOWED_TENANT_SOURCE_SYSTEMS,
  type TenantDocument,
} from "@/lib/types";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const SLUG_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (tenant: TenantDocument) => void;
}

export function CreateTenantModal({ open, onOpenChange, onCreated }: Props) {
  const [step, setStep] = useState<"form" | "success">("form");
  const [name, setName] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [contactEmail, setContactEmail] = useState("");
  const [sources, setSources] = useState<Set<string>>(new Set());
  const [nameError, setNameError] = useState("");
  const [slugHint, setSlugHint] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [created, setCreated] = useState<TenantDocument | null>(null);

  function reset() {
    setStep("form");
    setName("");
    setDisplayName("");
    setContactEmail("");
    setSources(new Set());
    setNameError("");
    setSlugHint("");
    setCreated(null);
  }

  function handleOpenChange(next: boolean) {
    if (!next) reset();
    onOpenChange(next);
  }

  function validateSlug(raw: string): string | null {
    const v = raw.trim().toLowerCase();
    if (!v) return "Name is required";
    if (v.length > 40) return "Max 40 characters";
    if (!SLUG_PATTERN.test(v)) {
      return "Use lowercase letters, numbers, and hyphens only";
    }
    return null;
  }

  function toggleSource(s: string) {
    setSources((prev) => {
      const next = new Set(prev);
      if (next.has(s)) next.delete(s);
      else next.add(s);
      return next;
    });
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setNameError("");
    const slugErr = validateSlug(name);
    if (slugErr) {
      setNameError(slugErr);
      return;
    }
    if (!displayName.trim()) {
      toast.error("Display name is required");
      return;
    }

    setSubmitting(true);
    try {
      const tenant = await createTenant({
        name: name.trim().toLowerCase(),
        display_name: displayName.trim(),
        contact_email: contactEmail.trim() || undefined,
        allowed_source_systems: Array.from(sources),
      });
      setCreated(tenant);
      setStep("success");
      onCreated(tenant);
      toast.success("Tenant created");
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setNameError("This tenant name is already taken");
      } else {
        toast.error("Failed to create tenant");
      }
    } finally {
      setSubmitting(false);
    }
  }

  function copy(text: string) {
    navigator.clipboard.writeText(text);
    toast.info("Copied");
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-md">
        {step === "form" ? (
          <>
            <DialogHeader>
              <DialogTitle>New tenant</DialogTitle>
              <DialogDescription>
                Slug, display name, and optional contact details. Source systems
                are limited to the integrations enabled for this dashboard.
              </DialogDescription>
            </DialogHeader>
            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="ct-name">Slug name</Label>
                <Input
                  id="ct-name"
                  value={name}
                  onChange={(e) => {
                    const v = e.target.value
                      .toLowerCase()
                      .replace(/[^a-z0-9-]/g, "")
                      .slice(0, 40);
                    setName(v);
                    setNameError("");
                    const err = validateSlug(v);
                    setSlugHint(err && v ? err : "");
                  }}
                  placeholder="example-corp"
                  aria-invalid={Boolean(nameError)}
                />
                {nameError ? (
                  <p className="text-sm text-destructive">{nameError}</p>
                ) : slugHint ? (
                  <p className="text-sm text-muted-foreground">{slugHint}</p>
                ) : (
                  <p className="text-xs text-muted-foreground">
                    Lowercase, alphanumeric, hyphens only. Max 40 characters.
                  </p>
                )}
              </div>
              <div className="space-y-2">
                <Label htmlFor="ct-display">Display name</Label>
                <Input
                  id="ct-display"
                  value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)}
                  placeholder="Example Corporation"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="ct-email">Contact email</Label>
                <Input
                  id="ct-email"
                  type="email"
                  value={contactEmail}
                  onChange={(e) => setContactEmail(e.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label>Allowed source systems</Label>
                <div className="space-y-2 rounded-md border p-3">
                  {ALLOWED_TENANT_SOURCE_SYSTEMS.map((s) => (
                    <label
                      key={s}
                      className="flex cursor-pointer items-center gap-2 text-sm"
                    >
                      <input
                        type="checkbox"
                        checked={sources.has(s)}
                        onChange={() => toggleSource(s)}
                        className="rounded border-input"
                      />
                      {s}
                    </label>
                  ))}
                </div>
              </div>
              <DialogFooter className="gap-2 sm:gap-0">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => handleOpenChange(false)}
                >
                  Cancel
                </Button>
                <Button type="submit" disabled={submitting}>
                  {submitting ? "Creating…" : "Create"}
                </Button>
              </DialogFooter>
            </form>
          </>
        ) : created ? (
          <>
            <DialogHeader>
              <DialogTitle>Tenant created</DialogTitle>
              <DialogDescription>
                Use these identifiers when configuring integrations. They are
                also visible on the tenant detail page.
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-3">
              <div>
                <Label className="text-muted-foreground">tenant_id</Label>
                <div className="mt-1 flex items-center gap-2 rounded-md border bg-muted/40 px-2 py-1.5 font-mono text-xs">
                  <span className="min-w-0 flex-1 truncate">
                    {created.tenant_id}
                  </span>
                  <button
                    type="button"
                    className="text-muted-foreground hover:text-foreground"
                    onClick={() => copy(created.tenant_id)}
                  >
                    <Copy className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
              <div>
                <Label className="text-muted-foreground">db_name</Label>
                <div className="mt-1 flex items-center gap-2 rounded-md border bg-muted/40 px-2 py-1.5 font-mono text-xs">
                  <span className="min-w-0 flex-1 truncate">
                    {created.db_name}
                  </span>
                  <button
                    type="button"
                    className="text-muted-foreground hover:text-foreground"
                    onClick={() => copy(created.db_name)}
                  >
                    <Copy className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
            </div>
            <DialogFooter>
              <Button onClick={() => handleOpenChange(false)}>Done</Button>
            </DialogFooter>
          </>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
