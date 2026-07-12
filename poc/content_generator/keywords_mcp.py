import os
import uvicorn
import asyncio
from bfa_sdk.core.mcp import BFAMCP

# Configure environmental options for FAISS local embeddings or mock embeddings
os.environ["IRCA_CHANNELS"] = "#content"
os.environ["BFA_GATEWAY_URL"] = "http://127.0.0.1:8000"

mcp_server = BFAMCP("keywords-mcp")

# In-memory database of used campaign keywords
CAMPAIGN_KEYWORDS = {
    "camp-123": ["artificial-intelligence", "agents", "automation"],
    "camp-456": ["content-creation", "marketing", "seo"]
}

@mcp_server.tool(
    name="get_used_keywords",
    description="Retrieve keywords already used in campaigns to avoid duplication.",
    tags=["keywords", "marketing", "campaign"],
    examples=["get used keywords", "fetch campaign keywords"]
)
def get_used_keywords(delegated_token: str, campaign_id: str) -> str:
    """
    Returns keywords already used in a campaign.
    Gated by parameter lockdown on campaign_id.
    """
    keywords = CAMPAIGN_KEYWORDS.get(campaign_id, [])
    import json
    return json.dumps({"campaign_id": campaign_id, "used_keywords": keywords})

@mcp_server.tool(
    name="reserve_keyword",
    description="Reserve a keyword for a marketing campaign.",
    tags=["keywords", "marketing", "reserve"],
    examples=["reserve keyword", "save campaign keyword"]
)
def reserve_keyword(delegated_token: str, campaign_id: str, keyword: str) -> str:
    """
    Reserves a new keyword for a campaign.
    Gated by parameter lockdown on campaign_id.
    """
    if campaign_id not in CAMPAIGN_KEYWORDS:
        CAMPAIGN_KEYWORDS[campaign_id] = []
    if keyword not in CAMPAIGN_KEYWORDS[campaign_id]:
        CAMPAIGN_KEYWORDS[campaign_id].append(keyword)
    import json
    return json.dumps({"campaign_id": campaign_id, "reserved_keyword": keyword, "status": "success"})

# Start registration helper on startup asynchronously
async def startup_register():
    await asyncio.sleep(1)  # Wait for gateway to boot
    await mcp_server.register_with_gateway("http://127.0.0.1:8000", "http://127.0.0.1:8102")

# Spawn background register task
import threading
loop = asyncio.new_event_loop()
threading.Thread(target=lambda: loop.run_until_complete(startup_register()), daemon=True).start()

app = mcp_server.app

if __name__ == "__main__":
    uvicorn.run("keywords_mcp:app", host="127.0.0.1", port=8102, log_level="warning")
