# Copyright (c) 2026 Sandro G. All rights reserved.
# Licensed under AGPLv3 / Commercial Dual License.
"""
IRC-A SDK: Lightweight Python framework for building autonomous agents and FastMCP tool servers.
"""
from bfa_sdk.agent import BFAAgent
from bfa_sdk.interactive_agent import BFAInteractiveAgent, MemoryStack
from bfa_sdk.mcp import BFAMCP
from bfa_sdk.paseto import verify_paseto_v4_public

__all__ = [
    "BFAAgent",
    "BFAInteractiveAgent",
    "BFAMCP",
    "MemoryStack",
    "verify_paseto_v4_public",
]
