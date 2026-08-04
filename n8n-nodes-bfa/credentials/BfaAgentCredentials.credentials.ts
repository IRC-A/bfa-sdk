import { ICredentialType, INodeProperties } from 'n8n-workflow';

export class BfaAgentCredentials implements ICredentialType {
	name = 'bfaAgentCredentials';
	displayName = 'BFA Agent & Observability API';
	documentationUrl = 'https://github.com/SandroG1977/bfa-sdk';
	properties: INodeProperties[] = [
		{
			displayName: 'BFA Gateway URL',
			name: 'gatewayUrl',
			type: 'string',
			default: 'http://localhost:8000',
			description: 'URL del servidor Gateway central de BFA / IRC-A',
			required: true,
		},
		{
			displayName: 'BFA License Key (Enterprise)',
			name: 'licenseKey',
			type: 'string',
			typeOptions: {
				password: true,
			},
			default: '',
			description: 'Clave de licencia comercial de BFA para habilitar telemetría y LangSmith',
		},
		{
			displayName: 'Agent Private Key (PEM)',
			name: 'agentPrivateKey',
			type: 'string',
			typeOptions: {
				password: true,
				rows: 4,
			},
			default: '',
			description: 'Clave privada RSA del agente en formato PEM para firmar el handshake del Gateway. Si se deja vacía, se autogenerará una efímera.',
		},
		{
			displayName: 'LangSmith API Key',
			name: 'langsmithApiKey',
			type: 'string',
			typeOptions: {
				password: true,
			},
			default: '',
			description: 'Clave de API para enviar trazas de ejecución a LangSmith',
		},
		{
			displayName: 'LangSmith Endpoint',
			name: 'langsmithEndpoint',
			type: 'string',
			default: 'https://api.smith.langchain.com',
			description: 'URL del endpoint de LangSmith',
		},
	];
}
