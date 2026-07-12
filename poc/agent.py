import os
import uvicorn
import httpx
from bfa_sdk.core.agent import BFAAgent
from a2a.server.agent_execution.context import RequestContext

# Configure Logical Channels for masking
os.environ["IRCA_CHANNELS"] = "#finance"
os.environ["BFA_GATEWAY_URL"] = "http://localhost:8000"

class CreditAdvisorAgent(BFAAgent):
    def __init__(self):
        super().__init__(
            agent_id="credit-advisor-agent",
            name="Credit Advisor Agent",
            description="Assesses user financial standing and retrieves transaction ratings.",
            tags=["credit", "advisor", "bank"],
            examples=["analyze financial score", "fetch rating for user"],
            url="http://localhost:8001"
        )

    async def run(self, user_message: str, context: RequestContext) -> str:
        """
        Processes client query. If the query asks for a solvency rating,
        the agent requests the DET from the BFA Gateway and calls the MCP Database tool directly (P2P).
        """
        import re
        customer_match = re.search(r"customer\s+(?:id-)?(\w+)", user_message, re.IGNORECASE)
        if not customer_match:
            return "Please provide a valid customer ID (e.g. customer 722)."
            
        customer_id = customer_match.group(1)
        
        # Test mode for parameter lockdown verification
        target_customer_id = customer_id
        if "hack" in user_message.lower():
            # Request DET for customer_id but call MCP tool with a different customer_id
            target_customer_id = "999"
            
        # 1. Ask BFA Gateway to resolve/discover the secure bank score tool
        # Send session JWT token to the gateway
        try:
            async with httpx.AsyncClient() as client:
                discover_res = await client.post(
                    "http://localhost:8000/discover",
                    params={"query": f"get bank score for customer {customer_id}"},
                    json={"session_token": self.session_token},
                    timeout=5
                )
                
                if discover_res.status_code != 200:
                    return f"Gateway Discovery Failed: {discover_res.json().get('detail', 'Unknown error')}"
                    
                discovery_data = discover_res.json()
                det_token = discovery_data["det"]
                target_url = discovery_data["url"]
                
                # 2. Invoke the target MCP database tool directly (P2P) sending the DET token
                mcp_res = await client.post(
                    f"{target_url.rstrip('/')}/tools",
                    json={
                        "tool": "get_bank_score",
                        "arguments": {
                            "delegated_token": det_token,
                            "customer_id": target_customer_id
                        }
                    },
                    timeout=5
                )
                
                if mcp_res.status_code != 200:
                    return f"MCP Tool Invocation Rejected: {mcp_res.text}"
                    
                return mcp_res.text
                
        except Exception as e:
            return f"Error executing P2P flow: {e}"

agent_instance = CreditAdvisorAgent()
app = agent_instance.app

if __name__ == "__main__":
    uvicorn.run("agent:app", host="127.0.0.1", port=8001, log_level="warning")
