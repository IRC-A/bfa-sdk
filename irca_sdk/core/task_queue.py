# Copyright (c) 2026 Sandro G. All rights reserved.
# Licensed under AGPLv3 / Commercial Dual License.
import re
import json
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger("irca.task_queue")


class SubTask:
    """
    Represents an atomic task/intent to be resolved independently against the BFA network.
    """
    def __init__(
        self,
        intent: str,
        params: Optional[Dict[str, Any]] = None,
        task_id: Optional[str] = None
    ):
        self.intent = intent.strip()
        self.params = dict(params or {})
        self.task_id = task_id or f"task-{hash(self.intent) & 0xfffffff}"
        self.matched_capability: Optional[Dict[str, Any]] = None
        self.det: Optional[str] = None
        self.endpoint: Optional[str] = None
        self.result: Any = None
        self.status: str = "pending"  # pending, discovered, authorized, completed, failed, no_match
        self.error: Optional[str] = None

    def bind_params_to_schema(self, input_schema: Dict[str, Any]) -> Dict[str, Any]:
        """
        Maps extracted generic parameters to the exact property names declared in the tool's input_schema.
        Supports snake_case, camelCase, and common parameter synonyms.
        """
        if not input_schema or not isinstance(input_schema, dict):
            return dict(self.params)

        props = input_schema.get("properties", {})
        if not props and input_schema.get("type") == "object":
            props = input_schema.get("properties", {})

        if not props:
            return dict(self.params)

        bound = {}
        # Normalize available extracted parameter keys (lowercase without underscores or hyphens)
        normalized_extracted = {}
        for k, v in self.params.items():
            norm_k = re.sub(r"[_\-\s]", "", str(k)).lower()
            normalized_extracted[norm_k] = v

        for prop_name, prop_def in props.items():
            norm_prop = re.sub(r"[_\-\s]", "", str(prop_name)).lower()
            # 1. Exact match
            if prop_name in self.params:
                bound[prop_name] = self.params[prop_name]
            # 2. Normalized match (e.g. check_in -> checkIn)
            elif norm_prop in normalized_extracted:
                bound[prop_name] = normalized_extracted[norm_prop]
            # 3. Common semantic synonyms
            elif norm_prop in ("checkin", "checkindate", "startdate", "fromdate") and "checkin" in normalized_extracted:
                bound[prop_name] = normalized_extracted["checkin"]
            elif norm_prop in ("checkout", "checkoutdate", "enddate", "todate") and "checkout" in normalized_extracted:
                bound[prop_name] = normalized_extracted["checkout"]
            elif norm_prop in ("guests", "pax", "numguests", "personas", "huespedes") and "guests" in normalized_extracted:
                bound[prop_name] = normalized_extracted["guests"]
            elif norm_prop in ("propertyid", "hotelid", "pmshotelid", "hotel") and "propertyid" in normalized_extracted:
                bound[prop_name] = normalized_extracted["propertyid"]
            elif norm_prop in ("accountid", "accid", "cuenta", "account") and "accountid" in normalized_extracted:
                bound[prop_name] = normalized_extracted["accountid"]

        # Also preserve any original parameters not explicitly in schema if none bound
        if not bound:
            return dict(self.params)

        return bound

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "intent": self.intent,
            "params": self.params,
            "status": self.status,
            "target": (self.matched_capability.get("tool") or self.matched_capability.get("node_id")) if self.matched_capability else None,
            "result": self.result,
            "error": self.error
        }


def extract_parameters_from_text(text: str) -> Dict[str, Any]:
    """
    Extracts structured domain parameters (dates, guests, property IDs, account IDs)
    from unstructured natural language queries.
    """
    params = {}

    # 1. Check-in and Check-out dates
    checkin_match = re.search(r"\b(?:check-?in|llegada|desde|from)\s*(?:date\s*)?[:=]?\s*(\d{4}-\d{2}-\d{2})", text, re.IGNORECASE)
    if checkin_match:
        params["check_in"] = checkin_match.group(1)

    checkout_match = re.search(r"\b(?:check-?out|salida|hasta|to)\s*(?:date\s*)?[:=]?\s*(\d{4}-\d{2}-\d{2})", text, re.IGNORECASE)
    if checkout_match:
        params["check_out"] = checkout_match.group(1)

    range_match = re.search(r"\b(?:del|de|from)\s*(\d{4}-\d{2}-\d{2})\s*(?:al|a|hasta|to)\s*(\d{4}-\d{2}-\d{2})", text, re.IGNORECASE)
    if range_match:
        if "check_in" not in params:
            params["check_in"] = range_match.group(1)
        if "check_out" not in params:
            params["check_out"] = range_match.group(2)

    # 2. Number of guests / personas
    guests_match = re.search(r"\b(\d+)\s*(?:guests?|personas?|hu[eé]spedes?|pax|adultos?|adults?)", text, re.IGNORECASE)
    if guests_match:
        params["guests"] = int(guests_match.group(1))
    else:
        for_guests = re.search(r"\bfor\s*(\d+)\s*(?:guests?|persons?|people)?", text, re.IGNORECASE)
        if for_guests and int(for_guests.group(1)) < 50:
            params["guests"] = int(for_guests.group(1))

    # 3. Property ID / Hotel ID / Tenant ID
    prop_match = re.search(
        r"\b(?:(?:hotel\s+)?property[_-]?id|hotel[_-]?id|tenant[_-]?id|hotel|property)\s*[:=]?\s*([0-9a-zA-Z_-]+)",
        text,
        re.IGNORECASE
    )
    if prop_match:
        val = prop_match.group(1).strip()
        if val.lower() in ("propertyid", "property_id", "id"):
            sub_m = re.search(r"\bproperty[_-]?id\s*[:=]?\s*([0-9a-zA-Z_-]+)", text, re.IGNORECASE)
            if sub_m:
                val = sub_m.group(1).strip()
        params["property_id"] = val

    # 4. Account ID / Customer ID
    acc_match = re.search(r"\b(?:account[_-]?id|customer[_-]?id|cuenta|cuenta[_-]?id)\s*[:=]?\s*(\w+)", text, re.IGNORECASE)
    if acc_match:
        params["account_id"] = acc_match.group(1)

    # 5. Room ID
    room_match = re.search(r"\b(?:room[_-]?id|habitaci[oó]n|cuarto)\s*[:=]?\s*(\w+)", text, re.IGNORECASE)
    if room_match:
        params["room_id"] = room_match.group(1)

    return params


def clean_intent_text(text: str) -> str:
    """
    Removes parameter clauses (dates, numbers, ids) from a query
    to produce a clean, pure semantic intent for Phase 1 Discovery.
    """
    cleaned = text

    # Remove date clauses
    cleaned = re.sub(r"\b(?:for\s+)?check-?in\s*(?:date\s*)?[:=]?\s*\d{4}-\d{2}-\d{2}", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(?:for\s+)?check-?out\s*(?:date\s*)?[:=]?\s*\d{4}-\d{2}-\d{2}", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(?:del|de|from)\s*\d{4}-\d{2}-\d{2}\s*(?:al|a|hasta|to)\s*\d{4}-\d{2}-\d{2}", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", "", cleaned)

    # Remove guests/pax clauses
    cleaned = re.sub(r"\b(?:for\s+)?\d+\s*(?:guests?|personas?|hu[eé]spedes?|pax|adultos?|adults?)\b", "", cleaned, flags=re.IGNORECASE)

    # Remove property/hotel/account ID clauses
    cleaned = re.sub(r"\b(?:for\s+)?(?:hotel\s+)?(?:property[_-]?id|hotel[_-]?id|tenant[_-]?id)\s*[:=]?\s*\w+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(?:account[_-]?id|customer[_-]?id|cuenta)\s*[:=]?\s*\w+", "", cleaned, flags=re.IGNORECASE)

    # Normalize whitespace and dangling prepositions/connectors
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = re.sub(r"\b(for|para|en|in|de|of)\s*$", "", cleaned, flags=re.IGNORECASE).strip()
    return cleaned


def decompose_prompt_to_tasks(prompt: str, common_params: Optional[Dict[str, Any]] = None) -> List[SubTask]:
    """
    Decomposes a composite prompt into a sequential list of atomic SubTasks.
    Extracts domain parameters once, strips them from the intent string,
    and splits composite conjunctions ('and', 'y', ';').
    """
    extracted_params = extract_parameters_from_text(prompt)
    if common_params:
        extracted_params.update(common_params)

    clean_intent = clean_intent_text(prompt)
    if not clean_intent:
        clean_intent = prompt.strip()

    # Split composite intents on action conjunctions
    # e.g. "check room availability and rates" -> ["check room availability", "check room rates"]
    # "consultar disponibilidad y ver tarifas" -> ["consultar disponibilidad", "ver tarifas"]
    split_patterns = [
        r"\s+and\s+(?:check\s+|ver\s+|obtener\s+|get\s+)?",
        r"\s+y\s+(?:ver\s+|consultar\s+|obtener\s+|check\s+)?",
        r"\s+además\s+de\s+",
        r"\s*;\s*"
    ]

    segments = [clean_intent]
    for pattern in split_patterns:
        new_segments = []
        for seg in segments:
            parts = [p.strip() for p in re.split(pattern, seg, flags=re.IGNORECASE) if p.strip()]
            new_segments.extend(parts)
        segments = new_segments

    # Refine segments: if a segment is just "rates", enrich it with the subject "check room rates"
    refined_segments = []
    base_subject = ""
    for seg in segments:
        seg_lower = seg.lower()
        if "room" in seg_lower or "habitaci" in seg_lower:
            base_subject = "room" if "room" in seg_lower else "habitacion"
        
        # If segment is short noun phrase like "rates" or "tarifas"
        if seg_lower in ("rates", "rate", "tarifas", "precios", "preço"):
            prefix = "check room rates" if "room" in clean_intent.lower() else "consultar tarifas"
            refined_segments.append(prefix)
        else:
            refined_segments.append(seg)

    tasks = []
    for i, seg in enumerate(refined_segments):
        tasks.append(SubTask(
            intent=seg,
            params=dict(extracted_params),
            task_id=f"subtask-{i+1}"
        ))

    return tasks


class TaskQueue:
    """
    Sequential Orchestration Queue for multi-step / composite requests.
    Enforces Phase 1 (Pure Discover without parameters) -> Phase 2 (Authorize with locked parameters) -> Phase 3 (P2P Execution).
    Aggregates individual sub-task outputs into a coherent final response.
    """
    def __init__(self, agent: Any, tasks: Optional[List[SubTask]] = None):
        self.agent = agent
        self.tasks: List[SubTask] = list(tasks or [])

    def add_task(self, intent: str, params: Optional[Dict[str, Any]] = None) -> SubTask:
        task = SubTask(intent=intent, params=params, task_id=f"subtask-{len(self.tasks)+1}")
        self.tasks.append(task)
        return task

    @classmethod
    def from_prompt(cls, agent: Any, prompt: str, common_params: Optional[Dict[str, Any]] = None) -> "TaskQueue":
        tasks = decompose_prompt_to_tasks(prompt, common_params=common_params)
        return cls(agent=agent, tasks=tasks)

    async def execute(self) -> Dict[str, Any]:
        """
        Executes each SubTask in the queue sequentially:
        1. Discover: Asks Gateway with clean intent (NO parameters) to verify capability and schema.
        2. Authorize: Submits bound parameters to Gateway to mint ephemeral DET.
        3. Execute: Performs direct P2P call with DET token.
        """
        results = []
        overall_success = True

        for task in self.tasks:
            try:
                # 1. Discover capability (Pure Intent without parameters)
                match = await self.agent.discover_capability(task.intent)
                if not match:
                    task.status = "no_match"
                    task.error = f"No authorized capability available in your channels for intent: '{task.intent}'"
                    overall_success = False
                    continue

                task.matched_capability = match
                tool_name = match.get("tool") or match.get("node_id")
                target_endpoint = match.get("endpoint") or match.get("url")
                target_type = match.get("type", "agent")
                input_schema = match.get("input_schema", {})

                # 2. Bind parameters to schema
                bound_params = task.bind_params_to_schema(input_schema)

                # 3. Authorize with locked parameters
                auth_info = await self.agent.authorize_execution(
                    intent=task.intent,
                    tool=tool_name,
                    args=bound_params
                )
                det = auth_info.get("det")
                endpoint = auth_info.get("endpoint") or target_endpoint
                is_tool = (auth_info.get("type") == "tool") or (target_type == "tool")
                task.det = det
                task.endpoint = endpoint

                # 4. P2P Direct Execution
                res = await self.agent.call_peer_p2p(
                    endpoint=endpoint,
                    tool_or_action=tool_name,
                    args=bound_params,
                    det=det,
                    is_tool=is_tool,
                    intent=task.intent
                )
                task.result = res
                task.status = "completed"

            except Exception as ex:
                task.status = "failed"
                task.error = str(ex)
                overall_success = False

        # Assemble unified response
        task_dicts = [t.to_dict() for t in self.tasks]
        completed_results = [t.result for t in self.tasks if t.status == "completed" and t.result is not None]

        # Compose human-readable synthesis
        summary_parts = []
        for t in self.tasks:
            target_desc = f"[{t.matched_capability.get('tool')}]" if t.matched_capability else ""
            if t.status == "completed":
                summary_parts.append(f"{t.intent} {target_desc}: {t.result}")
            elif t.status == "no_match":
                summary_parts.append(f"{t.intent}: No helper found in channels.")
            else:
                summary_parts.append(f"{t.intent}: Failed ({t.error})")

        return {
            "status": "success" if overall_success else ("partial" if completed_results else "failed"),
            "total_tasks": len(self.tasks),
            "completed_tasks": len([t for t in self.tasks if t.status == "completed"]),
            "tasks": task_dicts,
            "results": {t.intent: t.result for t in self.tasks if t.status == "completed"},
            "combined_summary": "\n".join(summary_parts) if len(self.tasks) > 1 else (completed_results[0] if completed_results else None)
        }
