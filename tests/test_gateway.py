import pytest
import os
import json
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient
from fastapi import HTTPException
from bfa_sdk.config import BFAConfig
from bfa_sdk.core.gateway import create_gateway_app, discover_agents, discover_tools, load_persisted_endpoints

# Clean up bfa_registry_db.json if it gets created during test runs
@pytest.fixture(autouse=True)
def clean_registry_file():
    db_file = "bfa_registry_db.json"
    if os.path.exists(db_file):
        os.remove(db_file)
    yield
    if os.path.exists(db_file):
        os.remove(db_file)

@pytest.fixture
def mock_gateway_setup():
    """
    Set environment variables and mock discovery calls for offline TestClient setup.
    """
    os.environ["BFA_USE_MOCK_EMBEDDINGS"] = "true"
    os.environ["BFA_AGENT_ENDPOINTS"] = "http://localhost:8002"
    os.environ["BFA_MCP_ENDPOINTS"] = "http://localhost:8001"
    
    # Mock A2A Card discovery
    mock_agent_card = MagicMock()
    mock_agent_card.name = "Mock Agent"
    mock_agent_card.description = "Test Description"
    mock_agent_card.version = "1.0"
    
    mock_skill = MagicMock()
    mock_skill.id = "mock_skill"
    mock_skill.name = "mock_skill"
    mock_skill.description = "A mock skill for testing"
    mock_skill.tags = ["tag1", "tag2"]
    mock_skill.examples = ["example 1"]
    
    mock_agent_card.skills = [mock_skill]
    
    # Mock MCP Tools discovery
    mock_tools_list = [
        {
            "name": "mock_tool",
            "description": "A mock tool for testing",
            "inputSchema": {"properties": {"param": {"type": "string"}}},
            "annotations": {"tags": ["tag3"], "examples": ["example 2"]}
        }
    ]

    with patch("bfa_sdk.core.gateway.A2ACardResolver") as mock_resolver_cls, \
         patch("httpx.AsyncClient.get") as mock_http_get:
         
        # Mock resolver instance behavior
        mock_resolver = AsyncMock()
        mock_resolver.get_agent_card.return_value = mock_agent_card
        mock_resolver_cls.return_value = mock_resolver
        
        # Mock http get response for MCP tools list
        mock_mcp_response = MagicMock()
        mock_mcp_response.status_code = 200
        mock_mcp_response.json.return_value = mock_tools_list
        mock_http_get.return_value = mock_mcp_response
        
        yield

def test_gateway_endpoints(mock_gateway_setup):
    config = BFAConfig()
    app = create_gateway_app(config)
    
    with TestClient(app) as client:
        # 1. Health check
        res = client.get("/")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"
        assert len(data["static_agent_endpoints"]) == 1
        
        # 2. Get registered skills
        res = client.get("/skills")
        assert res.status_code == 200
        skills = res.json()
        assert "mock_skill" in skills
        assert "mock_tool" in skills
        
        # 3. Resolve semantically (Agents)
        res = client.get("/resolve/agents", params={"query": "test query"})
        assert res.status_code == 200
        resolve_res = res.json()
        assert resolve_res["type"] == "semantic_faiss"
        assert resolve_res["best"]["skill"] == "mock_skill"
        
        # 4. Resolve semantically (Tools)
        res = client.get("/resolve/tools", params={"query": "test query"})
        assert res.status_code == 200
        resolve_res = res.json()
        assert resolve_res["type"] == "semantic_faiss"
        assert resolve_res["best"]["skill"] == "mock_tool"

@patch("bfa_sdk.core.gateway.discover_agents")
@patch("bfa_sdk.core.gateway.discover_tools")
def test_dynamic_registration_endpoints(mock_discover_tools, mock_discover_agents, mock_gateway_setup):
    mock_discover_agents.return_value = {
        "new_agent_skill": {
            "name": "New Agent",
            "description": "Dynamic registered agent",
            "url": "http://localhost:8080",
            "tags": ["dynamic"],
            "examples": ["hey dynamic"],
            "type": "agent"
        }
    }
    
    mock_discover_tools.return_value = {
        "new_mcp_tool": {
            "type": "tool",
            "server_url": "http://localhost:8081",
            "name": "new_mcp_tool",
            "description": "Dynamic registered tool",
            "tags": ["dynamic_tool"],
            "examples": ["invoke tool"]
        }
    }
    
    config = BFAConfig()
    app = create_gateway_app(config)
    
    with TestClient(app) as client:
        # 1. Register agent
        res = client.post("/register/agent", params={"url": "http://localhost:8080"})
        assert res.status_code == 200
        assert res.json()["status"] == "success"
        
        # Verify persistence file
        with open("bfa_registry_db.json", "r") as f:
            persisted = json.load(f)
            assert "http://localhost:8080" in persisted["agent_endpoints"]
            
        # 2. Register MCP
        res = client.post("/register/mcp", params={"url": "http://localhost:8081"})
        assert res.status_code == 200
        assert res.json()["status"] == "success"
        
        # Verify persistence file
        with open("bfa_registry_db.json", "r") as f:
            persisted = json.load(f)
            assert "http://localhost:8081" in persisted["mcp_endpoints"]

@patch("httpx.AsyncClient.post")
def test_gateway_invoke_routing(mock_post, mock_gateway_setup):
    # Mock outgoing agent invocation request in A2A format
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "jsonrpc": "2.0",
        "result": {
            "message": {
                "parts": [
                    {"text": "Routed response"}
                ]
            }
        },
        "id": 1
    }
    mock_post.return_value = mock_response
    
    config = BFAConfig()
    app = create_gateway_app(config)
    
    with TestClient(app) as client:
        payload = {
            "jsonrpc": "2.0",
            "method": "agent.execute",
            "params": {"user_input": {"text": "hey"}},
            "id": 1
        }
        res = client.post("/invoke", params={"query": "hey"}, json=payload)
        
        assert res.status_code == 200
        data = res.json()
        assert data["result"]["output"]["text"] == "Routed response"
        mock_post.assert_called_once()

# Additional edge case tests to reach high coverage:

# Test /invoke when there is no matching agent above threshold
def test_gateway_invoke_not_found(mock_gateway_setup):
    config = BFAConfig()
    config.agent_endpoints = [] # Clear endpoints so no agents are registered
    app = create_gateway_app(config)
    with TestClient(app) as client:
        res = client.post("/invoke", params={"query": "hey"})
        # Should return 404 because no agent resolved
        assert res.status_code == 404

# Test /invoke agent returning JSON-RPC error
@patch("httpx.AsyncClient.post")
def test_gateway_invoke_agent_error(mock_post, mock_gateway_setup):
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "jsonrpc": "2.0",
        "error": {
            "code": -32601,
            "message": "Method not found"
        },
        "id": 1
    }
    mock_post.return_value = mock_response
    
    config = BFAConfig()
    app = create_gateway_app(config)
    
    with TestClient(app) as client:
        res = client.post("/invoke", params={"query": "hey"})
        assert res.status_code == 200
        data = res.json()
        assert "error" in data
        assert data["error"]["code"] == -32601

# Test /invoke connection timeout / network error
@patch("httpx.AsyncClient.post", side_effect=Exception("network timeout"))
def test_gateway_invoke_network_exception(mock_post, mock_gateway_setup):
    config = BFAConfig()
    app = create_gateway_app(config)
    
    with TestClient(app) as client:
        res = client.post("/invoke", params={"query": "hey"})
        # Should fail with 502 Bad Gateway
        assert res.status_code == 502
        assert "Failed to forward request to Agent" in res.json()["detail"]

# Test load_persisted_endpoints with invalid file format
def test_load_persisted_endpoints_invalid():
    # Write invalid JSON to file
    with open("bfa_registry_db.json", "w") as f:
        f.write("{invalid: json}")
    
    endpoints = load_persisted_endpoints()
    assert endpoints["agent_endpoints"] == []
    assert endpoints["mcp_endpoints"] == []

# Test discover_agents with connection error
@patch("a2a.client.A2ACardResolver.get_agent_card", side_effect=Exception("connection error"))
@pytest.mark.anyio
async def test_discover_agents_error(mock_resolver):
    res = await discover_agents(["http://invalid-url"])
    assert res == {}

# Test discover_tools with connection error
@patch("httpx.AsyncClient.get", side_effect=Exception("connection error"))
@pytest.mark.anyio
async def test_discover_tools_error(mock_get):
    res = await discover_tools(["http://invalid-url"])
    assert res == {}

from bfa_sdk.core.gateway import persist_endpoint

def test_persist_endpoint_error():
    with patch("builtins.open", side_effect=IOError("disk full")):
        # Should execute cleanly without raising exception
        persist_endpoint("agent", "http://localhost:8080")

@pytest.mark.anyio
async def test_discover_agents_success():
    mock_agent_card = MagicMock()
    mock_agent_card.name = "My Agent"
    mock_agent_card.description = "Test Desc"
    mock_agent_card.version = "1.0"
    
    mock_skill = MagicMock()
    mock_skill.id = "my_skill"
    mock_skill.name = "My Skill"
    mock_skill.description = "Test Skill"
    mock_skill.tags = ["tag"]
    mock_skill.examples = ["ex"]
    mock_agent_card.skills = [mock_skill]
    
    with patch("bfa_sdk.core.gateway.A2ACardResolver") as mock_resolver_cls:
        mock_resolver = AsyncMock()
        mock_resolver.get_agent_card.return_value = mock_agent_card
        mock_resolver_cls.return_value = mock_resolver
        
        res = await discover_agents(["http://valid-url"])
        assert "my_skill" in res
        assert res["my_skill"]["name"] == "My Skill"
        assert res["my_skill"]["url"] == "http://valid-url"

@pytest.mark.anyio
async def test_discover_tools_success():
    mock_tools_list = [
        {
            "name": "my_tool",
            "description": "Test Tool",
            "inputSchema": {"properties": {"param": {"type": "string"}}},
            "annotations": {"tags": ["tag"], "examples": ["ex"]}
        }
    ]
    with patch("httpx.AsyncClient.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_tools_list
        mock_get.return_value = mock_resp
        
        res = await discover_tools(["http://valid-url"])
        assert "my_tool" in res
        assert res["my_tool"]["name"] == "my_tool"
        assert res["my_tool"]["server_url"] == "http://valid-url"

# Test lifespans with different embedder configurations
@patch("bfa_sdk.core.gateway.discover_agents", return_value={})
@patch("bfa_sdk.core.gateway.discover_tools", return_value={})
@patch("openai.OpenAI")
def test_gateway_lifespan_openai(mock_openai, mock_discover_tools, mock_discover_agents):
    config = BFAConfig()
    config.use_mock_embeddings = False
    config.use_openai_embeddings = True
    config.openai_api_key = "test-key"
    
    app = create_gateway_app(config)
    with TestClient(app):
        # Startup event triggered, check if embedder setup correctly
        pass

@patch("bfa_sdk.core.gateway.discover_agents", return_value={})
@patch("bfa_sdk.core.gateway.discover_tools", return_value={})
@patch("sentence_transformers.SentenceTransformer", side_effect=Exception("local load failed"))
def test_gateway_lifespan_local_fallback(mock_transformer, mock_discover_tools, mock_discover_agents):
    config = BFAConfig()
    config.use_mock_embeddings = False
    config.use_openai_embeddings = False
    config.embedding_model = "invalid-model-name-for-testing"
    
    app = create_gateway_app(config)
    with TestClient(app):
        # Startup event triggered, should fallback to DummyEmbedder cleanly
        pass

def test_mangum_import_error():
    import sys
    import importlib
    
    # Save original
    orig_mangum = sys.modules.get("mangum")
    
    try:
        # Mock ImportError for mangum
        sys.modules["mangum"] = None
        importlib.reload(sys.modules["bfa_sdk.core.gateway"])
    finally:
        # Restore original
        if orig_mangum:
            sys.modules["mangum"] = orig_mangum
        else:
            sys.modules.pop("mangum", None)

def test_gateway_not_ready():
    import bfa_sdk.core.gateway as gateway
    orig_router = gateway.ROUTER
    try:
        config = BFAConfig()
        app = create_gateway_app(config)
        with TestClient(app) as client:
            gateway.ROUTER = None # Clear it after lifespan startup runs
            res = client.get("/resolve", params={"query": "hey"})
            assert res.status_code == 503
            
            res = client.get("/resolve/agents", params={"query": "hey"})
            assert res.status_code == 503
            
            res = client.get("/resolve/tools", params={"query": "hey"})
            assert res.status_code == 503

            res = client.post("/register/agent", params={"url": "http://invalid"})
            assert res.status_code == 503

            res = client.post("/register/mcp", params={"url": "http://invalid"})
            assert res.status_code == 503

            res = client.post("/invoke", params={"query": "hey"})
            assert res.status_code == 503
    finally:
        gateway.ROUTER = orig_router

@patch("bfa_sdk.core.gateway.discover_agents", return_value={})
def test_gateway_register_agent_fail(mock_discover, mock_gateway_setup):
    config = BFAConfig()
    app = create_gateway_app(config)
    with TestClient(app) as client:
        res = client.post("/register/agent", params={"url": "http://invalid"})
        assert res.status_code == 400

@patch("bfa_sdk.core.gateway.discover_tools", return_value={})
def test_gateway_register_mcp_fail(mock_discover, mock_gateway_setup):
    config = BFAConfig()
    app = create_gateway_app(config)
    with TestClient(app) as client:
        res = client.post("/register/mcp", params={"url": "http://invalid"})
        assert res.status_code == 400



