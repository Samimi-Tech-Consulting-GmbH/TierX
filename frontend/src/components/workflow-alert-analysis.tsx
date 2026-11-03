"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { workflowRequest } from "@/lib/workflows";
import type { AlertDocument } from "@/lib/types";

export function WorkflowAlertAnalysis({ tenantId, alert }: { tenantId: string; alert: AlertDocument }) {
  const [history, setHistory] = useState<unknown[]>([]), [feedback, setFeedback] = useState<unknown[]>([]);
  const [decision, setDecision] = useState("APPROVE"), [corrections, setCorrections] = useState("");
  const [message, setMessage] = useState(""), [busy, setBusy] = useState(false);
  const [verdict, setVerdict] = useState(alert.verdict || "INCONCLUSIVE");
  const base = `/tenants/${tenantId}/alerts/${alert.alert_id}`;
  useEffect(() => {
    const controller = new AbortController();
    Promise.all([workflowRequest<{ items: unknown[] }>(base + "/workflow-analyses", "GET", undefined, controller.signal),
      workflowRequest<{ items: unknown[] }>(base + "/feedback", "GET", undefined, controller.signal)])
      .then(([analyses, entries]) => { setHistory(analyses.items); setFeedback(entries.items); })
      .catch(() => { if (!controller.signal.aborted) setMessage("Analysis history could not be loaded."); });
    return () => controller.abort();
  }, [base]);
  async function save() {
    setBusy(true); setMessage("");
    try { const item = await workflowRequest(base + "/feedback", "POST", { decision, claim_corrections: corrections });
      setFeedback(items => [item, ...items]); setCorrections(""); setMessage("Feedback recorded. No automatic training or benign rule was created.");
    } catch (reason) { setMessage(reason instanceof Error ? reason.message : "Feedback failed"); }
    finally { setBusy(false); }
  }
  async function applyVerdict() {
    if (!corrections.trim()) { setMessage("Provide a rationale before applying an analyst verdict."); return; }
    setBusy(true);
    try { await workflowRequest(base + "/decision", "PUT", { verdict, rationale: corrections }); setMessage("Analyst verdict saved on this alert only."); }
    catch (reason) { setMessage(reason instanceof Error ? reason.message : "Decision failed"); }
    finally { setBusy(false); }
  }
  return <section className="space-y-3 rounded-xl border p-5"><h2 className="font-semibold">Alert-owned workflow analysis</h2>
    {alert.run_id && <Link className="underline" href={`/dashboard/${tenantId}/workflows/runs/${alert.run_id}`}>Open workflow execution</Link>}
    <p className="text-sm text-muted-foreground">Cluster membership supplies context only. Each alert retains its own result and analyst decision.</p>
    <pre className="max-h-96 overflow-auto whitespace-pre-wrap text-xs">{JSON.stringify(alert.alert_analysis || { status: alert.analysis_status || "No persisted analysis" }, null, 2)}</pre>
    <details><summary>Analysis history ({history.length})</summary><pre className="overflow-auto whitespace-pre-wrap text-xs">{JSON.stringify(history, null, 2)}</pre></details>
    <label className="block">Analyst feedback <select className="rounded border bg-background p-2" value={decision} onChange={event => setDecision(event.target.value)}>
      <option value="APPROVE">Approve</option><option value="ESCALATE">Escalate</option><option value="CORRECT">Correct</option></select></label>
    <label className="block">Evidence or claim corrections<textarea className="mt-1 block w-full rounded border bg-background p-2" maxLength={8192} value={corrections} onChange={event => setCorrections(event.target.value)} /></label>
    <button disabled={busy} className="rounded border p-2" onClick={save}>{busy ? "Saving…" : "Record feedback"}</button>
    <label className="block">Alert verdict <select className="rounded border bg-background p-2" value={verdict} onChange={event => setVerdict(event.target.value)}>
      <option>INCONCLUSIVE</option><option>TRUE_POSITIVE</option><option>FALSE_POSITIVE</option><option>BENIGN</option></select></label>
    <button disabled={busy} className="rounded border p-2" onClick={applyVerdict}>Apply analyst verdict</button>
    {message && <p role="status">{message}</p>}
    <details><summary>Recorded feedback ({feedback.length})</summary><pre className="overflow-auto whitespace-pre-wrap text-xs">{JSON.stringify(feedback, null, 2)}</pre></details>
  </section>;
}
