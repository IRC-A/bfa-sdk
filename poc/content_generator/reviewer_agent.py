import os
import uvicorn
import httpx
from dotenv import load_dotenv
from bfa_sdk.core.agent import BFAAgent
from a2a.server.agent_execution.context import RequestContext

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

@traceable(run_type="llm", name="Reviewer LLM Generation")
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

class ReviewerAgent(BFAAgent):
    def __init__(self):
        super().__init__(
            agent_id="reviewer-agent",
            name="Reviewer Agent",
            description="Reviews essay drafts and provides structured critiques.",
            tags=["reviewer", "reflection", "critique"],
            examples=["review draft", "critique essay"],
            url="http://127.0.0.1:8103"
        )

    async def run(self, user_message: str, context: RequestContext) -> str:
        """
        Processes writing drafts. Performs reflection, generates critiques.
        If loop simulation is triggered, attempts to call WriterAgent recursively.
        """
        # If loop simulation is requested in the message
        if "loop" in user_message.lower():
            # Attempt to call back WriterAgent at port 8101 creating a circular call chain
            async with httpx.AsyncClient() as client:
                rpc_payload = {
                    "jsonrpc": "2.0",
                    "method": "SendMessage",
                    "params": {
                        "message": {
                            "role": 1,
                            "message_id": "msg-loop-001",
                            "context_id": "ctx-loop-001",
                            "parts": [{"text": "Generate essay recursively"}]
                        }
                    },
                    "id": 200
                }
                
                # Propagate visited nodes list (Writer -> Reviewer -> Writer loop)
                headers = {
                    "A2A-Version": "1.0",
                    "X-Trace-Id": "tx-loop-check",
                    "X-Visited-Nodes": "writer-agent,reviewer-agent"
                }
                
                try:
                    res_loop = await client.post(
                        "http://127.0.0.1:8101/",
                        json=rpc_payload,
                        headers=headers,
                        timeout=5
                    )
                    # Should be blocked and return 409 Conflict
                    return f"Status: {res_loop.status_code}, Body: {res_loop.text}"
                except Exception as e:
                    return f"Loop call failed: {e}"

        # Standard reflection flow: check if real LLM is available
        prompt = (
            "Review this draft essay. Write a single, brief sentence suggesting one specific "
            f"constructive improvement for the text:\n\n{user_message}"
        )
        real_critique, prompt_tokens, comp_tokens = await generate_llm_content(prompt)
        
        if real_critique:
            critique = f"Critique (via LLM): {real_critique.strip()}"
        else:
            critique = (
                "Critique: The draft effectively addresses the topic but lacks specific "
                "marketing examples. Recommend adding a call-to-action."
            )
            prompt_tokens = len(user_message) // 4
            comp_tokens = len(critique) // 4

        return f"{critique}\n[METRICS: prompt_tokens={prompt_tokens}, completion_tokens={comp_tokens}]"

agent_instance = ReviewerAgent()
app = agent_instance.app

if __name__ == "__main__":
    uvicorn.run("reviewer_agent:app", host="127.0.0.1", port=8103, log_level="warning")
