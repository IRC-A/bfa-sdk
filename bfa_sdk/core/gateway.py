# Copyright (c) 2026 Sandro G. All rights reserved.
# Licensed under AGPLv3 / Commercial Dual License.
from fastapi import FastAPI, Query, HTTPException
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

    @app.get("/public_key")
    def get_public_key():
        pem = GATEWAY_PUBLIC_KEY.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )
        return {"public_key": pem.decode("utf-8")}

    @app.get("/logs")
    def get_logs():
        return SYSTEM_LOGS

    @app.post("/register/init")
    def register_init(payload: Dict[str, Any]):
        node_id = payload.get("node_id")
        channels = payload.get("channels", ["#public"])
        if not node_id:
            raise HTTPException(status_code=400, detail="Missing node_id")
            
        challenge_bytes = secrets.token_hex(32)
        CHALLENGES[node_id] = challenge_bytes
        REGISTERED_NODES[node_id] = {
            "channels": channels,
            "public_key": None
        }
        add_system_log("REGISTRATION", node_id, "Initiated challenge-response handshake.")
        return {"challenge_bytes": challenge_bytes}

    @app.post("/register/verify")
    def register_verify(payload: Dict[str, Any]):
        node_id = payload.get("node_id")
        signature_hex = payload.get("signature")
        public_key_pem = payload.get("public_key")
        
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
    def discover(query: str, payload: Dict[str, Any] = None):
        """
        Secure semantic discovery (IRC-A Gateway broker).
        Verifies session token, performs logical channel masking, and mints an ephemeral DET.
        """
        auth_header = None
        if payload:
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
            
        result = ROUTER.resolve(query, agent_channels=caller_channels)
        best = result.get("best")
        if not best:
            add_system_log("DISCOVERY", caller_id, f"Failed discovery: No capability found matching query '{query}' under authorized channels.")
            raise HTTPException(status_code=404, detail="No matching capability found under authorized channels")
            
        target_node_id = best["skill"]
        target_type = best["type"]
        
        # Extract restricted parameters dynamically using the configured extractors
        restricted_params = {}
        if payload and "restricted_params" in payload:
            restricted_params.update(payload.get("restricted_params", {}))
            
        import re
        for param_name, pattern in DYNAMIC_PARAMETER_EXTRACTORS.items():
            if param_name not in restricted_params:
                match = re.search(pattern, query, re.IGNORECASE)
                if match:
                    restricted_params[param_name] = match.group(1)
            
        import uuid
        det_expiry = int(time.time()) + 60
        det = sign_paseto_v4_public(
            {
                "jti": str(uuid.uuid4()),
                "iss": "irca-gateway",
                "sub": caller_id,
                "aud": target_node_id,
                "permitted_action": best["data"]["name"],
                "restricted_params": restricted_params,
                "exp": det_expiry,
                "iat": int(time.time())
            },
            GATEWAY_PRIVATE_KEY
        )
        
        target_url = best["data"].get("url") or best["data"].get("server_url")
        
        add_system_log("DISCOVERY", caller_id, f"Resolved query '{query}' -> target '{target_node_id}' ({target_url}). Mints DET token.")
        return {
            "status": "success",
            "det": det,
            "url": target_url,
            "target_node_id": target_node_id,
            "type": target_type
        }
 
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
        import uuid
        det_expiry = int(time.time()) + 3600
        det = sign_paseto_v4_public(
            {
                "jti": str(uuid.uuid4()),
                "iss": "irca-gateway-admin",
                "sub": "gateway-admin",
                "aud": target_node_id,
                "permitted_action": permitted_action,
                "restricted_params": restricted_params,
                "exp": det_expiry,
                "iat": int(time.time())
            },
            GATEWAY_PRIVATE_KEY
        )
        add_system_log("SYSTEM", "Gateway", f"Manually minted DET token for target '{target_node_id}', action '{permitted_action}'")
        return {"det": det}

    @app.post("/register/agent")
    async def register_agent(url: str, channels: str = "#public", node_id: str = None, payload: Dict[str, Any] = None):
        """
        Dynamically register a new A2A Agent URL in runtime, index it in FAISS, and persist it.
        """
        if not ROUTER:
            raise HTTPException(status_code=503, detail="Gateway not ready")
            
        new_agents = await discover_agents([url])
        if not new_agents:
            add_system_log("ERROR", node_id or url, f"Failed dynamic discovery for Agent at {url}.")
            raise HTTPException(status_code=400, detail=f"Failed to discover agent at {url}")
            
        channel_list = [ch.strip() for ch in channels.split(",") if ch.strip()]
        for skill_id in new_agents:
            new_agents[skill_id]["channels"] = channel_list
            new_agents[skill_id]["node_id"] = node_id or skill_id
            if payload and "precomputed_embeddings" in payload:
                pre_embs = payload["precomputed_embeddings"]
                if skill_id in pre_embs:
                    new_agents[skill_id]["precomputed_embedding"] = pre_embs[skill_id]
            
        # Prevent registration of duplicate IDs or identical semantic metadata
        for skill_id, item in new_agents.items():
            if skill_id in ROUTER.registry:
                raise HTTPException(status_code=409, detail=f"Conflict: Agent skill ID '{skill_id}' is already registered.")
            
            tags_str = " ".join(item.get("tags", []))
            examples_str = " ".join(item.get("examples", []))
            new_search_text = " ".join([
                item.get("name", ""),
                item.get("description", ""),
                tags_str,
                examples_str
            ]).strip().lower()
 
            for existing_id, existing_item in ROUTER.registry.items():
                existing_tags_str = " ".join(existing_item.get("tags", []))
                existing_examples_str = " ".join(existing_item.get("examples", []))
                existing_search_text = " ".join([
                    existing_item.get("name", ""),
                    existing_item.get("description", ""),
                    existing_tags_str,
                    existing_examples_str
                ]).strip().lower()
 
                if new_search_text == existing_search_text:
                    raise HTTPException(
                        status_code=409, 
                        detail=f"Conflict: An agent/tool with identical semantic metadata is already registered ('{existing_id}')."
                    )
            
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
            
        new_tools = await discover_tools([url])
        if not new_tools:
            add_system_log("ERROR", node_id or url, f"Failed dynamic discovery for MCP tools at {url}.")
            raise HTTPException(status_code=400, detail=f"Failed to discover MCP tools at {url}")
            
        channel_list = [ch.strip() for ch in channels.split(",") if ch.strip()]
        for tool_name in new_tools:
            new_tools[tool_name]["channels"] = channel_list
            new_tools[tool_name]["node_id"] = node_id or url
            if payload and "precomputed_embeddings" in payload:
                pre_embs = payload["precomputed_embeddings"]
                if tool_name in pre_embs:
                    new_tools[tool_name]["precomputed_embedding"] = pre_embs[tool_name]
            
        # Prevent registration of duplicate IDs or identical semantic metadata
        for tool_name, item in new_tools.items():
            if tool_name in ROUTER.registry:
                raise HTTPException(status_code=409, detail=f"Conflict: Tool name '{tool_name}' is already registered.")
            
            tags_str = " ".join(item.get("tags", []))
            examples_str = " ".join(item.get("examples", []))
            new_search_text = " ".join([
                item.get("name", ""),
                item.get("description", ""),
                tags_str,
                examples_str
            ]).strip().lower()
 
            for existing_id, existing_item in ROUTER.registry.items():
                existing_tags_str = " ".join(existing_item.get("tags", []))
                existing_examples_str = " ".join(existing_item.get("examples", []))
                existing_search_text = " ".join([
                    existing_item.get("name", ""),
                    existing_item.get("description", ""),
                    existing_tags_str,
                    existing_examples_str
                ]).strip().lower()
 
                if new_search_text == existing_search_text:
                    raise HTTPException(
                        status_code=409, 
                        detail=f"Conflict: An agent/tool with identical semantic metadata is already registered ('{existing_id}')."
                    )
            
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

    gateway_app = create_gateway_app()
    uvicorn.run(gateway_app, host=host, port=port, log_level="warning")

