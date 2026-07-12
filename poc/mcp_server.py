import os
import uvicorn
import asyncio
from bfa_sdk.core.mcp import BFAMCP

# Configure environmental options for FAISS local embeddings or mock embeddings
os.environ["IRCA_CHANNELS"] = "#finance"
os.environ["BFA_GATEWAY_URL"] = "http://localhost:8000"

mcp_server = BFAMCP("bank-database-mcp")

@mcp_server.tool(
    name="get_bank_score",
    description="Query internal database for solvency score ratings.",
    tags=["bank", "score", "database"],
    examples=["get solvency score", "fetch score for customer"]
)
def get_bank_score(delegated_token: str, customer_id: str) -> str:
    """
    Retrieves solvency ratings from secure relational store.
    Access is gated by Gateway-signed DET.
    """
    return f'{{"customer_id": "{customer_id}", "credit_score": 780, "solvency_rating": "Excellent"}}'

# Start registration helper on startup asynchronously
async def startup_register():
    await asyncio.sleep(1)  # Wait for gateway to boot
    await mcp_server.register_with_gateway("http://localhost:8000", "http://localhost:8002")

# Spawn background register task
import threading
loop = asyncio.new_event_loop()
threading.Thread(target=lambda: loop.run_until_complete(startup_register()), daemon=True).start()

app = mcp_server.app

if __name__ == "__main__":
    uvicorn.run("mcp_server:app", host="127.0.0.1", port=8002, log_level="warning")
