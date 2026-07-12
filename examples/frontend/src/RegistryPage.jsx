// RegistryPage.jsx
import React, { useState, useEffect } from "react";
import AppLayout from "./Layout";
import { useAppState } from "./StateContext";

export default function RegistryPage() {
    const { updateState } = useAppState();
    const [skills, setSkills] = useState({});
    const [loading, setLoading] = useState(false);
    // Read-only central registry dashboard

    // Fetch active BFA gateway registry
    async function fetchRegistry() {
        setLoading(true);
        try {
            const response = await fetch("http://localhost:8000/skills");
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

    // Programmatic node registration is performed via authenticated API calls (cURL)

    const agentsList = Object.entries(skills).filter(([_, item]) => item.type === "agent");
    const toolsList = Object.entries(skills).filter(([_, item]) => item.type === "tool");

    return (
        <AppLayout>
            <div className="p-6 flex-1 overflow-auto flex flex-col gap-6 bg-gray-900 font-sans">
                {/* Header */}
                <div className="flex flex-col md:flex-row justify-between items-start md:items-center border-b border-gray-800 pb-4">
                    <div>
                        <h1 className="text-3xl font-bold text-white flex items-center gap-2">
                            <span>🔌</span> Nodo Central IRC-A (BFA Gateway)
                        </h1>
                        <p className="text-gray-400 text-sm mt-1">
                            Directorio y Ruteador Semántico de Agentes Financieros y Microservicios MCP en Tiempo Real.
                        </p>
                    </div>
                    <button 
                        onClick={fetchRegistry}
                        className="mt-4 md:mt-0 px-4 py-2 bg-gray-800 hover:bg-gray-700 text-white rounded-lg transition text-sm font-semibold border border-gray-700 flex items-center gap-2"
                    >
                        <span>🔄</span> Actualizar Directorio
                    </button>
                </div>

                {/* Main section: Form + Stats */}
                <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                    {/* Register Form */}
                    <div className="lg:col-span-2 bg-gray-800 p-6 rounded-2xl border border-gray-700 shadow-xl flex flex-col justify-between">
                        <div className="flex flex-col gap-4">
                            <h2 className="text-xl font-semibold text-white flex items-center gap-2">
                                <span>⚡</span> Conectar Nuevo Agente / MCP en Caliente
                            </h2>
                            <p className="text-gray-400 text-xs">
                                Por motivos de seguridad (IRC-A), el registro directo desde la interfaz web ha sido inhabilitado. Realiza el acoplamiento de servicios mediante peticiones programáticas cURL:
                            </p>
                            
                            <div className="flex flex-col gap-3 mt-1">
                                <div>
                                    <span className="text-xs font-semibold text-blue-400 block mb-1">Registrar un Agente (A2A):</span>
                                    <pre className="bg-gray-900 border border-gray-750 p-2.5 rounded-lg text-xs text-gray-300 font-mono overflow-x-auto select-all">
                                        {`curl -X POST "http://localhost:8000/register/agent?url=http://127.0.0.1:8104&channels=%23content"`}
                                    </pre>
                                </div>
                                <div>
                                    <span className="text-xs font-semibold text-indigo-400 block mb-1">Registrar un Servidor MCP:</span>
                                    <pre className="bg-gray-900 border border-gray-750 p-2.5 rounded-lg text-xs text-gray-300 font-mono overflow-x-auto select-all">
                                        {`curl -X POST "http://localhost:8000/register/mcp?url=http://127.0.0.1:8102&channels=%23content"`}
                                    </pre>
                                </div>
                            </div>
                        </div>
                    </div>

                    {/* Stats Card */}
                    <div className="bg-gray-800 p-6 rounded-2xl border border-gray-700 shadow-xl flex flex-col gap-4">
                        <h2 className="text-lg font-semibold text-white">📊 Métricas del Servidor</h2>
                        <div className="grid grid-cols-2 gap-4">
                            <div className="bg-gray-900 p-4 rounded-xl border border-gray-800 text-center">
                                <span className="text-2xl font-bold text-blue-400">{agentsList.length}</span>
                                <p className="text-gray-400 text-[10px] uppercase font-bold tracking-wider mt-1">Agentes Activos</p>
                            </div>
                            <div className="bg-gray-900 p-4 rounded-xl border border-gray-800 text-center">
                                <span className="text-2xl font-bold text-indigo-400">{toolsList.length}</span>
                                <p className="text-gray-400 text-[10px] uppercase font-bold tracking-wider mt-1">Tools Indexadas</p>
                            </div>
                        </div>
                        <div className="bg-gray-900 p-3 rounded-xl border border-gray-800 text-xs text-gray-400">
                            <div className="flex justify-between py-1 border-b border-gray-800">
                                <span>Enrutador Semántico:</span>
                                <span className="text-green-400 font-semibold">FAISS CPU</span>
                            </div>
                            <div className="flex justify-between py-1 mt-1">
                                <span>Estado del Nodo:</span>
                                <span className="text-green-400 font-semibold">ONLINE</span>
                            </div>
                        </div>
                    </div>
                </div>

                {/* Connected Agents & Tools Lists */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mt-2">
                    {/* Agents list */}
                    <div className="flex flex-col gap-4">
                        <h2 className="text-xl font-semibold text-white flex items-center gap-2">
                            <span>🤖</span> Agentes Conectados ({agentsList.length})
                        </h2>
                        {agentsList.length === 0 ? (
                            <div className="bg-gray-800 border border-gray-850 text-gray-500 rounded-2xl p-6 text-center text-sm border-dashed">
                                Ningún agente registrado dinámicamente.
                            </div>
                        ) : (
                            <div className="flex flex-col gap-3">
                                {agentsList.map(([id, item]) => (
                                    <div key={id} className="bg-gray-800 p-4 rounded-2xl border border-gray-700 shadow-md hover:scale-[1.01] transition">
                                        <div className="flex justify-between items-start">
                                            <h3 className="font-bold text-white text-base">{item.name}</h3>
                                            <span className="bg-blue-900/60 text-blue-300 border border-blue-800 text-[10px] px-2 py-0.5 rounded-full uppercase font-bold">
                                                A2A Agent
                                            </span>
                                        </div>
                                        <p className="text-gray-300 text-xs mt-1.5">{item.description}</p>
                                        <div className="flex flex-wrap gap-1 mt-3">
                                            {item.tags.map((tag) => (
                                                <span key={tag} className="bg-gray-900 text-gray-400 text-[10px] px-2 py-0.5 rounded-md font-semibold">
                                                    #{tag}
                                                </span>
                                            ))}
                                        </div>
                                        <div className="text-[10px] text-gray-500 mt-3 border-t border-gray-700/50 pt-2 flex justify-between">
                                            <span>ENDPOINT:</span>
                                            <span className="font-mono text-gray-400 select-all">{item.url}</span>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>

                    {/* Tools list */}
                    <div className="flex flex-col gap-4">
                        <h2 className="text-xl font-semibold text-white flex items-center gap-2">
                            <span>🛠️</span> Herramientas MCP Indexadas ({toolsList.length})
                        </h2>
                        {toolsList.length === 0 ? (
                            <div className="bg-gray-800 border border-gray-850 text-gray-500 rounded-2xl p-6 text-center text-sm border-dashed">
                                Ningún servidor MCP registrado dinámicamente.
                            </div>
                        ) : (
                            <div className="flex flex-col gap-3">
                                {toolsList.map(([name, item]) => (
                                    <div key={name} className="bg-gray-800 p-4 rounded-2xl border border-gray-700 shadow-md hover:scale-[1.01] transition">
                                        <div className="flex justify-between items-start">
                                            <h3 className="font-bold text-white text-base font-mono">{name}</h3>
                                            <span className="bg-indigo-900/60 text-indigo-300 border border-indigo-800 text-[10px] px-2 py-0.5 rounded-full uppercase font-bold">
                                                MCP Tool
                                            </span>
                                        </div>
                                        <p className="text-gray-300 text-xs mt-1.5">{item.description}</p>
                                        <div className="flex flex-wrap gap-1 mt-3">
                                            {item.tags && item.tags.map((tag) => (
                                                <span key={tag} className="bg-gray-900 text-gray-400 text-[10px] px-2 py-0.5 rounded-md font-semibold">
                                                    #{tag}
                                                </span>
                                            ))}
                                        </div>
                                        <div className="text-[10px] text-gray-500 mt-3 border-t border-gray-700/50 pt-2 flex justify-between">
                                            <span>MCP SERVER:</span>
                                            <span className="font-mono text-gray-400 select-all">{item.server_url}</span>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </AppLayout>
    );
}
