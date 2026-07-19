import abc
import httpx
from typing import Dict, List, Any
from bfa_sdk.core.agent import BFAAgent
from a2a.server.agent_execution.context import RequestContext

class MemoryStack:
    """
    Manages the session memory for interactive agents.
    It tracks conversation history and agents invoked in the current context.
    """
    def __init__(self):
        self.sessions: Dict[str, Dict[str, Any]] = {}

    def get_session(self, session_id: str) -> Dict[str, Any]:
        if session_id not in self.sessions:
            self.sessions[session_id] = {
                "history": [],
                "invoked_agents": set(),
                "semantic_keys": {}
            }
        return self.sessions[session_id]

    def add_message(self, session_id: str, role: str, content: str):
        session = self.get_session(session_id)
        session["history"].append({"role": role, "content": content})

    def record_agent_invocation(self, session_id: str, agent_id: str):
        session = self.get_session(session_id)
        session["invoked_agents"].add(agent_id)

    def set_semantic_keys(self, session_id: str, keys: dict):
        session = self.get_session(session_id)
        session["semantic_keys"].update(keys)

    def clear_session(self, session_id: str):
        if session_id in self.sessions:
            del self.sessions[session_id]


class BFAInteractiveAgent(BFAAgent):
    """
    An extension of BFAAgent for frontend/coordinator agents that need memory and context management.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.memory_stack = MemoryStack()

    async def run(self, user_message: str, context: RequestContext) -> str:
        """
        Intercepts the standard run to handle session memory before passing it to handle_interaction.
        """
        # Get context_id or default to a standard session ID
        session_id = None
        if hasattr(context, "context_id"):
            session_id = getattr(context, "context_id")
        elif hasattr(context, "message") and hasattr(context.message, "context_id"):
            session_id = context.message.context_id
            
        if not session_id:
            session_id = "default-session"
            
        self.memory_stack.add_message(session_id, "user", user_message)
        
        try:
            # Delegate to the concrete implementation
            response_text = await self.handle_interaction(session_id, user_message, self.memory_stack)
            self.memory_stack.add_message(session_id, "agent", str(response_text))
            return str(response_text)
        except Exception as e:
            error_msg = f"Error in Interactive Agent: {e}"
            self.memory_stack.add_message(session_id, "agent", error_msg)
            return error_msg

    @abc.abstractmethod
    async def handle_interaction(self, session_id: str, user_message: str, memory: MemoryStack) -> str:
        """
        Must be implemented by subclasses. 
        Provides access to the user message and the memory stack.
        """
        pass

    async def delegate_task(self, query: str, session_id: str = None) -> str:
        """
        Helper method to delegate a simplified query to the BFA Gateway or another agent,
        without sending the entire context/memory stack.
        """
        if not self.gateway_url:
            return "Error: Gateway URL not configured."

        if session_id:
            # Record that we are delegating
            self.memory_stack.record_agent_invocation(session_id, "gateway_delegate")

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "invoke"
        }
        
        import urllib.parse
        encoded_query = urllib.parse.quote(query)
        invoke_url = f"{self.gateway_url.rstrip('/')}/invoke?query={encoded_query}"
        
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                # We call the Gateway's invoke endpoint which does the semantic routing
                # and forwards only the simplified query to the target agent.
                res = await client.post(invoke_url, json=payload)
                if res.status_code == 200:
                    data = res.json()
                    if "result" in data and "output" in data["result"]:
                        return data["result"]["output"].get("text", str(data))
                return f"Delegation failed with status {res.status_code}: {res.text}"
            except Exception as e:
                return f"Delegation error: {e}"
