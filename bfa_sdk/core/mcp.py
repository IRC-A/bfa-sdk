import inspect
import os
import jwt
from contextlib import asynccontextmanager
from typing import Dict, Any, List, Callable
from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import hashes, serialization

class BFAMCP:
    """
    Wrapper around FastMCP to automatically expose a standard metadata /tools route.
    Tracks custom tags and examples to allow semantic routing of tools in the BFA.
    Enforces offline DET cryptographic token validation for secured tools.
    """
    def __init__(self, name: str, node_id: str = None, gateway_public_key: Any = None, gateway_url: str = None, **kwargs):
        self.name = name
        self.node_id = node_id or name
        self.mcp = FastMCP(name, **kwargs)
        self.tool_metadata: Dict[str, Dict[str, Any]] = {}
        self.gateway_url = gateway_url or os.getenv("BFA_GATEWAY_URL")
        
        # Load/Generate keys
        self._private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self._public_key = self._private_key.public_key()
        
        if isinstance(gateway_public_key, str):
            self.gateway_public_key = serialization.load_pem_public_key(gateway_public_key.encode("utf-8"))
        else:
            self.gateway_public_key = gateway_public_key

        # Resolve channels
        raw_channels = os.getenv("IRCA_CHANNELS", "#public")
        self.channels = [ch.strip() for ch in raw_channels.split(",")]
        
        self.session_token = None

        # Download gateway public key if missing
        if not self.gateway_public_key and self.gateway_url:
            try:
                import httpx
                res = httpx.get(f"{self.gateway_url.rstrip('/')}/public_key", timeout=5)
                if res.status_code == 200:
                    pem_str = res.json().get("public_key")
                    self.gateway_public_key = serialization.load_pem_public_key(pem_str.encode("utf-8"))
            except Exception as e:
                print(f"BFAMCP Warning: Could not download gateway public key: {e}")

        # Register the standard BFA discovery route
        @self.mcp.custom_route("/tools", methods=["GET"])
        async def list_tools_endpoint(request: Request) -> JSONResponse:
            return await self._list_tools_handler()

        # Custom POST endpoint for direct P2P HTTP tool calls
        @self.mcp.custom_route("/tools", methods=["POST"])
        async def call_tool_endpoint(request: Request) -> JSONResponse:
            try:
                body = await request.json()
            except Exception:
                body = {}
            
            tool_name = body.get("tool")
            arguments = body.get("arguments", {})
            
            if not tool_name:
                return JSONResponse(status_code=400, content="Missing 'tool' field in request body")
                
            try:
                # Invoke the tool via FastMCP's call_tool
                result_objects = await self.mcp.call_tool(tool_name, arguments)
                # Format text content list to string
                result_text = ""
                if hasattr(result_objects, "content") and result_objects.content:
                    result_text = "\n".join([c.text for c in result_objects.content if hasattr(c, "text")])
                elif result_objects and hasattr(result_objects, "__iter__") and not isinstance(result_objects, (str, bytes)):
                    result_text = "\n".join([r.text for r in result_objects if hasattr(r, "text")])
                elif hasattr(result_objects, "text"):
                    result_text = result_objects.text
                else:
                    result_text = str(result_objects)
                    
                return JSONResponse(status_code=200, content=result_text)
            except ValueError as val_err:
                # DET validation or parameter lockdown failures return 400
                return JSONResponse(status_code=400, content=str(val_err))
            except Exception as e:
                if "DET Token validation failed" in str(e):
                    return JSONResponse(status_code=400, content=str(e))
                return JSONResponse(status_code=500, content=f"Tool execution failed: {e}")

        # Cache Starlette/ASGI app and register shutdown hook to disconnect cleanly
        self._asgi_app = self.mcp.http_app()
        async def shutdown_event():
            if self.gateway_url:
                try:
                    import httpx
                    async with httpx.AsyncClient() as client:
                        await client.post(
                            f"{self.gateway_url.rstrip('/')}/register/disconnect",
                            json={"node_id": self.node_id},
                            timeout=3
                        )
                except Exception as e:
                    print(f"BFAMCP Warning: Failed to disconnect from gateway on shutdown: {e}")

        # Register lifespan-based teardown handler dynamically
        old_lifespan = self._asgi_app.router.lifespan_context
        @asynccontextmanager
        async def wrapped_lifespan(app_inst):
            async with old_lifespan(app_inst) as yielded_val:
                yield yielded_val
                await shutdown_event()
        self._asgi_app.router.lifespan_context = wrapped_lifespan

    @property
    def app(self):
        """
        Exposes the Starlette/ASGI application for uvicorn deployment.
        """
        return self._asgi_app

    def tool(self, name: str = None, description: str = None, tags: List[str] = None, examples: List[str] = None):
        """
        Decorator to register a tool on the MCP instance.
        Stores tags and examples metadata for vector search indexing.
        Automatically injects offline DET validation if 'delegated_token' is expected in arguments.
        """
        def decorator(func: Callable):
            tool_name = name or func.__name__
            self.tool_metadata[tool_name] = {
                "tags": tags or [],
                "examples": examples or []
            }
            
            sig = inspect.signature(func)
            
            if "delegated_token" in sig.parameters:
                import functools
                if inspect.iscoroutinefunction(func):
                    @functools.wraps(func)
                    async def async_wrapper(*args, **kwargs):
                        bound = sig.bind(*args, **kwargs)
                        bound.apply_defaults()
                        token = bound.arguments.get("delegated_token")
                        
                        if not token or not self.verify_incoming_det(token, tool_name, bound.arguments):
                            raise ValueError(f"IRC-A DET Token validation failed for action '{tool_name}'")
                        return await func(*args, **kwargs)
                    wrapped_func = async_wrapper
                else:
                    @functools.wraps(func)
                    def sync_wrapper(*args, **kwargs):
                        bound = sig.bind(*args, **kwargs)
                        bound.apply_defaults()
                        token = bound.arguments.get("delegated_token")
                        
                        if not token or not self.verify_incoming_det(token, tool_name, bound.arguments):
                            raise ValueError(f"IRC-A DET Token validation failed for action '{tool_name}'")
                        return func(*args, **kwargs)
                    wrapped_func = sync_wrapper
            else:
                wrapped_func = func

            # Register with underlying FastMCP
            mcp_decorator = self.mcp.tool(name=name, description=description)
            mcp_decorator(wrapped_func)
            return wrapped_func
        return decorator

    def resource(self, uri: str):
        """
        Exposes the standard FastMCP resource decorator.
        """
        return self.mcp.resource(uri)

    def prompt(self, func: Callable):
        """
        Exposes the standard FastMCP prompt decorator.
        """
        return self.mcp.prompt(func)

    def verify_incoming_det(self, delegated_token: str, expected_action: str, runtime_args: dict) -> bool:
        """
        Offline Verification of the Delegated Execution Token (DET).
        Enforces Gateway signature check, scope limit, and parameter constraints.
        """
        if not self.gateway_public_key:
            print("BFAMCP verify_incoming_det check failed: gateway_public_key is None")
            return False
        try:
            decoded_det = jwt.decode(
                delegated_token,
                self.gateway_public_key,
                algorithms=["RS256"],
                options={"verify_aud": False}
            )
            
            # Audience validation (accepts server node_id or expected_action)
            aud = decoded_det.get("aud")
            if aud not in (self.node_id, expected_action):
                print(f"BFAMCP verify_incoming_det check failed: aud '{aud}' not in {(self.node_id, expected_action)}")
                return False
                
            # Scope validation
            permitted = decoded_det.get("permitted_action")
            if permitted != expected_action:
                print(f"BFAMCP verify_incoming_det check failed: permitted_action '{permitted}' != expected_action '{expected_action}'")
                return False
                
            # Parameter lockdown verification
            for key, value in decoded_det.get("restricted_params", {}).items():
                if runtime_args.get(key) != value:
                    print(f"BFAMCP verify_incoming_det check failed: parameter lockdown check for '{key}' failed. Expected '{value}', got '{runtime_args.get(key)}'")
                    return False
                    
            print(f"BFAMCP verify_incoming_det check PASSED for action '{expected_action}'!")
            return True
        except Exception as e:
            print(f"BFAMCP verify_incoming_det exception: {e}")
            return False

    async def _list_tools_handler(self) -> JSONResponse:
        try:
            mcp_tools = await self.mcp.list_tools()
            tools_list = []
            
            for tool in mcp_tools:
                input_schema = {}
                if hasattr(tool, "parameters") and tool.parameters:
                    input_schema = tool.parameters
                elif hasattr(tool, "input_model") and tool.input_model:
                    input_schema = tool.input_model.model_json_schema()
                
                meta = self.tool_metadata.get(tool.name, {"tags": [], "examples": []})
                
                tools_list.append({
                    "name": tool.name,
                    "description": tool.description or "",
                    "inputSchema": input_schema,
                    "annotations": {
                        "tags": meta.get("tags", []),
                        "examples": meta.get("examples", [])
                    }
                })
            return JSONResponse(tools_list)
        except Exception as e:
            return JSONResponse(
                {"error": "Failed to list tools", "details": str(e)}, 
                status_code=500
            )

    async def register_with_gateway(self, gateway_url: str, mcp_url: str) -> bool:
        """
        Dynamically register this MCP server with BFA Gateway using cryptographic challenge-response,
        falling back to simple registration if unsupported.
        """
        import httpx
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.primitives import hashes
        
        import asyncio
        # Delay slightly to allow the local FastMCP port to bind and listen
        await asyncio.sleep(1.0)
        
        self.gateway_url = gateway_url
        init_url = f"{gateway_url.rstrip('/')}/register/init"
        verify_url = f"{gateway_url.rstrip('/')}/register/verify"
        fallback_url = f"{gateway_url.rstrip('/')}/register/mcp"
        
        try:
            # 1. Initialize
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
                        print(f"BFAMCP Warning: Could not download gateway public key during registration: {e}")

                res = await client.post(init_url, json={"node_id": self.node_id, "channels": self.channels}, timeout=5)
                if res.status_code in (404, 405, 501):
                    raise NotImplementedError("Gateway does not support cryptographic challenge-response")
                if res.status_code != 200:
                    raise NotImplementedError()
                challenge = res.json()["challenge_bytes"]
                
                # 2. Sign Challenge
                signature = self._private_key.sign(
                    challenge.encode("utf-8"),
                    padding.PKCS1v15(),
                    hashes.SHA256()
                )
                
                # 3. Verify Challenge
                pem = self._public_key.public_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PublicFormat.SubjectPublicKeyInfo
                ).decode("utf-8")
                
                res_verify = await client.post(verify_url, json={
                    "node_id": self.node_id,
                    "signature": signature.hex(),
                    "public_key": pem
                }, timeout=5)
                
                if res_verify.status_code == 200:
                    data = res_verify.json()
                    self.session_token = data["session_token"]
                    
                    # Also register URL/channels
                    await client.post(
                        fallback_url,
                        params={"url": mcp_url, "channels": ",".join(self.channels)},
                        timeout=5
                    )
                    print(f"BFAMCP: Successfully registered '{self.node_id}' via cryptographic handshake.")
                    return True
                else:
                    raise NotImplementedError()
        except (NotImplementedError, KeyError, Exception):
            # Fallback simple registration
            try:
                async with httpx.AsyncClient() as client:
                    res_simple = await client.post(
                        fallback_url,
                        params={"url": mcp_url, "channels": ",".join(self.channels)},
                        timeout=5
                    )
                    if res_simple.status_code == 200:
                        print(f"BFAMCP: Successfully registered '{self.node_id}' via simple registration fallback.")
                        return True
                    else:
                        print(f"BFAMCP Error: Registration fallback failed with status {res_simple.status_code}: {res_simple.text}")
                        return False
            except Exception as ex:
                print(f"BFAMCP Error: Failed to connect to Gateway fallback at {fallback_url}: {ex}")
                return False

