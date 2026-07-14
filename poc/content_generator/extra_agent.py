import os
import uvicorn
import httpx
from dotenv import load_dotenv
from bfa_sdk.core.agent import BFAAgent
from a2a.server.agent_execution.context import RequestContext

load_dotenv()

# Defensive Langsmith integration for real-time cloud tracing
try:
    from langsmith import traceable
except ImportError:
    # Dummy fallback decorator if package is missing
    def traceable(*args, **kwargs):
        return lambda func: func

# Configure environmental options for BFA routing
os.environ["IRCA_CHANNELS"] = "#content"

@traceable(run_type="llm", name="Extra Marketing Slogan Generation")
async def generate_llm_content(prompt: str) -> tuple[str, int, int]:
    """Helper to query the configured LLM provider and track token usage."""
    provider = os.getenv("LLM_PROVIDER", "").lower().strip()
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

    # 1. OpenAI
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
            except Exception as e:
                print(f"[EXTRA] OpenAI failed: {e}")

    # 2. Gemini
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
            except Exception as e:
                print(f"[EXTRA] Gemini failed: {e}")

    # 3. Ollama
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
        except Exception as e:
            print(f"[EXTRA] Ollama failed: {e}")

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
            # Set usage metadata using the official SDK set method
            rt.set(usage_metadata=usage_dict)
            
            # Support older/custom serialization fallbacks
            if not isinstance(rt.extra, dict):
                rt.extra = {}
            rt.extra["usage_metadata"] = usage_dict
            try:
                rt.usage_metadata = usage_dict
            except:
                pass
    except Exception as e:
        pass

    return {
        "output": text,
        "usage_metadata": {
            "input_tokens": prompt_tokens,
            "output_tokens": comp_tokens,
            "total_tokens": prompt_tokens + comp_tokens
        }
    }

class ExtraMarketingAgent(BFAAgent):
    def __init__(self):
        super().__init__(
            agent_id="extra-marketing-agent",
            name="Extra Marketing Agent",
            description="A manually registered agent that generates promotional slogans.",
            tags=["marketing", "slogan", "promo"],
            examples=["generate slogan for product", "write promo lines"],
            url="http://127.0.0.1:8104"
        )

    async def run(self, user_message: str, context: RequestContext) -> str:
        # Check if we should avoid keywords
        llm_prompt = (
            f"Generate an engaging, punchy marketing slogan for: '{user_message}'. "
            "Write only the slogan text directly without quotes."
        )
        llm_res = await generate_llm_content(llm_prompt)
        text = llm_res["output"]
        p_tok = llm_res["usage_metadata"]["input_tokens"]
        c_tok = llm_res["usage_metadata"]["output_tokens"]
        if text:
            slogan = text.strip()
        else:
            slogan = f"Slogan: Elevate your operations with '{user_message}'!"
            c_tok = len(slogan) // 4
        
        return f"{slogan}\n[METRICS: prompt_tokens={p_tok}, completion_tokens={c_tok}]"

agent_instance = ExtraMarketingAgent()
app = agent_instance.app

if __name__ == "__main__":
    print("[EXTRA] Starting ExtraMarketingAgent on port 8104...")
    print("[EXTRA] Note: This agent will NOT register with the Gateway automatically.")
    print("[EXTRA] You must register it manually via curl.")
    uvicorn.run("extra_agent:app", host="127.0.0.1", port=8104, log_level="warning")
