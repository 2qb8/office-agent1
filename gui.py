"""Desktop front end: choose an instruction, choose a language, press Run."""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, font as tkfont, ttk

from agent import __version__, ai_config
from agent.llm_factory import PROVIDERS
from agent.registry import build_registry
from agent.runtime import AgentRuntime
from agent.spec import SpecError
from agent.ui import (
    APP_TITLE,
    LANGUAGES,
    default_output_dir,
    describe_state,
    instruction_job_dir,
    is_instruction_file,
    remembered_ai,
    remembered_language,
    save_ai,
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


def asset_path(name: str) -> Path:
    """Where bundled assets live, both from source and inside the exe."""

    base = getattr(sys, "_MEIPASS", None)

    root = Path(base) if base else Path(__file__).resolve().parent

    return root / "assets" / name


class OfficeAgentWindow:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.language = remembered_language()
        self.messages: queue.Queue = queue.Queue()
        self.running = False
        self.outputs: list[str] = []
        self.poll_id: str | None = None
        self.testing = False

        self.instruction_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.status_var = tk.StringVar()
        self.provider_var = tk.StringVar()
        self.model_var = tk.StringVar()
        self.endpoint_var = tk.StringVar()
        self.api_key_var = tk.StringVar()
        self.ai_status_var = tk.StringVar()

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

        body = ttk.Frame(self.root, style="Body.TFrame", padding=(18, 14, 18, 8))
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(2, weight=1)

        self._build_document_card(body)
        self._build_ai_card(body)
        self._build_log(body)
        self._build_footer(body)

        self._set_icon()
        self._center(900, 740)

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
        self.instruction_label.grid(row=0, column=0, sticky="w", pady=(4, 0))

        self.instruction_entry = ttk.Entry(
            self.document_card,
            textvariable=self.instruction_var,
            font=(self.family, 10),
        )
        self.instruction_entry.grid(
            row=0, column=1, sticky="ew", padx=(12, 8), pady=(4, 0)
        )

        self.browse_button = ttk.Button(
            self.document_card,
            command=self.choose_instruction,
        )
        self.browse_button.grid(row=0, column=2, sticky="ew", pady=(4, 0))

        self.instruction_hint = ttk.Label(
            self.document_card, style="Muted.TLabel"
        )
        self.instruction_hint.grid(
            row=1, column=1, columnspan=2, sticky="w", padx=(12, 0)
        )

        self.output_label = ttk.Label(
            self.document_card, style="Path.TLabel"
        )
        self.output_label.grid(row=2, column=0, sticky="w", pady=(10, 0))

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
            pady=(10, 0),
        )

        self.language_label = ttk.Label(
            self.document_card, style="Path.TLabel"
        )
        self.language_label.grid(row=3, column=0, sticky="w", pady=(10, 0))

        self.language_combo = ttk.Combobox(
            self.document_card,
            state="readonly",
            width=16,
            values=list(self.code_by_label),
            font=(self.family, 10),
        )
        self.language_combo.grid(
            row=3, column=1, sticky="w", padx=(12, 0), pady=(10, 0)
        )
        self.language_combo.bind("<<ComboboxSelected>>", self.on_language)

    def _build_ai_card(self, parent: ttk.Frame) -> None:
        self.ai_card = ttk.LabelFrame(
            parent,
            style="Card.TLabelframe",
            padding=(14, 8, 14, 10),
        )
        self.ai_card.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        self.ai_card.columnconfigure(1, weight=1)

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
        self.endpoint_label.grid(row=1, column=0, sticky="w", pady=(8, 0))

        self.endpoint_entry = ttk.Entry(
            self.ai_card,
            textvariable=self.endpoint_var,
            font=(self.family, 10),
        )
        self.endpoint_entry.grid(
            row=1, column=1, columnspan=3, sticky="ew",
            padx=(12, 0), pady=(8, 0),
        )
        self.endpoint_entry.bind("<FocusOut>", self._on_ai_edit)

        self.key_label = ttk.Label(self.ai_card, style="Path.TLabel")
        self.key_label.grid(row=2, column=0, sticky="w", pady=(8, 0))

        self.key_entry = ttk.Entry(
            self.ai_card,
            textvariable=self.api_key_var,
            show="•",
            font=(self.family, 10),
        )
        self.key_entry.grid(
            row=2, column=1, columnspan=2, sticky="ew",
            padx=(12, 12), pady=(8, 0),
        )
        self.key_entry.bind("<FocusOut>", self._on_ai_edit)

        self.test_button = ttk.Button(
            self.ai_card,
            command=self.test_connection,
            width=17,
        )
        self.test_button.grid(row=2, column=3, sticky="ew", pady=(8, 0))

        self.ai_status_label = ttk.Label(
            self.ai_card,
            textvariable=self.ai_status_var,
            style="Muted.TLabel",
            wraplength=760,
        )
        self.ai_status_label.grid(
            row=3, column=0, columnspan=4, sticky="w", pady=(10, 0)
        )

        self.ai_hint_label = ttk.Label(
            self.ai_card, style="Muted.TLabel", wraplength=760
        )
        self.ai_hint_label.grid(row=4, column=0, columnspan=4, sticky="w")

    def _build_log(self, parent: ttk.Frame) -> None:
        self.log_card = ttk.LabelFrame(
            parent,
            style="Card.TLabelframe",
            padding=(10, 6, 10, 10),
        )
        self.log_card.grid(row=2, column=0, sticky="nsew", pady=(12, 0))
        self.log_card.columnconfigure(0, weight=1)
        self.log_card.rowconfigure(0, weight=1)

        mono = self._mono_family()

        self.log = tk.Text(
            self.log_card,
            height=10,
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
        self.status_label.grid(row=3, column=0, sticky="w", pady=(10, 6))

        footer = ttk.Frame(parent, style="Body.TFrame")
        footer.grid(row=4, column=0, sticky="ew")
        footer.columnconfigure(2, weight=1)

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

        self.progress = ttk.Progressbar(
            footer,
            mode="indeterminate",
            length=170,
        )
        self.progress.grid(row=0, column=3, sticky="e")

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

    def _center(self, width: int, height: int) -> None:
        try:
            screen_width = self.root.winfo_screenwidth()
            screen_height = self.root.winfo_screenheight()

            x = max(0, (screen_width - width) // 2)
            y = max(0, (screen_height - height) // 3)

            self.root.geometry(f"{width}x{height}+{x}+{y}")
        except tk.TclError:
            self.root.geometry(f"{width}x{height}")

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

        threading.Thread(
            target=self._test_ai,
            args=(ai_config.from_values(values),),
            daemon=True,
        ).start()

    def _test_ai(self, config) -> None:
        try:
            ok, detail = ai_config.test_connection(config)
        except Exception as exc:  # shown in the window, never a crash
            ok, detail = False, str(exc)

        self.messages.put(("ai_ok" if ok else "ai_fail", detail, None))

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

        threading.Thread(
            target=self._work,
            args=(instruction,),
            daemon=True,
        ).start()

    def _work(self, instruction: Path) -> None:
        try:
            runtime = AgentRuntime(
                instruction_job_dir(instruction),
                build_registry(),
                instruction_path=instruction,
            )

            # A spec in the instruction always wins; AI is used only for
            # instructions that have none, and only when configured.
            state = runtime.run()

            self.messages.put(
                ("done", state, runtime.output_files(state))
            )

        except SpecError:
            self.messages.put(("nospec", None, None))

        except Exception as exc:  # surfaced in the window, not a crash
            self.messages.put(("error", exc, None))

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

                self._set_running(False)
                self._set_status(
                    text(self.language, "failed", error=reason),
                    FAILURE,
                )
                return

            self.outputs = list(extra)

            for path in self.outputs:
                self._append("", None)
                self._append(path, "path")

            self._set_running(False)
            self._set_status(
                text(self.language, "done", count=len(self.outputs)),
                SUCCESS,
            )
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

        if kind == "nospec":
            message = text(self.language, "no_spec")
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

        if running:
            self.progress.start(14)
        else:
            self.progress.stop()

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

    def close(self) -> None:
        """Stop polling before the widgets disappear."""

        self.running = False

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

        self.root.destroy()

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
