import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { getPlatformHealth } from "./api";
import { PlatformHealthProvider, usePlatformHealth } from "./use-platform-health";

vi.mock("./api", () => ({ getPlatformHealth: vi.fn() }));

function Consumer({ name }: { name: string }) {
  const { health } = usePlatformHealth();
  return <span>{name}:{health?.status ?? "loading"}</span>;
}

describe("PlatformHealthProvider", () => {
  it("shares one poll between multiple consumers", async () => {
    vi.mocked(getPlatformHealth).mockResolvedValue({
      status: "HEALTHY",
      components: {},
      llm_analysis_enabled: true,
      release_version: "v0.1.0",
      release_sha: "abcdef0",
    });

    render(
      <PlatformHealthProvider>
        <Consumer name="header" />
        <Consumer name="card" />
      </PlatformHealthProvider>,
    );

    await waitFor(() => expect(screen.getByText("header:HEALTHY")).toBeVisible());
    expect(screen.getByText("card:HEALTHY")).toBeVisible();
    expect(getPlatformHealth).toHaveBeenCalledTimes(1);
  });
});
