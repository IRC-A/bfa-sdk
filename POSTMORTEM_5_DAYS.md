# 📌 IRC-A Gateway & BFA SDK — Post-Mortem & Resumen de Mejoras (Últimos 5 Días)

**Fecha de Reporte:** 4 de Agosto, 2026  
**Proyecto:** BFA (Backend for Agents) SDK & IRC-A Gateway  
**Autor:** Antigravity AI & Sandro Garcia  

---

## 🎯 Resumen Ejecutivo

Durante los últimos 5 días se llevó a cabo un proceso intensivo de **refactorización, securización y optimización del IRC-A Gateway** y el SDK de BFA (`bfa_sdk`). El objetivo principal fue transformar el Gateway en un componente de producción ultra-robusto para mallas multi-agente (*Agent-to-Agent / A2A*) y microservicios de herramientas (*FastMCP*), incorporando **observabilidad visual completa en tiempo real**, **control continuo de salud**, **ruteo antiautorreferencial** y **resiliencia ante reinicios y caídas de nodos**.

---

## 🚀 1. Principales Funcionalidades e Innovaciones Implementadas

### 👁️ 1.1 Observabilidad & Live Transaction Logs
* **Panel Visual Principal (`/`)**: Interfaz web en modo oscuro con métricas en tiempo real, contadores de agentes y herramientas, y el panel lateral **`📜 Live Transaction Logs`** que transmite trazas de peticiones, handshakes, redirecciones P2P y registros en vivo (actualización cada 1 segundo).
* **Pantalla Dedicada de Observabilidad (`/logs` o `/observability`)**:
  * Buscador por texto libre sobre payloads JSON y mensajes.
  * Filtros por tipo de evento (`REGISTRATION`, `DISCOVERY`, `EXECUTION`, `ERROR`, `SYSTEM`).
  * Botones de Pausar/Reanudar streaming en vivo y Limpiar trazas.
  * Vista en tabla interactiva con detalles expandibles en formato JSON formateado.

### 📊 1.2 Langsmith Token Metrics Tracker (Centralizado)
* Endpoint `/report-tokens` y `/token-metrics` para acumulación global de tokens de LLM (Prompt, Completion y Total) consumidos en la red BFA.
* Visualización en tarjetas destacadas dentro del dashboard principal.

### 🔄 1.3 Ruteo Semántico Antiautorreferencial (`exclude_node_id`)
* **Problema:** En búsquedas vectoriales sobre FAISS, el agente emisor (ej: `customers_agent`) podía obtener el puntaje de similitud coseno más alto contra su propia descripción de habilidades, provocando que se auto-seleccionara en un bucle infinito.
* **Solución:**
  1. Implementación del parámetro `exclude_node_id` en el motor `BFASemanticRouter.resolve`.
  2. Al recibir `exclude_node_id`, el motor descarta el candidato #1 autorreferencial y pasa automáticamente al candidato #2 o #3 (la Tool MCP o Agente especialista).
  3. Ampliación del rango de búsqueda en FAISS (`top_k + 5`) para no agotar candidatos.
  4. En `POST /discover`, si no se provee `exclude_node_id`, **el Gateway extrae automáticamente el `sub` del `session_token` del emisor** y lo establece como filtro de descarte de forma 100% transparente.

### 🩺 1.4 Monitoreo de Salud Continuo y Desindexación Automática
* **Función `prune_dead_endpoints()`**: Inspecciona periódicamente la disponibilidad de las URLs de agentes (`/.well-known/agent-card.json`) y herramientas MCP (`/tools`).
* Si un nodo se cae, no responde o da timeout:
  * Se elimina de `ROUTER.registry`.
  * Se purga de `REGISTERED_NODES`.
  * Se remueve de la base persistente `bfa_registry_db.json`.
  * **Reconstruye automáticamente el índice vectorial FAISS**.
  * Emite una traza en el log: `[DISCOVERY] Endpoint 'http://...' is dead/unreachable. Automatically unindexed from FAISS.`
* **Bucle en segundo plano (`health_monitor_loop`)**: Ejecución cada 10 segundos + ejecución instantánea al consultar `/skills`.

---

## 🛠️ 2. Bugs Críticos Detectados y Resoluciones Técnicas (Post-Mortem)

| # | Problema / Síntoma | Causa Raíz | Solución Implementada |
|---|---|---|---|
| **1** | `[Errno 21] Is a directory: 'bfa_registry_db.json'` | Al montar el volumen en `docker-compose.yml`, Docker creó un directorio en el host antes de que existiera el archivo JSON. | Se reemplazó el directorio por un archivo JSON válido `{"agent_endpoints": [], "mcp_endpoints": []}`. |
| **2** | UI mostrando `Connected Agents (0)` e `Indexed Tools (0)` | El endpoint `/skills` se había omitido por error durante una refactorización de rutas, devolviendo `404 Not Found` al frontend. | Se restauró `/skills` consolidando tanto el índice semántico FAISS como `REGISTERED_NODES`. |
| **3** | `409 Conflict: Tool name 'guardar_contacto' is already registered` | Verificaciones estrictas de duplicados bloqueaban el re-registro de herramientas o agentes al reiniciar contenedores. | Se reemplazó el bloqueo 409 por un **Modo Upsert** en `/register/agent` y `/register/mcp`, permitiendo re-registros transparentes. |
| **4** | `ModuleNotFoundError: No module named 'poc'` al iniciar Docker | `poc/gateway.py` invocaba `uvicorn.run("poc.gateway:app")` como texto dentro de `/app`, fallando la resolución de `importlib`. | Se refactorizó `poc/gateway.py` para pasar el objeto de la app directamente: `uvicorn.run(app, host="0.0.0.0", port=port)`. |
| **5** | Pantallas de UI y Observabilidad desapareciendo al recompilar Docker | `poc/gateway.py` mantenía 1.000+ líneas de código antiguo duplicado que sobreescribían `app.router.routes`. | Se limpió `poc/gateway.py` delegando al 100% en `create_gateway_app()` de `bfa_sdk.core.gateway` como fuente única de verdad. |
| **6** | Herramientas/Agentes caídos permaneciendo en FAISS | Falta de un recolector de basura o mecanismo de ping activo en la memoria del ruteador. | Se creó `prune_dead_endpoints()` y el bucle `health_monitor_loop` para desindexar nodos caídos y reconstruir FAISS automáticamente. |

---

## 🔒 3. Clarificaciones de Arquitectura y Seguridad Resolutivas

1. **A2A & FastMCP sin SDK Directo**: Se confirmó que cualquier microservicio que respete la especificación A2A (`/.well-known/agent-card.json`) o FastMCP (`/tools`) puede conectarse directamente al BFA Gateway vía HTTP/REST sin importar la librería cliente utilizada.
2. **Aislamiento por Canales (`IRCA_CHANNELS`)**:
   * Las restricciones de seguridad y alcance no dependen del LLM ni de prompts.
   * Las variables de entorno e identidades filtran el espacio vectorial de FAISS **antes** de la evaluación semántica (Blast Radius acotado por diseño).
3. **Handshake Criptográfico**: Validación mediante PASETO v4 / JWT con firmas de llave pública/privada RSA/ECDSA y tokens efímeros DET (Dynamic Ephemeral Tokens).

---

## 📸 4. Estado Actual del Sistema

* **Gateway Base**: Funcionando en Docker sobre el puerto `8000`.
* **Red Docker Bridge**: Configurada en `irca` (`attachable: true`).
* **Endpoints Activos**:
  * `GET /`: Dashboard visual + Live Transaction Logs.
  * `GET /logs` & `/observability`: Pantalla completa de trazabilidad.
  * `GET /skills`: Catálogo de habilidades de agentes y herramientas MCP.
  * `GET /resolve`, `/resolve/agents`, `/resolve/tools`: Ruteo vectorial FAISS.
  * `POST /discover`: Descubrimiento seguro con DET token + `exclude_node_id`.
  * `POST /register/agent` & `/register/mcp`: Registro upsert y hot-connect.
  * `POST /register/disconnect`: Desconexión limpia de nodos.

---

## 🔮 5. Próximos Pasos Recomendados

1. **Verificación en Staging / Producción**: Mantener el monitoreo de los logs de transacciones en vivo ante cargas concurrentes altas.
2. **Métricas Avanzadas de Latencia**: Añadir medición de latencia promedio en milisegundos por resolución vectorial FAISS en la pantalla de Observabilidad.
3. **Persistencia Avanzada en PostgreSQL/Redis**: En entornos multi-instancia horizontal, reemplazar el archivo `bfa_registry_db.json` por una tabla central en PostgreSQL o Redis Pub/Sub.

---

*Reporte generado por Antigravity AI — Pair Programming Assistant.*
