import pytest
import os
import yaml
from bfa_sdk.config import BFAConfig

def test_config_load_from_env():
    # Set mock environment variables
    os.environ["BFA_AGENT_ENDPOINTS"] = "http://agent1:8000, http://agent2:8000"
    os.environ["BFA_MCP_ENDPOINTS"] = "http://mcp:8000"
    os.environ["BFA_EMBEDDING_MODEL"] = "mock-model"
    os.environ["BFA_USE_MOCK_EMBEDDINGS"] = "true"
    os.environ["BFA_USE_OPENAI_EMBEDDINGS"] = "true"
    os.environ["OPENAI_API_KEY"] = "mock-api-key"
    
    config = BFAConfig()
    
    assert config.agent_endpoints == ["http://agent1:8000", "http://agent2:8000"]
    assert config.mcp_endpoints == ["http://mcp:8000"]
    assert config.embedding_model == "mock-model"
    assert config.use_mock_embeddings is True
    assert config.use_openai_embeddings is True
    assert config.openai_api_key == "mock-api-key"
    
    # Clean up
    del os.environ["BFA_AGENT_ENDPOINTS"]
    del os.environ["BFA_MCP_ENDPOINTS"]
    del os.environ["BFA_EMBEDDING_MODEL"]
    del os.environ["BFA_USE_MOCK_EMBEDDINGS"]
    del os.environ["BFA_USE_OPENAI_EMBEDDINGS"]
    del os.environ["OPENAI_API_KEY"]

def test_config_load_from_file(tmp_path):
    config_data = {
        "agent_endpoints": ["http://file-agent:8000"],
        "mcp_endpoints": ["http://file-mcp:8000"],
        "embedding_model": "file-model",
        "use_mock_embeddings": True,
        "use_openai_embeddings": False,
        "openai_api_key": "file-key"
    }
    
    # Write to a temporary file
    cfg_file = tmp_path / "bfa_config.yaml"
    with open(cfg_file, "w") as f:
        yaml.dump(config_data, f)
        
    config = BFAConfig(config_path=str(cfg_file))
    
    assert config.agent_endpoints == ["http://file-agent:8000"]
    assert config.mcp_endpoints == ["http://file-mcp:8000"]
    assert config.embedding_model == "file-model"
    assert config.use_mock_embeddings is True
    assert config.use_openai_embeddings is False
    assert config.openai_api_key == "file-key"
