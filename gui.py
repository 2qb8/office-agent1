"""Desktop front end: choose an instruction, choose a language, press Run."""

from __future__ import annotations

import os
import queue
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, font as tkfont, ttk

from agent import __version__, ai_config
from agent.desktop import (
    execute_plan,
    plan_instruction,
    run_instruction,
    self_test,
    test_ai_connection,
)
from agent.llm_factory import PROVIDERS
from agent.ui import (
    APP_TITLE,
    LANGUAGES,
    default_output_dir,
    describe_state,
    instruction_job_dir,
    is_instruction_file,
    remember_recent,
    remembered_ai,
    remembered_language,
    remembered_recent,
    remembered_review,
    save_ai,
    save_review,
    save_settings,
    text,
)


# Palette. One accent colour, a dark header, calm greys for everything else.
ACCENT = "#2563eb"
ACCENT_HOVER = "#1d4ed8"
HEADER_BG = "#111827"
HEADER_FG = "#f8fafc"
HEADER_MUTED = "#9ca3af"
WINDOW_BG = "#eef2f7"
MUTED = "#64748b"
SUCCESS = "#15803d"
FAILURE = "#b91c1c"


def _enable_dpi_awareness() -> None:
    """Draw sharp text on a scaled Windows display.

    Without this Windows renders the window at 96 dpi and scales the bitmap
    up, which is why untweaked Tk apps look blurry on a 150% screen. Tk
    picks the real scaling up once the process is aware, and _fit() then
    sizes the window from the real pixel metrics.
    """

    if not sys.platform.startswith("win"):
        return

    try:
        import ctypes

        try:
            # Per-monitor aware, which is what a single-window app wants.
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def _bundle_root() -> Path:
    base = getattr(sys, "_MEIPASS", None)

    return Path(base) if base else Path(__file__).resolve().parent


def asset_path(name: str) -> Path:
    """Where bundled assets live, both from source and inside the exe."""

    return _bundle_root() / "assets" / name


def example_dir() -> Path:
    """The example job bundled with the app."""

    return _bundle_root() / "examples" / "sales-pack"


class OfficeAgentWindow:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.language = remembered_language()
        self.messages: queue.Queue = queue.Queue()
        self.running = False
        self.failed = False
        self.outputs: list[str] = []
        self.poll_id: str | None = None
        self.testing = False

        # Set by the Stop button; the executor checks it between steps.
        self.cancel: threading.Event | None = None

        # The plan preview window, while it is open.
        self.plan_window: tk.Toplevel | None = None

        self.recent_paths: list[str] = remembered_recent()

        # The thread doing work right now. Kept so it can be joined before
        # the window (and its Tk objects) goes away: a worker that outlives
        # Tk can collect it on the wrong thread and abort the process.
        self.worker: threading.Thread | None = None

        self.instruction_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.status_var = tk.StringVar()
        self.provider_var = tk.StringVar()
        self.model_var = tk.StringVar()
        self.endpoint_var = tk.StringVar()
        self.api_key_var = tk.StringVar()
        self.ai_status_var = tk.StringVar()
        self.review_var = tk.BooleanVar(value=remembered_review())

        self.code_by_label = {
            label: code for code, label in LANGUAGES.items()
        }
        self.provider_by_label = {
            preset.label: code for code, preset in PROVIDERS.items()
        }

        self.family = tkfont.nametofont("TkDefaultFont").actual("family")

        self._build()

        self._restore_ai()

        self._apply_language()

        self.status_var.set(text(self.language, "ready"))

        self._refresh_ai_status()

        # _build() measures an empty window; the labels are filled in now, so
        # measure again or the right-hand column is clipped by the edge.
        self._fit()

        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self.poll_id = self.root.after(120, self._poll)

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _setup_style(self) -> None:
        style = ttk.Style(self.root)

        for theme in ("vista", "clam", "default"):
            if theme in style.theme_names():
                style.theme_use(theme)
                break

        base_font = tkfont.nametofont("TkDefaultFont")

        base_font.configure(size=10 if sys.platform.startswith("win") else 11)

        tkfont.nametofont("TkTextFont").configure(size=base_font.cget("size"))

        style.configure("Body.TFrame", background=WINDOW_BG)
        style.configure("Card.TLabelframe", background=WINDOW_BG)
        style.configure(
            "Card.TLabelframe.Label",
            font=(self.family, 10, "bold"),
            foreground="#334155",
        )
        style.configure("Muted.TLabel", foreground=MUTED, background=WINDOW_BG)
        style.configure("Path.TLabel", foreground="#0f172a", background=WINDOW_BG)
        style.configure("Status.TLabel", background=WINDOW_BG, wraplength=760)

    def _build(self) -> None:
        self.root.configure(bg=WINDOW_BG)
        self.root.minsize(860, 700)

        self._setup_style()

        self._build_header()

        body = ttk.Frame(self.root, style="Body.TFrame", padding=(18, 10, 18, 4))
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(2, weight=1)

        self._build_document_card(body)
        self._build_ai_card(body)
        self._build_log(body)
        self._build_footer(body)

        self._set_icon()
        self._fit()

    def _build_header(self) -> None:
        header = tk.Frame(self.root, bg=HEADER_BG)
        header.pack(fill="x")

        inner = tk.Frame(header, bg=HEADER_BG)
        inner.pack(fill="x", padx=20, pady=16)
        inner.columnconfigure(0, weight=1)

        self.title_label = tk.Label(
            inner,
            text=APP_TITLE,
            bg=HEADER_BG,
            fg=HEADER_FG,
            font=(self.family, 17, "bold"),
            anchor="w",
        )
        self.title_label.grid(row=0, column=0, sticky="w")

        self.version_label = tk.Label(
            inner,
            text=f"v{__version__}",
            bg=HEADER_BG,
            fg=HEADER_MUTED,
            font=(self.family, 10),
            anchor="e",
        )
        self.version_label.grid(row=0, column=1, sticky="e")

        self.subtitle_label = tk.Label(
            inner,
            bg=HEADER_BG,
            fg=HEADER_MUTED,
            font=(self.family, 10),
            anchor="w",
        )
        self.subtitle_label.grid(row=1, column=0, columnspan=2, sticky="w")

    def _build_document_card(self, parent: ttk.Frame) -> None:
        self.document_card = ttk.LabelFrame(
            parent,
            style="Card.TLabelframe",
            padding=(14, 8, 14, 12),
        )
        self.document_card.grid(row=0, column=0, sticky="ew")
        self.document_card.columnconfigure(1, weight=1)

        self.instruction_label = ttk.Label(
            self.document_card, style="Path.TLabel"
        )
        self.instruction_label.grid(row=0, column=0, sticky="w", pady=(2, 0))

        self.instruction_entry = ttk.Entry(
            self.document_card,
            textvariable=self.instruction_var,
            font=(self.family, 10),
        )
        self.instruction_entry.grid(
            row=0, column=1, sticky="ew", padx=(12, 8), pady=(2, 0)
        )

        self.browse_button = ttk.Button(
            self.document_card,
            command=self.choose_instruction,
        )
        self.browse_button.grid(row=0, column=2, sticky="ew", pady=(2, 0))

        self.instruction_hint = ttk.Label(
            self.document_card, style="Muted.TLabel"
        )
        self.instruction_hint.grid(
            row=1, column=1, columnspan=2, sticky="w", padx=(12, 0)
        )

        self.output_label = ttk.Label(
            self.document_card, style="Path.TLabel"
        )
        self.output_label.grid(row=2, column=0, sticky="w", pady=(6, 0))

        self.output_value = ttk.Label(
            self.document_card,
            textvariable=self.output_var,
            style="Path.TLabel",
            anchor="w",
        )
        self.output_value.grid(
            row=2,
            column=1,
            columnspan=2,
            sticky="ew",
            padx=(12, 0),
            pady=(6, 0),
        )

        self.language_label = ttk.Label(
            self.document_card, style="Path.TLabel"
        )
        self.language_label.grid(row=3, column=0, sticky="w", pady=(6, 0))

        self.language_combo = ttk.Combobox(
            self.document_card,
            state="readonly",
            width=16,
            values=list(self.code_by_label),
            font=(self.family, 10),
        )
        self.language_combo.grid(
            row=3, column=1, sticky="w", padx=(12, 0), pady=(6, 0)
        )
        self.language_combo.bind("<<ComboboxSelected>>", self.on_language)

        self.recent_button = ttk.Menubutton(
            self.document_card,
            width=12,
        )
        self.recent_menu = tk.Menu(self.recent_button, tearoff=False)
        self.recent_menu.configure(postcommand=self._fill_recent)
        self.recent_button.configure(menu=self.recent_menu)
        self.recent_button.grid(
            row=0, column=3, sticky="ew", padx=(8, 0), pady=(4, 0)
        )

        self.example_button = ttk.Button(
            self.document_card,
            command=self.use_example,
        )
        self.example_button.grid(
            row=1, column=3, sticky="e", padx=(8, 0)
        )

    def _build_ai_card(self, parent: ttk.Frame) -> None:
        self.ai_card = ttk.LabelFrame(
            parent,
            style="Card.TLabelframe",
            padding=(14, 8, 14, 10),
        )
        self.ai_card.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        self.ai_card.columnconfigure(3, weight=1)

        self.provider_label = ttk.Label(
            self.ai_card, style="Path.TLabel"
        )
        self.provider_label.grid(row=0, column=0, sticky="w")

        self.provider_combo = ttk.Combobox(
            self.ai_card,
            textvariable=self.provider_var,
            state="readonly",
            width=26,
            values=list(self.provider_by_label),
            font=(self.family, 10),
        )
        self.provider_combo.grid(row=0, column=1, sticky="w", padx=(12, 12))
        self.provider_combo.bind(
            "<<ComboboxSelected>>", self.on_provider_change
        )

        self.model_label = ttk.Label(self.ai_card, style="Path.TLabel")
        self.model_label.grid(row=0, column=2, sticky="w")

        self.model_entry = ttk.Entry(
            self.ai_card,
            textvariable=self.model_var,
            width=22,
            font=(self.family, 10),
        )
        self.model_entry.grid(row=0, column=3, sticky="ew", padx=(12, 0))
        self.model_entry.bind("<FocusOut>", self._on_ai_edit)

        self.endpoint_label = ttk.Label(
            self.ai_card, style="Path.TLabel"
        )
        self.endpoint_label.grid(row=1, column=0, sticky="w", pady=(5, 0))

        self.endpoint_entry = ttk.Entry(
            self.ai_card,
            textvariable=self.endpoint_var,
            font=(self.family, 10),
        )
        self.endpoint_entry.grid(
            row=1, column=1, columnspan=3, sticky="ew",
            padx=(12, 0), pady=(5, 0),
        )
        self.endpoint_entry.bind("<FocusOut>", self._on_ai_edit)

        self.key_label = ttk.Label(self.ai_card, style="Path.TLabel")
        self.key_label.grid(row=2, column=0, sticky="w", pady=(5, 0))

        self.key_entry = ttk.Entry(
            self.ai_card,
            textvariable=self.api_key_var,
            show="•",
            font=(self.family, 10),
        )
        self.key_entry.grid(
            row=2, column=1, columnspan=3, sticky="ew",
            padx=(12, 12), pady=(5, 0),
        )
        self.key_entry.bind("<FocusOut>", self._on_ai_edit)

        self.test_button = ttk.Button(
            self.ai_card,
            command=self.test_connection,
            width=17,
        )
        self.test_button.grid(row=2, column=4, sticky="e", pady=(5, 0))

        self.ai_status_label = ttk.Label(
            self.ai_card,
            textvariable=self.ai_status_var,
            style="Muted.TLabel",
            wraplength=760,
        )
        self.ai_status_label.grid(
            row=3, column=0, columnspan=5, sticky="w", pady=(6, 0)
        )

        self.ai_hint_label = ttk.Label(
            self.ai_card, style="Muted.TLabel", wraplength=760
        )
        self.ai_hint_label.grid(row=4, column=0, columnspan=5, sticky="w")

    def _build_log(self, parent: ttk.Frame) -> None:
        self.log_card = ttk.LabelFrame(
            parent,
            style="Card.TLabelframe",
            padding=(10, 4, 10, 8),
        )
        self.log_card.grid(row=2, column=0, sticky="nsew", pady=(12, 0))
        self.log_card.columnconfigure(0, weight=1)
        self.log_card.rowconfigure(0, weight=1)

        mono = self._mono_family()

        # The log expands to fill the card, so this is only the minimum it
        # demands; a smaller minimum is what lets the footer fit on a
        # 1024x768 screen instead of being pushed off the bottom.
        self.log = tk.Text(
            self.log_card,
            height=4,
            wrap="word",
            state="disabled",
            borderwidth=0,
            highlightthickness=1,
            highlightbackground="#d7dde7",
            highlightcolor="#d7dde7",
            background="#ffffff",
            foreground="#1f2937",
            font=(mono, 9),
            padx=10,
            pady=8,
        )
        self.log.grid(row=0, column=0, sticky="nsew")

        scroll = ttk.Scrollbar(
            self.log_card,
            orient="vertical",
            command=self.log.yview,
        )
        scroll.grid(row=0, column=1, sticky="ns")

        self.log.configure(yscrollcommand=scroll.set)

        self.log.tag_configure("ok", foreground=SUCCESS)
        self.log.tag_configure("fail", foreground=FAILURE)
        self.log.tag_configure("muted", foreground=MUTED)
        self.log.tag_configure("path", foreground=ACCENT_HOVER)
        self.log.tag_configure(
            "head",
            font=(mono, 9, "bold"),
            foreground="#0f172a",
        )


    def _build_footer(self, parent: ttk.Frame) -> None:
        self.status_label = ttk.Label(
            parent,
            textvariable=self.status_var,
            style="Status.TLabel",
        )
        self.status_label.grid(row=3, column=0, sticky="w", pady=(6, 2))

        footer = ttk.Frame(parent, style="Body.TFrame")
        footer.grid(row=4, column=0, sticky="ew")
        footer.columnconfigure(5, weight=1)

        self.run_button = tk.Button(
            footer,
            command=self.run_job,
            bg=ACCENT,
            fg="#ffffff",
            activebackground=ACCENT_HOVER,
            activeforeground="#ffffff",
            disabledforeground="#e2e8f0",
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            padx=26,
            pady=9,
            cursor="hand2",
            font=(self.family, 11, "bold"),
        )
        self.run_button.grid(row=0, column=0, sticky="w")
        self.run_button.bind(
            "<Enter>", lambda event: self._hover_run(True)
        )
        self.run_button.bind(
            "<Leave>", lambda event: self._hover_run(False)
        )

        self.open_button = ttk.Button(
            footer,
            command=self.open_output,
            state="disabled",
        )
        self.open_button.grid(row=0, column=1, sticky="w", padx=(12, 0))

        self.stop_button = ttk.Button(
            footer,
            command=self.stop_job,
            state="disabled",
        )
        self.stop_button.grid(row=0, column=2, sticky="w", padx=(8, 0))

        self.copy_button = ttk.Button(
            footer,
            command=self.copy_details,
            state="disabled",
        )
        self.copy_button.grid(row=0, column=3, sticky="e", padx=(16, 0))

        self.log_button = ttk.Button(footer, command=self.open_run_log)
        self.log_button.grid(row=0, column=4, sticky="e", padx=(8, 0))

        # Determinate: one step of the plan is one step of the bar.
        self.progress = ttk.Progressbar(
            footer,
            mode="determinate",
            maximum=100,
            value=0,
            length=170,
        )
        self.progress.grid(row=0, column=5, sticky="e", padx=(8, 0))

        # Only shown while a job runs; an idle bar is just a stray block.
        self.progress.grid_remove()

        self.review_check = ttk.Checkbutton(
            self.document_card,
            variable=self.review_var,
            command=self._on_review_toggle,
        )
        self.review_check.grid(
            row=4,
            column=1,
            columnspan=2,
            sticky="w",
            padx=(12, 0),
            pady=(8, 0),
        )

    def _mono_family(self) -> str:
        available = set(tkfont.families(self.root))

        for name in ("Consolas", "Cascadia Mono", "Menlo", "DejaVu Sans Mono"):
            if name in available:
                return name

        return "TkFixedFont"

    def _hover_run(self, entering: bool) -> None:
        if str(self.run_button.cget("state")) == "disabled":
            return

        self.run_button.configure(
            bg=ACCENT_HOVER if entering else ACCENT
        )

    def _set_icon(self) -> None:
        for name in ("office-agent.png", "office-agent.ico"):
            path = asset_path(name)

            if not path.is_file():
                continue

            try:
                self.icon = tk.PhotoImage(file=str(path))
                self.root.iconphoto(True, self.icon)
                return
            except tk.TclError:
                continue

    def _place(self, width: int, height: int) -> None:
        try:
            screen_width = self.root.winfo_screenwidth()
            screen_height = self.root.winfo_screenheight()

            x = max(0, (screen_width - width) // 2)
            y = max(0, (screen_height - height) // 3)

            self.root.geometry(f"{width}x{height}+{x}+{y}")
        except tk.TclError:
            self.root.geometry(f"{width}x{height}")

    def _fit(self) -> None:
        """Size the window to its content, capped by the screen.

        A fixed 900x740 silently clipped the footer the first time a row was
        added to it. Sizing from the requested geometry keeps the window
        right as rows come and go, and the cap stops it running off the
        bottom of a small display.
        """

        try:
            self.root.update_idletasks()

            width = max(900, self.root.winfo_reqwidth())
            height = max(740, self.root.winfo_reqheight())

            screen_width = self.root.winfo_screenwidth()
            available = self.root.winfo_screenheight() - 60

            if screen_width > 0:
                width = min(width, screen_width - 40)

            if available > 0:
                height = min(height, available)
        except tk.TclError:
            width, height = 900, 740

        self._place(width, height)

    def _apply_language(self) -> None:
        self.root.title(f"{APP_TITLE} {__version__}")

        self.subtitle_label.configure(
            text=text(self.language, "subtitle")
        )

        self.document_card.configure(
            text=text(self.language, "document_section")
        )
        self.instruction_label.configure(
            text=text(self.language, "instruction")
        )
        self.instruction_hint.configure(
            text=text(self.language, "instruction_hint")
        )
        self.output_label.configure(text=text(self.language, "output"))
        self.language_label.configure(
            text=text(self.language, "language")
        )
        self.browse_button.configure(text=text(self.language, "browse"))
        self.open_button.configure(
            text=text(self.language, "open_output")
        )
        self.stop_button.configure(text=text(self.language, "stop"))
        self.review_check.configure(
            text=text(self.language, "review_plan")
        )
        self.copy_button.configure(text=text(self.language, "copy_details"))
        self.log_button.configure(text=text(self.language, "open_log"))
        self.recent_button.configure(text=text(self.language, "recent"))
        self.example_button.configure(text=text(self.language, "example"))
        self.run_button.configure(
            text=text(
                self.language,
                "running" if self.running else "run",
            )
        )

        self.ai_card.configure(text=text(self.language, "ai_section"))
        self.provider_label.configure(
            text=text(self.language, "provider")
        )
        self.model_label.configure(text=text(self.language, "model"))
        self.endpoint_label.configure(
            text=text(self.language, "endpoint")
        )
        self.key_label.configure(text=text(self.language, "api_key"))
        self.test_button.configure(text=text(self.language, "test"))
        self.ai_hint_label.configure(text=text(self.language, "ai_hint"))

        self.log_card.configure(text=text(self.language, "log"))

        self.language_combo.set(LANGUAGES[self.language])

    # ------------------------------------------------------------------
    # Inputs
    # ------------------------------------------------------------------

    def choose_instruction(self) -> None:
        current = self.instruction_var.get().strip()

        initial = (
            str(Path(current).expanduser().parent)
            if current
            else None
        )

        options: dict = {
            "title": text(self.language, "select_instruction"),
            "filetypes": [
                (
                    text(self.language, "instruction_filter"),
                    "*.docx *.txt *.md",
                ),
                (text(self.language, "all_files"), "*.*"),
            ],
        }

        if initial:
            options["initialdir"] = initial

        chosen = filedialog.askopenfilename(**options)

        if not chosen:
            return

        self.use_instruction(Path(chosen).expanduser())

    def use_instruction(self, instruction: Path) -> None:
        """Fill the window for one instruction file, without a dialog."""

        self.instruction_var.set(str(instruction))
        self.output_var.set(str(default_output_dir(instruction)))
        self.status_var.set(text(self.language, "ready"))

        self._clear_log()

    def on_language(self, event=None) -> None:
        code = self.code_by_label.get(self.language_combo.get())

        if not code or code == self.language:
            return

        self.language = code

        save_settings(language=code)

        self._apply_language()

        self._refresh_ai_status()

        if not self.running and not self.outputs:
            self.status_var.set(text(self.language, "ready"))

    # ------------------------------------------------------------------
    # AI planner settings
    # ------------------------------------------------------------------

    def _restore_ai(self) -> None:
        saved = remembered_ai()

        if not saved.get("provider"):
            # First launch: show a configuration made with `run.py ai setup`
            # (environment or config/.env) instead of an empty form.
            current = ai_config.resolve()

            if current.provider:
                saved = {
                    "provider": current.provider,
                    "base_url": current.base_url,
                    "model": current.model,
                    "api_key": current.api_key,
                }

        provider = saved.get("provider") or "openai"

        if provider not in PROVIDERS:
            provider = "openai"

        self.provider_var.set(PROVIDERS[provider].label)
        self.model_var.set(
            saved.get("model") or PROVIDERS[provider].model
        )
        self.endpoint_var.set(
            saved.get("base_url") or PROVIDERS[provider].base_url
        )
        self.api_key_var.set(saved.get("api_key") or "")

        if saved.get("provider"):
            ai_config.apply_environment(self._ai_values())

    def _ai_values(self) -> dict[str, str]:
        code = self.provider_by_label.get(self.provider_var.get(), "custom")

        return {
            "provider": code,
            "base_url": self.endpoint_var.get().strip(),
            "model": self.model_var.get().strip(),
            "api_key": self.api_key_var.get().strip(),
        }

    def _persist_ai(self) -> None:
        save_ai(self._ai_values())

        ai_config.apply_environment(self._ai_values())

    def _on_ai_edit(self, event=None) -> None:
        self._persist_ai()
        self._refresh_ai_status()

    def on_provider_change(self, event=None) -> None:
        code = self.provider_by_label.get(self.provider_var.get())

        if code is None:
            return

        preset = PROVIDERS[code]

        self.model_var.set(preset.model)
        self.endpoint_var.set(preset.base_url)

        self._persist_ai()
        self._refresh_ai_status()

    def _refresh_ai_status(self) -> None:
        values = self._ai_values()
        preset = PROVIDERS.get(values["provider"])

        colour = MUTED

        if not values["base_url"] or not values["model"]:
            message = text(self.language, "ai_needs_endpoint")
        elif preset and preset.requires_key and not values["api_key"]:
            message = text(
                self.language,
                "ai_needs_key",
                provider=preset.label,
            )
        elif values["provider"]:
            message = text(
                self.language,
                "ai_ready",
                provider=(
                    preset.label if preset else values["provider"]
                ),
                model=values["model"],
            )
            colour = SUCCESS
        else:
            message = text(self.language, "ai_off")

        self.ai_status_var.set(message)
        self.ai_status_label.configure(foreground=colour)

    def test_connection(self) -> None:
        if self.testing:
            return

        values = self._ai_values()
        preset = PROVIDERS.get(values["provider"])

        if not values["base_url"] or not values["model"]:
            self.ai_status_var.set(
                text(self.language, "ai_needs_endpoint")
            )
            return

        if preset and preset.requires_key and not values["api_key"]:
            self.ai_status_var.set(
                text(
                    self.language,
                    "ai_needs_key",
                    provider=preset.label,
                )
            )
            return

        self._persist_ai()

        self.testing = True
        self.test_button.configure(state="disabled")
        self.ai_status_var.set(text(self.language, "testing"))

        self.worker = threading.Thread(
            target=self._test_ai,
            args=(values,),
            daemon=True,
        )
        self.worker.start()

    def _test_ai(self, values: dict[str, str]) -> None:
        check = test_ai_connection(values)

        self.messages.put(
            ("ai_ok" if check.ok else "ai_fail", check.summary, None)
        )

    # ------------------------------------------------------------------
    # Running
    # ------------------------------------------------------------------

    def run_job(self) -> None:
        if self.running:
            return

        raw = self.instruction_var.get().strip()

        if not raw:
            self._set_status(text(self.language, "no_instruction"), FAILURE)
            return

        instruction = Path(raw).expanduser()

        if not instruction.is_file():
            self._set_status(
                text(self.language, "missing_instruction"), FAILURE
            )
            return

        if not is_instruction_file(instruction):
            self._set_status(
                text(self.language, "unsupported_instruction"), FAILURE
            )
            return

        self._persist_ai()

        self.output_var.set(str(default_output_dir(instruction)))
        self.outputs = []
        self.failed = False

        self._clear_log()
        self._set_running(True)

        configured = ai_config.configured()

        self._append(f"Instruction: {instruction.name}", "head")
        self._append(
            text(
                self.language,
                "planning_ai" if configured else "spec_found",
                provider=_label_for(self._ai_values()["provider"]),
                model=self.model_var.get(),
            ),
            "muted",
        )
        self._append("", None)

        self.cancel = threading.Event()

        try:
            remember_recent(instruction)
        except Exception:
            pass

        target = self._work_plan if self.review_var.get() else self._work

        self.worker = threading.Thread(
            target=target,
            args=(instruction,),
            daemon=True,
        )
        self.worker.start()

    def _work(self, instruction: Path) -> None:
        # A spec in the instruction always wins; AI is used only for
        # instructions that have none, and only when configured.
        self.messages.put(run_instruction(instruction))

    def _work_plan(self, instruction: Path) -> None:
        """Plan only, so the window can show the steps first."""

        try:
            runtime, kind, payload = plan_instruction(instruction)
        except Exception as exc:  # never leave the window waiting
            self.messages.put(("error", exc, None))
            return

        if kind == "plan" and runtime is not None:
            self.messages.put(("plan", (runtime, payload), None))
            return

        self.messages.put((kind, payload, None))

    def _work_execute(self, runtime, plan) -> None:
        self.messages.put(
            execute_plan(
                runtime,
                plan,
                progress=self._progress,
                cancel=self.cancel,
            )
        )

    def _progress(self, done: int, total: int, label: str) -> None:
        """Called on the worker thread; the window draws it when polled."""

        self.messages.put(("progress", (done, total), label))

    def stop_job(self) -> None:
        """Stop before the next step; the current one is allowed to finish."""

        if not self.running:
            return

        if self.cancel is not None:
            self.cancel.set()

        self.stop_button.configure(state="disabled")
        self._set_status(text(self.language, "stopping"), MUTED)

    def _on_review_toggle(self) -> None:
        try:
            save_review(bool(self.review_var.get()))
        except Exception:
            pass

    def _poll(self) -> None:
        try:
            while True:
                kind, payload, extra = self.messages.get_nowait()

                self._handle(kind, payload, extra)
        except queue.Empty:
            pass

        self.poll_id = self.root.after(120, self._poll)

    def _handle(self, kind: str, payload, extra) -> None:
        if kind == "done":
            state = payload

            for line in describe_state(state):
                tag = "ok" if line.startswith("[OK]") else "fail"
                self._append(line, tag)

            if state.failed_steps:
                failed_id = state.failed_steps[-1]
                result = state.results.get(failed_id)

                reason = (
                    result.error
                    if result is not None and result.error
                    else failed_id
                )

                self.failed = True
                self._set_running(False)
                self._set_status(
                    text(self.language, "failed", error=reason),
                    FAILURE,
                )
                return

            self.outputs = list(extra)

            self._show_outputs()

            if state.status.value == "skipped":
                self._set_running(False)
                self._set_status(
                    text(
                        self.language,
                        "stopped",
                        count=len(self.outputs),
                    ),
                    MUTED,
                )
                return

            self._set_running(False)
            self._set_status(
                text(self.language, "done", count=len(self.outputs)),
                SUCCESS,
            )
            return

        if kind == "plan":
            runtime, plan = payload

            self._show_plan(runtime, plan)
            return

        if kind == "progress":
            done, total = payload

            if total:
                self.progress.configure(value=100.0 * done / total)

            if self.running and extra:
                self._set_status(str(extra), MUTED)

            return

        if kind == "ai_ok":
            self.testing = False
            self.test_button.configure(state="normal")
            self.ai_status_var.set(
                text(self.language, "ai_ok", detail=payload or "OK")
            )
            self.ai_status_label.configure(foreground=SUCCESS)
            return

        if kind == "ai_fail":
            self.testing = False
            self.test_button.configure(state="normal")
            self.ai_status_var.set(
                text(self.language, "ai_fail", detail=payload)
            )
            self.ai_status_label.configure(foreground=FAILURE)
            return

        self._set_running(False)
        self.failed = True

        if kind == "nospec":
            message = text(self.language, "no_spec")
            self._append(message, "fail")
            self._set_status(message, FAILURE)
            return

        if kind == "busy":
            message = text(self.language, "busy")
            self._append(message, "fail")
            self._set_status(message, FAILURE)
            return

        message = text(self.language, "failed", error=payload)
        self._append(message, "fail")
        self._set_status(message, FAILURE)

    def _set_status(self, message: str, colour: str = MUTED) -> None:
        self.status_var.set(message)
        self.status_label.configure(foreground=colour)

    def _set_running(self, running: bool) -> None:
        self.running = running

        self.run_button.configure(
            state="disabled" if running else "normal",
            text=text(
                self.language,
                "running" if running else "run",
            ),
        )
        self.run_button.configure(
            bg=ACCENT_HOVER if running else ACCENT
        )

        state = "disabled" if running or self.testing else "normal"

        self.browse_button.configure(state=state)
        self.provider_combo.configure(
            state="disabled" if running else "readonly"
        )

        self.open_button.configure(
            state=(
                "normal"
                if self.outputs and not running
                else "disabled"
            )
        )

        self.stop_button.configure(
            state="normal" if running else "disabled"
        )
        self.review_check.configure(
            state="disabled" if running else "normal"
        )
        self.copy_button.configure(
            state=(
                "normal"
                if self.failed and not running
                else "disabled"
            )
        )

        if running:
            self.progress.configure(value=0)
            self.progress.grid()
        else:
            self.progress.grid_remove()

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------

    def open_output(self) -> None:
        raw = self.output_var.get().strip()

        if not raw:
            self._set_status(text(self.language, "no_output"), FAILURE)
            return

        target = Path(raw).expanduser()

        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._set_status(
                text(self.language, "cannot_open", error=exc), FAILURE
            )
            return

        self._open_path(str(target))

    def _open_path(self, path: str) -> None:
        """Open a file or folder with whatever the system uses for it."""

        target = Path(path).expanduser()

        try:
            if sys.platform.startswith("win"):
                os.startfile(str(target))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(target)])
            else:
                subprocess.Popen(["xdg-open", str(target)])
        except OSError as exc:
            self._set_status(
                text(self.language, "cannot_open", error=exc), FAILURE
            )

    def _show_outputs(self) -> None:
        """One clickable line per created file."""

        for index, path in enumerate(self.outputs):
            tag = f"out{index}"

            self._append("", None)

            self.log.tag_configure(tag, underline=True, foreground=ACCENT)
            self._append(path, tag)

            self.log.tag_bind(
                tag,
                "<Button-1>",
                lambda event, target=path: self._open_path(target),
            )
            self.log.tag_bind(
                tag,
                "<Enter>",
                lambda event: self.log.configure(cursor="hand2"),
            )
            self.log.tag_bind(
                tag,
                "<Leave>",
                lambda event: self.log.configure(cursor=""),
            )

    def _log_path(self) -> Path:
        raw = self.instruction_var.get().strip()

        if not raw:
            return Path("run.log")

        return instruction_job_dir(Path(raw).expanduser()) / "run.log"

    def open_run_log(self) -> None:
        target = self._log_path()

        if not target.is_file():
            self._set_status(text(self.language, "no_log"), FAILURE)
            return

        self._open_path(str(target))

    def copy_details(self) -> None:
        """Everything needed to describe a failure, one click away."""

        lines = [
            f"{APP_TITLE} {__version__}",
            f"instruction: {self.instruction_var.get().strip()}",
            f"output: {self.output_var.get().strip()}",
            f"log: {self._log_path()}",
            f"status: {self.status_var.get()}",
        ]

        lines.extend(self.outputs)

        try:
            self.root.clipboard_clear()
            self.root.clipboard_append("\n".join(lines))
        except tk.TclError:
            pass

        self._set_status(text(self.language, "copied"), MUTED)

    def use_example(self) -> None:
        """Copy the bundled example into Documents and fill the window."""

        source = example_dir()

        if not source.is_dir():
            self._set_status(
                text(self.language, "example_failed", error=source),
                FAILURE,
            )
            return

        destination = Path.home() / "Documents" / "Office Agent example"

        try:
            if destination.exists():
                shutil.rmtree(destination)

            shutil.copytree(source, destination)
        except OSError as exc:
            self._set_status(
                text(self.language, "example_failed", error=exc),
                FAILURE,
            )
            return

        self.use_instruction(destination / "instruction.docx")

        self._set_status(
            text(self.language, "example_copied", path=destination),
            SUCCESS,
        )

    def _fill_recent(self) -> None:
        self.recent_menu.delete(0, "end")

        self.recent_paths = [
            path for path in remembered_recent() if Path(path).is_file()
        ]

        if not self.recent_paths:
            self.recent_menu.add_command(
                label=text(self.language, "recent_empty"),
                state="disabled",
            )
            return

        for path in self.recent_paths:
            self.recent_menu.add_command(
                label=f"{Path(path).name} — {Path(path).parent}",
                command=lambda chosen=path: self.use_instruction(
                    Path(chosen)
                ),
            )

    # ------------------------------------------------------------------
    # Plan preview
    # ------------------------------------------------------------------

    def _show_plan(self, runtime, plan) -> None:
        """Show the steps before anything is written."""

        if self.plan_window is not None:
            self._dismiss_plan(self.plan_window)

        window = tk.Toplevel(self.root)
        self.plan_window = window

        window.title(text(self.language, "plan_title"))
        window.configure(bg=WINDOW_BG)
        window.transient(self.root)
        window.resizable(False, False)

        frame = tk.Frame(window, bg=WINDOW_BG, padx=18, pady=16)
        frame.pack(fill="both", expand=True)

        tk.Label(
            frame,
            text=text(self.language, "plan_goal", goal=plan.goal or "—"),
            bg=WINDOW_BG,
            fg="#0f172a",
            font=(self.family, 11, "bold"),
            anchor="w",
            justify="left",
            wraplength=520,
        ).pack(fill="x")

        tk.Label(
            frame,
            text=text(self.language, "plan_count", count=len(plan.steps)),
            bg=WINDOW_BG,
            fg=MUTED,
            font=(self.family, 10),
            anchor="w",
        ).pack(fill="x", pady=(2, 10))

        body = tk.Text(
            frame,
            width=62,
            height=max(4, min(16, len(plan.steps) * 2)),
            wrap="word",
            relief="flat",
            bg="#ffffff",
            fg="#0f172a",
            font=(self.family, 10),
            padx=10,
            pady=8,
            highlightthickness=0,
        )

        for index, step in enumerate(plan.steps, start=1):
            body.insert("end", f"{index}. {step.tool}.{step.action}\n")
            body.insert("end", f"    {step.description}\n\n")

        body.configure(state="disabled")
        body.pack(fill="both", expand=True)

        buttons = tk.Frame(frame, bg=WINDOW_BG)
        buttons.pack(fill="x", pady=(14, 0))

        tk.Button(
            buttons,
            text=text(self.language, "plan_start"),
            command=lambda: self._start_plan(window, runtime, plan),
            bg=ACCENT,
            fg="#ffffff",
            activebackground=ACCENT_HOVER,
            activeforeground="#ffffff",
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            padx=20,
            pady=7,
            cursor="hand2",
            font=(self.family, 10, "bold"),
        ).pack(side="left")

        ttk.Button(
            buttons,
            text=text(self.language, "plan_cancel"),
            command=lambda: self._dismiss_plan(window),
        ).pack(side="right")

        window.protocol(
            "WM_DELETE_WINDOW", lambda: self._dismiss_plan(window)
        )

        window.update_idletasks()

        try:
            x = self.root.winfo_rootx() + max(
                0, (self.root.winfo_width() - window.winfo_width()) // 2
            )
            y = self.root.winfo_rooty() + 90

            window.geometry(f"+{x}+{y}")
            window.grab_set()
        except tk.TclError:
            pass

    def _start_plan(self, window, runtime, plan) -> None:
        self.plan_window = None

        try:
            window.grab_release()
            window.destroy()
        except tk.TclError:
            pass

        if self.cancel is not None and self.cancel.is_set():
            # Stop was pressed while the plan was being built: run nothing.
            self._set_running(False)
            self._set_status(
                text(self.language, "stopped", count=0), MUTED
            )
            return

        self.cancel = threading.Event()

        self.worker = threading.Thread(
            target=self._work_execute,
            args=(runtime, plan),
            daemon=True,
        )
        self.worker.start()

    def _dismiss_plan(self, window) -> None:
        """Cancelling the preview ends the run: nothing was written."""

        self.plan_window = None

        try:
            window.grab_release()
            window.destroy()
        except tk.TclError:
            pass

        self._set_running(False)
        self._set_status(text(self.language, "ready"), MUTED)

    def close(self) -> None:
        """Stop the worker and polling before the widgets disappear."""

        self.running = False

        worker = self.worker

        if worker is not None and worker.is_alive():
            # It only posts to a queue, so it can end now rather than
            # holding a reference to this window into Tk teardown.
            worker.join(2.0)

        try:
            self._persist_ai()
        except Exception:
            pass

        if self.poll_id is not None:
            try:
                self.root.after_cancel(self.poll_id)
            except Exception:
                pass

            self.poll_id = None

        if self.plan_window is not None:
            try:
                self.plan_window.grab_release()
                self.plan_window.destroy()
            except tk.TclError:
                pass

            self.plan_window = None

        self._release_tk_objects()

        try:
            self.root.destroy()
        except tk.TclError:
            pass  # already gone

    def _release_tk_objects(self) -> None:
        """Drop Tk variables and images while the interpreter still lives.

        Left alive, they are finalised at interpreter exit, after Tk has
        gone: that prints noise, and from the wrong thread it aborts the
        process with Tcl_AsyncDelete.
        """

        self.icon = None

        for name in (
            "instruction_var",
            "output_var",
            "status_var",
            "provider_var",
            "model_var",
            "endpoint_var",
            "api_key_var",
            "ai_status_var",
            "review_var",
        ):
            setattr(self, name, None)

    def _append(self, line: str, tag: str | None) -> None:
        self.log.configure(state="normal")

        if tag:
            self.log.insert("end", line + "\n", tag)
        else:
            self.log.insert("end", line + "\n")

        self.log.see("end")
        self.log.configure(state="disabled")

    def _clear_log(self) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")


def _label_for(provider: str) -> str:
    preset = PROVIDERS.get(provider)

    return preset.label if preset else provider or "(none)"


def main() -> int:
    argv = sys.argv[1:]

    # No window, no console: the frozen desktop executable runs one job and
    # reports through its exit code. CI uses this to prove the bundle works.
    if argv[:1] == ["--self-test"]:
        # A windowed build has no console, so the self-test narrates itself
        # into a file in the system temp folder as well as into the job.
        import tempfile

        diag = Path(tempfile.gettempdir()) / "office-agent-selftest.txt"
        notes = [f"argv: {argv!r}", f"cwd: {os.getcwd()}"]

        def flush() -> None:
            for target in (diag, job / "self-test-crash.txt"):
                try:
                    target.write_text(
                        "\n".join(notes) + "\n",
                        encoding="utf-8",
                    )
                except OSError:
                    pass

        job = Path(argv[1]) if len(argv) > 1 else Path(".")

        try:
            notes.append(f"job: {job}")
            flush()

            code = self_test(job)

            notes.append(f"exit code: {code}")
            flush()

            return code
        except BaseException:
            import traceback

            notes.append(traceback.format_exc())
            flush()

            return 1

    _enable_dpi_awareness()

    try:
        root = tk.Tk()
    except tk.TclError as exc:
        print(
            "The desktop window needs a graphical session "
            f"({exc}).\n"
            "Use the command line instead: office-agent run <job-folder>",
            file=sys.stderr,
        )
        return 1

    try:
        OfficeAgentWindow(root)
    except Exception:
        import traceback

        traceback.print_exc()

        # A windowed build has no console, so show the failure itself.
        try:
            from tkinter import messagebox

            messagebox.showerror(
                APP_TITLE,
                "The window could not start:\n\n"
                + traceback.format_exc(),
            )
        except Exception:
            pass

        root.destroy()

        return 1

    root.mainloop()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
