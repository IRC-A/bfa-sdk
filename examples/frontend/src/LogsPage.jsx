import React, { useState, useEffect } from "react";
import AppLayout from "./Layout";
import { GATEWAY_URL } from "./config";

export default function LogsPage() {
	const [logs, setLogs] = useState([]);
	const [loading, setLoading] = useState(false);
	const [searchQuery, setSearchQuery] = useState("");
	const [selectedLog, setSelectedLog] = useState(null);
	const [refreshInterval, setRefreshInterval] = useState(3000); // 3 seconds default polling
	const [filterType, setFilterType] = useState("ALL");

	// Fetch Gateway system logs
	async function fetchLogs() {
		try {
			const response = await fetch(`${GATEWAY_URL}/gateway-logs`);
			if (response.ok) {
				const data = await response.json();
				// Reverse to display newest first
				setLogs(data.reverse());
			}
		} catch (err) {
			console.error("Error fetching system logs:", err);
		}
	}

	// Dynamic polling hook
	useEffect(() => {
		fetchLogs();
		if (refreshInterval === 0) return;
		const interval = setInterval(fetchLogs, refreshInterval);
		return () => clearInterval(interval);
	}, [refreshInterval]);

	// Filter logs based on search query and category selector
	const filteredLogs = logs.filter((log) => {
		const matchesSearch =
			(log.source && log.source.toLowerCase().includes(searchQuery.toLowerCase())) ||
			(log.message && log.message.toLowerCase().includes(searchQuery.toLowerCase()));

		if (filterType === "ALL") return matchesSearch;
		return log.event_type === filterType && matchesSearch;
	});

	// Compute quick metrics
	const totalLogs = logs.length;
	const errorsCount = logs.filter(l => l.event_type === "ERROR").length;
	const discoveriesCount = logs.filter(l => l.event_type === "DISCOVERY").length;
	const registrationsCount = logs.filter(l => l.event_type === "REGISTRATION").length;
	const systemCount = logs.filter(l => l.event_type === "SYSTEM").length;

	// Success rate based on handshake events
	const handshakeSuccessRate = (() => {
		const totalHandshakes = logs.filter(l => l.message && l.message.toLowerCase().includes("handshake")).length;
		if (totalHandshakes === 0) return "100%";
		const failedHandshakes = logs.filter(l => l.event_type === "ERROR" && l.message.toLowerCase().includes("handshake")).length;
		const successRate = ((totalHandshakes - failedHandshakes) / totalHandshakes) * 100;
		return `${successRate.toFixed(1)}%`;
	})();

	// Badges mapping styling helper
	const getBadgeStyle = (type) => {
		switch (type) {
			case "REGISTRATION":
				return "bg-blue-900/60 text-blue-300 border border-blue-800";
			case "DISCOVERY":
				return "bg-teal-900/60 text-teal-300 border border-teal-800";
			case "EXECUTION":
				return "bg-purple-900/60 text-purple-300 border border-purple-800";
			case "SYSTEM":
				return "bg-gray-800/80 text-gray-400 border border-gray-700";
			case "ERROR":
				return "bg-red-950/60 text-red-400 border border-red-900 animate-pulse";
			default:
				return "bg-gray-700 text-gray-300 border border-gray-600";
		}
	};

	return (
		<AppLayout>
			<div className="p-6 flex-1 overflow-auto flex flex-col gap-6 bg-gray-900 font-sans">
				{/* Header */}
				<div className="flex flex-col md:flex-row justify-between items-start md:items-center border-b border-gray-800 pb-4">
					<div>
						<h1 className="text-3xl font-bold text-white flex items-center gap-2">
							<span>📊</span> Observability Console (IRC-A)
						</h1>
						<p className="text-gray-400 text-sm mt-1">
							Security Audit Monitoring, Cryptographic Handshakes, and Traceability for BFA Gateway.
						</p>
					</div>
					<div className="flex items-center gap-3 mt-4 md:mt-0">
						<div className="flex items-center gap-2 bg-gray-800 px-3 py-1.5 rounded-lg border border-gray-700">
							<span className="text-xs text-gray-400">🔄 Refresh:</span>
							<select
								value={refreshInterval}
								onChange={(e) => setRefreshInterval(Number(e.target.value))}
								className="bg-gray-900 text-white text-xs border-none focus:ring-0 rounded cursor-pointer"
							>
								<option value={1000}>Every 1s</option>
								<option value={3000}>Every 3s</option>
								<option value={5000}>Every 5s</option>
								<option value={0}>Paused</option>
							</select>
						</div>
						<button
							onClick={fetchLogs}
							className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg transition text-sm font-semibold border border-blue-500 flex items-center gap-2"
						>
							<span>🔄</span> Refresh
						</button>
					</div>
				</div>

				{/* Cards de Métricas */}
				<div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4">
					<div className="bg-gray-800 p-4 rounded-xl border border-gray-750 flex flex-col justify-between">
						<span className="text-xs font-bold uppercase tracking-wider text-gray-400">Total Events</span>
						<span className="text-3xl font-extrabold text-white mt-2">{totalLogs}</span>
					</div>
					<div className="bg-gray-800 p-4 rounded-xl border border-gray-750 flex flex-col justify-between">
						<span className="text-xs font-bold uppercase tracking-wider text-blue-400">Registrations</span>
						<span className="text-3xl font-extrabold text-blue-400 mt-2">{registrationsCount}</span>
					</div>
					<div className="bg-gray-800 p-4 rounded-xl border border-gray-750 flex flex-col justify-between">
						<span className="text-xs font-bold uppercase tracking-wider text-teal-400">Routing / Resolves</span>
						<span className="text-3xl font-extrabold text-teal-400 mt-2">{discoveriesCount}</span>
					</div>
					<div className="bg-gray-800 p-4 rounded-xl border border-gray-750 flex flex-col justify-between">
						<span className="text-xs font-bold uppercase tracking-wider text-red-400">Errors / Alerts</span>
						<span className="text-3xl font-extrabold text-red-400 mt-2">{errorsCount}</span>
					</div>
					<div className="bg-gray-800 p-4 rounded-xl border border-gray-750 flex flex-col justify-between">
						<span className="text-xs font-bold uppercase tracking-wider text-green-400">Handshake Success</span>
						<span className="text-3xl font-extrabold text-green-400 mt-2">{handshakeSuccessRate}</span>
					</div>
				</div>

				{/* Sección de Tabla y Detalle */}
				<div className="grid grid-cols-1 lg:grid-cols-3 gap-6 flex-1 min-h-[400px]">
					{/* Tabla de Logs (Lado Izquierdo) */}
					<div className="lg:col-span-2 bg-gray-800 rounded-2xl border border-gray-700 overflow-hidden flex flex-col">
						{/* Filtros de Tabla */}
						<div className="p-4 border-b border-gray-700 flex flex-col sm:flex-row justify-between gap-3 bg-gray-800/50">
							<div className="flex gap-2">
								{["ALL", "REGISTRATION", "DISCOVERY", "SYSTEM", "ERROR"].map((type) => (
									<button
										key={type}
										onClick={() => setFilterType(type)}
										className={`px-3 py-1.5 rounded-lg text-xs font-semibold border transition ${
											filterType === type
												? "bg-blue-600 border-blue-500 text-white"
												: "bg-gray-900 border-gray-750 text-gray-400 hover:text-white"
										}`}
									>
										{type}
									</button>
								))}
							</div>
							<input
								type="text"
								placeholder="Search logs by source or message..."
								value={searchQuery}
								onChange={(e) => setSearchQuery(e.target.value)}
								className="px-3 py-1.5 bg-gray-900 border border-gray-700 rounded-lg text-xs text-white placeholder-gray-500 focus:outline-none focus:border-blue-500 max-w-xs w-full"
							/>
						</div>

						{/* Tabla */}
						<div className="flex-1 overflow-auto">
							<table className="w-full text-left text-xs border-collapse">
								<thead>
									<tr className="border-b border-gray-700 bg-gray-900/40 text-gray-400 uppercase tracking-wider font-semibold">
										<th className="p-3">Time</th>
										<th className="p-3">Category</th>
										<th className="p-3">Source / Node</th>
										<th className="p-3">Event / Message</th>
									</tr>
								</thead>
								<tbody>
									{filteredLogs.length === 0 ? (
										<tr>
											<td colSpan={4} className="p-8 text-center text-gray-500">
												No log events found.
											</td>
										</tr>
									) : (
										filteredLogs.map((log, index) => (
											<tr
												key={index}
												onClick={() => setSelectedLog(log)}
												className={`border-b border-gray-750/50 hover:bg-gray-750/30 cursor-pointer transition ${
													selectedLog === log ? "bg-blue-950/20" : ""
												}`}
											>
												<td className="p-3 font-mono text-gray-400 whitespace-nowrap">
													{log.timestamp}
												</td>
												<td className="p-3 whitespace-nowrap">
													<span className={`text-[9px] px-2 py-0.5 rounded-full uppercase font-extrabold ${getBadgeStyle(log.event_type)}`}>
														{log.event_type}
													</span>
												</td>
												<td className="p-3 font-semibold text-white whitespace-nowrap max-w-[120px] overflow-hidden text-ellipsis">
													{log.source}
												</td>
												<td className="p-3 text-gray-300 max-w-[300px] overflow-hidden text-ellipsis whitespace-nowrap">
													{log.message}
												</td>
											</tr>
										))
									)}
								</tbody>
							</table>
						</div>
					</div>

					{/* Detalle del Log (Lado Derecho) */}
					<div className="bg-gray-800 rounded-2xl border border-gray-700 p-5 flex flex-col gap-4 shadow-xl">
						<h2 className="text-lg font-bold text-white border-b border-gray-700 pb-2 flex items-center gap-2">
							<span>🔍</span> Event Details
						</h2>
						{selectedLog ? (
							<div className="flex flex-col gap-4 flex-1 overflow-auto text-xs">
								<div className="grid grid-cols-2 gap-2 bg-gray-900/60 p-3 rounded-xl border border-gray-750">
									<div>
										<span className="text-[10px] uppercase font-bold text-gray-500 block">Timestamp:</span>
										<span className="text-gray-300 font-mono">{selectedLog.timestamp}</span>
									</div>
									<div>
										<span className="text-[10px] uppercase font-bold text-gray-500 block">Category:</span>
										<span className={`inline-block mt-0.5 text-[9px] px-2 py-0.5 rounded-full uppercase font-extrabold ${getBadgeStyle(selectedLog.event_type)}`}>
											{selectedLog.event_type}
										</span>
									</div>
									<div className="col-span-2 mt-1 border-t border-gray-800 pt-2">
										<span className="text-[10px] uppercase font-bold text-gray-500 block">Source:</span>
										<span className="text-blue-400 font-semibold font-mono break-all">{selectedLog.source}</span>
									</div>
								</div>

								<div>
									<span className="text-[10px] uppercase font-bold text-gray-500 block mb-1">Description:</span>
									<div className="p-3 bg-gray-900 border border-gray-750 rounded-xl text-gray-300 leading-relaxed">
										{selectedLog.message}
									</div>
								</div>

								{selectedLog.details && (
									<div className="flex-1 flex flex-col min-h-[150px]">
										<span className="text-[10px] uppercase font-bold text-gray-500 block mb-1">Metadata / Payload:</span>
										<pre className="bg-gray-900 border border-gray-750 p-3 rounded-xl text-green-400 font-mono text-[10px] overflow-auto flex-1 max-h-[220px]">
											{JSON.stringify(selectedLog.details, null, 2)}
										</pre>
									</div>
								)}
							</div>
						) : (
							<div className="flex-1 flex flex-col justify-center items-center text-center p-8 border border-dashed border-gray-700 rounded-xl text-gray-500 text-sm">
								<span>📝</span> Select an event from the list to inspect cryptographic signatures, assigned channels, and DET token metadata.
							</div>
						)}
					</div>
				</div>
			</div>
		</AppLayout>
	);
}
