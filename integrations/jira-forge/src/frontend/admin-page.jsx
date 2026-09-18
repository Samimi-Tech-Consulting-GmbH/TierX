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
import { invoke } from "@forge/bridge";

function App() {
  const [baseUrl, setBaseUrl] = useState("https://tierx.example.com");
  const [integrationId, setIntegrationId] = useState("");
  const [secret, setSecret] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    invoke("getConfig").then((config) => {
      setBaseUrl(config.baseUrl || "https://tierx.example.com");
      setIntegrationId(config.integrationId || "");
      if (config.configured) {
        setResult({
          name: config.connectionName,
          route_count: config.routeCount,
          configured: true,
        });
      }
    });
  }, []);

  async function submit() {
    setSaving(true);
    setError(null);
    try {
      const info = await invoke("saveConfig", { baseUrl, integrationId, secret });
      setResult(info);
      setSecret("");
    } catch (reason) {
      setError(String(reason?.message || reason));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Stack space="space.300">
      <Heading as="h1">Configure TierX</Heading>
      <Text>
        Enter the one-time credential created by a TierX platform administrator.
        The secret is stored in Forge encrypted storage.
      </Text>
      {error && (
        <SectionMessage appearance="error" title="Connection failed">
          <Text>{error}</Text>
        </SectionMessage>
      )}
      {result && (
        <SectionMessage appearance="success" title="Connected">
          <Text>Site connection: {result.name || "Configured Jira site"}</Text>
          <Text>Configured project routes: {result.route_count ?? 0}</Text>
        </SectionMessage>
      )}
      <Form onSubmit={submit}>
        <FormHeader title="TierX connection" />
        <FormSection>
          <Label labelFor="base-url">Base URL<RequiredAsterisk /></Label>
          <Textfield id="base-url" value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} />
          <Label labelFor="integration-id">Integration ID<RequiredAsterisk /></Label>
          <Textfield id="integration-id" value={integrationId} onChange={(event) => setIntegrationId(event.target.value)} />
          <Label labelFor="secret">Integration secret<RequiredAsterisk /></Label>
          <Textfield id="secret" type="password" value={secret} onChange={(event) => setSecret(event.target.value)} />
        </FormSection>
        <FormFooter>
          <Button appearance="primary" type="submit" isLoading={saving}>Test and save</Button>
        </FormFooter>
      </Form>
    </Stack>
  );
}

ForgeReconciler.render(<App />);
