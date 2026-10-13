// RegistryPage.jsx
import React, { useState, useEffect } from "react";
import AppLayout from "./Layout";
import { useAppState } from "./StateContext";
import { GATEWAY_URL } from "./config";

export default function RegistryPage() {
    const { updateState } = useAppState();
    const [skills, setSkills] = useState({});
    const [loading, setLoading] = useState(false);

    const [agentUrl, setAgentUrl] = useState("http://127.0.0.1:8104");
    const [agentChannels, setAgentChannels] = useState("#content");
    const [mcpUrl, setMcpUrl] = useState("http://127.0.0.1:8102");
    const [mcpChannels, setMcpChannels] = useState("#content");
    const [pendingReg, setPendingReg] = useState(null);
    const [statusMsg, setStatusMsg] = useState(null);

    async function fetchRegistry() {
        setLoading(true);
        try {
            const response = await fetch(`${GATEWAY_URL}/skills`);
            if (response.ok) {
                const data = await response.json();
                setSkills(data);
            }
        } catch (err) {
            console.error("Error fetching skills registry:", err);
        } finally {
            setLoading(false);
        }
    }

    useEffect(() => {
        fetchRegistry();
    }, []);

    function formatChannels(raw) {
        return (raw || "#public")
            .split(",")
            .map((c) => {
                const s = c.trim();
                if (!s) return "";
                return s.startsWith("#") ? s : `#${s}`;
            })
            .filter(Boolean)
            .join(",") || "#public";
    }

    function buildCurl(type, urlVal, chVal) {
        const cleanUrl = (urlVal || "").trim() || (type === "agent" ? "http://127.0.0.1:8104" : "http://127.0.0.1:8102");
        const normCh = formatChannels(chVal);
        const encCh = normCh.replace(/#/g, "%23");
        const path = type === "agent" ? "/register/agent" : "/register/mcp";
        return {
            type,
            cleanUrl,
            normCh,
            apiUrl: `${GATEWAY_URL}${path}?url=${encodeURIComponent(cleanUrl)}&channels=${encodeURIComponent(normCh)}`,
            curlCmd: `curl -X POST "${GATEWAY_URL}${path}?url=${cleanUrl}&channels=${encCh}"`
        };
    }

    async function handleExecuteNow() {
        if (!pendingReg) return;
        const req = pendingReg;
        setPendingReg(null);
        setStatusMsg({ text: `Registering ${req.type.toUpperCase()} at ${req.cleanUrl}...`, error: false });
        try {
            const res = await fetch(req.apiUrl, { method: "POST" });
            const data = await res.json();
            if (res.ok) {
                setStatusMsg({ text: data.message || "Successfully registered!", error: false });
                fetchRegistry();
            } else {
                setStatusMsg({ text: `Registration failed: ${data.detail || JSON.stringify(data)}`, error: true });
            }
        } catch (err) {
            setStatusMsg({ text: `Network error: ${err.message}`, error: true });
        }
    }

    async function handleCopyManual() {
        if (!pendingReg) return;
        try {
            await navigator.clipboard.writeText(pendingReg.curlCmd);
            setStatusMsg({ text: "cURL command copied to clipboard for manual execution in your console.", error: false });
        } catch {
            setStatusMsg({ text: "Copy the cURL command above to run it manually in your console.", error: false });
        }
        setPendingReg(null);
    }

    const agentsList = Object.entries(skills).filter(([_, item]) => item.type === "agent");
    const toolsList = Object.entries(skills).filter(([_, item]) => item.type === "tool");

    const mcpServers = {};
    toolsList.forEach(([name, item]) => {
        const serverUrl = item.server_url || item.url || "http://unknown-mcp-server";
        const nodeId = item.node_id || serverUrl;
        if (!mcpServers[nodeId]) {
            mcpServers[nodeId] = {
                node_id: nodeId,
                url: serverUrl,
                channels: item.channels || ["#public"],
                tools: []
            };
        }
        mcpServers[nodeId].tools.push([name, item]);
    });

    const agentCurlObj = buildCurl("agent", agentUrl, agentChannels);
    const mcpCurlObj = buildCurl("mcp", mcpUrl, mcpChannels);

    return (
        <AppLayout>
            <div className="p-6 flex-1 overflow-auto flex flex-col gap-6 bg-gray-900 font-sans">
                {/* Header */}
                <div className="flex flex-col md:flex-row justify-between items-start md:items-center border-b border-gray-800 pb-4">
                    <div>
                        <h1 className="text-3xl font-bold text-white flex items-center gap-2">
                            <span>🔌</span> IRC-A Central Gateway (BFA)
                        </h1>
                        <p className="text-gray-400 text-sm mt-1">
                            Real-time Semantic Router and Directory for Financial Agents and MCP Microservices.
                        </p>
                    </div>
                    <button 
                        onClick={fetchRegistry}
                        className="mt-4 md:mt-0 px-4 py-2 bg-gray-800 hover:bg-gray-700 text-white rounded-lg transition text-sm font-semibold border border-gray-700 flex items-center gap-2"
                    >
                        <span>🔄</span> Refresh Directory
                    </button>
                </div>

                {/* Main section: Form + Stats */}
                <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                    {/* Register Form */}
                    <div className="lg:col-span-2 bg-gray-800 p-6 rounded-2xl border border-gray-700 shadow-xl flex flex-col justify-between">
                        <div className="flex flex-col gap-4">
                            <h2 className="text-xl font-semibold text-white flex items-center gap-2">
                                <span>💻</span> Programmatic Service Registry (cURL)
                            </h2>
                            <p className="text-gray-400 text-xs">
                                Enter the endpoint below to build the cURL command and choose whether to execute it directly or run it manually in your console:
                            </p>
                            
                            <div className="flex flex-col gap-4 mt-1">
                                <div>
                                    <span className="text-xs font-semibold text-blue-400 block mb-1">Register an Agent (A2A):</span>
                                    <div className="flex gap-2 mb-1.5">
                                        <input
                                            type="text"
                                            value={agentUrl}
                                            onChange={(e) => setAgentUrl(e.target.value)}
                                            placeholder="http://127.0.0.1:8104"
                                            className="flex-1 bg-gray-900 border border-gray-700 rounded-lg px-3 py-1.5 text-xs text-white font-mono"
                                        />
                                        <input
                                            type="text"
                                            value={agentChannels}
                                            onChange={(e) => setAgentChannels(e.target.value)}
                                            placeholder="#public,#content"
                                            className="w-40 bg-gray-900 border border-gray-700 rounded-lg px-3 py-1.5 text-xs text-white font-mono"
                                        />
                                        <button
                                            onClick={() => setPendingReg(agentCurlObj)}
                                            className="px-3 py-1.5 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-xs font-bold whitespace-nowrap"
                                        >
                                            Register Agent
                                        </button>
                                    </div>
                                    <pre className="bg-gray-900 border border-gray-750 p-2.5 rounded-lg text-xs text-gray-300 font-mono overflow-x-auto select-all">
                                        {agentCurlObj.curlCmd}
                                    </pre>
                                </div>
                                <div>
                                    <span className="text-xs font-semibold text-indigo-400 block mb-1">Register an MCP Server:</span>
                                    <div className="flex gap-2 mb-1.5">
                                        <input
                                            type="text"
                                            value={mcpUrl}
                                            onChange={(e) => setMcpUrl(e.target.value)}
                                            placeholder="http://127.0.0.1:8102"
                                            className="flex-1 bg-gray-900 border border-gray-700 rounded-lg px-3 py-1.5 text-xs text-white font-mono"
                                        />
                                        <input
                                            type="text"
                                            value={mcpChannels}
                                            onChange={(e) => setMcpChannels(e.target.value)}
                                            placeholder="#public,#content"
                                            className="w-40 bg-gray-900 border border-gray-700 rounded-lg px-3 py-1.5 text-xs text-white font-mono"
                                        />
                                        <button
                                            onClick={() => setPendingReg(mcpCurlObj)}
                                            className="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-xs font-bold whitespace-nowrap"
                                        >
                                            Register MCP
                                        </button>
                                    </div>
                                    <pre className="bg-gray-900 border border-gray-750 p-2.5 rounded-lg text-xs text-gray-300 font-mono overflow-x-auto select-all">
                                        {mcpCurlObj.curlCmd}
                                    </pre>
                                </div>
                                {statusMsg && (
                                    <div className={`p-2.5 rounded-lg text-xs font-mono border ${statusMsg.error ? "bg-red-900/30 border-red-700 text-red-300" : "bg-emerald-900/30 border-emerald-700 text-emerald-300"}`}>
                                        {statusMsg.text}
                                    </div>
                                )}
                            </div>
                        </div>
                    </div>

                    {/* Stats Card */}
                    <div className="bg-gray-800 p-6 rounded-2xl border border-gray-700 shadow-xl flex flex-col gap-4">
                        <h2 className="text-lg font-semibold text-white">📊 Server Metrics</h2>
                        <div className="grid grid-cols-2 gap-4">
                            <div className="bg-gray-900 p-4 rounded-xl border border-gray-800 text-center">
                                <span className="text-2xl font-bold text-blue-400">{agentsList.length}</span>
                                <p className="text-gray-400 text-[10px] uppercase font-bold tracking-wider mt-1">Active Agents</p>
                            </div>
                            <div className="bg-gray-900 p-4 rounded-xl border border-gray-800 text-center">
                                <span className="text-2xl font-bold text-indigo-400">{toolsList.length}</span>
                                <p className="text-gray-400 text-[10px] uppercase font-bold tracking-wider mt-1">Indexed Tools</p>
                            </div>
                        </div>
                        <div className="bg-gray-900 p-3 rounded-xl border border-gray-800 text-xs text-gray-400">
                            <div className="flex justify-between py-1 border-b border-gray-800">
                                <span>Semantic Router:</span>
                                <span className="text-green-400 font-semibold">FAISS CPU</span>
                            </div>
                            <div className="flex justify-between py-1 mt-1">
                                <span>Node Status:</span>
                                <span className="text-green-400 font-semibold">ONLINE</span>
                            </div>
                        </div>
                    </div>
                </div>

                {/* Confirmation Modal */}
                {pendingReg && (
                    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
                        <div className="bg-gray-800 border border-gray-700 rounded-2xl p-6 max-w-xl w-full shadow-2xl">
                            <h3 className="text-lg font-bold text-white mb-2">
                                Confirm {pendingReg.type === "agent" ? "Agent" : "MCP Server"} Registration
                            </h3>
                            <p className="text-gray-400 text-xs mb-3">
                                The complete cURL command is ready. Would you like to execute it directly now or run it manually in your console?
                            </p>
                            <pre className="bg-gray-900 border border-gray-700 p-3 rounded-lg text-xs text-gray-200 font-mono overflow-x-auto mb-4 select-all">
                                {pendingReg.curlCmd}
                            </pre>
                            <div className="flex justify-end gap-2">
                                <button
                                    onClick={() => setPendingReg(null)}
                                    className="px-3 py-1.5 bg-gray-700 hover:bg-gray-600 text-white rounded-lg text-xs font-semibold"
                                >
                                    Cancel
                                </button>
                                <button
                                    onClick={handleCopyManual}
                                    className="px-3 py-1.5 bg-gray-900 hover:bg-gray-700 border border-indigo-500/50 text-indigo-300 rounded-lg text-xs font-semibold"
                                >
                                    📋 Run Manually (Copy cURL)
                                </button>
                                <button
                                    onClick={handleExecuteNow}
                                    className="px-4 py-1.5 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-xs font-bold"
                                >
                                    ⚡ Execute Now
                                </button>
                            </div>
                        </div>
                    </div>
                )}

                {/* Connected Agents & Tools Lists */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mt-2">
                    {/* Agents list */}
                    <div className="flex flex-col gap-4">
                        <h2 className="text-xl font-semibold text-white flex items-center gap-2">
                            <span>🤖</span> Connected Agents ({agentsList.length})
                        </h2>
                        {agentsList.length === 0 ? (
                            <div className="bg-gray-800 border border-gray-850 text-gray-500 rounded-2xl p-6 text-center text-sm border-dashed">
                                No agents dynamically registered.
                            </div>
                        ) : (
                            <div className="flex flex-col gap-3">
                                {agentsList.map(([id, item]) => {
                                    const rawChannels = item.channels && item.channels.length > 0 ? item.channels : ["#public"];
                                    const formattedChannels = rawChannels.map((c) => (String(c).startsWith("#") ? c : `#${c}`)).join(", ");
                                    const channelSet = new Set(rawChannels.map((c) => String(c).replace(/^#+/, "").toLowerCase()));
                                    const cleanTags = (item.tags || [])
                                        .map((t) => String(t).replace(/^#+/, "").trim())
                                        .filter((t) => t.length > 0 && !channelSet.has(t.toLowerCase()));

                                    return (
                                        <div key={id} className="bg-gray-800 p-4 rounded-2xl border border-gray-700 shadow-md hover:scale-[1.01] transition">
                                            <div className="flex justify-between items-start">
                                                <h3 className="font-bold text-white text-base">{item.name}</h3>
                                                <span className="bg-blue-900/60 text-blue-300 border border-blue-800 text-[10px] px-2 py-0.5 rounded-full uppercase font-bold">
                                                    A2A Agent
                                                </span>
                                            </div>
                                            <p className="text-gray-300 text-xs mt-1.5">{item.description || "No description"}</p>
                                            {cleanTags.length > 0 && (
                                                <div className="flex flex-wrap gap-1 mt-2.5">
                                                    {cleanTags.map((tag) => (
                                                        <span key={tag} className="bg-gray-900 text-gray-400 text-[10px] px-2 py-0.5 rounded-md font-semibold">
                                                            #{tag}
                                                        </span>
                                                    ))}
                                                </div>
                                            )}
                                            <div className="text-xs text-gray-400 mt-3 flex items-center gap-1.5">
                                                <span>registered at</span>
                                                <span className="font-mono text-[11px] text-blue-300 bg-blue-950/50 border border-blue-800/50 px-2 py-0.5 rounded">
                                                    [{formattedChannels}]
                                                </span>
                                            </div>
                                            <div className="text-[10px] text-gray-500 mt-3 border-t border-gray-700/50 pt-2 flex justify-between">
                                                <span>ENDPOINT:</span>
                                                <span className="font-mono text-gray-400 select-all">{item.url}</span>
                                            </div>
                                        </div>
                                    );
                                })}
                            </div>
                        )}
                    </div>

                    {/* Tools list grouped by MCP Server */}
                    <div className="flex flex-col gap-4">
                        <h2 className="text-xl font-semibold text-white flex items-center gap-2">
                            <span>🛠️</span> Indexed MCP Tools ({toolsList.length})
                        </h2>
                        {toolsList.length === 0 ? (
                            <div className="bg-gray-800 border border-gray-850 text-gray-500 rounded-2xl p-6 text-center text-sm border-dashed">
                                No MCP servers dynamically registered.
                            </div>
                        ) : (
                            <div className="flex flex-col gap-4">
                                {Object.values(mcpServers).map((server) => {
                                    const srvChannels = (server.channels && server.channels.length > 0 ? server.channels : ["#public"])
                                        .map((c) => (String(c).startsWith("#") ? c : `#${c}`))
                                        .join(", ");

                                    return (
                                        <div key={server.node_id} className="bg-gray-800/80 p-4 rounded-2xl border border-indigo-500/30 shadow-md flex flex-col gap-3">
                                            <div className="flex justify-between items-center border-b border-gray-700 pb-2.5">
                                                <div>
                                                    <div className="text-sm font-bold text-blue-400 flex items-center gap-1.5">
                                                        <span>🖥️</span> {server.node_id}
                                                    </div>
                                                    <div className="text-xs text-gray-400 mt-1 flex flex-wrap items-center gap-2">
                                                        <span>
                                                            ENDPOINT: <span className="font-mono text-gray-300">{server.url}</span>
                                                        </span>
                                                        <span>•</span>
                                                        <span>
                                                            registered at{" "}
                                                            <span className="font-mono text-[11px] text-blue-300 bg-blue-950/50 border border-blue-800/50 px-1.5 py-0.5 rounded">
                                                                [{srvChannels}]
                                                            </span>
                                                        </span>
                                                    </div>
                                                </div>
                                                <span className="bg-indigo-900/50 text-indigo-300 border border-indigo-700 text-[10px] px-2.5 py-0.5 rounded-full font-bold">
                                                    {server.tools.length} {server.tools.length === 1 ? "Tool" : "Tools"}
                                                </span>
                                            </div>

                                            <div className="flex flex-col gap-2.5">
                                                {server.tools.map(([name, item]) => {
                                                    const schemaProps =
                                                        item.input_schema && item.input_schema.properties
                                                            ? Object.keys(item.input_schema.properties).filter((p) => p !== "delegated_token")
                                                            : [];
                                                    const tagParams = (item.tags || [])
                                                        .map((t) => String(t).replace(/^#+/, "").trim())
                                                        .filter(Boolean);
                                                    const combinedParams = Array.from(new Set([...schemaProps, ...tagParams]));

                                                    return (
                                                        <div key={name} className="bg-gray-900/70 p-3.5 rounded-xl border border-gray-700/80">
                                                            <div className="flex justify-between items-start">
                                                                <h3 className="font-bold text-white text-sm font-mono">{name}</h3>
                                                                <span className="bg-indigo-900/60 text-indigo-300 border border-indigo-800 text-[10px] px-2 py-0.5 rounded-full uppercase font-bold">
                                                                    MCP TOOL
                                                                </span>
                                                            </div>
                                                            <p className="text-gray-300 text-xs mt-1.5">{item.description || "No description"}</p>
                                                            {combinedParams.length > 0 && (
                                                                <div className="text-xs text-gray-400 mt-2.5 flex items-center gap-1.5 flex-wrap">
                                                                    <span>params</span>
                                                                    <span className="font-mono text-[11px] text-purple-300 bg-purple-950/50 border border-purple-800/50 px-2 py-0.5 rounded">
                                                                        [{combinedParams.join(", ")}]
                                                                    </span>
                                                                </div>
                                                            )}
                                                        </div>
                                                    );
                                                })}
                                            </div>
                                        </div>
                                    );
                                })}
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </AppLayout>
    );
}
