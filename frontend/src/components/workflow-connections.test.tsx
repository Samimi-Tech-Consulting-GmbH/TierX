import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { afterEach, describe, it, expect, vi } from "vitest";
import { WorkflowConnections } from "./workflow-connections";
import type { FlowGraph } from "@/lib/workflows";
afterEach(cleanup);
describe("Keyboard connection editor", () => {
  it("connects a named outcome and prevents duplicates", () => {
    const graph: FlowGraph = {
      format_version: "2.0",
      nodes: [
        { id: "entry", type: "entry", config: {} },
        { id: "done", type: "complete", config: {} },
      ],
      edges: [],
    };
    const change = vi.fn();
    const view = render(
      <WorkflowConnections graph={graph} onChange={change} />,
    );
    fireEvent.change(screen.getByLabelText("Connection source"), {
      target: { value: "entry" },
    });
    fireEvent.change(screen.getByLabelText("Connection target"), {
      target: { value: "done" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Connect steps" }));
    expect(change.mock.calls[0][0].edges[0]).toMatchObject({
      source: "entry",
      target: "done",
      sourceHandle: "success",
    });
    view.rerender(
      <WorkflowConnections graph={change.mock.calls[0][0]} onChange={change} />,
    );
    expect(
      screen.getByRole("button", { name: "Connect steps" }),
    ).toBeDisabled();
  });
});
