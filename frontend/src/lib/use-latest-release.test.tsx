import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { getLatestRelease } from "./api";
import { LatestReleaseProvider, useLatestRelease } from "./use-latest-release";
vi.mock("./api", () => ({ getLatestRelease: vi.fn() }));
function Consumer({ name }: { name: string }) {
  const { release } = useLatestRelease();
  return <span>{name}:{release?.latest_version ?? "unknown"}</span>;
}
afterEach(() => { vi.useRealTimers(); vi.clearAllMocks(); });
describe("LatestReleaseProvider", () => {
  it("shares one load across both sidebars and refreshes hourly", async () => {
    vi.mocked(getLatestRelease).mockResolvedValue({ enabled: true, status: "AVAILABLE",
      latest_version: "0.2.1", release_url: null, checked_at: null });
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    const { unmount } = render(<LatestReleaseProvider>
      <Consumer name="desktop" /><Consumer name="mobile" />
    </LatestReleaseProvider>);
    await act(async () => {});
    expect(screen.getByText("desktop:0.2.1")).toBeVisible();
    expect(screen.getByText("mobile:0.2.1")).toBeVisible();
    expect(getLatestRelease).toHaveBeenCalledTimes(1);
    await act(async () => { vi.advanceTimersByTime(3_600_000); });
    expect(getLatestRelease).toHaveBeenCalledTimes(2);
    unmount();
    vi.advanceTimersByTime(3_600_000);
    expect(getLatestRelease).toHaveBeenCalledTimes(2);
  });
  it("waits a full hour after a slow request settles and never overlaps requests", async () => {
    let resolve!: (value: Awaited<ReturnType<typeof getLatestRelease>>) => void;
    vi.mocked(getLatestRelease).mockReturnValue(new Promise(done => { resolve = done; }));
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    const { unmount } = render(<LatestReleaseProvider><Consumer name="desktop" /></LatestReleaseProvider>);
    await act(async () => { vi.advanceTimersByTime(10_000); });
    expect(getLatestRelease).toHaveBeenCalledTimes(1);
    await act(async () => { resolve({ enabled: true, status: "AVAILABLE", latest_version: "0.2.3", release_url: null, checked_at: null }); });
    await act(async () => { vi.advanceTimersByTime(3_599_999); });
    expect(getLatestRelease).toHaveBeenCalledTimes(1);
    await act(async () => { vi.advanceTimersByTime(1); });
    expect(getLatestRelease).toHaveBeenCalledTimes(2);
    unmount();
  });
  it("does not schedule polling when unmounted during the initial request", async () => {
    let resolve!: (value: Awaited<ReturnType<typeof getLatestRelease>>) => void;
    vi.mocked(getLatestRelease).mockReturnValue(new Promise(done => { resolve = done; }));
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    const { unmount } = render(<LatestReleaseProvider><Consumer name="desktop" /></LatestReleaseProvider>);
    unmount();
    await act(async () => { resolve({ enabled: true, status: "UNAVAILABLE", latest_version: null, release_url: null, checked_at: null }); });
    await act(async () => { vi.advanceTimersByTime(7_200_000); });
    expect(getLatestRelease).toHaveBeenCalledTimes(1);
  });
});
