# Copyright (c) 2026 Sandro G. All rights reserved.
# Licensed under AGPLv3 / Commercial Dual License.
"""
Gateway import helper. The BFA Gateway server logic has moved to the standalone 'bfa-gateway' package.
"""
try:
    from bfa_gateway.app import create_gateway_app, main
except ImportError:
    def create_gateway_app(*args, **kwargs):
        raise ImportError("BFA Gateway has been moved to the standalone 'bfa-gateway' package. Install with: pip install bfa-gateway")
    def main(*args, **kwargs):
        raise ImportError("BFA Gateway has been moved to the standalone 'bfa-gateway' package. Install with: pip install bfa-gateway")
