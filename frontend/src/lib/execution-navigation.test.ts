import { describe, expect, it, vi } from "vitest";
import { executionDebugHref, executionDebugHome } from "./execution-navigation";
import OldAdminRun from "@/app/dashboard/admin/workflows/runs/[tenantId]/[runId]/page";
import OldTenantRun from "@/app/dashboard/[tenantId]/workflows/runs/[runId]/page";
vi.mock("next/navigation", () => ({
  redirect: (path: string) => {
    throw new Error(path);
  },
}));
describe("Execution inspection belongs to Debug", () => {
  it("uses scoped Debug routes and encodes identifiers", () => {
    expect(executionDebugHref("tenant/a", "run?b", true)).toBe(
      "/dashboard/admin/debug/runs/tenant%2Fa/run%3Fb",
    );
    expect(executionDebugHref("one", "run")).toBe(
      "/dashboard/one/debug/runs/run",
    );
    expect(executionDebugHome("one", true)).toBe("/dashboard/admin/debug");
    expect(executionDebugHome("one")).toBe("/dashboard/one/debug");
  });
  it.each([
    [OldAdminRun, "/dashboard/admin/debug/runs/one/run"],
    [OldTenantRun, "/dashboard/one/debug/runs/run"],
  ] as const)(
    "preserves old bookmarks through redirects",
    async (Page, destination) => {
      await expect(
        Page({ params: Promise.resolve({ tenantId: "one", runId: "run" }) }),
      ).rejects.toThrow(destination);
    },
  );
});
