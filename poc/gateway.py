import os
import uvicorn
from dotenv import load_dotenv
load_dotenv()

# If OpenAI API Key is loaded and not blank, use real OpenAI Embeddings!
openai_key = os.getenv("OPENAI_API_KEY", "").strip().strip("'\"")
if openai_key:
    os.environ["BFA_USE_OPENAI_EMBEDDINGS"] = "true"
    os.environ["BFA_USE_MOCK_EMBEDDINGS"] = "false"
    print("IRC-A Gateway: Found OpenAI API key, activating OpenAI Embeddings!")
else:
    os.environ["BFA_USE_MOCK_EMBEDDINGS"] = "true"
    os.environ["BFA_USE_OPENAI_EMBEDDINGS"] = "false"
    print("IRC-A Gateway: No OpenAI API key found, falling back to DummyEmbedder.")

os.environ["BFA_GATEWAY_URL"] = "http://127.0.0.1:8000"

import uvicorn
from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse
from bfa_sdk.core.gateway import create_gateway_app, ROUTER

app = create_gateway_app()

# Remove the default JSON "/" route from FastAPI's router so we can implement the conditional accept handler
app.router.routes = [r for r in app.router.routes if getattr(r, "path", None) != "/"]

# Global in-memory Langsmith token usage accumulator
AGGREGATED_TOKENS = {
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0
}

@app.post("/report-tokens")
async def report_tokens(payload: dict):
    """Allows active agents to report their LLM token usage for central dashboard tracking."""
    p = payload.get("prompt_tokens", 0)
    c = payload.get("completion_tokens", 0)
    AGGREGATED_TOKENS["prompt_tokens"] += p
    AGGREGATED_TOKENS["completion_tokens"] += c
    AGGREGATED_TOKENS["total_tokens"] += (p + c)
    return {"status": "success"}

@app.get("/token-metrics")
async def get_token_metrics():
    """Returns the aggregated token counts for visual playground cards."""
    return JSONResponse(AGGREGATED_TOKENS)

@app.get("/")
async def gateway_root(request: Request):
    accept = request.headers.get("accept", "")
    if "text/html" in accept:
        # Serve the beautiful dark-mode visualizer dashboard translated to English with dynamic Token Counter
        html_content = """
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>IRC-A Gateway</title>
            <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;800&family=JetBrains+Mono:wght@400;700&display=swap" rel="stylesheet">
            <style>
                :root {
                    --bg-color: #0b0f19;
                    --panel-bg: #111827;
                    --accent-blue: #3b82f6;
                    --accent-purple: #8b5cf6;
                    --accent-green: #10b981;
                    --border-color: #1f2937;
                    --text-color: #f3f4f6;
                    --text-muted: #9ca3af;
                }
                * {
                    box-sizing: border-box;
                    margin: 0;
                    padding: 0;
                }
                body {
                    font-family: 'Outfit', sans-serif;
                    background-color: var(--bg-color);
                    color: var(--text-color);
                    min-height: 100vh;
                    display: flex;
                    flex-direction: column;
                }
                header {
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    padding: 20px 40px;
                    border-bottom: 1px solid var(--border-color);
                    background: rgba(17, 24, 39, 0.9);
                    backdrop-filter: blur(8px);
                }
                .logo-area h1 {
                    font-size: 1.5rem;
                    font-weight: 800;
                    color: #ffffff;
                }
                .logo-area p {
                    font-size: 0.8rem;
                    color: var(--text-muted);
                    margin-top: 4px;
                }
                .btn-refresh {
                    background: #1f2937;
                    border: 1px solid var(--border-color);
                    color: #ffffff;
                    padding: 8px 16px;
                    border-radius: 8px;
                    font-size: 0.85rem;
                    cursor: pointer;
                    display: flex;
                    align-items: center;
                    gap: 8px;
                    transition: background 0.2s;
                }
                .btn-refresh:hover {
                    background: #374151;
                }
                .main-layout {
                    display: grid;
                    grid-template-columns: 1fr 320px;
                    flex-grow: 1;
                }
                .content-area {
                    padding: 30px 40px;
                    display: flex;
                    flex-direction: column;
                    gap: 30px;
                }
                .sidebar {
                    background: #0f172a;
                    border-left: 1px solid var(--border-color);
                    padding: 30px;
                    display: flex;
                    flex-direction: column;
                }
                .grid-top {
                    display: grid;
                    grid-template-columns: 1.5fr 1fr;
                    gap: 24px;
                }
                .card {
                    background: var(--panel-bg);
                    border: 1px solid var(--border-color);
                    border-radius: 16px;
                    padding: 24px;
                    box-shadow: 0 4px 20px rgba(0,0,0,0.3);
                }
                .card h2 {
                    font-size: 1.1rem;
                    font-weight: 600;
                    margin-bottom: 16px;
                    display: flex;
                    align-items: center;
                    gap: 8px;
                }
                .card-desc {
                    font-size: 0.8rem;
                    color: var(--text-muted);
                    line-height: 1.5;
                    margin-bottom: 16px;
                }
                .stats-grid {
                    display: grid;
                    grid-template-columns: 1fr 1fr;
                    gap: 16px;
                    margin-bottom: 16px;
                }
                .stat-box {
                    background: #0f172a;
                    border: 1px solid var(--border-color);
                    padding: 16px;
                    border-radius: 12px;
                    text-align: center;
                }
                .stat-num {
                    font-size: 1.75rem;
                    font-weight: 800;
                }
                .stat-label {
                    font-size: 0.65rem;
                    text-transform: uppercase;
                    color: var(--text-muted);
                    font-weight: bold;
                    margin-top: 4px;
                    letter-spacing: 0.5px;
                }
                .details-box {
                    background: #0f172a;
                    border: 1px solid var(--border-color);
                    border-radius: 12px;
                    padding: 12px;
                    font-size: 0.75rem;
                    color: var(--text-muted);
                    display: flex;
                    flex-direction: column;
                    gap: 8px;
                }
                .details-row {
                    display: flex;
                    justify-content: space-between;
                }
                .grid-bottom {
                    display: grid;
                    grid-template-columns: 1fr 1fr;
                    gap: 24px;
                }
                .column-title {
                    font-size: 1.1rem;
                    font-weight: 600;
                    margin-bottom: 16px;
                    display: flex;
                    align-items: center;
                    gap: 8px;
                }
                .nodes-list {
                    display: flex;
                    flex-direction: column;
                    gap: 16px;
                }
                .node-card {
                    background: var(--panel-bg);
                    border: 1px solid var(--border-color);
                    border-radius: 16px;
                    padding: 20px;
                    box-shadow: 0 2px 10px rgba(0,0,0,0.2);
                }
                .node-header {
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    margin-bottom: 8px;
                }
                .node-name {
                    font-weight: bold;
                    font-size: 0.95rem;
                }
                .node-badge {
                    font-size: 0.65rem;
                    font-weight: bold;
                    padding: 2px 8px;
                    border-radius: 9999px;
                    text-transform: uppercase;
                }
                .badge-agent {
                    background: rgba(59, 130, 246, 0.15);
                    color: #93c5fd;
                    border: 1px solid rgba(59, 130, 246, 0.3);
                }
                .badge-tool {
                    background: rgba(139, 92, 246, 0.15);
                    color: #c084fc;
                    border: 1px solid rgba(139, 92, 246, 0.3);
                }
                .node-desc {
                    font-size: 0.75rem;
                    color: var(--text-muted);
                    line-height: 1.5;
                    margin-bottom: 12px;
                }
                .node-tags {
                    display: flex;
                    flex-wrap: wrap;
                    gap: 4px;
                    margin-bottom: 12px;
                }
                .node-tag {
                    font-size: 0.65rem;
                    background: #0f172a;
                    color: var(--text-muted);
                    padding: 2px 6px;
                    border-radius: 4px;
                }
                .node-footer {
                    font-size: 0.65rem;
                    color: #4b5563;
                    border-top: 1px solid #1f2937;
                    padding-top: 8px;
                    display: flex;
                    justify-content: space-between;
                }
                .node-footer span {
                    font-family: 'JetBrains Mono', monospace;
                    color: var(--text-muted);
                }
                .sidebar h2 {
                    font-size: 1rem;
                    font-weight: 600;
                    margin-bottom: 16px;
                    display: flex;
                    align-items: center;
                    gap: 8px;
                }
                .state-json {
                    background: #0b0f19;
                    border: 1px solid var(--border-color);
                    border-radius: 12px;
                    padding: 16px;
                    font-family: 'JetBrains Mono', monospace;
                    font-size: 0.75rem;
                    color: #a7f3d0;
                    white-space: pre-wrap;
                    overflow-x: auto;
                    flex-grow: 1;
                }
                .curl-cmd {
                    background: #0b0f19;
                    border: 1px solid var(--border-color);
                    padding: 10px;
                    border-radius: 8px;
                    font-family: 'JetBrains Mono', monospace;
                    font-size: 0.7rem;
                    color: #e5e7eb;
                    overflow-x: auto;
                    margin-top: 4px;
                    user-select: all;
                }
                .no-nodes {
                    text-align: center;
                    padding: 30px;
                    color: var(--text-muted);
                    font-size: 0.8rem;
                    border: 1px dashed var(--border-color);
                    border-radius: 12px;
                }
            </style>
        </head>
        <body>
            <header>
                <div class="logo-area">
                    <h1>🔌 IRC-A Gateway</h1>
                    <p>Real-time Semantic Router & Directory for Financial Agents and MCP Microservices.</p>
                </div>
                <button class="btn-refresh" onclick="updateRegistry()">
                    <span>🔄</span> Refresh Directory
                </button>
            </header>

            <div class="main-layout">
                <div class="content-area">
                    <!-- Top Section -->
                    <div class="grid-top">
                        <!-- Programmatic cURL Info -->
                        <div class="card">
                            <h2><span>💻</span> Programmatic Service Registry (cURL)</h2>
                            <p class="card-desc">To dynamically register a new agent or MCP server, send a POST request to the Gateway. Indexing in the FAISS semantic pool is executed instantly in hot-connect mode.</p>
                            
                            <div style="display: flex; flex-direction: column; gap: 12px;">
                                <div>
                                    <span style="font-size: 0.7rem; font-weight: 600; color: var(--accent-blue);">Register an Agent (A2A):</span>
                                    <div class="curl-cmd">curl -X POST "http://127.0.0.1:8000/register/agent?url=http://127.0.0.1:8104&channels=%23content"</div>
                                </div>
                                <div>
                                    <span style="font-size: 0.7rem; font-weight: 600; color: var(--accent-purple);">Register an MCP Server:</span>
                                    <div class="curl-cmd">curl -X POST "http://127.0.0.1:8000/register/mcp?url=http://127.0.0.1:8102&channels=%23content"</div>
                                </div>
                            </div>
                        </div>

                        <!-- Server Metrics -->
                        <div class="card">
                            <h2>📊 Server Metrics</h2>
                            <div class="stats-grid">
                                <div class="stat-box">
                                    <div class="stat-num" id="stat-agents-count" style="color: var(--accent-blue);">0</div>
                                    <div class="stat-label">Active Agents</div>
                                </div>
                                <div class="stat-box">
                                    <div class="stat-num" id="stat-tools-count" style="color: var(--accent-purple);">0</div>
                                    <div class="stat-label">Indexed Tools</div>
                                </div>
                            </div>
                            <div class="details-box">
                                <div class="details-row">
                                    <span>Semantic Router:</span>
                                    <span style="color: var(--accent-green); font-weight: 600;">FAISS CPU</span>
                                </div>
                                <div class="details-row">
                                    <span>Node Status:</span>
                                    <span style="color: var(--accent-green); font-weight: 600;">ONLINE</span>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- Langsmith Token Metrics Row -->
                    <div class="card" style="background: rgba(59, 130, 246, 0.05); border: 1px solid rgba(59, 130, 246, 0.2);">
                        <h2 style="color: var(--accent-blue);">📊 Langsmith Token Metrics Tracker (Centralized)</h2>
                        <p class="card-desc">Monitors aggregate LLM prompt, completion, and total session tokens consumed across all P2P and A2A executions routed through the BFA network.</p>
                        <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; text-align: center; margin-top: 10px;">
                            <div style="background: #0f172a; padding: 15px; border-radius: 12px; border: 1px solid var(--border-color);">
                                <div style="font-size: 0.75rem; color: var(--text-muted); text-transform: uppercase; font-weight: 600;">Prompt Tokens</div>
                                <div id="metric-prompt" style="font-size: 1.8rem; font-weight: 800; color: var(--text-color); margin-top: 6px;">0</div>
                            </div>
                            <div style="background: #0f172a; padding: 15px; border-radius: 12px; border: 1px solid var(--border-color);">
                                <div style="font-size: 0.75rem; color: var(--text-muted); text-transform: uppercase; font-weight: 600;">Completion Tokens</div>
                                <div id="metric-completion" style="font-size: 1.8rem; font-weight: 800; color: var(--text-color); margin-top: 6px;">0</div>
                            </div>
                            <div style="background: #0f172a; padding: 15px; border-radius: 12px; border: 1px solid var(--border-color);">
                                <div style="font-size: 0.75rem; color: var(--text-muted); text-transform: uppercase; font-weight: 600;">Total Tokens</div>
                                <div id="metric-total" style="font-size: 1.8rem; font-weight: 800; color: var(--accent-purple); margin-top: 6px;">0</div>
                            </div>
                        </div>
                    </div>

                    <!-- Bottom Section: Lists -->
                    <div class="grid-bottom">
                        <!-- Connected Agents -->
                        <div>
                            <div class="column-title">🤖 Connected Agents (<span id="title-agents-count">0</span>)</div>
                            <div class="nodes-list" id="agents-list-container">
                                <div class="no-nodes">No dynamic agents registered.</div>
                            </div>
                        </div>

                        <!-- Connected Tools -->
                        <div>
                            <div class="column-title">🛠️ Indexed MCP Tools (<span id="title-tools-count">0</span>)</div>
                            <div class="nodes-list" id="tools-list-container">
                                <div class="no-nodes">No dynamic MCP servers registered.</div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Sidebar Shared State -->
                <div class="sidebar">
                    <h2>🗂️ Shared State</h2>
                    <div class="state-json" id="state-json-body">{
  "session_id": "session-content-123",
  "status": "ACTIVE",
  "visited_nodes": [
    "writer-agent",
    "reviewer-agent"
  ],
  "last_action": "A2A draft critique completed"
}</div>
                </div>
            </div>

            <script>
                async function updateTokenMetrics() {
                    try {
                        const res = await fetch("/token-metrics");
                        if (!res.ok) return;
                        const data = await res.json();
                        
                        document.getElementById("metric-prompt").textContent = data.prompt_tokens.toLocaleString();
                        document.getElementById("metric-completion").textContent = data.completion_tokens.toLocaleString();
                        document.getElementById("metric-total").textContent = data.total_tokens.toLocaleString();
                    } catch(e) {
                        console.error("Failed to fetch token metrics", e);
                    }
                }

                async function updateRegistry() {
                    try {
                        const res = await fetch("/skills");
                        if (!res.ok) return;
                        const skills = await res.json();
                        
                        const agentsContainer = document.getElementById("agents-list-container");
                        const toolsContainer = document.getElementById("tools-list-container");
                        
                        const items = Object.entries(skills);
                        const agents = items.filter(([_, item]) => item.type === "agent");
                        const tools = items.filter(([_, item]) => item.type === "tool");
                        
                        // Update counts
                        document.getElementById("stat-agents-count").textContent = agents.length;
                        document.getElementById("title-agents-count").textContent = agents.length;
                        document.getElementById("stat-tools-count").textContent = tools.length;
                        document.getElementById("title-tools-count").textContent = tools.length;
                        
                        // Render agents
                        if (agents.length === 0) {
                            agentsContainer.innerHTML = '<div class="no-nodes">No dynamic agents registered.</div>';
                        } else {
                            agentsContainer.innerHTML = agents.map(([id, item]) => `
                                <div class="node-card">
                                    <div class="node-header">
                                        <div class="node-name">${item.name}</div>
                                        <span class="node-badge badge-agent">A2A Agent</span>
                                    </div>
                                    <div class="node-desc">${item.description || 'No description'}</div>
                                    <div class="node-tags">
                                        ${(item.tags || []).map(t => `<span class="node-tag">#${t}</span>`).join('')}
                                    </div>
                                    <div class="node-footer">
                                        ENDPOINT: <span>${item.url}</span>
                                    </div>
                                </div>
                            `).join('');
                        }
                        
                        // Render tools
                        if (tools.length === 0) {
                            toolsContainer.innerHTML = '<div class="no-nodes">No dynamic MCP servers registered.</div>';
                        } else {
                            toolsContainer.innerHTML = tools.map(([name, item]) => `
                                <div class="node-card">
                                    <div class="node-header">
                                        <div class="node-name" style="font-family: 'JetBrains Mono', monospace;">${name}</div>
                                        <span class="node-badge badge-tool">MCP Tool</span>
                                    </div>
                                    <div class="node-desc">${item.description || 'No description'}</div>
                                    <div class="node-tags">
                                        ${(item.tags || []).map(t => `<span class="node-tag">#${t}</span>`).join('')}
                                    </div>
                                    <div class="node-footer">
                                        MCP SERVER: <span>${item.url || item.server_url || ''}</span>
                                    </div>
                                </div>
                            `).join('');
                        }
                        
                        // Update Shared State simulation JSON dynamically based on registered count
                        const stateObj = {
                            "session_id": "session-content-123",
                            "status": agents.length > 0 ? "ACTIVE" : "PENDING_HANDSHAKE",
                            "registered_capabilities": Object.keys(skills),
                            "visited_nodes": agents.map(([_, item]) => item.name)
                        };
                        document.getElementById("state-json-body").textContent = JSON.stringify(stateObj, null, 2);
                        
                    } catch(e) {
                        console.error("Failed to fetch registry skills", e);
                    }
                }
                
                // Set up polling intervals
                setInterval(updateRegistry, 1000);
                setInterval(updateTokenMetrics, 1000);
                
                // Initial loads
                updateRegistry();
                updateTokenMetrics();
            </script>
        </body>
        </html>
        """
        return HTMLResponse(content=html_content)
    else:
        # Return standard JSON response for API calls/tests
        from bfa_sdk.core.gateway import CONFIG, ROUTER, load_persisted_endpoints
        persisted = load_persisted_endpoints()
        return {
            "status": "ok", 
            "registry_size": len(ROUTER.registry) if ROUTER else 0,
            "static_agent_endpoints": CONFIG.agent_endpoints if CONFIG else [],
            "static_mcp_endpoints": CONFIG.mcp_endpoints if CONFIG else [],
            "dynamic_agent_endpoints": persisted["agent_endpoints"],
            "dynamic_mcp_endpoints": persisted["mcp_endpoints"]
        }

if __name__ == "__main__":
    host = os.getenv("BFA_GATEWAY_HOST", "127.0.0.1")
    port = int(os.getenv("BFA_GATEWAY_PORT", "8000"))
    uvicorn.run("gateway:app", host=host, port=port, log_level="warning")
