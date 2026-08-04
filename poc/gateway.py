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

os.environ["BFA_GATEWAY_URL"] = "http://127.0.0.1:8000"

from bfa_sdk.core.gateway import create_gateway_app

# Instantiate complete Gateway App with full UI, Observability, and Live Transaction Logs
app = create_gateway_app()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
