# Copyright (c) 2026 Sandro G. All rights reserved.
# Licensed under AGPLv3 / Commercial Dual License.
# Backend for Agents SDK (BFA)
# Version 0.3.0
"""
BFA SDK: A lightweight framework for Backend for Agents (BFA) architecture with FAISS semantic routing.
"""


from irca_sdk.core.agent import IRCAAgent, BFAAgent
from irca_sdk.core.interactive_agent import IRCAInteractiveAgent, BFAInteractiveAgent
from irca_sdk.core.mcp import IRCAMCP, BFAMCP
from irca_sdk.core.gateway import create_gateway_app
from irca_sdk.router.search import BFASemanticRouter

__all__ = [
    "IRCAAgent", 
    "IRCAMCP", 
    "IRCAInteractiveAgent", 
    "BFAAgent", 
    "BFAMCP", 
    "BFAInteractiveAgent", 
    "create_gateway_app", 
    "BFASemanticRouter"
]
