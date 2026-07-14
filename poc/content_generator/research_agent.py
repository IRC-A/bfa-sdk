import os
import json
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
    def traceable(*args, **kwargs):
        return lambda func: func

# Configure environmental options for BFA routing
os.environ["IRCA_CHANNELS"] = "#content"
os.environ["BFA_GATEWAY_URL"] = "http://127.0.0.1:8000"

@traceable(run_type="llm", name="Research LLM Generation")
async def generate_llm_content(prompt: str) -> dict:
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
                print(f"[RESEARCH] OpenAI failed: {e}")

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
                print(f"[RESEARCH] Gemini failed: {e}")

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
            print(f"[RESEARCH] Ollama failed: {e}")

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
            rt.set(usage_metadata=usage_dict)
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

class ResearchAgent(BFAAgent):
    def __init__(self):
        super().__init__(
            agent_id="research-agent",
            name="Research Agent",
            description="Performs web search research on any topic using Tavily API.",
            tags=["research", "search", "tavily", "websearch"],
            examples=["research topic", "search web for facts", "gather context on topic"],
            url="http://127.0.0.1:8105"
        )

    async def run(self, user_message: str, context: RequestContext) -> str:
        tavily_key = os.getenv("TAVILY_API_KEY", "").strip().strip("'\"")
        
        # 1. Ask the LLM to generate exactly 2 web search queries for the topic
        query_prompt = (
            f"Generate exactly 2 precise search queries to search the web for information on: '{user_message}'. "
            "Write the queries, one per line, and absolutely nothing else. No numbers, no headers."
        )
        
        llm_res = await generate_llm_content(query_prompt)
        raw_queries = llm_res["output"]
        p_tok = llm_res["usage_metadata"]["input_tokens"]
        c_tok = llm_res["usage_metadata"]["output_tokens"]
        
        queries = []
        if raw_queries:
            for line in raw_queries.split("\n"):
                line = line.strip().lstrip("1234567890.-* ")
                if line:
                    queries.append(line)
        
        # Fallback query if LLM returned nothing
        if not queries:
            queries = [user_message]
        
        # Keep only up to 2 queries for efficiency
        queries = queries[:2]
        print(f"[RESEARCH] Generated queries: {queries}")

        search_contents = []
        
        # 2. Call Tavily Search API for each query
        if tavily_key:
            async with httpx.AsyncClient() as client:
                for q in queries:
                    try:
                        tavily_res = await client.post(
                            "https://api.tavily.com/search",
                            json={
                                "api_key": tavily_key,
                                "query": q,
                                "max_results": 2
                            },
                            timeout=8
                        )
                        if tavily_res.status_code == 200:
                            data = tavily_res.json()
                            for result in data.get("results", []):
                                if "content" in result:
                                    search_contents.append(f"- {result['content']}")
                        else:
                            print(f"[RESEARCH] Tavily API Error: {tavily_res.status_code} - {tavily_res.text}")
                    except Exception as e:
                        print(f"[RESEARCH] Tavily search for query '{q}' failed: {e}")
        else:
            print("[RESEARCH] No TAVILY_API_KEY configured. Returning high-quality mock results.")
            for q in queries:
                mock_text = f"Mock context for query '{q}': The integration of advanced systems enables streamlining of industrial tasks, resulting in enhanced productivity, lower costs, and optimized operational workflows."
                search_contents.append(f"- {mock_text}")
        
        # 3. Combine results and return them
        research_context = "\n".join(search_contents)
        if not research_context:
            research_context = f"No search results found for topic: '{user_message}'."

        return f"{research_context}\n[METRICS: prompt_tokens={p_tok}, completion_tokens={c_tok}]"

agent_instance = ResearchAgent()
app = agent_instance.app

if __name__ == "__main__":
    print("[RESEARCH] Starting ResearchAgent on port 8105...")
    uvicorn.run("research_agent:app", host="127.0.0.1", port=8105, log_level="warning")
