# Enterprise architecture patterns

How large orgs actually build and run Fabric platforms. Pull the relevant section.

## Contents
- Medallion (bronze/silver/gold)
- Load strategies: full vs incremental
- Watermarks
- CDC
- SCD Type 1 and Type 2
- Delta tables, partitioning, file optimization
- Data retention
- Multi-workspace / multi-environment (Dev/Test/UAT/Prod)
- Deployment pipelines and release management
- Git branching strategy
- Disaster recovery and backup

## Medallion (bronze / silver / gold)
- **Bronze**: raw as-ingested, append-only, minimal transformation, keep source fidelity. This is your replay buffer; never overwrite history you might need.
- **Silver**: cleaned, conformed, deduplicated, typed. One row per business entity/event. Business rules applied.
- **Gold**: business-level aggregates and star-schema tables ready for reporting and Direct Lake.
- Keep each layer as Delta tables; separate by schema/folder. Serving reads gold, not silver.
- Why the separation: reprocessability (rebuild silver/gold from bronze), clear contracts between layers, and a clean serving surface. Collapsing layers saves storage but loses auditability and replay.

## Load strategies
- **Full load**: truncate and reload. Simple, correct, expensive at scale. Fine for small dimensions or when the source has no reliable change signal.
- **Incremental load**: pull only changed/new rows since last run. Cheaper and faster; needs a change signal (a watermark column or CDC).
- Choose incremental once volume or frequency makes full loads costly, and the source can tell you what changed.

## Watermarks
- Store the high-water mark (max modified timestamp or ID) per source object in a control table.
- Each run reads rows greater than the stored watermark, then updates it after success.
- Update the watermark only on successful load to avoid gaps; make loads idempotent so a retry does not double-count.

## CDC (change data capture)
- Source emits inserts/updates/deletes. Options: native source CDC, Fabric Mirroring for supported sources, or a watermark approximation when true CDC is unavailable.
- Use true CDC when you must capture deletes and mid-cycle updates accurately; watermarks alone miss hard deletes.

## SCD Type 1 vs Type 2
- **Type 1**: overwrite the attribute. No history. Use when only the current value matters (a corrected typo).
- **Type 2**: keep history by adding a new row with effective-from/effective-to (or current-flag) columns. Use when you must report as-of a point in time (a customer's region last quarter vs now).
- Apply SCD to descriptive dimension attributes, not to measures. In a lakehouse, implement with MERGE INTO in silver/gold (mechanics in faisal-fabric / faisal-pyspark).
- Common mistake: SCD2 on everything. It is expensive and only justified where history has business value.

## Delta tables, partitioning, file optimization
- Partition large tables by a low-cardinality column used in filters (usually a date). Do not over-partition; too many small partitions hurts more than it helps.
- Compact small files with OPTIMIZE; reclaim old versions with VACUUM (respecting your time-travel retention needs).
- Prefer MERGE for upserts over overwrite so you keep Delta history and do not rewrite whole tables.

## Data retention
- Decide retention per layer: bronze often longest (replay/audit), gold aligned to reporting needs.
- VACUUM retention governs how far back time travel works; set it deliberately, not by default.

## Multi-workspace / multi-environment
- Separate Dev, Test, UAT, Prod, typically as distinct workspaces, often per domain.
- Isolate capacities so non-prod load cannot throttle prod.
- Parameterize connections so the same item points at the right source per environment.

## Deployment pipelines and release management
- Promote content Dev to Test to Prod with deployment pipelines; use deployment rules to swap environment-specific parameters (connections, workspace/lakehouse IDs) per stage.
- Do not hand-edit items in Prod; changes flow through the pipeline so they are reviewed and reproducible.

## Git branching strategy
- Version-control workspace items via Git integration.
- A workable model: feature branches off main, PR review, merge to a Dev-tracked branch, then promote through deployment pipelines. Keep one branch mapped to Dev; higher environments come from promotion, not direct Git sync, unless your governance says otherwise.
- Keep company code ownership in mind: personal account vs a GitHub organization matters for continuity when people leave.

## Disaster recovery and backup
- Know what OneLake/Fabric provides versus what you must arrange. Design for RPO/RTO the business actually needs, not a vague "we have backups".
- Bronze retention plus reproducible silver/gold builds is itself a recovery strategy: if downstream is lost, rebuild from bronze.
- For critical sources, keep an independent copy or rely on the source system's own recovery. Document the recovery runbook; untested DR is not DR.
