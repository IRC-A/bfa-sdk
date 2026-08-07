variable "project_id" {
  description = "The Google Cloud Project ID to deploy resources into."
  type        = string
}

variable "region" {
  description = "The Google Cloud region for Cloud Run services."
  type        = string
  default     = "us-central1"
}

variable "gateway_image" {
  description = "The Docker image for the BFA Gateway service."
  type        = string
  default     = "sandrog77/irc-a-gateway:latest"
}

variable "chat_ui_image" {
  description = "The Docker image for the Chat UI conversation frontend."
  type        = string
  default     = "sandrog77/irc-a-chat-ui:latest"
}

variable "cuentas_image" {
  description = "The Docker image for the Mock Cuentas Agent service."
  type        = string
  default     = "sandrog77/irc-a-cuentas:latest"
}

variable "tarjetas_image" {
  description = "The Docker image for the Mock Tarjetas Agent service."
  type        = string
  default     = "sandrog77/irc-a-tarjetas:latest"
}

variable "mdbank_image" {
  description = "The Docker image for the Mock MDBank MCP service."
  type        = string
  default     = "sandrog77/irc-a-mdbank:latest"
}

variable "openai_api_key" {
  description = "OpenAI API key for Gateway embeddings & LLM."
  type        = string
  default     = ""
  sensitive   = true
}

variable "llm_provider" {
  description = "LLM Provider configuration"
  type        = string
  default     = "openai"
}

variable "openai_model" {
  description = "OpenAI model override"
  type        = string
  default     = "gpt-4o-mini"
}

variable "google_api_key" {
  description = "Google API Key"
  type        = string
  default     = ""
  sensitive   = true
}

variable "tavily_api_key" {
  description = "Tavily API Key"
  type        = string
  default     = ""
  sensitive   = true
}

variable "langsmith_tracing" {
  description = "Enable LangSmith tracing"
  type        = string
  default     = "true"
}

variable "langsmith_endpoint" {
  description = "LangSmith API endpoint"
  type        = string
  default     = "https://api.smith.langchain.com"
}

variable "langsmith_api_key" {
  description = "LangSmith API Key"
  type        = string
  default     = ""
  sensitive   = true
}

variable "langsmith_project" {
  description = "LangSmith project name"
  type        = string
  default     = "content-generator-multi-agent"
}
