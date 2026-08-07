# Monitoring and operations

How to observe a Fabric platform and troubleshoot production failures.

## The identifiers, and why they matter
- **Pipeline run ID**: one execution of a pipeline. Your primary key for a run.
- **Activity run details**: per-activity input, output, duration, error inside a run.
- **Job ID**: an execution of a job (notebook, dataflow, etc.).
- **Correlation ID**: ties related operations together across items; the thread to pull when a failure spans components.
- **Workspace ID / Item ID**: identify where a thing lives; needed for support tickets and Log Analytics queries.
Capture these in your own log table so an incident is traceable without hunting through the UI.

## Where to look
- **Monitoring Hub**: central list of runs across items in a workspace. First stop for "what failed".
- **Activity run details**: drill into the failed activity for the actual error message and payload.
- **Refresh history**: for semantic models and dataflows.
- **Spark monitoring**: application UI, executor logs, stage/task detail for notebook/Spark jobs.
- **Capacity Metrics app**: CU consumption, throttling, smoothing, top consumers. This is where you diagnose "everything is slow".

## Azure Monitor / Log Analytics integration
- Route Fabric logs/metrics to Log Analytics for retention beyond the in-product window, cross-item queries (KQL), and alerting.
- Use when you need longer history, correlation across many items, or alerting the built-in UI does not cover.

## Alerts
- Wire pipeline failure paths to Teams/Email notification activities for immediate operational signal.
- Use Data Activator for condition-based alerts on live data or Power BI measures.
- Use Log Analytics alert rules for infrastructure/capacity thresholds.

## Cost and capacity monitoring
- Capacity is shared; one heavy Spark job or Dataflow can throttle unrelated reports on the same capacity.
- Watch CU usage, throttling events, and the top-consuming items in the Capacity Metrics app.
- Bursting/smoothing means a spike may be absorbed then repaid; sustained overload is the real problem. Right-size the SKU or isolate workloads onto separate capacities.

## Troubleshooting a production failure (the drill)
1. Monitoring Hub: find the failed run, note run ID and timestamp.
2. Open activity run details: read the actual error, not just "failed". Capture input/output payloads.
3. Classify: transient (timeout, throttling, source blip) vs deterministic (bad data, schema drift, permission, logic bug).
4. Transient: check capacity throttling and source availability; confirm retry settings; re-run if isolated.
5. Deterministic: reproduce with the same parameters; inspect the offending data; check for schema drift against the control table; verify identity/permissions (managed identity, Key Vault access).
6. Correlate: use the correlation ID to see whether upstream activities or a shared capacity event contributed.
7. Fix forward, then harden: add the missing validation, retry, or alert so the same failure is caught earlier next time.
8. Log the incident and resolution; feed recurring failures back into pipeline design.

## Operational hygiene
- Every pipeline writes run status (start, end, rows, status, error) to a log table. The UI is for humans; the log table is for automation and history.
- Validate inputs before processing (Validation / Get Metadata) so failures are caught at the gate with clear messages, not deep in a transform.
