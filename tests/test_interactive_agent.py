import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from starlette.testclient import TestClient
from a2a.server.agent_execution.context import RequestContext
from bfa_sdk.core.interactive_agent import BFAInteractiveAgent, MemoryStack

# 1. Test MemoryStack
def test_memory_stack():
    memory = MemoryStack()
    
    # Check default initialization
    session = memory.get_session("session-1")
    assert session["history"] == []
    assert session["invoked_agents"] == set()
    assert session["semantic_keys"] == {}
    
    # Add messages
    memory.add_message("session-1", "user", "hello")
    memory.add_message("session-1", "agent", "hi")
    assert len(session["history"]) == 2
    assert session["history"][0] == {"role": "user", "content": "hello"}
    
    # Record invocation
    memory.record_agent_invocation("session-1", "agent_A")
    assert "agent_A" in session["invoked_agents"]
    
    # Set semantic keys
    memory.set_semantic_keys("session-1", {"intent": "check_balance"})
    assert session["semantic_keys"]["intent"] == "check_balance"
    
    # Clear session
    memory.clear_session("session-1")
    assert "session-1" not in memory.sessions


# 2. Test BFAInteractiveAgent Subclass
class MockInteractiveAgent(BFAInteractiveAgent):
    async def handle_interaction(self, session_id: str, user_message: str, memory: MemoryStack) -> str:
        if user_message == "throw_error":
            raise ValueError("custom error")
        return f"Echo: {user_message}"

@pytest.mark.anyio
async def test_interactive_agent_run_success():
    agent = MockInteractiveAgent(
        agent_id="test_interactive",
        name="Test Interactive Agent",
        description="desc",
        url="http://localhost:8005",
        tags=["interactive"],
        examples=["hello"]
    )
    
    # Mock RequestContext
    context = MagicMock(spec=RequestContext)
    context.get_user_input.return_value = "hello world"
    context.context_id = "session-123"
    
    response = await agent.run("hello world", context)
    assert response == "Echo: hello world"
    
    # Verify history
    history = agent.memory_stack.get_session("session-123")["history"]
    assert len(history) == 2
    assert history[0] == {"role": "user", "content": "hello world"}
    assert history[1] == {"role": "agent", "content": "Echo: hello world"}

@pytest.mark.anyio
async def test_interactive_agent_run_fallback_session_id():
    agent = MockInteractiveAgent(
        agent_id="test_interactive",
        name="Test Interactive Agent",
        description="desc",
        url="http://localhost:8005",
        tags=["interactive"],
        examples=["hello"]
    )
    
    # Context lacking attribute context_id, falls back to context.message.context_id
    context = MagicMock()
    del context.context_id
    context.message = MagicMock()
    context.message.context_id = "session-fallback"
    
    response = await agent.run("hello", context)
    assert response == "Echo: hello"
    
    history = agent.memory_stack.get_session("session-fallback")["history"]
    assert len(history) == 2

    # Ultimately falls back to default-session if neither exists
    context_no_id = MagicMock()
    del context_no_id.context_id
    del context_no_id.message
    response = await agent.run("hello", context_no_id)
    assert response == "Echo: hello"
    assert len(agent.memory_stack.get_session("default-session")["history"]) == 2

@pytest.mark.anyio
async def test_interactive_agent_run_exception():
    agent = MockInteractiveAgent(
        agent_id="test_interactive",
        name="Test Interactive Agent",
        description="desc",
        url="http://localhost:8005",
        tags=["interactive"],
        examples=["hello"]
    )
    
    context = MagicMock(spec=RequestContext)
    context.context_id = "session-error"
    
    response = await agent.run("throw_error", context)
    assert "Error in Interactive Agent: custom error" in response
    
    history = agent.memory_stack.get_session("session-error")["history"]
    assert history[1]["role"] == "agent"
    assert "Error in Interactive Agent: custom error" in history[1]["content"]


# 3. Test delegate_task method
@pytest.mark.anyio
@patch("httpx.AsyncClient.post")
async def test_delegate_task_success(mock_post):
    agent = MockInteractiveAgent(
        agent_id="test_interactive",
        name="Test Interactive Agent",
        description="desc",
        url="http://localhost:8005",
        tags=["interactive"],
        examples=["hello"],
        gateway_url="http://localhost:8000"
    )
    
    # Success Case
    mock_res = MagicMock()
    mock_res.status_code = 200
    mock_res.json.return_value = {
        "jsonrpc": "2.0",
        "result": {
            "output": {
                "text": "Delegated answer"
            }
        }
    }
    mock_post.return_value = mock_res
    
    res = await agent.delegate_task("check weather", session_id="session-456")
    assert res == "Delegated answer"
    
    # Verify memory recorded the delegation
    session = agent.memory_stack.get_session("session-456")
    assert "gateway_delegate" in session["invoked_agents"]

@pytest.mark.anyio
@patch("httpx.AsyncClient.post")
async def test_delegate_task_failures(mock_post):
    agent = MockInteractiveAgent(
        agent_id="test_interactive",
        name="Test Interactive Agent",
        description="desc",
        url="http://localhost:8005",
        tags=["interactive"],
        examples=["hello"],
        gateway_url="http://localhost:8000"
    )
    
    # Failure Case 1: Status Code 500
    mock_res = MagicMock()
    mock_res.status_code = 500
    mock_res.text = "Internal error"
    mock_post.return_value = mock_res
    
    res = await agent.delegate_task("error query")
    assert "Delegation failed with status 500" in res
    
    # Failure Case 2: Connection exception
    mock_post.side_effect = Exception("network timeout")
    res = await agent.delegate_task("exception query")
    assert "Delegation error: network timeout" in res

@pytest.mark.anyio
async def test_delegate_task_no_gateway():
    agent = MockInteractiveAgent(
        agent_id="test_interactive",
        name="Test Interactive Agent",
        description="desc",
        url="http://localhost:8005",
        tags=["interactive"],
        examples=["hello"],
        gateway_url=None
    )
    res = await agent.delegate_task("query")
    assert "Gateway URL not configured" in res
