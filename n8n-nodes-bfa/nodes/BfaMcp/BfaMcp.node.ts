import {
	IHookFunctions,
	IWebhookFunctions,
	INodeType,
	INodeTypeDescription,
	IWebhookResponseData,
	NodeApiError,
	IExecuteFunctions,
	INodeExecutionData,
} from 'n8n-workflow';

import * as crypto from 'crypto';

function verifyJwtOffline(token: string, publicKeyPem: string): any {
	const parts = token.split('.');
	if (parts.length !== 3) {
		throw new Error('Formato de token JWT inválido.');
	}
	const [headerB64, payloadB64, signatureB64] = parts;
	const verify = crypto.createVerify('RSA-SHA256');
	verify.update(`${headerB64}.${payloadB64}`);
	const signature = Buffer.from(signatureB64, 'base64url');
	const isValid = verify.verify(publicKeyPem, signature);
	if (!isValid) {
		throw new Error('La firma del token no coincide con el Gateway.');
	}
	const payloadJson = Buffer.from(payloadB64, 'base64url').toString('utf8');
	return JSON.parse(payloadJson);
}

export class BfaMcp implements INodeType {
	description: INodeTypeDescription = {
		displayName: 'IRC-A MCP (Enterprise)',
		name: 'bfaMcp',
		icon: 'file:bfaMcp.svg',
		group: ['transform'],
		version: 1,
		description: 'Nodo MCP bidireccional: actúa como Servidor (Proveedor) o Cliente (Consumidor) en el ecosistema BFA.',
		defaults: {
			name: 'IRC-A MCP',
		},
		inputs: [
			{
				displayName: 'Gateway Server',
				type: 'ai_tool',
				maxConnections: 1,
			},
		],
		outputs: ['ai_tool'],
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
				path: 'mcp',
			},
			{
				name: 'default',
				httpMethod: 'POST',
				responseMode: 'onReceived',
				path: 'mcp',
			},
		],
		properties: [
			// --- SELECCIÓN DE MODO ---
			{
				displayName: 'Mode',
				name: 'mode',
				type: 'options',
				options: [
					{
						name: 'Server (Tool Provider)',
						value: 'server',
						description: 'Expone una herramienta al Gateway BFA/IRC-A',
					},
					{
						name: 'Client (Tool Consumer)',
						value: 'client',
						description: 'Consume herramientas de un servidor MCP externo',
					},
				],
				default: 'server',
				description: 'Selecciona el rol de este nodo en el flujo de trabajo',
			},

			// --- PROPIEDADES MODO SERVER (TOOL PROVIDER) ---
			{
				displayName: 'Tool Name',
				name: 'toolName',
				type: 'string',
				default: 'fetch_customer_data',
				required: true,
				displayOptions: {
					show: {
						mode: ['server'],
					},
				},
				description: 'Nombre de la herramienta MCP',
			},
			{
				displayName: 'Description',
				name: 'description',
				type: 'string',
				default: 'Recupera datos financieros y scoring de un cliente de la base de datos.',
				required: true,
				displayOptions: {
					show: {
						mode: ['server'],
					},
				},
				description: 'Descripción detallada utilizada para el enrutamiento semántico (FAISS)',
			},
			{
				displayName: 'Channels',
				name: 'channels',
				type: 'string',
				default: '#public',
				displayOptions: {
					show: {
						mode: ['server'],
					},
				},
				description: 'Canales separados por coma en los que se publicará la herramienta',
			},
			{
				displayName: 'Tags',
				name: 'tags',
				type: 'string',
				default: 'finance, audit, compliance',
				displayOptions: {
					show: {
						mode: ['server'],
					},
				},
				description: 'Etiquetas semánticas separadas por coma',
			},
			{
				displayName: 'Usage Examples',
				name: 'examples',
				type: 'string',
				default: 'Audit transactions for customer ID-882 exceeding 10,000 USD.',
				displayOptions: {
					show: {
						mode: ['server'],
					},
				},
				description: 'Ejemplos de consultas válidas separados por coma',
			},
			{
				displayName: 'Input Schema (JSON)',
				name: 'inputSchema',
				type: 'json',
				default: `{
  "type": "object",
  "properties": {
    "customer_id": {
      "type": "string",
      "description": "ID único del cliente en la base de datos empresarial"
    }
  },
  "required": ["customer_id"]
}`,
				required: true,
				displayOptions: {
					show: {
						mode: ['server'],
					},
				},
				description: 'JSON Schema de los parámetros de entrada que acepta esta herramienta',
			},
			{
				displayName: 'Execution Mode',
				name: 'executionMode',
				type: 'options',
				displayOptions: {
					show: {
						mode: ['server'],
					},
				},
				options: [
					{ name: 'Custom Code (JS/TS)', value: 'customCode' },
					{ name: 'Workflow Trigger', value: 'workflow' },
				],
				default: 'customCode',
				description: 'Cómo se resolverá la ejecución de la herramienta',
			},
			{
				displayName: 'Custom Code (JavaScript)',
				name: 'customCode',
				type: 'string',
				typeOptions: {
					rows: 6,
				},
				default: `// Los argumentos de la herramienta se inyectan en la variable 'args'
const { customer_id } = args;

// Implementación de la lógica de negocio aislada
return {
  customer_id,
  score: 750,
  risk_level: "low",
  timestamp: new Date().toISOString()
};`,
				required: true,
				displayOptions: {
					show: {
						mode: ['server'],
						executionMode: ['customCode'],
					},
				},
				description: 'Código de Node.js que se ejecuta al llamar a la herramienta',
			},

			// --- PROPIEDADES MODO CLIENT (TOOL CONSUMER) ---
			{
				displayName: 'MCP Server URL',
				name: 'serverUrl',
				type: 'string',
				default: 'http://localhost:8001',
				required: true,
				displayOptions: {
					show: {
						mode: ['client'],
					},
				},
				description: 'URL física del servidor MCP externo',
			},
			{
				displayName: 'Tool Name',
				name: 'clientToolName',
				type: 'string',
				default: 'anti_money_laundering_audit',
				required: true,
				displayOptions: {
					show: {
						mode: ['client'],
					},
				},
				description: 'Nombre exacto de la herramienta a ejecutar',
			},
			{
				displayName: 'Arguments (JSON)',
				name: 'clientArguments',
				type: 'json',
				default: `{\n  "customer_id": "customer-882"\n}`,
				required: true,
				displayOptions: {
					show: {
						mode: ['client'],
					},
				},
				description: 'Parámetros que se enviarán a la herramienta en formato JSON',
			},
			{
				displayName: 'Delegated Execution Token (DET)',
				name: 'delegatedTokenOverride',
				type: 'string',
				typeOptions: { password: true },
				default: '',
				displayOptions: {
					show: {
						mode: ['client'],
					},
				},
				description: 'Token DET opcional. Si se deja vacío, el nodo lo solicitará automáticamente al Gateway de BFA.',
			},
		],
	};

	webhookMethods = {
		default: {
			async checkExists(this: IHookFunctions): Promise<boolean> {
				return true;
			},
			async create(this: IHookFunctions): Promise<boolean> {
				const mode = this.getNodeParameter('mode') as string;
				if (mode !== 'server') return true;

				let gatewayUrl = 'http://127.0.0.1:8000';
				try {
					const credentials = await this.getCredentials('bfaAgentCredentials');
					gatewayUrl = (credentials?.gatewayUrl as string) || 'http://127.0.0.1:8000';
				} catch (e) {}

				const toolName = this.getNodeParameter('toolName') as string;
				const channels = (this.getNodeParameter('channels') as string || '#public')
					.split(',')
					.map((ch) => ch.trim());

				const webhookUrl = this.getNodeWebhookUrl('default') as string;

				try {
					// El Gateway de BFA realiza el descubrimiento dinámico leyendo de la URL "/tools"
					await this.helpers.request({
						method: 'POST',
						url: `${gatewayUrl.replace(/\/$/, '')}/register/mcp`,
						qs: {
							url: webhookUrl,
							channels: channels.join(','),
							node_id: toolName,
						},
						json: true,
					});

					console.log(`BFAMCP (n8n Server): Herramienta '${toolName}' registrada en Gateway.`);
					return true;
				} catch (error) {
					const err = error as Error;
					console.error(`BFAMCP (n8n Server) Error: Registro fallido: ${err.message}`);
					throw new NodeApiError(this.getNode(), err as any);
				}
			},
			async delete(this: IHookFunctions): Promise<boolean> {
				const mode = this.getNodeParameter('mode') as string;
				if (mode !== 'server') return true;

				let gatewayUrl = 'http://127.0.0.1:8000';
				try {
					const credentials = await this.getCredentials('bfaAgentCredentials');
					gatewayUrl = (credentials?.gatewayUrl as string) || 'http://127.0.0.1:8000';
				} catch (e) {}

				const toolName = this.getNodeParameter('toolName') as string;

				try {
					await this.helpers.request({
						method: 'POST',
						url: `${gatewayUrl.replace(/\/$/, '')}/register/disconnect`,
						body: { node_id: toolName },
						json: true,
					});
					console.log(`BFAMCP (n8n Server): Desconexión limpia de '${toolName}'.`);
					return true;
				} catch (error) {
					const err = error as Error;
					console.warn(`BFAMCP (n8n Server) Warning: No se pudo desconectar: ${err.message}`);
					return false;
				}
			},
		},
	};

	async webhook(this: IWebhookFunctions): Promise<IWebhookResponseData> {
		const req = this.getRequestObject();
		const res = this.getResponseObject();
		const method = req.method;

		const toolName = this.getNodeParameter('toolName') as string;
		const description = this.getNodeParameter('description') as string;
		const tags = (this.getNodeParameter('tags') as string || '').split(',').map((t) => t.trim()).filter(Boolean);
		const examples = (this.getNodeParameter('examples') as string || '').split(',').map((ex) => ex.trim()).filter(Boolean);
		const inputSchemaStr = this.getNodeParameter('inputSchema') as string;

		let inputSchema = {};
		try {
			inputSchema = JSON.parse(inputSchemaStr);
		} catch (e) {
			inputSchema = { type: 'object' };
		}

		// Manejo de GET: Endpoint del MCP list para autodescubrimiento (/tools)
		if (method === 'GET') {
			const mcpToolList = [
				{
					name: toolName,
					description,
					inputSchema,
					annotations: {
						tags,
						examples,
					},
				},
			];
			res.json(mcpToolList);
			return { noWebhookResponse: true };
		}

		// Manejo de POST: Ejecución de la herramienta
		const body = req.body || {};
		const requestedTool = body.tool;
		const argumentsData = body.arguments || {};
		const delegatedToken = req.headers['authorization']?.replace('Bearer ', '') || body.delegated_token;

		if (!requestedTool || requestedTool !== toolName) {
			res.status(400).send(`Herramienta solicitada '${requestedTool}' no coincide con este nodo.`);
			return { noWebhookResponse: true };
		}

		// 1. Validación de Token DET (Delegated Execution Token) offline mediante JWT
		let gatewayUrl = 'http://127.0.0.1:8000';
		try {
			const credentials = await this.getCredentials('bfaAgentCredentials');
			gatewayUrl = (credentials?.gatewayUrl as string) || 'http://127.0.0.1:8000';
		} catch (e) {}
		
		// Intentar leer configuración del Gateway Server conectado en el pin
		try {
			const gatewayConnection = await (this as any).getInputConnectionData('ai_tool', 0);
			if (gatewayConnection) {
				gatewayUrl = gatewayConnection.gatewayUrl || gatewayUrl;
			}
		} catch (e) {
			// Toleramos que no esté conectado
		}

		let gatewayPubKeyPem = '';
		try {
			// Descargar llave pública del gateway para validar la firma
			const pubRes = await this.helpers.request({
				method: 'GET',
				url: `${gatewayUrl.replace(/\/$/, '')}/public_key`,
				json: true,
			});
			gatewayPubKeyPem = pubRes.public_key;
		} catch (error) {
			console.warn(`BFAMCP (n8n Server): No se pudo descargar la firma pública del Gateway.`);
		}

		if (gatewayPubKeyPem && delegatedToken) {
			try {
				// Validar la firma criptográfica del Gateway localmente usando nuestro método nativo
				verifyJwtOffline(delegatedToken, gatewayPubKeyPem);
			} catch (jwtErr) {
				const jErr = jwtErr as Error;
				res.status(401).send(`DET Token validation failed: Firma inválida. ${jErr.message}`);
				return { noWebhookResponse: true };
			}
		} else if (gatewayPubKeyPem && !delegatedToken) {
			res.status(401).send('DET Token validation failed: Se requiere un token de ejecución delegado.');
			return { noWebhookResponse: true };
		}

		// 2. Ejecutar la Lógica de la Herramienta
		const executionMode = this.getNodeParameter('executionMode') as string;

		if (executionMode === 'customCode') {
			// Ejecutar lógica de código JS directa
			const customCode = this.getNodeParameter('customCode') as string;
			let outputData: any = {};
			try {
				// Evaluar dinámicamente inyectando argumentos
				const runCode = new Function('args', `${customCode}`);
				outputData = runCode(argumentsData);
			} catch (evalErr) {
				const evErr = evalErr as Error;
				res.status(500).send(`Error ejecutando código de la herramienta: ${evErr.message}`);
				return { noWebhookResponse: true };
			}

			// Responder de inmediato
			res.json(outputData);

			return {
				noWebhookResponse: true,
			};
		}

		// Ejecución a través del flujo n8n (Workflow mode)
		return {
			webhookResponse: async (responseData: any) => {
				let finalOutputText = '';
				try {
					if (Array.isArray(responseData) && responseData.length > 0) {
						const firstItem = responseData[0];
						finalOutputText = firstItem.json?.output || firstItem.json?.message || JSON.stringify(firstItem.json);
					} else if (responseData && typeof responseData === 'object') {
						finalOutputText = responseData.output || responseData.message || JSON.stringify(responseData);
					} else {
						finalOutputText = String(responseData);
					}
				} catch (e) {
					finalOutputText = 'Error extrayendo resultado de herramienta de n8n.';
				}

				return {
					body: finalOutputText,
					headers: {
						'Content-Type': 'application/json; charset=utf-8',
					},
					statusCode: 200,
				};
			},
		};
	}

	// --- CÓDIGO DE EJECUCIÓN (CLIENT / CONSUMER MODE) ---
	async execute(this: IExecuteFunctions): Promise<INodeExecutionData[][]> {
		const items = this.getInputData();
		const returnData: INodeExecutionData[] = [];
		const mode = this.getNodeParameter('mode', 0) as string;

		if (mode !== 'client') {
			// En modo servidor, actúa como proveedor de la conexión y retorna sus metadatos al Gateway
			for (let i = 0; i < items.length; i++) {
				const toolName = this.getNodeParameter('toolName', i) as string;
				const description = this.getNodeParameter('description', i) as string;
				const channels = (this.getNodeParameter('channels', i) as string || '#public').split(',').map((ch) => ch.trim());
				const tags = (this.getNodeParameter('tags', i) as string || '').split(',').map((t) => t.trim()).filter(Boolean);
				const examples = (this.getNodeParameter('examples', i) as string || '').split(',').map((ex) => ex.trim()).filter(Boolean);

				returnData.push({
					json: {
						toolName,
						description,
						channels,
						tags,
						examples,
					}
				});
			}
			return [returnData];
		}

		let gatewayUrl = 'http://127.0.0.1:8000';
		try {
			const credentials = await this.getCredentials('bfaAgentCredentials');
			gatewayUrl = (credentials?.gatewayUrl as string) || 'http://127.0.0.1:8000';
		} catch (e) {}
		
		// Intentar leer configuración del Gateway Server conectado en el pin
		try {
			const gatewayConnection = await (this as any).getInputConnectionData('ai_tool', 0);
			if (gatewayConnection) {
				gatewayUrl = gatewayConnection.gatewayUrl || gatewayUrl;
			}
		} catch (e) {
			// Toleramos que no esté conectado
		}
		const serverUrl = this.getNodeParameter('serverUrl', 0) as string;
		const clientToolName = this.getNodeParameter('clientToolName', 0) as string;
		const clientArgumentsStr = this.getNodeParameter('clientArguments', 0) as string;

		let clientArguments = {};
		try {
			clientArguments = typeof clientArgumentsStr === 'object' ? clientArgumentsStr : JSON.parse(clientArgumentsStr);
		} catch (e) {
			throw new NodeApiError(this.getNode(), {}, {
				message: 'Formato de argumentos JSON inválido.',
				description: 'Asegúrate de escribir un JSON válido en el campo Arguments.',
			});
		}

		for (let i = 0; i < items.length; i++) {
			try {
				let headers: Record<string, string> = {
					'Content-Type': 'application/json',
				};

				let detToken = this.getNodeParameter('delegatedTokenOverride', i, '') as string;

				if (!detToken) {
					// Solicitar token DET para el enrutamiento semántico en el Gateway
					try {
						const detRes = await this.helpers.request({
							method: 'GET',
							url: `${gatewayUrl.replace(/\/$/, '')}/resolve`,
							qs: {
								query: clientToolName,
							},
							json: true,
						});
						
						const bestMatch = detRes?.[0];
						if (bestMatch && bestMatch.det_token) {
							detToken = bestMatch.det_token;
						} else {
							throw new Error('El Gateway BFA no retornó un token DET para esta herramienta.');
						}
					} catch (detErr) {
						const dErr = detErr as Error;
						throw new Error(`No se pudo obtener el token de ejecución delegado (DET) del Gateway BFA: ${dErr.message}`);
					}
				}

				headers['Authorization'] = `Bearer ${detToken}`;

				// Invocar herramienta P2P
				const response = await this.helpers.request({
					method: 'POST',
					url: `${serverUrl.replace(/\/$/, '')}/tools`,
					headers,
					body: {
						tool: clientToolName,
						arguments: clientArguments,
					},
					json: true,
				});

				returnData.push({
					json: {
						tool: clientToolName,
						success: true,
						output: response,
					},
				});
			} catch (error) {
				const err = error as Error;
				if (this.continueOnFail()) {
					returnData.push({
						json: {
							tool: clientToolName,
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
