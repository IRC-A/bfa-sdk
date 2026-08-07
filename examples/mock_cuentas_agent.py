import os
import uvicorn
import asyncio
from a2a.server.agent_execution.context import RequestContext
from bfa_sdk.core.agent import BFAAgent
try:
    from openai import AsyncOpenAI
except ImportError:
    AsyncOpenAI = None

gateway_url = os.getenv("BFA_GATEWAY_URL", "http://127.0.0.1:8000")
agent_public_url = os.getenv("PUBLIC_URL", os.getenv("AGENT_URL", "http://127.0.0.1:8002"))
openai_api_key = os.getenv("OPENAI_API_KEY")

class MockCuentasAgent(BFAAgent):
    """
    Real AI Accounts Agent powered by OpenAI subclassing BFAAgent.
    """
    def __init__(self, url: str):
        super().__init__(
            agent_id="cuentas_agent",
            name="Agente de Cuentas",
            description="Expert banking agent for checking, opening, and managing bank accounts and savings accounts.",
            tags=["cuenta", "abrir cuenta", "caja de ahorro", "cuenta corriente", "registro"],
            examples=[
                "quiero abrir una cuenta bancaria", 
                "como abro una caja de ahorro?", 
                "crear cuenta corriente",
                "consultar mi cuenta"
            ],
            url=url,
            gateway_url=gateway_url
        )
        self.openai_client = AsyncOpenAI(api_key=openai_api_key) if (AsyncOpenAI and openai_api_key) else None

    async def run(self, user_message: str, context: RequestContext) -> str:
        if self.openai_client:
            try:
                response = await self.openai_client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {
                            "role": "system", 
                            "content": (
                                "You are MDBank's Accounts Specialist AI Agent. "
                                "You assist customers with opening bank/savings accounts, checking account balances, "
                                "and managing account information. Be polite, professional, helpful, and answer in the language of the user query."
                            )
                        },
                        {"role": "user", "content": user_message}
                    ],
                    temperature=0.7,
                    max_tokens=350
                )
                return response.choices[0].message.content.strip()
            except Exception as e:
                print(f"[Cuentas Agent LLM Error]: {e}")
        
        return f"Hello! I am MDBank's Accounts Specialist. I can help you open a checking or savings account, or check your account balance. How can I assist you today regarding: '{user_message}'?"

agent = MockCuentasAgent(url=agent_public_url)
app = agent.app

if __name__ == "__main__":
    bind_host = os.getenv("HOST", "0.0.0.0")
    bind_port = int(os.getenv("PORT", 8002))
    print(f"Starting Cuentas Agent server on {bind_host}:{bind_port}...")
    uvicorn.run(app, host=bind_host, port=bind_port, log_level="info")
