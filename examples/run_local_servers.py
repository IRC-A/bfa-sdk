import os
import time
import subprocess
import httpx
import sys

def main():
    print("=== STARTING ALL BFA LOCAL BACKEND SERVERS ===")
    print("Press Ctrl+C to terminate all servers.")
    
    # Clean up previous persisted dynamic registry database for a fresh run
    if os.path.exists("bfa_registry_db.json"):
        os.remove("bfa_registry_db.json")
        print("Cleared previous dynamic registry database (bfa_registry_db.json).")

    # Set environment variables for local testing
    os.environ["BFA_USE_MOCK_EMBEDDINGS"] = "true"  # Use DummyEmbedder for offline demo
    
    # 1. Start BFA Gateway Server (Port 8000)
    print("Launching BFA Gateway Server on http://127.0.0.1:8000...")
    gateway_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "bfa_sdk.core.gateway:app", "--host", "127.0.0.1", "--port", "8000", "--log-level", "warning"]
    )
    
    # 2. Launch Mock MDBank MCP Server (Port 8001)
    print("Launching mock MDBank MCP Server on http://127.0.0.1:8001...")
    mcp_proc = subprocess.Popen(
        [sys.executable, "examples/mock_mdbank_mcp.py"]
    )
    
    # 3. Launch Mock Cuentas Agent Server (Port 8002)
    print("Launching mock Cuentas Agent Server on http://127.0.0.1:8002...")
    cuentas_proc = subprocess.Popen(
        [sys.executable, "examples/mock_cuentas_agent.py"]
    )
    
    # 4. Launch Mock Tarjetas Agent Server (Port 8003)
    print("Launching mock Tarjetas Agent Server on http://127.0.0.1:8003...")
    tarjetas_proc = subprocess.Popen(
        [sys.executable, "examples/mock_tarjetas_agent.py"]
    )
    
    # Wait for servers to spin up
    print("Waiting 4 seconds for servers to initialize...")
    time.sleep(4)
    
    # 5. DYNAMIC SELF-REGISTRATION (PUSH)
    gateway_url = "http://127.0.0.1:8000"
    print("\n--- Performing Dynamic Self-Registration ---")
    
    # Register MCP
    try:
        res = httpx.post(f"{gateway_url}/register/mcp", params={"url": "http://127.0.0.1:8001"})
        print(f"Registered MCP: {res.json().get('status')}")
    except Exception as e:
        print(f"MCP registration failed: {e}")

    # Register Cuentas Agent
    try:
        res = httpx.post(f"{gateway_url}/register/agent", params={"url": "http://127.0.0.1:8002"})
        print(f"Registered Cuentas: {res.json().get('status')}")
    except Exception as e:
        print(f"Cuentas Agent registration failed: {e}")

    # Register Tarjetas Agent
    try:
        res = httpx.post(f"{gateway_url}/register/agent", params={"url": "http://127.0.0.1:8003"})
        print(f"Registered Tarjetas: {res.json().get('status')}")
    except Exception as e:
        print(f"Tarjetas Agent registration failed: {e}")
        
    print("\nAll servers are running and registered! You can now start the frontend app.")
    print("Gateway API is available at: http://127.0.0.1:8000")
    print("Keep this terminal open.\n")

    try:
        # Keep the script running to hold the subprocesses alive
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nTerminating all local servers...")
    finally:
        gateway_proc.terminate()
        mcp_proc.terminate()
        cuentas_proc.terminate()
        tarjetas_proc.terminate()
        print("All servers stopped successfully.")

if __name__ == "__main__":
    main()
