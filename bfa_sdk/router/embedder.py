# Copyright (c) 2026 Sandro G. All rights reserved.
# Licensed under AGPLv3 / Commercial Dual License.
# Transparent backward compatibility proxy module for bfa_gateway.router.embedder
import sys
import bfa_gateway.router.embedder

class _EmbedderModuleProxy(sys.modules[__name__].__class__):
    def __getattr__(self, name):
        if name.startswith('_'):
            return super().__getattr__(name)
        return getattr(bfa_gateway.router.embedder, name)

    def __setattr__(self, name, value):
        if name.startswith('_'):
            super().__setattr__(name, value)
        else:
            setattr(bfa_gateway.router.embedder, name, value)

    def __dir__(self):
        return dir(bfa_gateway.router.embedder)

sys.modules[__name__].__class__ = _EmbedderModuleProxy
