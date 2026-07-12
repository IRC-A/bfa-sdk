# Multi-Agent Content Generation POC

This folder contains a Proof of Concept (POC) demonstrating the **BFA / IRC-A Security protocol** applied to a **Multi-Agent Content Generation flow**. It adapts prompt structures from the `/Users/sandrogarcia/Documents/GitHub/content-generator-multi-agent` repository, using **Model-Context Protocol (MCP)** tools to securely manage keywords and prevent duplication.

---

## 🏗️ Architecture

```mermaid
graph TD
    Client["run_content_poc.py (Simulated Client)"] -->|1. Request Essay| Writer["poc/content_generator/writer_agent.py :8101"]
    Writer -->|2. Asymmetric handshake / Registration| Gateway["poc/gateway.py (BFA Gateway) :8000"]
    Writer -->|3. Request Credentials for campaign 'camp-123'| Gateway
    Gateway -->|4. Resolve & Mint DET| Writer
    Writer -->|5. P2P call get_used_keywords| KeywordsMCP["poc/content_generator/keywords_mcp.py :8102"]
    KeywordsMCP -->|6. Offline DET Verification & Lockdown| KeywordsMCP
    KeywordsMCP -->|7. Used keywords list| Writer
    Writer -->|8. Forward draft for audit (A2A)| Reviewer["poc/content_generator/reviewer_agent.py :8103"]
    Reviewer -->|9. Audit & Critique / Approval| Writer
    Writer -->|10. Refined essay output| Client
```

---

## 🎯 Verification Flows

### Flow 1: Dynamic Handshake & Registration
- Verifies that all agents and MCP servers execute asymmetric RSA challenge-response handshakes with the gateway on startup.

### Flow 2: Secure P2P Keyword Audit
- The `WriterAgent` queries `KeywordsMCP` directly using a BFA-minted Delegated Execution Token (DET).
- The MCP validates the token signature offline and returns keywords used by campaign `"camp-123"` (e.g. `["artificial-intelligence", "agents"]`).
- The `WriterAgent` produces a plan and draft that strictly avoids repeating these keywords.

### Flow 3: Parameter Lockdown Block (Zero-Trust Validation)
- Simulates an attack: The `WriterAgent` attempts to query used keywords for a competitor campaign (`"camp-999"`) using the DET minted for `"camp-123"`.
- The `KeywordsMCP` server detects that the runtime parameter `campaign_id="camp-999"` does not match the token's locked-down constraint (`"camp-123"`) and rejects the request.

### Flow 4: Loop Interception
- Demonstrates BFA's `X-Visited-Nodes` trace validation, terminating infinite loops if two agents start communicating in circles (Writer -> Reviewer -> Writer).

### Flow 5: End-to-End A2A Generation
- Executes the full agent-to-agent writing cycle, producing a plan, a draft, a critique, a revised draft, and a final essay.

---

## 🚀 How to Run

Execute the runner script:

```bash
.venv/bin/python poc/content_generator/run_content_poc.py
```
