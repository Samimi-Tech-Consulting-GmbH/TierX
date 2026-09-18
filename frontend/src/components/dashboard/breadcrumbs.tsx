"use client";

import Link from "next/link";
import { House } from "lucide-react";

import { cn } from "@/lib/utils";

export interface Crumb {
  label: string;
  href?: string;
}

export function Breadcrumbs({
  items,
  className,
}: {
  items: Crumb[];
  className?: string;
}) {
  return (
    <nav
      aria-label="Breadcrumb"
      className={cn("flex items-center gap-2 text-sm", className)}
    >
      {items.map((item, index) => {
        const last = index === items.length - 1;
        return (
          <span
            key={`${item.label}-${index}`}
            className="flex items-center gap-2"
          >
            {index > 0 && (
              <span aria-hidden="true" className="text-[#525252]">
                /
              </span>
            )}
            {item.href && !last ? (
              <Link
                href={item.href}
                className="flex items-center gap-1.5 text-[#a3a3a3] transition-colors hover:text-foreground"
              >
                {index === 0 && <House className="size-4" />}
                {item.label}
              </Link>
            ) : (
              <span
                aria-current={last ? "page" : undefined}
                className="flex items-center gap-1.5 font-medium text-primary"
              >
                {index === 0 && <House className="size-4" />}
                {item.label}
              </span>
            )}
          </span>
        );
      })}
    </nav>
  );
}
