import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { compareVersions, ReleaseStatusBadge } from "./release-status";
import type { LatestRelease } from "@/lib/types";

const release: LatestRelease = { enabled: true, status: "AVAILABLE", latest_version: "0.2.1",
  release_url: "https://github.com/Samimi-Tech-Consulting-GmbH/TierX/releases/tag/v0.2.1",
  checked_at: "2026-10-05T12:00:00Z" };
afterEach(cleanup);

describe("release status", () => {
  it("compares numeric semantic versions and optional prefixes", () => {
    expect(compareVersions("0.2.9", "v0.2.10")).toBe(-1);
    expect(compareVersions("v0.2.1", "0.2.1")).toBe(0);
    expect(compareVersions("1.0.0", "0.99.99")).toBe(1);
    expect(compareVersions("development", "0.2.1")).toBeNull();
    expect(compareVersions("0.2", "0.2.1")).toBeNull();
    expect(compareVersions("00.2.1", "0.2.1")).toBeNull();
  });
  it("links older installations to the available release", () => {
    render(<ReleaseStatusBadge installed="0.2.0" release={release} />);
    expect(screen.getByRole("link", { name: /Update available/ })).toHaveAttribute("href", release.release_url);
    expect(screen.getByText("Update available!")).toHaveClass("text-amber-400");
  });
  it("shows latest in green and newer installations as development", () => {
    const { rerender } = render(<ReleaseStatusBadge installed="v0.2.1" release={release} />);
    expect(screen.getByText("Latest version")).toHaveClass("text-green-400");
    rerender(<ReleaseStatusBadge installed="0.3.0" release={release} />);
    expect(screen.getByText("Development version")).toBeVisible();
  });
  it("handles unknown and disabled checks without claiming latest", () => {
    const { rerender } = render(<ReleaseStatusBadge installed="0.2.0" release={null} />);
    expect(screen.getByText("Update check unavailable")).toBeVisible();
    rerender(<ReleaseStatusBadge installed="development" release={release} />);
    expect(screen.getByText("Update check unavailable")).toBeVisible();
    rerender(<ReleaseStatusBadge installed="0.2.0" release={{ ...release, enabled: false, status: "DISABLED" }} />);
    expect(screen.queryByText(/Update/)).not.toBeInTheDocument();
  });
});
