import uvicorn
from a2a.server.agent_execution.context import RequestContext
from bfa_sdk.core.agent import BFAAgent

class MockClimaAgent(BFAAgent):
    """
    Mock Weather Agent subclassing BFAAgent representing the weather microservice.
    """
    def __init__(self, url: str):
        super().__init__(
            agent_id="clima_agent",
            name="Agente del Clima",
            description="Expert agent for checking current weather, temperature, forecast, and weather conditions in different cities.",
            tags=["clima", "tiempo", "pronostico", "temperatura", "lluvia", "sol"],
            examples=[
                "como esta el clima en Buenos Aires?", 
                "va a llover hoy?", 
                "cual es la temperatura en Madrid?",
                "dame el pronostico del tiempo"
            ],
            url=url
        )

    async def run(self, user_message: str, context: RequestContext) -> str:
        return f"[Clima Agent] El clima actual es parcialmente nublado con 24°C. Pedido recibido: '{user_message}'."


# Initialize on port 8004
agent_url = "http://127.0.0.1:8004"
agent = MockClimaAgent(url=agent_url)
app = agent.app

if __name__ == "__main__":
    print("Starting mock Clima Agent server on port 8004...")
    uvicorn.run(app, host="127.0.0.1", port=8004, log_level="info")
