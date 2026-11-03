#!/usr/bin/env bash
set -e

# Directorio del proyecto
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

# 1. Cargar entorno virtual (.venv)
if [ -d ".venv" ]; then
    echo "📦 Activando entorno virtual (.venv)..."
    source .venv/bin/activate
elif [ -d "../Backend for Agents SDK/.venv" ]; then
    echo "📦 Activando entorno virtual (../Backend for Agents SDK/.venv)..."
    source "../Backend for Agents SDK/.venv/bin/activate"
fi

# 2. Cargar variables de entorno desde .env si existe
ENV_FILE=""
if [ -f .env ]; then
    ENV_FILE=".env"
elif [ -f "../Backend for Agents SDK/.env" ]; then
    ENV_FILE="../Backend for Agents SDK/.env"
elif [ -f .env.example ]; then
    echo "⚠️  No se encontró archivo .env. Creando .env desde .env.example..."
    cp .env.example .env
    ENV_FILE=".env"
fi

if [ -n "$ENV_FILE" ]; then
    echo "📋 Cargando variables desde $ENV_FILE..."
    while IFS='=' read -r key value || [ -n "$key" ]; do
        key=$(echo "$key" | tr -d ' \r\t')
        case "$key" in
            \#*|"") continue ;;
        esac
        value=$(echo "$value" | tr -d '\r' | sed -e 's/^["'"'"']//' -e 's/["'"'"']$//')
        export "$key=$value"
    done < "$ENV_FILE"
fi

# 3. Configuración de Host y Puerto (Gateway)
PORT=${BFA_GATEWAY_PORT:-8000}
HOST=${BFA_GATEWAY_HOST:-"0.0.0.0"}

export BFA_GATEWAY_PORT="$PORT"
export BFA_GATEWAY_HOST="$HOST"

# 4. Liberar puerto si está ocupado por una instancia previa
EXISTING_PID=$(lsof -ti :"$PORT" 2>/dev/null || true)
if [ -n "$EXISTING_PID" ]; then
    echo "⚠️  El puerto $PORT está en uso por PID(s): $EXISTING_PID"
    echo "🛑 Liberando puerto $PORT..."
    kill -15 $EXISTING_PID 2>/dev/null || true
    sleep 1
    STILL_RUNNING=$(lsof -ti :"$PORT" 2>/dev/null || true)
    if [ -n "$STILL_RUNNING" ]; then
        kill -9 $STILL_RUNNING 2>/dev/null || true
        sleep 0.5
    fi
    echo "✅ Puerto $PORT liberado correctamente."
fi

echo "============================================================"
echo "🚀 Iniciando IRC-A / BFA Gateway"
echo "============================================================"
echo "📍 Host:           $HOST"
echo "🌐 Puerto:         $PORT"
echo "🔍 URL Base:       http://127.0.0.1:$PORT"
echo "📋 Dashboard Logs: http://127.0.0.1:$PORT/logs"
echo "📊 Skills Index:   http://127.0.0.1:$PORT/skills"
echo "============================================================"

# 5. Ejecutar Gateway
if command -v irc-a-gateway &> /dev/null; then
    exec irc-a-gateway
elif command -v bfa-gateway &> /dev/null; then
    exec bfa-gateway
else
    python3 -m irca_sdk.core.gateway
fi
