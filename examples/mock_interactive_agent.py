import uvicorn
from bfa_sdk.core.interactive_agent import BFAInteractiveAgent, MemoryStack

class MockChatbotAgent(BFAInteractiveAgent):
    """
    Mock Interactive Agent representing a Customer Support Chatbot.
    """
    def __init__(self, url: str):
        super().__init__(
            agent_id="chatbot_agent",
            name="Chatbot Interactivo",
            description="Frontend agent that chats with the user, maintains context, and delegates to specific agents.",
            tags=["chat", "soporte", "frontend", "atencion"],
            examples=[
                "hola, necesito ayuda", 
                "soy juan",
                "quiero ver el clima y luego mis cuentas"
            ],
            url=url
        )

    async def handle_interaction(self, session_id: str, user_message: str, memory: MemoryStack) -> str:
        # Example logic: extract simple keyword intents to delegate
        user_message_lower = user_message.lower()
        
        if "clima" in user_message_lower:
            # Delegate simplified query to the Gateway
            res = await self.delegate_task("clima", session_id)
            return f"[Chatbot] Pregunté por el clima y me dijeron: {res}"
            
        if "cuenta" in user_message_lower:
            res = await self.delegate_task("cuenta bancaria", session_id)
            return f"[Chatbot] Consulté al sistema de cuentas: {res}"
            
        if "historial" in user_message_lower:
            # Let's echo the memory back
            session_data = memory.get_session(session_id)
            return f"[Chatbot] Memoria de sesión: {len(session_data['history'])} mensajes. Agentes invocados: {list(session_data['invoked_agents'])}"
            
        return f"[Chatbot] Te escucho en la sesión {session_id}. Puedes preguntarme sobre el clima, tus cuentas, o ver tu historial."


# Initialize on port 8005
agent_url = "http://127.0.0.1:8005"
agent = MockChatbotAgent(url=agent_url)
app = agent.app

if __name__ == "__main__":
    print("Starting mock Interactive Chatbot Agent server on port 8005...")
    uvicorn.run(app, host="127.0.0.1", port=8005, log_level="info")
