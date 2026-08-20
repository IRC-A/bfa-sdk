import os
import uvicorn
import asyncio
import random
from bfa_sdk.core.mcp import BFAMCP

gateway_url = os.getenv("BFA_GATEWAY_URL", "http://127.0.0.1:8000")
mcp_public_url = os.getenv("PUBLIC_URL", os.getenv("MCP_URL", "http://127.0.0.1:8001"))

# Initialize BFA-managed MCP Server representing MDBank Core Banking Resources
mcp_server = BFAMCP("MDBank")

@mcp_server.tool(
    name="abrir_cuenta_bancaria",
    description="Simulate opening a new official MDBank account (checking or savings) with IBAN, account number, agency, and initial balance.",
    tags=["account", "open", "create", "checking", "savings", "bank", "abrir cuenta"],
    examples=[
        "open a checking account for John Doe with CPF 12345678900",
        "create a new savings account",
        "open bank account with initial deposit"
    ]
)
async def abrir_cuenta_bancaria(nombre: str, cpf: str, tipo_cuenta: str = "Checking Account", deposito_inicial: float = 1000.0) -> dict:
    """
    Simulates core banking registration for a new bank account.
    Returns structured JSON with IBAN, Agency, Account Number, and Balance.
    """
    account_number = f"{random.randint(1000, 9999)}-{random.randint(10, 99)}"
    agency = "0001"
    clean_acc = account_number.replace("-", "")
    iban = f"MDBK0001000{clean_acc}"
    
    return {
        "status": "SUCCESS",
        "message": f"Bank account successfully opened at MDBank for {nombre}.",
        "details": {
            "holder_name": nombre,
            "cpf": cpf,
            "agency": agency,
            "account_number": account_number,
            "account_type": tipo_cuenta,
            "initial_balance": f"R$ {deposito_inicial:,.2f}",
            "iban": iban,
            "status": "ACTIVE"
        }
    }


@mcp_server.tool(
    name="consultar_cuenta",
    description="Check if a client has an active bank account at MDBank using their CPF.",
    tags=["cuenta", "consultar", "saldo", "estado", "cpf"],
    examples=["verificar si tengo una cuenta activa", "buscar mi cuenta bancaria por CPF", "consultar conta do cliente"]
)
async def consultar_cuenta(cpf: str) -> str:
    """
    Look up existing account details by customer CPF.
    """
    return f"Active account found for CPF: {cpf}. Current balance: R$ 1,200.50."


@mcp_server.tool(
    name="consultar_tarjeta",
    description="Query details and credit limits of client credit cards at MDBank using CPF.",
    tags=["tarjeta", "credito", "limite", "plastico", "consultar"],
    examples=["quiero ver mi tarjeta de credito", "consultar limite de tarjeta", "buscar cartao de credito"]
)
async def consultar_tarjeta(cpf: str) -> str:
    """
    Query approved credit card details and limit by customer CPF.
    """
    return f"MDBank Credit Card for CPF: {cpf}. Approved limit: R$ 5,000.00."


@mcp_server.tool(
    name="crear_o_buscar_cuenta",
    description="Register a new bank account or retrieve it if the client already exists in MDBank database.",
    tags=["crear", "abrir", "cuenta", "registro", "cliente", "novo"],
    examples=["quiero abrir una cuenta bancaria", "registrarme como cliente nuevo", "abrir conta no banco"]
)
async def crear_o_buscar_cuenta(nombre: str, cpf: str) -> str:
    """
    Register or look up a bank customer account.
    """
    return f"Account successfully registered/found for {nombre} (CPF: {cpf}). Account Number: 987654."


@mcp_server.tool(
    name="solicitar_tarjeta",
    description="Process request and issuance of a new physical or digital credit card for MDBank accounts.",
    tags=["tarjeta", "solicitar", "emitir", "plastico", "nuevo"],
    examples=["quiero pedir una tarjeta de credito", "solicitar plastico para mi cuenta", "pedir cartao novo"]
)
async def solicitar_tarjeta(cpf: str, tipo: str) -> str:
    """
    Process new physical/digital credit card issuance request.
    """
    return f"Credit card request of type '{tipo}' processed successfully for CPF: {cpf}."


# Start registration helper on startup asynchronously
async def startup_register():
    await asyncio.sleep(1)
    await mcp_server.register_with_gateway(gateway_url, mcp_public_url)

# Spawn background register task
import threading
loop = asyncio.new_event_loop()
threading.Thread(target=lambda: loop.run_until_complete(startup_register()), daemon=True).start()

# Expose Starlette ASGI app for Uvicorn
app = mcp_server.app

if __name__ == "__main__":
    bind_host = os.getenv("HOST", "0.0.0.0")
    bind_port = int(os.getenv("PORT", 8001))
    print(f"Starting mock MDBank MCP server on {bind_host}:{bind_port}...")
    uvicorn.run(app, host=bind_host, port=bind_port, log_level="info")
