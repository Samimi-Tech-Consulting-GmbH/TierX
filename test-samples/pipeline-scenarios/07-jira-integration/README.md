# Jira integration scenario

The Jira issue is a transport and audit surface for a normal TierX alert. It
is not converted into a `jira.issue.security` alert.

For a fresh Forge installation, use the endpoint-malware schema and playbook
from the sibling `schemas` and `playbooks` directories. No Jira-specific schema
is required; the obsolete Jira-envelope fixtures have been removed.

Create a Jira issue and provide the contents of `alert-valid.json` in exactly
one of these locations:

1. a JSON code block in the issue description; or
2. one UTF-8 `.json` or `.txt` attachment no larger than 1 MiB.

The JSON is the raw source object only. The Jira site's `DEMO` project must be
routed in TierX to the intended tenant, `SPLUNK`, and
`splunk.notable.endpoint_malware`. The route and active schema supply the normal
ingestion envelope, including the `result._time` event timestamp. Jira metadata
is stored separately as alert provenance and is not inserted into the raw alert.

Expected behavior:

1. **Send to TierX** extracts one unambiguous raw alert object.
2. The alert enters the normal Splunk schema, normalization, correlation, and
   analysis pipeline with its original source and alert type.
3. Jira receives an acknowledgement containing the TierX alert UUID.
4. Jira later receives the analysis result or a sanitized pipeline failure.
5. Missing, malformed, conflicting, or legacy-wrapper alerts produce a clear Jira
   input-error comment and no TierX alert.
