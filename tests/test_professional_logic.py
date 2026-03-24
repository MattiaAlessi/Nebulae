from __future__ import annotations

from pathlib import Path

from core.app import NEBULAEApp
from core.network import _build_signed_announce, _parse_and_verify_announce

import p2p_crypto as _rust


def _identity() -> dict:
    base = _rust.generate_identity()
    kyber = _rust.generate_kyber_keypair()
    return {
        "ed25519_public": base["ed25519_public"].hex(),
        "ed25519_private": base["ed25519_private"].hex(),
        "x25519_public": base["x25519_public"].hex(),
        "x25519_private": base["x25519_private"].hex(),
        "kyber_public": kyber["kyber_public"].hex(),
        "kyber_private": kyber["kyber_private"].hex(),
    }


def test_announce_signature_verification_ok():
    ident = _identity()
    blob = _build_signed_announce(ident, "node-123", "abc.onion")
    info = _parse_and_verify_announce(blob)
    assert info["node_id"] == "node-123"
    assert info["ed25519_pub"] == ident["ed25519_public"]


def test_announce_signature_tamper_detected():
    ident = _identity()
    blob = _build_signed_announce(ident, "node-123", "abc.onion")
    tampered = blob.replace(b"node-123", b"node-999")
    try:
        _parse_and_verify_announce(tampered)
    except Exception as e:
        assert "signature" in str(e).lower()
    else:
        raise AssertionError("tampered announce should fail verification")


def test_connect_peer_retry_backoff():
    app = NEBULAEApp(lambda *_: None, lambda *_: None)

    class DummyNode:
        def __init__(self):
            self.calls = 0

        def connect_to_peer(self, onion: str) -> bool:
            self.calls += 1
            return self.calls == 3

    app.node = DummyNode()
    ok = app.connect_peer("abc.onion")
    assert ok is True
    assert app.node.calls == 3
