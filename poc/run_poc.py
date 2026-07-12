import subprocess
import time
import sys
import httpx
import os

print("=" * 70)
print("🚀 STARTING BFA / IRC-A PROOF OF CONCEPT (POC) ORCHESTRATOR...")
print("=" * 70)

# Set python path to current workspace so imports resolve correctly
os.environ["PYTHONPATH"] = os.getcwd()

# Start Gateway
print("\n[POC] Launching BFA Gateway on port 8000...")
gateway_proc = subprocess.Popen([sys.executable, "-u", "poc/gateway.py"])

# Start Agent
print("[POC] Launching CreditAdvisorAgent on port 8001...")
agent_proc = subprocess.Popen([sys.executable, "-u", "poc/agent.py"])

# Start MCP Server
print("[POC] Launching BankDatabaseMCP on port 8002...")
mcp_proc = subprocess.Popen([sys.executable, "-u", "poc/mcp_server.py"])

try:
    print("\n[POC] Waiting for services to boot up and respond...")
    
    # Wait for Gateway
    gateway_ok = False
    for i in range(15):
        try:
            with httpx.Client() as client:
                res = client.get("http://localhost:8000/")
                if res.status_code == 200:
                    gateway_ok = True
                    break
        except Exception:
            pass
        time.sleep(1)
        
    if not gateway_ok:
        print("[POC] Error: Gateway failed to respond on port 8000 after 15 seconds.")
        sys.exit(1)
        
    print("[POC] Gateway is UP.")
    
    # Wait for Agent
    agent_ok = False
    for i in range(15):
        try:
            with httpx.Client() as client:
                res = client.post("http://localhost:8001/", json={})
                agent_ok = True
                break
        except Exception:
            pass
        time.sleep(1)
        
    if not agent_ok:
        print("[POC] Error: Agent failed to respond on port 8001 after 15 seconds.")
        sys.exit(1)
        
    print("[POC] Agent is UP.")
    
    # Wait for MCP
    mcp_ok = False
    for i in range(15):
        try:
            with httpx.Client() as client:
                res = client.get("http://localhost:8002/tools")
                if res.status_code == 200:
                    mcp_ok = True
                    break
        except Exception:
            pass
        time.sleep(1)
        
    if not mcp_ok:
        print("[POC] Error: MCP Server failed to respond on port 8002 after 15 seconds.")
        sys.exit(1)
        
    print("[POC] MCP Server is UP.")
    
    # Give registration time to process
    print("[POC] Services are online. Giving 2 seconds for registrations to sync...")
    time.sleep(2)
    
    # -------------------------------------------------------------
    # FLOW 1: Verification of semantic routing resolves
    # -------------------------------------------------------------
    print("\n" + "-" * 60)
    print("🎯 FLOW 1: Verification of Semantic Index and Registrations")
    print("-" * 60)
    
    with httpx.Client() as client:
        # Check active skills registered in Gateway
        res_skills = client.get("http://localhost:8000/skills")
        print(f"Active Skills in Gateway Registry: {list(res_skills.json().keys())}")
        
        # Verify logical channel pre-filtering resolve
        res_resolve = client.get("http://localhost:8000/resolve?query=bank solvency score")
        print(f"Semantic Resolution matches: {res_resolve.json().get('best', {}).get('skill')}")

    # -------------------------------------------------------------
    # FLOW 2: Successful End-to-End P2P Invocation with signed DET
    # -------------------------------------------------------------
    print("\n" + "-" * 60)
    print("🎯 FLOW 2: Secure P2P Invocation with signed DET")
    print("-" * 60)
    
    with httpx.Client() as client:
        # JSON-RPC SendMessage to Agent
        rpc_payload = {
            "jsonrpc": "2.0",
            "method": "SendMessage",
            "params": {
                "message": {
                    "role": 1,
                    "message_id": "msg-001",
                    "context_id": "ctx-001",
                    "parts": [{"text": "calculate solvency rating for customer 722"}]
                }
            },
            "id": 1
        }
        headers = {"A2A-Version": "1.0"}
        res_agent = client.post("http://localhost:8001/", json=rpc_payload, headers=headers, timeout=10)
        print(f"Agent Response Payload: {res_agent.text}")

    # -------------------------------------------------------------
    # FLOW 3: Parameter Lockdown Block (Zero-Trust Enforcement)
    # -------------------------------------------------------------
    print("\n" + "-" * 60)
    print("🎯 FLOW 3: Parameter Lockdown Rejection")
    print("-" * 60)
    
    with httpx.Client() as client:
        # Try to invoke with "hack" keyword to trigger mismatched param comparison offline in MCP
        rpc_payload_hack = {
            "jsonrpc": "2.0",
            "method": "SendMessage",
            "params": {
                "message": {
                    "role": 1,
                    "message_id": "msg-002",
                    "context_id": "ctx-002",
                    "parts": [{"text": "calculate solvency rating for customer 722 hack"}]
                }
            },
            "id": 2
        }
        headers = {"A2A-Version": "1.0"}
        res_agent_hack = client.post("http://localhost:8001/", json=rpc_payload_hack, headers=headers, timeout=10)
        print(f"Agent Response Payload: {res_agent_hack.text}")

    # -------------------------------------------------------------
    # FLOW 4: Loop Protection Verification
    # -------------------------------------------------------------
    print("\n" + "-" * 60)
    print("🎯 FLOW 4: Trace-based Infinite Loop Mitigation")
    print("-" * 60)
    
    # We send a request to the Agent on port 8001 but inject a circular tracing visited list
    with httpx.Client() as client:
        rpc_payload_loop = {
            "jsonrpc": "2.0",
            "method": "SendMessage",
            "params": {
                "message": {
                    "role": 1,
                    "message_id": "msg-003",
                    "context_id": "ctx-003",
                    "parts": [{"text": "calculate solvency rating for customer 722"}]
                }
            },
            "id": 3
        }
        headers = {
            "X-Trace-Id": "tx-circular-check",
            "X-Visited-Nodes": "credit-advisor-agent,gateway",
            "A2A-Version": "1.0"
        }
        res_loop = client.post("http://localhost:8001/", json=rpc_payload_loop, headers=headers, timeout=10)
        print("Loop Execution Status Code (should be 409 Conflict):", res_loop.status_code)
        print("Loop Response Payload (should show recursion block details):", res_loop.text)

finally:
    print("\n" + "=" * 60)
    print("🧹 TERMINATING AND CLEANING UP SERVICES...")
    print("=" * 60)
    
    # Send teardown signals
    agent_proc.terminate()
    mcp_proc.terminate()
    gateway_proc.terminate()
    
    # Wait for completion
    agent_proc.wait()
    mcp_proc.wait()
    gateway_proc.wait()
    
    print("\n[POC] All processes terminated cleanly. FAISS registry index updated on disconnect.")
