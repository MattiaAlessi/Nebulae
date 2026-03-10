"""
NEBULAE – Database Manager
SQLCipher-encrypted storage with HMAC-SHA3 contact indexing (Header Blindness).
Supports RAM-only amnesic mode and secure wipe.
"""
from __future__ import annotations

import json
import os
import secrets
import sqlite3
import time
from pathlib import Path
from typing import List, Optional, Dict, Any

# SQLCipher is a drop-in replacement for sqlite3 with encryption
try:
    from pysqlcipher3 import dbapi2 as sqlcipher
    HAS_SQLCIPHER = True
except ImportError:
    import sqlite3 as sqlcipher
    HAS_SQLCIPHER = False


SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    contact_idx TEXT    NOT NULL,           -- HMAC-SHA3 blind index
    direction   TEXT    NOT NULL,           -- 'in' | 'out'
    encrypted   BLOB    NOT NULL,           -- ChaCha20 ciphertext
    timestamp   REAL    NOT NULL,
    uuid        TEXT    UNIQUE NOT NULL,
    self_destruct_at REAL DEFAULT NULL      -- epoch; NULL = never
);
CREATE INDEX IF NOT EXISTS idx_contact ON messages(contact_idx, timestamp);

CREATE TABLE IF NOT EXISTS contacts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    contact_idx TEXT    UNIQUE NOT NULL,    -- HMAC blind index
    meta_enc    BLOB    NOT NULL,           -- encrypted metadata blob
    added_at    REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS file_chunks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    transfer_id TEXT NOT NULL,
    chunk_idx   INTEGER NOT NULL,
    total_chunks INTEGER NOT NULL,
    encrypted   BLOB NOT NULL,
    UNIQUE(transfer_id, chunk_idx)
);
"""

# ─────────────────────────────────────────────────────────────────────────────
#  AmnesicDB – pure RAM SQLite (vanishes on close)
# ─────────────────────────────────────────────────────────────────────────────
class AmnesicDB:
    """In-memory only database. Leaves no trace on disk."""

    def __init__(self):
        self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def execute(self, sql: str, params=()) -> sqlite3.Cursor:
        return self._conn.execute(sql, params)

    def commit(self) -> None:
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()


# ─────────────────────────────────────────────────────────────────────────────
#  PersistentDB – SQLCipher on disk
# ─────────────────────────────────────────────────────────────────────────────
class PersistentDB:
    def __init__(self, path: Path, key: bytes):
        self._path = path
        self._conn = sqlcipher.connect(str(path), check_same_thread=False)
        if HAS_SQLCIPHER:
            key_hex = key.hex()
            self._conn.execute(f"PRAGMA key = \"x'{key_hex}'\"")
            self._conn.execute("PRAGMA cipher_page_size = 4096")
            self._conn.execute("PRAGMA kdf_iter = 256000")
            self._conn.execute("PRAGMA cipher_hmac_algorithm = HMAC_SHA512")
            self._conn.execute("PRAGMA cipher_kdf_algorithm = PBKDF2_HMAC_SHA512")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def execute(self, sql: str, params=()) -> sqlite3.Cursor:
        return self._conn.execute(sql, params)

    def commit(self) -> None:
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def secure_wipe(self) -> None:
        """Overwrite file contents multiple times before deletion."""
        self._conn.close()
        if self._path.exists():
            size = self._path.stat().st_size
            for _ in range(3):
                with open(self._path, "r+b") as f:
                    f.write(secrets.token_bytes(size))
                    f.flush()
                    os.fsync(f.fileno())
            self._path.unlink()


# ─────────────────────────────────────────────────────────────────────────────
#  MessageStore – high-level message storage
# ─────────────────────────────────────────────────────────────────────────────
class MessageStore:
    """
    Stores and retrieves messages with blind contact indexing.
    Handles self-destruct timer enforcement and file chunk storage.
    """

    def __init__(self, db, contact_index, crypto_manager):
        self._db      = db
        self._index   = contact_index   # ContactIndex instance
        self._crypto  = crypto_manager  # MessageCrypto for local encryption
        self._local_key: Optional[bytes] = None  # set after login

    def set_local_key(self, key: bytes) -> None:
        self._local_key = key

    # ── Messages ──────────────────────────────────────────────────────────────

    def save_message(
        self,
        onion: str,
        direction: str,
        plaintext: bytes,
        msg_uuid: str,
        self_destruct_seconds: Optional[float] = None,
    ) -> None:
        if not self._local_key:
            return
        blind_idx = self._index.index(onion)
        import p2p_crypto as _rust
        encrypted  = _rust.encrypt_message(self._local_key, plaintext)
        destruct_at = time.time() + self_destruct_seconds if self_destruct_seconds else None

        self._db.execute(
            "INSERT OR IGNORE INTO messages "
            "(contact_idx, direction, encrypted, timestamp, uuid, self_destruct_at) "
            "VALUES (?,?,?,?,?,?)",
            (blind_idx, direction, encrypted, time.time(), msg_uuid, destruct_at),
        )
        self._db.commit()

    def load_messages(self, onion: str, limit: int = 100) -> List[Dict[str, Any]]:
        if not self._local_key:
            return []
        import p2p_crypto as _rust
        blind_idx = self._index.index(onion)
        cur = self._db.execute(
            "SELECT direction, encrypted, timestamp, uuid, self_destruct_at "
            "FROM messages WHERE contact_idx=? ORDER BY timestamp DESC LIMIT ?",
            (blind_idx, limit),
        )
        results = []
        for row in cur.fetchall():
            direction, enc, ts, uid, destruct_at = row
            if destruct_at and time.time() > destruct_at:
                self._secure_delete_message(uid)
                continue
            try:
                plaintext = _rust.decrypt_message(self._local_key, enc)
                results.append({
                    "direction": direction,
                    "body":      plaintext.decode(errors="replace"),
                    "timestamp": ts,
                    "uuid":      uid,
                })
            except Exception:
                pass
        return list(reversed(results))

    def purge_expired(self) -> int:
        cur = self._db.execute(
            "SELECT uuid FROM messages WHERE self_destruct_at IS NOT NULL "
            "AND self_destruct_at < ?", (time.time(),)
        )
        uuids = [row[0] for row in cur.fetchall()]
        for uid in uuids:
            self._secure_delete_message(uid)
        return len(uuids)

    def _secure_delete_message(self, msg_uuid: str) -> None:
        self._db.execute(
            "UPDATE messages SET encrypted=? WHERE uuid=?",
            (secrets.token_bytes(64), msg_uuid),
        )
        self._db.commit()
        self._db.execute("DELETE FROM messages WHERE uuid=?", (msg_uuid,))
        self._db.commit()

    def delete_all_for_contact(self, onion: str) -> None:
        blind_idx = self._index.index(onion)
        cur = self._db.execute(
            "SELECT uuid FROM messages WHERE contact_idx=?", (blind_idx,)
        )
        for (uid,) in cur.fetchall():
            self._secure_delete_message(uid)

    # ── Contacts ──────────────────────────────────────────────────────────────

    def save_contact(self, onion: str, nickname: str, public_keys: Dict[str, str]) -> None:
        if not self._local_key:
            return
        import p2p_crypto as _rust
        blind_idx = self._index.index(onion)
        meta = json.dumps({"nickname": nickname, "onion": onion, **public_keys}).encode()
        encrypted = _rust.encrypt_message(self._local_key, meta)
        self._db.execute(
            "INSERT OR REPLACE INTO contacts (contact_idx, meta_enc, added_at) VALUES (?,?,?)",
            (blind_idx, encrypted, time.time()),
        )
        self._db.commit()

    def load_contacts(self) -> List[Dict[str, Any]]:
        if not self._local_key:
            return []
        import p2p_crypto as _rust
        cur = self._db.execute("SELECT meta_enc FROM contacts")
        results = []
        for (enc,) in cur.fetchall():
            try:
                meta = json.loads(_rust.decrypt_message(self._local_key, enc))
                results.append(meta)
            except Exception:
                pass
        return results

    # ── File chunks ───────────────────────────────────────────────────────────

    def save_chunk(self, transfer_id: str, idx: int, total: int, encrypted: bytes) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO file_chunks "
            "(transfer_id, chunk_idx, total_chunks, encrypted) VALUES (?,?,?,?)",
            (transfer_id, idx, total, encrypted),
        )
        self._db.commit()

    def load_chunks(self, transfer_id: str) -> List[bytes]:
        cur = self._db.execute(
            "SELECT encrypted FROM file_chunks WHERE transfer_id=? ORDER BY chunk_idx",
            (transfer_id,),
        )
        return [row[0] for row in cur.fetchall()]

    def delete_chunks(self, transfer_id: str) -> None:
        self._db.execute("DELETE FROM file_chunks WHERE transfer_id=?", (transfer_id,))
        self._db.commit()

    # ── Settings ──────────────────────────────────────────────────────────────

    def get_setting(self, key: str, default=None):
        cur = self._db.execute("SELECT value FROM settings WHERE key=?", (key,))
        row = cur.fetchone()
        return json.loads(row[0]) if row else default

    def set_setting(self, key: str, value) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)",
            (key, json.dumps(value)),
        )
        self._db.commit()


# ─────────────────────────────────────────────────────────────────────────────
#  SessionFactory – wires up the right DB backend
# ─────────────────────────────────────────────────────────────────────────────
def create_session(
    data_dir: Path,
    db_key: bytes,
    amnesic: bool = False,
    contact_index=None,
    crypto_manager=None,
) -> MessageStore:
    if amnesic:
        db = AmnesicDB()
    else:
        db = PersistentDB(data_dir / "nebulae.db", db_key)
    return MessageStore(db, contact_index, crypto_manager)
