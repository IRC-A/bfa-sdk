# AGENTS.md — Backend for Agents SDK (BFA) & IRC-A Protocol

> This file is intended for AI coding agents. It summarises the project structure, conventions, build/test workflow, and security model. The codebase is written in English, so this file is in English. User-facing documentation is also available in Spanish (`README.es.md`) and Portuguese (`README.pt.md`).

---

## 1. Project Overview

This repository implements the **Backend for Agents (BFA)** architectural pattern and the **IRC-A (Internet Relay Chat for Agents)** protocol. It is a Python SDK plus reference implementations that turn a central gateway into a semantic registry and broker for autonomous agents and tool servers.

The core idea is:
- The **BFA Gateway** does **not** run business logic or hold database connections.
- It maintains a dense **FAISS vector index** of agent/tool metadata (descriptions, tags, examples) so that a natural-language query can be resolved to the right capability.
- Once a capability is matched, the Gateway mints a short-lived cryptographically signed **Delegated Execution Token (DET)** and returns the target URL. The caller then invokes the target **peer-to-peer** (A2A or FastMCP), avoiding gateway bottlenecks.

The project is dual-licensed: **AGPLv3** for the Community Edition and a **Commercial Proprietary License** for the Enterprise Edition. All security features (PASETO DET, Ed25519 handshakes, channel masking, parameter lockdown, prompt-hash integrity) are present in the community edition.

### Technology Stack

| Layer | Technology |
|-------|------------|
| Language | Python 3.12+ (3.13 works for tests with the mock embedder) |
| Gateway / API | FastAPI + Uvicorn |
| Agent server | `a2a-sdk` on Starlette |
| Tool server | `fastmcp` wrapped by `BFAMCP` |
| Semantic search | FAISS (`faiss-cpu`) + NumPy |
| Embeddings | `sentence-transformers` (local), OpenAI `text-embedding-3-small` (cloud), or a deterministic `DummyEmbedder` (offline mock) |
| Crypto | `cryptography` (Ed25519), custom PASETO v4.public implementation in `bfa_sdk/core/paseto.py` |
| Optional serverless | `mangum` (AWS Lambda ASGI adapter) |
| Config / env | `python-dotenv`, `pyyaml` |
| Package | `setuptools` via `pyproject.toml`; package name `bfa-irc-a-sdk` |
| Frontend | React 18 + Tailwind + `react-router-dom` + `@ag-ui/client` (`examples/frontend/`) |
| n8n integration | TypeScript package `n8n-nodes-bfa` with enterprise license check |
| Infrastructure (example) | Terraform for Google Cloud Run (`terraform/`) |

---

## 2. Repository Layout

```text
bfa_sdk/                    # Core SDK (must stay business-logic-free)
  __init__.py               # Public exports: BFAAgent, BFAInteractiveAgent, BFAMCP,
                            # create_gateway_app, BFASemanticRouter
  config.py                 # BFAConfig: env/yaml-based configuration
  core/
    gateway.py              # FastAPI app factory, discovery, registration, DET minting
    agent.py                # BFAAgent base class, A2A server, DET middleware
    interactive_agent.py    # BFAInteractiveAgent + MemoryStack for coordinator agents
    mcp.py                  # BFAMCP wrapper around FastMCP
    paseto.py               # PASETO v4.public sign/verify with Ed25519
  router/
    search.py               # BFASemanticRouter (FAISS index + resolve)
    embedder.py             # AbstractEmbedder, LocalEmbedder, OpenAIEmbedder, DummyEmbedder

examples/                   # Reference implementations and demos
  mock_mdbank_mcp.py        # Mock MCP server with 4 banking tools
  mock_cuentas_agent.py     # Mock A2A agent (accounts) with optional OpenAI LLM
  mock_tarjetas_agent.py    # Mock A2A agent (credit cards) with optional OpenAI LLM
  mock_clima_agent.py       # Mock A2A agent (weather)
  mock_interactive_agent.py # Frontend/coordinator chatbot agent
  run_demo.py               # Self-contained demo: starts gateway + mocks + runs queries
  run_local_servers.py      # Starts gateway + mocks and keeps them alive for frontend dev
  frontend/                 # React dashboard (npm-based)

poc/                        # Early proof-of-concept scripts (not the main SDK)
  agent.py, gateway.py, mcp_server.py, run_poc.py
  content_generator/        # Content-generation PoC agents

n8n-nodes-bfa/              # Enterprise n8n community nodes (TypeScript)
  nodes/BfaAgent/           # BFA Agent node
  nodes/BfaMcp/             # BFA MCP node
  nodes/IrcaGateway/        # IRC-A Gateway node
  nodes/BfaEntryPointAgent/ # Entry-point agent node
  credentials/              # BFA credentials
  package.json, gulpfile.js, index.ts

terraform/                  # Example GCP Cloud Run deployment
  main.tf, variables.tf, outputs.tf, terraform.tfvars

tests/                      # Pytest suite
  conftest.py               # Autouse fixture that clears global ROUTER registry
  test_config.py            # BFAConfig env/file loading
  test_core_wrappers.py     # BFAAgent, BFAMCP, registration fallbacks
  test_embedder.py          # Dummy, OpenAI, Local embedders
  test_gateway.py           # Gateway endpoints, dynamic registration, invoke
  test_interactive_agent.py # MemoryStack and BFAInteractiveAgent
  test_router.py            # FAISS semantic routing
  test_irca_security.py     # Handshake, DET, channel masking, prompt-hash integrity

pyproject.toml              # Package metadata, dependencies, CLI entrypoint
requirements.txt            # CI/development dependencies (includes pytest, pytest-cov)
README.md / README.es.md / README.pt.md   # Multilingual user docs
IRC-A_Whitepaper.md         # Full architecture specification
LICENSE / LICENSE_MATRIX.md # Dual licensing and feature matrix
CONTRIBUTING.md             # Contribution guidelines
.dockerignore / .gitignore  # Standard exclusions
```

---

## 3. Build & Test Commands

### Create a virtual environment and install the SDK

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install -e .
```

### Run the test suite

```bash
source .venv/bin/activate
pytest
```

With coverage:

```bash
pytest --cov=bfa_sdk --cov-report=term-missing
```

The current suite is 65 tests and passes in the bundled `.venv`.

### Start the gateway CLI

After installing the package, the entrypoint `irc-a-gateway` is available:

```bash
irc-a-gateway
```

It binds to `127.0.0.1:8000` by default (configurable via `BFA_GATEWAY_HOST` / `BFA_GATEWAY_PORT`).

### Run the reference demo locally

```bash
source .venv/bin/activate
python examples/run_demo.py
```

This starts the gateway, the mock MCP server, and three mock agents, then performs semantic resolution and dynamic invocation queries.

### Start the backend servers for frontend development

```bash
source .venv/bin/activate
python examples/run_local_servers.py
```

Then, in a separate terminal:

```bash
cd examples/frontend
npm install
npm start
```

The React app runs on `http://localhost:3000`.

### Docker

Individual mock components have Dockerfiles:

```text
Dockerfile.agent    # poc/agent.py (port 18001)
Dockerfile.cuentas  # examples/mock_cuentas_agent.py (port 8002)
Dockerfile.tarjetas # examples/mock_tarjetas_agent.py (port 8003)
Dockerfile.mdbank   # examples/mock_mdbank_mcp.py (port 8001)
Dockerfile.mcp      # poc/mcp_server.py (port 18002)
```

> **Note:** `docker-compose.yml` references a `Dockerfile.gateway` that does **not** currently exist in the repository. If you want to use Docker Compose, either create `Dockerfile.gateway` or update `docker-compose.yml` to point to one of the existing Dockerfiles or to a pre-built image.

---

## 4. Code Style Guidelines

The project follows these conventions, which are also summarised in `CONTRIBUTING.md`:

- **Python style:** PEP 8. Descriptive variable names, 4-space indentation, type hints where helpful.
- **File header:** Every core Python file starts with the copyright and dual-license comment:

  ```python
  # Copyright (c) 2026 Sandro G. All rights reserved.
  # Licensed under AGPLv3 / Commercial Dual License.
  ```

- **Language:** Source code comments and docstrings are in English. User-facing READMEs are translated to Spanish and Portuguese.
- **Core must stay generic:** Do not put business logic (banking, hotel, etc.) into `bfa_sdk/`. Business-specific code belongs in `examples/` or in downstream projects.
- **Use the abstractions:** New agents must inherit from `BFAAgent` (or `BFAInteractiveAgent` for coordinators). New tool servers must use `BFAMCP`. This ensures automatic A2A/FastMCP compatibility, metadata extraction, and security middleware.
- **Serverless-friendly:** Keep the dependency footprint light. Heavy dependencies such as `sentence-transformers`/`torch` are optional (`pip install 'bfa-irc-a-sdk[local]'`).
- **Tests:** Add tests for new code, especially security-critical branches and edge cases. The existing tests use `pytest`, `unittest.mock`, and FastAPI/Starlette `TestClient`.

---

## 5. Architecture & Module Divisions

### 5.1 BFA Gateway (`bfa_sdk/core/gateway.py`)

- `create_gateway_app()` builds the FastAPI application.
- On startup it initialises an embedder and a `BFASemanticRouter`, then discovers static endpoints (from env/file) and persisted endpoints (from `bfa_registry_db.json` or DynamoDB).
- Key endpoints:
  - `GET /` — health + registry sizes
  - `GET /skills` — all registered capabilities
  - `GET /resolve[/{agents,tools}]` — semantic search with optional type filter
  - `POST /register/{agent,mcp}` — dynamic registration of an agent or MCP server
  - `POST /register/init` + `POST /register/verify` — Ed25519 challenge-response handshake
  - `POST /register/disconnect` — remove a node and rebuild the FAISS index
  - `POST /discover` — authenticated semantic discovery that mints an ephemeral DET
  - `POST /mint` — admin endpoint to manually mint a DET
  - `POST /invoke` — semantic routing + forwarding an A2A JSON-RPC request to the best agent
  - `GET /public_key` — Gateway public Ed25519 key
  - `GET /logs` — system trace log buffer
- Storage backends: local JSON (`BFA_REGISTRY_DB_PATH`) or DynamoDB with optimistic locking (`BFA_DYNAMODB_TABLE`).

### 5.2 Semantic Router (`bfa_sdk/router/`)

- `BFASemanticRouter` indexes capability metadata (name, description, tags, examples) in a FAISS `IndexFlatL2` and converts L2 distance to a 0–1 confidence score.
- `AbstractEmbedder` / `LocalEmbedder` / `OpenAIEmbedder` / `DummyEmbedder` provide three embedding modes.
- The router supports filtering by capability type (`agent` or `tool`) and logical channel overlap (`agent_channels`).

### 5.3 Agents (`bfa_sdk/core/agent.py`)

- `BFAAgent` is an abstract base class. Subclasses implement `async run(user_message, context) -> str`.
- It automatically creates an A2A agent card, an A2A Starlette server, and middleware that validates incoming DETs.
- `BFAInteractiveAgent` (`bfa_sdk/core/interactive_agent.py`) adds a per-session `MemoryStack` and a `delegate_task(query)` helper that forwards a simplified query to the Gateway, preventing full chat history from being sent across the network.

### 5.4 MCP Tool Servers (`bfa_sdk/core/mcp.py`)

- `BFAMCP` wraps `FastMCP`. It exposes:
  - `GET /tools` — standard metadata endpoint with tags/examples for semantic indexing
  - `POST /tools` — direct P2P tool invocation
- `@mcp_server.tool(...)` decorator stores tags/examples and optionally injects offline DET validation if the function signature includes `delegated_token`.

### 5.5 Security Tokens (`bfa_sdk/core/paseto.py`)

- Pure-Python implementation of PASETO `v4.public` signing/verification using Ed25519. Used for both session tokens and DETs.

### 5.6 Configuration (`bfa_sdk/config.py`)

- `BFAConfig` reads from a YAML file or environment variables:
  - `BFA_AGENT_ENDPOINTS` — comma-separated static A2A agent URLs
  - `BFA_MCP_ENDPOINTS` — comma-separated static MCP server URLs
  - `BFA_EMBEDDING_MODEL` — default `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`
  - `BFA_USE_MOCK_EMBEDDINGS=true` — offline hash-based embedder
  - `BFA_USE_OPENAI_EMBEDDINGS=true` + `OPENAI_API_KEY` — cloud embedder
  - `OPENAI_API_KEY` — also used by example LLM agents and can auto-enable OpenAI embeddings in the CLI

---

## 6. Testing Strategy

- Framework: **pytest**.
- Async tests use `pytest.mark.anyio` (the `anyio` pytest plugin is pulled in by the test dependencies).
- `tests/conftest.py` contains an `autouse` fixture that clears the global `ROUTER` registry and index before/after every test to avoid cross-test pollution.
- `tests/test_gateway.py` uses `fastapi.testclient.TestClient` and extensive mocking of `A2ACardResolver`, `httpx`, and discovery functions.
- `tests/test_irca_security.py` exercises the full handshake, DET verification, channel masking, recursive-loop middleware, and prompt-hash integrity.
- Tests are run by the CI workflow on every push/PR to `main` (Python 3.12).

---

## 7. Security Considerations

Security is central to the design. When modifying code, preserve and test the following mechanisms:

### 7.1 Asymmetric Registration Handshake
- `BFAAgent` and `BFAMCP` nodes register with `POST /register/init` and `POST /register/verify`.
- The Gateway sends a random challenge; the node signs it with its Ed25519 private key; the Gateway verifies it against the submitted public key.
- If the Gateway does not implement the handshake, nodes fall back to simple HTTP registration for compatibility.

### 7.2 Delegated Execution Tokens (DET)
- DETs are PASETO `v4.public` tokens signed by the Gateway's Ed25519 private key.
- They contain `sub`, `aud`, `permitted_action`, `restricted_params`, `exp`, `iat`, `jti`, and optionally `expected_prompt_hash`.
- Receiving agents/MCP servers verify the Gateway's signature **offline** using the Gateway public key; they do not need to call the Gateway for every request.

### 7.3 Offline Verification Checks (`verify_incoming_det`)
- Ed25519 signature validation
- Expiry (`exp`) with a 5-second clock-skew tolerance
- Replay-attack prevention via a JTI cache (`ReplayPreventionCache`)
- Audience (`aud`) and scope (`permitted_action`) validation
- Parameter lockdown: every key/value in `restricted_params` must exactly match the runtime arguments
- Prompt-hash integrity: if the token carries `expected_prompt_hash`, the local `prompt_hash` (SHA-256 of the system prompt template) must match — this mitigates prompt-hijacking

### 7.4 Logical Channel Masking
- Nodes belong to channels (`IRCA_CHANNELS` env variable, e.g. `#public,#finance`).
- The Gateway filters semantic search results so a caller only sees capabilities whose channel list overlaps with its own channels.
- This provides network-level segregation of the capability search space.

### 7.5 Recursive Loop Mitigation
- The `IRCAHeaderTracingMiddleware` tracks `x-trace-id` and `x-visited-nodes` headers.
- If an agent sees its own `agent_id` in the visited list, it returns HTTP 409 with an `IRC-A Circular Loop Detected` error.

### 7.6 Operational Security Notes
- The Gateway does **not** currently enforce TLS. In production, terminate TLS at the reverse proxy or load balancer.
- Store private keys and API keys (OpenAI, etc.) in environment variables or a secrets manager, never in code.
- The default CORS middleware in the Gateway allows all origins (`allow_origins=["*"]`). Harden this before exposing to the public internet.
- `bfa_registry_db.json` is a local plaintext registry. Use `BFA_DYNAMODB_TABLE` for production persistence.

---

## 8. Deployment Options

### 8.1 Local / Development
- `pip install -e .` and `irc-a-gateway` for the Gateway.
- `python examples/run_local_servers.py` for the full backend stack.
- `npm install && npm start` inside `examples/frontend` for the React dashboard.

### 8.2 Docker / Containers
- Individual mock services can be built with the provided Dockerfiles.
- The missing `Dockerfile.gateway` needs to be added before `docker-compose up --build -d` works as documented.

### 8.3 Serverless (AWS Lambda)
- `bfa_sdk/core/gateway.py` creates a `Mangum` handler if `mangum` is installed.
- Set `BFA_USE_OPENAI_EMBEDDINGS=true` and `OPENAI_API_KEY` so no heavy local model is loaded in the Lambda environment.

### 8.4 Google Cloud Run (Terraform example)
- `terraform/main.tf` defines Cloud Run services for the Gateway, Chat UI, Cuentas agent, Tarjetas agent, and MDBank MCP.
- Variables are in `terraform/variables.tf` / `terraform.tfvars`; the Gateway image is set via `var.gateway_image`, etc.
- The Gateway is exposed with `allUsers` invoker permission; secure it with IAM and TLS in real deployments.

### 8.5 n8n Enterprise Nodes
- `n8n-nodes-bfa` is a separate TypeScript package.
- Build with `npm install && npm run build`.
- It includes a license-key check (`BFA-ENTERPRISE-DEV-KEY-2026` is the mock development key) and supports LangSmith tracing, primary/backup LLM providers, and direct BFA Gateway registration via webhooks.

---

## 9. Important Design Constraints

- **No document chunking in the Gateway.** The Gateway indexes short metadata cards only. RAG/chunking over large documents belongs inside individual A2A agents, not in the router.
- **Local embedder requires Python <= 3.12.** `sentence-transformers` depends on `torch`, which is not yet available for Python 3.13 at the time of writing. Use `DummyEmbedder` or `OpenAIEmbedder` on Python 3.13.
- **Core must remain business-agnostic.** Any banking/hotel/weather-specific code is in `examples/` or `poc/`.
- **Dual licensing.** Before distributing derivative work, check `LICENSE` and `LICENSE_MATRIX.md`. The Enterprise n8n nodes and certain observability features are commercial-only.

---

## 10. CI/CD

- `.github/workflows/ci.yml` runs on `push`/`pull_request` to `main`:
  - Sets up Python 3.12
  - Installs `requirements.txt`
  - Installs the package with `pip install -e .`
  - Runs `pytest`
- `.github/workflows/publish.yml` triggers on GitHub releases or tags `v*` and publishes the Python package to PyPI using trusted publishing (OIDC).

---

## 11. Quick Reference: Key Files to Read First

- `README.md` — end-user introduction and usage examples
- `IRC-A_Whitepaper.md` — full architectural rationale and protocol specification
- `bfa_sdk/core/gateway.py` — Gateway implementation and API surface
- `bfa_sdk/core/agent.py` — `BFAAgent` base class and security middleware
- `bfa_sdk/core/mcp.py` — `BFAMCP` wrapper
- `bfa_sdk/router/search.py` — FAISS semantic router
- `bfa_sdk/router/embedder.py` — embedder implementations
- `bfa_sdk/core/paseto.py` — token cryptography
- `tests/test_irca_security.py` — comprehensive security scenarios
- `CONTRIBUTING.md` — contribution rules and style expectations

---

## 12. Quickstart & Implementation Guide (For Humans and AIs)

This section provides clear instructions and code templates to implement Gateway, A2A Agents, and MCP tool servers using the BFA-SDK.

### 1. Architectural Roles Summary
- **Gateway (`create_gateway_app`)**: Acts as a lightweight capability directory, broker, and token minter (PASETO v4.public).
- **Agent Node (`BFAAgent`)**: Represents a cognitive reasoning node. It auto-registers with the Gateway, runs an A2A server, and verifies incoming DET tokens before executing core logic.
- **Interactive Agent (`BFAInteractiveAgent`)**: An agent with built-in session memory (`MemoryStack`) that tracks execution traces (which sub-agents were called) and allows delegating simplified queries to other agents via `delegate_task(query)`.
- **Tool Server (`BFAMCP`)**: Wraps FastMCP. Exposes endpoints to index tools semantically, receives P2P requests, and validates parameters offline using the Gateway's public key.

---

### 2. Implementation Blueprints

#### Blueprint A: Standard Cognitive Agent (A2A)
To implement a standard cognitive agent, subclass `BFAAgent` and define the `async run` method:

```python
import uvicorn
from bfa_sdk.core.agent import BFAAgent
from a2a.server.agent_execution.context import RequestContext

class SupportAgent(BFAAgent):
    def __init__(self):
        super().__init__(
            agent_id="support_agent",
            name="Customer Support Agent",
            description="Handles general support queries and redirects complex issues.",
            tags=["support", "help", "general"],
            examples=["help me with my account", "how do I reset my password?"],
            url="http://127.0.0.1:8002",
            gateway_url="http://127.0.0.1:8000"
        )

    async def run(self, user_message: str, context: RequestContext) -> str:
        # Business logic goes here (e.g., call LLM, query static context)
        return f"Support Agent response to: '{user_message}'"

if __name__ == "__main__":
    agent = SupportAgent()
    uvicorn.run(agent.app, host="127.0.0.1", port=8002)
```

#### Blueprint B: Interactive Agent with Execution Tracing Memory
For conversational agents that coordinate multiple sub-agents, subclass `BFAInteractiveAgent`:

```python
import uvicorn
from bfa_sdk.core.interactive_agent import BFAInteractiveAgent
from a2a.server.agent_execution.context import RequestContext

class CoordinatorAgent(BFAInteractiveAgent):
    def __init__(self):
        super().__init__(
            agent_id="coordinator_agent",
            name="Main Coordinator",
            description="Coordinates specialized sub-agents to resolve complex user requests.",
            tags=["coordinate", "orchestrate"],
            examples=["process application"],
            url="http://127.0.0.1:8005",
            gateway_url="http://127.0.0.1:8000"
        )

    async def run(self, user_message: str, context: RequestContext) -> str:
        # Retrieve session context ID
        session_id = context.get_context_id() or "default-session"
        
        # 1. Store interaction in the execution memory stack
        stack = self.get_stack(session_id)
        stack.push(user_message, caller_node="user")
        
        # 2. Delegate a sub-task semantically to another agent
        # delegate_task performs query rewriting and requests a DET from the Gateway
        response = await self.delegate_task("verify compliance for user account", session_id)
        
        # 3. Clean up stack after delegation
        stack.pop()
        
        return f"Coordinator completed step. Sub-agent response: {response}"

if __name__ == "__main__":
    agent = CoordinatorAgent()
    uvicorn.run(agent.app, host="127.0.0.1", port=8005)
```

#### Blueprint C: Tool Server (MCP)
To expose tools and register them dynamically:

```python
import uvicorn
import asyncio
import threading
from bfa_sdk.core.mcp import BFAMCP

mcp = BFAMCP("Database Tools")

# Define tools using the @mcp.tool decorator, declaring tags and examples for semantic indexing
@mcp.tool(
    name="get_user_profile",
    description="Fetches a user profile from the database.",
    tags=["profile", "database", "user_id"],
    examples=["fetch profile for user 123", "who is user 456?"]
)
async def get_user_profile(user_id: str) -> dict:
    return {"user_id": user_id, "name": "John Doe", "status": "Active"}

# Dynamically auto-register with the Gateway in the background after startup
async def register():
    await asyncio.sleep(1) # wait for local server to start
    await mcp.register_with_gateway(
        gateway_url="http://127.0.0.1:8000",
        my_url="http://127.0.0.1:8003"
    )

threading.Thread(target=lambda: asyncio.run(register()), daemon=True).start()

if __name__ == "__main__":
    uvicorn.run(mcp.app, host="127.0.0.1", port=8003)
```

---

### 3. Understanding the Security Lifecycle
1. **Asymmetric Handshake**: On startup, the `BFAAgent` or `BFAMCP` performs a challenge-response handshake with `/register/init` and `/register/verify` using its Ed25519 key, obtaining an ephemeral session token.
2. **Dynamic Discovery**: When a caller queries `/discover`, the Gateway resolves the match using the FAISS index, verifies logical channels, and signs an **Ephemeral Delegated Execution Token (DET)** containing audience and parameter lockdowns (`restricted_params`).
3. **P2P Verification**: The receiver node intercepts incoming requests via middleware, runs `verify_incoming_det(...)` offline using the Gateway's public key, and locks parameters/prompt-hash constraints before execution.

