# Copyright (c) 2026 Sandro G. All rights reserved.
# Licensed under AGPLv3 / Commercial Dual License.
# Transparent backward compatibility proxy module for bfa_gateway.router.search
import sys
import bfa_gateway.router.search

class _SearchModuleProxy(sys.modules[__name__].__class__):
    def __getattr__(self, name):
        if name.startswith('_'):
            return super().__getattr__(name)
        return getattr(bfa_gateway.router.search, name)

    def __setattr__(self, name, value):
        if name.startswith('_'):
            super().__setattr__(name, value)
        else:
            setattr(bfa_gateway.router.search, name, value)

    def __delattr__(self, name):
        if name.startswith('_'):
            super().__delattr__(name)
        else:
            try:
                delattr(bfa_gateway.router.search, name)
            except AttributeError:
                pass

    def __dir__(self):
        return dir(bfa_gateway.router.search)

sys.modules[__name__].__class__ = _SearchModuleProxy
