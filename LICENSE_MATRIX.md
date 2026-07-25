# Licensing & Feature Matrix: BFA-SDK & IRC-A

The Backend for Agents (BFA) SDK and the IRC-A architecture operate under a **Dual-Licensing Model**:
*   **Community Edition:** Open-source under the **GNU Affero General Public License v3 (AGPLv3)**.
*   **Enterprise Edition:** Closed-source under a **Commercial Proprietary License** tailored for corporate and high-compliance deployments.

---

## Our Security Philosophy: No Security Paywalls

We believe that **system security and network hardening are fundamental rights, not upsells**. 

In many infrastructure projects, critical security features (such as TLS encryption, token authentication, and prompt validation) are locked behind premium commercial tiers. We reject this practice. 

The **Community Edition SDK inherits 100% of the cryptographic security pipeline** out-of-the-box. Every startup, independent developer, and academic researcher can build zero-trust agentic networks using the exact same mathematical security safeguards as a global bank.

**What we commercialize is not the lock, but the dashboard.** Enterprise customers pay for governance at scale, operational observability (beautiful dashboards), integration with corporate SIEM logging pipelines, and professional SLAs.

---

## Feature Matrix

| Feature Category | Capability / Feature | Community Edition (AGPLv3) | Enterprise Edition (Commercial) |
| :--- | :--- | :---: | :---: |
| **Core Architecture** | Peer-to-Peer Message Passing (JSON-RPC) | ✔ | ✔ |
| | Late-Binding capability discovery | ✔ | ✔ |
| | Dynamic Hot-plugging of new Nodes | ✔ | ✔ |
| **Zero-Trust Security** | Ephemeral Delegated Execution Tokens (PASETO DET) | ✔ | ✔ |
| | Offline Token Verification (Asymmetric Ed25519) | ✔ | ✔ |
| | Dynamic Parameter Lockdown (Argument assertion) | ✔ | ✔ |
| | **Semantic Prompt Hash Integrity Validation** (Anti-Hijack) | ✔ | ✔ |
| | Dynamic Logical Channel Isolation (Network masking) | ✔ | ✔ |
| **Search & Discovery** | Dense FAISS Vector Search Engine | ✔ | ✔ |
| | Local/Mock Embedder Drivers | ✔ | ✔ |
| | Cloud/OpenAI Embedder Drivers | ✔ | ✔ |
| **Observability (UI)** | **Real-time Observability Hub Console** | ❌ | **✔ (Interactive Dashboard)** |
| | Visual Topology Mapping (Live node flow diagrams) | ❌ | ✔ |
| | Telemetry Analyzer (Latencies & Node response mapping) | ❌ | ✔ |
| **Compliance & SIEM** | **Audit Trail Logging Engine** (SOC2 / ISO 27001 export) | ❌ | ✔ |
| | Native SIEM Integration (Datadog, Splunk, Elastic) | ❌ | ✔ |
| | Centralized Logical Channel Mapping and Role Audits | ❌ | ✔ |
| **Support & Operations** | Production SLAs & 24/7 Priority Support | ❌ | ✔ |
| | Commercial Use Exemption (Closed-Source distribution) | ❌ | ✔ |

---

## Enterprise Feature Highlights

### 1. Real-time Observability Hub Console
A premium, interactive web interface designed for operational monitoring of the agent network.
*   **Live Network Topology:** Real-time visual tracking of active agents and tools, demonstrating dynamic channel boundaries.
*   **Call Execution Inspection:** Deep-dive inspecting of JSON-RPC transaction payloads, routing decisions, and dynamic DET token issuances.

### 2. Audit Trail Logging Engine (SOC2/ISO 27001)
Highly regulated industries require strict historical records of all agent operations.
*   **Immutability Logging:** Export-ready transactional logs detailing who authorized what action (DET token payload mapping) and with what exact parameters.
*   **SIEM Connectors:** Native forwarding of security logs to Datadog, Splunk, or AWS CloudWatch for anomaly detection and corporate audits.

### 3. Telemetry Analyzer
Detailed analytics for cost and performance management in multi-agent environments.
*   **Cost Attribution:** Real-time tracking of token usage and LLM API costs mapped directly per node and transaction.
*   **Latency Breakdown:** Segmented monitoring of network latency vs. LLM inference time (TTFT) to detect bottlenecks in P2P execution paths.
