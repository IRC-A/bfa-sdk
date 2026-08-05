# Copyright (c) 2026 Sandro G. All rights reserved.
# Licensed under AGPLv3 / Commercial Dual License.
import os
import uvicorn
from dotenv import load_dotenv

load_dotenv()

openai_key = os.getenv("OPENAI_API_KEY", "").strip().strip("'\"")
use_mock = os.getenv("BFA_USE_MOCK_EMBEDDINGS", "").lower() in ("true", "1")

if openai_key and not use_mock:
    os.environ["BFA_USE_OPENAI_EMBEDDINGS"] = "true"
    os.environ["BFA_USE_MOCK_EMBEDDINGS"] = "false"
    print("IRC-A Gateway: Found OpenAI API key, activating OpenAI Embeddings!")
else:
    os.environ["BFA_USE_MOCK_EMBEDDINGS"] = "true"
    os.environ["BFA_USE_OPENAI_EMBEDDINGS"] = "false"
    print("IRC-A Gateway: Using DummyEmbedder for fast local/offline testing.")

def mask(val: str) -> str:
    if not val:
        return "<NOT SET>"
    if len(val) <= 10:
        return val[:3] + "..." + val[-2:]
    return val[:7] + "..." + val[-6:]

print("\n================================================================================")
print("=== [BFA GATEWAY STARTUP - ENVIRONMENT & CREDENTIALS DIAGNOSTIC] ===")
print(f"🔹 OPENAI_API_KEY        : {mask(os.getenv('OPENAI_API_KEY'))}")
print(f"🔹 GOOGLE_API_KEY        : {mask(os.getenv('GOOGLE_API_KEY'))}")
print(f"🔹 TAVILY_API_KEY        : {mask(os.getenv('TAVILY_API_KEY'))}")
print(f"🔹 LANGSMITH_API_KEY     : {mask(os.getenv('LANGSMITH_API_KEY'))}")
print(f"🔹 LLM_PROVIDER          : {os.getenv('LLM_PROVIDER', '<NOT SET>')}")
print(f"🔹 BFA_USE_MOCK_EMBEDDINGS: {os.getenv('BFA_USE_MOCK_EMBEDDINGS', 'false')}")
print(f"🔹 BFA_USE_OPENAI_EMBEDDINGS: {os.getenv('BFA_USE_OPENAI_EMBEDDINGS', 'false')}")
print(f"🔹 BFA_REGISTRY_DB_PATH  : {os.getenv('BFA_REGISTRY_DB_PATH', 'bfa_registry_db.json')}")
print("================================================================ algorithm\n")

os.environ["BFA_GATEWAY_URL"] = "http://127.0.0.1:8000"

from bfa_sdk.core.gateway import create_gateway_app

# Instantiate complete Gateway App with full UI, Observability, and Live Transaction Logs
app = create_gateway_app()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
