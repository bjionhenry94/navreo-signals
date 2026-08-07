# Data Factory activities (Fabric pipelines)

Per activity: purpose, key settings, failure/retry behavior, common mistakes, enterprise use. Pull the ones relevant to the question.

Cross-cutting notes that apply to every activity:
- **Retry**: most activities expose retry count and retry interval. Set them for transient-failure-prone activities (Copy from flaky sources, Web calls), not for logic that should fail fast.
- **Timeout**: default is generous (often 12h). Tighten it so a hung activity does not silently burn capacity.
- **Failure handling**: use the red (failure), green (success), and other output paths to route to logging/notification. An unhandled failure stops the pipeline; decide per activity whether that is what you want.
- **Logging**: write run status to a log table (see enterprise-patterns.md and monitoring-ops.md). Do not rely only on the Monitor UI.

## Copy Activity
- Purpose: move data source to sink, optional light mapping/type conversion.
- Key settings: source dataset, sink dataset, mapping, staging, parallel copies, degree of copy parallelism, fault tolerance (skip incompatible rows).
- Mistakes: using Copy to do transformation logic; not enabling staging for large cross-store copies; ignoring parallelism on large loads.
- Performance: throughput scales with parallel copies and DIU-equivalent settings; partition the source for parallelism.
- Enterprise use: the workhorse for bronze ingestion. Metadata-driven: one generic Copy in a ForEach over a control table.
- Why Copy over Notebook for ingestion: cheaper and simpler for straight movement; no Spark cluster spin-up. Reach for a Notebook when you need real transformation on the way in.

## Lookup
- Purpose: read a single row or a small result set (from a table, file, or query) into the pipeline for use in expressions.
- Key settings: source, query vs table, first-row-only toggle.
- Mistakes: pulling large result sets (Lookup has a row cap); use it for control data, not bulk.
- Enterprise use: read the control/config table, feed its rows into ForEach. The backbone of metadata-driven pipelines.

## Get Metadata
- Purpose: inspect an object (file/folder existence, size, last modified, child items, column list).
- Enterprise use: check a file landed before processing; drive conditional logic on existence or size.

## If Condition
- Purpose: branch on a boolean expression.
- Mistakes: deep nesting; prefer Switch or a metadata-driven approach when there are many branches.

## Switch
- Purpose: multi-way branch on an expression value.
- Enterprise use: route by load type or source system read from the control table.

## Filter
- Purpose: filter an array to a subset in-pipeline.
- Enterprise use: narrow a Get Metadata child list or a control-table array before ForEach.

## Until
- Purpose: loop until a condition is met.
- Mistakes: no safety timeout or max-iteration guard, creating an infinite loop.
- Enterprise use: paging a source (offset/remaining-rows pattern) until rows are exhausted.

## ForEach
- Purpose: iterate over an array, running inner activities per item.
- Key settings: sequential vs parallel, batch count.
- Mistakes: leaving it parallel when order matters or when parallelism overloads the source/capacity; oversized batch counts.
- Enterprise use: the loop in metadata-driven ingestion. ForEach over control-table rows, each calling a child pipeline via Execute Pipeline.

## Execute Pipeline
- Purpose: call a child pipeline, optionally passing parameters and waiting for completion.
- Enterprise use: parent/child pattern. Parent loops and orchestrates; child does the per-object work. Keeps pipelines reusable and testable. See metadata-driven.md.

## Web Activity
- Purpose: call a REST endpoint (GET/POST/etc.), read the response.
- Key settings: URL, method, headers, body, authentication (managed identity preferred).
- Mistakes: putting secrets in plain text instead of Key Vault; not handling non-2xx responses.
- Security: authenticate with managed identity/service principal; never inline credentials.

## Wait
- Purpose: pause for a set duration.
- Enterprise use: backoff between polling attempts; rarely needed in well-designed flows.

## Set Variable / Append Variable
- Purpose: assign a pipeline variable / append to an array variable.
- Mistakes: relying on variable mutation inside a parallel ForEach (race conditions). Append in parallel loops is unreliable; iterate sequentially or restructure.

## Fail
- Purpose: deliberately fail the pipeline with a custom message and error code.
- Enterprise use: enforce a data-quality gate; if a validation check fails, Fail with a clear message so monitoring surfaces it.

## Validation
- Purpose: wait for and validate that a dataset/file exists (and optionally meets size/age) before proceeding.
- Enterprise use: do not start processing until the upstream file has actually landed.

## Delete
- Purpose: delete files/folders.
- Mistakes: pointing it at the wrong path; no logging of what was deleted. Handle with care; deletes are destructive.

## Stored Procedure
- Purpose: execute a stored proc in a warehouse/SQL target.
- Enterprise use: push set-based transformation into the warehouse where SQL is the right tool; log run metadata via a proc.
- Why proc over Notebook: for SQL-native set logic against a warehouse, a proc is simpler and avoids Spark startup. Notebook wins for Spark-scale or non-SQL logic.

## Script
- Purpose: run arbitrary SQL (DDL/DML, multiple statements) against a SQL target.
- Enterprise use: schema management, control-table updates, watermark writes.

## Notebook
- Purpose: run a Fabric notebook (Spark) with parameters.
- Key settings: parameters passed in, session/environment config.
- Enterprise use: the transformation step in a pipeline. Parameterize so one notebook serves many objects. Mechanics in faisal-fabric / faisal-pyspark.
- Why Notebook over Dataflow Gen2: cheaper and more controllable at scale; Dataflow wins for analyst-owned low-code transforms at modest volume.

## Azure Function
- Purpose: call custom code hosted in Azure Functions.
- Enterprise use: bespoke logic that does not fit pipeline activities (custom API auth flows, specialized processing).
- Why Function: when you need real code and neither Notebook nor pipeline expressions fit. Adds an external dependency to operate and secure.

## Office Scripts
- Purpose: run an Office Script (Excel automation) from the pipeline.
- Enterprise use: niche; Excel-centric business processes.

## Teams / Email Notifications
- Purpose: send a Teams message or email, typically on success/failure.
- Enterprise use: wire to the failure path for operational alerting. Prefer routing through a standard notification child pipeline so the format is consistent.

## Pipeline Return Value
- Purpose: return a value from a child pipeline to its caller.
- Enterprise use: child reports rows processed / status back to the parent for logging and control flow.
