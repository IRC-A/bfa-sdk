# Copyright (c) 2026 Sandro G. All rights reserved.
# Licensed under AGPLv3 / Commercial Dual License.
from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from contextlib import asynccontextmanager
import httpx
import asyncio
import json
import os
import time
import secrets
import jwt
from typing import Dict, Any, List, Optional
from a2a.client import A2ACardResolver
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization
from cryptography.exceptions import InvalidSignature

from bfa_sdk.config import BFAConfig
from bfa_sdk.router.embedder import LocalEmbedder, DummyEmbedder, OpenAIEmbedder
from bfa_sdk.router.search import BFASemanticRouter
from bfa_sdk.core.paseto import sign_paseto_v4_public, verify_paseto_v4_public

# Global application dependencies
CONFIG = BFAConfig()
EMBEDDER = None
ROUTER = None

# Global system trace logs
SYSTEM_LOGS: List[Dict[str, Any]] = []

# Global in-memory Langsmith token usage accumulator
AGGREGATED_TOKENS = {
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0
}

def add_system_log(event_type: str, source: str, message: str, details: Any = None):
    import time
    log_entry = {
        "timestamp": time.strftime("%H:%M:%S"),
        "event_type": event_type, # "REGISTRATION", "DISCOVERY", "EXECUTION", "SYSTEM", "ERROR"
        "source": source,
        "message": message,
        "details": details
    }
    SYSTEM_LOGS.append(log_entry)
    if len(SYSTEM_LOGS) > 200:
        SYSTEM_LOGS.pop(0)

# Configurable parameter extractors to map natural language query patterns to DET parameters.
# In a production environment, this can be customized in BFAConfig or loaded dynamically.
DYNAMIC_PARAMETER_EXTRACTORS: Dict[str, str] = {
    "customer_id": r"customer\s+(?:id-)?(\w+)",
    "campaign_id": r"campaign\s+(\S+)"
}

REGISTRY_DB_PATH = os.getenv("BFA_REGISTRY_DB_PATH", "bfa_registry_db.json")

# Ephemeral keys generated on load (unless loaded from env/files)
GATEWAY_PRIVATE_KEY = ed25519.Ed25519PrivateKey.generate()
GATEWAY_PUBLIC_KEY = GATEWAY_PRIVATE_KEY.public_key()

# Memory databases for challenge-response handshake
CHALLENGES: Dict[str, str] = {} # node_id -> challenge_hex
REGISTERED_NODES: Dict[str, Dict[str, Any]] = {} # node_id -> {"public_key": ed25519_pubkey_obj, "channels": list}

class BFAStorageManager:
    """
    Manages persistence of registered endpoints.
    Supports standard local JSON files and DynamoDB-based storage with Optimistic Locking.
    """
    @staticmethod
    def load_registry() -> Dict[str, Any]:
        table_name = os.getenv("BFA_DYNAMODB_TABLE")
        if table_name:
            try:
                import boto3
                dynamodb = boto3.resource("dynamodb")
                table = dynamodb.Table(table_name)
                response = table.get_item(Key={"registry_id": "default"})
                item = response.get("Item")
                if item:
                    return {
                        "agent_endpoints": item.get("agent_endpoints", []),
                        "mcp_endpoints": item.get("mcp_endpoints", []),
                        "version": int(item.get("version", 1))
                    }
                return {"agent_endpoints": [], "mcp_endpoints": [], "version": 1}
            except Exception as e:
                print(f"BFAStorageManager: Error loading from DynamoDB: {e}")
                return {"agent_endpoints": [], "mcp_endpoints": [], "version": 1}
        else:
            if not os.path.exists(REGISTRY_DB_PATH):
                return {"agent_endpoints": [], "mcp_endpoints": [], "version": 1}
            try:
                with open(REGISTRY_DB_PATH, "r") as f:
                    data = json.load(f)
                    return {
                        "agent_endpoints": data.get("agent_endpoints", []),
                        "mcp_endpoints": data.get("mcp_endpoints", []),
                        "version": 1
                    }
            except Exception as e:
                print(f"BFAStorageManager: Error loading from local DB: {e}")
                return {"agent_endpoints": [], "mcp_endpoints": [], "version": 1}

    @staticmethod
    def save_registry(data: Dict[str, Any], max_retries: int = 5) -> bool:
        table_name = os.getenv("BFA_DYNAMODB_TABLE")
        if table_name:
            import boto3
            import time
            from botocore.exceptions import ClientError
            
            dynamodb = boto3.resource("dynamodb")
            table = dynamodb.Table(table_name)
            
            retries = 0
            backoff = 0.1
            
            while retries < max_retries:
                current_reg = BFAStorageManager.load_registry()
                current_version = current_reg.get("version", 1)
                
                updated_agent = list(set(current_reg["agent_endpoints"] + data.get("agent_endpoints", [])))
                updated_mcp = list(set(current_reg["mcp_endpoints"] + data.get("mcp_endpoints", [])))
                
                try:
                    table.put_item(
                        Item={
                            "registry_id": "default",
                            "agent_endpoints": updated_agent,
                            "mcp_endpoints": updated_mcp,
                            "version": current_version + 1
                        },
                        ConditionExpression="attribute_not_exists(version) OR version = :ver",
                        ExpressionAttributeValues={":ver": current_version}
                    )
                    print(f"BFAStorageManager: Successfully saved to DynamoDB (v{current_version + 1}).")
                    return True
                except ClientError as e:
                    if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                        retries += 1
                        print(f"BFAStorageManager: Concurrency conflict detected. Retry {retries}/{max_retries}...")
                        time.sleep(backoff)
                        backoff *= 2
                    else:
                        print(f"BFAStorageManager: DynamoDB ClientError: {e}")
                        return False
                except Exception as e:
                    print(f"BFAStorageManager: DynamoDB Error: {e}")
                    return False
            print("BFAStorageManager Error: Failed to save registry to DynamoDB due to lock contention.")
            return False
        else:
            try:
                file_data = {
                    "agent_endpoints": data.get("agent_endpoints", []),
                    "mcp_endpoints": data.get("mcp_endpoints", [])
                }
                with open(REGISTRY_DB_PATH, "w") as f:
                    json.dump(file_data, f, indent=2)
                return True
            except Exception as e:
                print(f"BFAStorageManager: Error saving to local DB: {e}")
                return False

def load_persisted_endpoints() -> Dict[str, List[str]]:
    """
    Load persisted endpoints using BFAStorageManager.
    """
    reg = BFAStorageManager.load_registry()
    return {
        "agent_endpoints": reg["agent_endpoints"],
        "mcp_endpoints": reg["mcp_endpoints"]
    }

def persist_endpoint(type_: str, url: str):
    """
    Save a registered endpoint dynamically using BFAStorageManager.
    """
    reg = BFAStorageManager.load_registry()
    key = "agent_endpoints" if type_ == "agent" else "mcp_endpoints"
    if url not in reg[key]:
        reg[key].append(url)
        BFAStorageManager.save_registry(reg)


async def discover_agents(endpoints: List[str]) -> Dict[str, Any]:
    """
    Query A2A endpoints to obtain card and skill registrations.
    """
    registry = {}
    async with httpx.AsyncClient(timeout=30.0) as client:
        for url in endpoints:
            try:
                resolver = A2ACardResolver(
                    httpx_client=client,
                    base_url=url,
                )
                card = await resolver.get_agent_card()
                for skill in card.skills:
                    registry[str(skill.id)] = {
                        "name": str(skill.name),
                        "description": str(skill.description),
                        "url": url,
                        "tags": list(skill.tags),
                        "examples": list(skill.examples),
                        "type": "agent",
                    }
            except Exception as e:
                print(f"BFA Discovery: Error connecting to Agent at {url}: {e}")
    return registry


async def discover_tools(endpoints: List[str]) -> Dict[str, Any]:
    """
    Query MCP endpoints to extract metadata schemas.
    """
    registry = {}
    async with httpx.AsyncClient(timeout=30.0) as client:
        for url in endpoints:
            try:
                response = await client.get(f"{url}/tools")
                if response.status_code == 200:
                    tools = response.json()
                    for tool in tools:
                        tool_name = tool.get("name")
                        annotations = tool.get("annotations", {})
                        tags = annotations.get("tags", [])
                        examples = annotations.get("examples", [])
                        
                        registry[tool_name] = {
                            "type": "tool",
                            "server_url": url,
                            "name": tool_name,
                            "description": tool.get("description", ""),
                            "input_schema": tool.get("inputSchema", {}),
                            "tags": tags,
                            "examples": examples,
                        }
            except Exception as e:
                print(f"BFA Discovery: Error connecting to MCP server at {url}: {e}")
    return registry


async def prune_dead_endpoints():
    """
    Actively pings all registered endpoints. If an agent or MCP server is unreachable, connection refused,
    or timed out, automatically unregister it, purge it from FAISS, and persist the update.
    """
    if not ROUTER:
        return
        
    urls_to_check = set()
    for key, item in list(ROUTER.registry.items()):
        url = item.get("url") or item.get("server_url")
        if url:
            urls_to_check.add(url)
            
    for node_id, data in list(REGISTERED_NODES.items()):
        if data.get("url"):
            urls_to_check.add(data["url"])
            
    if not urls_to_check:
        return
        
    dead_urls = set()
    async with httpx.AsyncClient(timeout=2.0) as client:
        for url in urls_to_check:
            try:
                is_mcp = False
                for item in ROUTER.registry.values():
                    if item.get("server_url") == url or item.get("type") == "tool":
                        is_mcp = True
                        break
                
                if is_mcp:
                    res = await client.get(f"{url.rstrip('/')}/tools")
                else:
                    res = await client.get(f"{url.rstrip('/')}/.well-known/agent-card.json")
                    if res.status_code != 200:
                        res = await client.get(f"{url.rstrip('/')}/")
                        
                if res.status_code >= 500:
                    dead_urls.add(url)
            except Exception:
                dead_urls.add(url)
                
    if dead_urls:
        removed_count = 0
        for dead_url in dead_urls:
            keys_to_remove = []
            for k, item in list(ROUTER.registry.items()):
                if item.get("url") == dead_url or item.get("server_url") == dead_url:
                    keys_to_remove.append(k)
            for k in keys_to_remove:
                if k in ROUTER.registry:
                    del ROUTER.registry[k]
                    removed_count += 1
                    
            nodes_to_remove = [nid for nid, d in REGISTERED_NODES.items() if d.get("url") == dead_url]
            for nid in nodes_to_remove:
                del REGISTERED_NODES[nid]
                
            # Remove from persisted DB
            reg = BFAStorageManager.load_registry()
            reg["agent_endpoints"] = [u for u in reg.get("agent_endpoints", []) if u != dead_url]
            reg["mcp_endpoints"] = [u for u in reg.get("mcp_endpoints", []) if u != dead_url]
            BFAStorageManager.save_registry(reg)
            
            add_system_log("DISCOVERY", dead_url, f"Endpoint '{dead_url}' is dead/unreachable. Automatically unindexed from FAISS.")
            
        if removed_count > 0 and ROUTER:
            ROUTER.build_index()


async def health_monitor_loop():
    """Background task to continuously monitor registered nodes and prune dead ones."""
    while True:
        try:
            await asyncio.sleep(10)
            await prune_dead_endpoints()
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"BFA Health Monitor Error: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global EMBEDDER, ROUTER
    
    # Print loaded environment variables and credentials for debugging
    def mask(val: str) -> str:
        if not val:
            return "<NOT SET>"
        if len(val) <= 10:
            return val[:3] + "..." + val[-2:]
        return val[:7] + "..." + val[-6:]

    print("\n================================================================================")
    print("=== [BFA GATEWAY STARTUP - ENVIRONMENT & CREDENTIALS DIAGNOSTIC] ===")
    print(f"🔹 OPENAI_API_KEY        : {mask(os.getenv('OPENAI_API_KEY'))}")
    print(f"🔹 GOOGLE_API_KEY        : {mask(os.getenv('GOOGLE_API_KEY'))}")
    print(f"🔹 TAVILY_API_KEY        : {mask(os.getenv('TAVILY_API_KEY'))}")
    print(f"🔹 LANGSMITH_API_KEY     : {mask(os.getenv('LANGSMITH_API_KEY'))}")
    print(f"🔹 LLM_PROVIDER          : {os.getenv('LLM_PROVIDER', '<NOT SET>')}")
    print(f"🔹 BFA_USE_MOCK_EMBEDDINGS: {os.getenv('BFA_USE_MOCK_EMBEDDINGS', 'false')}")
    print(f"🔹 BFA_USE_OPENAI_EMBEDDINGS: {os.getenv('BFA_USE_OPENAI_EMBEDDINGS', 'false')}")
    print(f"🔹 BFA_REGISTRY_DB_PATH  : {os.getenv('BFA_REGISTRY_DB_PATH', 'bfa_registry_db.json')}")
    print("================================================================================\n")

    # Initialize embedding driver
    if CONFIG.use_mock_embeddings:
        print("IRC-A Gateway: Using DummyEmbedder for fast offline testing.")
        EMBEDDER = DummyEmbedder()
    elif CONFIG.use_openai_embeddings:
        print("IRC-A Gateway: Using cloud OpenAIEmbedder (perfect for serverless/Lambda).")
        EMBEDDER = OpenAIEmbedder(api_key=CONFIG.openai_api_key)
    else:
        try:
            print(f"IRC-A Gateway: Initializing local model '{CONFIG.embedding_model}'...")
            EMBEDDER = LocalEmbedder(CONFIG.embedding_model)
        except Exception as e:
            print(f"IRC-A Gateway Warning: Could not load local model: {e}. Falling back to DummyEmbedder.")
            EMBEDDER = DummyEmbedder()
            
    ROUTER = BFASemanticRouter(EMBEDDER)
    
    # Load dynamically registered endpoints from database
    persisted = load_persisted_endpoints()
    
    # Combine static config endpoints and runtime persisted endpoints
    all_agents = list(set(CONFIG.agent_endpoints + persisted["agent_endpoints"]))
    all_mcps = list(set(CONFIG.mcp_endpoints + persisted["mcp_endpoints"]))
    
    # Perform agent/tool discovery
    print("IRC-A Gateway: Starting network discovery...")
    agents = await discover_agents(all_agents)
    tools = await discover_tools(all_mcps)
    
    # Assign default '#public' channels to statically loaded endpoints
    for skill_id in agents:
        agents[skill_id]["channels"] = ["#public"]
    for tool_name in tools:
        tools[tool_name]["channels"] = ["#public"]
        
    ROUTER.update_registry(agents)
    ROUTER.update_registry(tools)
    ROUTER.build_index()
    
    print(f"IRC-A Gateway: Discovery completed. Indexed {len(agents)} agents and {len(tools)} tools.")
    
    # Start background health monitor loop
    monitor_task = asyncio.create_task(health_monitor_loop())
    try:
        yield
    finally:
        monitor_task.cancel()


def create_gateway_app(config: BFAConfig = None) -> FastAPI:
    """
    FastAPI app factory for the BFA Gateway Server.
    """
    global CONFIG
    if config:
        CONFIG = config
        
    app = FastAPI(lifespan=lifespan)
    
    from fastapi.middleware.cors import CORSMiddleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    @app.get("/skills")
    async def get_skills():
        await prune_dead_endpoints()
        registry = dict(ROUTER.registry) if ROUTER else {}
        for node_id, data in REGISTERED_NODES.items():
            found = False
            for k, item in registry.items():
                if item.get("node_id") == node_id or k == node_id:
                    found = True
                    break
            if not found:
                registry[node_id] = {
                    "name": node_id,
                    "description": f"Registered node on channels {', '.join(data.get('channels', []))}",
                    "url": data.get("url", f"http://{node_id}"),
                    "tags": data.get("channels", ["#public"]),
                    "examples": [],
                    "type": "agent",
                    "node_id": node_id
                }
        return registry

    @app.get("/resolve")
    def resolve(query: str, top_k: int = Query(3), threshold: Optional[float] = Query(None), exclude_node_id: Optional[str] = Query(None)):
        if not ROUTER:
            raise HTTPException(status_code=503, detail="Gateway not ready")
        eff_threshold = threshold if threshold is not None else CONFIG.semantic_threshold
        return ROUTER.resolve(query, top_k=top_k, threshold=eff_threshold, exclude_node_id=exclude_node_id)

    @app.get("/resolve/agents")
    def resolve_agents(query: str, top_k: int = Query(3), threshold: Optional[float] = Query(None), exclude_node_id: Optional[str] = Query(None)):
        if not ROUTER:
            raise HTTPException(status_code=503, detail="Gateway not ready")
        eff_threshold = threshold if threshold is not None else CONFIG.semantic_threshold
        return ROUTER.resolve(query, top_k=top_k, threshold=eff_threshold, filter_type="agent", exclude_node_id=exclude_node_id)

    @app.get("/resolve/tools")
    def resolve_tools(query: str, top_k: int = Query(3), threshold: Optional[float] = Query(None), exclude_node_id: Optional[str] = Query(None)):
        if not ROUTER:
            raise HTTPException(status_code=503, detail="Gateway not ready")
        eff_threshold = threshold if threshold is not None else CONFIG.semantic_threshold
        return ROUTER.resolve(query, top_k=top_k, threshold=eff_threshold, filter_type="tool", exclude_node_id=exclude_node_id)

    @app.get("/public_key")
    def get_public_key():
        pem = GATEWAY_PUBLIC_KEY.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )
        return {"public_key": pem.decode("utf-8")}

    @app.post("/report-tokens")
    async def report_tokens(payload: dict):
        """Allows active agents to report their LLM token usage for central dashboard tracking."""
        p = payload.get("prompt_tokens", 0)
        c = payload.get("completion_tokens", 0)
        AGGREGATED_TOKENS["prompt_tokens"] += p
        AGGREGATED_TOKENS["completion_tokens"] += c
        AGGREGATED_TOKENS["total_tokens"] += (p + c)
        return {"status": "success"}

    @app.get("/token-metrics")
    async def get_token_metrics():
        """Returns the aggregated token counts for visual playground cards."""
        return JSONResponse(AGGREGATED_TOKENS)

    @app.get("/gateway-logs")
    async def get_gateway_logs_api():
        """Returns the live trace logs for the dashboard panel."""
        return JSONResponse(SYSTEM_LOGS)

    @app.post("/gateway-logs")
    async def report_gateway_log(payload: dict):
        """Allows agents to report internal execution steps and conversational redirects."""
        add_system_log(
            event_type=payload.get("event_type", "EXECUTION"),
            source=payload.get("source", "Agent"),
            message=payload.get("message", ""),
            details=payload.get("details")
        )
        return {"status": "success"}

    @app.post("/gateway-logs/clear")
    async def clear_gateway_logs():
        """Clears all captured system trace logs."""
        SYSTEM_LOGS.clear()
        return {"status": "success"}

    @app.get("/logs")
    @app.get("/observability")
    async def gateway_observability(request: Request):
        accept = request.headers.get("accept", "")
        if "text/html" in accept:
            html_content = """
            <!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>IRC-A Gateway - Observability & Traces</title>
                <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;800&family=JetBrains+Mono:wght@400;700&display=swap" rel="stylesheet">
                <style>
                    :root {
                        --bg-color: #0b0f19;
                        --panel-bg: #111827;
                        --accent-blue: #3b82f6;
                        --accent-purple: #8b5cf6;
                        --accent-green: #10b981;
                        --accent-red: #ef4444;
                        --accent-amber: #f59e0b;
                        --border-color: #1f2937;
                        --text-color: #f3f4f6;
                        --text-muted: #9ca3af;
                    }
                    * {
                        box-sizing: border-box;
                        margin: 0;
                        padding: 0;
                    }
                    body {
                        font-family: 'Outfit', sans-serif;
                        background-color: var(--bg-color);
                        color: var(--text-color);
                        min-height: 100vh;
                        display: flex;
                        flex-direction: column;
                    }
                    header {
                        display: flex;
                        justify-content: space-between;
                        align-items: center;
                        padding: 16px 40px;
                        border-bottom: 1px solid var(--border-color);
                        background: rgba(17, 24, 39, 0.95);
                        backdrop-filter: blur(8px);
                    }
                    .logo-area h1 {
                        font-size: 1.4rem;
                        font-weight: 800;
                        color: #ffffff;
                    }
                    .logo-area p {
                        font-size: 0.75rem;
                        color: var(--text-muted);
                    }
                    .nav-tabs {
                        display: flex;
                        gap: 12px;
                    }
                    .nav-tab {
                        padding: 8px 16px;
                        border-radius: 8px;
                        font-size: 0.85rem;
                        font-weight: 600;
                        color: var(--text-muted);
                        text-decoration: none;
                        transition: all 0.2s;
                        border: 1px solid transparent;
                    }
                    .nav-tab:hover {
                        color: #ffffff;
                        background: #1f2937;
                    }
                    .nav-tab.active {
                        color: #ffffff;
                        background: var(--accent-blue);
                        border-color: var(--accent-blue);
                    }
                    .container {
                        padding: 30px 40px;
                        display: flex;
                        flex-direction: column;
                        gap: 24px;
                        flex-grow: 1;
                    }
                    .stats-bar {
                        display: grid;
                        grid-template-columns: repeat(4, 1fr);
                        gap: 16px;
                    }
                    .stat-card {
                        background: var(--panel-bg);
                        border: 1px solid var(--border-color);
                        border-radius: 12px;
                        padding: 16px 20px;
                        display: flex;
                        flex-direction: column;
                        gap: 4px;
                    }
                    .stat-value {
                        font-size: 1.6rem;
                        font-weight: 800;
                    }
                    .stat-title {
                        font-size: 0.7rem;
                        text-transform: uppercase;
                        color: var(--text-muted);
                        font-weight: 700;
                        letter-spacing: 0.5px;
                    }
                    .toolbar {
                        background: var(--panel-bg);
                        border: 1px solid var(--border-color);
                        border-radius: 12px;
                        padding: 16px 20px;
                        display: flex;
                        justify-content: space-between;
                        align-items: center;
                        gap: 16px;
                    }
                    .search-box {
                        display: flex;
                        gap: 12px;
                        flex-grow: 1;
                    }
                    .input-search {
                        background: #0b0f19;
                        border: 1px solid var(--border-color);
                        color: #ffffff;
                        padding: 8px 14px;
                        border-radius: 8px;
                        font-family: 'Outfit', sans-serif;
                        font-size: 0.85rem;
                        flex-grow: 1;
                        max-width: 400px;
                    }
                    .input-search:focus {
                        outline: none;
                        border-color: var(--accent-blue);
                    }
                    .select-filter {
                        background: #0b0f19;
                        border: 1px solid var(--border-color);
                        color: #ffffff;
                        padding: 8px 14px;
                        border-radius: 8px;
                        font-family: 'Outfit', sans-serif;
                        font-size: 0.85rem;
                        cursor: pointer;
                    }
                    .btn {
                        padding: 8px 16px;
                        border-radius: 8px;
                        font-size: 0.85rem;
                        font-weight: 600;
                        cursor: pointer;
                        border: 1px solid var(--border-color);
                        background: #1f2937;
                        color: #ffffff;
                        transition: background 0.2s;
                    }
                    .btn:hover {
                        background: #374151;
                    }
                    .btn-danger {
                        background: rgba(239, 68, 68, 0.15);
                        color: #fca5a5;
                        border-color: rgba(239, 68, 68, 0.3);
                    }
                    .btn-danger:hover {
                        background: rgba(239, 68, 68, 0.25);
                    }
                    .logs-table-container {
                        background: var(--panel-bg);
                        border: 1px solid var(--border-color);
                        border-radius: 12px;
                        overflow: hidden;
                        flex-grow: 1;
                        display: flex;
                        flex-direction: column;
                    }
                    table {
                        width: 100%;
                        border-collapse: collapse;
                        font-family: 'JetBrains Mono', monospace;
                        font-size: 0.75rem;
                    }
                    th {
                        background: #0f172a;
                        text-align: left;
                        padding: 12px 16px;
                        font-weight: bold;
                        color: var(--text-muted);
                        border-bottom: 1px solid var(--border-color);
                    }
                    td {
                        padding: 12px 16px;
                        border-bottom: 1px solid #1f2937;
                        vertical-align: top;
                    }
                    tr:hover td {
                        background: rgba(31, 41, 55, 0.5);
                    }
                    .badge {
                        font-size: 0.65rem;
                        font-weight: bold;
                        padding: 3px 8px;
                        border-radius: 9999px;
                        text-transform: uppercase;
                        display: inline-block;
                    }
                    .badge-REGISTRATION { background: rgba(192, 132, 252, 0.15); color: #c084fc; border: 1px solid rgba(192, 132, 252, 0.3); }
                    .badge-DISCOVERY { background: rgba(96, 165, 250, 0.15); color: #60a5fa; border: 1px solid rgba(96, 165, 250, 0.3); }
                    .badge-EXECUTION { background: rgba(52, 211, 153, 0.15); color: #34d399; border: 1px solid rgba(52, 211, 153, 0.3); }
                    .badge-ERROR { background: rgba(248, 113, 113, 0.15); color: #f87171; border: 1px solid rgba(248, 113, 113, 0.3); }
                    .badge-SYSTEM { background: rgba(245, 158, 11, 0.15); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.3); }

                    .details-pre {
                        background: #0b0f19;
                        border: 1px solid var(--border-color);
                        border-radius: 6px;
                        padding: 8px;
                        margin-top: 6px;
                        color: #a7f3d0;
                        font-size: 0.7rem;
                        white-space: pre-wrap;
                        max-height: 200px;
                        overflow-y: auto;
                    }
                </style>
            </head>
            <body>
                <header>
                    <div style="display: flex; align-items: center; gap: 24px;">
                        <div class="logo-area">
                            <h1>🔌 IRC-A Gateway</h1>
                            <p>Observability, Real-time Traces & Audit Logs</p>
                        </div>
                        <div class="nav-tabs">
                            <a href="/" class="nav-tab">🔌 Directory & Mesh</a>
                            <a href="/logs" class="nav-tab active">👁️ Observability & Traces</a>
                        </div>
                    </div>
                </header>

                <div class="container">
                    <!-- Stats Summary -->
                    <div class="stats-bar">
                        <div class="stat-card">
                            <div class="stat-value" id="stat-total" style="color: #ffffff;">0</div>
                            <div class="stat-title">Total Captured Traces</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-value" id="stat-execution" style="color: var(--accent-green);">0</div>
                            <div class="stat-title">Executions & P2P Redirects</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-value" id="stat-discovery" style="color: var(--accent-blue);">0</div>
                            <div class="stat-title">Semantic Discoveries</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-value" id="stat-errors" style="color: var(--accent-red);">0</div>
                            <div class="stat-title">Errors & Security Faults</div>
                        </div>
                    </div>

                    <!-- Toolbar -->
                    <div class="toolbar">
                        <div class="search-box">
                            <input type="text" id="search-input" class="input-search" placeholder="🔍 Search traces by node or message..." oninput="renderLogs()">
                            <select id="event-filter" class="select-filter" onchange="renderLogs()">
                                <option value="ALL">All Event Types</option>
                                <option value="EXECUTION">EXECUTION</option>
                                <option value="DISCOVERY">DISCOVERY</option>
                                <option value="REGISTRATION">REGISTRATION</option>
                                <option value="ERROR">ERROR</option>
                                <option value="SYSTEM">SYSTEM</option>
                            </select>
                        </div>
                        <div style="display: flex; gap: 8px;">
                            <button class="btn" id="btn-pause" onclick="togglePause()">⏸️ Pause Live</button>
                            <button class="btn btn-danger" onclick="clearLogs()">🗑️ Clear Logs</button>
                        </div>
                    </div>

                    <!-- Logs Table -->
                    <div class="logs-table-container">
                        <table>
                            <thead>
                                <tr>
                                    <th style="width: 100px;">Timestamp</th>
                                    <th style="width: 140px;">Event Type</th>
                                    <th style="width: 180px;">Source Node</th>
                                    <th>Message / Execution Trace</th>
                                </tr>
                            </thead>
                            <tbody id="logs-tbody">
                                <tr>
                                    <td colspan="4" style="text-align: center; color: var(--text-muted); padding: 40px;">No transaction logs recorded.</td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </div>

                <script>
                    let allLogs = [];
                    let isPaused = false;

                    async function fetchLogs() {
                        if (isPaused) return;
                        try {
                            const res = await fetch("/gateway-logs");
                            if (!res.ok) return;
                            allLogs = await res.json();
                            updateStats();
                            renderLogs();
                        } catch(e) {
                            console.error("Failed to fetch logs", e);
                        }
                    }

                    function updateStats() {
                        document.getElementById("stat-total").textContent = allLogs.length;
                        document.getElementById("stat-execution").textContent = allLogs.filter(l => l.event_type === "EXECUTION").length;
                        document.getElementById("stat-discovery").textContent = allLogs.filter(l => l.event_type === "DISCOVERY").length;
                        document.getElementById("stat-errors").textContent = allLogs.filter(l => l.event_type === "ERROR").length;
                    }

                    function renderLogs() {
                        const tbody = document.getElementById("logs-tbody");
                        const searchTerm = document.getElementById("search-input").value.toLowerCase();
                        const filterEvent = document.getElementById("event-filter").value;

                        const filtered = allLogs.filter(log => {
                            const matchesFilter = (filterEvent === "ALL" || log.event_type === filterEvent);
                            const matchesSearch = !searchTerm || 
                                (log.source && log.source.toLowerCase().includes(searchTerm)) || 
                                (log.message && log.message.toLowerCase().includes(searchTerm));
                            return matchesFilter && matchesSearch;
                        }).reverse();

                        if (filtered.length === 0) {
                            tbody.innerHTML = '<tr><td colspan="4" style="text-align: center; color: var(--text-muted); padding: 40px;">No matching logs found.</td></tr>';
                            return;
                        }

                        tbody.innerHTML = filtered.map((log) => {
                            let detailsHtml = '';
                            if (log.details) {
                                const detailsStr = typeof log.details === 'object' ? JSON.stringify(log.details, null, 2) : log.details;
                                detailsHtml = `<div class="details-pre">${detailsStr}</div>`;
                            }
                            
                            return `
                                <tr>
                                    <td style="color: #6b7280;">${log.timestamp || ''}</td>
                                    <td><span class="badge badge-${log.event_type || 'SYSTEM'}">${log.event_type || 'INFO'}</span></td>
                                    <td style="font-weight: 600; color: #9ca3af;">${log.source || 'Gateway'}</td>
                                    <td>
                                        <div style="color: #f3f4f6;">${log.message || ''}</div>
                                        ${detailsHtml}
                                    </td>
                                </tr>
                            `;
                        }).join('');
                    }

                    function togglePause() {
                        isPaused = !isPaused;
                        const btn = document.getElementById("btn-pause");
                        btn.textContent = isPaused ? "▶️ Resume Live" : "⏸️ Pause Live";
                        btn.style.background = isPaused ? "rgba(245, 158, 11, 0.2)" : "#1f2937";
                    }

                    async function clearLogs() {
                        if (!confirm("Are you sure you want to clear all system trace logs?")) return;
                        try {
                            await fetch("/gateway-logs/clear", { method: "POST" });
                            allLogs = [];
                            updateStats();
                            renderLogs();
                        } catch(e) {
                            console.error("Failed to clear logs", e);
                        }
                    }

                    setInterval(fetchLogs, 1000);
                    fetchLogs();
                </script>
            </body>
            </html>
            """
            return HTMLResponse(content=html_content)
        else:
            return JSONResponse(SYSTEM_LOGS)

    @app.get("/")
    async def gateway_root(request: Request):
        accept = request.headers.get("accept", "")
        if "text/html" in accept:
            html_content = """
            <!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>IRC-A Gateway</title>
                <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;800&family=JetBrains+Mono:wght@400;700&display=swap" rel="stylesheet">
                <style>
                    :root {
                        --bg-color: #0b0f19;
                        --panel-bg: #111827;
                        --accent-blue: #3b82f6;
                        --accent-purple: #8b5cf6;
                        --accent-green: #10b981;
                        --border-color: #1f2937;
                        --text-color: #f3f4f6;
                        --text-muted: #9ca3af;
                    }
                    * {
                        box-sizing: border-box;
                        margin: 0;
                        padding: 0;
                    }
                    body {
                        font-family: 'Outfit', sans-serif;
                        background-color: var(--bg-color);
                        color: var(--text-color);
                        min-height: 100vh;
                        display: flex;
                        flex-direction: column;
                    }
                    header {
                        display: flex;
                        justify-content: space-between;
                        align-items: center;
                        padding: 16px 40px;
                        border-bottom: 1px solid var(--border-color);
                        background: rgba(17, 24, 39, 0.95);
                        backdrop-filter: blur(8px);
                    }
                    .logo-area h1 {
                        font-size: 1.4rem;
                        font-weight: 800;
                        color: #ffffff;
                    }
                    .logo-area p {
                        font-size: 0.75rem;
                        color: var(--text-muted);
                    }
                    .nav-tabs {
                        display: flex;
                        gap: 12px;
                    }
                    .nav-tab {
                        padding: 8px 16px;
                        border-radius: 8px;
                        font-size: 0.85rem;
                        font-weight: 600;
                        color: var(--text-muted);
                        text-decoration: none;
                        transition: all 0.2s;
                        border: 1px solid transparent;
                    }
                    .nav-tab:hover {
                        color: #ffffff;
                        background: #1f2937;
                    }
                    .nav-tab.active {
                        color: #ffffff;
                        background: var(--accent-blue);
                        border-color: var(--accent-blue);
                    }
                    .btn-refresh {
                        background: #1f2937;
                        border: 1px solid var(--border-color);
                        color: #ffffff;
                        padding: 8px 16px;
                        border-radius: 8px;
                        font-size: 0.85rem;
                        cursor: pointer;
                        display: flex;
                        align-items: center;
                        gap: 8px;
                        transition: background 0.2s;
                    }
                    .btn-refresh:hover {
                        background: #374151;
                    }
                    .main-layout {
                        display: grid;
                        grid-template-columns: 1fr 450px;
                        flex-grow: 1;
                    }
                    .content-area {
                        padding: 30px 40px;
                        display: flex;
                        flex-direction: column;
                        gap: 30px;
                    }
                    .sidebar {
                        background: #0f172a;
                        border-left: 1px solid var(--border-color);
                        padding: 30px;
                        display: flex;
                        flex-direction: column;
                    }
                    .grid-top {
                        display: grid;
                        grid-template-columns: 1.5fr 1fr;
                        gap: 24px;
                    }
                    .card {
                        background: var(--panel-bg);
                        border: 1px solid var(--border-color);
                        border-radius: 16px;
                        padding: 24px;
                        box-shadow: 0 4px 20px rgba(0,0,0,0.3);
                    }
                    .card h2 {
                        font-size: 1.1rem;
                        font-weight: 600;
                        margin-bottom: 16px;
                        display: flex;
                        align-items: center;
                        gap: 8px;
                    }
                    .card-desc {
                        font-size: 0.8rem;
                        color: var(--text-muted);
                        line-height: 1.5;
                        margin-bottom: 16px;
                    }
                    .stats-grid {
                        display: grid;
                        grid-template-columns: 1fr 1fr;
                        gap: 16px;
                        margin-bottom: 16px;
                    }
                    .stat-box {
                        background: #0f172a;
                        border: 1px solid var(--border-color);
                        padding: 16px;
                        border-radius: 12px;
                        text-align: center;
                    }
                    .stat-num {
                        font-size: 1.75rem;
                        font-weight: 800;
                    }
                    .stat-label {
                        font-size: 0.65rem;
                        text-transform: uppercase;
                        color: var(--text-muted);
                        font-weight: bold;
                        margin-top: 4px;
                        letter-spacing: 0.5px;
                    }
                    .details-box {
                        background: #0f172a;
                        border: 1px solid var(--border-color);
                        border-radius: 12px;
                        padding: 12px;
                        font-size: 0.75rem;
                        color: var(--text-muted);
                        display: flex;
                        flex-direction: column;
                        gap: 8px;
                    }
                    .details-row {
                        display: flex;
                        justify-content: space-between;
                    }
                    .grid-bottom {
                        display: grid;
                        grid-template-columns: 1fr 1fr;
                        gap: 24px;
                    }
                    .column-title {
                        font-size: 1.1rem;
                        font-weight: 600;
                        margin-bottom: 16px;
                        display: flex;
                        align-items: center;
                        gap: 8px;
                    }
                    .nodes-list {
                        display: flex;
                        flex-direction: column;
                        gap: 16px;
                    }
                    .node-card {
                        background: var(--panel-bg);
                        border: 1px solid var(--border-color);
                        border-radius: 16px;
                        padding: 20px;
                        box-shadow: 0 2px 10px rgba(0,0,0,0.2);
                    }
                    .node-header {
                        display: flex;
                        justify-content: space-between;
                        align-items: center;
                        margin-bottom: 8px;
                    }
                    .node-name {
                        font-weight: bold;
                        font-size: 0.95rem;
                    }
                    .node-badge {
                        font-size: 0.65rem;
                        font-weight: bold;
                        padding: 2px 8px;
                        border-radius: 9999px;
                        text-transform: uppercase;
                    }
                    .badge-agent {
                        background: rgba(59, 130, 246, 0.15);
                        color: #93c5fd;
                        border: 1px solid rgba(59, 130, 246, 0.3);
                    }
                    .badge-tool {
                        background: rgba(139, 92, 246, 0.15);
                        color: #c084fc;
                        border: 1px solid rgba(139, 92, 246, 0.3);
                    }
                    .node-desc {
                        font-size: 0.75rem;
                        color: var(--text-muted);
                        line-height: 1.5;
                        margin-bottom: 12px;
                    }
                    .node-tags {
                        display: flex;
                        flex-wrap: wrap;
                        gap: 4px;
                        margin-bottom: 12px;
                    }
                    .node-tag {
                        font-size: 0.65rem;
                        background: #0f172a;
                        color: var(--text-muted);
                        padding: 2px 6px;
                        border-radius: 4px;
                    }
                    .node-footer {
                        font-size: 0.65rem;
                        color: #4b5563;
                        border-top: 1px solid #1f2937;
                        padding-top: 8px;
                        display: flex;
                        justify-content: space-between;
                    }
                    .node-footer span {
                        font-family: 'JetBrains Mono', monospace;
                        color: var(--text-muted);
                    }
                    .sidebar h2 {
                        font-size: 1rem;
                        font-weight: 600;
                        margin-bottom: 16px;
                        display: flex;
                        align-items: center;
                        gap: 8px;
                    }
                    .curl-cmd {
                        background: #0b0f19;
                        border: 1px solid var(--border-color);
                        padding: 10px;
                        border-radius: 8px;
                        font-family: 'JetBrains Mono', monospace;
                        font-size: 0.7rem;
                        color: #e5e7eb;
                        overflow-x: auto;
                        margin-top: 4px;
                        user-select: all;
                    }
                    .no-nodes {
                        text-align: center;
                        padding: 30px;
                        color: var(--text-muted);
                        font-size: 0.8rem;
                        border: 1px dashed var(--border-color);
                        border-radius: 12px;
                    }
                </style>
            </head>
            <body>
                <header>
                    <div style="display: flex; align-items: center; gap: 24px;">
                        <div class="logo-area">
                            <h1>🔌 IRC-A Gateway</h1>
                            <p>Real-time Semantic Router & Directory for Financial Agents and MCP Microservices.</p>
                        </div>
                        <div class="nav-tabs">
                            <a href="/" class="nav-tab active">🔌 Directory & Mesh</a>
                            <a href="/logs" class="nav-tab">👁️ Observability & Traces</a>
                        </div>
                    </div>
                    <button class="btn-refresh" onclick="updateRegistry()">
                        <span>🔄</span> Refresh Directory
                    </button>
                </header>

                <div class="main-layout">
                    <div class="content-area">
                        <!-- Top Section -->
                        <div class="grid-top">
                            <!-- Programmatic cURL Info -->
                            <div class="card">
                                <h2><span>💻</span> Programmatic Service Registry (cURL)</h2>
                                <p class="card-desc">To dynamically register a new agent or MCP server, send a POST request to the Gateway. Indexing in the FAISS semantic pool is executed instantly in hot-connect mode.</p>
                                
                                <div style="display: flex; flex-direction: column; gap: 12px;">
                                    <div>
                                        <span style="font-size: 0.7rem; font-weight: 600; color: var(--accent-blue);">Register an Agent (A2A):</span>
                                        <div class="curl-cmd">curl -X POST "http://127.0.0.1:8000/register/agent?url=http://127.0.0.1:8104&channels=%23content"</div>
                                    </div>
                                    <div>
                                        <span style="font-size: 0.7rem; font-weight: 600; color: var(--accent-purple);">Register an MCP Server:</span>
                                        <div class="curl-cmd">curl -X POST "http://127.0.0.1:8000/register/mcp?url=http://127.0.0.1:8102&channels=%23content"</div>
                                    </div>
                                </div>
                            </div>

                            <!-- Server Metrics -->
                            <div class="card">
                                <h2>📊 Server Metrics</h2>
                                <div class="stats-grid">
                                    <div class="stat-box">
                                        <div class="stat-num" id="stat-agents-count" style="color: var(--accent-blue);">0</div>
                                        <div class="stat-label">Active Agents</div>
                                    </div>
                                    <div class="stat-box">
                                        <div class="stat-num" id="stat-tools-count" style="color: var(--accent-purple);">0</div>
                                        <div class="stat-label">Indexed Tools</div>
                                    </div>
                                </div>
                                <div class="details-box">
                                    <div class="details-row">
                                        <span>Semantic Router:</span>
                                        <span style="color: var(--accent-green); font-weight: 600;">FAISS CPU</span>
                                    </div>
                                    <div class="details-row">
                                        <span>Node Status:</span>
                                        <span style="color: var(--accent-green); font-weight: 600;">ONLINE</span>
                                    </div>
                                </div>
                            </div>
                        </div>

                        <!-- Langsmith Token Metrics Row -->
                        <div class="card" style="background: rgba(59, 130, 246, 0.05); border: 1px solid rgba(59, 130, 246, 0.2);">
                            <h2 style="color: var(--accent-blue);">📊 Langsmith Token Metrics Tracker (Centralized)</h2>
                            <p class="card-desc">Monitors aggregate LLM prompt, completion, and total session tokens consumed across all P2P and A2A executions routed through the BFA network.</p>
                            <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; text-align: center; margin-top: 10px;">
                                <div style="background: #0f172a; padding: 15px; border-radius: 12px; border: 1px solid var(--border-color);">
                                    <div style="font-size: 0.75rem; color: var(--text-muted); text-transform: uppercase; font-weight: 600;">Prompt Tokens</div>
                                    <div id="metric-prompt" style="font-size: 1.8rem; font-weight: 800; color: var(--text-color); margin-top: 6px;">0</div>
                                </div>
                                <div style="background: #0f172a; padding: 15px; border-radius: 12px; border: 1px solid var(--border-color);">
                                    <div style="font-size: 0.75rem; color: var(--text-muted); text-transform: uppercase; font-weight: 600;">Completion Tokens</div>
                                    <div id="metric-completion" style="font-size: 1.8rem; font-weight: 800; color: var(--text-color); margin-top: 6px;">0</div>
                                </div>
                                <div style="background: #0f172a; padding: 15px; border-radius: 12px; border: 1px solid var(--border-color);">
                                    <div style="font-size: 0.75rem; color: var(--text-muted); text-transform: uppercase; font-weight: 600;">Total Tokens</div>
                                    <div id="metric-total" style="font-size: 1.8rem; font-weight: 800; color: var(--accent-purple); margin-top: 6px;">0</div>
                                </div>
                            </div>
                        </div>

                        <!-- Bottom Section: Lists -->
                        <div class="grid-bottom">
                            <!-- Connected Agents -->
                            <div>
                                <div class="column-title">🤖 Connected Agents (<span id="title-agents-count">0</span>)</div>
                                <div class="nodes-list" id="agents-list-container">
                                    <div class="no-nodes">No dynamic agents registered.</div>
                                </div>
                            </div>

                            <!-- Connected Tools -->
                            <div>
                                <div class="column-title">🛠️ Indexed MCP Tools (<span id="title-tools-count">0</span>)</div>
                                <div class="nodes-list" id="tools-list-container">
                                    <div class="no-nodes">No dynamic MCP servers registered.</div>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- Sidebar Live Transaction Logs -->
                    <div class="sidebar" style="width: 450px; display: flex; flex-direction: column;">
                        <h2>📜 Live Transaction Logs</h2>
                        <p style="font-size: 0.75rem; color: var(--text-muted); margin-bottom: 12px;">Trace of active requests, P2P redirects, registrations, and responses.</p>
                        <div id="logs-container" style="flex-grow: 1; overflow-y: auto; background: #0b0f19; border: 1px solid var(--border-color); border-radius: 12px; padding: 12px; display: flex; flex-direction: column; gap: 8px; font-family: 'JetBrains Mono', monospace; font-size: 0.7rem;">
                            <div style="color: var(--text-muted); text-align: center; padding-top: 20px;">No logs captured yet.</div>
                        </div>
                    </div>
                </div>

                <script>
                    async function updateTokenMetrics() {
                        try {
                            const res = await fetch("/token-metrics");
                            if (!res.ok) return;
                            const data = await res.json();
                            
                            document.getElementById("metric-prompt").textContent = data.prompt_tokens.toLocaleString();
                            document.getElementById("metric-completion").textContent = data.completion_tokens.toLocaleString();
                            document.getElementById("metric-total").textContent = data.total_tokens.toLocaleString();
                        } catch(e) {
                            console.error("Failed to fetch token metrics", e);
                        }
                    }

                    async function updateRegistry() {
                        try {
                            const res = await fetch("/skills");
                            if (!res.ok) return;
                            const skills = await res.json();
                            
                            const agentsContainer = document.getElementById("agents-list-container");
                            const toolsContainer = document.getElementById("tools-list-container");
                            
                            const items = Object.entries(skills);
                            const agents = items.filter(([_, item]) => item.type === "agent");
                            const tools = items.filter(([_, item]) => item.type === "tool");
                            
                            // Update counts
                            document.getElementById("stat-agents-count").textContent = agents.length;
                            document.getElementById("title-agents-count").textContent = agents.length;
                            document.getElementById("stat-tools-count").textContent = tools.length;
                            document.getElementById("title-tools-count").textContent = tools.length;
                            
                            // Render agents
                            if (agents.length === 0) {
                                agentsContainer.innerHTML = '<div class="no-nodes">No dynamic agents registered.</div>';
                            } else {
                                agentsContainer.innerHTML = agents.map(([id, item]) => `
                                    <div class="node-card">
                                        <div class="node-header">
                                            <div class="node-name">${item.name}</div>
                                            <span class="node-badge badge-agent">A2A Agent</span>
                                        </div>
                                        <div class="node-desc">${item.description || 'No description'}</div>
                                        <div class="node-tags">
                                            ${(item.tags || []).map(t => `<span class="node-tag">#${t}</span>`).join('')}
                                        </div>
                                        <div class="node-footer">
                                            ENDPOINT: <span>${item.url}</span>
                                        </div>
                                    </div>
                                `).join('');
                            }
                            
                            // Render tools
                            if (tools.length === 0) {
                                toolsContainer.innerHTML = '<div class="no-nodes">No dynamic MCP servers registered.</div>';
                            } else {
                                toolsContainer.innerHTML = tools.map(([name, item]) => `
                                    <div class="node-card">
                                        <div class="node-header">
                                            <div class="node-name" style="font-family: 'JetBrains Mono', monospace;">${name}</div>
                                            <span class="node-badge badge-tool">MCP Tool</span>
                                        </div>
                                        <div class="node-desc">${item.description || 'No description'}</div>
                                        <div class="node-tags">
                                            ${(item.tags || []).map(t => `<span class="node-tag">#${t}</span>`).join('')}
                                        </div>
                                        <div class="node-footer">
                                            MCP SERVER: <span>${item.url || item.server_url || ''}</span>
                                        </div>
                                    </div>
                                `).join('');
                            }
                            
                        } catch(e) {
                            console.error("Failed to fetch registry skills", e);
                        }
                    }

                    async function updateLogs() {
                        try {
                            const res = await fetch("/gateway-logs");
                            if (!res.ok) return;
                            const logs = await res.json();
                            const container = document.getElementById("logs-container");
                            
                            if (logs.length === 0) {
                                container.innerHTML = '<div style="color: var(--text-muted); text-align: center; padding-top: 20px;">No logs captured yet.</div>';
                                return;
                            }
                            
                            container.innerHTML = logs.map(log => {
                                let color = "#e5e7eb";
                                if (log.event_type === "REGISTRATION") color = "#c084fc";
                                else if (log.event_type === "DISCOVERY") color = "#60a5fa";
                                else if (log.event_type === "EXECUTION") color = "#34d399";
                                else if (log.event_type === "ERROR") color = "#f87171";
                                
                                return `
                                    <div style="border-bottom: 1px solid #1f2937; padding-bottom: 6px; margin-bottom: 4px; line-height: 1.4;">
                                        <span style="color: #6b7280; font-size: 0.65rem;">[${log.timestamp}]</span>
                                        <span style="color: ${color}; font-weight: bold; font-size: 0.65rem;">[${log.event_type}]</span>
                                        <span style="color: #9ca3af; font-weight: 600;">${log.source}:</span>
                                        <span style="color: #f3f4f6;">${log.message}</span>
                                    </div>
                                `;
                            }).reverse().join(''); // Show newest logs at top
                        } catch(e) {
                            console.error("Failed to fetch logs", e);
                        }
                    }
                    
                    // Set up polling intervals
                    setInterval(updateRegistry, 1000);
                    setInterval(updateTokenMetrics, 1000);
                    setInterval(updateLogs, 1000);
                    
                    // Initial loads
                    updateRegistry();
                    updateTokenMetrics();
                    updateLogs();
                </script>
            </body>
            </html>
            """
            return HTMLResponse(content=html_content)

        persisted = load_persisted_endpoints()
        return {
            "status": "ok", 
            "registry_size": len(ROUTER.registry) if ROUTER else 0,
            "static_agent_endpoints": CONFIG.agent_endpoints,
            "static_mcp_endpoints": CONFIG.mcp_endpoints,
            "dynamic_agent_endpoints": persisted["agent_endpoints"],
            "dynamic_mcp_endpoints": persisted["mcp_endpoints"]
        }

    @app.post("/register/init")
    def register_init(payload: Dict[str, Any]):
        node_id = payload.get("node_id")
        channels = payload.get("channels", ["#public"])
        prompt_hash = payload.get("prompt_hash")
        if not node_id:
            raise HTTPException(status_code=400, detail="Missing node_id")
            
        challenge_bytes = secrets.token_hex(32)
        CHALLENGES[node_id] = challenge_bytes
        REGISTERED_NODES[node_id] = {
            "channels": channels,
            "public_key": None,
            "prompt_hash": prompt_hash
        }
        add_system_log("REGISTRATION", node_id, "Initiated challenge-response handshake.")
        return {"challenge_bytes": challenge_bytes}

    @app.post("/register/verify")
    def register_verify(payload: Dict[str, Any]):
        node_id = payload.get("node_id")
        signature_hex = payload.get("signature")
        public_key_pem = payload.get("public_key")
        prompt_hash = payload.get("prompt_hash")
        
        if not node_id or not signature_hex or not public_key_pem:
            raise HTTPException(status_code=400, detail="Missing required parameters")
            
        challenge = CHALLENGES.get(node_id)
        if not challenge:
            raise HTTPException(status_code=400, detail="No active challenge for this node_id")
            
        try:
            pubkey = serialization.load_pem_public_key(public_key_pem.encode("utf-8"))
            sig_bytes = bytes.fromhex(signature_hex)
            pubkey.verify(
                sig_bytes,
                challenge.encode("utf-8")
            )
        except InvalidSignature:
            add_system_log("ERROR", node_id, "Handshake validation failed: Invalid cryptographic signature.")
            raise HTTPException(status_code=401, detail="Invalid cryptographic signature")
        except Exception as e:
            add_system_log("ERROR", node_id, f"Handshake validation failed with exception: {e}")
            raise HTTPException(status_code=400, detail=f"Failed to verify signature: {e}")
            
        REGISTERED_NODES[node_id]["public_key"] = pubkey
        if prompt_hash:
            REGISTERED_NODES[node_id]["prompt_hash"] = prompt_hash
        del CHALLENGES[node_id]
        
        expiry = int(time.time()) + 3600
        session_token = sign_paseto_v4_public(
            {
                "sub": node_id,
                "channels": REGISTERED_NODES[node_id]["channels"],
                "exp": expiry
            },
            GATEWAY_PRIVATE_KEY
        )
        
        add_system_log("REGISTRATION", node_id, "Handshake verified. Session token generated successfully.")
        return {"session_token": session_token, "expiry": expiry}

    @app.post("/register/disconnect")
    def register_disconnect(payload: Dict[str, Any]):
        """
        Unregisters/disconnects a node from the Gateway registry and rebuilds the FAISS index.
        """
        node_id = payload.get("node_id")
        if not node_id:
            raise HTTPException(status_code=400, detail="Missing node_id")
            
        # 1. Remove from registered nodes list
        if node_id in REGISTERED_NODES:
            del REGISTERED_NODES[node_id]
            
        # 2. Remove associated capabilities from semantic search registry
        keys_to_remove = []
        for key, value in list(ROUTER.registry.items()):
            if (key == node_id or 
                value.get("node_id") == node_id or 
                value.get("url") == node_id or 
                value.get("server_url") == node_id):
                keys_to_remove.append(key)
            elif value.get("type") == "agent" and key.startswith(node_id):
                keys_to_remove.append(key)
                
        for k in keys_to_remove:
            if k in ROUTER.registry:
                del ROUTER.registry[k]
                
        # Rebuild FAISS index
        if ROUTER:
            ROUTER.build_index()
            
        add_system_log("REGISTRATION", node_id, f"Node successfully disconnected. Removed {len(keys_to_remove)} capabilities from FAISS.")
        return {
            "status": "success",
            "message": f"Node '{node_id}' successfully disconnected and removed from FAISS index."
        }

    @app.post("/discover")
    def discover(query: str = None, threshold: float = None, exclude_node_id: str = None, payload: Dict[str, Any] = None):
        """
        Secure semantic discovery (IRC-A Gateway broker).
        Verifies session token, performs logical channel masking, excludes calling node ID if requested, and mints an ephemeral DET.
        """
        if payload is None:
            payload = {}
            
        actual_query = query or payload.get("query")
        if not actual_query:
            raise HTTPException(status_code=400, detail="Missing query parameter or payload JSON")

        auth_header = payload.get("session_token")
        if not auth_header:
            raise HTTPException(status_code=401, detail="Missing session_token")
            
        try:
            decoded_session = verify_paseto_v4_public(auth_header, GATEWAY_PUBLIC_KEY)
            caller_id = decoded_session["sub"]
            caller_channels = decoded_session.get("channels", ["#public"])
            if decoded_session.get("exp", 0) < time.time():
                raise HTTPException(status_code=401, detail="Session token expired")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=401, detail=f"Invalid session token: {e}")
            
        if not ROUTER:
            raise HTTPException(status_code=503, detail="Gateway not ready")
            
        effective_exclude_id = exclude_node_id or payload.get("exclude_node_id") or caller_id
            
        req_threshold = threshold if threshold is not None else (payload.get("threshold") if payload.get("threshold") is not None else CONFIG.semantic_threshold)

        result = ROUTER.resolve(
            actual_query, 
            threshold=req_threshold,
            agent_channels=caller_channels, 
            exclude_node_id=effective_exclude_id
        )
        best = result.get("best")
        if not best:
            add_system_log("DISCOVERY", caller_id, f"Failed discovery: No capability found matching query '{actual_query}' above threshold {req_threshold}.")
            raise HTTPException(status_code=404, detail=f"No matching capability found above threshold {req_threshold}")
            
        target_node_id = best["skill"]
        target_type = best["type"]
        
        # Extract restricted parameters dynamically using the configured extractors, incoming payload, or schema matching
        restricted_params = {}
        if payload:
            if "restricted_params" in payload and isinstance(payload["restricted_params"], dict):
                restricted_params.update(payload["restricted_params"])
            elif "params" in payload and isinstance(payload["params"], dict):
                restricted_params.update(payload["params"])

        import re
        for param_name, pattern in DYNAMIC_PARAMETER_EXTRACTORS.items():
            if param_name not in restricted_params:
                match = re.search(pattern, query, re.IGNORECASE)
                if match:
                    restricted_params[param_name] = match.group(1)

        # Advanced parameter extraction for dates, ranges, and queries
        if not restricted_params:
            schema_props = best["data"].get("input_schema", {}).get("properties", {})
            
            # Extract date ranges (e.g. "del 28 al 31 de Julio" or "desde 2026-07-28 hasta 2026-07-31")
            date_range_match = re.search(r'(?:del|desde)\s+([0-9]{1,4}[-/][0-9]{1,2}[-/][0-9]{1,4}|[0-9]{1,2}\s+(?:de\s+)?[a-zA-Z]+|\d+)\s+(?:al|hasta|a)\s+([0-9]{1,4}[-/][0-9]{1,2}[-/][0-9]{1,4}|[0-9]{1,2}\s+(?:de\s+)?[a-zA-Z]+|\d+)', query, re.IGNORECASE)
            if date_range_match:
                if "desde" in schema_props:
                    restricted_params["desde"] = date_range_match.group(1).strip()
                if "hasta" in schema_props:
                    restricted_params["hasta"] = date_range_match.group(2).strip()
            
            if "nombre" in schema_props or "apellido" in schema_props or "phone" in schema_props or "query" in schema_props:
                # Clean up query prefixes to isolate entity names
                clean_q = re.sub(r'^(buscar|consultar|ver|obtener|find|search|buscar_contactos|contactos|crm)\s+', '', query, flags=re.IGNORECASE).strip()
                words = clean_q.split()
                if "nombre" in schema_props and len(words) >= 1 and "desde" not in restricted_params:
                    restricted_params["nombre"] = words[0]
                if "apellido" in schema_props and len(words) >= 2 and "desde" not in restricted_params:
                    restricted_params["apellido"] = " ".join(words[1:])
                elif "query" in schema_props:
                    restricted_params["query"] = clean_q

        # Retrieve prompt_hash if registered for target node
        target_prompt_hash = REGISTERED_NODES.get(target_node_id, {}).get("prompt_hash")
        if not target_prompt_hash:
            target_prompt_hash = best["data"].get("prompt_hash")

        import uuid
        det_expiry = int(time.time()) + 60
        det_claims = {
            "jti": str(uuid.uuid4()),
            "iss": "irca-gateway",
            "sub": caller_id,
            "aud": target_node_id,
            "permitted_action": best["data"]["name"],
            "restricted_params": restricted_params,
            "exp": det_expiry,
            "iat": int(time.time())
        }
        if target_prompt_hash:
            det_claims["expected_prompt_hash"] = target_prompt_hash

        det = sign_paseto_v4_public(
            det_claims,
            GATEWAY_PRIVATE_KEY
        )
        
        target_url = best["data"].get("url") or best["data"].get("server_url")
        base_tools_url = target_url.rstrip("/") + "/tools" if target_type == "tool" and not target_url.endswith("/tools") else target_url

        # Build arguments for prepared execution call
        prepared_args = dict(restricted_params)
        prepared_args["delegated_token"] = det

        prepared_call = {
            "url": base_tools_url,
            "method": "POST",
            "body": {
                "tool": target_node_id,
                "arguments": prepared_args
            }
        } if target_type == "tool" else {
            "url": target_url,
            "method": "POST",
            "headers": {"Authorization": f"Bearer {det}"},
            "body": {"query": query, "params": restricted_params}
        }
        
        add_system_log("DISCOVERY", caller_id, f"Resolved query '{query}' -> target '{target_node_id}' ({target_url}). Mints DET token with restricted_params: {restricted_params}")
        response_data = {
            "status": "success",
            "det": det,
            "url": target_url,
            "target_node_id": target_node_id,
            "type": target_type,
            "input_schema": best["data"].get("input_schema", {}),
            "restricted_params": restricted_params,
            "prepared_call": prepared_call
        }
        print("\n" + "="*80)
        print(f"=== [BFA GATEWAY /discover RESPUESTA EMITIDA] ===")
        print(f"🔹 Caller ID       : {caller_id}")
        print(f"🔹 Query           : {query}")
        print(f"🔹 Target          : {target_node_id} ({target_type}) @ {target_url}")
        print(f"🔹 Restricted Params: {json.dumps(restricted_params, ensure_ascii=False)}")
        print(f"🔹 Prepared Call   : {json.dumps(prepared_call, ensure_ascii=False, indent=2)}")
        print("="*80 + "\n")
        return response_data
 
    @app.post("/mint")
    def mint_token(payload: Dict[str, Any]):
        """
        Manually mint a DET token for a custom target and action.
        """
        target_node_id = payload.get("target_node_id")
        permitted_action = payload.get("permitted_action")
        restricted_params = payload.get("restricted_params", {})
        if not target_node_id or not permitted_action:
            raise HTTPException(status_code=400, detail="Missing target_node_id or permitted_action")
        # Look up prompt_hash for target_node_id
        target_prompt_hash = payload.get("prompt_hash") or REGISTERED_NODES.get(target_node_id, {}).get("prompt_hash")
        if not target_prompt_hash and ROUTER:
            for existing_item in ROUTER.registry.values():
                if existing_item.get("node_id") == target_node_id or existing_item.get("skill") == target_node_id:
                    target_prompt_hash = existing_item.get("prompt_hash")
                    break

        import uuid
        det_expiry = int(time.time()) + 3600
        det_claims = {
            "jti": str(uuid.uuid4()),
            "iss": "irca-gateway-admin",
            "sub": "gateway-admin",
            "aud": target_node_id,
            "permitted_action": permitted_action,
            "restricted_params": restricted_params,
            "exp": det_expiry,
            "iat": int(time.time())
        }
        if target_prompt_hash:
            det_claims["expected_prompt_hash"] = target_prompt_hash

        det = sign_paseto_v4_public(
            det_claims,
            GATEWAY_PRIVATE_KEY
        )
        add_system_log("SYSTEM", "Gateway", f"Manually minted DET token for target '{target_node_id}', action '{permitted_action}'")
        return {"det": det}

    @app.post("/register/agent")
    async def register_agent(url: str, channels: str = "#public", node_id: str = None, prompt_hash: str = None, payload: Dict[str, Any] = None):
        """
        Dynamically register a new A2A Agent URL in runtime, index it in FAISS, and persist it.
        """
        if not ROUTER:
            raise HTTPException(status_code=503, detail="Gateway not ready")
            
        new_agents = await discover_agents([url])
        if not new_agents:
            add_system_log("ERROR", node_id or url, f"Failed dynamic discovery for Agent at {url}.")
            raise HTTPException(status_code=400, detail=f"Failed to discover agent at {url}")
            
        # Check collision: Is the URL used by a DIFFERENT node?
        current_target_id = node_id or (list(new_agents.keys())[0] if new_agents else None)
        for reg_id, reg_info in REGISTERED_NODES.items():
            if reg_info.get("url") == url:
                if reg_id != current_target_id and reg_id not in new_agents:
                    raise HTTPException(
                        status_code=409, 
                        detail=f"Agent URL '{url}' is already registered by node '{reg_id}'"
                    )

        # Extract prompt_hash from payload if present
        actual_prompt_hash = prompt_hash
        if not actual_prompt_hash and payload:
            actual_prompt_hash = payload.get("prompt_hash")

        channel_list = [ch.strip() for ch in channels.split(",") if ch.strip()]
        for skill_id, new_item in new_agents.items():
            target_id = node_id or skill_id
            
            # If target_id is registered under a DIFFERENT URL, it's a collision
            if target_id in REGISTERED_NODES:
                existing_url = REGISTERED_NODES[target_id].get("url")
                if existing_url and existing_url != url:
                    raise HTTPException(
                        status_code=409, 
                        detail=f"Agent '{target_id}' is already registered at URL '{existing_url}'"
                    )

            # Check semantic content collision with a DIFFERENT agent/node
            for existing_id, existing_item in ROUTER.registry.items():
                existing_node = existing_item.get("node_id") or existing_id
                if existing_node != target_id and (
                    existing_item.get("name") == new_item.get("name") and
                    existing_item.get("description") == new_item.get("description")
                ):
                    raise HTTPException(
                        status_code=409, 
                        detail="An agent with identical semantic metadata is already registered"
                    )

            new_agents[skill_id]["channels"] = channel_list
            new_agents[skill_id]["node_id"] = target_id
            if actual_prompt_hash:
                new_agents[skill_id]["prompt_hash"] = actual_prompt_hash
            if payload and "precomputed_embeddings" in payload:
                pre_embs = payload["precomputed_embeddings"]
                if skill_id in pre_embs:
                    new_agents[skill_id]["precomputed_embedding"] = pre_embs[skill_id]
            
        # Update or add agent skills in registry
        for skill_id, item in new_agents.items():
            target_id = node_id or skill_id
            if target_id not in REGISTERED_NODES:
                REGISTERED_NODES[target_id] = {}
            REGISTERED_NODES[target_id]["url"] = url
            REGISTERED_NODES[target_id]["channels"] = channel_list

        ROUTER.update_registry(new_agents)
        ROUTER.build_index()
        
        persist_endpoint("agent", url)
        add_system_log("REGISTRATION", node_id or list(new_agents.keys())[0], f"Successfully registered Agent at {url} on channels {channels}.")
        return {
            "status": "success",
            "message": f"Successfully registered Agent at {url}",
            "registered_skills": list(new_agents.keys())
        }
 
    @app.post("/register/mcp")
    async def register_mcp(url: str, channels: str = "#public", node_id: str = None, payload: Dict[str, Any] = None):
        """
        Dynamically register a new MCP Server URL in runtime, index its tools in FAISS, and persist it.
        """
        if not ROUTER:
            raise HTTPException(status_code=503, detail="Gateway not ready")
            
        current_target_id = node_id or url
        # Check collision: Is the URL used by a DIFFERENT node?
        for reg_id, reg_info in REGISTERED_NODES.items():
            if reg_info.get("url") == url and reg_id != current_target_id:
                raise HTTPException(
                    status_code=409, 
                    detail=f"MCP Server URL '{url}' is already registered by node '{reg_id}'"
                )

        new_tools = await discover_tools([url])
        if not new_tools:
            add_system_log("ERROR", node_id or url, f"Failed dynamic discovery for MCP tools at {url}.")
            raise HTTPException(status_code=400, detail=f"Failed to discover MCP tools at {url}")
            
        channel_list = [ch.strip() for ch in channels.split(",") if ch.strip()]
        for tool_name, new_item in new_tools.items():
            target_id = node_id or url
            if tool_name in ROUTER.registry:
                existing_node = ROUTER.registry[tool_name].get("node_id") or ROUTER.registry[tool_name].get("server_url")
                if existing_node and existing_node != target_id and existing_node != url:
                    raise HTTPException(
                        status_code=409, 
                        detail=f"Tool '{tool_name}' is already registered by '{existing_node}'"
                    )

            # Check semantic content collision with a DIFFERENT tool/server
            for existing_id, existing_item in ROUTER.registry.items():
                existing_server = existing_item.get("server_url") or existing_item.get("node_id")
                if existing_id != tool_name and existing_server and existing_server != url and (
                    existing_item.get("name") == new_item.get("name") and
                    existing_item.get("description") == new_item.get("description")
                ):
                    raise HTTPException(
                        status_code=409, 
                        detail="A tool with identical semantic metadata is already registered"
                    )

            new_tools[tool_name]["channels"] = channel_list
            new_tools[tool_name]["node_id"] = node_id or url
            if payload and "precomputed_embeddings" in payload:
                pre_embs = payload["precomputed_embeddings"]
                if tool_name in pre_embs:
                    new_tools[tool_name]["precomputed_embedding"] = pre_embs[tool_name]
            
        # Update or add MCP tools in registry
        for tool_name, item in new_tools.items():
            target_id = node_id or url
            if target_id not in REGISTERED_NODES:
                REGISTERED_NODES[target_id] = {}
            REGISTERED_NODES[target_id]["url"] = url
            REGISTERED_NODES[target_id]["channels"] = channel_list

        ROUTER.update_registry(new_tools)
        ROUTER.build_index()
        
        persist_endpoint("mcp", url)
        add_system_log("REGISTRATION", node_id or "MCP Server", f"Successfully registered MCP Server at {url} with {len(new_tools)} tools.")
        return {
            "status": "success",
            "message": f"Successfully registered MCP Server at {url}",
            "registered_tools": list(new_tools.keys())
        }

    @app.post("/invoke")
    async def invoke(query: str, payload: Dict[str, Any] = None):
        """
        Semantically select the best agent and forward the JSON-RPC execution.
        """
        if not ROUTER:
            raise HTTPException(status_code=503, detail="Gateway not ready")
            
        req_threshold = payload.get("threshold") if (payload and payload.get("threshold") is not None) else CONFIG.semantic_threshold
        result = ROUTER.resolve(query, threshold=req_threshold, filter_type="agent")
        best = result.get("best")
        
        if not best:
            raise HTTPException(status_code=404, detail=f"No matching agent found above threshold {req_threshold}.")
            
        agent_url = best["data"]["url"]
        target_node_id = best.get("skill") or best.get("data", {}).get("node_id") or "agent"
        
        # Retrieve prompt_hash if registered for target node
        target_prompt_hash = REGISTERED_NODES.get(target_node_id, {}).get("prompt_hash")
        if not target_prompt_hash:
            target_prompt_hash = best["data"].get("prompt_hash")

        import uuid
        det_expiry = int(time.time()) + 3600
        det_claims = {
            "jti": str(uuid.uuid4()),
            "iss": "irca-gateway",
            "sub": "gateway-broker",
            "aud": target_node_id,
            "permitted_action": "SendMessage",
            "restricted_params": {},
            "exp": det_expiry,
            "iat": int(time.time())
        }
        if target_prompt_hash:
            det_claims["expected_prompt_hash"] = target_prompt_hash

        det = sign_paseto_v4_public(
            det_claims,
            GATEWAY_PRIVATE_KEY
        )

        # 1. Translate the incoming payload to A2A SendMessage format
        a2a_payload = {
            "jsonrpc": "2.0",
            "method": "SendMessage",
            "params": {
                "message": {
                    "role": 1, # ROLE_USER
                    "message_id": "bfa-msg-id",
                    "context_id": "bfa-session-id",
                    "parts": [
                        {
                            "text": query
                        }
                    ]
                }
            },
            "id": payload.get("id", 1) if payload else 1
        }
        
        # Add system log for Observability Console
        add_system_log("DISCOVERY", target_node_id, f"Resolved query '{query}' -> target '{target_node_id}' ({agent_url}). Mints DET token.")

        # 2. Forward request to A2A Agent with required DET and version headers
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.post(
                    agent_url, 
                    json=a2a_payload,
                    headers={
                        "A2A-Version": "1.0",
                        "x-det": det
                    }
                )
                response_json = response.json()
            except Exception as e:
                add_system_log("ERROR", target_node_id, f"Execution failed for query '{query}': {e}")
                raise HTTPException(
                    status_code=502, 
                    detail=f"Failed to forward request to Agent at {agent_url}: {e}"
                )
                
        # 3. Translate the outgoing A2A response back to the frontend format
        if "error" in response_json:
            return response_json
            
        text_response = "Sin respuesta estructurada del agente."
        if "result" in response_json and "message" in response_json["result"]:
            parts = response_json["result"]["message"].get("parts", [])
            if parts:
                text_response = parts[0].get("text", "")
                
        return {
            "jsonrpc": "2.0",
            "result": {
                "output": {
                    "text": text_response
                }
            },
            "id": response_json.get("id", 1)
        }

    return app


# Standard Mangum Handler for AWS Lambda deployments
try:
    from mangum import Mangum
    app = create_gateway_app()
    handler = Mangum(app)
except ImportError:
    # Mangum optional
    pass


def main():
    """
    CLI execution entry point to start the IRC-A Gateway using uvicorn.
    """
    import uvicorn
    # Load dotenv if present
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    host = os.getenv("BFA_GATEWAY_HOST", "127.0.0.1")
    port = int(os.getenv("BFA_GATEWAY_PORT", "8000"))
    
    # Check if OpenAI API Key is loaded
    openai_key = os.getenv("OPENAI_API_KEY", "").strip().strip("'\"")
    if openai_key:
        os.environ["BFA_USE_OPENAI_EMBEDDINGS"] = "true"
        os.environ["BFA_USE_MOCK_EMBEDDINGS"] = "false"
        print("IRC-A Gateway: Found OpenAI API key, activating OpenAI Embeddings!")
    else:
        # Check if local dependencies are missing
        try:
            import sentence_transformers
            os.environ["BFA_USE_MOCK_EMBEDDINGS"] = "false"
            os.environ["BFA_USE_OPENAI_EMBEDDINGS"] = "false"
        except ImportError:
            os.environ["BFA_USE_MOCK_EMBEDDINGS"] = "true"
            os.environ["BFA_USE_OPENAI_EMBEDDINGS"] = "false"
            print("IRC-A Gateway: Falling back to DummyEmbedder (offline mock).")

    import logging

    class EndpointFilter(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            msg = record.getMessage()
            polling_paths = ["GET /skills", "GET /gateway-logs", "GET /token-metrics", "GET /logs"]
            return not any(path in msg for path in polling_paths)

    logging.getLogger("uvicorn.access").addFilter(EndpointFilter())

    gateway_app = create_gateway_app()
    uvicorn.run(gateway_app, host=host, port=port)

