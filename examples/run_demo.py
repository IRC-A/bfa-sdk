import os
import time
import subprocess
import httpx
import sys

def main():
    print("=== START MDBANK BFA SEMANTIC ROUTER DEMO ===")
    
    # Clean up previous persisted dynamic registry database for a fresh test run
    if os.path.exists("bfa_registry_db.json"):
        os.remove("bfa_registry_db.json")
        print("Cleared previous dynamic registry database (bfa_registry_db.json) for clean run.")

    # 1. Start BFA Gateway Server FIRST (Port 8000)
    # Notice: We do NOT define any environment variables (BFA_AGENT_ENDPOINTS, BFA_MCP_ENDPOINTS)
    # The BFA will start with an empty index, and mock servers will register dynamically!
    os.environ["BFA_USE_MOCK_EMBEDDINGS"] = "true"  # Use DummyEmbedder for fast offline demo
    
    print("Launching BFA Gateway Server on port 8000...")
    from bfa_sdk.core.gateway import create_gateway_app
    import uvicorn
    import threading
    
    app = create_gateway_app()
    
    def run_gateway():
        uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
        
    gateway_thread = threading.Thread(target=run_gateway, daemon=True)
    gateway_thread.start()
    
    time.sleep(2)  # Wait for gateway to bind
    gateway_url = "http://127.0.0.1:8000"

    # 2. Launch Mock MDBank MCP Server (Port 8001)
    print("Launching mock MDBank MCP Server on port 8001...")
    mcp_proc = subprocess.Popen(
        [sys.executable, "examples/mock_mdbank_mcp.py"]
    )
    
    # 3. Launch Mock Cuentas Agent Server (Port 8002)
    print("Launching mock Cuentas Agent Server on port 8002...")
    cuentas_proc = subprocess.Popen(
        [sys.executable, "examples/mock_cuentas_agent.py"]
    )
    
    # 4. Launch Mock Tarjetas Agent Server (Port 8003)
    print("Launching mock Tarjetas Agent Server on port 8003...")
    tarjetas_proc = subprocess.Popen(
        [sys.executable, "examples/mock_tarjetas_agent.py"]
    )
    
    # 4b. Launch Mock Clima Agent Server (Port 8004)
    print("Launching mock Clima Agent Server on port 8004...")
    clima_proc = subprocess.Popen(
        [sys.executable, "examples/mock_clima_agent.py"]
    )
    
    # Wait for servers to spin up
    print("Waiting 4 seconds for mock servers to initialize...")
    time.sleep(4)
    
    # 5. DYNAMIC SELF-REGISTRATION (PUSH ROUTING)
    # We call the BFA register endpoints to simulate CITIBANK dynamic plugin addition
    print("\n--- SIMULATING RUNTIME PLUG-AND-PLAY REGISTRATION ---")
    
    # Register MCP
    print("Registering MDBank MCP (http://127.0.0.1:8001)...")
    try:
        res = httpx.post(f"{gateway_url}/register/mcp", params={"url": "http://127.0.0.1:8001"})
        print(f"BFA Response: {res.json()}")
    except Exception as e:
        print(f"MCP registration failed: {e}")

    # Register Cuentas Agent
    print("Registering Cuentas Agent (http://127.0.0.1:8002)...")
    try:
        res = httpx.post(f"{gateway_url}/register/agent", params={"url": "http://127.0.0.1:8002"})
        print(f"BFA Response: {res.json()}")
    except Exception as e:
        print(f"Cuentas Agent registration failed: {e}")

    # Register Tarjetas Agent
    print("Registering Tarjetas Agent (http://127.0.0.1:8003)...")
    try:
        res = httpx.post(f"{gateway_url}/register/agent", params={"url": "http://127.0.0.1:8003"})
        print(f"BFA Response: {res.json()}")
    except Exception as e:
        print(f"Tarjetas Agent registration failed: {e}")
        
    # Register Clima Agent
    print("Registering Clima Agent (http://127.0.0.1:8004)...")
    try:
        res = httpx.post(f"{gateway_url}/register/agent", params={"url": "http://127.0.0.1:8004"})
        print(f"BFA Response: {res.json()}")
    except Exception as e:
        print(f"Clima Agent registration failed: {e}")
        
    print("\nDiscovery completed dynamically! FAISS Index rebuilt in real-time.")

    # 6. Execute Semantic Resolution Queries
    print("\n--- TEST 1: Semantic Agent Resolution (Cuentas) ---")
    query_1 = "quiero abrir una cuenta corriente o caja de ahorro"
    print(f"Query: '{query_1}'")
    try:
        res = httpx.get(f"{gateway_url}/resolve/agents", params={"query": query_1})
        print(f"Status: {res.status_code}")
        print("Match Result:")
        print(res.json())
    except Exception as e:
        print(f"Test failed: {e}")
        
    print("\n--- TEST 2: Semantic Agent Resolution (Tarjetas) ---")
    query_2 = "necesito solicitar un plastico de credito gold o black"
    print(f"Query: '{query_2}'")
    try:
        res = httpx.get(f"{gateway_url}/resolve/agents", params={"query": query_2})
        print(f"Status: {res.status_code}")
        print("Match Result:")
        print(res.json())
    except Exception as e:
        print(f"Test failed: {e}")

    print("\n--- TEST 3: Semantic Tool Resolution (Consultar Cuenta) ---")
    query_3 = "ver mi saldo disponible por favor"
    print(f"Query: '{query_3}'")
    try:
        res = httpx.get(f"{gateway_url}/resolve/tools", params={"query": query_3})
        print(f"Status: {res.status_code}")
        print("Match Result:")
        print(res.json())
    except Exception as e:
        print(f"Test failed: {e}")

    print("\n--- TEST 4: Semantic Tool Resolution (Solicitar Tarjeta) ---")
    query_4 = "pedir una tarjeta nueva"
    print(f"Query: '{query_4}'")
    try:
        res = httpx.get(f"{gateway_url}/resolve/tools", params={"query": query_4})
        print(f"Status: {res.status_code}")
        print("Match Result:")
        print(res.json())
    except Exception as e:
        print(f"Test failed: {e}")

    print("\n--- TEST 5: Dynamic Agent Invocation (Routing to Cuentas) ---")
    query_5 = "quiero abrir una cuenta corriente"
    print(f"Invoking best agent for: '{query_5}'")
    try:
        rpc_payload = {
            "jsonrpc": "2.0",
            "method": "agent.execute",
            "params": {
                "user_input": {
                    "text": query_5
                }
            },
            "id": 1
        }
        res = httpx.post(f"{gateway_url}/invoke", params={"query": query_5}, json=rpc_payload)
        print(f"Status: {res.status_code}")
        print("Response from routed agent:")
        print(res.json())
    except Exception as e:
        print(f"Test failed: {e}")

    print("\n--- TEST 6: Dynamic Agent Invocation (Routing to Clima) ---")
    query_6 = "temperatura en madrid"
    print(f"Invoking best agent for: '{query_6}'")
    try:
        rpc_payload = {
            "jsonrpc": "2.0",
            "method": "agent.execute",
            "params": {
                "user_input": {
                    "text": query_6
                }
            },
            "id": 1
        }
        res = httpx.post(f"{gateway_url}/invoke", params={"query": query_6}, json=rpc_payload)
        print(f"Status: {res.status_code}")
        print("Response from routed agent:")
        print(res.json())
    except Exception as e:
        print(f"Test failed: {e}")

    # Cleanup subprocesses
    print("\nShutting down mock subprocesses...")
    mcp_proc.terminate()
    cuentas_proc.terminate()
    tarjetas_proc.terminate()
    clima_proc.terminate()
    print("Demo execution finished.")

if __name__ == "__main__":
    main()
