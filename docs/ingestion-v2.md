# Workflow execution

Use [Workflow Studio](workflows.md) for platform-managed workflows, nested
playbooks, agents, tools and fixed ingestion URLs. The standard pipeline service
runs the workflow scheduler automatically.

The former tenant-owned Ingestion V2 experiment is retired. Historical reads
remain available; legacy mutations and ingestion return 410. There are no
execution-mode flags and no optional workflow worker profile.
