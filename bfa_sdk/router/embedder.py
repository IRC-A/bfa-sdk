import abc
import os
from typing import List

class AbstractEmbedder(abc.ABC):
    """
    Interface for text embedding generation.
    """
    @abc.abstractmethod
    def embed_query(self, text: str) -> List[float]:
        pass

    @abc.abstractmethod
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        pass


class OpenAIEmbedder(AbstractEmbedder):
    """
    Cloud-based embedding generator using OpenAI's API.
    Fast, lightweight, and perfect for AWS Lambda environments.
    """
    def __init__(self, model_name: str = "text-embedding-3-small", api_key: str = None):
        try:
            from openai import OpenAI
            self.client = OpenAI(api_key=api_key or os.getenv("OPENAI_API_KEY"))
            self.model_name = model_name
        except ImportError:
            raise ImportError(
                "openai package not found. "
                "Please run: pip install openai"
            )

    def embed_query(self, text: str) -> List[float]:
        response = self.client.embeddings.create(
            input=[text],
            model=self.model_name
        )
        return response.data[0].embedding

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        response = self.client.embeddings.create(
            input=texts,
            model=self.model_name
        )
        return [item.embedding for item in response.data]


class LocalEmbedder(AbstractEmbedder):
    """
    Local embedding generator using sentence-transformers.
    Defaults to 'paraphrase-multilingual-MiniLM-L12-v2' which is highly effective
    for Spanish, Portuguese, and English.
    Requires 'pip install sentence-transformers' and is only supported on Python <= 3.12 (not yet on 3.13 due to torch).
    """
    def __init__(self, model_name: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"):
        try:
            from sentence_transformers import SentenceTransformer
            self.model = SentenceTransformer(model_name)
        except ImportError:
            raise ImportError(
                "sentence-transformers package not found. "
                "Please run: pip install 'bfa-sdk[local]'"
            )

    def embed_query(self, text: str) -> List[float]:
        embedding = self.model.encode(text)
        return embedding.tolist()

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        embeddings = self.model.encode(texts)
        return embeddings.tolist()


class DummyEmbedder(AbstractEmbedder):
    """
    Mock embedder for unit tests and local runs without model/API overhead.
    Generates deterministic, unit-normalized vectors based on input hashes.
    """
    def __init__(self, dimension: int = 384):
        self.dimension = dimension

    def embed_query(self, text: str) -> List[float]:
        import re
        import hashlib
        import math
        
        # Tokenize and lowercase words
        words = re.findall(r'\w+', text.lower())
        
        vec = [0.0] * self.dimension
        if not words:
            # Fallback for empty strings
            vec[0] = 1.0
            return vec
            
        for word in words:
            # Use md5 for stable hash mapping across processes
            h = hashlib.md5(word.encode("utf-8")).hexdigest()
            idx = int(h, 16) % self.dimension
            vec[idx] += 1.0
            
        # Normalize to unit length (L2 norm = 1.0)
        norm = math.sqrt(sum(x*x for x in vec))
        if norm > 0:
            vec = [x / norm for x in vec]
        return vec

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return [self.embed_query(t) for t in texts]
