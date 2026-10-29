"""One on-demand OCR process, with bounded IPC, deadlines and idle retirement."""

from __future__ import annotations

import atexit
import hashlib
import importlib.util
import json
import logging
import os
import queue
import subprocess
import sys
import threading
import time
from contextlib import suppress
from pathlib import Path
from uuid import uuid4

from app.error_reporting import report_error
from app.services.ocr_process_owner import ProcessTreeOwner
from ocr_runtime.native_runtime import PROCESS_ENVIRONMENT
from ocr_runtime.protocol import MAX_REQUEST_BYTES, MAX_RESPONSE_BYTES, OcrRuntimeError, read_message, write_message

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
logger = logging.getLogger(__name__)


def _runtime_command() -> list[str]:
    if getattr(sys, "frozen", False):
        root = Path(sys.executable).parent / "ocr-runtime"
        executable = root / "ticketbox-ocr.exe"
        if not executable.is_file():
            raise OcrRuntimeError("ocr_runtime_unavailable")
        return [str(executable), "--recipe", str(root / "recipe.json"), "--model-root", str(root / "models")]
    spec = importlib.util.find_spec("rapidocr")
    if spec is None or spec.origin is None:
        raise OcrRuntimeError("ocr_runtime_unavailable")
    root = _BACKEND_ROOT / "build/ocr-runtime"
    return [sys.executable, "-m", "ocr_runtime", "--recipe", str(root / "recipe.json"),
            "--model-root", str(root / "models")]


def _worker_environment() -> dict[str, str]:
    # Do not inherit database URLs, pairing tokens, cloud credentials or proxy
    # credentials. The model bundle is local and the child has no DB code.
    names = {"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATH", "PATHEXT", "LANG", "LC_ALL"}
    environment = {key: value for key, value in os.environ.items() if key.upper() in names}
    environment.update(PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
    environment.update(PROCESS_ENVIRONMENT)
    return environment


def ocr_runtime_available() -> bool:
    """Read installation integrity without importing native OCR or waking it."""
    from ocr_runtime.engine import _model_file

    try:
        command = _runtime_command()
        recipe_path = Path(command[command.index("--recipe") + 1])
        model_root = Path(command[command.index("--model-root") + 1])
        recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
        if recipe.get("schema") != 1:
            return False
        entries = [*recipe["models"].values(), recipe["dictionary"]]
        if region := recipe.get("region_recognition"):
            entries.extend([region["model"], region["dictionary"]])
        for entry in entries:
            _model_file(model_root, entry)
        return True
    except (OSError, ValueError, KeyError, TypeError, OcrRuntimeError):
        return False


def configured_ocr_runtime_identity() -> dict:
    """Fingerprint configuration without starting a worker or claiming it was loaded."""
    try:
        command = _CLIENT.command or _runtime_command()
        recipe_bytes = Path(command[command.index("--recipe") + 1]).read_bytes()
        recipe = json.loads(recipe_bytes)
        return {"recipe_sha256": hashlib.sha256(recipe_bytes).hexdigest(), "recipe_name": recipe["name"]}
    except (OSError, ValueError, KeyError, TypeError, IndexError, OcrRuntimeError):
        # Actual admission still reports the runtime failure; this records that
        # no configured identity could be read, never a guessed model version.
        return {"recipe_sha256": None, "recipe_name": None}


class OcrWorkerClient:
    def __init__(self, *, command: list[str] | None = None, idle_seconds: float = 60,
                 timeout_seconds: float = 60, stop_seconds: float = 3) -> None:
        self.command = command
        self.idle_seconds = idle_seconds
        self.timeout_seconds = timeout_seconds
        self.stop_seconds = stop_seconds
        self._call_lock = threading.Lock()
        self._state_lock = threading.RLock()
        self._process: subprocess.Popen | None = None
        self._owner: ProcessTreeOwner | None = None
        self._messages: queue.Queue | None = None
        self._reader: threading.Thread | None = None
        self._timer: threading.Timer | None = None
        self._generation = ""
        self._last_used = 0.0
        self._closed = False

    @property
    def pid(self) -> int | None:
        with self._state_lock:
            return self._process.pid if self._process and self._process.poll() is None else None

    def _start(self) -> None:
        if self._closed:
            raise OcrRuntimeError("ocr_stopping")
        if self._process is not None:
            if self._process.poll() is None:
                return
            self._stop()
        self._generation = str(uuid4())
        # A hidden console can start conhost before the Job is attached. Private
        # pipes need no console; detached startup avoids that unowned helper.
        process = subprocess.Popen(self.command or _runtime_command(), cwd=_BACKEND_ROOT,
                                   env=_worker_environment(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, creationflags=0x00000008 if os.name == "nt" else 0,
                                   start_new_session=os.name != "nt")
        owner = None
        try:
            owner = ProcessTreeOwner(process)
        finally:
            if owner is None:
                process.kill()
                process.wait(timeout=self.stop_seconds)
                for stream in (process.stdin, process.stdout):
                    stream.close()
        self._process, self._owner = process, owner
        self._messages = queue.Queue(maxsize=1)
        self._reader = threading.Thread(target=self._read, args=(process, self._messages),
                                        name="xpj-ocr-pipe", daemon=True)
        self._reader.start()

    @staticmethod
    def _read(process: subprocess.Popen, messages: queue.Queue) -> None:
        try:
            while message := read_message(process.stdout, MAX_RESPONSE_BYTES):
                messages.put_nowait(message)
            messages.put_nowait(OcrRuntimeError("ocr_worker_exited"))
        except (ValueError, OSError, OcrRuntimeError, queue.Full) as exc:
            with suppress(queue.Full):
                messages.put_nowait(OcrRuntimeError("ocr_protocol_invalid") if not isinstance(exc, OcrRuntimeError) else exc)
        except Exception as exc:
            report_error(logger, "OCR pipe reader failed", error=exc)
            with suppress(queue.Full):
                messages.put_nowait(OcrRuntimeError("ocr_protocol_invalid"))

    def recognize(self, path: Path, digest: str, *, region: list[int] | None = None) -> dict:
        if not self._call_lock.acquire(timeout=self.timeout_seconds):
            raise OcrRuntimeError("ocr_busy")
        try:
            with self._state_lock:
                if self._timer:
                    self._timer.cancel()
                self._start()
                generation, messages = self._generation, self._messages
                request_id = str(uuid4())
                write_message(self._process.stdin, {"operation": "recognize_region" if region is not None else "recognize",
                              "generation": generation, "request_id": request_id, "path": str(path),
                              "input_sha256": digest, **({"region": region} if region is not None else {})}, MAX_REQUEST_BYTES)
            return self._receive_result(messages, generation, request_id, digest, region)
        except (OSError, ValueError, KeyError, OcrRuntimeError):
            with self._state_lock:
                if not self._closed:
                    self._stop()
            raise
        finally:
            with self._state_lock:
                self._last_used = time.monotonic()
                # A timer may run immediately. Release the completed call before
                # arming it so a busy callback always belongs to a newer call,
                # whose own completion will schedule retirement again.
                self._call_lock.release()
                if self._process is not None and not self._closed:
                    self._arm_idle_timer(self.idle_seconds)

    def _receive_result(self, messages, generation, request_id, digest, region) -> dict:
        try:
            response = messages.get(timeout=self.timeout_seconds)
        except queue.Empty as exc:
            raise OcrRuntimeError("ocr_timeout") from exc
        if isinstance(response, Exception):
            raise response
        if response.get("generation") != generation or response.get("request_id") != request_id:
            raise OcrRuntimeError("ocr_protocol_invalid")
        if response.get("outcome") != "success":
            raise OcrRuntimeError(response.get("error_code", "ocr_inference_failed"))
        result = response["result"]
        if result.get("input_sha256") != digest:
            raise OcrRuntimeError("ocr_input_changed")
        if region is not None and result.get("region") != region:
            raise OcrRuntimeError("ocr_protocol_invalid")
        return result

    def _arm_idle_timer(self, delay: float) -> None:
        if self._timer:
            self._timer.cancel()
        self._timer = threading.Timer(delay, self._idle_stop, args=(self._generation,))
        self._timer.daemon = True
        self._timer.start()

    def _idle_stop(self, generation: str) -> None:
        if not self._call_lock.acquire(blocking=False):
            return
        try:
            with self._state_lock:
                if self._generation == generation and self._process is not None and not self._closed:
                    remaining = self.idle_seconds - (time.monotonic() - self._last_used)
                    if remaining > 0:
                        self._arm_idle_timer(remaining)
                    else:
                        self._stop()
        except (OSError, TimeoutError, subprocess.TimeoutExpired) as exc:
            with self._state_lock:
                self._closed = True
            report_error(logger, "OCR idle retirement failed; new work remains stopped", error=exc)
        finally:
            self._call_lock.release()

    def _stop(self) -> None:
        process, owner = self._process, self._owner
        if process is None:
            return
        try:
            if process.poll() is None:
                with suppress(BrokenPipeError, OSError):
                    write_message(process.stdin, {"operation": "stop"}, MAX_REQUEST_BYTES)
                with suppress(subprocess.TimeoutExpired):
                    process.wait(timeout=self.stop_seconds)
            # Also retire descendants if the worker has already exited.
            owner.terminate_and_wait(self.stop_seconds)
        except (OSError, TimeoutError, subprocess.TimeoutExpired):
            self._closed = True  # No new generation until this owned tree is gone.
            raise
        finally:
            owner.close()
        for stream in (process.stdin, process.stdout):
            with suppress(OSError):
                stream.close()
        if self._reader:
            self._reader.join(timeout=self.stop_seconds)
        self._process = self._owner = self._messages = self._reader = None

    def close(self) -> None:
        with self._state_lock:
            self._closed = True
            if self._timer:
                self._timer.cancel()
            self._stop()

    def start_service(self) -> None:
        with self._state_lock:
            if self._closed and self._process is not None:
                raise OcrRuntimeError("ocr_stopping")
            self._closed = False


_CLIENT = OcrWorkerClient()
atexit.register(_CLIENT.close)


def recognize_snapshot(path: Path, digest: str) -> dict:
    return _CLIENT.recognize(path, digest)


def recognize_region_snapshot(path: Path, digest: str, region: list[int]) -> dict:
    return _CLIENT.recognize(path, digest, region=region)


def shutdown_ocr_worker() -> None:
    _CLIENT.close()


def start_ocr_worker_service() -> None:
    _CLIENT.start_service()
