import { Globe } from "lucide-react";
import { ReleaseStatus } from "./release-status";

export function ProductLinks({ version, sha }: { version: string; sha: string }) {
  const normalizedVersion = version.replace(/^v/, "");
  const repository = (process.env.NEXT_PUBLIC_TIERX_SOURCE_REPOSITORY?.trim() ||
    "https://github.com/Samimi-Tech-Consulting-GmbH/TierX").replace(/\/+$/, "");
  const releaseUrl = /^\d+\.\d+\.\d+$/.test(normalizedVersion)
    ? `${repository}/releases/tag/v${normalizedVersion}`
    : `${repository}/releases`;

  return (
    <div className="mt-3 px-3 pb-2 text-muted-foreground">
      <div className="mb-1 font-mono text-[10px]"><ReleaseStatus installed={version} /></div>
      <a
        href={releaseUrl}
        target="_blank"
        rel="noopener noreferrer"
        title="Release notes and corresponding source (AGPL-3.0-only)"
        className="font-mono text-[10px] hover:text-foreground focus-visible:outline focus-visible:outline-2"
      >
        {version === "development" ? version : `v${normalizedVersion}`}
      </a>
      <div className="font-mono text-[10px]">
        {sha === "development" ? sha : sha.slice(0, 7)}
      </div>
      <a
        href="https://tierx.tech"
        target="_blank"
        rel="noopener noreferrer"
        className="mt-3 flex items-center gap-2 rounded-md py-2 text-sm text-[#d4d4d4] hover:text-foreground focus-visible:outline focus-visible:outline-2"
      >
        <Globe className="size-4 shrink-0" aria-hidden="true" />
        TierX.Tech
      </a>
    </div>
  );
}
