"""Desktop front end: choose an instruction, choose a language, press Run."""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from agent import __version__
from agent.runtime import AgentRuntime
from agent.spec import SpecError
from agent.ui import (
    APP_TITLE,
    LANGUAGES,
    default_output_dir,
    describe_state,
    instruction_job_dir,
    is_instruction_file,
    remembered_language,
    save_settings,
    text,
)
from run import build_registry


class OfficeAgentWindow:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.language = remembered_language()
        self.messages: queue.Queue = queue.Queue()
        self.running = False
        self.outputs: list[str] = []

        self.instruction_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.status_var = tk.StringVar()

        self.code_by_label = {
            label: code for code, label in LANGUAGES.items()
        }

        self._build()

        self._apply_language()

        self.status_var.set(text(self.language, "ready"))

        self.root.protocol("WM_DELETE_WINDOW", self.root.destroy)

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _build(self) -> None:
        self.root.minsize(760, 520)

        frame = ttk.Frame(self.root, padding=16)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(5, weight=1)

        self.instruction_label = ttk.Label(frame)
        self.instruction_label.grid(row=0, column=0, sticky="w", pady=4)

        self.instruction_entry = ttk.Entry(
            frame,
            textvariable=self.instruction_var,
        )
        self.instruction_entry.grid(
            row=0, column=1, sticky="ew", padx=(10, 8), pady=4
        )

        self.browse_button = ttk.Button(
            frame,
            command=self.choose_instruction,
        )
        self.browse_button.grid(row=0, column=2, sticky="ew", pady=4)

        self.output_label = ttk.Label(frame)
        self.output_label.grid(row=1, column=0, sticky="w", pady=4)

        self.output_entry = ttk.Entry(
            frame,
            textvariable=self.output_var,
            state="readonly",
        )
        self.output_entry.grid(
            row=1, column=1, columnspan=2, sticky="ew",
            padx=(10, 0), pady=4,
        )

        self.language_label = ttk.Label(frame)
        self.language_label.grid(row=2, column=0, sticky="w", pady=4)

        self.language_combo = ttk.Combobox(
            frame,
            state="readonly",
            width=18,
            values=list(self.code_by_label),
        )
        self.language_combo.grid(
            row=2, column=1, sticky="w", padx=(10, 0), pady=4
        )
        self.language_combo.bind(
            "<<ComboboxSelected>>",
            self.on_language,
        )

        self.run_button = ttk.Button(frame, command=self.run_job)
        self.run_button.grid(
            row=3, column=1, sticky="w", padx=(10, 0), pady=(14, 4)
        )

        self.open_button = ttk.Button(
            frame,
            command=self.open_output,
            state="disabled",
        )
        self.open_button.grid(row=3, column=2, sticky="ew", pady=(14, 4))

        self.status_label = ttk.Label(
            frame,
            textvariable=self.status_var,
            wraplength=700,
        )
        self.status_label.grid(
            row=4, column=0, columnspan=3, sticky="w", pady=(6, 0)
        )

        self.log = tk.Text(
            frame,
            height=10,
            wrap="word",
            state="disabled",
            borderwidth=1,
            relief="solid",
        )
        self.log.grid(
            row=5, column=0, columnspan=3, sticky="nsew", pady=(12, 0)
        )

        scroll = ttk.Scrollbar(
            frame,
            orient="vertical",
            command=self.log.yview,
        )
        scroll.grid(row=5, column=3, sticky="ns", pady=(12, 0))

        self.log.configure(yscrollcommand=scroll.set)

    def _apply_language(self) -> None:
        self.root.title(f"{APP_TITLE} {__version__}")

        self.instruction_label.configure(
            text=text(self.language, "instruction")
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

        chosen = filedialog.askopenfilename(
            title=text(self.language, "select_instruction"),
            initialdir=initial,
            filetypes=[
                (
                    text(self.language, "instruction_filter"),
                    "*.docx *.txt *.md",
                ),
                (text(self.language, "all_files"), "*.*"),
            ],
        )

        if not chosen:
            return

        instruction = Path(chosen).expanduser()

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

        if not self.running and not self.outputs:
            self.status_var.set(text(self.language, "ready"))

    # ------------------------------------------------------------------
    # Running
    # ------------------------------------------------------------------

    def run_job(self) -> None:
        if self.running:
            return

        raw = self.instruction_var.get().strip()

        if not raw:
            self.status_var.set(text(self.language, "no_instruction"))
            return

        instruction = Path(raw).expanduser()

        if not instruction.is_file():
            self.status_var.set(
                text(self.language, "missing_instruction")
            )
            return

        if not is_instruction_file(instruction):
            self.status_var.set(
                text(self.language, "unsupported_instruction")
            )
            return

        self.output_var.set(str(default_output_dir(instruction)))
        self.outputs = []

        self._clear_log()
        self._set_running(True)

        threading.Thread(
            target=self._work,
            args=(instruction,),
            daemon=True,
        ).start()

        self.root.after(120, self._poll)

    def _work(self, instruction: Path) -> None:
        try:
            runtime = AgentRuntime(
                instruction_job_dir(instruction),
                build_registry(),
                instruction_path=instruction,
            )

            state = runtime.run(use_ai=False)

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

        if self.running:
            self.root.after(120, self._poll)

    def _handle(self, kind: str, payload, extra) -> None:
        if kind == "done":
            state = payload

            for line in describe_state(state):
                self._append(line)

            if state.failed_steps:
                failed_id = state.failed_steps[-1]
                result = state.results.get(failed_id)

                reason = (
                    result.error
                    if result is not None and result.error
                    else failed_id
                )

                self._append("")
                self._set_running(False)
                self.status_var.set(
                    text(self.language, "failed", error=reason)
                )
                return

            self.outputs = list(extra)

            for path in self.outputs:
                self._append(path)

            self._set_running(False)
            self.status_var.set(
                text(self.language, "done", count=len(self.outputs))
            )
            return

        self._set_running(False)

        if kind == "nospec":
            self._append(text(self.language, "no_spec"))
            self.status_var.set(text(self.language, "no_spec"))
            return

        message = text(self.language, "failed", error=payload)

        self._append(message)
        self.status_var.set(message)

    def _set_running(self, running: bool) -> None:
        self.running = running

        self.run_button.configure(
            state="disabled" if running else "normal",
            text=text(
                self.language,
                "running" if running else "run",
            ),
        )
        self.browse_button.configure(
            state="disabled" if running else "normal"
        )
        self.open_button.configure(
            state=(
                "normal"
                if self.outputs and not running
                else "disabled"
            )
        )

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------

    def open_output(self) -> None:
        raw = self.output_var.get().strip()

        if not raw:
            self.status_var.set(text(self.language, "no_output"))
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
            self.status_var.set(
                text(self.language, "cannot_open", error=exc)
            )

    def _append(self, line: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", line + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _clear_log(self) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")


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

    OfficeAgentWindow(root)
    root.mainloop()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
