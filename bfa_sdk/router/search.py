import numpy as np
from typing import List, Dict, Any, Optional
from bfa_sdk.router.embedder import AbstractEmbedder

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
        """
        import faiss
        
        self.index_keys = []
        corpus_texts = []

        for skill_id, item in self.registry.items():
            # Build semantic search text
            tags_str = " ".join(item.get("tags", []))
            examples_str = " ".join(item.get("examples", []))
            search_text = item.get("search_text") or " ".join([
                item.get("name", ""),
                item.get("description", ""),
                tags_str,
                examples_str
            ])
            
            corpus_texts.append(search_text)
            self.index_keys.append(skill_id)

        if not corpus_texts:
            self.index = None
            return

        # Generate embeddings
        embeddings = self.embedder.embed_documents(corpus_texts)
        embeddings_np = np.array(embeddings).astype("float32")
        
        dimension = embeddings_np.shape[1]
        
        # L2 Distance Indexing
        self.index = faiss.IndexFlatL2(dimension)
        self.index.add(embeddings_np)

    def resolve(
        self, 
        query: str, 
        top_k: int = 3, 
        threshold: float = 0.3, 
        filter_type: Optional[str] = None,
        agent_channels: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Resolves the query to the best matching agent or tool from FAISS index.
        Normalizes L2 distance to a 0.0 - 1.0 confidence score.
        """
        if self.index is None or not self.index_keys:
            return {"type": "no_match", "best": None, "candidates": []}

        # Embed query
        query_vector = self.embedder.embed_query(query)
        query_vector_np = np.array([query_vector]).astype("float32")

        # Search index
        # Limit search to actual registered item count if smaller than top_k
        actual_k = min(top_k, len(self.index_keys))
        distances, indices = self.index.search(query_vector_np, len(self.index_keys))

        candidates = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx == -1:
                continue
                
            skill_id = self.index_keys[idx]
            item = self.registry[skill_id]

            # Filter by type if requested
            if filter_type and item.get("type") != filter_type:
                continue

            # Filter by channel overlap (Logical Channel Masking)
            if agent_channels is not None:
                item_channels = item.get("channels", ["#public"])
                if not any(ch in item_channels for ch in agent_channels):
                    continue

            # Convert L2 distance squared to Cosine Similarity in [0.0, 1.0] range
            # Assuming unit-normalized vectors: CosSim = 1.0 - (L2_dist_squared / 4.0)
            similarity = float(1.0 - (dist / 4.0))
            similarity = max(0.0, min(1.0, similarity))

            candidates.append({
                "skill": skill_id,
                "distance": float(dist),
                "confidence": similarity,
                "type": item.get("type", "agent"),
                "data": item
            })

        # Filter and sort candidate results
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
