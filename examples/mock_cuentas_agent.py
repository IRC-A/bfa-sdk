import os
import uvicorn
import asyncio
import json
import httpx
from a2a.server.agent_execution.context import RequestContext
from bfa_sdk.core.agent import BFAAgent
try:
    from openai import AsyncOpenAI
except ImportError:
    AsyncOpenAI = None

gateway_url = os.getenv("BFA_GATEWAY_URL", "http://127.0.0.1:8000")
agent_public_url = os.getenv("PUBLIC_URL", os.getenv("AGENT_URL", "http://127.0.0.1:8002"))
openai_api_key = os.getenv("OPENAI_API_KEY")

class MockCuentasAgent(BFAAgent):
    """
    Real AI Accounts Specialist Agent powered by OpenAI subclassing BFAAgent.
    Uses function calling to simulate bank account creation with structured output.
    """
    def __init__(self, url: str):
        super().__init__(
            agent_id="cuentas_agent",
            name="Agente de Cuentas",
            description="Expert banking agent for checking, opening, and managing bank accounts and savings accounts.",
            tags=["cuenta", "abrir cuenta", "caja de ahorro", "cuenta corriente", "registro", "open account"],
            examples=[
                "quiero abrir una cuenta bancaria", 
                "como abro una caja de ahorro?", 
                "crear cuenta corriente",
                "consultar mi cuenta",
                "open a new bank account"
            ],
            url=url,
            gateway_url=gateway_url
        )
        self.openai_client = AsyncOpenAI(api_key=openai_api_key) if (AsyncOpenAI and openai_api_key) else None

    async def run(self, user_message: str, context: RequestContext) -> str:
        """
        Processes user query using OpenAI Chat Completion.
        If user expresses intent to open an account, triggers Function Calling tool 'abrir_cuenta_bancaria'.
        """
        if self.openai_client:
            try:
                # Declare function tool for opening bank accounts
                tools = [
                    {
                        "type": "function",
                        "function": {
                            "name": "abrir_cuenta_bancaria",
                            "description": "Simulates creating and opening a new official bank account at MDBank.",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "nombre": {
                                        "type": "string",
                                        "description": "Full name of the account holder."
                                    },
                                    "cpf": {
                                        "type": "string",
                                        "description": "CPF or identification number of the holder."
                                    },
                                    "tipo_cuenta": {
                                        "type": "string",
                                        "description": "Type of account, e.g. Checking Account or Savings Account.",
                                        "default": "Checking Account"
                                    },
                                    "deposito_inicial": {
                                        "type": "number",
                                        "description": "Initial deposit amount in R$.",
                                        "default": 1000.0
                                    }
                                },
                                "required": ["nombre", "cpf"]
                            }
                        }
                    }
                ]

                messages = [
                    {
                        "role": "system", 
                        "content": (
                            "You are MDBank's Accounts Specialist AI Agent. "
                            "You assist customers with opening bank/savings accounts, checking account balances, "
                            "and managing account information. "
                            "When a user asks to open a new account, extract or request their full name and CPF. "
                            "If testing or if details are missing, use a realistic sample name (e.g., 'Juan Perez') and CPF ('123.456.789-00') "
                            "and call the 'abrir_cuenta_bancaria' tool to open the account. "
                            "Be polite, professional, concise, and helpful."
                        )
                    },
                    {"role": "user", "content": user_message}
                ]

                # Step 1: Request initial completion from LLM with tool calling enabled
                response = await self.openai_client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=messages,
                    tools=tools,
                    tool_choice="auto",
                    temperature=0.7,
                    max_tokens=400
                )

                response_message = response.choices[0].message

                # Step 2: Check if model invoked tool call for account opening
                if response_message.tool_calls:
                    tool_call = response_message.tool_calls[0]
                    function_name = tool_call.function.name
                    function_args = json.loads(tool_call.function.arguments)

                    if function_name == "abrir_cuenta_bancaria":
                        nombre = function_args.get("nombre", "Juan Perez")
                        cpf = function_args.get("cpf", "123.456.789-00")
                        tipo_cuenta = function_args.get("tipo_cuenta", "Checking Account")
                        deposito_inicial = function_args.get("deposito_inicial", 1000.0)

                        import random
                        account_number = f"{random.randint(1000, 9999)}-{random.randint(10, 99)}"
                        agency = "0001"
                        clean_acc = account_number.replace("-", "")
                        iban = f"MDBK0001000{clean_acc}"

                        tool_result = {
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

                        # Append tool response to chat context
                        messages.append(response_message)
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": json.dumps(tool_result)
                        })

                        # Step 3: Call LLM again to synthesize confirmation message for user
                        final_response = await self.openai_client.chat.completions.create(
                            model="gpt-4o-mini",
                            messages=messages,
                            temperature=0.7,
                            max_tokens=400
                        )
                        return final_response.choices[0].message.content.strip()

                return response_message.content.strip() if response_message.content else "How can I assist you with your MDBank account today?"
            except Exception as e:
                print(f"[Cuentas Agent LLM Error]: {e}")
        
        return f"Welcome to MDBank Accounts Service. I can help you open a checking or savings account. How can I assist you today regarding: '{user_message}'?"

agent = MockCuentasAgent(url=agent_public_url)
app = agent.app

if __name__ == "__main__":
    bind_host = os.getenv("HOST", "0.0.0.0")
    bind_port = int(os.getenv("PORT", 8002))
    print(f"Starting Cuentas Agent server on {bind_host}:{bind_port}...")
    uvicorn.run(app, host=bind_host, port=bind_port, log_level="info")
