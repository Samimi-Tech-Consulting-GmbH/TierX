import { Globe, LogOut } from "lucide-react";
import { ReleaseStatus } from "./release-status";

export function ProductLinks({
  version,
  sha,
  onLogout,
}: {
  version: string;
  sha: string;
  onLogout?: () => void;
}) {
  const normalizedVersion = version.replace(/^v/, "");
  const repository = (
    process.env.NEXT_PUBLIC_TIERX_SOURCE_REPOSITORY?.trim() ||
    "https://github.com/Samimi-Tech-Consulting-GmbH/TierX"
  ).replace(/\/+$/, "");
  const releaseUrl = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/.test(
    normalizedVersion,
  )
    ? `${repository}/releases/tag/v${normalizedVersion}`
    : `${repository}/releases`;

  return (
    <div className="mt-1 px-3 text-muted-foreground">
      <div className="flex min-w-0 items-center gap-1 whitespace-nowrap py-1 font-mono text-[11px]">
        <a
          href={releaseUrl}
          target="_blank"
          rel="noopener noreferrer"
          title={`Release notes and corresponding source (AGPL-3.0-only) · SHA ${sha}`}
          className="shrink-0 rounded-sm hover:text-foreground focus-visible:outline focus-visible:outline-2"
        >
          {version === "development" ? version : `v${normalizedVersion}`}
        </a>
        <span className="min-w-0 truncate">
          <ReleaseStatus installed={version} />
        </span>
      </div>
      <nav
        aria-label="Product and session links"
        className="flex items-center justify-between pt-1"
      >
        <button
          type="button"
          onClick={onLogout}
          aria-label="Logout"
          title="Logout"
          className="flex size-11 items-center justify-center rounded-md text-[#f87171] hover:bg-white/5 focus-visible:outline focus-visible:outline-2"
        >
          <LogOut className="size-[18px]" aria-hidden="true" />
        </button>
        <a
          href="https://tierx.tech"
          target="_blank"
          rel="noopener noreferrer"
          aria-label="TierX.Tech"
          title="TierX.Tech"
          className="flex size-11 items-center justify-center rounded-md text-[#d4d4d4] hover:bg-white/5 hover:text-foreground focus-visible:outline focus-visible:outline-2"
        >
          <Globe className="size-4 shrink-0" aria-hidden="true" />
        </a>
        <a
          href={repository}
          target="_blank"
          rel="noopener noreferrer"
          aria-label="GitHub repository (AGPL source code)"
          title="GitHub repository (AGPL source code)"
          className="flex size-11 items-center justify-center rounded-md text-[#d4d4d4] hover:bg-white/5 hover:text-foreground focus-visible:outline focus-visible:outline-2"
        >
          {/* GitHub's official mark: https://github.githubassets.com/favicons/favicon.svg */}
          <svg
            viewBox="0 0 32 32"
            className="size-[18px]"
            aria-hidden="true"
            focusable="false"
            fill="currentColor"
          >
            <path
              fillRule="evenodd"
              clipRule="evenodd"
              d="M16 0C7.16 0 0 7.16 0 16C0 23.08 4.58 29.06 10.94 31.18C11.74 31.32 12.04 30.84 12.04 30.42C12.04 30.04 12.02 28.78 12.02 27.44C8 28.18 6.96 26.46 6.64 25.56C6.46 25.1 5.68 23.68 5 23.3C4.44 23 3.64 22.26 4.98 22.24C6.24 22.22 7.14 23.4 7.44 23.88C8.88 26.3 11.18 25.62 12.1 25.2C12.24 24.16 12.66 23.46 13.12 23.06C9.56 22.66 5.84 21.28 5.84 15.16C5.84 13.42 6.46 11.98 7.48 10.86C7.32 10.46 6.76 8.82 7.64 6.62C7.64 6.62 8.98 6.2 12.04 8.26C13.32 7.9 14.68 7.72 16.04 7.72C17.4 7.72 18.76 7.9 20.04 8.26C23.1 6.18 24.44 6.62 24.44 6.62C25.32 8.82 24.76 10.46 24.6 10.86C25.62 11.98 26.24 13.4 26.24 15.16C26.24 21.3 22.5 22.66 18.94 23.06C19.52 23.56 20.02 24.52 20.02 26.02C20.02 28.16 20 29.88 20 30.42C20 30.84 20.3 31.34 21.1 31.18C27.42 29.06 32 23.06 32 16C32 7.16 24.84 0 16 0V0Z"
            />
          </svg>
        </a>
      </nav>
    </div>
  );
}
