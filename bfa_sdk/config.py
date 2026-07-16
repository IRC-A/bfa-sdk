# Copyright (c) 2026 Sandro G. All rights reserved.
# Licensed under AGPLv3 / Commercial Dual License.
import os
import yaml
from typing import List, Dict, Any

class BFAConfig:
    """
    Configuration helper parsing endpoints and models from environment variables
    or a YAML configuration file.
    """
    def __init__(self, config_path: str = None):
        self.agent_endpoints: List[str] = []
        self.mcp_endpoints: List[str] = []
        self.embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
        self.use_mock_embeddings: bool = False
        self.use_openai_embeddings: bool = False
        self.openai_api_key: str = ""

        # Load from config file if provided
        if config_path and os.path.exists(config_path):
            self.load_from_file(config_path)
        else:
            self.load_from_env()

    def load_from_file(self, path: str):
        with open(path, "r") as f:
            data = yaml.safe_load(f) or {}
            self.agent_endpoints = data.get("agent_endpoints", [])
            self.mcp_endpoints = data.get("mcp_endpoints", [])
            self.embedding_model = data.get("embedding_model", self.embedding_model)
            self.use_mock_embeddings = data.get("use_mock_embeddings", False)
            self.use_openai_embeddings = data.get("use_openai_embeddings", False)
            self.openai_api_key = data.get("openai_api_key", "")

    def load_from_env(self):
        # Parse comma-separated strings
        agents_env = os.getenv("BFA_AGENT_ENDPOINTS", "")
        self.agent_endpoints = [x.strip() for x in agents_env.split(",") if x.strip()]

        mcps_env = os.getenv("BFA_MCP_ENDPOINTS", "")
        self.mcp_endpoints = [x.strip() for x in mcps_env.split(",") if x.strip()]

        self.embedding_model = os.getenv("BFA_EMBEDDING_MODEL", self.embedding_model)
        self.use_mock_embeddings = os.getenv("BFA_USE_MOCK_EMBEDDINGS", "false").lower() == "true"
        self.use_openai_embeddings = os.getenv("BFA_USE_OPENAI_EMBEDDINGS", "false").lower() == "true"
        self.openai_api_key = os.getenv("OPENAI_API_KEY", "")
