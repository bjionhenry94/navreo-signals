# Azure data services, and when to choose Azure-native over Fabric-native

Fabric does a lot, but not everything, and sometimes an Azure service is the right call even in a Fabric shop. Each entry: what it is and the "reach for this instead of Fabric when..." trigger.

## Contents
- ADLS Gen2
- Azure SQL Database
- Azure Synapse Analytics
- Azure Functions
- Azure Logic Apps
- Azure Key Vault
- Azure Monitor / Log Analytics
- Azure DevOps
- Entra ID
- Networking (VNet, Private Endpoints)
- IAM / RBAC / Managed Identity / Service Principals
- API Management
- Event Grid / Event Hub / Service Bus

## ADLS Gen2
Hierarchical-namespace object storage.
- Fabric OneLake sits on the same lineage. Use OneLake shortcuts to reference existing ADLS in place rather than copying.
- Reach for ADLS directly when data must live outside Fabric governance, or a non-Fabric consumer owns it.

## Azure SQL Database
Managed OLTP relational database.
- Reach for it (not a Fabric Warehouse) when you need a transactional application backend. Bring its data into Fabric via Mirroring or Copy.

## Azure Synapse Analytics
The prior-generation analytics platform (dedicated/serverless SQL, Spark).
- Fabric is the strategic successor for new builds. Reach for Synapse only when an existing investment or a specific feature parity gap requires it; plan migration toward Fabric.

## Azure Functions
Serverless custom code.
- Reach for it when you need real code that pipeline activities and notebooks cannot express cleanly (custom auth handshakes, specialized processing), then call it from a pipeline Web/Function activity.

## Azure Logic Apps
Low-code workflow/integration with hundreds of connectors.
- Reach for it for business-process integration and SaaS connectors outside the data-engineering path. For in-platform data orchestration, Fabric pipelines are the native choice.

## Azure Key Vault
Secret, key, and certificate store.
- Always the answer for credentials. Never inline secrets in pipelines, control tables, or notebooks. Reference Key Vault, authenticate with managed identity.

## Azure Monitor / Log Analytics
Centralized logs/metrics with KQL and alerting.
- Reach for it when you need retention beyond Fabric's in-product window, cross-item correlation, or alerting the built-in tools do not cover. See monitoring-ops.md.

## Azure DevOps
Repos, pipelines, boards.
- Alternative to GitHub for source control and CI/CD of Fabric items. Choose based on where the org already lives; the branching/release principles are the same.

## Entra ID
Identity provider behind Fabric and Azure.
- The source of truth for who is who. Groups here drive workspace roles and data access. Design access around Entra groups, not individual users.

## Networking (VNet, Private Endpoints)
- Reach for private endpoints/VNet integration when data must not traverse public networks (regulated industries, sensitive sources). Confirm current Fabric networking feature support before committing a design.

## IAM / RBAC / Managed Identity / Service Principals
- **Managed identity**: preferred for service-to-service auth; no secrets to store or rotate. Use it for pipeline connections wherever supported.
- **Service principal**: for automation/apps that need their own identity; store its secret in Key Vault, prefer certificate over secret where possible.
- **RBAC**: grant least privilege via roles on the right scope. A dedicated read-only service account beats a personal account: least privilege and it survives staff changes.

## API Management
- Reach for it when you are exposing or governing APIs (rate limiting, auth, versioning), not for internal data movement.

## Event Grid / Event Hub / Service Bus
- **Event Hub**: high-throughput event ingestion; a common source for Fabric Eventstream.
- **Event Grid**: event routing/reactive triggers (e.g., react to a blob landing).
- **Service Bus**: enterprise messaging with queues/topics and ordering/delivery guarantees.
- Reach for these upstream of Fabric for the streaming/eventing backbone; Eventstream then ingests into Fabric.

## The general rule
Default to Fabric-native for anything inside the analytics platform: it is integrated, governed through OneLake, and less to operate. Reach for an Azure service when the workload is genuinely outside Fabric's remit (OLTP apps, secret management, custom code, enterprise messaging, private networking, cross-cloud governance) or when an existing investment makes it pragmatic. State the trade-off rather than defaulting on autopilot in either direction.
