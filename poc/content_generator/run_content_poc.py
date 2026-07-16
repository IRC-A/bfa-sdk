# Copyright (c) 2026 Sandro G. All rights reserved.
# Licensed under AGPLv3 / Commercial Dual License.
import subprocess
import time
import sys
import httpx
import os

print("=" * 80)
print("🚀 STARTING BFA / IRC-A MULTI-AGENT CONTENT GENERATION POC...")
print("=" * 80)

# Set python path to current workspace so imports resolve correctly
os.environ["PYTHONPATH"] = os.getcwd()

# Clean up previous persisted dynamic registry database for a fresh run
if os.path.exists("bfa_registry_db.json"):
    try:
        os.remove("bfa_registry_db.json")
        print("[POC] Cleared previous dynamic registry database (bfa_registry_db.json).")
    except Exception as e:
        print(f"[POC] Warning: Could not clear previous registry database: {e}")

# Start Gateway (Port 8000)
print("\n[POC] Launching IRC-A Gateway on port 8000...")
gateway_proc = subprocess.Popen([sys.executable, "-u", "poc/gateway.py"])

try:
    print("\n[POC] Waiting for IRC-A Gateway to boot up...")
    
    # Wait for Gateway
    gateway_ok = False
    for i in range(15):
        try:
            with httpx.Client() as client:
                res = client.get("http://127.0.0.1:8000/")
                if res.status_code == 200:
                    gateway_ok = True
                    break
        except Exception:
            pass
        time.sleep(1)
        
    if not gateway_ok:
        print("[POC] Error: Gateway failed to respond on port 8000 after 15 seconds.")
        sys.exit(1)
    print("[POC] Gateway is UP. Now spawning agents and MCP servers...")

    # Start OrchestratorAgent (Port 8101)
    print("[POC] Launching OrchestratorAgent on port 8101...")
    orchestrator_proc = subprocess.Popen([sys.executable, "-u", "poc/content_generator/orchestrator_agent.py"])

    # Start WriterAgent (Port 8106)
    print("[POC] Launching WriterAgent on port 8106...")
    writer_proc = subprocess.Popen([sys.executable, "-u", "poc/content_generator/writer_agent.py"])

    # Start KeywordsMCP (Port 8102)
    print("[POC] Launching KeywordsMCP on port 8102...")
    mcp_proc = subprocess.Popen([sys.executable, "-u", "poc/content_generator/keywords_mcp.py"])

    # Start ReviewerAgent (Port 8103)
    print("[POC] Launching ReviewerAgent on port 8103...")
    reviewer_proc = subprocess.Popen([sys.executable, "-u", "poc/content_generator/reviewer_agent.py"])

    # Start ExtraAgent (Port 8104)
    print("[POC] Launching ExtraMarketingAgent on port 8104 (isolated)...")
    extra_proc = subprocess.Popen([sys.executable, "-u", "poc/content_generator/extra_agent.py"])

    # Start ResearchAgent (Port 8105)
    print("[POC] Launching ResearchAgent on port 8105...")
    research_proc = subprocess.Popen([sys.executable, "-u", "poc/content_generator/research_agent.py"])

    print("\n[POC] Waiting for agents and MCP servers to boot up...")
    
    # Wait for OrchestratorAgent (8101)
    orchestrator_ok = False
    for i in range(15):
        try:
            with httpx.Client() as client:
                res = client.get("http://127.0.0.1:8101/.well-known/agent-card.json")
                if res.status_code == 200:
                    orchestrator_ok = True
                    break
        except Exception:
            pass
        time.sleep(1)
        
    if not orchestrator_ok:
        print("[POC] Error: OrchestratorAgent failed to respond on port 8101.")
        sys.exit(1)
    print("[POC] OrchestratorAgent is UP.")

    # Wait for WriterAgent (8106)
    writer_ok = False
    for i in range(15):
        try:
            with httpx.Client() as client:
                res = client.get("http://127.0.0.1:8106/.well-known/agent-card.json")
                if res.status_code == 200:
                    writer_ok = True
                    break
        except Exception:
            pass
        time.sleep(1)
        
    if not writer_ok:
        print("[POC] Error: WriterAgent failed to respond on port 8106.")
        sys.exit(1)
    print("[POC] WriterAgent is UP.")

    # Wait for KeywordsMCP
    mcp_ok = False
    for i in range(15):
        try:
            with httpx.Client() as client:
                res = client.get("http://127.0.0.1:8102/tools")
                if res.status_code == 200:
                    mcp_ok = True
                    break
        except Exception:
            pass
        time.sleep(1)
        
    if not mcp_ok:
        print("[POC] Error: KeywordsMCP failed to respond on port 8102.")
        sys.exit(1)
    print("[POC] KeywordsMCP is UP.")

    # Wait for ReviewerAgent
    reviewer_ok = False
    for i in range(15):
        try:
            with httpx.Client() as client:
                res = client.get("http://127.0.0.1:8103/.well-known/agent-card.json")
                if res.status_code == 200:
                    reviewer_ok = True
                    break
        except Exception:
            pass
        time.sleep(1)
        
    if not reviewer_ok:
        print("[POC] Error: ReviewerAgent failed to respond on port 8103.")
        sys.exit(1)
    print("[POC] ReviewerAgent is UP.")

    # Wait for ExtraAgent
    extra_ok = False
    for i in range(15):
        try:
            with httpx.Client() as client:
                res = client.get("http://127.0.0.1:8104/.well-known/agent-card.json")
                if res.status_code == 200:
                    extra_ok = True
                    break
        except Exception:
            pass
        time.sleep(1)
    if not extra_ok:
        print("[POC] Warning: ExtraMarketingAgent failed to respond on port 8104.")
    else:
        print("[POC] ExtraMarketingAgent is UP (isolated, ready for manual registration).")

    # Wait for ResearchAgent
    research_ok = False
    for i in range(15):
        try:
            with httpx.Client() as client:
                res = client.get("http://127.0.0.1:8105/.well-known/agent-card.json")
                if res.status_code == 200:
                    research_ok = True
                    break
        except Exception:
            pass
        time.sleep(1)
    if not research_ok:
        print("[POC] Error: ResearchAgent failed to respond on port 8105.")
        sys.exit(1)
    print("[POC] ResearchAgent is UP.")

    # Give registration time to process
    print("[POC] Services are online. Giving 5 seconds for registrations to sync...")
    time.sleep(5)
    
    # -------------------------------------------------------------
    # FLOW 1: Verification of registration handshakes
    # -------------------------------------------------------------
    print("\n" + "-" * 70)
    print("🎯 FLOW 1: Verification of Semantic Index and Registrations")
    print("-" * 70)
    
    with httpx.Client() as client:
        res_skills = client.get("http://127.0.0.1:8000/skills")
        print(f"Active Registry Skills: {list(res_skills.json().keys())}")
        
        res_resolve = client.get("http://127.0.0.1:8000/resolve?query=used keywords for campaign camp-123")
        print(f"Semantic Resolution matches: {res_resolve.json().get('best', {}).get('skill')}")

    # -------------------------------------------------------------
    # FLOW 2: Successful End-to-End P2P used keyword check + A2A writing
    # -------------------------------------------------------------
    print("\n" + "-" * 70)
    print("🎯 FLOW 2: Secure P2P Keyword Audit & A2A Content Generation")
    print("-" * 70)
    
    with httpx.Client() as client:
        rpc_payload = {
            "jsonrpc": "2.0",
            "method": "SendMessage",
            "params": {
                "message": {
                    "role": 1,
                    "message_id": "msg-writer-001",
                    "context_id": "ctx-writer-001",
                    "parts": [{"text": "generate essay for campaign camp-123 on topic: AI Automation"}]
                }
            },
            "id": 1
        }
        headers = {"A2A-Version": "1.0"}
        res_writer = client.post("http://127.0.0.1:8101/", json=rpc_payload, headers=headers, timeout=60)
        print(f"WriterAgent Response Payload:\n{res_writer.json()['result']['message']['parts'][0]['text']}")

    # -------------------------------------------------------------
    # FLOW 3: Parameter Lockdown Block (Zero-Trust Enforcement)
    # -------------------------------------------------------------
    print("\n" + "-" * 70)
    print("🎯 FLOW 3: Parameter Lockdown Rejection")
    print("-" * 70)
    
    with httpx.Client() as client:
        # Hack scenario: Request essay for camp-123, but WriterAgent requests keywords for competitor camp-999
        rpc_payload_hack = {
            "jsonrpc": "2.0",
            "method": "SendMessage",
            "params": {
                "message": {
                    "role": 1,
                    "message_id": "msg-writer-002",
                    "context_id": "ctx-writer-002",
                    "parts": [{"text": "generate essay for campaign camp-123 on topic: AI Automation hack"}]
                }
            },
            "id": 2
        }
        headers = {"A2A-Version": "1.0"}
        res_writer_hack = client.post("http://127.0.0.1:8101/", json=rpc_payload_hack, headers=headers, timeout=60)
        print(f"WriterAgent Hack Response:\n{res_writer_hack.json()['result']['message']['parts'][0]['text']}")

    # -------------------------------------------------------------
    # FLOW 4: Trace-based Infinite Loop Mitigation
    # -------------------------------------------------------------
    print("\n" + "-" * 70)
    print("🎯 FLOW 4: Trace-based Circular Loop Mitigation")
    print("-" * 70)
    
    with httpx.Client() as client:
        # Trigger the loop on the ReviewerAgent
        rpc_payload_loop = {
            "jsonrpc": "2.0",
            "method": "SendMessage",
            "params": {
                "message": {
                    "role": 1,
                    "message_id": "msg-writer-003",
                    "context_id": "ctx-writer-003",
                    "parts": [{"text": "loop"}]
                }
            },
            "id": 3
        }
        headers = {"A2A-Version": "1.0"}
        res_reviewer_loop = client.post("http://127.0.0.1:8103/", json=rpc_payload_loop, headers=headers, timeout=60)
        print(f"ReviewerAgent Loop Call Response (should show recursive call blocked with 409):\n{res_reviewer_loop.json()['result']['message']['parts'][0]['text']}")

    # -------------------------------------------------------------
    # Visual Playground Active State
    # -------------------------------------------------------------
    print("\n" + "=" * 80)
    print("🚀 ALL AUTOMATED FLOWS COMPLETED SUCCESSFULLY!")
    print("=" * 80)
    print("\n[POC] The Visual Dashboard is active and running!")
    print("👉 Open your browser to: http://127.0.0.1:8101/")
    print("\n[POC] Press Ctrl+C to terminate all servers and exit.")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[POC] Shutting down...")

finally:
    print("\n" + "=" * 80)
    print("🧹 TERMINATING AND CLEANING UP SERVICES...")
    print("=" * 80)
    
    writer_proc.terminate()
    mcp_proc.terminate()
    reviewer_proc.terminate()
    extra_proc.terminate()
    research_proc.terminate()
    orchestrator_proc.terminate()
    gateway_proc.terminate()
    
    writer_proc.wait()
    mcp_proc.wait()
    reviewer_proc.wait()
    extra_proc.wait()
    research_proc.wait()
    orchestrator_proc.wait()
    gateway_proc.wait()
    
    print("\n[POC] All processes terminated cleanly. FAISS registry index updated on disconnect.")
