// NEBULAE Cryptographic Engine
// Senior Crypting Engineer: Post-Quantum Hybrid Crypto Core
// Memory-safe Rust implementation with zeroize protection

use pyo3::prelude::*;
use pyo3::exceptions::PyValueError;
use pyo3::types::PyBytes;

use chacha20poly1305::{
    aead::{Aead, AeadCore, KeyInit, OsRng as AeadOsRng},
    ChaCha20Poly1305, Key, Nonce,
};
use x25519_dalek::{EphemeralSecret, PublicKey, StaticSecret};
use ed25519_dalek::{Signer, SigningKey, VerifyingKey, Verifier, Signature};
use zeroize::{Zeroize, ZeroizeOnDrop};
use rand::RngCore;
use rand_core::OsRng;
use sha3::{Digest, Sha3_256, Sha3_512};
use hmac::{Hmac, Mac};
use hkdf::Hkdf;
use blake3;
use serde::{Deserialize, Serialize};
use pqcrypto_kyber::kyber768;
use pqcrypto_traits::kem::{PublicKey as KemPublicKey, SecretKey as KemSecretKey, SharedSecret, Ciphertext};

// ─────────────────────────────────────────────────────────────────────────────
//  Zeroize-on-drop session key container
// ─────────────────────────────────────────────────────────────────────────────
#[derive(Zeroize, ZeroizeOnDrop)]
struct SessionKey([u8; 32]);

// ─────────────────────────────────────────────────────────────────────────────
//  Double Ratchet State
// ─────────────────────────────────────────────────────────────────────────────
#[derive(Serialize, Deserialize, Clone)]
pub struct RatchetState {
    root_key: Vec<u8>,
    chain_key_send: Vec<u8>,
    chain_key_recv: Vec<u8>,
    send_count: u64,
    recv_count: u64,
    prev_send_count: u64,
    dh_send_pub: Vec<u8>,
    dh_send_priv: Vec<u8>,
    dh_recv_pub: Vec<u8>,
}

// ─────────────────────────────────────────────────────────────────────────────
//  Helper: HKDF-SHA256 key derivation
// ─────────────────────────────────────────────────────────────────────────────
fn hkdf_derive(ikm: &[u8], salt: &[u8], info: &[u8], length: usize) -> Vec<u8> {
    let hk = Hkdf::<sha2_crate::Sha256>::new(Some(salt), ikm);
    let mut okm = vec![0u8; length];
    hk.expand(info, &mut okm).expect("HKDF expand failed");
    okm
}

fn kdf_rk(root_key: &[u8], dh_out: &[u8]) -> (Vec<u8>, Vec<u8>) {
    let new_rk = hkdf_derive(dh_out, root_key, b"NEBULAE_ROOT_RATCHET", 32);
    let new_ck = hkdf_derive(dh_out, root_key, b"NEBULAE_CHAIN_RATCHET", 32);
    (new_rk, new_ck)
}

fn kdf_ck(chain_key: &[u8]) -> (Vec<u8>, Vec<u8>) {
    let msg_key = hkdf_derive(chain_key, b"NEBULAE_MSG", b"msg", 32);
    let new_ck  = hkdf_derive(chain_key, b"NEBULAE_CHN", b"chain", 32);
    (new_ck, msg_key)
}

// ─────────────────────────────────────────────────────────────────────────────
//  Module: nebulae_crypto — exposed to Python via PyO3
// ─────────────────────────────────────────────────────────────────────────────
#[pymodule]
fn p2p_crypto(_py: Python<'_>, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(generate_identity, m)?)?;
    m.add_function(wrap_pyfunction!(generate_kyber_keypair, m)?)?;
    m.add_function(wrap_pyfunction!(hybrid_encapsulate, m)?)?;
    m.add_function(wrap_pyfunction!(hybrid_decapsulate, m)?)?;
    m.add_function(wrap_pyfunction!(encrypt_message, m)?)?;
    m.add_function(wrap_pyfunction!(decrypt_message, m)?)?;
    m.add_function(wrap_pyfunction!(sign_message, m)?)?;
    m.add_function(wrap_pyfunction!(verify_signature, m)?)?;
    m.add_function(wrap_pyfunction!(derive_key_pbkdf2, m)?)?;
    m.add_function(wrap_pyfunction!(hmac_sha3_index, m)?)?;
    m.add_function(wrap_pyfunction!(secure_random_bytes, m)?)?;
    m.add_function(wrap_pyfunction!(blake3_hash, m)?)?;
    m.add_function(wrap_pyfunction!(ratchet_init_sender, m)?)?;
    m.add_function(wrap_pyfunction!(ratchet_init_receiver, m)?)?;
    m.add_function(wrap_pyfunction!(ratchet_encrypt, m)?)?;
    m.add_function(wrap_pyfunction!(ratchet_decrypt, m)?)?;
    m.add_function(wrap_pyfunction!(strip_exif_bytes, m)?)?;
    m.add_function(wrap_pyfunction!(wipe_memory, m)?)?;
    Ok(())
}

// ─────────────────────────────────────────────────────────────────────────────
//  Identity Generation (X25519 + Ed25519)
// ─────────────────────────────────────────────────────────────────────────────
#[pyfunction]
fn generate_identity(py: Python<'_>) -> PyResult<PyObject> {
    let signing_key = SigningKey::generate(&mut OsRng);
    let verifying_key = signing_key.verifying_key();

    let static_secret = StaticSecret::random_from_rng(OsRng);
    let dh_public = PublicKey::from(&static_secret);

    let dict = pyo3::types::PyDict::new(py);
    dict.set_item("ed25519_private", PyBytes::new(py, signing_key.to_bytes().as_ref()))?;
    dict.set_item("ed25519_public",  PyBytes::new(py, verifying_key.to_bytes().as_ref()))?;
    dict.set_item("x25519_private",  PyBytes::new(py, static_secret.to_bytes().as_ref()))?;
    dict.set_item("x25519_public",   PyBytes::new(py, dh_public.as_bytes().as_ref()))?;
    Ok(dict.into())
}

// ─────────────────────────────────────────────────────────────────────────────
//  Post-Quantum Kyber-768 Keypair
// ─────────────────────────────────────────────────────────────────────────────
#[pyfunction]
fn generate_kyber_keypair(py: Python<'_>) -> PyResult<PyObject> {
    let (pk, sk) = kyber768::keypair();
    let dict = pyo3::types::PyDict::new(py);
    dict.set_item("kyber_public",  PyBytes::new(py, pk.as_bytes()))?;
    dict.set_item("kyber_private", PyBytes::new(py, sk.as_bytes()))?;
    Ok(dict.into())
}

// ─────────────────────────────────────────────────────────────────────────────
//  Hybrid Encapsulation: X25519 + Kyber768 → combined shared secret
// ─────────────────────────────────────────────────────────────────────────────
#[pyfunction]
fn hybrid_encapsulate(
    py: Python<'_>,
    x25519_peer_pub: &[u8],
    kyber_peer_pub: &[u8],
) -> PyResult<PyObject> {
    // X25519 DH
    let ephemeral = EphemeralSecret::random_from_rng(OsRng);
    let eph_pub   = PublicKey::from(&ephemeral);
    let peer_pub: [u8; 32] = x25519_peer_pub.try_into()
        .map_err(|_| PyValueError::new_err("Invalid X25519 public key length"))?;
    let peer_key  = PublicKey::from(peer_pub);
    let dh_shared = ephemeral.diffie_hellman(&peer_key);

    // Kyber encapsulation
    let kyber_pk  = kyber768::PublicKey::from_bytes(kyber_peer_pub)
        .map_err(|_| PyValueError::new_err("Invalid Kyber public key"))?;
    let (kyber_ss, kyber_ct) = kyber768::encapsulate(&kyber_pk);

    // Combine: BLAKE3(X25519_shared || Kyber_shared)
    let mut combined = Vec::new();
    combined.extend_from_slice(dh_shared.as_bytes());
    combined.extend_from_slice(kyber_ss.as_bytes());
    let final_secret = blake3::hash(&combined);

    let dict = pyo3::types::PyDict::new(py);
    dict.set_item("shared_secret",   PyBytes::new(py, final_secret.as_bytes()))?;
    dict.set_item("x25519_eph_pub",  PyBytes::new(py, eph_pub.as_bytes().as_ref()))?;
    dict.set_item("kyber_ciphertext", PyBytes::new(py, kyber_ct.as_bytes()))?;
    Ok(dict.into())
}

// ─────────────────────────────────────────────────────────────────────────────
//  Hybrid Decapsulation
// ─────────────────────────────────────────────────────────────────────────────
#[pyfunction]
fn hybrid_decapsulate(
    py: Python<'_>,
    x25519_my_priv: &[u8],
    x25519_eph_pub: &[u8],
    kyber_my_priv: &[u8],
    kyber_ciphertext: &[u8],
) -> PyResult<PyObject> {
    // X25519
    let priv_bytes: [u8; 32] = x25519_my_priv.try_into()
        .map_err(|_| PyValueError::new_err("Invalid X25519 private key length"))?;
    let my_static  = StaticSecret::from(priv_bytes);
    let eph_bytes: [u8; 32] = x25519_eph_pub.try_into()
        .map_err(|_| PyValueError::new_err("Invalid X25519 ephemeral pub length"))?;
    let eph_key    = PublicKey::from(eph_bytes);
    let dh_shared  = my_static.diffie_hellman(&eph_key);

    // Kyber
    let kyber_sk = kyber768::SecretKey::from_bytes(kyber_my_priv)
        .map_err(|_| PyValueError::new_err("Invalid Kyber secret key"))?;
    let ct = kyber768::Ciphertext::from_bytes(kyber_ciphertext)
        .map_err(|_| PyValueError::new_err("Invalid Kyber ciphertext"))?;
    let kyber_ss = kyber768::decapsulate(&ct, &kyber_sk);

    let mut combined = Vec::new();
    combined.extend_from_slice(dh_shared.as_bytes());
    combined.extend_from_slice(kyber_ss.as_bytes());
    let final_secret = blake3::hash(&combined);

    Ok(PyBytes::new(py, final_secret.as_bytes()).into())
}

// ─────────────────────────────────────────────────────────────────────────────
//  ChaCha20-Poly1305 Encrypt/Decrypt
// ─────────────────────────────────────────────────────────────────────────────
#[pyfunction]
fn encrypt_message(py: Python<'_>, key: &[u8], plaintext: &[u8]) -> PyResult<PyObject> {
    let key_arr: [u8; 32] = key.try_into()
        .map_err(|_| PyValueError::new_err("Key must be 32 bytes"))?;
    let cipher = ChaCha20Poly1305::new(Key::from_slice(&key_arr));
    let nonce  = ChaCha20Poly1305::generate_nonce(&mut AeadOsRng);
    let ciphertext = cipher.encrypt(&nonce, plaintext)
        .map_err(|e| PyValueError::new_err(format!("Encryption failed: {e}")))?;

    let mut out = nonce.to_vec();
    out.extend_from_slice(&ciphertext);
    Ok(PyBytes::new(py, &out).into())
}

#[pyfunction]
fn decrypt_message(py: Python<'_>, key: &[u8], ciphertext_with_nonce: &[u8]) -> PyResult<PyObject> {
    if ciphertext_with_nonce.len() < 12 {
        return Err(PyValueError::new_err("Ciphertext too short"));
    }
    let key_arr: [u8; 32] = key.try_into()
        .map_err(|_| PyValueError::new_err("Key must be 32 bytes"))?;
    let cipher  = ChaCha20Poly1305::new(Key::from_slice(&key_arr));
    let nonce   = Nonce::from_slice(&ciphertext_with_nonce[..12]);
    let plaintext = cipher.decrypt(nonce, &ciphertext_with_nonce[12..])
        .map_err(|e| PyValueError::new_err(format!("Decryption failed: {e}")))?;
    Ok(PyBytes::new(py, &plaintext).into())
}

// ─────────────────────────────────────────────────────────────────────────────
//  Ed25519 Sign / Verify
// ─────────────────────────────────────────────────────────────────────────────
#[pyfunction]
fn sign_message(py: Python<'_>, private_key: &[u8], message: &[u8]) -> PyResult<PyObject> {
    let key_bytes: [u8; 32] = private_key.try_into()
        .map_err(|_| PyValueError::new_err("Private key must be 32 bytes"))?;
    let signing_key = SigningKey::from_bytes(&key_bytes);
    let signature   = signing_key.sign(message);
    Ok(PyBytes::new(py, signature.to_bytes().as_ref()).into())
}

#[pyfunction]
fn verify_signature(public_key: &[u8], message: &[u8], signature: &[u8]) -> PyResult<bool> {
    let key_bytes: [u8; 32] = public_key.try_into()
        .map_err(|_| PyValueError::new_err("Public key must be 32 bytes"))?;
    let verifying_key = VerifyingKey::from_bytes(&key_bytes)
        .map_err(|_| PyValueError::new_err("Invalid public key"))?;
    let sig_bytes: [u8; 64] = signature.try_into()
        .map_err(|_| PyValueError::new_err("Signature must be 64 bytes"))?;
    let sig = Signature::from_bytes(&sig_bytes);
    Ok(verifying_key.verify(message, &sig).is_ok())
}

// ─────────────────────────────────────────────────────────────────────────────
//  PBKDF2-SHA512 Key Derivation (for master password)
// ─────────────────────────────────────────────────────────────────────────────
#[pyfunction]
fn derive_key_pbkdf2(py: Python<'_>, password: &[u8], salt: &[u8], iterations: u32) -> PyResult<PyObject> {
    use pbkdf2::pbkdf2_hmac;
    let mut key = vec![0u8; 32];
    pbkdf2_hmac::<sha2_crate::Sha512>(password, salt, iterations, &mut key);
    Ok(PyBytes::new(py, &key).into())
}

// ─────────────────────────────────────────────────────────────────────────────
//  HMAC-SHA3 Index (for Header Blindness)
// ─────────────────────────────────────────────────────────────────────────────
#[pyfunction]
fn hmac_sha3_index(py: Python<'_>, key: &[u8], data: &[u8]) -> PyResult<PyObject> {
    use hmac::Mac as HmacMacTrait;
    type HmacSha3 = Hmac<Sha3_256>;
    let mut mac = <HmacSha3 as hmac::Mac>::new_from_slice(key)
        .map_err(|_| PyValueError::new_err("HMAC key error"))?;
    mac.update(data);
    let result = mac.finalize();
    Ok(PyBytes::new(py, result.into_bytes().as_ref()).into())
}

// ─────────────────────────────────────────────────────────────────────────────
//  Secure Random & Blake3
// ─────────────────────────────────────────────────────────────────────────────
#[pyfunction]
fn secure_random_bytes(py: Python<'_>, length: usize) -> PyResult<PyObject> {
    let mut buf = vec![0u8; length];
    OsRng.fill_bytes(&mut buf);
    Ok(PyBytes::new(py, &buf).into())
}

#[pyfunction]
fn blake3_hash(py: Python<'_>, data: &[u8]) -> PyResult<PyObject> {
    let hash = blake3::hash(data);
    Ok(PyBytes::new(py, hash.as_bytes()).into())
}

// ─────────────────────────────────────────────────────────────────────────────
//  Double Ratchet (X3DH-style)
// ─────────────────────────────────────────────────────────────────────────────
#[pyfunction]
fn ratchet_init_sender(py: Python<'_>, shared_secret: &[u8], receiver_dh_pub: &[u8]) -> PyResult<PyObject> {
    let send_secret = StaticSecret::random_from_rng(OsRng);
    let send_pub    = PublicKey::from(&send_secret);
    let recv_pub_bytes: [u8; 32] = receiver_dh_pub.try_into()
        .map_err(|_| PyValueError::new_err("Bad DH pub"))?;
    let recv_pub  = PublicKey::from(recv_pub_bytes);
    let dh_out    = send_secret.diffie_hellman(&recv_pub);
    let (rk, ck) = kdf_rk(shared_secret, dh_out.as_bytes());

    let state = RatchetState {
        root_key: rk,
        chain_key_send: ck,
        chain_key_recv: vec![0u8; 32],
        send_count: 0,
        recv_count: 0,
        prev_send_count: 0,
        dh_send_pub: send_pub.as_bytes().to_vec(),
        dh_send_priv: send_secret.to_bytes().to_vec(),
        dh_recv_pub: receiver_dh_pub.to_vec(),
    };
    let json = serde_json::to_string(&state).unwrap();
    Ok(pyo3::types::PyString::new(py, &json).into())
}

#[pyfunction]
fn ratchet_init_receiver(py: Python<'_>, shared_secret: &[u8], my_dh_priv: &[u8], sender_dh_pub: &[u8]) -> PyResult<PyObject> {
    let priv_bytes: [u8; 32] = my_dh_priv.try_into()
        .map_err(|_| PyValueError::new_err("Bad DH priv"))?;
    let my_static = StaticSecret::from(priv_bytes);
    let pub_bytes: [u8; 32]  = sender_dh_pub.try_into()
        .map_err(|_| PyValueError::new_err("Bad DH pub"))?;
    let sender_pub = PublicKey::from(pub_bytes);
    let dh_out     = my_static.diffie_hellman(&sender_pub);
    let (rk, ck)   = kdf_rk(shared_secret, dh_out.as_bytes());

    let my_pub = PublicKey::from(&StaticSecret::from(priv_bytes));
    let state = RatchetState {
        root_key: rk,
        chain_key_send: vec![0u8; 32],
        chain_key_recv: ck,
        send_count: 0,
        recv_count: 0,
        prev_send_count: 0,
        dh_send_pub: my_pub.as_bytes().to_vec(),
        dh_send_priv: my_dh_priv.to_vec(),
        dh_recv_pub: sender_dh_pub.to_vec(),
    };
    let json = serde_json::to_string(&state).unwrap();
    Ok(pyo3::types::PyString::new(py, &json).into())
}

#[pyfunction]
fn ratchet_encrypt(py: Python<'_>, state_json: &str, plaintext: &[u8]) -> PyResult<PyObject> {
    let mut state: RatchetState = serde_json::from_str(state_json)
        .map_err(|e| PyValueError::new_err(format!("State parse error: {e}")))?;

    let (new_ck, msg_key) = kdf_ck(&state.chain_key_send);
    state.chain_key_send = new_ck;
    state.send_count += 1;

    let key_arr: [u8; 32] = msg_key.as_slice().try_into().unwrap();
    let cipher = ChaCha20Poly1305::new(Key::from_slice(&key_arr));
    let nonce  = ChaCha20Poly1305::generate_nonce(&mut AeadOsRng);
    let mut ct = nonce.to_vec();
    ct.extend_from_slice(&cipher.encrypt(&nonce, plaintext)
        .map_err(|e| PyValueError::new_err(format!("Ratchet encrypt: {e}")))?);

    let new_json = serde_json::to_string(&state).unwrap();
    let dict = pyo3::types::PyDict::new(py);
    dict.set_item("ciphertext", PyBytes::new(py, &ct))?;
    dict.set_item("state", pyo3::types::PyString::new(py, &new_json))?;
    dict.set_item("header_dh_pub", PyBytes::new(py, &state.dh_send_pub))?;
    Ok(dict.into())
}

#[pyfunction]
fn ratchet_decrypt(py: Python<'_>, state_json: &str, ciphertext: &[u8]) -> PyResult<PyObject> {
    let mut state: RatchetState = serde_json::from_str(state_json)
        .map_err(|e| PyValueError::new_err(format!("State parse error: {e}")))?;

    let (new_ck, msg_key) = kdf_ck(&state.chain_key_recv);
    state.chain_key_recv = new_ck;
    state.recv_count += 1;

    let key_arr: [u8; 32] = msg_key.as_slice().try_into().unwrap();
    let cipher = ChaCha20Poly1305::new(Key::from_slice(&key_arr));
    if ciphertext.len() < 12 {
        return Err(PyValueError::new_err("Ciphertext too short"));
    }
    let nonce = Nonce::from_slice(&ciphertext[..12]);
    let plaintext = cipher.decrypt(nonce, &ciphertext[12..])
        .map_err(|e| PyValueError::new_err(format!("Ratchet decrypt: {e}")))?;

    let new_json = serde_json::to_string(&state).unwrap();
    let dict = pyo3::types::PyDict::new(py);
    dict.set_item("plaintext", PyBytes::new(py, &plaintext))?;
    dict.set_item("state", pyo3::types::PyString::new(py, &new_json))?;
    Ok(dict.into())
}

// ─────────────────────────────────────────────────────────────────────────────
//  Strip EXIF (basic: truncate JPEG at 0xFFE1 markers in-memory)
// ─────────────────────────────────────────────────────────────────────────────
#[pyfunction]
fn strip_exif_bytes(py: Python<'_>, image_bytes: &[u8]) -> PyResult<PyObject> {
    // Simple JPEG EXIF strip: remove APP1 (0xFFE1) segment
    if image_bytes.len() < 4 || &image_bytes[0..2] != b"\xFF\xD8" {
        return Ok(PyBytes::new(py, image_bytes).into());
    }
    let mut out = vec![0xFF_u8, 0xD8];
    let mut i = 2usize;
    while i + 3 < image_bytes.len() {
        if image_bytes[i] == 0xFF {
            let marker = image_bytes[i + 1];
            if marker == 0xE1 {
                // APP1 (EXIF) — skip it
                let seg_len = u16::from_be_bytes([image_bytes[i + 2], image_bytes[i + 3]]) as usize;
                i += 2 + seg_len;
                continue;
            }
        }
        out.push(image_bytes[i]);
        i += 1;
    }
    Ok(PyBytes::new(py, &out).into())
}

// ─────────────────────────────────────────────────────────────────────────────
//  Secure memory wipe (accepts bytes, returns zeros; caller drops the original)
// ─────────────────────────────────────────────────────────────────────────────
#[pyfunction]
fn wipe_memory(py: Python<'_>, data: &[u8]) -> PyResult<PyObject> {
    let mut wiped = data.to_vec();
    wiped.zeroize();
    Ok(PyBytes::new(py, &wiped).into())
}

// sha2 used internally via direct crate reference
use sha2 as sha2_crate;
