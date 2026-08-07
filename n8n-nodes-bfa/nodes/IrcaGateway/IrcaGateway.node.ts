import {
	IExecuteFunctions,
	INodeExecutionData,
	INodeType,
	INodeTypeDescription,
	NodeApiError,
} from 'n8n-workflow';

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

export class IrcaGateway implements INodeType {
	description: INodeTypeDescription = {
		displayName: 'IRC-A/BFA Gateway Server',
		name: 'ircaGateway',
		icon: 'file:ircaGateway.svg',
		group: ['transform'],
		version: 1,
		description: 'Nodo de interconexión y ruteador central del protocolo IRC-A y patrón BFA.',
		defaults: {
			name: 'IRC-A/BFA Gateway Server',
		},
		inputs: [],
		outputs: ['ai_tool'],
		credentials: [
			{
				name: 'bfaAgentCredentials',
				required: false,
			},
		],
		properties: [
			// --- SECCIÓN DE ENRUTAMIENTO SEMÁNTICO CENTRALIZADO ---
			{
				displayName: 'Semantic Resolve Options',
				name: 'resolveNotice',
				type: 'notice',
				default: 'Este nodo centralizado resuelve intenciones semánticas evaluando las entradas del flujo previo (ej: mensaje del usuario). También acuña automáticamente tokens DET firmados.',
			},
			{
				displayName: 'Top K Matches',
				name: 'topK',
				type: 'number',
				default: 1,
				description: 'Cantidad de coincidencias máximas a retornar',
			},
			{
				displayName: 'Similarity Threshold',
				name: 'threshold',
				type: 'number',
				typeOptions: {
					minValue: 0,
					maxValue: 1,
				},
				default: 0.3,
				description: 'Límite de score de similitud de coseno para considerar una coincidencia válida',
			},
			{
				displayName: 'Restricted Parameters (JSON)',
				name: 'restrictedParams',
				type: 'json',
				default: '{}',
				description: 'Parámetros restringidos (lockdown) para el token DET del ruteo en formato JSON',
			},
		],
	};

	async execute(this: IExecuteFunctions): Promise<INodeExecutionData[][]> {
		const items = this.getInputData();
		const returnData: INodeExecutionData[] = [];

		let gatewayUrl = 'http://127.0.0.1:8000';
		let licenseKey = '';
		let sessionToken = '';

		try {
			const credentials = await this.getCredentials('bfaAgentCredentials');
			gatewayUrl = (credentials?.gatewayUrl as string) || 'http://127.0.0.1:8000';
			licenseKey = (credentials?.licenseKey as string) || '';
			sessionToken = (credentials?.sessionToken as string) || '';
		} catch (e) {
			// Toleramos que no se provean credenciales en modo offline/desarrollo
		}

		// Validar licencia Enterprise para auditoría y logs
		const hasEnterpriseLicense = validateLicenseKey(licenseKey);

		returnData.push({
			json: {
				gatewayUrl,
				licenseKey,
				sessionToken,
				hasEnterpriseLicense,
				success: true,
			}
		});

		return [returnData];
	}
}
