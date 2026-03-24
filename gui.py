"""
NEBULAE – GUI
Senior Game Designer aesthetic: cyberpunk dark, neon accents, crisp typography.
Built with tkinter + ttk for zero external GUI dependency.
"""
from __future__ import annotations

import os
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from pathlib import Path
from typing import Optional, Dict, List, Callable
import queue

# ─────────────────────────────────────────────────────────────────────────────
#  Palette – NEBULAE cyberpunk color system
# ─────────────────────────────────────────────────────────────────────────────
C = {
    "bg_deep":      "#080b12",   # deepest background
    "bg_panel":     "#0d1120",   # panel background
    "bg_card":      "#111827",   # card / widget bg
    "bg_input":     "#0f1521",   # input fields
    "border":       "#1e2d4a",   # default border
    "border_accent":"#00e5ff",   # cyan accent border
    "accent_cyan":  "#00e5ff",   # primary accent
    "accent_purple":"#a855f7",   # secondary accent
    "accent_green": "#22c55e",   # success / online
    "accent_red":   "#ef4444",   # danger / offline / panic
    "accent_amber": "#f59e0b",   # warning
    "text_primary": "#e2e8f0",   # primary text
    "text_secondary":"#64748b",  # muted text
    "text_accent":  "#00e5ff",   # accent text
    "text_dim":     "#334155",   # very dim
    "msg_out_bg":   "#0f2744",   # outbound message bubble
    "msg_in_bg":    "#1a0f33",   # inbound message bubble
    "msg_out_text": "#bae6fd",
    "msg_in_text":  "#ddd6fe",
    "scrollbar":    "#1e2d4a",
    "highlight":    "#00e5ff22",
}

FONT_MONO  = ("JetBrains Mono", 10) if sys.platform != "darwin" else ("Menlo", 11)
FONT_BODY  = ("Segoe UI", 10)       if sys.platform == "win32"  else ("SF Pro Text", 10) if sys.platform == "darwin" else ("Ubuntu", 10)
FONT_TITLE = ("Segoe UI Semibold", 12) if sys.platform == "win32" else ("SF Pro Display", 12)
FONT_LARGE = ("Segoe UI Bold", 16)  if sys.platform == "win32"  else ("SF Pro Display", 16, "bold")
FONT_SMALL = (FONT_BODY[0], 8)


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────
def ts_str(epoch: float) -> str:
    import datetime
    return datetime.datetime.fromtimestamp(epoch).strftime("%H:%M")


def apply_dark_style(root: tk.Tk) -> None:
    style = ttk.Style(root)
    style.theme_use("clam")

    style.configure(".", background=C["bg_panel"], foreground=C["text_primary"],
                    font=FONT_BODY, borderwidth=0, relief="flat")
    style.configure("TFrame",     background=C["bg_panel"])
    style.configure("TLabel",     background=C["bg_panel"], foreground=C["text_primary"])
    style.configure("TButton",    background=C["bg_card"],  foreground=C["accent_cyan"],
                    borderwidth=1, relief="solid", padding=(12, 6))
    style.map("TButton",
              background=[("active", C["border"])],
              foreground=[("active", "#ffffff")])
    style.configure("Accent.TButton", background=C["accent_cyan"], foreground=C["bg_deep"],
                    font=(FONT_BODY[0], 10, "bold"))
    style.map("Accent.TButton", background=[("active", "#00b8d4")])
    style.configure("Danger.TButton", background=C["accent_red"], foreground="#fff",
                    font=(FONT_BODY[0], 10, "bold"))
    style.configure("TEntry",     fieldbackground=C["bg_input"], foreground=C["text_primary"],
                    borderwidth=1, relief="solid", insertcolor=C["accent_cyan"])
    style.configure("TScrollbar", background=C["scrollbar"], troughcolor=C["bg_deep"],
                    borderwidth=0, arrowsize=0)
    style.configure("TSeparator", background=C["border"])


# ─────────────────────────────────────────────────────────────────────────────
#  Reusable widgets
# ─────────────────────────────────────────────────────────────────────────────
class NeonLabel(tk.Label):
    def __init__(self, parent, text, glow_color=None, **kw):
        color = glow_color or C["accent_cyan"]
        super().__init__(parent, text=text,
                         fg=color, bg=C["bg_panel"],
                         font=FONT_TITLE, **kw)


class SidebarButton(tk.Frame):
    """Contact list item with online indicator."""

    def __init__(self, parent, nickname, onion, is_online, on_click, **kw):
        super().__init__(parent, bg=C["bg_panel"], cursor="hand2", **kw)
        self.onion    = onion
        self.on_click = on_click
        self._selected = False

        self.indicator = tk.Label(self, width=2, bg=C["accent_green"] if is_online else C["text_dim"])
        self.indicator.pack(side="left", fill="y", padx=(0, 8))

        self.name_lbl = tk.Label(self, text=nickname, fg=C["text_primary"], bg=C["bg_panel"],
                                 font=FONT_BODY, anchor="w")
        self.name_lbl.pack(side="left", fill="x", expand=True)

        self.onion_lbl = tk.Label(self, text=onion[:20] + "…", fg=C["text_secondary"],
                                  bg=C["bg_panel"], font=FONT_SMALL, anchor="w")
        self.onion_lbl.pack(side="left", padx=(0, 8))

        for w in (self, self.indicator, self.name_lbl, self.onion_lbl):
            w.bind("<Button-1>", self._clicked)
            w.bind("<Enter>",    self._hover_in)
            w.bind("<Leave>",    self._hover_out)

    def _clicked(self, _=None): self.on_click(self.onion)
    def _hover_in(self, _=None):
        if not self._selected:
            self.configure(bg=C["bg_card"])
            for w in (self.name_lbl, self.onion_lbl): w.configure(bg=C["bg_card"])
    def _hover_out(self, _=None):
        if not self._selected:
            self.configure(bg=C["bg_panel"])
            for w in (self.name_lbl, self.onion_lbl): w.configure(bg=C["bg_panel"])

    def set_selected(self, selected: bool):
        self._selected = selected
        bg = C["bg_card"] if selected else C["bg_panel"]
        self.configure(bg=bg)
        for w in (self.name_lbl, self.onion_lbl): w.configure(bg=bg)
        self.name_lbl.configure(fg=C["accent_cyan"] if selected else C["text_primary"])

    def set_online(self, online: bool):
        self.indicator.configure(bg=C["accent_green"] if online else C["text_dim"])


class MessageBubble(tk.Frame):
    """Single chat message bubble."""

    def __init__(self, parent, body: str, direction: str, timestamp: float):
        super().__init__(parent, bg=C["bg_deep"])
        is_out = direction == "out"
        bubble_bg   = C["msg_out_bg"] if is_out else C["msg_in_bg"]
        bubble_fg   = C["msg_out_text"] if is_out else C["msg_in_text"]
        side        = "e" if is_out else "w"

        wrapper = tk.Frame(self, bg=C["bg_deep"])
        wrapper.pack(anchor=side, padx=16, pady=3)

        # Border effect via a slightly-larger frame
        border_frame = tk.Frame(wrapper,
                                bg=C["accent_cyan"] if is_out else C["accent_purple"],
                                padx=1, pady=1)
        border_frame.pack(anchor=side)

        inner = tk.Frame(border_frame, bg=bubble_bg, padx=12, pady=8)
        inner.pack()

        msg_txt = tk.Text(inner, wrap="word", bg=bubble_bg, fg=bubble_fg,
                          font=FONT_MONO, relief="flat", borderwidth=0,
                          state="normal", height=1, width=min(len(body), 60))
        msg_txt.insert("1.0", body)
        msg_txt.configure(state="disabled")
        lines = max(1, (len(body) // 58) + body.count("\n") + 1)
        msg_txt.configure(height=lines)
        msg_txt.pack()

        ts_lbl = tk.Label(inner, text=ts_str(timestamp),
                          fg=C["text_secondary"], bg=bubble_bg, font=FONT_SMALL)
        ts_lbl.pack(anchor="e")


# ─────────────────────────────────────────────────────────────────────────────
#  Login screen
# ─────────────────────────────────────────────────────────────────────────────
class LoginWindow(tk.Toplevel):
    def __init__(self, parent, on_login: Callable, on_setup: Callable, has_identity: bool):
        super().__init__(parent)
        self.on_login  = on_login
        self.on_setup  = on_setup
        self.configure(bg=C["bg_deep"])
        self.title("NEBULAE")
        self.geometry("420x520")
        self.resizable(False, False)
        self._build(has_identity)

    def _build(self, has_identity: bool):
        # Logo area
        header = tk.Frame(self, bg=C["bg_deep"], pady=30)
        header.pack(fill="x")

        title = tk.Label(header, text="◈ NEBULAE", fg=C["accent_cyan"],
                         bg=C["bg_deep"], font=(FONT_BODY[0], 28, "bold"))
        title.pack()
        subtitle = tk.Label(header,
                            text="P2P · TOR · POST-QUANTUM ENCRYPTED",
                            fg=C["text_secondary"], bg=C["bg_deep"],
                            font=(FONT_BODY[0], 9))
        subtitle.pack(pady=(4, 0))

        sep = tk.Frame(self, bg=C["accent_cyan"], height=1)
        sep.pack(fill="x", padx=40)

        body = tk.Frame(self, bg=C["bg_deep"], padx=40)
        body.pack(fill="both", expand=True)

        if not has_identity:
            self._build_setup(body)
        else:
            self._build_login(body)

    def _build_login(self, parent):
        tk.Label(parent, text="MASTER PASSWORD", fg=C["text_secondary"],
                 bg=C["bg_deep"], font=(FONT_BODY[0], 9)).pack(anchor="w", pady=(30, 4))

        self.pw_var = tk.StringVar()
        pw_entry = tk.Entry(parent, textvariable=self.pw_var, show="•",
                            bg=C["bg_input"], fg=C["text_primary"], insertbackground=C["accent_cyan"],
                            relief="solid", bd=1, font=FONT_MONO, highlightthickness=1,
                            highlightcolor=C["accent_cyan"], highlightbackground=C["border"])
        pw_entry.pack(fill="x", ipady=8)
        pw_entry.bind("<Return>", lambda _: self._do_login())
        pw_entry.focus_set()

        tk.Frame(parent, bg=C["bg_deep"], height=20).pack()

        btn = tk.Button(parent, text="▶  DECRYPT & CONNECT",
                        command=self._do_login, bg=C["accent_cyan"],
                        fg=C["bg_deep"], font=(FONT_BODY[0], 11, "bold"),
                        relief="flat", cursor="hand2", activebackground="#00b8d4",
                        activeforeground=C["bg_deep"], pady=10)
        btn.pack(fill="x")

        self.status = tk.Label(parent, text="", fg=C["accent_red"],
                               bg=C["bg_deep"], font=FONT_SMALL)
        self.status.pack(pady=8)

        # Amnesic mode
        self.amnesic_var = tk.BooleanVar(value=False)
        chk = tk.Checkbutton(parent, text="⚡ Amnesic Mode (RAM only, no disk write)",
                             variable=self.amnesic_var,
                             bg=C["bg_deep"], fg=C["text_secondary"],
                             selectcolor=C["bg_card"], activebackground=C["bg_deep"],
                             font=FONT_SMALL, cursor="hand2")
        chk.pack(anchor="w", pady=(20, 0))

    def _build_setup(self, parent):
        tk.Label(parent, text="FIRST RUN – CREATE IDENTITY",
                 fg=C["accent_amber"], bg=C["bg_deep"],
                 font=(FONT_BODY[0], 11, "bold")).pack(pady=(24, 16))

        for label, attr in [("REAL PASSWORD", "real_pw"), ("DECOY PASSWORD", "decoy_pw"),
                             ("CONFIRM DECOY", "decoy_confirm")]:
            tk.Label(parent, text=label, fg=C["text_secondary"],
                     bg=C["bg_deep"], font=(FONT_BODY[0], 8)).pack(anchor="w", pady=(8, 2))
            var = tk.StringVar()
            setattr(self, attr + "_var", var)
            e = tk.Entry(parent, textvariable=var, show="•",
                         bg=C["bg_input"], fg=C["text_primary"],
                         insertbackground=C["accent_cyan"], relief="solid", bd=1,
                         font=FONT_MONO, highlightthickness=1,
                         highlightcolor=C["accent_cyan"], highlightbackground=C["border"])
            e.pack(fill="x", ipady=6)

        tk.Frame(parent, bg=C["bg_deep"], height=12).pack()
        btn = tk.Button(parent, text="⬡  FORGE IDENTITY",
                        command=self._do_setup, bg=C["accent_purple"],
                        fg="#fff", font=(FONT_BODY[0], 11, "bold"),
                        relief="flat", cursor="hand2",
                        activebackground="#9333ea", pady=10)
        btn.pack(fill="x")

        self.status = tk.Label(parent, text="", fg=C["accent_red"],
                               bg=C["bg_deep"], font=FONT_SMALL)
        self.status.pack(pady=6)

    def _do_login(self):
        pw = self.pw_var.get()
        if not pw:
            self.status.configure(text="Password required")
            return
        amnesic = getattr(self, "amnesic_var", tk.BooleanVar()).get()
        self.status.configure(text="Decrypting…", fg=C["accent_amber"])
        self.update()
        self.on_login(pw, amnesic)

    def _do_setup(self):
        real  = self.real_pw_var.get()
        decoy = self.decoy_pw_var.get()
        conf  = self.decoy_confirm_var.get()
        if not real or not decoy:
            self.status.configure(text="All fields required")
            return
        if decoy != conf:
            self.status.configure(text="Decoy passwords don't match")
            return
        if real == decoy:
            self.status.configure(text="Real and decoy passwords must differ")
            return
        self.on_setup(real, decoy)

    def show_error(self, msg: str):
        self.status.configure(text=f"✗ {msg}", fg=C["accent_red"])

    def show_success(self, msg: str):
        self.status.configure(text=f"✓ {msg}", fg=C["accent_green"])


# ─────────────────────────────────────────────────────────────────────────────
#  Add Contact dialog
# ─────────────────────────────────────────────────────────────────────────────
class AddContactDialog(tk.Toplevel):
    def __init__(self, parent, on_add: Callable[[str, str], None]):
        super().__init__(parent)
        self.on_add = on_add
        self.configure(bg=C["bg_deep"])
        self.title("Add Contact")
        self.geometry("400x280")
        self.resizable(False, False)
        self.grab_set()
        self._build()

    def _build(self):
        tk.Label(self, text="ADD CONTACT", fg=C["accent_cyan"],
                 bg=C["bg_deep"], font=(FONT_BODY[0], 14, "bold")).pack(pady=20)

        body = tk.Frame(self, bg=C["bg_deep"], padx=30)
        body.pack(fill="both", expand=True)

        for lbl, attr in [("NICKNAME", "nick"), ("ONION ADDRESS", "onion")]:
            tk.Label(body, text=lbl, fg=C["text_secondary"],
                     bg=C["bg_deep"], font=(FONT_BODY[0], 8)).pack(anchor="w", pady=(10, 2))
            var = tk.StringVar()
            setattr(self, attr + "_var", var)
            tk.Entry(body, textvariable=var, bg=C["bg_input"], fg=C["text_primary"],
                     insertbackground=C["accent_cyan"], relief="solid", bd=1,
                     font=FONT_MONO, highlightthickness=1,
                     highlightcolor=C["accent_cyan"], highlightbackground=C["border"]
                     ).pack(fill="x", ipady=6)

        tk.Button(body, text="ADD", command=self._submit,
                  bg=C["accent_cyan"], fg=C["bg_deep"],
                  font=(FONT_BODY[0], 10, "bold"), relief="flat",
                  cursor="hand2", pady=8).pack(fill="x", pady=16)

    def _submit(self):
        nick  = self.nick_var.get().strip()
        onion = self.onion_var.get().strip()
        if nick and onion:
            self.on_add(nick, onion)
            self.destroy()



# ─────────────────────────────────────────────────────────────────────────────
#  LoginFrame
# ─────────────────────────────────────────────────────────────────────────────
class LoginFrame(tk.Frame):
    def __init__(self, parent, on_login: Callable, on_setup: Callable, has_identity: bool):
        super().__init__(parent, bg=C["bg_deep"])
        self.on_login = on_login
        self.on_setup = on_setup
        self._build(has_identity)

    def _build(self, has_identity):
        header = tk.Frame(self, bg=C["bg_deep"], pady=30)
        header.pack(fill="x")
        tk.Label(header, text="◈ NEBULAE", fg=C["accent_cyan"],
                 bg=C["bg_deep"], font=(FONT_BODY[0], 28, "bold")).pack()
        tk.Label(header, text="P2P · TOR · POST-QUANTUM ENCRYPTED",
                 fg=C["text_secondary"], bg=C["bg_deep"],
                 font=(FONT_BODY[0], 9)).pack(pady=(4, 0))
        tk.Frame(self, bg=C["accent_cyan"], height=1).pack(fill="x", padx=40)
        body = tk.Frame(self, bg=C["bg_deep"], padx=40)
        body.pack(fill="both", expand=True)
        if not has_identity:
            self._build_setup(body)
        else:
            self._build_login(body)

    def _build_login(self, parent):
        tk.Label(parent, text="MASTER PASSWORD", fg=C["text_secondary"],
                 bg=C["bg_deep"], font=(FONT_BODY[0], 9)).pack(anchor="w", pady=(30, 4))
        self.pw_var = tk.StringVar()
        pw_entry = tk.Entry(parent, textvariable=self.pw_var, show="•",
                            bg=C["bg_input"], fg=C["text_primary"],
                            insertbackground=C["accent_cyan"],
                            relief="solid", bd=1, font=FONT_MONO,
                            highlightthickness=1, highlightcolor=C["accent_cyan"],
                            highlightbackground=C["border"])
        pw_entry.pack(fill="x", ipady=8)
        pw_entry.bind("<Return>", lambda _: self._do_login())
        pw_entry.focus_set()
        self.amnesic_var = tk.BooleanVar(value=False)
        tk.Checkbutton(parent, text="Amnesic mode (RAM only)",
                       variable=self.amnesic_var, bg=C["bg_deep"],
                       fg=C["text_secondary"], selectcolor=C["bg_card"],
                       activebackground=C["bg_deep"],
                       font=(FONT_BODY[0], 9)).pack(anchor="w", pady=(12, 0))
        tk.Frame(parent, bg=C["bg_deep"], height=20).pack()
        tk.Button(parent, text="UNLOCK  ▶", command=self._do_login,
                  bg=C["accent_cyan"], fg=C["bg_deep"],
                  font=(FONT_BODY[0], 11, "bold"), relief="flat",
                  cursor="hand2", pady=10).pack(fill="x")
        self.msg_lbl = tk.Label(parent, text="", bg=C["bg_deep"], font=(FONT_BODY[0], 9))
        self.msg_lbl.pack(pady=8)

    def _build_setup(self, parent):
        tk.Label(parent, text="CREATE IDENTITY", fg=C["accent_purple"],
                 bg=C["bg_deep"], font=(FONT_BODY[0], 13, "bold")).pack(pady=(24, 0))
        for label, attr in [("REAL PASSWORD", "real_var"),
                             ("DECOY PASSWORD", "decoy_var"),
                             ("CONFIRM DECOY", "confirm_var")]:
            tk.Label(parent, text=label, fg=C["text_secondary"],
                     bg=C["bg_deep"], font=(FONT_BODY[0], 9)).pack(anchor="w", pady=(14, 2))
            var = tk.StringVar()
            setattr(self, attr, var)
            tk.Entry(parent, textvariable=var, show="•",
                     bg=C["bg_input"], fg=C["text_primary"],
                     insertbackground=C["accent_cyan"],
                     relief="solid", bd=1, font=FONT_MONO).pack(fill="x", ipady=6)
        tk.Frame(parent, bg=C["bg_deep"], height=16).pack()
        tk.Button(parent, text="FORGE IDENTITY  ▶", command=self._do_setup,
                  bg=C["accent_purple"], fg="#fff",
                  font=(FONT_BODY[0], 11, "bold"), relief="flat",
                  cursor="hand2", pady=10).pack(fill="x")
        self.msg_lbl = tk.Label(parent, text="", bg=C["bg_deep"], font=(FONT_BODY[0], 9))
        self.msg_lbl.pack(pady=8)

    def _do_login(self):
        self.on_login(self.pw_var.get(), self.amnesic_var.get())

    def _do_setup(self):
        if self.real_var.get() and self.decoy_var.get() == self.confirm_var.get():
            self.on_setup(self.real_var.get(), self.decoy_var.get())
        else:
            self.show_error("Passwords do not match or are empty")

    def show_error(self, msg):
        self.msg_lbl.configure(text=f"✗ {msg}", fg=C["accent_red"])

    def show_success(self, msg):
        self.msg_lbl.configure(text=f"✓ {msg}", fg=C["accent_green"])

# ─────────────────────────────────────────────────────────────────────────────
#  Main application window
# ─────────────────────────────────────────────────────────────────────────────
class NEBULAEWindow(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title("NEBULAE — P2P Tor-Crypted Chat")
        self.geometry("1200x750")
        self.minsize(900, 600)
        self.configure(bg=C["bg_deep"])
        apply_dark_style(self)

        self.app = None  # NEBULAEApp, set after login
        self._active_peer: Optional[str] = None
        self._contact_frames: Dict[str, SidebarButton] = {}
        self._msg_queue: queue.Queue = queue.Queue()

        self._build_ui()
        self._show_login()
        self.after(200, self._poll_messages)

        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Global panic key: Ctrl+Shift+P
        self.bind("<Control-Shift-P>", self._panic)
        self.bind("<Control-Shift-p>", self._panic)

    # ── UI Construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        # Top bar
        self.topbar = tk.Frame(self, bg=C["bg_panel"], height=48)
        self.topbar.pack(fill="x", side="top")
        self.topbar.pack_propagate(False)

        tk.Label(self.topbar, text="◈ NEBULAE", fg=C["accent_cyan"],
                 bg=C["bg_panel"], font=(FONT_BODY[0], 16, "bold")).pack(side="left", padx=16)

        self.status_lbl = tk.Label(self.topbar, text="⬡ OFFLINE",
                                   fg=C["text_dim"], bg=C["bg_panel"], font=FONT_SMALL)
        self.status_lbl.pack(side="left", padx=8)

        # Panic button
        tk.Button(self.topbar, text="🔴 PANIC",
                  command=self._panic, bg=C["accent_red"],
                  fg="#fff", font=(FONT_SMALL[0], 9, "bold"), relief="flat",
                  cursor="hand2", padx=10).pack(side="right", padx=8, pady=6)

        # Settings / canary
        tk.Button(self.topbar, text="⚙",
                  command=self._open_settings, bg=C["bg_panel"],
                  fg=C["text_secondary"], font=(FONT_BODY[0], 14), relief="flat",
                  cursor="hand2").pack(side="right", padx=4)

        # Separator line
        tk.Frame(self, bg=C["accent_cyan"], height=1).pack(fill="x", side="top")

        # Main layout: sidebar + chat area
        self.main = tk.Frame(self, bg=C["bg_deep"])
        self.main.pack(fill="both", expand=True)

        self._build_sidebar()
        self._build_chat_area()

    def _build_sidebar(self):
        self.sidebar = tk.Frame(self.main, bg=C["bg_panel"], width=260)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        # Sidebar header
        sh = tk.Frame(self.sidebar, bg=C["bg_panel"])
        sh.pack(fill="x", padx=12, pady=(12, 6))
        tk.Label(sh, text="CONTACTS", fg=C["text_secondary"],
                 bg=C["bg_panel"], font=(FONT_BODY[0], 9)).pack(side="left")
        tk.Button(sh, text="+", command=self._add_contact,
                  bg=C["bg_card"], fg=C["accent_cyan"],
                  font=(FONT_BODY[0], 12, "bold"), relief="flat",
                  cursor="hand2", width=2).pack(side="right")

        tk.Frame(self.sidebar, bg=C["border"], height=1).pack(fill="x")

        # Scrollable contact list
        contact_wrapper = tk.Frame(self.sidebar, bg=C["bg_panel"])
        contact_wrapper.pack(fill="both", expand=True)

        self.contact_canvas = tk.Canvas(contact_wrapper, bg=C["bg_panel"],
                                        highlightthickness=0, bd=0)
        vsb = ttk.Scrollbar(contact_wrapper, orient="vertical",
                             command=self.contact_canvas.yview)
        self.contact_canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.contact_canvas.pack(fill="both", expand=True)

        self.contact_list = tk.Frame(self.contact_canvas, bg=C["bg_panel"])
        self._contact_win = self.contact_canvas.create_window(
            (0, 0), window=self.contact_list, anchor="nw"
        )
        self.contact_list.bind("<Configure>", self._on_contact_resize)
        self.contact_canvas.bind("<Configure>", lambda e: self.contact_canvas.itemconfig(
            self._contact_win, width=e.width
        ))

        # My onion
        tk.Frame(self.sidebar, bg=C["border"], height=1).pack(fill="x")
        onion_row = tk.Frame(self.sidebar, bg=C["bg_panel"])
        onion_row.pack(fill="x", padx=10, pady=6)
        self.my_onion_lbl = tk.Label(onion_row, text="◎ Not connected",
                                     fg=C["text_dim"], bg=C["bg_panel"],
                                     font=(FONT_SMALL[0], 7), wraplength=190,
                                     anchor="w", justify="left")
        self.my_onion_lbl.pack(side="left", fill="x", expand=True)
        self._copy_btn = tk.Button(onion_row, text="⎘",
                                   command=self._copy_onion,
                                   bg=C["bg_card"], fg=C["accent_cyan"],
                                   font=(FONT_SMALL[0], 9), relief="flat",
                                   cursor="hand2", width=2,
                                   activebackground=C["border"])
        self._copy_btn.pack(side="right")

    def _on_contact_resize(self, _=None):
        self.contact_canvas.configure(scrollregion=self.contact_canvas.bbox("all"))

    def _build_chat_area(self):
        self.chat_frame = tk.Frame(self.main, bg=C["bg_deep"])
        self.chat_frame.pack(side="left", fill="both", expand=True)

        # Chat header
        self.chat_header = tk.Frame(self.chat_frame, bg=C["bg_panel"], height=48)
        self.chat_header.pack(fill="x")
        self.chat_header.pack_propagate(False)
        self.chat_peer_lbl = tk.Label(self.chat_header, text="Select a contact",
                                      fg=C["text_secondary"], bg=C["bg_panel"],
                                      font=FONT_TITLE)
        self.chat_peer_lbl.pack(side="left", padx=16)
        self.chat_onion_lbl = tk.Label(self.chat_header, text="",
                                       fg=C["text_dim"], bg=C["bg_panel"],
                                       font=FONT_SMALL)
        self.chat_onion_lbl.pack(side="left")

        # Self-destruct toggle
        self.destruct_var = tk.StringVar(value="off")
        destruct_btn = tk.OptionMenu(self.chat_header, self.destruct_var,
                                     "off", "30s", "5m", "1h", "24h")
        destruct_btn.configure(bg=C["bg_card"], fg=C["text_secondary"],
                               font=FONT_SMALL, relief="flat", bd=0,
                               activebackground=C["bg_card"],
                               highlightthickness=0)
        destruct_btn["menu"].configure(bg=C["bg_card"], fg=C["text_secondary"])
        destruct_btn.pack(side="right", padx=8)
        tk.Label(self.chat_header, text="⏱", fg=C["text_secondary"],
                 bg=C["bg_panel"], font=FONT_BODY).pack(side="right")

        tk.Frame(self.chat_frame, bg=C["border"], height=1).pack(fill="x")

        # Message display
        msg_wrapper = tk.Frame(self.chat_frame, bg=C["bg_deep"])
        msg_wrapper.pack(fill="both", expand=True)

        self.msg_canvas = tk.Canvas(msg_wrapper, bg=C["bg_deep"],
                                    highlightthickness=0, bd=0)
        msb = ttk.Scrollbar(msg_wrapper, orient="vertical",
                             command=self.msg_canvas.yview)
        self.msg_canvas.configure(yscrollcommand=msb.set)
        msb.pack(side="right", fill="y")
        self.msg_canvas.pack(fill="both", expand=True)

        self.msg_inner = tk.Frame(self.msg_canvas, bg=C["bg_deep"])
        self._msg_win = self.msg_canvas.create_window(
            (0, 0), window=self.msg_inner, anchor="nw"
        )
        self.msg_inner.bind("<Configure>", self._on_msg_resize)
        self.msg_canvas.bind("<Configure>", lambda e: self.msg_canvas.itemconfig(
            self._msg_win, width=e.width
        ))

        # Input bar
        input_bar = tk.Frame(self.chat_frame, bg=C["bg_panel"], pady=12, padx=12)
        input_bar.pack(fill="x", side="bottom")

        self.msg_input = tk.Text(input_bar, height=3, bg=C["bg_input"],
                                 fg=C["text_primary"], insertbackground=C["accent_cyan"],
                                 relief="solid", bd=1, font=FONT_MONO,
                                 wrap="word", highlightthickness=1,
                                 highlightcolor=C["accent_cyan"],
                                 highlightbackground=C["border"])
        self.msg_input.pack(side="left", fill="x", expand=True)
        self.msg_input.bind("<Return>",       self._on_return)
        self.msg_input.bind("<Shift-Return>", self._on_shift_return)

        send_btn = tk.Button(input_bar, text="▶",
                             command=self._send_message,
                             bg=C["accent_cyan"], fg=C["bg_deep"],
                             font=(FONT_BODY[0], 16, "bold"), relief="flat",
                             cursor="hand2", width=3)
        send_btn.pack(side="left", padx=(8, 0), fill="y")

        attach_btn = tk.Button(input_bar, text="⊕",
                               command=self._attach_file,
                               bg=C["bg_card"], fg=C["text_secondary"],
                               font=(FONT_BODY[0], 14), relief="flat",
                               cursor="hand2", width=2)
        attach_btn.pack(side="left", padx=(4, 0), fill="y")

    def _on_msg_resize(self, _=None):
        self.msg_canvas.configure(scrollregion=self.msg_canvas.bbox("all"))

    # ── Login flow ───────────────────────────────────────────────────────────

    def _show_login(self):
        from pathlib import Path
        data_dir = Path.home() / ".nebulae" / "data"
        has_identity = (data_dir / "identity.a.enc").exists()
        self.main.pack_forget()
        self.topbar.pack_forget()
        self._login_frame = LoginFrame(self, self._do_login, self._do_setup, has_identity)
        self._login_frame.pack(expand=True)
        self.geometry("420x540")
        self.resizable(False, False)
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        self.geometry(f"420x540+{(sw-420)//2}+{(sh-540)//2}")
        self.deiconify()
        self.lift()
        self.focus_force()

    def _do_setup(self, real_pw: str, decoy_pw: str):
        from core.app import NEBULAEApp
        tmp_app = NEBULAEApp(lambda *a: None, lambda s: None)
        try:
            tmp_app.first_run_setup(real_pw, decoy_pw)
            self._login_frame.show_success("Identity forged! Login now.")
            self.after(1200, lambda: [self._login_frame.destroy(), self._show_login()])
        except Exception as e:
            self._login_frame.show_error(str(e))

    def _do_login(self, password: str, amnesic: bool):
        from core.app import NEBULAEApp
        self.app = NEBULAEApp(
            message_callback=self._on_message_received,
            status_callback=self._on_status,
            amnesic_mode=amnesic,
        )
        try:
            ok = self.app.login(password)
            if ok:
                self._login_frame.destroy()
                self.geometry("1200x750")
                self.resizable(True, True)
                self.minsize(900, 600)
                self.topbar.pack(fill="x", side="top")
                tk.Frame(self, bg=C["accent_cyan"], height=1).pack(fill="x", side="top")
                self.main.pack(fill="both", expand=True)
                self._post_login()
            else:
                self._login_frame.show_error("Wrong password")
        except Exception as e:
            self._login_frame.show_error(str(e))

    def _post_login(self):
        onion = self.app.node.onion_address if self.app.node else "unknown"
        self._my_onion_addr = onion
        self.my_onion_lbl.configure(text=f"◎ {onion}", fg=C["text_secondary"])
        self.status_lbl.configure(text=f"⬡ ONLINE", fg=C["accent_green"])
        self._refresh_contacts()
        self.after(5000, self._periodic_refresh)

    def _copy_onion(self):
        addr = getattr(self, "_my_onion_addr", None)
        if not addr or addr == "unknown":
            return
        self.clipboard_clear()
        self.clipboard_append(addr)
        # Feedback visivo temporaneo
        self._copy_btn.configure(text="✓", fg=C["accent_green"])
        self.after(1500, lambda: self._copy_btn.configure(text="⎘", fg=C["accent_cyan"]))

    # ── Contact management ───────────────────────────────────────────────────

    def _add_contact(self):
        if not self.app:
            return
        AddContactDialog(self, on_add=self._do_add_contact)

    def _do_add_contact(self, nick: str, onion: str):
        self.app.add_contact(onion, nick)
        self.app.connect_peer(onion)
        self._refresh_contacts()

    def _refresh_contacts(self):
        if not self.app:
            return
        contacts = self.app.get_contacts()
        peers    = {p["onion"]: p for p in self.app.get_peers()}

        # Clear existing
        for w in self.contact_list.winfo_children():
            w.destroy()
        self._contact_frames.clear()

        for c in contacts:
            onion   = c.get("onion", "")
            nick    = c.get("nickname", onion[:12])
            online  = onion in peers
            btn = SidebarButton(
                self.contact_list, nick, onion, online,
                on_click=self._select_contact
            )
            btn.pack(fill="x", pady=1)
            self._contact_frames[onion] = btn
            if onion == self._active_peer:
                btn.set_selected(True)

    def _select_contact(self, onion: str):
        self._active_peer = onion
        for o, btn in self._contact_frames.items():
            btn.set_selected(o == onion)

        contacts = self.app.get_contacts() if self.app else []
        nick = next((c.get("nickname", onion) for c in contacts if c.get("onion") == onion), onion)
        self.chat_peer_lbl.configure(text=nick, fg=C["text_primary"])
        self.chat_onion_lbl.configure(text=onion[:30] + "…")
        self._load_history(onion)

    def _load_history(self, onion: str):
        for w in self.msg_inner.winfo_children():
            w.destroy()
        if not self.app:
            return
        history = self.app.get_history(onion, limit=100)
        for msg in history:
            bubble = MessageBubble(
                self.msg_inner,
                msg["body"],
                msg["direction"],
                msg.get("timestamp", time.time()),
            )
            bubble.pack(fill="x", pady=1)
        self.after(100, self._scroll_to_bottom)

    def _scroll_to_bottom(self):
        self.msg_canvas.update_idletasks()
        self.msg_canvas.yview_moveto(1.0)

    # ── Messaging ────────────────────────────────────────────────────────────

    def _on_return(self, event):
        self._send_message()
        return "break"

    def _on_shift_return(self, event):
        return  # Allow newline

    def _send_message(self):
        if not self.app or not self._active_peer:
            return
        text = self.msg_input.get("1.0", "end-1c").strip()
        if not text:
            return

        destruct_map = {"off": None, "30s": 30, "5m": 300, "1h": 3600, "24h": 86400}
        destruct = destruct_map.get(self.destruct_var.get())

        self.app.send_message(self._active_peer, text, self_destruct_seconds=destruct)
        self.msg_input.delete("1.0", "end")

        bubble = MessageBubble(self.msg_inner, text, "out", time.time())
        bubble.pack(fill="x", pady=1)
        self.after(50, self._scroll_to_bottom)
        self.app.heartbeat()

    def _attach_file(self):
        path = filedialog.askopenfilename(parent=self)
        if not path or not self._active_peer or not self.app:
            return
        try:
            import p2p_crypto as _rust
            data    = Path(path).read_bytes()
            cleaned = _rust.strip_exif_bytes(data)
            self.app.send_message(self._active_peer, f"[FILE:{Path(path).name}:{len(cleaned)}B]")
        except Exception as e:
            messagebox.showerror("File Error", str(e), parent=self)

    # ── Callbacks ────────────────────────────────────────────────────────────

    def _on_message_received(self, peer_id: str, nickname: str, body: str):
        self._msg_queue.put((peer_id, nickname, body))

    def _on_status(self, status: str):
        self.after(0, lambda: self.status_lbl.configure(text=f"⬡ {status}"))

    def _poll_messages(self):
        try:
            while True:
                peer_id, nickname, body = self._msg_queue.get_nowait()
                if peer_id == self._active_peer:
                    bubble = MessageBubble(self.msg_inner, body, "in", time.time())
                    bubble.pack(fill="x", pady=1)
                    self.after(50, self._scroll_to_bottom)
                else:
                    # Flash contact button
                    btn = self._contact_frames.get(peer_id)
                    if btn:
                        self._flash_contact(btn)
        except queue.Empty:
            pass
        self.after(200, self._poll_messages)

    def _flash_contact(self, btn: SidebarButton, count: int = 6):
        if count <= 0:
            return
        color = C["accent_amber"] if count % 2 == 0 else C["bg_panel"]
        btn.configure(bg=color)
        self.after(300, lambda: self._flash_contact(btn, count - 1))

    # ── Settings ─────────────────────────────────────────────────────────────

    def _open_settings(self):
        if not self.app:
            return
        win = tk.Toplevel(self)
        win.title("Settings")
        win.configure(bg=C["bg_deep"])
        win.geometry("380x320")
        win.grab_set()

        tk.Label(win, text="SETTINGS", fg=C["accent_cyan"],
                 bg=C["bg_deep"], font=(FONT_BODY[0], 14, "bold")).pack(pady=16)

        body = tk.Frame(win, bg=C["bg_deep"], padx=24)
        body.pack(fill="both", expand=True)

        # Canary timeout
        tk.Label(body, text="CANARY TIMEOUT (hours)", fg=C["text_secondary"],
                 bg=C["bg_deep"], font=(FONT_BODY[0], 9)).pack(anchor="w", pady=(12, 2))
        canary_var = tk.StringVar(value="48")
        tk.Entry(body, textvariable=canary_var, bg=C["bg_input"], fg=C["text_primary"],
                 insertbackground=C["accent_cyan"], relief="solid", bd=1,
                 font=FONT_MONO).pack(fill="x", ipady=5)

        tk.Button(body, text="ENABLE CANARY",
                  command=lambda: self._enable_canary_from_ui(canary_var.get()),
                  bg=C["accent_amber"], fg=C["bg_deep"],
                  font=(FONT_BODY[0], 10, "bold"), relief="flat",
                  cursor="hand2", pady=8).pack(fill="x", pady=12)

        tk.Button(body, text="SECURE WIPE ALL DATA",
                  command=self._confirm_wipe,
                  bg=C["accent_red"], fg="#fff",
                  font=(FONT_BODY[0], 10, "bold"), relief="flat",
                  cursor="hand2", pady=8).pack(fill="x")

    def _confirm_wipe(self):
        if messagebox.askyesno("⚠ CONFIRM", "This will PERMANENTLY DESTROY all data. Continue?",
                               parent=self, icon="warning"):
            if self.app:
                self.app.panic_wipe()

    def _enable_canary_from_ui(self, value: str):
        if not self.app:
            return
        try:
            hours = float(value) if value.strip() else 48.0
        except ValueError:
            messagebox.showerror("Invalid value", "Canary timeout must be a number.", parent=self)
            return
        self.app.enable_canary(hours)

    # ── Panic ─────────────────────────────────────────────────────────────────

    def _panic(self, _=None):
        if messagebox.askyesno("🔴 PANIC", "Immediately destroy all sessions and data?",
                               parent=self, icon="warning"):
            if self.app:
                self.app.panic_wipe()
            else:
                sys.exit(0)

    # ── Periodic tasks ────────────────────────────────────────────────────────

    def _periodic_refresh(self):
        if not self.app:
            return
        self._refresh_contacts()
        if self.app.store:
            self.app.store.purge_expired()
        self.after(5000, self._periodic_refresh)

    def _on_close(self):
        if self.app:
            self.app.shutdown()
        self.destroy()


# ─────────────────────────────────────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    try:
        app = NEBULAEWindow()
        app.mainloop()
    except Exception:
        import traceback as _tb
        err = _tb.format_exc()
        print(err)
        root = tk.Tk()
        root.title("NEBULAE - Error")
        root.configure(bg="#080b12")
        root.geometry("700x400")
        tk.Label(root, text="STARTUP ERROR", fg="#ef4444", bg="#080b12",
                 font=("Courier", 14, "bold")).pack(pady=10)
        txt = tk.Text(root, bg="#0d1120", fg="#e2e8f0", font=("Courier", 9), wrap="word", relief="flat")
        txt.insert("1.0", err)
        txt.configure(state="disabled")
        txt.pack(fill="both", expand=True, padx=10, pady=10)
        tk.Button(root, text="Close", command=root.destroy, bg="#ef4444", fg="white", relief="flat").pack(pady=6)
        root.mainloop()
