# Copyright (c) 2026 Sandro G. All rights reserved.
# Licensed under AGPLv3 / Commercial Dual License.
# Backend for Agents SDK (BFA)
# Version 0.1.0
"""
BFA SDK: A lightweight framework for Backend for Agents (BFA) architecture with FAISS semantic routing.
"""


from bfa_sdk.core.agent import BFAAgent
from bfa_sdk.core.mcp import BFAMCP
from bfa_sdk.core.gateway import create_gateway_app
from bfa_sdk.router.search import BFASemanticRouter

__all__ = ["BFAAgent", "BFAMCP", "create_gateway_app", "BFASemanticRouter"]
