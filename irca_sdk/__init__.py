# Copyright (c) 2026 Sandro G. All rights reserved.
# Licensed under AGPLv3 / Commercial Dual License.
# Backend for Agents SDK (BFA)
# Version 0.3.0
"""
BFA SDK: A lightweight framework for Backend for Agents (BFA) architecture with FAISS semantic routing.
"""
import logging

class _SilentProbeFilter(logging.Filter):
    SILENT_PATHS = {"/tools", "/ping", "/health", "/.well-known/agent-card.json"}
    def filter(self, record: logging.LogRecord) -> bool:
        args = getattr(record, "args", None)
        if isinstance(args, tuple) and len(args) >= 3:
            _, method, full_path, *_ = args
            path = str(full_path).split("?", 1)[0]
            if path in self.SILENT_PATHS and method == "GET":
                return False
        msg = record.getMessage()
        if any(f" {p} " in msg or f'"{p}' in msg or f"'{p}'" in msg for p in self.SILENT_PATHS) and "POST" not in msg:
            return False
        return True

logging.getLogger("uvicorn.access").addFilter(_SilentProbeFilter())
logging.getLogger("httpx").setLevel(logging.WARNING)

try:
    import uvicorn.config
    if "filters" not in uvicorn.config.LOGGING_CONFIG:
        uvicorn.config.LOGGING_CONFIG["filters"] = {}
    uvicorn.config.LOGGING_CONFIG["filters"]["irca_probe_filter"] = {
        "()": lambda: _SilentProbeFilter()
    }
    if "access" in uvicorn.config.LOGGING_CONFIG.get("handlers", {}):
        access_filters = uvicorn.config.LOGGING_CONFIG["handlers"]["access"].setdefault("filters", [])
        if "irca_probe_filter" not in access_filters:
            access_filters.append("irca_probe_filter")
except Exception:
    pass

from irca_sdk.core.agent import IRCAAgent, BFAAgent
from irca_sdk.core.interactive_agent import IRCAInteractiveAgent, BFAInteractiveAgent
from irca_sdk.core.mcp import IRCAMCP, BFAMCP
from irca_sdk.core.gateway import create_gateway_app
from irca_sdk.router.search import BFASemanticRouter
from irca_sdk.core.task_queue import TaskQueue, SubTask, decompose_prompt_to_tasks, extract_parameters_from_text

__all__ = [
    "IRCAAgent", 
    "IRCAMCP", 
    "IRCAInteractiveAgent", 
    "BFAAgent", 
    "BFAMCP", 
    "BFAInteractiveAgent", 
    "create_gateway_app", 
    "BFASemanticRouter",
    "TaskQueue",
    "SubTask",
    "decompose_prompt_to_tasks",
    "extract_parameters_from_text"
]
