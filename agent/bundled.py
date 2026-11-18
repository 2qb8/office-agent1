"""A planning model that comes with the app: llama-server plus one GGUF file.

This is a prototype and it is off unless ``OFFICE_AGENT_BUNDLED_MODEL=1``.
When it is on, the ``bundled`` provider downloads the model once (checking
its SHA-256), starts ``llama-server`` from llama.cpp on loopback and hands
the existing OpenAI-compatible client a base URL. No account, no API key,
and after the first download no network at all.

Everything here fails with a sentence a user can act on: no server binary,
no space, a checksum that does not match, a server that never becomes
ready. Nothing here is imported on the normal path, so with the flag unset
the app behaves exactly as before.
"""

from __future__ import annotations

import atexit
import hashlib
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Callable

FLAG_ENV = "OFFICE_AGENT_BUNDLED_MODEL"
PROVIDER = "bundled"

DEFAULT_PORT = 8477
START_TIMEOUT = 120
GENERATE_TIMEOUT = 600
MODEL_BYTES = 986_048_768

# Qwen2.5-1.5B-Instruct, Q4_K_M: about 1 GB, comfortable on 4 GB of RAM.
MODEL_FILE = "Qwen2.5-1.5B-Instruct-Q4_K_M.gguf"
MODEL_URL = (
    "https://huggingface.co/bartowski/Qwen2.5-1.5B-Instruct-GGUF"
    "/resolve/main/Qwen2.5-1.5B-Instruct-Q4_K_M.gguf"
)
MODEL_SHA256 = (
    "1adf0b11065d8ad2e8123ea110d1ec956dab4ab038eab665614adba04b6c3370"
)

CHUNK = 1024 * 1024


class BundledError(RuntimeError):
    """Something the user has to fix, said in plain words."""


def enabled() -> bool:
    return os.environ.get(FLAG_ENV, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def preset():
    """The provider entry the GUI and the factory both read."""

    from agent.llm_factory import ProviderPreset

    return ProviderPreset(
        label="Bundled (offline)",
        base_url=f"http://127.0.0.1:{DEFAULT_PORT}/v1",
        model="bundled",
        requires_key=False,
    )


def models_dir() -> Path:
    override = os.environ.get("OFFICE_AGENT_MODELS", "").strip()

    if override:
        return Path(override).expanduser()

    if sys.platform == "win32":
        base = Path(
            os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local"
        )
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(
            os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share"
        )

    return base / "office-agent" / "models"


def model_path() -> Path:
    return models_dir() / MODEL_FILE


def server_log_path() -> Path:
    """Where the server's own output goes, so a failed start can be read."""

    return models_dir() / "llama-server.log"


def timeout_seconds() -> int:
    """How long one planning call may take. A slow CPU needs more."""

    raw = os.environ.get("OFFICE_AGENT_BUNDLED_TIMEOUT", "").strip()

    if not raw:
        return GENERATE_TIMEOUT

    try:
        value = int(raw)
    except ValueError:
        return GENERATE_TIMEOUT

    return value if value > 0 else GENERATE_TIMEOUT


def find_server() -> str | None:
    """The llama-server binary: an explicit path first, then the PATH."""

    override = os.environ.get("OFFICE_AGENT_LLAMA_SERVER", "").strip()

    if override:
        return override if Path(override).is_file() else None

    return shutil.which("llama-server")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            digest.update(block)

    return digest.hexdigest()


def ensure_model(
    progress: Callable[[int, int], None] | None = None,
) -> Path:
    """Download the model once, and only keep it if the hash matches."""

    target = model_path()

    if target.is_file():
        if _sha256(target) == MODEL_SHA256:
            return target

        # A half-written or corrupted file is worth less than a download.
        target.unlink()

    target.parent.mkdir(parents=True, exist_ok=True)

    free = shutil.disk_usage(target.parent).free

    if free < MODEL_BYTES:
        raise BundledError(
            f"The offline model needs about "
            f"{MODEL_BYTES // (1024 * 1024)} MB and that folder has "
            f"{free // (1024 * 1024)} MB free. Free some space, or point "
            f"OFFICE_AGENT_MODELS at another disk."
        )

    temporary = target.with_name(target.name + ".part")

    digest = hashlib.sha256()
    written = 0

    try:
        with urllib.request.urlopen(MODEL_URL, timeout=60) as response:
            total = int(response.headers.get("Content-Length") or 0)

            with temporary.open("wb") as handle:
                for block in iter(lambda: response.read(CHUNK), b""):
                    handle.write(block)
                    digest.update(block)
                    written += len(block)

                    if progress is not None:
                        progress(written, total)
    except OSError as error:
        temporary.unlink(missing_ok=True)

        raise BundledError(
            f"Could not download the offline model: {error}. "
            f"Check the connection and try again."
        ) from None

    if digest.hexdigest() != MODEL_SHA256:
        temporary.unlink(missing_ok=True)

        raise BundledError(
            f"The downloaded model does not match its checksum "
            f"({digest.hexdigest()[:12]}… instead of {MODEL_SHA256[:12]}…). "
            f"Nothing was kept; try again."
        )

    temporary.replace(target)

    return target


def server_command(
    server: str,
    model: Path,
    port: int = DEFAULT_PORT,
) -> list[str]:
    """llama.cpp's server, on loopback, CPU only, ready for chat."""

    return [
        server,
        "--model",
        str(model),
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        # 32k overflowed a 3 GB machine's memory: the KV cache alone is
        # about a gigabyte. 16k holds the largest brief seen so far, and a
        # cap on the reply keeps a rambling model from filling it.
        "--ctx-size",
        "16384",
        "--n-predict",
        "2500",
        "--n-gpu-layers",
        "0",
        "--no-webui",
    ]


def _port_free(port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(0.5)

        return probe.connect_ex(("127.0.0.1", port)) != 0


class BundledServer:
    """One llama-server process, started on first use and stopped at exit."""

    def __init__(self, port: int | None = None) -> None:
        self.port = port or int(
            os.environ.get("OFFICE_AGENT_BUNDLED_PORT") or DEFAULT_PORT
        )
        self.process: subprocess.Popen | None = None

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    @property
    def health_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/health"

    def running(self) -> bool:
        if self.process is not None and self.process.poll() is None:
            return True

        # Something else may already be listening on the port — a second
        # window, or a server the user started by hand.
        return not _port_free(self.port)

    def start(self) -> None:
        if self.running():
            return

        server = find_server()

        if server is None:
            raise BundledError(
                "llama-server was not found. Install llama.cpp and put "
                "llama-server on the PATH, or set "
                "OFFICE_AGENT_LLAMA_SERVER to its full path."
            )

        model = ensure_model()

        # The server's own output is the only record of why it refused to
        # start, so it is kept beside the model rather than discarded.
        log = server_log_path().open("a", encoding="utf-8")

        self.process = subprocess.Popen(
            server_command(server, model, self.port),
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
        )

        log.close()

        atexit.register(self.stop)

        self.wait_ready()

    def wait_ready(self, timeout: float = START_TIMEOUT) -> None:
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            if self.process is not None and self.process.poll() is not None:
                raise BundledError(
                    "llama-server stopped while starting up. Run it by hand "
                    "to see why, for example: llama-server -m <model.gguf>"
                )

            try:
                with urllib.request.urlopen(self.health_url, timeout=2) as reply:
                    if reply.status == 200:
                        return
            except OSError:
                pass

            time.sleep(0.5)

        self.stop()

        raise BundledError(
            f"llama-server did not answer on port {self.port} within "
            f"{int(timeout)}s. A smaller model, or a machine with more "
            f"memory, will start faster."
        )

    def stop(self) -> None:
        if self.process is None or self.process.poll() is not None:
            return

        self.process.terminate()

        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=10)


_server: BundledServer | None = None


def serve() -> BundledServer:
    """Start the server once per process and reuse it."""

    global _server

    if _server is None:
        _server = BundledServer()

    _server.start()

    return _server


def create_client():
    """The client the planner uses when the bundled provider is picked."""

    from agent.llm import OpenAICompatibleLLM

    if not enabled():
        raise BundledError(
            "The bundled model is off. Set "
            f"{FLAG_ENV}=1 to use it (it downloads about 1 GB once)."
        )

    server = serve()

    # The planner is the only thing this client does, so the plan's JSON
    # shape travels with every request. llama.cpp turns it into a grammar.
    from agent.plan_schema import response_format

    return OpenAICompatibleLLM(
        base_url=server.base_url,
        api_key="local",
        model="bundled",
        timeout=timeout_seconds(),
        response_format=response_format(),
        max_attempts=1,
    )


def describe() -> str:
    """One line for a window or a log: what the bundled provider would do."""

    state = "on" if enabled() else "off"

    return (
        f"Bundled model: {state}; {MODEL_FILE} in {models_dir()}; "
        f"llama-server {'found' if find_server() else 'missing'}"
    )
