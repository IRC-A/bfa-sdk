output "gateway_url" {
  description = "The public URL of the BFA Gateway Cloud Run service."
  value       = google_cloud_run_v2_service.gateway.uri
}

output "chat_ui_url" {
  description = "The public URL of the Conversation Frontend Chat UI service."
  value       = google_cloud_run_v2_service.chat_ui.uri
}

output "cuentas_url" {
  description = "The public URL of the Mock Cuentas Agent service."
  value       = google_cloud_run_v2_service.cuentas.uri
}

output "tarjetas_url" {
  description = "The public URL of the Mock Tarjetas Agent service."
  value       = google_cloud_run_v2_service.tarjetas.uri
}

output "mdbank_url" {
  description = "The public URL of the Mock MDBank MCP service."
  value       = google_cloud_run_v2_service.mdbank.uri
}

output "dev_to_embed_code" {
  description = "The markdown embed code to paste into your DEV.to article."
  value       = "<!-- dev-embed-cloudrun: ${google_cloud_run_v2_service.gateway.uri} -->"
}
