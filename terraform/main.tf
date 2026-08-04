terraform {
  required_version = ">= 1.0.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# Enable Cloud Run API
resource "google_project_service" "cloud_run_api" {
  service            = "run.googleapis.com"
  disable_on_destroy = false
}

# -------------------------------------------------------------
# 1. BFA / IRC-A Gateway Cloud Run Service
# -------------------------------------------------------------
resource "google_cloud_run_v2_service" "gateway" {
  name     = "irc-a-gateway"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    containers {
      image = var.gateway_image

      ports {
        container_port = 8000
      }

      env {
        name  = "BFA_GATEWAY_HOST"
        value = "0.0.0.0"
      }

      env {
        name  = "BFA_GATEWAY_PORT"
        value = "8000"
      }

      env {
        name  = "BFA_USE_MOCK_EMBEDDINGS"
        value = "false"
      }

      env {
        name  = "BFA_USE_OPENAI_EMBEDDINGS"
        value = "true"
      }

      env {
        name  = "OPENAI_API_KEY"
        value = var.openai_api_key
      }

      env {
        name  = "LLM_PROVIDER"
        value = var.llm_provider
      }

      env {
        name  = "OPENAI_MODEL"
        value = var.openai_model
      }

      env {
        name  = "GOOGLE_API_KEY"
        value = var.google_api_key
      }

      env {
        name  = "TAVILY_API_KEY"
        value = var.tavily_api_key
      }

      env {
        name  = "LANGSMITH_TRACING"
        value = var.langsmith_tracing
      }

      env {
        name  = "LANGSMITH_ENDPOINT"
        value = var.langsmith_endpoint
      }

      env {
        name  = "LANGSMITH_API_KEY"
        value = var.langsmith_api_key
      }

      env {
        name  = "LANGSMITH_PROJECT"
        value = var.langsmith_project
      }
    }
  }

  depends_on = [google_project_service.cloud_run_api]
}

# Allow unauthenticated invocation for the Gateway
resource "google_cloud_run_v2_service_iam_member" "gateway_public" {
  location = google_cloud_run_v2_service.gateway.location
  name     = google_cloud_run_v2_service.gateway.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# -------------------------------------------------------------
# 2. Conversation Frontend (Chat UI) Cloud Run Service
# -------------------------------------------------------------
resource "google_cloud_run_v2_service" "chat_ui" {
  name     = "irc-a-chat-ui"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    containers {
      image = var.chat_ui_image

      ports {
        container_port = 3000
      }

      env {
        name  = "REACT_APP_GATEWAY_URL"
        value = google_cloud_run_v2_service.gateway.uri
      }
    }
  }

  depends_on = [google_project_service.cloud_run_api]
}

# Allow unauthenticated invocation for the Chat UI
resource "google_cloud_run_v2_service_iam_member" "chat_ui_public" {
  location = google_cloud_run_v2_service.chat_ui.location
  name     = google_cloud_run_v2_service.chat_ui.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# -------------------------------------------------------------
# 3. Mock Cuentas Agent Cloud Run Service
# -------------------------------------------------------------
resource "google_cloud_run_v2_service" "cuentas" {
  name     = "irc-a-cuentas"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    containers {
      image = var.cuentas_image

      ports {
        container_port = 8002
      }

      env {
        name  = "BFA_GATEWAY_URL"
        value = google_cloud_run_v2_service.gateway.uri
      }
    }
  }

  depends_on = [google_project_service.cloud_run_api]
}

resource "google_cloud_run_v2_service_iam_member" "cuentas_public" {
  location = google_cloud_run_v2_service.cuentas.location
  name     = google_cloud_run_v2_service.cuentas.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# -------------------------------------------------------------
# 6. Mock Tarjetas Agent Cloud Run Service
# -------------------------------------------------------------
resource "google_cloud_run_v2_service" "tarjetas" {
  name     = "irc-a-tarjetas"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    containers {
      image = var.tarjetas_image

      ports {
        container_port = 8003
      }

      env {
        name  = "BFA_GATEWAY_URL"
        value = google_cloud_run_v2_service.gateway.uri
      }
    }
  }

  depends_on = [google_project_service.cloud_run_api]
}

resource "google_cloud_run_v2_service_iam_member" "tarjetas_public" {
  location = google_cloud_run_v2_service.tarjetas.location
  name     = google_cloud_run_v2_service.tarjetas.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# -------------------------------------------------------------
# 7. Mock MDBank MCP Server Cloud Run Service
# -------------------------------------------------------------
resource "google_cloud_run_v2_service" "mdbank" {
  name     = "irc-a-mdbank"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    containers {
      image = var.mdbank_image

      ports {
        container_port = 8001
      }

      env {
        name  = "BFA_GATEWAY_URL"
        value = google_cloud_run_v2_service.gateway.uri
      }
    }
  }

  depends_on = [google_project_service.cloud_run_api]
}

resource "google_cloud_run_v2_service_iam_member" "mdbank_public" {
  location = google_cloud_run_v2_service.mdbank.location
  name     = google_cloud_run_v2_service.mdbank.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
