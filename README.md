# ◈ NEBULAE
### P2P Tor-Crypted Chat — Hybrid Rust/Python Stealth Messenger

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![Rust](https://img.shields.io/badge/Rust-2021_Edition-orange.svg)](https://www.rust-lang.org/)
[![Tor](https://img.shields.io/badge/Tor-Hidden_Services_v3-purple.svg)](https://www.torproject.org/)
[![Crypto](https://img.shields.io/badge/Crypto-Post--Quantum_Hybrid-cyan.svg)]()

> **Zero servers. Zero metadata. Zero traces.**  
> Every byte encrypted. Every identity anonymous. Every session ephemeral.

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│                         NEBULAE Stack                                │
├──────────────────────────────────────────────────────────────────────┤
│  GUI (Tkinter cyberpunk dark UI)  │  CLI (Rich terminal interface)   │
├──────────────────────────────────────────────────────────────────────┤
│                    core/app.py — Application Core                    │
│           (login, dual-password, canary, lifecycle mgmt)             │
├─────────────────────────┬────────────────────────────────────────────┤
│   core/network.py       │         core/database.py                  │
│   P2PNode (asyncio)     │  MessageStore + SQLCipher + HMAC index     │
│   TorController (stem)  │  AmnesicDB (RAM-only mode)                │
│   AdaptivePadding       │  Secure wipe (3-pass overwrite)           │
│   OutboxQueue           │                                            │
│   CanaryProtocol        │                                            │
├─────────────────────────┴────────────────────────────────────────────┤
│                    core/crypto_manager.py                            │
│          (Python wrapper for Rust engine via PyO3)                   │
├──────────────────────────────────────────────────────────────────────┤
│                    p2p_crypto/src/lib.rs  ← RUST                     │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │  Hybrid Handshake: X25519 + ML-KEM-768 (Kyber) → BLAKE3 merge  │ │
│  │  Double Ratchet: X3DH init → per-message ChaCha20-Poly1305     │ │
│  │  Signatures: Ed25519 sign/verify                                │ │
│  │  KDF: PBKDF2-SHA512 (600k iter) + HKDF-SHA256                 │ │
│  │  Index: HMAC-SHA3-256 (Header Blindness)                        │ │
│  │  Memory: zeroize (Zeroize + ZeroizeOnDrop traits)              │ │
│  └─────────────────────────────────────────────────────────────────┘ │
├──────────────────────────────────────────────────────────────────────┤
│                     Tor Network (SOCKS5 + stem)                      │
│     Hidden Services v3 · obfs4/Snowflake bridges · Vanguards        │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Security Features

### 🔐 Post-Quantum Hybrid Cryptography
- **Handshake**: X25519 (ECDH) **+** ML-KEM-768 (Kyber) combined via BLAKE3
- **Protects against**: "Harvest Now, Decrypt Later" quantum attacks
- **Symmetric**: ChaCha20-Poly1305 (faster than AES on non-accelerated hardware)
- **Signatures**: Ed25519 for message authenticity and non-repudiation

### 🔄 Double Ratchet Protocol (Signal-style)
- X3DH initial key exchange
- Per-message key derivation and immediate destruction
- **Perfect Forward Secrecy**: past messages safe even if current key is compromised
- Break-in recovery: future messages safe after compromise

### 🛡 Anti-Forensics
| Feature | Implementation |
|---|---|
| **Header Blindness** | HMAC-SHA3-256 blind index — contacts not identifiable without master key |
| **Dual Password** | Real password → real data · Decoy password → fake database |
| **Amnesic Mode** | RAM-only database — vanishes on app close |
| **Secure Wipe** | 3-pass random overwrite before deletion |
| **Memory Safety** | Rust `zeroize` crate — keys overwritten at scope exit |
| **EXIF Strip** | In-memory only, originals never touch disk |

### 🧅 Tor Integration
- **Pure P2P v3 Hidden Services**: each node is a `.onion` address
- **Adaptive Padding**: chaff traffic masks real message timing
- **Denial Traffic**: constant encrypted noise when idle
- **Bridge Support**: obfs4 and Snowflake for firewall/DPI bypass
- **Stealth Mode**: `client-auth` makes your hidden service invisible

### 🚨 Emergency Features
| Feature | Trigger |
|---|---|
| **Panic Button** | `Ctrl+Shift+P` or GUI button → instant kill + wipe |
| **Canary Protocol** | No user activity for N hours → auto-wipe |
| **Self-Destruct Timer** | Per-message configurable (30s, 5m, 1h, 24h) |
| **Offline Outbox** | Messages queued locally, sent on peer reconnect |

---

## Installation

### Prerequisites
- Python 3.11+
- Rust (latest stable): `curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh`
- Tor: see platform instructions below
- `maturin`: `pip install maturin`

### 1. Clone & setup Python environment
```bash
git clone https://github.com/MattiaAlessi/Nebulae.git
cd nebulae

python -m venv venv
source venv/bin/activate        # Linux/macOS
# or: venv\Scripts\activate     # Windows

pip install -r requirements.txt
```

### 2. Build Rust crypto engine
```bash
cd p2p_crypto
maturin build --release
pip install target/wheels/p2p_crypto-*.whl
cd ..
```

### 3. Install Tor

**Linux (Debian/Ubuntu)**
```bash
sudo apt install tor
sudo systemctl start tor
```

**macOS**
```bash
brew install tor && brew services start tor
```

**Windows**
Download [Tor Expert Bundle](https://www.torproject.org/download/tor/) and run `tor.exe`.

---

## Usage

### Graphical Interface (recommended)
```bash
python gui.py
```

### Command Line Interface
```bash
python main.py
```

**CLI Commands:**
| Command | Description |
|---|---|
| `/connect <onion>` | Connect to a peer |
| `/add <nick> <onion>` | Add a contact |
| `/contacts` | List all contacts |
| `/peers` | List connected peers |
| `/chat <onion>` | Open interactive chat |
| `/history <onion> [n]` | Show last N messages |
| `/canary <hours>` | Enable dead-man's switch |
| `/wipe` | Secure wipe all data |
| `/panic` | Instant destroy |
| `/exit` | Quit |

### Build standalone executables
```bash
# GUI
pyinstaller --onefile --windowed --name NEBULAE_GUI \
  --add-data "p2p_crypto/target/release/p2p_crypto.pyd;." gui.py

# CLI
pyinstaller --onefile --console --name NEBULAE_CLI \
  --add-data "p2p_crypto/target/release/p2p_crypto.pyd;." main.py
```

---

## First Run

1. Launch the app — it detects no identity and enters **Setup mode**
2. Enter a **Real Password** (your actual password)
3. Enter a **Decoy Password** (opens fake database under coercion)
4. Your identity is generated: Ed25519 + X25519 + Kyber-768 keypair
5. A v3 hidden service is created — you receive a `.onion` address
6. Share your `.onion` with trusted contacts out-of-band

---

## Project Structure

```
nebulae/
├── p2p_crypto/              # Rust cryptographic engine (PyO3)
│   ├── src/lib.rs           # All crypto primitives
│   └── Cargo.toml           # Dependencies: ring, pqcrypto-kyber, zeroize…
├── core/
│   ├── app.py               # Top-level application orchestrator
│   ├── crypto_manager.py    # Python crypto wrapper (sessions, identity, dual-pw)
│   ├── network.py           # Async P2P node, Tor controller, chaff, outbox, canary
│   └── database.py          # SQLCipher store, amnesic mode, blind index, secure wipe
├── gui.py                   # Tkinter GUI (cyberpunk dark theme)
├── main.py                  # Rich CLI interface
├── requirements.txt
└── README.md
```

---

## Cryptographic Design Details

### Key Derivation Chain
```
Master Password
      │
      ▼ PBKDF2-SHA512 (600,000 iterations + random salt)
Master Key (32 bytes)
      │
      ├──▶ BLAKE3(Master Key) → HMAC-SHA3 contact index key
      └──▶ ChaCha20-Poly1305 → local database encryption key

Per-session (X3DH + Double Ratchet):
X25519_shared || Kyber768_shared
      │
      ▼ BLAKE3
Combined Shared Secret (32 bytes)
      │
      ▼ HKDF-SHA256
Root Key → Chain Key → Message Key (destroyed after use)
```

### Wire Protocol
```
[4B length][1B msg_type][payload]

Types: HANDSHAKE(0x01) MESSAGE(0x02) CHAFF(0x03)
       PING(0x04) PONG(0x05) ANNOUNCE(0x06)
       FILE_CHUNK(0x07) CANARY_ACK(0x08) TYPING_IND(0x0A)
```

---

## Security Threat Model

NEBULAE is designed to resist:
- ✅ Network-level surveillance (Tor + padding)
- ✅ Physical device seizure (encrypted DB + amnesic mode + dual-password)
- ✅ Forward secrecy attacks (Double Ratchet)
- ✅ Future quantum computers (ML-KEM-768 / Kyber)
- ✅ Memory forensics (Rust zeroize, Python ctypes wipe)
- ✅ Contact graph analysis (HMAC blind index)
- ✅ Coercive disclosure (decoy database)
- ✅ Replay attacks (UUID tracking + timestamp validation)

NEBULAE does **not** protect against:
- ❌ Compromised endpoint (keylogger, malware on your device)
- ❌ Social engineering
- ❌ Side-channel attacks at hardware level

---

## Roadmap (from FUTURE_DEVELOPMENT.md)

- [ ] DHT peer discovery (Kademlia)
- [ ] NAT traversal / STUN / TURN
- [ ] Voice/Video over WebRTC
- [ ] Slint native GUI (replacing Tkinter)
- [ ] Landlock / AppSandbox OS-level sandboxing
- [ ] Vanguards-next integration (guard node protection)
- [ ] IPv6 full support
- [ ] Bot API

---

## License

MIT License — see `LICENSE` file.

## Disclaimer

This software is provided for educational, research, and legitimate privacy purposes.  
Users are solely responsible for compliance with applicable laws in their jurisdiction.  
The authors assume no liability for misuse.

---

*© 2026 NEBULAE Contributors. Built for privacy, not for crime.*
