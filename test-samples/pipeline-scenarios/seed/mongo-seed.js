// Seed data for the pipeline test scenarios.
// Run: docker exec -i socmind_mongodb mongosh -u root -p example < seed/mongo-seed.js
const platform = db.getSiblingDB("soc_mind_platform");
const tenantDb = db.getSiblingDB("soc_mind_tenant_demo");

platform.tenants.updateOne(
  { tenant_id: "tenant-demo" },
  { $set: {
      tenant_id: "tenant-demo",
      name: "Demo Tenant",
      status: "ACTIVE",
      db_name: "soc_mind_tenant_demo",
      allowed_source_systems: ["SPLUNK", "CORTEX_XDR"],
  } },
  { upsert: true }
);

// Schema A: endpoint malware — WITH playbook link (enrichment tier a)
tenantDb.alert_type_schemas.updateOne(
  { alert_type: "splunk.notable.endpoint_malware", version: "1.0.0" },
  { $set: {
      schema_id: "schema-malware-100",
      tenant_id: "tenant-demo",
      alert_type: "splunk.notable.endpoint_malware",
      version: "1.0.0",
      description: "Splunk endpoint malware notables (ECS mapping)",
      field_mapping: {
        "host.hostname": "result.host", "source.ip": "result.src",
        "destination.ip": "result.dest", "destination.port": "result.dest_port",
        "user.name": "result.user", "process.name": "result.process",
        "process.command_line": "result.process_command_line",
        "file.path": "result.file_path", "file.hash.sha256": "result.file_hash",
        "event.severity": "result.severity", "event.category": "result.category",
        "event.action": "result.action", "rule.name": "result.rule_name",
        "rule.id": "result.rule_id", "threat.technique.id": "result.mitre_attack_id",
        "event.created": "result._time"
      },
      critical_fields: ["host.hostname", "source.ip", "event.severity", "event.created"],
      playbook_id: "pb-malware-triage",
      is_active: true, severity: "5",
      created_at: new Date(), updated_at: new Date(), created_by: "seed",
  } },
  { upsert: true }
);

// Schema B: phishing — WITHOUT playbook link (enrichment tier b: alert_types fallback)
tenantDb.alert_type_schemas.updateOne(
  { alert_type: "splunk.notable.phishing", version: "1.0.0" },
  { $set: {
      schema_id: "schema-phishing-100",
      tenant_id: "tenant-demo",
      alert_type: "splunk.notable.phishing",
      version: "1.0.0",
      description: "Splunk phishing notables",
      field_mapping: {
        "host.hostname": "result.host", "source.ip": "result.src",
        "user.name": "result.user", "event.severity": "result.severity",
        "event.created": "result._time"
      },
      critical_fields: ["host.hostname", "event.severity", "event.created"],
      playbook_id: null,
      is_active: true, severity: "3",
      created_at: new Date(), updated_at: new Date(), created_by: "seed",
  } },
  { upsert: true }
);

// Schema C: valid at upload, poisoned at runtime — critical field not present in mapping.
// Every alert of this type dies in Validation with MISSING_REQUIRED_FIELD.
tenantDb.alert_type_schemas.updateOne(
  { alert_type: "splunk.notable.poisoned", version: "1.0.0" },
  { $set: {
      schema_id: "schema-poisoned-100",
      tenant_id: "tenant-demo",
      alert_type: "splunk.notable.poisoned",
      version: "1.0.0",
      field_mapping: { "host.hostname": "result.host" },
      critical_fields: ["destination.ip"],   // <-- not in field_mapping
      playbook_id: null, is_active: true,
      created_at: new Date(), updated_at: new Date(), created_by: "seed",
  } },
  { upsert: true }
);

// Playbook 1: linked by schema A
tenantDb.playbooks.updateOne(
  { playbook_id: "pb-malware-triage", version: 1 },
  { $set: {
      playbook_id: "pb-malware-triage", version: 1, tenant_id: "tenant-demo",
      playbook_name: "Endpoint Malware Triage",
      actions: [],
      prompt: "You are a Tier-1 SOC analyst. Analyse this endpoint malware alert. Summarize what happened, assess severity, cite evidence from the alert fields, and recommend next actions.",
      description: "Triage playbook for endpoint malware alerts.",
      alert_types: ["splunk.notable.endpoint_malware"],
      is_active: true, is_system: false, created_by: "seed",
      created_at: new Date(), updated_at: new Date(),
  } },
  { upsert: true }
);

// Playbook 2: found via alert_types fallback (schema B has no playbook_id)
tenantDb.playbooks.updateOne(
  { playbook_id: "pb-phishing", version: 1 },
  { $set: {
      playbook_id: "pb-phishing", version: 1, tenant_id: "tenant-demo",
      playbook_name: "Phishing Triage",
      actions: [],
      prompt: "You are a Tier-1 SOC analyst. Analyse this phishing alert: assess sender reputation indicators present in the alert, affected user, and recommend containment steps.",
      description: "Triage playbook for phishing alerts.",
      alert_types: ["splunk.notable.phishing"],
      is_active: true, is_system: false, created_by: "seed",
      created_at: new Date(), updated_at: new Date(),
  } },
  { upsert: true }
);

// Playbook 3: SYSTEM default (future target design; not yet used by current code)
tenantDb.playbooks.updateOne(
  { playbook_id: "pb-system-default", version: 1 },
  { $set: {
      playbook_id: "pb-system-default", version: 1, tenant_id: "tenant-demo",
      playbook_name: "System Default Analysis",
      actions: [],
      prompt: "You are a SOC analyst. No specific playbook exists for this alert type. Perform a generic triage: classify the alert, extract indicators, and recommend whether to escalate.",
      description: "Platform default playbook used when no tenant playbook matches.",
      alert_types: [],
      is_active: true, is_system: true, created_by: "seed",
      created_at: new Date(), updated_at: new Date(),
  } },
  { upsert: true }
);

print("Seed complete: 1 tenant, 3 schemas, 3 playbooks.");
