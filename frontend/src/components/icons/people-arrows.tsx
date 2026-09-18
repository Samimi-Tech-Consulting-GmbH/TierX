import type { SVGProps } from "react";

export function PeopleArrows({ className, ...props }: SVGProps<SVGSVGElement>) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="currentColor"
      aria-hidden="true"
      focusable="false"
      className={className}
      {...props}
    >
      <circle cx="4.5" cy="3.75" r="2.5" />
      <rect x="2" y="7.75" width="5" height="14" rx="2.5" />
      <circle cx="19.5" cy="3.75" r="2.5" />
      <rect x="17" y="7.75" width="5" height="14" rx="2.5" />
      <path d="M8 13.25 10.2 11v1.3h3.6V11L16 13.25 13.8 15.5v-1.3h-3.6v1.3Z" />
    </svg>
  );
}
