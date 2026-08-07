# Fabric components

Each entry: what it is, when to use, when not to, and the gotcha that bites people. Pull the relevant entry; do not read end to end.

## Contents
- OneLake
- Lakehouse
- Warehouse
- Data Factory (pipelines), see also data-factory-activities.md
- Dataflow Gen2
- Notebooks / Spark
- Semantic models / Direct Lake
- Power BI
- Real-Time Intelligence (Eventstream, Eventhouse, KQL DB)
- Data Activator
- Mirroring
- Fabric Databases (SQL database)
- Data Science
- Shortcuts
- Domains
- Environments
- Deployment Pipelines / Git / CI/CD
- Capacity, Workspaces, Security, Governance

## OneLake
One tenant-wide data lake, one copy of data, open Delta/Parquet format, addressable by every Fabric item. Think "OneDrive for data".
- Use: as the single physical store under everything. Reference data in place with shortcuts instead of copying.
- Not: as a dumping ground with no medallion structure; governance still applies.
- Gotcha: everything is Delta/Parquet underneath, so "lakehouse vs warehouse" is an experience choice over the same lake, not two separate storage systems.

## Lakehouse
Files plus Delta tables, readable by Spark and by a SQL analytics endpoint (read-only T-SQL).
- Use: data engineering, ingestion, medallion layers, unstructured/semi-structured data, anything Spark-first.
- Not: when the team is SQL-only and needs multi-table transactions or full T-SQL writes; use a Warehouse.
- Gotcha: the SQL endpoint on a lakehouse is read-only. Writes go through Spark. Endpoint metadata can lag after Spark writes.

## Warehouse
Full T-SQL, multi-table ACID transactions, writes via SQL. Still stores Delta in OneLake.
- Use: SQL-centric teams, heavy BI serving, when you need T-SQL DML and transactions.
- Not: for large-scale file/unstructured processing or Spark ML; that is lakehouse territory.
- Gotcha: do not copy the same data into both lakehouse and warehouse without a reason. One copy in OneLake, referenced, is the goal.

## Data Factory (pipelines)
Orchestration: Copy, control flow, calling notebooks/procedures. Detailed activity reference in data-factory-activities.md.
- Use: ingestion and orchestration, metadata-driven loops.
- Not: for heavy row-level transformation logic; push that to Spark or SQL.
- Gotcha: pipelines orchestrate, they do not transform well. Keep transformation in notebooks/SQL.

## Dataflow Gen2
Power Query (M) low-code transformation with a designer.
- Use: analyst-built transformations, moderate volumes, when the team lives in Power Query.
- Not: for large-scale or performance-critical engineering; a notebook is cheaper and faster at scale.
- Gotcha: convenient but can be a cost and performance surprise on big data. Compare against a Copy+Notebook path before defaulting to it.

## Notebooks / Spark
PySpark/Spark SQL over lakehouse Delta.
- Use: real transformation, medallion silver/gold builds, ML, large or semi-structured data.
- Not: for one-row lookups or simple orchestration; that is a pipeline's job.
- Gotcha: small-file problems and over-partitioning kill performance. Use MERGE for upserts, OPTIMIZE/VACUUM to compact. Mechanics live in faisal-fabric / faisal-pyspark.

## Semantic models / Direct Lake
The BI model layer. Direct Lake reads gold Delta directly: import-like speed with no refresh copy.
- Use: build the semantic model on clean gold star-schema Delta tables for Direct Lake.
- Not: on messy wide silver tables; Direct Lake can fall back to DirectQuery and lose its speed advantage.
- Gotcha: Direct Lake has guardrails (row/size limits per SKU) that trigger DirectQuery fallback. Star schema and clean gold tables keep it in Direct Lake mode. Modeling mechanics in faisal-powerbi-model.

## Power BI
Reporting and the semantic layer, now native in Fabric.
- Use: serving, dashboards, self-service.
- Gotcha: report performance is usually a model problem, not a visual problem. Fix the model first.

## Real-Time Intelligence
- **Eventstream**: ingest/route streaming events (Event Hubs, Kafka, IoT) with no/low code.
- **Eventhouse / KQL Database**: store and query high-volume time-series/log/telemetry data with KQL.
- Use: telemetry, logs, IoT, clickstream, anything append-heavy and time-ordered queried with KQL.
- Not: as a general relational store or for sl-changing dimensional BI; that is warehouse/lakehouse.
- Gotcha: KQL is not T-SQL. Different engine, different query language, different mental model.

## Data Activator
No-code trigger/alert engine: watch a stream or a Power BI measure, act when a condition is met.
- Use: operational alerting and automated actions off live data.
- Not: as a scheduler for batch pipelines; use the pipeline scheduler.

## Mirroring
Near-real-time replication of an external database (Azure SQL, Cosmos DB, Snowflake, etc.) into OneLake as Delta, continuously.
- Use: get an operational source into Fabric analytics-ready without building CDC pipelines.
- Not: when you need heavy transformation on ingest; mirroring lands a replica, you still model downstream.
- Gotcha: mirrored data is a read replica in OneLake; treat it as bronze and build silver/gold from it.

## Fabric Databases (SQL database)
A transactional SQL database native to Fabric, autogenerated Delta copy in OneLake.
- Use: app/OLTP workload that should sit close to analytics with minimal plumbing.
- Not: as your warehouse; it is OLTP-shaped.

## Data Science
Notebooks, MLflow experiments/models, integration with the lakehouse.
- Use: ML on lakehouse data, experiment tracking, model registry.

## Shortcuts
Reference data in place (ADLS, S3, another lakehouse) without copying.
- Use: single copy of data referenced by many items; avoid duplication and drift.
- Gotcha: a shortcut is a pointer; source availability and permissions still govern access.

## Domains
Logical grouping of workspaces by business area for federated governance (data mesh style).
- Use: large orgs organizing ownership across many workspaces.

## Environments
Reusable Spark configuration and libraries attached to notebooks/pipelines.
- Use: standardize Spark pool settings and library versions across a team.

## Deployment Pipelines / Git / CI/CD
- Deployment pipelines promote content across Dev/Test/Prod stages.
- Git integration version-controls workspace items.
- Use: any real project. See enterprise-patterns.md for branching and release strategy.
- Gotcha: not every item type supports Git/deployment equally; check current support before designing the release flow.

## Capacity, Workspaces, Security, Governance
- **Capacity** (F SKUs): the compute you pay for; workloads consume Capacity Units, subject to smoothing/throttling. Right-sizing and monitoring matter (see monitoring-ops.md).
- **Workspaces**: the unit of collaboration and access control; organize by environment and domain.
- **Security**: Entra ID identities, workspace roles, item permissions, OneLake data access roles, row/column/object-level security downstream.
- **Governance**: Purview integration, sensitivity labels, lineage, endorsement.
- Gotcha: capacity is shared across everything in it; a runaway Spark job or Dataflow can throttle unrelated reports on the same capacity.
