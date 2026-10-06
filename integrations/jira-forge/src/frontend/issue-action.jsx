import React, { useEffect, useRef, useState } from "react";
import ForgeReconciler, {
  Button,
  Heading,
  SectionMessage,
  Spinner,
  Stack,
  Text,
} from "@forge/react";
import { invoke, view } from "@forge/bridge";

import { TERMINAL_UI_STATES } from "../lib/ui-state.js";

function App() {
  const started = useRef(false);
  const [job, setJob] = useState({ state: "STARTING" });
  const [error, setError] = useState(null);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    let timer;
    invoke("enqueueIssue")
      .then((queued) => {
        setJob(queued);
        timer = setInterval(async () => {
          const current = await invoke("getActionStatus", {
            requestId: queued.requestId,
          });
          setJob(current);
          if (TERMINAL_UI_STATES.has(current.state)) clearInterval(timer);
        }, 2000);
      })
      .catch((reason) => setError(String(reason?.message || reason)));
    return () => timer && clearInterval(timer);
  }, []);

  const done = TERMINAL_UI_STATES.has(job.state);
  return (
    <Stack space="space.200">
      <Heading as="h2">Send to TierX</Heading>
      {error ? (
        <SectionMessage appearance="error" title="Submission could not start">
          <Text>{error}</Text>
        </SectionMessage>
      ) : job.state === "FAILED" || job.state === "CANCELLED" ? (
        <SectionMessage appearance="error" title={job.state === "CANCELLED" ? "TierX observation cancelled" : "TierX submission failed"}>
          <Text>{job.failure?.error_detail || "Open TierX traces for details."}</Text>
        </SectionMessage>
      ) : done ? (
        <SectionMessage appearance="success" title="Issue accepted">
          <Text>Alert UUID: {job.alertId}</Text>
          <Text>Current state: {job.state}</Text>
        </SectionMessage>
      ) : (
        <SectionMessage appearance="information" title="Submission queued">
          <Stack space="space.100">
            <Spinner size="small" />
            <Text>Current step: {job.state.replaceAll("_", " ")}</Text>
            <Text>You may close this dialog. TierX will comment on the issue.</Text>
          </Stack>
        </SectionMessage>
      )}
      {job.state !== "STARTING" || error ? (
        <Button onClick={() => view.close()}>Close</Button>
      ) : null}
    </Stack>
  );
}

ForgeReconciler.render(<App />);
