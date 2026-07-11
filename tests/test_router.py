import pytest
from unittest.mock import MagicMock
from bfa_sdk.router.embedder import DummyEmbedder
from bfa_sdk.router.search import BFASemanticRouter

def test_semantic_router_indexing_and_resolution():
    # 1. Initialize embedder and router
    embedder = DummyEmbedder()
    router = BFASemanticRouter(embedder)
    
    # 2. Add mock data
    mock_agent_data = {
        "cuentas_agent": {
            "name": "Agente de Cuentas",
            "description": "Expert banking agent for checking, opening, and managing bank accounts.",
            "url": "http://127.0.0.1:8002",
            "tags": ["cuenta", "abrir cuenta", "caja de ahorro"],
            "examples": ["quiero abrir una cuenta corriente", "como abro caja de ahorro"],
            "type": "agent"
        }
    }
    
    router.update_registry(mock_agent_data)
    router.build_index()
    
    # Verify registry sizes
    assert len(router.registry) == 1
    assert "cuentas_agent" in router.registry
    
    # 3. Test resolution
    result = router.resolve("quiero abrir una cuenta corriente", threshold=0.1)
    
    assert result["type"] == "semantic_faiss"
    assert result["best"] is not None
    assert result["best"]["skill"] == "cuentas_agent"
    assert result["best"]["confidence"] > 0.1
    
def test_semantic_router_no_match_on_high_threshold():
    embedder = DummyEmbedder()
    router = BFASemanticRouter(embedder)
    
    mock_agent_data = {
        "cuentas_agent": {
            "name": "Agente de Cuentas",
            "description": "Expert banking agent",
            "url": "http://127.0.0.1:8002",
            "tags": ["cuenta"],
            "examples": ["abrir cuenta"],
            "type": "agent"
        }
    }
    
    router.update_registry(mock_agent_data)
    router.build_index()
    
    # If we request a very high confidence threshold (e.g. 0.999), it should fall back to no confident match
    result = router.resolve("hola", threshold=0.999)
    assert result["type"] == "no_confident_match"
    assert result["best"] is None

def test_semantic_router_empty_registry():
    embedder = DummyEmbedder()
    router = BFASemanticRouter(embedder)
    router.build_index()
    assert router.index is None
    
    # Resolve should return empty match
    result = router.resolve("hello")
    assert result["type"] == "no_match"
    assert result["best"] is None

def test_semantic_router_unknown_filter_type():
    embedder = DummyEmbedder()
    router = BFASemanticRouter(embedder)
    mock_agent_data = {
        "cuentas_agent": {
            "name": "Agente de Cuentas",
            "description": "Expert banking agent",
            "url": "http://127.0.0.1:8002",
            "tags": ["cuenta"],
            "examples": ["abrir cuenta"],
            "type": "agent"
        }
    }
    router.update_registry(mock_agent_data)
    router.build_index()
    
    # Filter by type "tool" which is not present in registry
    result = router.resolve("abrir cuenta", filter_type="tool")
    assert result["type"] == "no_match"
    assert result["best"] is None

def test_semantic_router_invalid_index():
    embedder = DummyEmbedder()
    router = BFASemanticRouter(embedder)
    router.update_registry({
        "agent": {"name": "Test", "type": "agent", "description": "desc"}
    })
    router.build_index()
    
    # Mock index.search to return -1 index (not found)
    import numpy as np
    router.index.search = MagicMock(return_value=(np.array([[1.0]]), np.array([[-1]])))
    
    result = router.resolve("hello")
    assert result["type"] == "no_match"
    assert result["best"] is None


