import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from starlette.testclient import TestClient
from a2a.server.agent_execution.context import RequestContext
from a2a.server.events.event_queue import EventQueue
from bfa_sdk.core.mcp import BFAMCP
from bfa_sdk.core.agent import BFAAgent, BFAAgentExecutor

# 1. Test BFAMCP Wrapper
def test_mcp_wrapper():
    mcp_server = BFAMCP("MDBank MCP", version="1.2.3")
    
    @mcp_server.tool(tags=["test_tag"], examples=["example 1"])
    def dummy_tool(param: str) -> str:
        """This is a dummy tool for testing."""
        return f"Result: {param}"
        
    @mcp_server.resource("schema://test")
    def dummy_resource() -> str:
        return "resource-content"
        
    @mcp_server.prompt
    def dummy_prompt() -> str:
        return "prompt-content"
        
    client = TestClient(mcp_server.app)
    
    # Query /tools endpoint
    response = client.get("/tools")
    assert response.status_code == 200
    tools = response.json()
    
    assert len(tools) == 1
    tool = tools[0]
    assert tool["name"] == "dummy_tool"
    assert tool["description"] == "This is a dummy tool for testing."
    assert "test_tag" in tool["annotations"]["tags"]
    assert "example 1" in tool["annotations"]["examples"]
    assert isinstance(tool["inputSchema"], dict)
# 2. Test BFAMCP register and list tools exceptions
@pytest.mark.anyio
@patch("httpx.AsyncClient.post")
async def test_mcp_register_with_gateway(mock_post):
    mcp_server = BFAMCP("MDBank MCP")
    
    # Success Case
    mock_res = MagicMock()
    mock_res.status_code = 200
    mock_post.return_value = mock_res
    success = await mcp_server.register_with_gateway("http://localhost:8000", "http://localhost:8001")
    assert success is True
    
    # Failure Case 1: Status Code 500
    mock_res.status_code = 500
    success = await mcp_server.register_with_gateway("http://localhost:8000", "http://localhost:8001")
    assert success is False

    # Failure Case 2: Exception raised
    mock_post.side_effect = Exception("network connection failed")
    success = await mcp_server.register_with_gateway("http://localhost:8000", "http://localhost:8001")
    assert success is False

@pytest.mark.anyio
async def test_mcp_list_tools_exception():
    mcp_server = BFAMCP("MDBank MCP")
    # Force list_tools to raise an exception
    mcp_server.mcp.list_tools = AsyncMock(side_effect=Exception("mock list tools error"))
    
    response = await mcp_server._list_tools_handler()
    assert response.status_code == 500
    assert "Failed to list tools" in response.body.decode()

# 3. Test BFAAgent Wrapper
class MockAgent(BFAAgent):
    async def run(self, user_message: str, context: RequestContext) -> str:
        if user_message == "throw_error":
            raise ValueError("custom agent error")
        return f"Processed: {user_message}"

def test_agent_wrapper():
    agent = MockAgent(
        agent_id="test_agent",
        name="Test Agent",
        description="Subclass of BFAAgent for unit testing",
        url="http://localhost:8002",
        tags=["unit_test", "mock"],
        examples=["test message"]
    )
    
    client = TestClient(agent.app)
    
    # 1. Query /.well-known/agent-card.json endpoint
    response = client.get("/.well-known/agent-card.json")
    assert response.status_code == 200
    card = response.json()
    assert card["name"] == "Test Agent"
    assert card["description"] == "Subclass of BFAAgent for unit testing"
    assert card["skills"][0]["name"] == "Test Agent"
    
    # 2. Query JSON-RPC execution endpoint
    rpc_payload = {
        "jsonrpc": "2.0",
        "method": "SendMessage",
        "params": {
            "message": {
                "role": 1,
                "message_id": "test-msg-id",
                "context_id": "test-session-id",
                "parts": [
                    {
                        "text": "hello BFA"
                    }
                ]
            }
        },
        "id": 42
    }
    headers = {"A2A-Version": "1.0"}
    response = client.post("/", json=rpc_payload, headers=headers)
    assert response.status_code == 200
    rpc_res = response.json()
    
    assert rpc_res["jsonrpc"] == "2.0"
    assert rpc_res["id"] == 42
    assert "Processed: hello BFA" in rpc_res["result"]["message"]["parts"][0]["text"]

# Test Agent Executor cancel and exception branches
@pytest.mark.anyio
async def test_agent_executor_cancel_and_error():
    agent = MockAgent(
        agent_id="test_agent",
        name="Test Agent",
        description="desc",
        tags=["tag"],
        examples=["ex"],
        url="http://localhost:8002"
    )
    executor = BFAAgentExecutor(agent)
    
    # Test cancel method
    context = MagicMock()
    event_queue = MagicMock()
    await executor.cancel(context, event_queue) # should execute pass cleanly
    
    # Test error path during execute
    mock_context = MagicMock()
    mock_context.get_user_input.return_value = "throw_error"
    
    mock_event_queue = AsyncMock()
    await executor.execute(mock_context, mock_event_queue)
    
    mock_event_queue.enqueue_event.assert_called_once()
    args, kwargs = mock_event_queue.enqueue_event.call_args
    # Check that error is in the text of the message
    msg_obj = args[0]
    assert "Error in Agent execution: custom agent error" in msg_obj.parts[0].text

@pytest.mark.anyio
@patch("httpx.AsyncClient.post")
async def test_agent_register_with_gateway(mock_post):
    agent = MockAgent(
        agent_id="test_agent",
        name="Test Agent",
        description="desc",
        tags=["tag"],
        examples=["ex"],
        url="http://localhost:8002"
    )
    
    # Success Case
    mock_res = MagicMock()
    mock_res.status_code = 200
    mock_post.return_value = mock_res
    
    success = await agent.register_with_gateway("http://localhost:8000")
    assert success is True
    
    # Failure Case 1: Status Code 500
    mock_res.status_code = 500
    success = await agent.register_with_gateway("http://localhost:8000")
    assert success is False
    
    # Failure Case 2: Exception raised
    mock_post.side_effect = Exception("network connection failed")
    success = await agent.register_with_gateway("http://localhost:8000")
    assert success is False


