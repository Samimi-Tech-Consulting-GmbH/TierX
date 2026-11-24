import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  callsFor,
  executionMap,
  loadExecution,
  stepId,
} from "./workflow-execution";
import { workflowRequest } from "./workflows";
import { executionFixture } from "@/test/execution-fixture";
vi.mock("./workflows", async (original) => ({
  ...(await original<typeof import("./workflows")>()),
  workflowRequest: vi.fn(),
}));

describe("Complete execution loading and layout", () => {
  beforeEach(() => vi.mocked(workflowRequest).mockReset());
  it("loads all nested runs from pinned read-only endpoints and resolves a child link to the root", async () => {
    const runs = executionFixture();
    vi.mocked(workflowRequest)
      .mockResolvedValueOnce(runs[2])
      .mockResolvedValueOnce(runs[0])
      .mockResolvedValueOnce(runs[1]);
    const result = await loadExecution(
      "one",
      "s",
      new AbortController().signal,
    );
    expect(result.root.run_id).toBe("r");
    expect(result.runs.map((run) => run.run_id)).toEqual(["r", "p", "s"]);
    expect(result.issues).toEqual([]);
    expect(workflowRequest).toHaveBeenCalledTimes(3);
    expect(
      vi.mocked(workflowRequest).mock.calls.map((call) => call[0]),
    ).toEqual([
      "/tenants/one/runs/s",
      "/tenants/one/runs/r",
      "/tenants/one/runs/p",
    ]);
    expect(
      vi.mocked(workflowRequest).mock.calls.every((call) => call[1] === "GET"),
    ).toBe(true);
  });
  it("reports inaccessible or cross-alert subflows rather than hiding the partial trace", async () => {
    const [root, child] = executionFixture();
    vi.mocked(workflowRequest)
      .mockResolvedValueOnce(root)
      .mockResolvedValueOnce({ ...child, alert_id: "other" });
    const result = await loadExecution(
      "one",
      "r",
      new AbortController().signal,
    );
    expect(result.runs).toEqual([root]);
    expect(result.issues[0]).toContain("incomplete");
  });
  it("terminates cyclic references", async () => {
    const [root] = executionFixture();
    root.children = [{ run_id: "r", state: "RUNNING" }];
    vi.mocked(workflowRequest).mockResolvedValue(root);
    const result = await loadExecution(
      "one",
      "r",
      new AbortController().signal,
    );
    expect(result.issues[0]).toContain("cyclic");
    expect(workflowRequest).toHaveBeenCalledTimes(1);
  });
  it("nests every child under its actual caller, including model/tool call subnodes", () => {
    const runs = executionFixture(),
      result = executionMap({ root: runs[0], runs, issues: [] });
    expect(result.issues).toEqual([]);
    expect(result.nodes.find((node) => node.id === "run:p")?.parentId).toBe(
      stepId("r", "route"),
    );
    expect(result.nodes.find((node) => node.id === "run:s")?.parentId).toBe(
      stepId("p", "agent"),
    );
    expect(
      result.nodes.filter((node) => node.data.kind === "call"),
    ).toHaveLength(2);
    expect(new Set(result.nodes.map((node) => node.id)).size).toBe(
      result.nodes.length,
    );
    expect(
      result.nodes.find((node) => node.id === stepId("r", "skipped"))?.data
        .state,
    ).toBe("NOT_REACHED");
    expect(
      result.edges.find((edge) => edge.id === "run:r:error")?.style
        ?.strokeDasharray,
    ).toBe("5 4");
  });
  it("collapse hides the whole descendant tree without mislabeling grandchildren as orphans", () => {
    const runs = executionFixture(),
      result = executionMap(
        { root: runs[0], runs, issues: [] },
        new Set([stepId("r", "route")]),
      );
    expect(
      result.nodes.some(
        (node) => node.data.run.run_id === "p" || node.data.run.run_id === "s",
      ),
    ).toBe(false);
    expect(result.issues).toEqual([]);
  });
  it("keeps missing-caller traces visible with an explicit warning instead of guessing a parent", () => {
    const runs = executionFixture();
    runs[1].parent_job_id = "missing";
    const result = executionMap({ root: runs[0], runs, issues: [] });
    expect(
      result.nodes.find((node) => node.id === "run:p")?.parentId,
    ).toBeUndefined();
    expect(result.nodes.some((node) => node.id === "run:s")).toBe(true);
    expect(result.issues[0]).toContain("no visible caller");
  });
  it("only associates calls using their recorded job id", () => {
    const runs = executionFixture();
    expect(callsFor(runs[2], runs[2].nodes?.[1])).toHaveLength(2);
    expect(callsFor(runs[2], runs[2].nodes?.[0])).toEqual([]);
  });
  it("keeps unattributed call records visible without inventing a caller", () => {
    const runs = executionFixture();
    runs[2].tool_calls!.push({ call_id: "legacy-call", state: "FAILED" });
    const result = executionMap({ root: runs[0], runs, issues: [] });
    expect(
      result.nodes.find((node) => node.id === "unlinked:s:tool:legacy-call")
        ?.parentId,
    ).toBeUndefined();
    expect(result.issues.join(" ")).toContain("no recorded caller");
  });
  it("bounds concurrent reads and warns instead of silently truncating large traces", async () => {
    const [root, child] = executionFixture();
    const children = Array.from({ length: 105 }, (_, i) => ({
      ...child,
      run_id: `c${i}`,
      children: [],
    }));
    root.children = children.map((child) => ({
      run_id: child.run_id,
      state: child.state,
    }));
    const byPath = new Map(
      [root, ...children].map((run) => [
        `/tenants/one/runs/${run.run_id}`,
        run,
      ]),
    );
    let active = 0,
      maximum = 0;
    vi.mocked(workflowRequest).mockImplementation(async (path) => {
      maximum = Math.max(maximum, ++active);
      await Promise.resolve();
      active--;
      return byPath.get(path)!;
    });
    const result = await loadExecution(
      "one",
      "r",
      new AbortController().signal,
    );
    expect(result.runs).toHaveLength(100);
    expect(maximum).toBeLessThanOrEqual(6);
    expect(result.issues.join(" ")).toContain("display limit");
  });
  it("places parallel branches in the same column and joins after both, not a fake serial chain", () => {
    const [root] = executionFixture();
    root.children = [];
    root.graph = {
      format_version: "2.0",
      nodes: ["entry", "fork", "left", "right", "join", "done"].map((id) => ({
        id,
        type: id === "fork" ? "fork" : "entry",
        config: id === "fork" ? { branches: ["left", "right"] } : {},
      })),
      edges: [
        ["entry", "fork"],
        ["fork", "left", "left"],
        ["fork", "right", "right"],
        ["left", "join"],
        ["right", "join"],
        ["join", "done"],
        ["fork", "join", "error"],
      ].map(([source, target, sourceHandle], i) => ({
        id: `e${i}`,
        source,
        target,
        sourceHandle,
      })),
    };
    root.nodes = root.graph.nodes.map((node) => ({
      job_id: node.id,
      node_id: node.id,
      state: "SUCCEEDED",
      port: "success",
    }));
    const result = executionMap({ root, runs: [root], issues: [] });
    const left = result.nodes.find((node) => node.id === stepId("r", "left"))!,
      right = result.nodes.find((node) => node.id === stepId("r", "right"))!,
      join = result.nodes.find((node) => node.id === stepId("r", "join"))!;
    expect(left.position.x).toBe(right.position.x);
    expect(left.position.y).not.toBe(right.position.y);
    expect(join.position.x).toBeGreaterThan(left.position.x);
    expect(
      result.edges.find((edge) => edge.id === "run:r:e6")?.style
        ?.strokeDasharray,
    ).toBe("5 4");
  });
});
