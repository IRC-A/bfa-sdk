import {
	IExecuteFunctions,
	IHookFunctions,
	IWebhookFunctions,
	INodeExecutionData,
	INodeType,
	INodeTypeDescription,
	IWebhookResponseData,
	NodeApiError,
} from 'n8n-workflow';

import * as crypto from 'crypto';
import { Client as LangSmithClient, RunTree } from 'langsmith';

// Import LangChain messages to format LLM invocation
import { SystemMessage, HumanMessage } from '@langchain/core/messages';

// Clave pública/secreta simulada para verificar llaves de licencia empresariales BFA
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

export class BfaAgent implements INodeType {
	description: INodeTypeDescription = {
		displayName: 'IRC-A Agent (Enterprise)',
		name: 'bfaAgent',
		icon: 'file:bfaAgent.svg',
		group: ['transform'],
		version: 1,
		description: 'Registra un agente cognitivo en BFA/IRC-A con configuración de LLM Directa (Primario + Backup) y telemetría LangSmith.',
		defaults: {
			name: 'IRC-A Agent',
		},
		inputs: [
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
				displayName: 'Gateway Server',
				type: 'ai_tool',
				maxConnections: 1,
			},
		],
		outputs: ['ai_chain'],
		credentials: [
			{
				name: 'bfaAgentCredentials',
				required: false,
			},
		],
		webhooks: [
			{
				name: 'default',
				httpMethod: 'GET',
				responseMode: 'onReceived',
				path: 'a2a',
			},
			{
				name: 'default',
				httpMethod: 'POST',
				responseMode: 'onReceived',
				path: 'a2a',
			},
		],
		properties: [
			// --- METADATOS DE REGISTRO BFA ---
			{
				displayName: 'Agent ID',
				name: 'agentId',
				type: 'string',
				default: 'my-n8n-agent',
				placeholder: 'ej: tarjetas-agent',
				required: true,
				description: 'Identificador único del agente en la red BFA/IRC-A',
			},
			{
				displayName: 'Agent Name',
				name: 'agentName',
				type: 'string',
				default: 'BFA n8n Agent',
				required: true,
				description: 'Nombre descriptivo del agente',
			},
			{
				displayName: 'Description',
				name: 'description',
				type: 'string',
				default: 'Agente cognitivo expuesto en n8n',
				required: true,
				description: 'Descripción semántica de las capacidades del agente',
			},
			{
				displayName: 'Logical Channels (IRC-A)',
				name: 'channels',
				type: 'string',
				default: '#public',
				description: 'Canales separados por coma donde el agente escuchará',
			},
			{
				displayName: 'Semantic Tags',
				name: 'tags',
				type: 'string',
				default: 'credit, cards, banking',
				description: 'Etiquetas semánticas separadas por coma',
			},
			{
				displayName: 'Usage Examples',
				name: 'examples',
				type: 'string',
				default: 'Ver mis saldos, ¿Cuál es mi saldo actual?',
				description: 'Ejemplos de consultas separados por coma',
			},
			{
				displayName: 'System Prompt',
				name: 'systemPrompt',
				type: 'string',
				typeOptions: {
					rows: 4,
				},
				default: 'Eres un agente bancario experto. Ayuda al usuario con su consulta de forma cordial.',
				required: true,
				description: 'Instrucciones del comportamiento del agente',
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

	webhookMethods = {
		default: {
			async checkExists(this: IHookFunctions): Promise<boolean> {
				return true;
			},
			async create(this: IHookFunctions): Promise<boolean> {
				let gatewayUrl = 'http://127.0.0.1:8000';
				let privateKeyPem = '';
				let licenseKey = '';
				let langsmithApiKey = '';
				let langsmithEndpoint = '';

				try {
					const credentials = await this.getCredentials('bfaAgentCredentials');
					gatewayUrl = (credentials?.gatewayUrl as string) || 'http://127.0.0.1:8000';
					privateKeyPem = (credentials?.agentPrivateKey as string) || '';
					licenseKey = (credentials?.licenseKey as string) || '';
					langsmithApiKey = (credentials?.langsmithApiKey as string) || '';
					langsmithEndpoint = (credentials?.langsmithEndpoint as string) || '';
				} catch (e) {
					// Offline fallback
				}

				const agentId = this.getNodeParameter('agentId') as string;
				const agentName = this.getNodeParameter('agentName') as string;
				const description = this.getNodeParameter('description') as string;
				const channels = (this.getNodeParameter('channels') as string || '#public')
					.split(',')
					.map((ch) => ch.trim());
				const tags = (this.getNodeParameter('tags') as string || '')
					.split(',')
					.map((t) => t.trim())
					.filter(Boolean);
				const examples = (this.getNodeParameter('examples') as string || '')
					.split(',')
					.map((ex) => ex.trim())
					.filter(Boolean);

				const webhookUrl = this.getNodeWebhookUrl('default') as string;

				// Obtener o generar llave RSA
				if (!privateKeyPem) {
					const { privateKey } = crypto.generateKeyPairSync('rsa', {
						modulusLength: 2048,
						publicKeyEncoding: { type: 'spki', format: 'pem' },
						privateKeyEncoding: { type: 'pkcs8', format: 'pem' },
					});
					privateKeyPem = privateKey;
				}

				const publicKey = crypto.createPublicKey(privateKeyPem);
				const publicKeyPem = publicKey.export({ type: 'spki', format: 'pem' }).toString();

				try {
					// 1. Inicializar Handshake /register/init
					const initRes = await this.helpers.request({
						method: 'POST',
						url: `${gatewayUrl.replace(/\/$/, '')}/register/init`,
						body: { node_id: agentId, channels },
						json: true,
					});

					const challenge = initRes.challenge_bytes;

					// 2. Firmar Reto Criptográfico
					const sign = crypto.createSign('SHA256');
					sign.update(challenge);
					sign.end();
					const signature = sign.sign(privateKeyPem).toString('hex');

					// 3. Verificar en Gateway y obtener Token de Sesión
					await this.helpers.request({
						method: 'POST',
						url: `${gatewayUrl.replace(/\/$/, '')}/register/verify`,
						body: {
							node_id: agentId,
							signature,
							public_key: publicKeyPem,
						},
						json: true,
					});

					// 4. Registrar los metadatos semánticos en el Gateway
					await this.helpers.request({
						method: 'POST',
						url: `${gatewayUrl.replace(/\/$/, '')}/register/agent`,
						qs: {
							url: webhookUrl,
							channels: channels.join(','),
							node_id: agentId,
						},
						json: true,
					});

					console.log(`BFAAgent (n8n): Agente '${agentId}' registrado exitosamente.`);
					return true;
				} catch (error) {
					const err = error as Error;
					console.error(`BFAAgent (n8n) Error: Fallo el registro en el Gateway: ${err.message}`);
					throw new NodeApiError(this.getNode(), err as any);
				}
			},
			async delete(this: IHookFunctions): Promise<boolean> {
				let gatewayUrl = 'http://127.0.0.1:8000';
				try {
					const credentials = await this.getCredentials('bfaAgentCredentials');
					gatewayUrl = (credentials?.gatewayUrl as string) || 'http://127.0.0.1:8000';
				} catch (e) {}
				const agentId = this.getNodeParameter('agentId') as string;

				try {
					await this.helpers.request({
						method: 'POST',
						url: `${gatewayUrl.replace(/\/$/, '')}/register/disconnect`,
						body: { node_id: agentId },
						json: true,
					});
					console.log(`BFAAgent (n8n): Agente '${agentId}' desconectado.`);
					return true;
				} catch (error) {
					const err = error as Error;
					console.warn(`BFAAgent (n8n) Warning: No se pudo desconectar el agente: ${err.message}`);
					return false;
				}
			},
		},
	};

	async webhook(this: IWebhookFunctions): Promise<IWebhookResponseData> {
		const req = this.getRequestObject();
		const res = this.getResponseObject();
		const method = req.method;

		const agentId = this.getNodeParameter('agentId') as string;
		const agentName = this.getNodeParameter('agentName') as string;
		const description = this.getNodeParameter('description') as string;
		const tags = (this.getNodeParameter('tags') as string || '').split(',').map((t) => t.trim()).filter(Boolean);
		const examples = (this.getNodeParameter('examples') as string || '').split(',').map((ex) => ex.trim()).filter(Boolean);

		// Manejo de GET: Endpoint del AgentCard para autodescubrimiento
		if (method === 'GET') {
			const agentCard = {
				name: agentName,
				description,
				default_input_modes: ['text'],
				default_output_modes: ['text'],
				skills: [
					{
						id: agentId,
						name: agentName,
						description,
						tags,
						examples,
					},
				],
				version: '1.0.0-enterprise',
				capabilities: { streaming: false },
				supported_interfaces: [
					{
						protocol_binding: 'JSONRPC',
						url: this.getNodeWebhookUrl('default'),
					},
				],
			};
			res.json(agentCard);
			return { noWebhookResponse: true };
		}

		// Manejo de POST: Ejecución de consultas
		const body = req.body || {};
		const userMessage = body.message || body.input || '';
		const systemPrompt = this.getNodeParameter('systemPrompt') as string;

		const enableLangSmith = this.getNodeParameter('enableLangSmith') as boolean;

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
		// Intentar leer configuración del Gateway Server conectado en el pin
		try {
			const gatewayConnection = await this.getInputConnectionData('ai_tool', 0) as any;
			if (gatewayConnection) {
				gatewayUrl = gatewayConnection.gatewayUrl || gatewayUrl;
				licenseKey = gatewayConnection.licenseKey || licenseKey;
				sessionToken = gatewayConnection.sessionToken || sessionToken;
			}
		} catch (e) {
			// Toleramos que no esté conectado
		}


		// Validar licencia si se usa LangSmith o Backup Model
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

		// --- RESOLUCIÓN SEMÁNTICA DE HERRAMIENTAS MCP (P2P) ---
		let resolvedTool: any = null;
		let toolResultText = '';

		try {
			// A) Consultar al Gateway qué herramientas MCP sirven para la consulta
			const toolRes = await this.helpers.request({
				method: 'GET',
				url: `${gatewayUrl.replace(/\/$/, '')}/resolve/tools`,
				qs: { query: userMessage, top_k: 1, threshold: 0.3 },
				json: true,
			});

			if (Array.isArray(toolRes) && toolRes.length > 0) {
				resolvedTool = toolRes[0];
			} else if (toolRes && typeof toolRes === 'object' && toolRes.det_token) {
				resolvedTool = toolRes;
			}
		} catch (e) {
			console.warn(`IRC-A Agent: Error resolviendo herramientas en el Gateway: ${(e as Error).message}`);
		}

		// B) Ejecutar llamada directa P2P al servidor MCP de destino
		if (resolvedTool && resolvedTool.url && resolvedTool.det_token) {
			const detToken = resolvedTool.det_token;
			const mcpServerUrl = resolvedTool.url.replace(/\/$/, '') + '/tools';
			const targetToolName = resolvedTool.skills?.[0]?.name || resolvedTool.name || 'query_tool';

			try {
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

				toolResultText = typeof mcpResponse === 'string' ? mcpResponse : JSON.stringify(mcpResponse);
			} catch (p2pErr) {
				console.error(`IRC-A Agent: Falló la llamada directa P2P al MCP: ${(p2pErr as Error).message}`);
				toolResultText = `[Error de red P2P al llamar a la herramienta MCP: ${(p2pErr as Error).message}]`;
			}
		}

		// Inicializar LangSmith si está habilitado
		let parentRun: RunTree | undefined;
		if (enableLangSmith) {
			const langsmithProject = this.getNodeParameter('langsmithProject') as string;
			const client = new LangSmithClient({
				apiKey: langsmithApiKey || '',
				apiUrl: langsmithEndpoint || '',
			});

			parentRun = new RunTree({
				name: `BFAAgent n8n Exec: ${agentId}`,
				run_type: 'chain',
				inputs: {
					message: userMessage,
					system_prompt: systemPrompt,
					delegated_tool: resolvedTool,
				},
				project_name: langsmithProject,
				client,
			});
			await parentRun.postRun();
		}

		let finalResultText = '';
		let usedBackup = false;

		// Modificar dinámicamente el System Prompt si hubo ejecución de herramienta MCP exitosa
		let dynamicSystemPrompt = systemPrompt;
		if (toolResultText) {
			dynamicSystemPrompt = `${systemPrompt}\n\n[CONTEXTO DE HERRAMIENTA MCP RESOLVIDO DE LA RED]\nEl agente consultó al Gateway centralizado y ejecutó directamente la herramienta MCP de soporte:\n"""\n${toolResultText}\n"""\nPor favor, responde al usuario elaborando en base a esta información de forma cordial y directa.`;
		}

		// Preparar mensajes en formato LangChain
		const messages = [
			new SystemMessage(dynamicSystemPrompt),
			new HumanMessage(userMessage),
		];

		// Crear Run de LangSmith para la llamada de LLM si corresponde
		let llmRun: RunTree | undefined;

		try {
			if (parentRun) {
				llmRun = await parentRun.createChild({
					name: `LLM Call: Primary Model`,
					run_type: 'llm',
					inputs: { messages },
				});
				await llmRun.postRun();
			}

			// Intentar llamar al LLM Primario usando la interfaz de LangChain
			const response = await primaryModel.invoke(messages);
			finalResultText = response.content;

			if (llmRun) {
				await llmRun.end({ response: finalResultText });
				await llmRun.patchRun();
			}
		} catch (primaryError) {
			const pErr = primaryError as Error;
			console.warn(`BFAAgent: Falló LLM principal: ${pErr.message}`);
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
							inputs: { messages },
						});
						await backupLlmRun.postRun();
					}

					const response = await backupModel.invoke(messages);
					finalResultText = response.content;

					if (backupLlmRun) {
						await backupLlmRun.end({ response: finalResultText });
						await backupLlmRun.patchRun();
					}
					console.log(`BFAAgent: Fallback exitoso utilizando LLM secundario de respaldo.`);
				} catch (backupError) {
					const bErr = backupError as Error;
					console.error(`BFAAgent: También falló el LLM secundario: ${bErr.message}`);
					if (backupLlmRun) {
						await backupLlmRun.end({ error: bErr.message });
						await backupLlmRun.patchRun();
					}
					
					if (parentRun) {
						await parentRun.end({ error: `Ambos LLMs fallaron. Error primario: ${pErr.message}. Error backup: ${bErr.message}` });
						await parentRun.patchRun();
					}
					
					throw new NodeApiError(this.getNode(), {}, {
						message: 'Ambos proveedores de LLM fallaron.',
						description: `Error primario: ${pErr.message}. Error de respaldo: ${bErr.message}`,
					});
				}
			} else {
				// Si no hay backup habilitado, propagar error
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

		// Responder al cliente (Gateway de BFA) de forma directa
		res.json(finalResultText);

		return {
			noWebhookResponse: true,
		};
	}

	async execute(this: IExecuteFunctions): Promise<INodeExecutionData[][]> {
		const items = this.getInputData();
		const returnData: INodeExecutionData[] = [];

		for (let i = 0; i < items.length; i++) {
			const agentId = this.getNodeParameter('agentId', i) as string;
			const agentName = this.getNodeParameter('agentName', i) as string;
			const description = this.getNodeParameter('description', i) as string;
			const channels = (this.getNodeParameter('channels', i) as string || '#public').split(',').map((ch) => ch.trim());
			const tags = (this.getNodeParameter('tags', i) as string || '').split(',').map((t) => t.trim()).filter(Boolean);
			const examples = (this.getNodeParameter('examples', i) as string || '').split(',').map((ex) => ex.trim()).filter(Boolean);

			returnData.push({
				json: {
					agentId,
					agentName,
					description,
					channels,
					tags,
					examples,
				}
			});
		}

		return [returnData];
	}
}
