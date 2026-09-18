# Correlation fixtures

These are messages for the private `enriched` Kafka topic, not HTTP ingestion
bodies.

- `enriched-shared-ip-a.json` creates an open cluster.
- `enriched-shared-ip-b.json` has a different fingerprint but shares
  `source.ip` and `threat.technique.id`, so it joins the first cluster.
- `enriched-no-overlap.json` creates a separate solo cluster.
- `synthetic-alert-a.json` and `synthetic-alert-b.json` are the
  synthetic regression pair. They share hostname, source IP, and username
  and must form one correlated cluster even when stored MongoDB dates mix
  legacy timezone-naive and timezone-aware values.

The expected MVP rule is exact, case-sensitive equality on the same ECS field.
There is no weighted overlap score. Correlation must be enabled explicitly.
