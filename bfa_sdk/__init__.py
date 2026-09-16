# Copyright (c) 2026 Sandro Garcia. All rights reserved.
# Backward Compatibility Shim for bfa_sdk -> irca_sdk
"""
bfa_sdk: Backward compatibility wrapper for irca_sdk.
Please import directly from `irca_sdk` for new projects.
"""
from irca_sdk import (
    IRCAAgent,
    IRCAMCP,
    IRCAInteractiveAgent,
    BFAAgent,
    BFAMCP,
    BFAInteractiveAgent,
    create_gateway_app,
    BFASemanticRouter
)

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
