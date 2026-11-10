"use client";
import { useState } from "react";
import { outputPorts, type FlowGraph } from "@/lib/workflows";
import { studioButton } from "./workflow-library";

/** Keyboard-operable alternative to dragging a wire between canvas handles. */
export function WorkflowConnections({
  graph,
  onChange,
}: {
  graph: FlowGraph;
  onChange: (graph: FlowGraph) => void;
}) {
  const [source, setSource] = useState(""),
    [target, setTarget] = useState(""),
    [port, setPort] = useState("success"),
    [message, setMessage] = useState("");
  const from = graph.nodes.find((n) => n.id === source),
    to = graph.nodes.find((n) => n.id === target);
  const ports = from
    ? [...outputPorts(from), ...(from.type === "tool_call" ? ["tool"] : [])]
    : [];
  const duplicate = graph.edges.some(
    (e) =>
      e.source === source &&
      e.target === target &&
      (e.sourceHandle || "success") === port,
  );
  const field = "h-10 w-full rounded-lg border bg-background px-2 text-sm";
  return (
    <details className="mt-4 rounded-lg border p-4">
      <summary className="cursor-pointer text-sm font-medium">
        Manage connections without dragging
      </summary>
      <p className="my-3 text-xs text-muted-foreground">
        Choose a source, outcome, and next step. All canvas actions are also
        available here with a keyboard.
      </p>
      <div className="grid items-end gap-3 md:grid-cols-4">
        <label className="text-xs">
          From step
          <select
            aria-label="Connection source"
            className={field}
            value={source}
            onChange={(e) => {
              setSource(e.target.value);
              setPort("success");
            }}
          >
            <option value="">Select source</option>
            {graph.nodes.map((n) => (
              <option key={n.id} value={n.id}>
                {n.label || n.id}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs">
          Outcome
          <select
            aria-label="Connection outcome"
            className={field}
            value={port}
            onChange={(e) => setPort(e.target.value)}
          >
            {ports.map((p) => (
              <option key={p}>{p}</option>
            ))}
          </select>
        </label>
        <label className="text-xs">
          To step
          <select
            aria-label="Connection target"
            className={field}
            value={target}
            onChange={(e) => setTarget(e.target.value)}
          >
            <option value="">Select next step</option>
            {graph.nodes
              .filter((n) => n.id !== source && n.type !== "entry")
              .map((n) => (
                <option key={n.id} value={n.id}>
                  {n.label || n.id}
                </option>
              ))}
          </select>
        </label>
        <button
          className={studioButton}
          disabled={
            !from ||
            !to ||
            !ports.includes(port) ||
            duplicate ||
            source === target
          }
          onClick={() => {
            onChange({
              ...graph,
              edges: [
                ...graph.edges,
                {
                  id: crypto.randomUUID(),
                  source,
                  target,
                  sourceHandle: port,
                  ...(port === "tool" ? { targetHandle: "tools" } : {}),
                },
              ],
            });
            setMessage("Connection added to draft.");
          }}
        >
          Connect steps
        </button>
      </div>
      {message && (
        <p role="status" className="mt-3 text-xs">
          {message}
        </p>
      )}
      <ul className="mt-4 divide-y">
        {graph.edges.map((edge) => (
          <li
            key={edge.id}
            className="flex items-center justify-between gap-4 py-3 text-xs"
          >
            <span>
              {graph.nodes.find((n) => n.id === edge.source)?.label ||
                edge.source}{" "}
              →{" "}
              {graph.nodes.find((n) => n.id === edge.target)?.label ||
                edge.target}{" "}
              · {edge.sourceHandle || "success"}
            </span>
            <button
              className="text-destructive underline"
              aria-label={"Remove connection " + edge.id}
              onClick={() =>
                onChange({
                  ...graph,
                  edges: graph.edges.filter((e) => e.id !== edge.id),
                })
              }
            >
              Remove
            </button>
          </li>
        ))}
      </ul>
    </details>
  );
}
