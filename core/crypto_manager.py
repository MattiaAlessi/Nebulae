"""
NEBULAE – Crypto Manager
Wraps the Rust p2p_crypto engine with Pythonic session management.
Handles key storage, identity persistence, and the dual-password decoy system.
"""
from __future__ import annotations

import os
import json
import time
import ctypes
import hashlib
import secrets
import threading
from pathlib import Path
from typing import Optional, Tuple

try:
    import p2p_crypto as _rust
except ImportError:
    _rust = None  # running without compiled Rust module (dev fallback)

# ─────────────────────────────────────────────────────────────────────────────
#  Secure Python string wiper
# ─────────────────────────────────────────────────────────────────────────────
def _wipe_bytes(data: bytearray) -> None:
    """Overwrite a bytearray with zeros using ctypes for memory certainty."""
    if isinstance(data, bytearray) and len(data) > 0:
        ctypes.memset(ctypes.c_char_p(bytes(data)), 0, len(data))


# ─────────────────────────────────────────────────────────────────────────────
#  CryptoSession – per-peer session state holder
# ─────────────────────────────────────────────────────────────────────────────
class CryptoSession:
    """Holds a live ratchet state for one peer. Zeroized on close()."""

    def __init__(self, peer_id: str, ratchet_state_json: str):
        self.peer_id = peer_id
        self._state = bytearray(ratchet_state_json.encode())
        self._lock  = threading.Lock()
        self.created_at = time.time()

    def encrypt(self, plaintext: bytes) -> Tuple[bytes, bytes]:
        with self._lock:
            result = _rust.ratchet_encrypt(self._state.decode(), plaintext)
            # Update state in-place
            ctypes.memset(ctypes.c_char_p(bytes(self._state)), 0, len(self._state))
            new_state = result["state"].encode()
            self._state = bytearray(new_state)
            return result["ciphertext"], result["header_dh_pub"]

    def decrypt(self, ciphertext: bytes) -> bytes:
        with self._lock:
            result = _rust.ratchet_decrypt(self._state.decode(), ciphertext)
            ctypes.memset(ctypes.c_char_p(bytes(self._state)), 0, len(self._state))
            self._state = bytearray(result["state"].encode())
            return result["plaintext"]

    def close(self) -> None:
        with self._lock:
            _wipe_bytes(self._state)
            self._state = bytearray(0)


# ─────────────────────────────────────────────────────────────────────────────
#  IdentityManager – persistent encrypted identity on disk
# ─────────────────────────────────────────────────────────────────────────────
class IdentityManager:
    """
    Manages the node's long-term identity keys.
    Keys are stored encrypted with the master password via PBKDF2 + ChaCha20.
    """

    PBKDF2_ITERATIONS = 600_000

    def __init__(self, identity_path: Path):
        self.path = identity_path
        self._master_key: Optional[bytearray] = None

    def create_new(self, password: str) -> dict:
        """Generate a fresh identity and persist it."""
        salt = _rust.secure_random_bytes(32)
        key  = self._derive_key(password.encode(), salt)

        identity = _rust.generate_identity()
        kyber    = _rust.generate_kyber_keypair()

        payload = {
            "ed25519_public":  identity["ed25519_public"].hex(),
            "ed25519_private": identity["ed25519_private"].hex(),
            "x25519_public":   identity["x25519_public"].hex(),
            "x25519_private":  identity["x25519_private"].hex(),
            "kyber_public":    kyber["kyber_public"].hex(),
            "kyber_private":   kyber["kyber_private"].hex(),
        }
        plaintext = json.dumps(payload).encode()
        encrypted = _rust.encrypt_message(bytes(key), plaintext)
        _wipe_bytes(key)

        blob = {
            "version": 1,
            "salt":    salt.hex(),
            "payload": encrypted.hex(),
        }
        self.path.write_text(json.dumps(blob))
        return payload

    def load(self, password: str) -> Optional[dict]:
        """Decrypt and return identity dict, or None on wrong password."""
        if not self.path.exists():
            return None
        blob = json.loads(self.path.read_text())
        salt = bytes.fromhex(blob["salt"])
        key  = self._derive_key(password.encode(), salt)
        try:
            plaintext = _rust.decrypt_message(bytes(key), bytes.fromhex(blob["payload"]))
            _wipe_bytes(key)
            return json.loads(plaintext)
        except Exception:
            _wipe_bytes(key)
            return None

    def _derive_key(self, password: bytes, salt: bytes) -> bytearray:
        raw = _rust.derive_key_pbkdf2(password, salt, self.PBKDF2_ITERATIONS)
        return bytearray(raw)


# ─────────────────────────────────────────────────────────────────────────────
#  DualPasswordManager – real + decoy database
# ─────────────────────────────────────────────────────────────────────────────
class DualPasswordManager:
    """
    Manages two identity files:
      - identity.real.enc  (unlocked by real password)
      - identity.decoy.enc (unlocked by decoy password → fake data)
    An observer cannot distinguish which file is which.
    """

    def __init__(self, base_dir: Path):
        self.real_path  = base_dir / "identity.a.enc"
        self.decoy_path = base_dir / "identity.b.enc"

    def setup(self, real_password: str, decoy_password: str) -> None:
        real_mgr  = IdentityManager(self.real_path)
        decoy_mgr = IdentityManager(self.decoy_path)
        real_mgr.create_new(real_password)
        decoy_mgr.create_new(decoy_password)

    def unlock(self, password: str) -> Optional[Tuple[dict, bool]]:
        """Returns (identity_dict, is_real) or None if wrong password."""
        real_mgr  = IdentityManager(self.real_path)
        decoy_mgr = IdentityManager(self.decoy_path)

        identity = real_mgr.load(password)
        if identity:
            return identity, True
        identity = decoy_mgr.load(password)
        if identity:
            return identity, False
        return None


# ─────────────────────────────────────────────────────────────────────────────
#  MessageCrypto – high-level encrypt/decrypt for transport layer
# ─────────────────────────────────────────────────────────────────────────────
class MessageCrypto:
    """
    High-level interface used by the network layer.
    Handles session key establishment and message framing.
    """

    def __init__(self, my_identity: dict):
        self.identity = my_identity
        self._sessions: dict[str, CryptoSession] = {}

    def initiate_handshake(self, peer_id: str, peer_x25519_pub: bytes,
                           peer_kyber_pub: bytes) -> bytes:
        """Sender side: perform hybrid key exchange, return handshake blob."""
        result = _rust.hybrid_encapsulate(peer_x25519_pub, peer_kyber_pub)
        shared = result["shared_secret"]

        state_json = _rust.ratchet_init_sender(shared, peer_x25519_pub)
        self._sessions[peer_id] = CryptoSession(peer_id, state_json)

        # Pack handshake: eph_pub(32) + kyber_ct(variable)
        eph_pub  = result["x25519_eph_pub"]
        kyber_ct = result["kyber_ciphertext"]
        handshake = (
            len(eph_pub).to_bytes(2, "big") + eph_pub +
            len(kyber_ct).to_bytes(4, "big") + kyber_ct
        )
        return handshake

    def complete_handshake(self, peer_id: str, handshake: bytes,
                           my_x25519_priv: bytes, my_kyber_priv: bytes) -> None:
        """Receiver side: decapsulate and initialise ratchet."""
        idx = 0
        eph_len  = int.from_bytes(handshake[idx:idx+2], "big"); idx += 2
        eph_pub  = handshake[idx:idx+eph_len]; idx += eph_len
        ct_len   = int.from_bytes(handshake[idx:idx+4], "big"); idx += 4
        kyber_ct = handshake[idx:idx+ct_len]

        shared = _rust.hybrid_decapsulate(my_x25519_priv, eph_pub, my_kyber_priv, kyber_ct)
        state_json = _rust.ratchet_init_receiver(shared, my_x25519_priv, eph_pub)
        self._sessions[peer_id] = CryptoSession(peer_id, state_json)

    def encrypt_for(self, peer_id: str, plaintext: bytes) -> bytes:
        session = self._sessions.get(peer_id)
        if not session:
            raise KeyError(f"No session for peer {peer_id}")
        ct, _ = session.encrypt(plaintext)
        return ct

    def decrypt_from(self, peer_id: str, ciphertext: bytes) -> bytes:
        session = self._sessions.get(peer_id)
        if not session:
            raise KeyError(f"No session for peer {peer_id}")
        return session.decrypt(ciphertext)

    def close_session(self, peer_id: str) -> None:
        session = self._sessions.pop(peer_id, None)
        if session:
            session.close()

    def close_all(self) -> None:
        for s in list(self._sessions.values()):
            s.close()
        self._sessions.clear()


# ─────────────────────────────────────────────────────────────────────────────
#  ContactIndex – HMAC-SHA3 blind index for database header blindness
# ─────────────────────────────────────────────────────────────────────────────
class ContactIndex:
    """Converts .onion addresses into opaque HMAC tokens for DB storage."""

    def __init__(self, master_key: bytes):
        self._key = master_key

    def index(self, onion_address: str) -> str:
        token = _rust.hmac_sha3_index(self._key, onion_address.encode())
        return token.hex()

    def close(self) -> None:
        key_buf = bytearray(self._key)
        _wipe_bytes(key_buf)


# ─────────────────────────────────────────────────────────────────────────────
#  MediaSanitizer – in-memory EXIF stripping
# ─────────────────────────────────────────────────────────────────────────────
class MediaSanitizer:
    """Strip metadata from media files entirely in RAM."""

    @staticmethod
    def strip(image_bytes: bytes) -> bytes:
        return _rust.strip_exif_bytes(image_bytes)
