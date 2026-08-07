# Metadata-driven pipelines

Why enterprises build generic, reusable pipelines instead of one activity per table, and how.

## The problem it solves
Hardcoding one Copy activity per source table does not scale: 200 tables means 200 activities to build, test, and maintain, and every new table is a code change. Metadata-driven design moves the "what to load" out of the pipeline and into a control table, so one generic pipeline loads all of them and adding a source is a row insert, not a redeploy.

## Building blocks
- **Parameters**: values passed into a pipeline or notebook at runtime (source name, destination, load type). Set at call time; do not mutate.
- **Variables**: mutable values within a pipeline run. Beware mutation inside parallel ForEach (race conditions).
- **Expressions / dynamic content**: build values at runtime from parameters, variables, and system variables.
- **System variables**: pipeline name, run ID, trigger time, etc. Use for logging and idempotency.

## Control / config table (the heart of it)
A table describing every source object to load. Typical columns:
- source system, source object/query, destination lakehouse/warehouse and table
- workspace/lakehouse/tenant IDs
- load type (full/incremental), watermark column, last watermark value
- priority/order, is_enabled flag
- optional paging fields (offset, remaining rows) for batching large sets

The pipeline reads this, not hardcoded values. Enabling/disabling or reprioritizing a load is a data change.

## The core pattern
1. **Lookup** the control table, filtered by process type and is_enabled.
2. **ForEach** over the returned rows (sequential or bounded-parallel per load characteristics).
3. Inside, **Execute Pipeline** calls a child pipeline, passing the row's fields as parameters.
4. The **child** does the per-object work: Copy or Notebook driven by its parameters, writes data, updates the watermark, logs status, returns a result.
5. Parent aggregates child results into the log table.

## Parent/child (generic, reusable pipelines)
- Parent: orchestration and looping only. Knows nothing source-specific.
- Child: does one object's load, fully parameterized. Testable in isolation by passing one set of parameters.
- Benefit: one child pipeline serves hundreds of objects; fixes and improvements apply everywhere at once.

## Paging the control table itself
For very large source counts, page the config table (offset / remaining-rows) so you process it in batches through the same ForEach, invoking recursively until remaining rows hits zero. This keeps a single loop handling an arbitrary number of objects without one giant iteration.

## Common mistakes
- Mutating an append variable inside a parallel ForEach and getting nondeterministic results.
- Updating the watermark before the load succeeds, creating gaps on failure.
- Non-idempotent child loads, so a retry double-loads. Design MERGE-based, replayable loads.
- Putting connection secrets in the control table instead of Key Vault.
- Letting the control table drift from reality (disabled sources still enabled, stale watermarks).

## Why this over per-table pipelines
Maintainability and scale win decisively at more than a handful of tables. The cost is up-front design complexity and a control table to govern, which is why for a two-table POC a hardcoded pipeline is fine and this pattern is overkill. Say so when the scale does not justify it.
