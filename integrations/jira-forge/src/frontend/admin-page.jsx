import React, { useEffect, useState } from "react";
import ForgeReconciler, {
  Button,
  Form,
  FormFooter,
  FormHeader,
  FormSection,
  Heading,
  Label,
  RequiredAsterisk,
  SectionMessage,
  Stack,
  Text,
  Textfield,
} from "@forge/react";
import { invoke, permissions } from "@forge/bridge";
import { approveDestination } from "../lib/egress.js";
import { permissionCleanupMessage } from "../lib/ui-state.js";

function App() {
  const [baseUrl, setBaseUrl] = useState("");
  const [integrationId, setIntegrationId] = useState("");
  const [secret, setSecret] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);
  const [warning, setWarning] = useState(null);

  useEffect(() => {
    invoke("getConfig").then((config) => {
      setBaseUrl(config.baseUrl || "");
      setIntegrationId(config.integrationId || "");
      if (config.configured) {
        setResult(config);
      }
    }).catch(() => setError("Unable to load configuration. Jira administrator access is required."));
  }, []);

  async function submit() {
    setSaving(true);
    setError(null);
    setWarning(null);
    try {
      if (!integrationId.trim() || !secret.trim()) throw new Error("Connection ID and secret are required.");
      const destination = await invoke("prepareConnection", { baseUrl });
      await approveDestination(permissions.egress, destination);
      const info = await invoke("saveConfig", { baseUrl: destination.baseUrl, integrationId, secret });
      setResult(info);
      setBaseUrl(info.baseUrl);
      setWarning(permissionCleanupMessage(false));
    } catch (reason) {
      setError(String(reason?.message || reason));
    } finally {
      setSecret("");
      setSaving(false);
    }
  }

  async function testSaved() {
    setSaving(true); setError(null);
    try { setResult(await invoke("testConnection")); }
    catch { setError("Connection test failed. Check credentials, server availability, and outbound permissions."); }
    finally { setSaving(false); }
  }

  async function disconnectSaved() {
    setSaving(true); setError(null);
    try {
      await invoke("disconnect");
      setResult(null); setSecret(""); setBaseUrl(""); setIntegrationId("");
      setWarning(permissionCleanupMessage(true));
    } catch { setError("Check connection status. If disconnected, remove any remaining TierX outbound permissions in Connected Apps."); }
    finally { setSaving(false); }
  }

  return (
    <Stack space="space.300">
      <Heading as="h1">Configure TierX</Heading>
      <Text>
        Enter the one-time credential created by a TierX platform administrator.
        The secret is stored in Forge encrypted storage.
        Your server must be reachable from Atlassian over public HTTPS. Approve
        the destination before credentials are sent. Changing the server or
        connection ID stops observation of old submissions.
      </Text>
      {error && (
        <SectionMessage appearance="error" title="Connection failed">
          <Text>{error}</Text>
        </SectionMessage>
      )}
      {warning && <SectionMessage appearance="warning" title="Outbound permission cleanup required"><Text>{warning}</Text></SectionMessage>}
      {result && (
        <SectionMessage appearance="success" title="Connected">
          <Text>Site connection: {result.connectionName || "Configured Jira site"}</Text>
          <Text>Saved server: {result.baseUrl}</Text>
          <Text>Configured project routes: {result.routeCount ?? 0}</Text>
        </SectionMessage>
      )}
      <Form onSubmit={submit}>
        <FormHeader title="TierX connection" />
        <FormSection>
          <Label labelFor="base-url">TierX server URL<RequiredAsterisk /></Label>
          <Textfield id="base-url" value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} />
          <Label labelFor="integration-id">Connection ID<RequiredAsterisk /></Label>
          <Textfield id="integration-id" value={integrationId} onChange={(event) => setIntegrationId(event.target.value)} />
          <Label labelFor="secret">Connection secret<RequiredAsterisk /></Label>
          <Textfield id="secret" type="password" value={secret} onChange={(event) => setSecret(event.target.value)} />
        </FormSection>
        <FormFooter>
          <Button appearance="primary" type="submit" isLoading={saving} isDisabled={saving}>Test and save</Button>
        </FormFooter>
      </Form>
      {result && <Stack space="space.100">
        <Button onClick={testSaved} isDisabled={saving}>Test connection</Button>
        <Text>Disconnect stops sending and polling. Existing Jira comments and TierX records are retained.</Text>
        <Button appearance="danger" onClick={disconnectSaved} isDisabled={saving}>Disconnect</Button>
      </Stack>}
    </Stack>
  );
}

ForgeReconciler.render(<App />);
