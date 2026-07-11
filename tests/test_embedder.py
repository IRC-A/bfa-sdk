import sys
import builtins
from unittest.mock import MagicMock, patch

# Inject mock sentence_transformers to support offline tests on environments without it (e.g. Python 3.13)
sys.modules['sentence_transformers'] = MagicMock()

import pytest
import numpy as np
from bfa_sdk.router.embedder import DummyEmbedder, OpenAIEmbedder, LocalEmbedder

def test_dummy_embedder():
    embedder = DummyEmbedder()
    # Test embed_documents
    vecs = embedder.embed_documents(["hola", "mundo"])
    assert len(vecs) == 2
    assert len(vecs[0]) == 384
    
    # Test embed_query (single text)
    vec = embedder.embed_query("hola")
    assert len(vec) == 384
    norm = np.linalg.norm(vec)
    assert pytest.approx(norm, abs=1e-5) == 1.0

    # Test empty query fallback coverage
    vec_empty = embedder.embed_query("")
    assert len(vec_empty) == 384
    assert vec_empty[0] == 1.0

@patch("openai.OpenAI")
def test_openai_embedder(mock_openai):
    # Set up mock client response
    mock_client = MagicMock()
    mock_openai.return_value = mock_client
    
    mock_response = MagicMock()
    mock_response.data = [
        MagicMock(embedding=[0.1, 0.2, 0.3])
    ]
    mock_client.embeddings.create.return_value = mock_response
    
    embedder = OpenAIEmbedder(api_key="mock-key")
    
    # Test embed_documents
    vecs = embedder.embed_documents(["test query"])
    assert len(vecs) == 1
    assert vecs[0] == [0.1, 0.2, 0.3]
    
    # Test embed_query
    vec = embedder.embed_query("test query 2")
    assert vec == [0.1, 0.2, 0.3]
    
    assert mock_client.embeddings.create.call_count == 2

@patch("sentence_transformers.SentenceTransformer")
def test_local_embedder(mock_transformer):
    mock_model = MagicMock()
    mock_transformer.return_value = mock_model
    mock_model.encode.return_value = np.array([[0.5, 0.6]])
    
    embedder = LocalEmbedder(model_name="mock-model")
    
    # Test embed_documents
    vecs = embedder.embed_documents(["hello"])
    assert len(vecs) == 1
    assert vecs[0] == [0.5, 0.6]
    
    # Test embed_query
    mock_model.encode.return_value = np.array([0.7, 0.8])
    vec = embedder.embed_query("hello 2")
    assert vec == [0.7, 0.8]

def test_openai_embedder_import_error():
    # Force import of openai to raise ImportError
    real_import = builtins.__import__
    def mock_import(name, *args, **kwargs):
        if name == "openai":
            raise ImportError("openai missing")
        return real_import(name, *args, **kwargs)
        
    with patch("builtins.__import__", side_effect=mock_import):
        with pytest.raises(ImportError) as exc:
            OpenAIEmbedder()
        assert "openai package not found" in str(exc.value)

def test_local_embedder_import_error():
    # Force import of sentence_transformers to raise ImportError
    real_import = builtins.__import__
    def mock_import(name, *args, **kwargs):
        if name == "sentence_transformers":
            raise ImportError("sentence_transformers missing")
        return real_import(name, *args, **kwargs)
        
    with patch("builtins.__import__", side_effect=mock_import):
        with pytest.raises(ImportError) as exc:
            LocalEmbedder()
        assert "sentence-transformers package not found" in str(exc.value)
