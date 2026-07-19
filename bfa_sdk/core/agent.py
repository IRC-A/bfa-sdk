# Copyright (c) 2026 Sandro G. All rights reserved.
# Licensed under AGPLv3 / Commercial Dual License.
import abc
import os
import httpx
import json
import time
import asyncio
from contextlib import asynccontextmanager
from typing import List, Dict, Any, Optional
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.types import AgentCapabilities, AgentCard, AgentSkill, AgentInterface
from a2a.server.agent_execution import AgentExecutor
from a2a.server.agent_execution.context import RequestContext
from a2a.server.events.event_queue import EventQueue
from a2a.helpers import new_text_message
from a2a.types import Role
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization
from bfa_sdk.core.paseto import verify_paseto_v4_public

class BFAAgentExecutor(AgentExecutor):
    """
    Internal executor that maps standard A2A execution to BFAAgent's run method.
    """
    def __init__(self, agent_instance):
        super().__init__()
        self.agent_instance = agent_instance

    async def execute(self, context: RequestContext, event_queue: EventQueue):
        try:
            user_input = context.get_user_input()
            # Run the concrete agent logic
            response_text = await self.agent_instance.run(user_input, context=context)
            # Enqueue response as a text message
            await event_queue.enqueue_event(
                new_text_message(str(response_text), role=Role.ROLE_AGENT)
            )
        except Exception as e:
            await event_queue.enqueue_event(
                new_text_message(f"Error in Agent execution: {str(e)}", role=Role.ROLE_AGENT)
            )

    async def cancel(self, context: RequestContext, event_queue: EventQueue):
        pass


class ReplayPreventionCache:
    def __init__(self, maxsize=1000):
        import collections
        self.cache = collections.OrderedDict()
        self.maxsize = maxsize

    def check_and_add(self, jti: str) -> bool:
        if not jti:
            return False
        if jti in self.cache:
            return True
        self.cache[jti] = True
        if len(self.cache) > self.maxsize:
            self.cache.popitem(last=False)
        return False


class BFADETValidationMiddleware(BaseHTTPMiddleware):
    """
    Enforces zero-trust dynamic authorization at the recipient agent node.
    Verifies the PASETO v4.public signature, clock skew, parameters, and jti replay.
    """
    def __init__(self, app, agent_instance):
        super().__init__(app)
        self.agent_instance = agent_instance
        
    async def dispatch(self, request, call_next):
        if request.method == "POST" and request.url.path == "/":
            auth = request.headers.get("authorization")
            token = None
            if auth and auth.lower().startswith("bearer "):
                token = auth[7:].strip()
            else:
                token = request.headers.get("x-det") or request.headers.get("x-irca-det")
                
            if not self.agent_instance.gateway_public_key and not token:
                return await call_next(request)
                
            if not token:
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "error": {
                            "code": -32001,
                            "message": "Unauthorized: Missing IRC-A Delegated Execution Token (DET)"
                        },
                        "id": None
                    },
                    status_code=401
                )
                
            body = await request.body()
            try:
                rpc_payload = json.loads(body.decode('utf-8'))
                method_name = rpc_payload.get("method")
                params = rpc_payload.get("params", {})
                runtime_args = {}
                if isinstance(params, dict):
                    msg = params.get("message", {})
                    if isinstance(msg, dict):
                        parts = msg.get("parts", [])
                        if parts and isinstance(parts[0], dict):
                            query_text = parts[0].get("text", "")
                            import re
                            customer_match = re.search(r"customer\s+(?:id-)?(\w+)", query_text, re.IGNORECASE)
                            if customer_match:
                                runtime_args["customer_id"] = customer_match.group(1)
                            campaign_match = re.search(r"campaign\s+(\S+)", query_text, re.IGNORECASE)
                            if campaign_match:
                                runtime_args["campaign_id"] = campaign_match.group(1)
            except Exception:
                method_name = "SendMessage"
                runtime_args = {}
                
            async def receive():
                return {"type": "http.request", "body": body, "more_body": False}
            request._receive = receive
            
            is_valid = self.agent_instance.verify_incoming_det(token, method_name, runtime_args)
            if not is_valid:
                is_valid = self.agent_instance.verify_incoming_det(token, self.agent_instance.agent_id, runtime_args)
                
            if not is_valid:
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "error": {
                            "code": -32001,
                            "message": "Unauthorized: Invalid or expired IRC-A DET Token"
                        },
                        "id": None
                    },
                    status_code=401
                )
                
        return await call_next(request)


class IRCAHeaderTracingMiddleware(BaseHTTPMiddleware):
    """
    Starlette middleware for loop detection and propagation of transaction correlation context.
    """
    def __init__(self, app, agent_instance):
        super().__init__(app)
        self.agent_instance = agent_instance
        
    async def dispatch(self, request, call_next):
        trace_id = request.headers.get("x-trace-id")
        visited_raw = request.headers.get("x-visited-nodes", "")
        
        if trace_id:
            visited_nodes = [x.strip() for x in visited_raw.split(",") if x.strip()]
            
            # Execution loop mitigation check
            if self.agent_instance.agent_id in visited_nodes:
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "error": {
                            "code": -32000,
                            "message": f"IRC-A Circular Loop Detected: Node '{self.agent_instance.agent_id}' visited twice."
                        },
                        "id": None
                    },
                    status_code=409
                )
                
            # Store values on request state
            request.state.trace_id = trace_id
            request.state.visited_nodes = visited_nodes + [self.agent_instance.agent_id]
            
        return await call_next(request)


class BFAAgent(abc.ABC):
    """
    Abstract Base Class for BFA Agents.
    Inheriting from this class automatically configures an A2A server.
    Developers only need to implement the async run() method.
    """
    def __init__(
        self,
        agent_id: str,
        name: str,
        description: str,
        tags: List[str],
        examples: List[str],
        url: str,
        version: str = "1.0.0",
        private_key: Any = None,
        gateway_public_key: Any = None,
        gateway_url: str = None
    ):
        self.agent_id = agent_id
        self.name = name
        self.description = description
        self.tags = tags
        self.examples = examples
        self.url = url
        self.version = version
        self.gateway_url = gateway_url or os.getenv("BFA_GATEWAY_URL")
        self.replay_cache = ReplayPreventionCache()

        # Load/Generate keys
        if private_key is None:
            self._private_key = ed25519.Ed25519PrivateKey.generate()
        elif isinstance(private_key, str):
            self._private_key = serialization.load_pem_private_key(private_key.encode("utf-8"), password=None)
        else:
            self._private_key = private_key
        self._public_key = self._private_key.public_key()

        # Load gateway public key
        if isinstance(gateway_public_key, str):
            self.gateway_public_key = serialization.load_pem_public_key(gateway_public_key.encode("utf-8"))
        else:
            self.gateway_public_key = gateway_public_key

        # Resolve channels
        raw_channels = os.getenv("IRCA_CHANNELS", "#public")
        self.channels = [ch.strip() for ch in raw_channels.split(",")]

        self.session_token = None
        self.token_expiry = 0

        # Try to download gateway public key if missing
        if not self.gateway_public_key and self.gateway_url:
            try:
                res = httpx.get(f"{self.gateway_url.rstrip('/')}/public_key", timeout=5)
                if res.status_code == 200:
                    pem_str = res.json().get("public_key")
                    self.gateway_public_key = serialization.load_pem_public_key(pem_str.encode("utf-8"))
            except Exception as e:
                print(f"BFAAgent Warning: Could not download gateway public key: {e}")

        # Create default A2A skill representing this agent
        self.skill = AgentSkill(
            id=self.agent_id,
            name=self.name,
            description=self.description,
            tags=self.tags,
            examples=self.examples
        )

        # Create AgentCard representation for BFA Discovery
        self.agent_card = AgentCard(
            name=self.name,
            description=self.description,
            default_input_modes=["text"],
            default_output_modes=["text"],
            skills=[self.skill],
            version=self.version,
            capabilities=AgentCapabilities(streaming=True),
            supported_interfaces=[
                AgentInterface(
                    protocol_binding="JSONRPC",
                    url=self.url,
                )
            ]
        )

        self.task_store = InMemoryTaskStore()
        self.executor = BFAAgentExecutor(self)
        self.http_handler = DefaultRequestHandler(
            agent_executor=self.executor,
            task_store=self.task_store,
            agent_card=self.agent_card
        )

        # Setup standard routes
        routes = []
        routes.extend(create_agent_card_routes(self.agent_card))
        routes.extend(create_jsonrpc_routes(request_handler=self.http_handler, rpc_url="/"))
        self.app = Starlette(routes=routes)
        self.app.add_middleware(BFADETValidationMiddleware, agent_instance=self)
        self.app.add_middleware(IRCAHeaderTracingMiddleware, agent_instance=self)

        # Register shutdown hook to disconnect from Gateway cleanly
        async def shutdown_event():
            if self.gateway_url:
                try:
                    async with httpx.AsyncClient() as client:
                        await client.post(
                            f"{self.gateway_url.rstrip('/')}/register/disconnect",
                            json={"node_id": self.agent_id},
                            timeout=3
                        )
                except Exception as e:
                    print(f"BFAAgent Warning: Failed to disconnect from gateway on shutdown: {e}")

        # Register lifespan-based teardown handler dynamically
        old_lifespan = self.app.router.lifespan_context
        @asynccontextmanager
        async def wrapped_lifespan(app_inst):
            async with old_lifespan(app_inst) as yielded_val:
                yield yielded_val
                await shutdown_event()
        self.app.router.lifespan_context = wrapped_lifespan

        # Run auto-registration
        if self.gateway_url:
            self._auto_register_to_gateway()

    @property
    def public_key_pem(self) -> str:
        pem = self._public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )
        return pem.decode("utf-8")

    def _auto_register_to_gateway(self) -> bool:
        """Spawns register_with_gateway as a non-blocking background task."""
        if not self.gateway_url:
            return False
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.register_with_gateway(self.gateway_url))
            return True
        except RuntimeError:
            import threading
            threading.Thread(
                target=lambda: asyncio.run(self.register_with_gateway(self.gateway_url)),
                daemon=True
            ).start()
            return True

    async def register_with_gateway(self, gateway_url: str) -> bool:
        """
        Dynamically register this agent with BFA Gateway using cryptographic challenge-response,
        falling back to simple registration if unsupported.
        """
        # Delay slightly to allow the local Uvicorn/Starlette port to bind and listen
        await asyncio.sleep(1.0)
        
        self.gateway_url = gateway_url
        init_url = f"{gateway_url.rstrip('/')}/register/init"
        verify_url = f"{gateway_url.rstrip('/')}/register/verify"
        fallback_url = f"{gateway_url.rstrip('/')}/register/agent"
        
        try:
            # 1. Initialize challenge
            async with httpx.AsyncClient() as client:
                # Try to download gateway public key if still missing
                if not self.gateway_public_key:
                    try:
                        res_pub = await client.get(f"{gateway_url.rstrip('/')}/public_key", timeout=5)
                        if res_pub.status_code == 200:
                            pem_str = res_pub.json().get("public_key")
                            from cryptography.hazmat.primitives.serialization import load_pem_public_key
                            self.gateway_public_key = load_pem_public_key(pem_str.encode("utf-8"))
                    except Exception as e:
                        print(f"BFAAgent Warning: Could not download gateway public key during registration: {e}")

                res = await client.post(init_url, json={"node_id": self.agent_id, "channels": self.channels}, timeout=5)
                if res.status_code in (404, 405, 501):
                    raise NotImplementedError("Gateway does not support cryptographic challenge-response")
                if res.status_code != 200:
                    raise NotImplementedError()
                challenge = res.json()["challenge_bytes"]
                
                # 2. Sign Challenge
                signature = self._private_key.sign(
                    challenge.encode("utf-8")
                )
                
                # 3. Verify Challenge and obtain Session JWT
                res_verify = await client.post(verify_url, json={
                    "node_id": self.agent_id,
                    "signature": signature.hex(),
                    "public_key": self.public_key_pem
                }, timeout=5)
                
                if res_verify.status_code == 200:
                    data = res_verify.json()
                    self.session_token = data["session_token"]
                    self.token_expiry = data["expiry"]
                    
                    # Also register URL/channels in gateway index
                    await client.post(
                        fallback_url,
                        params={"url": self.url, "channels": ",".join(self.channels), "node_id": self.agent_id},
                        timeout=5
                    )
                    print(f"BFAAgent: Successfully registered '{self.agent_id}' via cryptographic handshake.")
                    return True
                else:
                    raise NotImplementedError()
        except (NotImplementedError, KeyError, Exception):
            # Fall back to simple, unauthenticated registration for compatibility
            try:
                async with httpx.AsyncClient() as client:
                    res_simple = await client.post(
                        fallback_url,
                        params={"url": self.url, "channels": ",".join(self.channels), "node_id": self.agent_id},
                        timeout=5
                    )
                    if res_simple.status_code == 200:
                        print(f"BFAAgent: Successfully registered '{self.agent_id}' via simple registration fallback.")
                        return True
                    else:
                        print(f"BFAAgent Error: Registration fallback failed with status {res_simple.status_code}: {res_simple.text}")
                        return False
            except Exception as ex:
                print(f"BFAAgent Error: Failed to connect to Gateway fallback at {fallback_url}: {ex}")
                return False

    def verify_incoming_det(self, delegated_token: str, expected_function: str, runtime_args: dict) -> bool:
        """
        Offline Decentralized Verification performed locally by the agent node.
        Validates the BFA-Gateway signature and enforces parameter lock-down.
        """
        if not self.gateway_public_key:
            return False
        try:
            decoded_det = verify_paseto_v4_public(delegated_token, self.gateway_public_key)
            
            # Clock skew validation (5s tolerance)
            exp = decoded_det.get("exp", 0)
            if exp + 5 < time.time():
                print("BFAAgent verify_incoming_det failed: Token expired")
                return False
                
            # Replay Attack prevention check
            jti = decoded_det.get("jti")
            if self.replay_cache.check_and_add(jti):
                print(f"BFAAgent verify_incoming_det failed: Replay attack detected for jti '{jti}'")
                return False
            
            # Audience validation
            aud = decoded_det.get("aud")
            if aud not in (self.agent_id, expected_function):
                print(f"BFAAgent verify_incoming_det failed: aud '{aud}' not in {(self.agent_id, expected_function)}")
                return False

            # Scope validation
            permitted = decoded_det.get("permitted_action")
            if permitted != expected_function:
                print(f"BFAAgent verify_incoming_det failed: permitted_action '{permitted}' != expected_function '{expected_function}'")
                return False
                
            # Parameter lockdown verification
            for key, value in decoded_det.get("restricted_params", {}).items():
                if runtime_args.get(key) != value:
                    print(f"BFAAgent verify_incoming_det failed: parameter '{key}' lockdown failed. Expected '{value}', got '{runtime_args.get(key)}'")
                    return False
            
            return True
        except Exception as e:
            print(f"BFAAgent verify_incoming_det exception: {e}")
            return False

    @abc.abstractmethod
    async def run(self, user_message: str, context: RequestContext) -> str:
        """
        Process the user message and return the agent's response.
        Must be implemented by subclasses.
        """
        pass

