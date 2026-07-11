from fastapi import FastAPI, Query, HTTPException
from contextlib import asynccontextmanager
import httpx
import asyncio
import json
import os
from typing import Dict, Any, List, Optional
from a2a.client import A2ACardResolver

from bfa_sdk.config import BFAConfig
from bfa_sdk.router.embedder import LocalEmbedder, DummyEmbedder, OpenAIEmbedder
from bfa_sdk.router.search import BFASemanticRouter

# Global application dependencies
CONFIG = BFAConfig()
EMBEDDER = None
ROUTER = None

REGISTRY_DB_PATH = os.getenv("BFA_REGISTRY_DB_PATH", "bfa_registry_db.json")

def load_persisted_endpoints() -> Dict[str, List[str]]:
    """
    Load persisted endpoints from the local JSON registry database.
    """
    if not os.path.exists(REGISTRY_DB_PATH):
        return {"agent_endpoints": [], "mcp_endpoints": []}
    try:
        with open(REGISTRY_DB_PATH, "r") as f:
            data = json.load(f)
            return {
                "agent_endpoints": data.get("agent_endpoints", []),
                "mcp_endpoints": data.get("mcp_endpoints", [])
            }
    except Exception as e:
        print(f"BFA Gateway: Error loading persisted registry DB: {e}")
        return {"agent_endpoints": [], "mcp_endpoints": []}


def persist_endpoint(type_: str, url: str):
    """
    Save a registered endpoint dynamically to the database.
    """
    data = load_persisted_endpoints()
    key = "agent_endpoints" if type_ == "agent" else "mcp_endpoints"
    if url not in data[key]:
        data[key].append(url)
        try:
            with open(REGISTRY_DB_PATH, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"BFA Gateway: Error saving to persisted registry DB: {e}")


async def discover_agents(endpoints: List[str]) -> Dict[str, Any]:
    """
    Query A2A endpoints to obtain card and skill registrations.
    """
    registry = {}
    async with httpx.AsyncClient(timeout=5) as client:
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
    async with httpx.AsyncClient(timeout=5) as client:
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    global EMBEDDER, ROUTER
    
    # Initialize embedding driver
    if CONFIG.use_mock_embeddings:
        print("BFA Gateway: Using DummyEmbedder for fast offline testing.")
        EMBEDDER = DummyEmbedder()
    elif CONFIG.use_openai_embeddings:
        print("BFA Gateway: Using cloud OpenAIEmbedder (perfect for serverless/Lambda).")
        EMBEDDER = OpenAIEmbedder(api_key=CONFIG.openai_api_key)
    else:
        try:
            print(f"BFA Gateway: Initializing local model '{CONFIG.embedding_model}'...")
            EMBEDDER = LocalEmbedder(CONFIG.embedding_model)
        except Exception as e:
            print(f"BFA Gateway Warning: Could not load local model: {e}. Falling back to DummyEmbedder.")
            EMBEDDER = DummyEmbedder()
            
    ROUTER = BFASemanticRouter(EMBEDDER)
    
    # Load dynamically registered endpoints from database
    persisted = load_persisted_endpoints()
    
    # Combine static config endpoints and runtime persisted endpoints
    all_agents = list(set(CONFIG.agent_endpoints + persisted["agent_endpoints"]))
    all_mcps = list(set(CONFIG.mcp_endpoints + persisted["mcp_endpoints"]))
    
    # Perform agent/tool discovery
    print("BFA Gateway: Starting network discovery...")
    agents = await discover_agents(all_agents)
    tools = await discover_tools(all_mcps)
    
    ROUTER.update_registry(agents)
    ROUTER.update_registry(tools)
    ROUTER.build_index()
    
    print(f"BFA Gateway: Discovery completed. Indexed {len(agents)} agents and {len(tools)} tools.")
    yield


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
    
    @app.get("/")
    def health():
        persisted = load_persisted_endpoints()
        return {
            "status": "ok", 
            "registry_size": len(ROUTER.registry) if ROUTER else 0,
            "static_agent_endpoints": CONFIG.agent_endpoints,
            "static_mcp_endpoints": CONFIG.mcp_endpoints,
            "dynamic_agent_endpoints": persisted["agent_endpoints"],
            "dynamic_mcp_endpoints": persisted["mcp_endpoints"]
        }

    @app.get("/skills")
    def get_skills():
        return ROUTER.registry if ROUTER else {}

    @app.get("/resolve")
    def resolve(query: str, top_k: int = Query(3), threshold: float = Query(0.3)):
        if not ROUTER:
            raise HTTPException(status_code=503, detail="Gateway not ready")
        return ROUTER.resolve(query, top_k=top_k, threshold=threshold)

    @app.get("/resolve/agents")
    def resolve_agents(query: str, top_k: int = Query(3), threshold: float = Query(0.3)):
        if not ROUTER:
            raise HTTPException(status_code=503, detail="Gateway not ready")
        return ROUTER.resolve(query, top_k=top_k, threshold=threshold, filter_type="agent")

    @app.get("/resolve/tools")
    def resolve_tools(query: str, top_k: int = Query(3), threshold: float = Query(0.3)):
        if not ROUTER:
            raise HTTPException(status_code=503, detail="Gateway not ready")
        return ROUTER.resolve(query, top_k=top_k, threshold=threshold, filter_type="tool")

    @app.post("/register/agent")
    async def register_agent(url: str):
        """
        Dynamically register a new A2A Agent URL in runtime, index it in FAISS, and persist it.
        """
        if not ROUTER:
            raise HTTPException(status_code=503, detail="Gateway not ready")
            
        new_agents = await discover_agents([url])
        if not new_agents:
            raise HTTPException(status_code=400, detail=f"Failed to discover agent at {url}")
            
        ROUTER.update_registry(new_agents)
        ROUTER.build_index()
        
        persist_endpoint("agent", url)
        return {
            "status": "success",
            "message": f"Successfully registered Agent at {url}",
            "registered_skills": list(new_agents.keys())
        }

    @app.post("/register/mcp")
    async def register_mcp(url: str):
        """
        Dynamically register a new MCP Server URL in runtime, index its tools in FAISS, and persist it.
        """
        if not ROUTER:
            raise HTTPException(status_code=503, detail="Gateway not ready")
            
        new_tools = await discover_tools([url])
        if not new_tools:
            raise HTTPException(status_code=400, detail=f"Failed to discover MCP tools at {url}")
            
        ROUTER.update_registry(new_tools)
        ROUTER.build_index()
        
        persist_endpoint("mcp", url)
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
            
        result = ROUTER.resolve(query, filter_type="agent")
        best = result.get("best")
        
        if not best:
            raise HTTPException(status_code=404, detail="No matching agent found above threshold.")
            
        agent_url = best["data"]["url"]
        
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
        
        # 2. Forward request to A2A Agent with required version headers
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    agent_url, 
                    json=a2a_payload,
                    headers={"A2A-Version": "1.0"}
                )
                response_json = response.json()
            except Exception as e:
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
