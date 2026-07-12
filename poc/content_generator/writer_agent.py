import os
import re
import json
import uvicorn
import httpx
from dotenv import load_dotenv
from bfa_sdk.core.agent import BFAAgent
from a2a.server.agent_execution.context import RequestContext
from starlette.responses import HTMLResponse, JSONResponse

# Load environmental configurations
load_dotenv()

# Defensive Langsmith integration for real-time cloud tracing
try:
    from langsmith import traceable
except ImportError:
    # Dummy fallback decorator if package is missing
    def traceable(*args, **kwargs):
        return lambda func: func

# Configure environmental options for BFA Gateway routing
os.environ["IRCA_CHANNELS"] = "#content"
os.environ["BFA_GATEWAY_URL"] = "http://127.0.0.1:8000"

@traceable(run_type="llm", name="Writer LLM Generation")
async def generate_llm_content(prompt: str) -> tuple[str, int, int]:
    """Helper to query the configured LLM provider and track token usage."""
    provider = os.getenv("LLM_PROVIDER", "").lower().strip()
    
    # Auto-detect default provider if not explicitly set
    if not provider:
        if os.getenv("OPENAI_API_KEY", "").strip().strip("'\""):
            provider = "openai"
        elif (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY", "")).strip().strip("'\""):
            provider = "gemini"
        else:
            provider = "mock"

    text = ""
    prompt_tokens = len(prompt) // 4
    comp_tokens = 0

    # 1. OpenAI Provider
    if provider == "openai":
        openai_key = os.getenv("OPENAI_API_KEY", "").strip().strip("'\"")
        model = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip().strip("'\"")
        if openai_key:
            try:
                url = "https://api.openai.com/v1/chat/completions"
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {openai_key}"
                }
                json_payload = {
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.7
                }
                async with httpx.AsyncClient() as client:
                    res = await client.post(url, json=json_payload, headers=headers, timeout=10)
                    if res.status_code == 200:
                        data = res.json()
                        text = data["choices"][0]["message"]["content"]
                        usage = data.get("usage", {})
                        prompt_tokens = usage.get("prompt_tokens", len(prompt) // 4)
                        comp_tokens = usage.get("completion_tokens", len(text) // 4)
                    else:
                        print(f"OpenAI API Error: {res.status_code} - {res.text}")
            except Exception as e:
                print(f"OpenAI Call failed: {e}")

    # 2. Gemini Provider
    elif provider == "gemini":
        gemini_key = (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY", "")).strip().strip("'\"")
        if gemini_key:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_key}"
                async with httpx.AsyncClient() as client:
                    res = await client.post(
                        url,
                        json={"contents": [{"parts": [{"text": prompt}]}]},
                        headers={"Content-Type": "application/json"},
                        timeout=10
                    )
                    if res.status_code == 200:
                        data = res.json()
                        text = data["candidates"][0]["content"]["parts"][0]["text"]
                        usage = data.get("usageMetadata", {})
                        prompt_tokens = usage.get("promptTokenCount", len(prompt) // 4)
                        comp_tokens = usage.get("candidatesTokenCount", len(text) // 4)
                    else:
                        print(f"Gemini API Error: {res.status_code} - {res.text}")
            except Exception as e:
                print(f"Gemini call failed: {e}")

    # 3. Ollama Provider (Local LLM)
    elif provider == "ollama":
        ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434").strip().strip("'\"")
        ollama_model = os.getenv("OLLAMA_MODEL", "llama3").strip().strip("'\"")
        try:
            url = f"{ollama_host.rstrip('/')}/api/chat"
            json_payload = {
                "model": ollama_model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False
            }
            async with httpx.AsyncClient() as client:
                res = await client.post(url, json=json_payload, timeout=15)
                if res.status_code == 200:
                    data = res.json()
                    text = data["message"]["content"]
                    prompt_tokens = data.get("prompt_eval_count", len(prompt) // 4)
                    comp_tokens = data.get("eval_count", len(text) // 4)
                else:
                    print(f"Ollama API Error: {res.status_code} - {res.text}")
        except Exception as e:
            print(f"Ollama call failed: {e}")

    # Log custom LLM metrics to Langsmith if package is active and environment variables are set
    try:
        from langsmith import get_current_run_tree
        rt = get_current_run_tree()
        if rt:
            rt.metadata.update({
                "ls_provider": provider,
                "ls_model_name": os.getenv("OPENAI_MODEL", "gpt-4o-mini") if provider == "openai" else provider
            })
            usage_dict = {
                "input_tokens": prompt_tokens,
                "output_tokens": comp_tokens,
                "total_tokens": prompt_tokens + comp_tokens
            }
            # Support older Langsmith SDK versions (like 0.10.x used locally)
            if not isinstance(rt.extra, dict):
                rt.extra = {}
            rt.extra["usage_metadata"] = usage_dict
            
            # Support newer Langsmith SDK versions
            try:
                rt.usage_metadata = usage_dict
            except:
                pass
    except Exception as e:
        pass

    return text, prompt_tokens, comp_tokens

class WriterAgent(BFAAgent):
    def __init__(self):
        super().__init__(
            agent_id="writer-agent",
            name="Writer Agent",
            description="Generates campaign articles while avoiding duplicate keywords.",
            tags=["writer", "content", "essay"],
            examples=["write article", "generate essay for campaign"],
            url="http://127.0.0.1:8101"
        )

    async def run(self, user_message: str, context: RequestContext) -> str:
        """
        Processes client request. Queries the KeywordsMCP server for already used keywords,
        drafts an essay excluding them, and submits the draft to the ReviewerAgent via A2A.
        """
        # Parse campaign_id and topic
        campaign_match = re.search(r"campaign\s+(\S+)", user_message, re.IGNORECASE)
        topic_match = re.search(r"topic:\s*(.*)", user_message, re.IGNORECASE)

        campaign_id = campaign_match.group(1) if campaign_match else "camp-123"
        
        # Smarker topic extraction
        if topic_match:
            topic = topic_match.group(1).strip()
        else:
            clean_msg = re.sub(r"generate\s+essay\s+for\s+campaign\s+\S+", "", user_message, flags=re.IGNORECASE).strip()
            clean_msg = re.sub(r"campaign\s+\S+", "", clean_msg, flags=re.IGNORECASE).strip()
            topic = clean_msg if clean_msg else "AI Automation"

        # Check for parameter lockdown simulation (hack mode)
        target_campaign_id = campaign_id
        if "hack" in user_message.lower():
            target_campaign_id = "camp-999"

        # Check if the user is asking for a slogan or promotional content
        is_slogan = any(kw in user_message.lower() for kw in ["slogan", "marketing", "promo"])

        provider = os.getenv("LLM_PROVIDER", "").lower().strip() or "openai"
        total_prompt_tokens = 0
        total_comp_tokens = 0
        
        # Initialize execution trace logs
        logs = []
        logs.append("🎬 [START] Initiating collaborative multi-agent execution pipeline...")

        # 1. Gateway Discovery: Resolve used keywords capability
        try:
            async with httpx.AsyncClient() as client:
                logs.append(f"🔍 [STEP 1] Querying BFA Gateway (:8000) to discover a tool for campaign '{campaign_id}'...")
                discover_res = await client.post(
                    "http://127.0.0.1:8000/discover",
                    params={"query": f"get used keywords for campaign {campaign_id}"},
                    json={"session_token": self.session_token},
                    timeout=5
                )

                if discover_res.status_code != 200:
                    return f"Gateway Discovery Failed: {discover_res.json().get('detail', 'Unknown error')}"

                discovery_data = discover_res.json()
                det_token = discovery_data["det"]
                target_url = discovery_data["url"]
                
                logs.append(f"   ↳ [SUCCESS] Gateway matched capability to: Keywords MCP ({target_url})")

                # 2. P2P tool call to KeywordsMCP sending the DET token
                logs.append(f"⚙️ [STEP 2] Calling 'get_used_keywords' on Keywords MCP ({target_url}) via P2P protocol...")
                mcp_res = await client.post(
                    f"{target_url.rstrip('/')}/tools",
                    json={
                        "tool": "get_used_keywords",
                        "arguments": {
                            "delegated_token": det_token,
                            "campaign_id": target_campaign_id
                        }
                    },
                    timeout=5
                )

                if mcp_res.status_code != 200:
                    return f"MCP Tool Invocation Rejected: {mcp_res.text}"

                # Parse the keywords used
                mcp_data = json.loads(mcp_res.json())
                used_keywords = mcp_data.get("used_keywords", [])
                
                logs.append(f"   ↳ [SUCCESS] Keywords MCP returned blacklisted keywords: {used_keywords}")

                # Check if we should dynamically delegate the slogan request to the marketing agent
                delegated_text = None
                if is_slogan:
                    logs.append("🔍 [STEP 2.5] Slogan request detected. Querying BFA Gateway for slogan capability...")
                    try:
                        slogan_discover = await client.post(
                            "http://127.0.0.1:8000/discover",
                            params={"query": "generate slogan for product"},
                            json={"session_token": self.session_token},
                            timeout=5
                        )
                        if slogan_discover.status_code == 200:
                            slogan_data = slogan_discover.json()
                            slogan_url = slogan_data["url"]
                            
                            logs.append(f"   ↳ [MATCH] Gateway matched capability to: Extra Marketing Agent ({slogan_url})")
                            logs.append(f"🚀 [A2A DELEGATION] Routing slogan generation to Extra Marketing Agent ({slogan_url}) via A2A protocol...")
                            
                            # Construct A2A message payload
                            rpc_payload = {
                                "jsonrpc": "2.0",
                                "method": "SendMessage",
                                "params": {
                                    "message": {
                                        "role": 1,
                                        "message_id": "msg-a2a-slogan-001",
                                        "context_id": "ctx-a2a-slogan-001",
                                        "parts": [{"text": topic}]
                                    }
                                },
                                "id": 101
                            }
                            headers = {
                                "A2A-Version": "1.0",
                                "X-Visited-Nodes": "writer-agent"
                            }
                            slogan_res = await client.post(slogan_url, json=rpc_payload, headers=headers, timeout=10)
                            if slogan_res.status_code == 200:
                                raw_slogan_resp = slogan_res.json()["result"]["message"]["parts"][0]["text"]
                                s_match = re.search(r"\[METRICS:\s*prompt_tokens=(\d+),\s*completion_tokens=(\d+)\]", raw_slogan_resp)
                                if s_match:
                                    s_p_tok = int(s_match.group(1))
                                    s_c_tok = int(s_match.group(2))
                                    delegated_text = raw_slogan_resp.split("\n[METRICS:")[0].strip()
                                    total_prompt_tokens += s_p_tok
                                    total_comp_tokens += s_c_tok
                                else:
                                    delegated_text = raw_slogan_resp
                                
                                logs.append(f"   ↳ [SUCCESS] Extra Marketing Agent generated slogan: \"{delegated_text}\"")
                            else:
                                logs.append(f"   ⚠️ [ERROR] Slogan agent HTTP {slogan_res.status_code}. Falling back to local generation.")
                        else:
                            logs.append("   ⚠️ [NO MATCH] Gateway found no active marketing agent. Falling back to local generation.")
                    except Exception as e:
                        logs.append(f"   ⚠️ [ERROR] Slogan agent communication failed: {e}. Falling back to local generation.")

                # 3. Content Generation
                if delegated_text:
                    draft = delegated_text
                    outline = f"Plan: Slogan for '{topic}' avoiding keywords {used_keywords}."
                    logs.append("✍️ [STEP 3] Slogan retrieved from delegated agent. Skipping local drafting.")
                else:
                    outline = f"Plan: Essay on '{topic}' avoiding keywords {used_keywords}."
                    llm_prompt = (
                        f"Write a short, engaging 2-paragraph essay about '{topic}'. "
                        f"Crucial rule: You MUST NOT use any of these words: {used_keywords}. "
                        "Write the essay content directly without introductory remarks or meta-text."
                    )
                    logs.append(f"✍️ [STEP 3] Calling Writer Agent LLM ({provider}) to draft initial essay...")
                    real_draft, p_tok1, c_tok1 = await generate_llm_content(llm_prompt)
                    total_prompt_tokens += p_tok1
                    total_comp_tokens += c_tok1

                    if real_draft:
                        draft = real_draft.strip()
                    else:
                        draft = f"Draft essay for topic: '{topic}' without repeating used campaign terms."
                        total_comp_tokens += len(draft) // 4

                # 4. A2A call to ReviewerAgent for critique
                rpc_payload = {
                    "jsonrpc": "2.0",
                    "method": "SendMessage",
                    "params": {
                        "message": {
                            "role": 1,
                            "message_id": "msg-a2a-001",
                            "context_id": "ctx-a2a-001",
                            "parts": [{"text": f"Audit this draft for topic '{topic}':\n{draft}"}]
                        }
                    },
                    "id": 100
                }
                
                # Propagate visited nodes tracking headers (standard BFA loop trace)
                headers = {
                    "A2A-Version": "1.0",
                    "X-Visited-Nodes": "writer-agent"
                }

                logs.append("🤝 [STEP 4] Sending initial draft to Reviewer Agent (http://127.0.0.1:8103) via A2A protocol for critique...")
                rev_res = await client.post(
                    "http://127.0.0.1:8103/",
                    json=rpc_payload,
                    headers=headers,
                    timeout=5
                )

                if rev_res.status_code != 200:
                    return f"A2A Review Request Failed: {rev_res.text}"

                rev_data = rev_res.json()
                raw_critique = rev_data["result"]["message"]["parts"][0]["text"]

                # Parse reviewer tokens from A2A payload
                reviewer_prompt_tokens = 0
                reviewer_comp_tokens = 0
                metrics_match = re.search(
                    r"\[METRICS:\s*prompt_tokens=(\d+),\s*completion_tokens=(\d+)\]",
                    raw_critique
                )
                if metrics_match:
                    reviewer_prompt_tokens = int(metrics_match.group(1))
                    reviewer_comp_tokens = int(metrics_match.group(2))
                    critique = raw_critique.split("\n[METRICS:")[0].strip()
                else:
                    critique = raw_critique

                total_prompt_tokens += reviewer_prompt_tokens
                total_comp_tokens += reviewer_comp_tokens
                
                logs.append(f"   ↳ [SUCCESS] Reviewer Agent returned review critique:\n     \"{critique}\"")

                # 5. Final Refinement incorporating critique
                refinement_prompt = (
                    f"Refine this initial draft:\n{draft}\n\n"
                    f"Incorporate this review critique:\n{critique}\n\n"
                    "Provide only the updated refined text directly."
                )
                
                logs.append(f"✨ [STEP 5] Calling Writer Agent LLM ({provider}) to refine the draft based on peer critique...")
                real_final, p_tok2, c_tok2 = await generate_llm_content(refinement_prompt)
                total_prompt_tokens += p_tok2
                total_comp_tokens += c_tok2

                if real_final:
                    final_essay = real_final.strip()
                else:
                    final_essay = f"Refined essay on '{topic}' resolving critique: '{critique}'."
                    total_comp_tokens += len(final_essay) // 4

                logs.append("🏁 [FINISH] Collaborative multi-agent workflow completed successfully.")

                final_output = (
                    "=== Multi-Agent Execution Steps & Route Trace ===\n"
                    + "\n".join(logs) + "\n\n"
                    f"=== Outlining & Drafting ===\n{outline}\n\n"
                    f"=== Initial Draft ===\n{draft}\n\n"
                    f"=== Review Critique received ===\n{critique}\n\n"
                    f"=== Final Refined Essay ===\n{final_essay}\n"
                    f"[TOTAL_METRICS: prompt_tokens={total_prompt_tokens}, completion_tokens={total_comp_tokens}]"
                )

                # Report tokens dynamically to BFA Gateway for centralized counter visibility
                try:
                    await client.post(
                        "http://127.0.0.1:8000/report-tokens",
                        json={"prompt_tokens": total_prompt_tokens, "completion_tokens": total_comp_tokens},
                        timeout=2
                    )
                except Exception as e:
                    print(f"BFAAgent Warning: Failed to report tokens to Gateway: {e}")

                return final_output

        except Exception as e:
            return f"Error executing Multi-Agent content flow: {e}"

agent_instance = WriterAgent()
app = agent_instance.app

# Serve Visualizer HTML Dashboard
async def serve_dashboard(request):
    template_path = os.path.join(os.path.dirname(__file__), "templates", "index.html")
    if os.path.exists(template_path):
        with open(template_path, "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())
    return HTMLResponse("<h1>Visualizer Dashboard Template Not Found</h1>", status_code=404)

# Endpoint to check which API Key is loaded in the .env file
async def api_status(request):
    provider = os.getenv("LLM_PROVIDER", "").lower().strip()
    if not provider:
        if os.getenv("OPENAI_API_KEY", "").strip().strip("'\""):
            provider = "openai"
        elif (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY", "")).strip().strip("'\""):
            provider = "gemini"
        else:
            provider = "mock"
    return JSONResponse({"provider": provider})

# Proxy endpoint to check online status of all registered nodes without browser CORS issues
async def get_nodes_status(request):
    gateway_online = False
    status_list = []
    try:
        async with httpx.AsyncClient() as client:
            try:
                res_gw = await client.get("http://127.0.0.1:8000/", timeout=1)
                if res_gw.status_code == 200:
                    gateway_online = True
            except:
                pass
            
            if gateway_online:
                res = await client.get("http://127.0.0.1:8000/skills", timeout=2)
                if res.status_code == 200:
                    skills = res.json()
                    unique_nodes = {}
                    for item in skills.values():
                        url = item.get("url") or item.get("server_url")
                        if not url:
                            continue
                        
                        port = ""
                        try:
                            from urllib.parse import urlparse
                            u = urlparse(url)
                            port = f"(:{u.port})" if u.port else ""
                        except:
                            pass
                        
                        clean_url = url.rstrip('/')
                        if item.get("type") == "agent":
                            unique_nodes[clean_url] = {
                                "name": f"{item.get('name', 'Agent')} {port}",
                                "check_url": f"{clean_url}/.well-known/agent-card.json"
                            }
                        else:
                            server_name = "Keywords MCP" if item.get("name") in ["get_used_keywords", "reserve_keyword"] else "MCP Server"
                            unique_nodes[clean_url] = {
                                "name": f"{server_name} {port}",
                                "check_url": f"{clean_url}/tools"
                            }
                    
                    # Check online status of each node server-side
                    for clean_url, node in unique_nodes.items():
                        node_online = False
                        try:
                            test_res = await client.get(node["check_url"], timeout=1)
                            if test_res.status_code == 200:
                                node_online = True
                        except:
                            pass
                        status_list.append({
                            "name": node["name"],
                            "online": node_online
                        })
    except Exception as e:
        print(f"Error checking nodes status: {e}")
    
    return JSONResponse({
        "gateway_online": gateway_online,
        "nodes": status_list
    })

# Proxy route to pull skills list from BFA Gateway server-side (prevents browser CORS errors)
async def get_gateway_skills(request):
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get("http://127.0.0.1:8000/skills", timeout=2)
            if res.status_code == 200:
                return JSONResponse(res.json())
            return JSONResponse({"error": f"Gateway returned {res.status_code}"}, status_code=res.status_code)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

# Proxy route to pull token metrics from BFA Gateway server-side (prevents browser CORS errors)
async def get_gateway_token_metrics(request):
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get("http://127.0.0.1:8000/token-metrics", timeout=2)
            if res.status_code == 200:
                return JSONResponse(res.json())
            return JSONResponse({"error": f"Gateway returned {res.status_code}"}, status_code=res.status_code)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

# Action trigger endpoint to run the different POC flows
async def run_visual_flow(request):
    flow_type = request.path_params.get("flow_type")
    body = await request.json()
    query_text = body.get("query", "")
    
    async with httpx.AsyncClient() as client:
        headers = {"A2A-Version": "1.0"}
        
        if flow_type == "normal":
            rpc_payload = {
                "jsonrpc": "2.0",
                "method": "SendMessage",
                "params": {
                    "message": {
                        "role": 1,
                        "message_id": "visual-msg-1",
                        "context_id": "visual-ctx-1",
                        "parts": [{"text": query_text}]
                    }
                },
                "id": 1
            }
            res = await client.post("http://127.0.0.1:8101/", json=rpc_payload, headers=headers, timeout=30)
            if res.status_code == 200:
                res_data = res.json()
                if "error" in res_data:
                    return JSONResponse({"error": res_data["error"]["message"]})
                
                raw_result = res_data["result"]["message"]["parts"][0]["text"]
                total_prompt = 0
                total_comp = 0
                
                metrics_match = re.search(
                    r"\[TOTAL_METRICS:\s*prompt_tokens=(\d+),\s*completion_tokens=(\d+)\]",
                    raw_result
                )
                if metrics_match:
                    total_prompt = int(metrics_match.group(1))
                    total_comp = int(metrics_match.group(2))
                    result_text = raw_result.split("[TOTAL_METRICS:")[0].strip()
                else:
                    result_text = raw_result
                
                return JSONResponse({
                    "result": result_text,
                    "tokens": {
                        "prompt_tokens": total_prompt,
                        "completion_tokens": total_comp,
                        "total_tokens": total_prompt + total_comp
                    }
                })
            return JSONResponse({"error": f"HTTP Error {res.status_code}: {res.text}"})
            
        elif flow_type == "hack":
            rpc_payload = {
                "jsonrpc": "2.0",
                "method": "SendMessage",
                "params": {
                    "message": {
                        "role": 1,
                        "message_id": "visual-msg-2",
                        "context_id": "visual-ctx-2",
                        "parts": [{"text": f"{query_text} hack"}],
                    }
                },
                "id": 2
            }
            res = await client.post("http://127.0.0.1:8101/", json=rpc_payload, headers=headers, timeout=30)
            if res.status_code == 200:
                res_data = res.json()
                if "error" in res_data:
                    return JSONResponse({"error": res_data["error"]["message"]})
                
                raw_result = res_data["result"]["message"]["parts"][0]["text"]
                return JSONResponse({
                    "result": raw_result,
                    "tokens": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
                })
            return JSONResponse({"error": f"HTTP Error {res.status_code}: {res.text}"})
            
        elif flow_type == "loop":
            rpc_payload = {
                "jsonrpc": "2.0",
                "method": "SendMessage",
                "params": {
                    "message": {
                        "role": 1,
                        "message_id": "visual-msg-3",
                        "context_id": "visual-ctx-3",
                        "parts": [{"text": "loop"}]
                    }
                },
                "id": 3
            }
            res = await client.post("http://127.0.0.1:8103/", json=rpc_payload, headers=headers, timeout=30)
            if res.status_code == 200:
                res_data = res.json()
                if "error" in res_data:
                    return JSONResponse({"result": f"Status: 409, Body: {json.dumps(res_data)}"})
                
                raw_result = res_data["result"]["message"]["parts"][0]["text"]
                return JSONResponse({
                    "result": raw_result,
                    "tokens": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
                })
            return JSONResponse({"result": f"Status: {res.status_code}, Body: {res.text}"})

from starlette.routing import Route
app.routes.append(Route("/", serve_dashboard, methods=["GET"]))
app.routes.append(Route("/api-status", api_status, methods=["GET"]))
app.routes.append(Route("/api-status/nodes", get_nodes_status, methods=["GET"]))
app.routes.append(Route("/api/gateway/skills", get_gateway_skills, methods=["GET"]))
app.routes.append(Route("/api/gateway/token-metrics", get_gateway_token_metrics, methods=["GET"]))
app.routes.append(Route("/run-flow/{flow_type}", run_visual_flow, methods=["POST"]))

if __name__ == "__main__":
    uvicorn.run("writer_agent:app", host="127.0.0.1", port=8101, log_level="warning")
