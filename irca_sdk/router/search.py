# Copyright (c) 2026 Sandro G. All rights reserved.
# Licensed under AGPLv3 / Commercial Dual License.
import numpy as np
from typing import List, Dict, Any, Optional
from irca_sdk.router.embedder import AbstractEmbedder

class BFASemanticRouter:
    """
    Handles FAISS-based indexing and semantic search for BFA Agents and Tools.
    Replaces keyword-based search with vector similarity matching.
    """
    def __init__(self, embedder: AbstractEmbedder):
        self.embedder = embedder
        self.registry: Dict[str, Dict[str, Any]] = {}
        self.index = None
        self.index_keys: List[str] = []

    def update_registry(self, items: Dict[str, Dict[str, Any]]):
        """
        Add or update discovered items in the local registry.
        """
        self.registry.update(items)

    def build_index(self):
        """
        Rebuilds the FAISS vector index based on registered agent and tool metadata.
        Bypasses embedding generator for nodes supplying pre-computed embeddings.
        """
        import faiss
        
        new_index_keys = []
        texts_to_embed = []
        keys_to_embed = []
        precomputed_embeddings = {}

        for skill_id, item in self.registry.items():
            if "precomputed_embedding" in item and item["precomputed_embedding"] is not None:
                precomputed_embeddings[skill_id] = item["precomputed_embedding"]
                new_index_keys.append(skill_id)
            else:
                tags_str = " ".join(item.get("tags", []))
                examples_str = " ".join(item.get("examples", []))
                search_text = item.get("search_text") or " ".join([
                    item.get("name", ""),
                    item.get("description", ""),
                    tags_str,
                    examples_str
                ])
                texts_to_embed.append(search_text)
                keys_to_embed.append(skill_id)

        # Generate missing embeddings
        generated_embeddings = []
        if texts_to_embed:
            generated_embeddings = self.embedder.embed_documents(texts_to_embed)

        all_embeddings = []
        # First add the ones that were generated
        for key, emb in zip(keys_to_embed, generated_embeddings):
            all_embeddings.append(emb)
            new_index_keys.append(key)
        # Next add the pre-computed ones
        for key in precomputed_embeddings:
            all_embeddings.append(precomputed_embeddings[key])

        if not all_embeddings:
            self.index = None
            self.index_keys = []
            return

        embeddings_np = np.array(all_embeddings).astype("float32")
        dimension = embeddings_np.shape[1]
        
        # L2 Distance Indexing
        new_index = faiss.IndexFlatL2(dimension)
        new_index.add(embeddings_np)
        
        # Atomic assignment to prevent race conditions during concurrent requests
        self.index = new_index
        self.index_keys = new_index_keys

    def resolve(
        self, 
        query: str, 
        top_k: int = 3, 
        threshold: float = 0.3, 
        filter_type: Optional[str] = None,
        prefer: Optional[str] = "agent",
        agent_channels: Optional[List[str]] = None,
        exclude_node_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Resolves the query to the best matching agent or tool from FAISS index.
        Normalizes L2 distance to a 0.0 - 1.0 confidence score.
        Supports prefer="agent" (default) to prioritize cognitive agents over tools when above threshold.
        Supports exclude_node_id to bypass self-referential matches.
        """
        if self.index is None or not self.index_keys:
            return {"type": "no_match", "best": None, "candidates": []}

        # Embed query
        query_vector = self.embedder.embed_query(query)
        query_vector_np = np.array([query_vector]).astype("float32")

        # Search index - fetch broader candidate pool so type preferences and exclusions have ample candidates
        search_k = min(max(top_k * 4, 25), len(self.index_keys))
        if search_k <= 0:
            return {"type": "no_match", "best": None, "candidates": []}
        distances, indices = self.index.search(query_vector_np, search_k)

        candidates = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx == -1:
                continue
                
            skill_id = self.index_keys[idx]
            item = self.registry[skill_id]

            # Filter out self-referential calling node if exclude_node_id is provided
            if exclude_node_id:
                target_node_id = str(item.get("node_id") or "").strip().lower()
                target_url = str(item.get("url") or item.get("server_url") or "").strip().lower()
                ex_clean = str(exclude_node_id).strip().lower()
                if (ex_clean == str(skill_id).strip().lower() or
                    ex_clean == target_node_id or
                    (ex_clean and ex_clean in target_url)):
                    continue

            # Filter by type if requested
            if filter_type and item.get("type") != filter_type:
                continue

            # Filter by channel overlap (Logical Channel Masking)
            if agent_channels is not None:
                item_channels = item.get("channels") or ["#public"]
                norm_agent_channels = {str(c).strip().lstrip("#").lower() for c in agent_channels if c}
                norm_item_channels = {str(c).strip().lstrip("#").lower() for c in item_channels if c}
                
                # Logical Channel Masking:
                # A target item is accessible if it is public (#public or empty channels),
                # OR if the caller shares at least one channel with the target item.
                # A caller having #public does NOT grant access to private channels.
                item_is_public = not norm_item_channels or "public" in norm_item_channels
                has_channel_overlap = bool(norm_agent_channels.intersection(norm_item_channels))
                if not item_is_public and not has_channel_overlap:
                    continue

            # Convert L2 distance squared to Cosine Similarity in [0.0, 1.0] range
            similarity = float(1.0 - (dist / 4.0))
            similarity = max(0.0, min(1.0, similarity))

            candidates.append({
                "skill": skill_id,
                "distance": float(dist),
                "confidence": similarity,
                "type": item.get("type", "agent"),
                "data": item
            })

        # Sort candidates according to cognitive preference (Cognitive-First)
        norm_prefer = str(prefer).strip().lower() if prefer else None

        if norm_prefer == "agent":
            # Cognitive-First priority:
            # 0. Meets threshold & is Agent (Highest priority)
            # 1. Meets threshold & is Tool (MCP fallback)
            # 2. Below threshold & is Agent
            # 3. Below threshold & is Tool
            def sort_key(c):
                meets = c["confidence"] >= threshold
                is_agent = c.get("type") == "agent"
                if meets and is_agent:
                    priority = 0
                elif meets:
                    priority = 1
                elif is_agent:
                    priority = 2
                else:
                    priority = 3
                return (priority, -c["confidence"])
            candidates = sorted(candidates, key=sort_key)
        elif norm_prefer == "tool":
            def sort_key(c):
                meets = c["confidence"] >= threshold
                is_tool = c.get("type") == "tool"
                if meets and is_tool:
                    priority = 0
                elif meets:
                    priority = 1
                elif is_tool:
                    priority = 2
                else:
                    priority = 3
                return (priority, -c["confidence"])
            candidates = sorted(candidates, key=sort_key)
        else:
            candidates = sorted(candidates, key=lambda x: x["confidence"], reverse=True)

        filtered_candidates = candidates[:top_k]

        if not filtered_candidates:
            return {"type": "no_match", "best": None, "candidates": []}

        best = filtered_candidates[0]

        # Check threshold
        if best["confidence"] < threshold:
            return {
                "type": "no_confident_match", 
                "best": None, 
                "candidates": filtered_candidates
            }

        return {
            "type": "semantic_faiss", 
            "best": best, 
            "candidates": filtered_candidates
        }
