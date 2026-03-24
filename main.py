"""
NEBULAE – Command Line Interface
Rich terminal UI with full access to all features.
"""
from __future__ import annotations

import sys
import threading
import time
import getpass
from pathlib import Path

try:
    from rich.console import Console
    from rich.prompt import Prompt, Confirm
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    from rich.live import Live
    from rich.layout import Layout
    from rich import print as rprint
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

console = Console() if HAS_RICH else None

BANNER = r"""
[cyan]
  ███╗   ██╗███████╗██████╗ ██╗   ██╗██╗      █████╗ ███████╗
  ████╗  ██║██╔════╝██╔══██╗██║   ██║██║     ██╔══██╗██╔════╝
  ██╔██╗ ██║█████╗  ██████╔╝██║   ██║██║     ███████║█████╗  
  ██║╚██╗██║██╔══╝  ██╔══██╗██║   ██║██║     ██╔══██║██╔══╝  
  ██║ ╚████║███████╗██████╔╝╚██████╔╝███████╗██║  ██║███████╗
  ╚═╝  ╚═══╝╚══════╝╚═════╝  ╚═════╝ ╚══════╝╚═╝  ╚═╝╚══════╝
[/cyan]
[dim]  P2P · TOR · POST-QUANTUM ENCRYPTED MESSENGER[/dim]
"""

HELP = """
[cyan]Commands:[/cyan]
  [green]/connect[/green] [dim]<onion>[/dim]          Connect to a peer
  [green]/add[/green] [dim]<nick> <onion>[/dim]       Add contact
  [green]/contacts[/green]               List contacts  
  [green]/peers[/green]                  List connected peers
  [green]/chat[/green] [dim]<onion>[/dim]             Open chat with peer
  [green]/history[/green] [dim]<onion> [limit][/dim]  View chat history
  [green]/canary[/green] [dim]<hours>[/dim]           Enable dead-man's switch
  [green]/wipe[/green]                   Secure wipe ALL data
  [green]/panic[/green]                  Instant panic destroy
  [green]/status[/green]                 Node status
  [green]/help[/green]                   Show this help
  [green]/exit[/green]                   Quit

[dim]In chat mode, type message and press Enter to send. /back to return.[/dim]
"""


class NEBULAECLI:
    def __init__(self):
        self.app = None
        self._current_chat: str | None = None
        self._messages: list = []
        self._lock = threading.Lock()

    def _print(self, msg: str):
        if HAS_RICH:
            console.print(msg)
        else:
            print(msg)

    def run(self):
        if HAS_RICH:
            console.print(BANNER)
        else:
            print("=== NEBULAE ===")

        data_dir = Path.home() / ".nebulae" / "data"
        has_identity = (data_dir / "identity.a.enc").exists()

        if not has_identity:
            self._setup()
        else:
            self._login()

        self._main_loop()

    def _setup(self):
        self._print("[yellow]First run – creating identity[/yellow]")
        real_pw  = getpass.getpass("Real password: ")
        decoy_pw = getpass.getpass("Decoy password: ")
        confirm  = getpass.getpass("Confirm decoy: ")

        if decoy_pw != confirm:
            self._print("[red]Decoy passwords don't match[/red]")
            sys.exit(1)

        from core.app import NEBULAEApp
        tmp = NEBULAEApp(lambda *a: None, lambda s: None)
        tmp.first_run_setup(real_pw, decoy_pw)
        self._print("[green]✓ Identity created[/green]")
        self._login()

    def _login(self):
        password = getpass.getpass("Master Password: ")
        amnesic  = input("Amnesic mode? (y/N): ").lower() == "y"

        from core.app import NEBULAEApp
        self.app = NEBULAEApp(
            message_callback=self._on_message,
            status_callback=lambda s: self._print(f"[dim]{s}[/dim]"),
            amnesic_mode=amnesic,
        )
        ok = self.app.login(password)
        if not ok:
            self._print("[red]✗ Wrong password[/red]")
            sys.exit(1)
        self._print(f"[green]✓ Online: {self.app.node.onion_address}[/green]")

    def _on_message(self, peer_id: str, nickname: str, body: str):
        with self._lock:
            self._messages.append((peer_id, nickname, body, time.time()))
        if self._current_chat == peer_id or self._current_chat is None:
            self._print(f"\n[purple]← {nickname}[/purple] {body}")

    def _main_loop(self):
        self._print(HELP)
        while True:
            try:
                if HAS_RICH:
                    line = Prompt.ask("[cyan]>[/cyan]").strip()
                else:
                    line = input("\n[nebulae]> ").strip()
            except (EOFError, KeyboardInterrupt):
                self._do_exit()
                break

            if not line:
                continue

            parts = line.split()
            cmd   = parts[0].lower()

            if cmd == "/exit":       self._do_exit(); break
            elif cmd == "/help":     self._print(HELP)
            elif cmd == "/connect":  self._cmd_connect(parts[1:])
            elif cmd == "/add":      self._cmd_add(parts[1:])
            elif cmd == "/contacts": self._cmd_contacts()
            elif cmd == "/peers":    self._cmd_peers()
            elif cmd == "/chat":     self._cmd_chat(parts[1:])
            elif cmd == "/history":  self._cmd_history(parts[1:])
            elif cmd == "/canary":   self._cmd_canary(parts[1:])
            elif cmd == "/status":   self._cmd_status()
            elif cmd == "/wipe":     self._cmd_wipe()
            elif cmd == "/panic":    self.app.panic_wipe()
            else:
                self._print(f"[red]Unknown command: {cmd}[/red]")

    def _cmd_connect(self, args):
        if not args:
            self._print("[red]Usage: /connect <onion>[/red]"); return
        ok = self.app.connect_peer(args[0])
        self._print(f"{'[green]✓ Connected' if ok else '[red]✗ Failed'}[/]")

    def _cmd_add(self, args):
        if len(args) < 2:
            self._print("[red]Usage: /add <nick> <onion>[/red]"); return
        self.app.add_contact(args[1], args[0])
        self._print(f"[green]✓ Contact added: {args[0]}[/green]")

    def _cmd_contacts(self):
        contacts = self.app.get_contacts()
        if HAS_RICH:
            t = Table(title="Contacts", style="cyan")
            t.add_column("Nickname"); t.add_column("Onion")
            for c in contacts:
                t.add_row(c.get("nickname", "?"), c.get("onion", "?"))
            console.print(t)
        else:
            for c in contacts:
                print(f"  {c.get('nickname')} — {c.get('onion')}")

    def _cmd_peers(self):
        peers = self.app.get_peers()
        if HAS_RICH:
            t = Table(title="Connected Peers", style="cyan")
            t.add_column("ID"); t.add_column("Onion"); t.add_column("Session")
            for p in peers:
                t.add_row(p["id"], p["onion"],
                          "[green]✓[/green]" if p["session"] else "[red]✗[/red]")
            console.print(t)
        else:
            for p in peers:
                print(f"  {p['id']} — {p['onion']}")

    def _cmd_chat(self, args):
        if not args:
            self._print("[red]Usage: /chat <onion>[/red]"); return
        onion = args[0]
        self._current_chat = onion
        self._print(f"[cyan]─── Chat with {onion} ───[/cyan]")
        self._print("[dim]Type message + Enter to send. /back to return.[/dim]")
        while True:
            try:
                msg = input("  > ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if msg == "/back": break
            if msg:
                self.app.send_message(onion, msg)
        self._current_chat = None

    def _cmd_history(self, args):
        if not args:
            self._print("[red]Usage: /history <onion> [limit][/red]"); return
        limit = int(args[1]) if len(args) > 1 else 50
        history = self.app.get_history(args[0], limit)
        for m in history:
            arrow = "[cyan]→[/cyan]" if m["direction"] == "out" else "[purple]←[/purple]"
            self._print(f"  {arrow} {m['body']}")

    def _cmd_canary(self, args):
        hours = float(args[0]) if args else 48
        self.app.enable_canary(hours)
        self._print(f"[yellow]⚠ Canary set: {hours}h timeout[/yellow]")

    def _cmd_status(self):
        onion = self.app.node.onion_address if self.app.node else "N/A"
        peers = len(self.app.get_peers())
        self._print(f"[cyan]Onion:[/cyan] {onion}")
        self._print(f"[cyan]Peers:[/cyan] {peers}")

    def _cmd_wipe(self):
        confirm = input("Type WIPE to confirm: ")
        if confirm == "WIPE":
            self.app.panic_wipe()

    def _do_exit(self):
        self._print("[dim]Shutting down…[/dim]")
        if self.app:
            self.app.shutdown()
        sys.exit(0)


if __name__ == "__main__":
    NEBULAECLI().run()
