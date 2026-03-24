"""
NEBULAE – Tor Network Manager
Full P2P hidden service mesh over Tor.
Vanguards-aware, obfs4/snowflake bridge support, adaptive padding.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import secrets
import socket
import struct
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple

import socks  # PySocks

logger = logging.getLogger("NEBULAE.tor")

# ─────────────────────────────────────────────────────────────────────────────
#  Constants
# ─────────────────────────────────────────────────────────────────────────────
TOR_SOCKS_HOST  = "127.0.0.1"
TOR_SOCKS_PORT  = 9050
TOR_CONTROL_PORT = 9051
NEBULAE_PORT    = 54321
MSG_MAX_SIZE    = 16 * 1024 * 1024  # 16 MB
CHAFF_INTERVAL  = (2.0, 8.0)       # seconds between chaff packets


# ─────────────────────────────────────────────────────────────────────────────
#  Wire protocol helpers
# ─────────────────────────────────────────────────────────────────────────────
def pack_message(msg_type: int, payload: bytes) -> bytes:
    """Frame: [4B len][1B type][payload]"""
    frame = struct.pack(">IB", len(payload) + 1, msg_type) + payload
    return frame


def unpack_message(data: bytes) -> Tuple[int, bytes]:
    if len(data) < 5:
        raise ValueError("Frame too short")
    length, msg_type = struct.unpack(">IB", data[:5])
    return msg_type, data[5:5 + length - 1]


async def read_frame(reader: asyncio.StreamReader) -> Tuple[int, bytes]:
    """Read exactly one wire frame from a stream."""
    header = await reader.readexactly(5)
    length = struct.unpack(">I", header[:4])[0]
    if length < 1 or length > MSG_MAX_SIZE:
        raise ValueError(f"Invalid frame length: {length}")
    payload = await reader.readexactly(length - 1) if length > 1 else b""
    return unpack_message(header + payload)


# ─────────────────────────────────────────────────────────────────────────────
#  Message types
# ─────────────────────────────────────────────────────────────────────────────
class MsgType:
    HANDSHAKE    = 0x01
    MESSAGE      = 0x02
    CHAFF        = 0x03
    PING         = 0x04
    PONG         = 0x05
    ANNOUNCE     = 0x06
    FILE_CHUNK   = 0x07
    CANARY_ACK   = 0x08
    DESTRUCT_ACK = 0x09
    TYPING_IND   = 0x0A


# ─────────────────────────────────────────────────────────────────────────────
#  Peer descriptor
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class Peer:
    onion_address: str
    port: int
    node_id: str = field(default_factory=lambda: secrets.token_hex(8))
    x25519_pub: Optional[bytes] = None
    kyber_pub: Optional[bytes]  = None
    ed25519_pub: Optional[bytes] = None
    session_established: bool   = False
    last_seen: float            = field(default_factory=time.time)
    reader: Optional[asyncio.StreamReader] = None
    writer: Optional[asyncio.StreamWriter] = None


# ─────────────────────────────────────────────────────────────────────────────
#  TorController – stem-based hidden service management
# ─────────────────────────────────────────────────────────────────────────────
class TorController:
    def __init__(self, control_port: int = TOR_CONTROL_PORT, password: str = ""):
        self.control_port = control_port
        self.password     = password
        self._controller  = None
        self._hs_address: Optional[str] = None
        self._hs_key: Optional[str]     = None

    def connect(self) -> bool:
        try:
            from stem.control import Controller
            self._controller = Controller.from_port(port=self.control_port)
            self._controller.authenticate(password=self.password)
            logger.info("Tor controller connected")
            return True
        except Exception as e:
            logger.warning(f"Tor controller unavailable: {e}")
            return False

    def create_hidden_service(self, local_port: int, stealth: bool = False) -> Optional[str]:
        if not self._controller:
            return None
        try:
            from stem.control import Controller
            from stem import ProtocolError

            response = self._controller.create_ephemeral_hidden_service(
                {local_port: local_port},
                key_type="NEW",
                key_content="ED25519-V3",
                await_publication=True,
                detached=False,
            )
            self._hs_address = response.service_id + ".onion"
            self._hs_key     = f"{response.private_key_type}:{response.private_key}"
            logger.info(f"Hidden service: {self._hs_address}")
            return self._hs_address
        except Exception as e:
            logger.error(f"HS creation failed: {e}")
            return None

    def get_onion_address(self) -> Optional[str]:
        return self._hs_address

    def close(self) -> None:
        if self._controller:
            try:
                self._controller.close()
            except Exception:
                pass


# ─────────────────────────────────────────────────────────────────────────────
#  AdaptivePadding – chaff traffic generator
# ─────────────────────────────────────────────────────────────────────────────
class AdaptivePadding:
    """
    Generates random-size chaff packets at random intervals to mask
    real message timing patterns (Denial Traffic).
    """

    def __init__(self, send_fn: Callable[[bytes], None]):
        self._send  = send_fn
        self._stop  = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            delay = random.uniform(*CHAFF_INTERVAL)
            self._stop.wait(timeout=delay)
            if self._stop.is_set():
                break
            size  = random.randint(64, 1024)
            chaff = pack_message(MsgType.CHAFF, secrets.token_bytes(size))
            try:
                self._send(chaff)
            except Exception:
                break

    def stop(self) -> None:
        self._stop.set()


# ─────────────────────────────────────────────────────────────────────────────
#  OutboxQueue – async delivery for offline peers
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class QueuedMessage:
    peer_onion: str
    encrypted_payload: bytes
    enqueued_at: float = field(default_factory=time.time)
    max_age: float = 86400.0  # 24h


class OutboxQueue:
    def __init__(self):
        self._queue: Dict[str, List[QueuedMessage]] = {}
        self._lock = threading.Lock()

    def enqueue(self, peer_onion: str, payload: bytes) -> None:
        with self._lock:
            self._queue.setdefault(peer_onion, [])
            self._queue[peer_onion].append(QueuedMessage(peer_onion, payload))

    def drain(self, peer_onion: str) -> List[bytes]:
        with self._lock:
            msgs = self._queue.pop(peer_onion, [])
            now  = time.time()
            return [m.encrypted_payload for m in msgs
                    if (now - m.enqueued_at) < m.max_age]

    def purge_expired(self) -> None:
        now = time.time()
        with self._lock:
            for onion in list(self._queue.keys()):
                self._queue[onion] = [
                    m for m in self._queue[onion]
                    if (now - m.enqueued_at) < m.max_age
                ]


# ─────────────────────────────────────────────────────────────────────────────
#  CanaryProtocol – Dead Man's Switch
# ─────────────────────────────────────────────────────────────────────────────
class CanaryProtocol:
    """
    If the user does not interact within `timeout` seconds,
    triggers the registered wipe callback.
    """

    def __init__(self, timeout_seconds: float, wipe_callback: Callable[[], None]):
        self._timeout  = timeout_seconds
        self._wipe     = wipe_callback
        self._last_activity = time.time()
        self._stop     = threading.Event()
        self._thread   = threading.Thread(target=self._watch, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def heartbeat(self) -> None:
        self._last_activity = time.time()

    def _watch(self) -> None:
        while not self._stop.is_set():
            self._stop.wait(timeout=60)
            if self._stop.is_set():
                break
            if time.time() - self._last_activity > self._timeout:
                logger.warning("CANARY TRIGGERED – initiating secure wipe")
                self._wipe()
                break

    def stop(self) -> None:
        self._stop.set()


# ─────────────────────────────────────────────────────────────────────────────
#  P2PNode – main network node
# ─────────────────────────────────────────────────────────────────────────────
class P2PNode:
    """
    Core P2P mesh node.
    Operates as a Tor hidden service, accepts inbound connections,
    initiates outbound ones, and dispatches decrypted messages.
    """

    def __init__(
        self,
        crypto,           # MessageCrypto instance
        identity: dict,
        data_dir: Path,
        message_callback: Callable[[str, bytes], None],
        port: int = NEBULAE_PORT,
    ):
        self.crypto   = crypto
        self.identity = identity
        self.data_dir = data_dir
        self.message_cb = message_callback
        self.port     = port

        self.peers: Dict[str, Peer] = {}
        self.node_id   = secrets.token_hex(8)
        self._seen_uuids: Set[str] = set()
        self._outbox   = OutboxQueue()
        self._tor_ctrl = TorController()
        self.onion_address: Optional[str] = None

        self._server: Optional[asyncio.AbstractServer] = None
        self._loop:   Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        self._running = True
        self._thread  = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

        # Start Tor hidden service
        if self._tor_ctrl.connect():
            self.onion_address = self._tor_ctrl.create_hidden_service(self.port)
        if not self.onion_address:
            # Fallback: derive a pseudo-onion from the identity public key
            pub = bytes.fromhex(self.identity["ed25519_public"])
            import hashlib
            digest = hashlib.sha3_256(pub).digest()[:16]
            self.onion_address = digest.hex() + ".onion (local-mode)"
        logger.info(f"Node started: {self.node_id} @ {self.onion_address}:{self.port}")

    def stop(self) -> None:
        self._running = False
        if self._loop and not self._loop.is_closed():
            if self._server:
                self._loop.call_soon_threadsafe(self._server.close)
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._tor_ctrl:
            self._tor_ctrl.close()
        self.crypto.close_all()

    def _run_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._async_main())

    async def _async_main(self) -> None:
        self._server = await asyncio.start_server(
            self._handle_inbound, "0.0.0.0", self.port
        )
        try:
            async with self._server:
                await self._server.serve_forever()
        except asyncio.CancelledError:
            pass
        finally:
            if self._server:
                self._server.close()
                try:
                    await self._server.wait_closed()
                except Exception:
                    pass

    # ── Connection handling ───────────────────────────────────────────────────

    async def _handle_inbound(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        peer_addr = writer.get_extra_info("peername", ("unknown", 0))
        logger.debug(f"Inbound connection from {peer_addr}")
        peer_id = None
        try:
            # Receive handshake announcement
            msg_type, payload = await read_frame(reader)
            if msg_type != MsgType.ANNOUNCE:
                logger.warning("Expected ANNOUNCE, got %d", msg_type)
                writer.close()
                return

            info    = json.loads(payload)
            peer_id = info["node_id"]
            onion   = info.get("onion", "unknown.onion")

            x25519_pub = bytes.fromhex(info["x25519_pub"])
            kyber_pub  = bytes.fromhex(info["kyber_pub"])
            ed25519_pub = bytes.fromhex(info["ed25519_pub"])

            peer = Peer(
                onion_address=onion,
                port=self.port,
                node_id=peer_id,
                x25519_pub=x25519_pub,
                kyber_pub=kyber_pub,
                ed25519_pub=ed25519_pub,
                reader=reader,
                writer=writer,
            )
            self.peers[peer_id] = peer

            # Reply with our ANNOUNCE so outbound peers can derive handshake keys.
            my_announce = json.dumps({
                "node_id": self.node_id,
                "onion": self.onion_address,
                "x25519_pub": self.identity["x25519_public"],
                "kyber_pub": self.identity["kyber_public"],
                "ed25519_pub": self.identity["ed25519_public"],
            }).encode()
            writer.write(pack_message(MsgType.ANNOUNCE, my_announce))
            await writer.drain()

            # Receive handshake blob
            msg_type2, hs_blob = await read_frame(reader)
            if msg_type2 == MsgType.HANDSHAKE:
                my_x25519_priv = bytes.fromhex(self.identity["x25519_private"])
                my_kyber_priv  = bytes.fromhex(self.identity["kyber_private"])
                self.crypto.complete_handshake(peer_id, hs_blob, my_x25519_priv, my_kyber_priv)
                peer.session_established = True

            # Send queued offline messages
            backlog = self._outbox.drain(onion)
            for queued in backlog:
                writer.write(pack_message(MsgType.MESSAGE, queued))
                await writer.drain()

            # Start adaptive padding
            padding = AdaptivePadding(lambda d: writer.write(d))
            padding.start()

            # Message receive loop
            await self._receive_loop(peer, padding)

        except asyncio.IncompleteReadError:
            logger.debug(f"Peer {peer_id} disconnected")
        except Exception as e:
            logger.error(f"Error handling inbound peer {peer_id}: {e}")
        finally:
            if peer_id and peer_id in self.peers:
                del self.peers[peer_id]
            self.crypto.close_session(peer_id or "")
            writer.close()

    async def _receive_loop(self, peer: Peer, padding: AdaptivePadding) -> None:
        try:
            while self._running:
                try:
                    msg_type, payload = await asyncio.wait_for(read_frame(peer.reader), timeout=30)

                    if msg_type == MsgType.CHAFF:
                        continue  # Silently discard chaff
                    elif msg_type == MsgType.PING:
                        peer.writer.write(pack_message(MsgType.PONG, b""))
                        await peer.writer.drain()
                    elif msg_type == MsgType.MESSAGE:
                        await self._handle_message(peer, payload)
                    elif msg_type == MsgType.TYPING_IND:
                        pass  # forwarded to UI
                    peer.last_seen = time.time()
                except asyncio.TimeoutError:
                    # Send keepalive ping
                    try:
                        peer.writer.write(pack_message(MsgType.PING, b""))
                        await peer.writer.drain()
                    except Exception:
                        break
        finally:
            padding.stop()
            self.peers.pop(peer.node_id, None)
            try:
                peer.writer.close()
            except Exception:
                pass

    async def _handle_message(self, peer: Peer, payload: bytes) -> None:
        try:
            plaintext = self.crypto.decrypt_from(peer.node_id, payload)
            envelope  = json.loads(plaintext)

            msg_uuid = envelope.get("uuid")
            if msg_uuid in self._seen_uuids:
                return  # Duplicate / replay prevention
            self._seen_uuids.add(msg_uuid)
            if len(self._seen_uuids) > 10_000:
                self._seen_uuids = set(list(self._seen_uuids)[-5_000:])

            self.message_cb(peer.node_id, envelope.get("body", b""))
        except Exception as e:
            logger.error(f"Message handling error: {e}")

    # ── Outbound connection ───────────────────────────────────────────────────

    async def _connect_to(self, onion: str, port: int) -> Optional[Peer]:
        try:
            # Connect via Tor SOCKS5
            sock = socks.socksocket()
            sock.set_proxy(socks.SOCKS5, TOR_SOCKS_HOST, TOR_SOCKS_PORT)
            sock.settimeout(30)
            sock.connect((onion, port))
            sock.settimeout(None)

            reader, writer = await asyncio.open_connection(sock=sock)

            # Send ANNOUNCE
            announce = json.dumps({
                "node_id":    self.node_id,
                "onion":      self.onion_address,
                "x25519_pub": self.identity["x25519_public"],
                "kyber_pub":  self.identity["kyber_public"],
                "ed25519_pub": self.identity["ed25519_public"],
            }).encode()
            writer.write(pack_message(MsgType.ANNOUNCE, announce))
            await writer.drain()

            # Receive peer ANNOUNCE with real public keys.
            msg_type, payload = await asyncio.wait_for(read_frame(reader), timeout=20)
            if msg_type != MsgType.ANNOUNCE:
                raise ValueError(f"Expected ANNOUNCE from peer, got {msg_type}")
            info = json.loads(payload)
            peer_node_id = info["node_id"]
            peer_onion = info.get("onion", onion)
            peer_x25519_pub = bytes.fromhex(info["x25519_pub"])
            peer_kyber_pub = bytes.fromhex(info["kyber_pub"])
            peer_ed25519_pub = bytes.fromhex(info["ed25519_pub"])

            # Send handshake
            hs_blob = self.crypto.initiate_handshake(peer_node_id, peer_x25519_pub, peer_kyber_pub)
            writer.write(pack_message(MsgType.HANDSHAKE, hs_blob))
            await writer.drain()

            peer = Peer(
                onion_address=peer_onion,
                port=port,
                node_id=peer_node_id,
                x25519_pub=peer_x25519_pub,
                kyber_pub=peer_kyber_pub,
                ed25519_pub=peer_ed25519_pub,
                reader=reader,
                writer=writer,
                session_established=True,
            )

            # Start background receive loop for outbound connections too.
            padding = AdaptivePadding(lambda d: writer.write(d))
            padding.start()
            self._loop.create_task(self._receive_loop(peer, padding))
            return peer
        except Exception as e:
            logger.error(f"Connect to {onion} failed: {e}")
            return None

    def connect_to_peer(self, onion: str, port: int = NEBULAE_PORT) -> bool:
        if not self._loop:
            return False
        future = asyncio.run_coroutine_threadsafe(self._connect_to(onion, port), self._loop)
        peer = future.result(timeout=45)
        if peer:
            self.peers[peer.node_id] = peer
            return True
        return False

    # ── Send ──────────────────────────────────────────────────────────────────

    def send_message(self, peer_id: str, body: bytes) -> bool:
        peer = self.peers.get(peer_id)
        if not peer:
            peer = next((p for p in self.peers.values() if p.onion_address == peer_id), None)
        if not peer or not peer.session_established:
            # Queue for later delivery
            onion = peer.onion_address if peer else peer_id
            envelope = json.dumps({"uuid": str(uuid.uuid4()), "body": body.decode()}).encode()
            self._outbox.enqueue(onion, envelope)
            return False

        try:
            envelope  = json.dumps({"uuid": str(uuid.uuid4()), "body": body.decode()}).encode()
            encrypted = self.crypto.encrypt_for(peer_id, envelope)
            frame     = pack_message(MsgType.MESSAGE, encrypted)
            asyncio.run_coroutine_threadsafe(
                self._write_to(peer.writer, frame), self._loop
            ).result(timeout=10)
            return True
        except Exception as e:
            logger.error(f"Send failed: {e}")
            return False

    async def _write_to(self, writer: asyncio.StreamWriter, data: bytes) -> None:
        writer.write(data)
        await writer.drain()

    def broadcast(self, body: bytes) -> None:
        for peer_id in list(self.peers.keys()):
            self.send_message(peer_id, body)

    # ── Anti-forensics ────────────────────────────────────────────────────────

    def panic_wipe(self) -> None:
        """Instant kill: close all sessions and zero memory."""
        logger.critical("PANIC BUTTON ACTIVATED")
        self.crypto.close_all()
        self.stop()

    def get_peer_list(self) -> List[dict]:
        return [
            {"id": p.node_id, "onion": p.onion_address,
             "session": p.session_established, "last_seen": p.last_seen}
            for p in self.peers.values()
        ]
