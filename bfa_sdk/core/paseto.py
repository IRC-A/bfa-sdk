# Copyright (c) 2026 Sandro G. All rights reserved.
# Licensed under AGPLv3 / Commercial Dual License.

import base64
import json
import struct
from typing import Dict, Any, Optional
from cryptography.hazmat.primitives.asymmetric import ed25519

def le64(n: int) -> bytes:
    """Encode an 8-byte little-endian unsigned integer."""
    return struct.pack("<Q", n)

def pae(pieces: list[bytes]) -> bytes:
    """Pre-Authentication Encoding (PAE) standard helper."""
    output = le64(len(pieces))
    for piece in pieces:
        output += le64(len(piece)) + piece
    return output

def base64url_encode(data: bytes) -> str:
    """Base64url encode without padding."""
    return base64.urlsafe_b64encode(data).decode('utf-8').rstrip('=')

def base64url_decode(data: str) -> bytes:
    """Base64url decode with padding recovery."""
    rem = len(data) % 4
    if rem > 0:
        data += '=' * (4 - rem)
    return base64.urlsafe_b64decode(data.encode('utf-8'))

def sign_paseto_v4_public(
    payload: Dict[str, Any], 
    private_key: ed25519.Ed25519PrivateKey, 
    footer: Optional[Dict[str, Any]] = None
) -> str:
    """
    Sign a payload using PASETO v4.public token format with Ed25519.
    """
    header = b"v4.public."
    payload_json = json.dumps(payload, separators=(',', ':')).encode('utf-8')
    footer_json = b""
    if footer:
        footer_json = json.dumps(footer, separators=(',', ':')).encode('utf-8')
        
    # PAE construction: PAE(h, m, f, i) where implicit assertion i is empty
    m_to_sign = pae([header, payload_json, footer_json, b""])
    
    # Compute Ed25519 signature
    signature = private_key.sign(m_to_sign)
    
    encoded_payload = base64url_encode(payload_json)
    encoded_signature = base64url_encode(signature)
    
    if footer:
        encoded_footer = base64url_encode(footer_json)
        return f"v4.public.{encoded_payload}.{encoded_signature}.{encoded_footer}"
    
    return f"v4.public.{encoded_payload}.{encoded_signature}"

def verify_paseto_v4_public(
    token: str, 
    public_key: ed25519.Ed25519PublicKey
) -> Dict[str, Any]:
    """
    Verify a PASETO v4.public token using the issuer's Ed25519 public key.
    """
    parts = token.split('.')
    if len(parts) < 4 or parts[0] != "v4" or parts[1] != "public":
        raise ValueError("Invalid PASETO header or format")
        
    encoded_payload = parts[2]
    encoded_signature = parts[3]
    encoded_footer = parts[4] if len(parts) > 4 else ""
    
    payload_json = base64url_decode(encoded_payload)
    signature = base64url_decode(encoded_signature)
    footer_json = base64url_decode(encoded_footer) if encoded_footer else b""
    
    header = b"v4.public."
    m_to_verify = pae([header, payload_json, footer_json, b""])
    
    # Verify Ed25519 signature
    public_key.verify(signature, m_to_verify)
    
    return json.loads(payload_json.decode('utf-8'))
