"use client";
import type { LatestRelease } from "@/lib/types";
import { useLatestRelease } from "@/lib/use-latest-release";

export function compareVersions(installed: string, latest: string): number | null {
  const parse = (value: string) => {
    const match = /^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/.exec(value);
    return match ? match.slice(1).map(BigInt) : null;
  };
  const a = parse(installed), b = parse(latest);
  if (!a || !b) return null;
  for (let index = 0; index < 3; index++) {
    if (a[index] !== b[index]) return a[index] < b[index] ? -1 : 1;
  }
  return 0;
}

export function ReleaseStatusBadge({ installed, release, loading = false }: {
  installed: string; release: LatestRelease | null; loading?: boolean;
}) {
  if (loading || release?.enabled === false) return null;
  const comparison = release?.status === "AVAILABLE" && release.latest_version
    ? compareVersions(installed, release.latest_version) : null;
  if (comparison === null) return <span className="text-muted-foreground">Update check unavailable</span>;
  if (comparison > 0) return <span className="text-muted-foreground">Development version</span>;
  if (comparison === 0) return <span className="text-green-400">Latest version</span>;
  // Only link to this project's GitHub releases, even if API data is malformed.
  const expected = /^https:\/\/github\.com\/Samimi-Tech-Consulting-GmbH\/TierX\/releases\/tag\/v?\d+\.\d+\.\d+$/;
  return release?.release_url && expected.test(release.release_url)
    ? <a href={release.release_url} target="_blank" rel="noopener noreferrer"
        className="text-amber-400 hover:underline focus-visible:outline focus-visible:outline-2"
        aria-label={`Update available! Latest release v${release.latest_version}`}>
        Update available!
      </a>
    : <span className="text-amber-400">Update available!</span>;
}

export function ReleaseStatus({ installed }: { installed: string }) {
  const { release, loading } = useLatestRelease();
  return <ReleaseStatusBadge installed={installed} release={release} loading={loading} />;
}
