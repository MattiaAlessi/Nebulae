"""
NEBULAE – Application Core
Wires together crypto, network, database, and UI layers.
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import sys
import time
from pathlib import Path
from typing import Callable, Optional, Dict, List

# ─────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
)
logger = logging.getLogger("NEBULAE")

# ─────────────────────────────────────────────────────────────────────────────
APP_DIR  = Path.home() / ".nebulae"
DATA_DIR = APP_DIR / "data"
APP_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)


# ─────────────────────────────────────────────────────────────────────────────
class NEBULAEApp:
    """
    Top-level application object.
    Instantiated by the GUI; holds all subsystems.
    """

    def __init__(
        self,
        message_callback: Callable[[str, str, str], None],  # (peer_id, nickname, body)
        status_callback: Callable[[str], None],
        amnesic_mode: bool = False,
    ):
        self.message_cb = message_callback
        self.status_cb  = status_callback
        self.amnesic    = amnesic_mode

        self.identity: Optional[Dict]  = None
        self.crypto = None
        self.node   = None
        self.store  = None
        self.contact_index = None
        self._canary = None
        self._running = False

    # ── Authentication ────────────────────────────────────────────────────────

    def first_run_setup(self, real_password: str, decoy_password: str) -> bool:
        """Generate a fresh identity with dual-password protection."""
        from core.crypto_manager import DualPasswordManager
        mgr = DualPasswordManager(DATA_DIR)
        mgr.setup(real_password, decoy_password)
        self.status_cb("Identity created. Please restart and login.")
        return True

    def login(self, password: str) -> bool:
        from core.crypto_manager import (
            DualPasswordManager, MessageCrypto, ContactIndex
        )
        import p2p_crypto as _rust

        mgr = DualPasswordManager(DATA_DIR)
        result = mgr.unlock(password)
        if not result:
            return False

        self.identity, is_real = result
        logger.info(f"Logged in (real={is_real})")

        # Derive local DB key from identity
        salt = _rust.secure_random_bytes(32)
        salt_path = DATA_DIR / "db.salt"
        if not salt_path.exists():
            salt_path.write_bytes(salt)
        else:
            salt = salt_path.read_bytes()

        db_key = _rust.derive_key_pbkdf2(password.encode(), salt, 200_000)
        master_hmac_key = _rust.blake3_hash(db_key)

        # Bootstrap subsystems
        self.crypto = MessageCrypto(self.identity)
        self.contact_index = ContactIndex(master_hmac_key)

        from core.database import create_session
        self.store = create_session(
            DATA_DIR, db_key,
            amnesic=self.amnesic,
            contact_index=self.contact_index,
            crypto_manager=self.crypto,
        )
        self.store.set_local_key(bytes(db_key))

        # Start network node
        from core.network import P2PNode
        self.node = P2PNode(
            crypto=self.crypto,
            identity=self.identity,
            data_dir=DATA_DIR,
            message_callback=self._on_message,
        )
        self.node.start()
        self._running = True
        self.status_cb(f"Node online: {self.node.onion_address}")
        return True

    # ── Message flow ──────────────────────────────────────────────────────────

    def _on_message(self, peer_id: str, body: bytes) -> None:
        contacts = self.store.load_contacts() if self.store else []
        nickname = next(
            (c.get("nickname", peer_id) for c in contacts if c.get("node_id") == peer_id),
            peer_id[:8]
        )
        if self.store:
            import uuid
            self.store.save_message(
                peer_id, "in", body, str(uuid.uuid4())
            )
        if self._canary:
            self._canary.heartbeat()
        self.message_cb(peer_id, nickname, body.decode(errors="replace"))

    def send_message(
        self,
        peer_id: str,
        text: str,
        self_destruct_seconds: Optional[float] = None,
    ) -> bool:
        if not self.node or not self._running:
            return False
        body = text.encode()
        if self.store:
            import uuid
            self.store.save_message(
                peer_id, "out", body, str(uuid.uuid4()),
                self_destruct_seconds=self_destruct_seconds,
            )
        if self._canary:
            self._canary.heartbeat()
        return self.node.send_message(peer_id, body)

    # ── Peer management ───────────────────────────────────────────────────────

    def connect_peer(self, onion: str) -> bool:
        if not self.node:
            return False
        return self.node.connect_to_peer(onion)

    def add_contact(self, onion: str, nickname: str) -> None:
        if self.store:
            self.store.save_contact(onion, nickname, {})

    def get_contacts(self) -> List[Dict]:
        return self.store.load_contacts() if self.store else []

    def get_history(self, peer_id: str, limit: int = 100) -> List[Dict]:
        return self.store.load_messages(peer_id, limit) if self.store else []

    def get_peers(self) -> List[Dict]:
        return self.node.get_peer_list() if self.node else []

    # ── Canary ───────────────────────────────────────────────────────────────

    def enable_canary(self, timeout_hours: float = 48) -> None:
        from core.network import CanaryProtocol
        self._canary = CanaryProtocol(
            timeout_seconds=timeout_hours * 3600,
            wipe_callback=self.panic_wipe,
        )
        self._canary.start()
        logger.info(f"Canary enabled ({timeout_hours}h timeout)")

    def heartbeat(self) -> None:
        if self._canary:
            self._canary.heartbeat()

    # ── Emergency ────────────────────────────────────────────────────────────

    def panic_wipe(self) -> None:
        """PANIC: destroy everything, quit."""
        logger.critical("=== PANIC WIPE INITIATED ===")
        if self.node:
            self.node.panic_wipe()
        if self.store and hasattr(self.store._db, "secure_wipe"):
            self.store._db.secure_wipe()
        # Wipe identity files
        for f in DATA_DIR.glob("identity.*.enc"):
            size = f.stat().st_size
            for _ in range(3):
                f.write_bytes(secrets.token_bytes(size))
            f.unlink()
        sys.exit(0)

    def shutdown(self) -> None:
        if self._canary:
            self._canary.stop()
        if self.node:
            self.node.stop()
        if self.contact_index:
            self.contact_index.close()
        self.crypto and self.crypto.close_all()
        self._running = False
