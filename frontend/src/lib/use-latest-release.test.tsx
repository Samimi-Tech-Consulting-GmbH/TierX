import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { getLatestRelease } from "./api";
import { LatestReleaseProvider, useLatestRelease } from "./use-latest-release";
vi.mock("./api", () => ({ getLatestRelease: vi.fn() }));
function Consumer({ name }: { name: string }) {
  const { release } = useLatestRelease();
  return <span>{name}:{release?.latest_version ?? "unknown"}</span>;
}
afterEach(() => vi.useRealTimers());
describe("LatestReleaseProvider", () => {
  it("shares one load across both sidebars and refreshes hourly", async () => {
    vi.mocked(getLatestRelease).mockResolvedValue({ enabled: true, status: "AVAILABLE",
      latest_version: "0.2.1", release_url: null, checked_at: null });
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    const { unmount } = render(<LatestReleaseProvider>
      <Consumer name="desktop" /><Consumer name="mobile" />
    </LatestReleaseProvider>);
    await waitFor(() => expect(screen.getByText("desktop:0.2.1")).toBeVisible());
    expect(screen.getByText("mobile:0.2.1")).toBeVisible();
    expect(getLatestRelease).toHaveBeenCalledTimes(1);
    await act(async () => { vi.advanceTimersByTime(3_600_000); });
    expect(getLatestRelease).toHaveBeenCalledTimes(2);
    unmount();
    vi.advanceTimersByTime(3_600_000);
    expect(getLatestRelease).toHaveBeenCalledTimes(2);
  });
});
