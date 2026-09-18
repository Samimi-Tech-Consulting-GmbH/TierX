"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ChevronsUpDown, Settings } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

export interface SettingsMenuItem {
  href: string;
  label: string;
  icon: LucideIcon;
}

export function SettingsMenu({
  items,
  onNavigate,
}: {
  items: SettingsMenuItem[];
  onNavigate?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: MouseEvent) {
      if (rootRef.current?.contains(event.target as Node)) return;
      setOpen(false);
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  if (items.length === 0) return null;

  if (items.length === 1) {
    const [item] = items;
    return (
      <Link
        href={item.href}
        onClick={onNavigate}
        className="flex w-full items-center gap-3 rounded-md px-3 py-2.5 text-sm text-[#d4d4d4] transition-colors hover:bg-white/5 hover:text-foreground"
      >
        <item.icon className="size-4 shrink-0" />
        <span className="truncate">{item.label}</span>
      </Link>
    );
  }

  return (
    <div className="relative" ref={rootRef}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="menu"
        className={cn(
          "flex w-full items-center gap-3 rounded-md px-3 py-2.5 text-sm transition-colors",
          open
            ? "bg-white/10 text-foreground"
            : "text-[#d4d4d4] hover:bg-white/5 hover:text-foreground",
        )}
      >
        <Settings className="size-4 shrink-0" />
        <span className="min-w-0 flex-1 truncate text-left">Settings</span>
        <ChevronsUpDown className="size-4 shrink-0 text-muted-foreground" />
      </button>

      {open && (
        <div
          role="menu"
          className="absolute bottom-full left-0 z-30 mb-2 w-full overflow-hidden rounded-lg border border-[#404040] bg-card p-1 shadow-lg"
        >
          {items.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              role="menuitem"
              onClick={() => {
                setOpen(false);
                onNavigate?.();
              }}
              className="flex items-center gap-3 rounded-md px-3 py-2 text-sm text-[#d4d4d4] transition-colors hover:bg-white/5 hover:text-foreground"
            >
              <item.icon className="size-4 shrink-0" />
              <span className="truncate">{item.label}</span>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
