from __future__ import annotations

from pathlib import Path
import tempfile

import p2p_crypto as _rust

from core.crypto_manager import ContactIndex, MessageCrypto
from core.database import create_session


def make_identity() -> dict:
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


def test_handshake_and_message_crypto() -> None:
    alice = make_identity()
    bob = make_identity()

    a_crypto = MessageCrypto(alice)
    b_crypto = MessageCrypto(bob)

    hs = a_crypto.initiate_handshake(
        "bob",
        bytes.fromhex(bob["x25519_public"]),
        bytes.fromhex(bob["kyber_public"]),
    )
    b_crypto.complete_handshake(
        "alice",
        hs,
        bytes.fromhex(bob["x25519_private"]),
        bytes.fromhex(bob["kyber_private"]),
    )

    plaintext = b"hello nebulae"
    ct = a_crypto.encrypt_for("bob", plaintext)
    out = b_crypto.decrypt_from("alice", ct)
    assert out == plaintext, "decrypted payload mismatch"

    a_crypto.close_all()
    b_crypto.close_all()


def test_message_store_roundtrip() -> None:
    with tempfile.TemporaryDirectory() as td:
        data_dir = Path(td)
        db_key = _rust.secure_random_bytes(32)
        contact_key = _rust.blake3_hash(db_key)
        index = ContactIndex(contact_key)
        store = create_session(data_dir, db_key, amnesic=False, contact_index=index, crypto_manager=None)
        store.set_local_key(db_key)

        onion = "peerexample1234567890abcdef.onion"
        store.save_contact(onion, "Bob", {})
        store.save_message(onion, "out", b"ping", "uuid-1")
        store.save_message(onion, "in", b"pong", "uuid-2")

        contacts = store.load_contacts()
        history = store.load_messages(onion, 10)

        assert any(c.get("onion") == onion for c in contacts), "contact not found"
        bodies = [m["body"] for m in history]
        assert bodies == ["ping", "pong"], f"unexpected history order/content: {bodies}"

        store._db.close()
        index.close()


if __name__ == "__main__":
    test_handshake_and_message_crypto()
    test_message_store_roundtrip()
    print("SMOKE TEST OK")
