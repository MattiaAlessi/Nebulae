import PyInstaller.__main__
import os

# Percorsi assoluti basati sulla tua struttura
venv_path = r"C:\Users\matti\OneDrive\Desktop\Programmazione\Compiti\Progetto_chat_TOR\NEBULAE\venv"
site_packages = os.path.join(venv_path, "Lib", "site-packages")
crypto_pyd = os.path.join(site_packages, "p2p_crypto", "p2p_crypto.cp311-win_amd64.pyd")

PyInstaller.__main__.run([
    'gui.py',
    '--onefile',
    '--windowed',
    '--name=NEBULAE_GUI',
    f'--paths={site_packages}',       # Forza PyInstaller a guardare qui per stem, rich, etc.
    f'--add-data={crypto_pyd};.',     # Inserisce il modulo Rust
    '--clean',
    '--noconfirm'
])