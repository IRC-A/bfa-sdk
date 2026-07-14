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

class WriterAgent(BFAAgent):
    def __init__(self):
        super().__init__(
            agent_id="writer-agent",
            name="Writer Agent",
            description="Generates campaign articles while avoiding duplicate keywords.",
            tags=["writer", "content", "essay"],
            examples=["write article", "generate essay for campaign"],
            url="http://127.0.0.1:8106"
        )

    async def run(self, user_message: str, context: RequestContext) -> str:
        """
        Pure text writing/refinement node.
        Receives writing instructions and calls the LLM provider directly to generate content.
        """
        # Determine if this is a refinement task or an initial draft
        if "refine" in user_message.lower() or "critique" in user_message.lower():
            system_instruction = (
                "You are a professional content editor. Refine the given draft based on the provided critique instructions.\n"
                "Incorporate all corrections and improvements. Respond ONLY with the final refined text, without any conversational intro/outro or surrounding markdown formatting."
            )
        else:
            system_instruction = (
                "You are an expert article writer. Draft a high-quality, engaging, and professional 2-paragraph essay or article based on the provided topic and constraints.\n"
                "Respond ONLY with the generated text, without any conversational intro/outro, headers, or surrounding markdown formatting."
            )

        prompt = f"{system_instruction}\n\nUser request & instructions:\n{user_message}"
        
        llm_res = await generate_llm_content(prompt)
        text = llm_res["output"].strip()
        p_tok = llm_res["usage_metadata"]["input_tokens"]
        c_tok = llm_res["usage_metadata"]["output_tokens"]

        # Report tokens dynamically to BFA Gateway for centralized dashboard tracking
        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    "http://127.0.0.1:8000/report-tokens",
                    json={"prompt_tokens": p_tok, "completion_tokens": c_tok},
                    timeout=2
                )
        except Exception as e:
            print(f"BFAAgent Warning: Failed to report tokens to Gateway: {e}")

        return f"{text}\n[METRICS: prompt_tokens={p_tok}, completion_tokens={c_tok}]"

agent_instance = WriterAgent()
app = agent_instance.app

if __name__ == "__main__":
    print("[WRITER] Starting WriterAgent on port 8106...")
    uvicorn.run("writer_agent:app", host="127.0.0.1", port=8106, log_level="warning")
