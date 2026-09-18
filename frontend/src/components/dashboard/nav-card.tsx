import Link from "next/link";
import { ArrowRight } from "lucide-react";
import type { LucideIcon } from "lucide-react";

export interface NavCardItem {
  href: string;
  title: string;
  description: string;
  icon: LucideIcon;
}

export function NavCard({ href, title, description, icon: Icon }: NavCardItem) {
  return (
    <Link
      href={href}
      className="group flex flex-col items-center rounded-lg bg-card px-6 py-8 text-center transition-colors hover:bg-card/80"
    >
      <span className="flex size-20 items-center justify-center rounded-full bg-primary">
        <Icon className="size-8 text-primary-foreground" />
      </span>
      <h2 className="mt-6 text-lg font-bold">{title}</h2>
      <p className="mt-3 text-sm text-muted-foreground">{description}</p>
      <span className="mt-auto flex items-center gap-2 pt-6 text-sm font-bold text-primary">
        Open now
        <ArrowRight className="size-3.5 transition-transform group-hover:translate-x-0.5" />
      </span>
    </Link>
  );
}
