import {
	IExecuteFunctions,
	INodeExecutionData,
	INodeType,
	INodeTypeDescription,
	NodeApiError,
} from 'n8n-workflow';

import { Client as LangSmithClient, RunTree } from 'langsmith';

// Import LangChain messages to format LLM invocation
import { SystemMessage, HumanMessage, AIMessage } from '@langchain/core/messages';

// Clave pública/secreta para validar licencia comercial BFA Enterprise
const MOCK_LICENSE_KEY_VALID = 'BFA-ENTERPRISE-DEV-KEY-2026';

function validateLicenseKey(licenseKey: string): boolean {
	if (!licenseKey) return false;
	if (licenseKey.trim() === MOCK_LICENSE_KEY_VALID) {
		return true;
	}
	if (licenseKey.startsWith('bfa_lic_') && licenseKey.length > 20) {
		return true;
	}
	return false;
}

export class BfaEntryPointAgent implements INodeType {
	description: INodeTypeDescription = {
		displayName: 'IRC-A EntryPoint Agent (Enterprise)',
		name: 'bfaEntryPointAgent',
		icon: 'file:bfaEntryPointAgent.svg',
		group: ['transform'],
		version: 1,
		description: 'Agente de entrada perimetral con conector de memoria que interactúa con el usuario final y delega tareas.',
		defaults: {
			name: 'IRC-A EntryPoint Agent',
		},
		inputs: [
			'main',
			{
				displayName: 'Primary Model',
				type: 'ai_languageModel',
				required: true,
			},
			{
				displayName: 'Backup Model',
				type: 'ai_languageModel',
			},
			{
				displayName: 'Memory',
				type: 'ai_memory',
				maxConnections: 1,
			},
			{
				displayName: 'Gateway Server',
				type: 'ai_tool',
				maxConnections: 1,
			},
		],
		outputs: ['main'],
		credentials: [
			{
				name: 'bfaAgentCredentials',
				required: false,
			},
		],
		properties: [
			// --- SECCIÓN GENERAL ---
			{
				displayName: 'Session ID',
				name: 'sessionId',
				type: 'string',
				default: '={{ $json.sessionId || "default-session" }}',
				required: true,
				description: 'Identificador único de la sesión del chat del usuario (para persistir memoria)',
			},
			{
				displayName: 'User Message',
				name: 'userMessage',
				type: 'string',
				default: '={{ $json.message }}',
				required: true,
				description: 'Consulta o entrada escrita por el usuario',
			},
			{
				displayName: 'System Prompt',
				name: 'systemPrompt',
				type: 'string',
				typeOptions: {
					rows: 4,
				},
				default: 'Eres el agente de entrada principal de MDBank. Ayudas al usuario y derivas consultas complejas a otros agentes.',
				required: true,
				description: 'Instrucciones del comportamiento y restricciones del agente perimetral',
			},

			// --- OBSERVABILIDAD (LANGSMITH) ---
			{
				displayName: 'Enable LangSmith Tracing',
				name: 'enableLangSmith',
				type: 'boolean',
				default: false,
				description: 'Envía trazas de ejecución detalladas a LangSmith (Requiere Licencia)',
			},
			{
				displayName: 'LangSmith Project Name',
				name: 'langsmithProject',
				type: 'string',
				default: 'bfa-n8n-agents',
				displayOptions: {
					show: {
						enableLangSmith: [true],
					},
				},
				description: 'Proyecto de LangSmith donde se registrarán las ejecuciones',
			},
		],
	};

	async execute(this: IExecuteFunctions): Promise<INodeExecutionData[][]> {
		const items = this.getInputData();
		const returnData: INodeExecutionData[] = [];

		let gatewayUrl = 'http://127.0.0.1:8000';
		let licenseKey = '';
		let langsmithApiKey = '';
		let langsmithEndpoint = '';
		let sessionToken = '';

		try {
			const credentials = await this.getCredentials('bfaAgentCredentials');
			gatewayUrl = (credentials?.gatewayUrl as string) || 'http://127.0.0.1:8000';
			licenseKey = (credentials?.licenseKey as string) || '';
			langsmithApiKey = (credentials?.langsmithApiKey as string) || '';
			langsmithEndpoint = (credentials?.langsmithEndpoint as string) || '';
			sessionToken = (credentials?.sessionToken as string) || '';
		} catch (e) {
			// Fallback offline
		}

		// Intentar leer configuración del Gateway Server conectado abajo
		try {
			const gatewayConnection = await this.getInputConnectionData('ai_tool', 0) as any;
			if (gatewayConnection) {
				gatewayUrl = gatewayConnection.gatewayUrl || gatewayUrl;
				licenseKey = gatewayConnection.licenseKey || licenseKey;
				sessionToken = gatewayConnection.sessionToken || sessionToken;
			}
		} catch (e) {
			// Toleramos que no esté conectado abajo para testeo libre
		}

		for (let i = 0; i < items.length; i++) {
			try {
				const sessionId = this.getNodeParameter('sessionId', i) as string;
				const userMessage = this.getNodeParameter('userMessage', i) as string;
				const systemPrompt = this.getNodeParameter('systemPrompt', i) as string;

				const enableLangSmith = this.getNodeParameter('enableLangSmith', i) as boolean;

				// Obtener las conexiones de los Modelos e inicializar
				const primaryModel = await this.getInputConnectionData('ai_languageModel', 0) as any;
				const backupModel = await this.getInputConnectionData('ai_languageModel', 1) as any;

				if (enableLangSmith || backupModel) {
					if (!validateLicenseKey(licenseKey)) {
						throw new NodeApiError(this.getNode(), {}, {
							message: 'Licencia Comercial Enterprise inválida o faltante.',
							description: 'Por favor, introduce tu BFA License Key para activar el backup de LLM secundario o LangSmith.',
						});
					}
				}

				if (!primaryModel) {
					throw new NodeApiError(this.getNode(), {}, {
						message: 'Falta conectar un Modelo de Lenguaje Primario.',
						description: 'Por favor, arrastra un nodo de modelo (OpenAI, Anthropic, etc.) y conéctalo al pin Primary Model en la parte inferior.',
					});
				}

				// 1. Cargar Historial de Chat mediante el Conector de Memoria
				let chatHistoryMessages: any[] = [];
				const memoryConnection = this.getInputConnectionData('ai_memory', 0) as any;

				if (memoryConnection) {
					try {
						const chatHistory = await memoryConnection.getChatHistory(sessionId);
						if (chatHistory && typeof chatHistory.getMessages === 'function') {
							chatHistoryMessages = await chatHistory.getMessages();
						} else if (chatHistory && Array.isArray(chatHistory)) {
							chatHistoryMessages = chatHistory;
						}
					} catch (e) {
						const err = e as Error;
						console.warn(`BfaEntryPointAgent: No se pudo obtener el historial de la memoria: ${err.message}`);
					}
				}

				// --- CICLO PROTOCOLO IRC-A / BFA: RESOLUCIÓN SEMÁNTICA Y DELEGACIÓN DIRECTA (P2P) ---
				let resolvedRoute: any = null;
				let delegationResultText = '';

				try {
					// A) Consultar al Gateway Server a quién solicitar ayuda
					const discoverRes = await this.helpers.request({
						method: 'POST',
						url: `${gatewayUrl.replace(/\/$/, '')}/discover`,
						qs: { query: userMessage },
						body: {
							session_token: sessionToken || '',
							restricted_params: {}
						},
						json: true,
					}).catch(async () => {
						// Fallback de compatibilidad
						return await this.helpers.request({
							method: 'GET',
							url: `${gatewayUrl.replace(/\/$/, '')}/resolve`,
							qs: { query: userMessage, top_k: 1, threshold: 0.3 },
							json: true,
						});
					});

					if (Array.isArray(discoverRes) && discoverRes.length > 0) {
						resolvedRoute = discoverRes[0];
					} else if (discoverRes && typeof discoverRes === 'object' && discoverRes.url) {
						resolvedRoute = discoverRes;
					}
				} catch (e) {
					console.warn(`BfaEntryPointAgent: Error consultando resolución al Gateway: ${(e as Error).message}`);
				}

				// B) Realizar la llamada P2P (A2A al Agent o FastMCP al MCP)
				if (resolvedRoute && resolvedRoute.url && resolvedRoute.det_token) {
					const detToken = resolvedRoute.det_token;
					const isAgent = resolvedRoute.type === 'agent' || resolvedRoute.url.includes('/a2a');
					
					try {
						if (isAgent) {
							// LLAMADA P2P A2A (Agent)
							const agentWebhookUrl = resolvedRoute.url.replace(/\/$/, '') + '/a2a';
							const a2aResponse = await this.helpers.request({
								method: 'POST',
								url: agentWebhookUrl,
								headers: {
									'Authorization': `Bearer ${detToken}`,
									'Content-Type': 'application/json'
								},
								body: {
									jsonrpc: '2.0',
									method: 'SendMessage',
									params: {
										message: userMessage,
										sender_id: 'entrypoint-agent'
									},
									id: 1
								},
								json: true,
							});
							
							if (a2aResponse && a2aResponse.result) {
								delegationResultText = a2aResponse.result;
							} else if (typeof a2aResponse === 'string') {
								delegationResultText = a2aResponse;
							} else {
								delegationResultText = JSON.stringify(a2aResponse);
							}
						} else {
							// LLAMADA P2P FastMCP (MCP Tool)
							const mcpServerUrl = resolvedRoute.url.replace(/\/$/, '') + '/tools';
							const targetToolName = resolvedRoute.skills?.[0]?.name || resolvedRoute.name || 'query_tool';
							
							const mcpResponse = await this.helpers.request({
								method: 'POST',
								url: mcpServerUrl,
								headers: {
									'Authorization': `Bearer ${detToken}`,
									'Content-Type': 'application/json'
								},
								body: {
									tool: targetToolName,
									arguments: {
										query: userMessage
									}
								},
								json: true,
							});

							delegationResultText = typeof mcpResponse === 'string' ? mcpResponse : JSON.stringify(mcpResponse);
						}
					} catch (p2pErr) {
						console.error(`BfaEntryPointAgent: Fallo la llamada directa P2P: ${(p2pErr as Error).message}`);
						delegationResultText = `[Error de red P2P al llamar a la capacidad resuelta: ${(p2pErr as Error).message}]`;
					}
				}

				// Formatear mensajes históricos para los modelos en la API de LangChain
				const chatMessages: any[] = [];

				// Modificar dinámicamente el System Prompt si hubo delegación exitosa
				let dynamicSystemPrompt = systemPrompt;
				if (delegationResultText) {
					dynamicSystemPrompt = `${systemPrompt}\n\n[CONTEXTO DE RED P2P RESOLVIDO]\nEl agente perimetral consultó al Gateway y obtuvo la siguiente respuesta directa de la red de capacidades para la consulta del usuario:\n"""\n${delegationResultText}\n"""\nPor favor, responde al usuario elaborando en base a esta información de forma cordial y directa.`;
				}
				
				chatMessages.push(new SystemMessage(dynamicSystemPrompt));

				chatHistoryMessages.forEach((msg: any) => {
					const role = msg.type === 'human' || msg.role === 'user' ? 'user' : 'assistant';
					const content = msg.text || msg.content || '';
					if (role === 'user') {
						chatMessages.push(new HumanMessage(content));
					} else {
						chatMessages.push(new AIMessage(content));
					}
				});

				// Añadir el mensaje de entrada actual
				chatMessages.push(new HumanMessage(userMessage));

				// 2. Inicializar LangSmith si está habilitado
				let parentRun: RunTree | undefined;
				if (enableLangSmith) {
					const langsmithProject = this.getNodeParameter('langsmithProject', i) as string;
					const client = new LangSmithClient({
						apiKey: langsmithApiKey || '',
						apiUrl: langsmithEndpoint || '',
					});

					parentRun = new RunTree({
						name: `BFAEntryPointAgent n8n Exec: ${sessionId}`,
						run_type: 'chain',
						inputs: {
							session_id: sessionId,
							message: userMessage,
							history_size: chatHistoryMessages.length,
							delegated_route: resolvedRoute,
						},
						project_name: langsmithProject,
						client,
					});
					await parentRun.postRun();
				}

				let finalResultText = '';
				let usedBackup = false;

				// Crear Run de LangSmith para la llamada de LLM si corresponde
				let llmRun: RunTree | undefined;

				try {
					if (parentRun) {
						llmRun = await parentRun.createChild({
							name: `LLM Call: Primary Model`,
							run_type: 'llm',
							inputs: { messages: chatMessages },
						});
						await llmRun.postRun();
					}

					// Intentar llamar al LLM Primario usando la interfaz de LangChain
					const response = await primaryModel.invoke(chatMessages);
					finalResultText = response.content;

					if (llmRun) {
						await llmRun.end({ response: finalResultText });
						await llmRun.patchRun();
					}
				} catch (primaryError) {
					const pErr = primaryError as Error;
					console.warn(`BfaEntryPointAgent: Falló LLM principal: ${pErr.message}`);
					if (llmRun) {
						await llmRun.end({ error: pErr.message });
						await llmRun.patchRun();
					}

					// Si falló el primario y el backup está conectado, intentar backup
					if (backupModel) {
						usedBackup = true;
						let backupLlmRun: RunTree | undefined;

						try {
							if (parentRun) {
								backupLlmRun = await parentRun.createChild({
									name: `LLM Call: Backup Model`,
									run_type: 'llm',
									inputs: { messages: chatMessages },
								});
								await backupLlmRun.postRun();
							}

							const response = await backupModel.invoke(chatMessages);
							finalResultText = response.content;

							if (backupLlmRun) {
								await backupLlmRun.end({ response: finalResultText });
								await backupLlmRun.patchRun();
							}
							console.log(`BfaEntryPointAgent: Fallback exitoso utilizando LLM secundario de respaldo.`);
						} catch (backupError) {
							const bErr = backupError as Error;
							console.error(`BfaEntryPointAgent: También falló el LLM secundario: ${bErr.message}`);
							if (backupLlmRun) {
								await backupLlmRun.end({ error: bErr.message });
								await backupLlmRun.patchRun();
							}
							
							if (parentRun) {
								await parentRun.end({ error: `Ambos LLMs fallaron. Error primario: ${pErr.message}. Error backup: ${bErr.message}` });
								await parentRun.patchRun();
							}
							
							throw new NodeApiError(this.getNode(), {}, {
								message: 'Ambos proveedores de LLM fallaron en el EntryPoint Agent.',
								description: `Error primario: ${pErr.message}. Error de respaldo: ${bErr.message}`,
							});
						}
					} else {
						if (parentRun) {
							await parentRun.end({ error: pErr.message });
							await parentRun.patchRun();
						}
						throw new NodeApiError(this.getNode(), {}, {
							message: `Falló el LLM principal: ${pErr.message}`,
							description: 'Conecta un Backup Model en la parte inferior para tolerar caídas.',
						});
					}
				}

				// Finalizar el traceo de LangSmith si se activó
				if (parentRun) {
					await parentRun.end({ output: finalResultText, used_backup: usedBackup });
					await parentRun.patchRun();
				}

				// 3. Guardar el nuevo turno en la Memoria (User Message + AI Response)
				if (memoryConnection) {
					try {
						const chatHistory = await memoryConnection.getChatHistory(sessionId);
						if (chatHistory) {
							if (typeof chatHistory.addUserMessage === 'function') {
								await chatHistory.addUserMessage(userMessage);
								await chatHistory.addAIChatMessage(finalResultText);
							} else if (typeof chatHistory.addMessage === 'function') {
								await chatHistory.addMessage({ role: 'user', text: userMessage });
								await chatHistory.addMessage({ role: 'assistant', text: finalResultText });
							}
						}
					} catch (e) {
						const err = e as Error;
						console.warn(`BfaEntryPointAgent: No se pudo guardar la interacción en la memoria: ${err.message}`);
					}
				}

				// Retornar la respuesta final
				returnData.push({
					json: {
						sessionId,
						message: userMessage,
						output: finalResultText,
						usedBackup,
					},
				});
			} catch (error) {
				const err = error as Error;
				if (this.continueOnFail()) {
					returnData.push({
						json: {
							success: false,
							error: err.message,
						},
					});
				} else {
					throw new NodeApiError(this.getNode(), err as any);
				}
			}
		}

		return [returnData];
	}
}
