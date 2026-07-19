import pytest

@pytest.fixture(autouse=True)
def clear_global_router_registry():
    """
    Autouse fixture that clears the global gateway ROUTER registry 
    and index before and after every test to prevent test pollution.
    """
    import bfa_sdk.core.gateway as gateway_mod
    
    # Pre-test cleanup
    if getattr(gateway_mod, "ROUTER", None) is not None:
        gateway_mod.ROUTER.registry.clear()
        gateway_mod.ROUTER.index = None
        gateway_mod.ROUTER.index_keys = []
        
    yield
    
    # Post-test cleanup
    if getattr(gateway_mod, "ROUTER", None) is not None:
        gateway_mod.ROUTER.registry.clear()
        gateway_mod.ROUTER.index = None
        gateway_mod.ROUTER.index_keys = []
