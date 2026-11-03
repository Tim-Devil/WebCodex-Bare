"""Standard-library launcher for the local virtual environment."""
from __future__ import annotations

import contextlib
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parent


def local_environment() -> dict[str, str]:
    env = os.environ.copy()
    paths = {
        "TMP": ".tmp", "TEMP": ".tmp", "TMPDIR": ".tmp",
        "PIP_CACHE_DIR": ".cache/pip", "UV_CACHE_DIR": ".cache/uv",
        "XDG_CACHE_HOME": ".cache", "XDG_CONFIG_HOME": "runtime/config",
        "XDG_DATA_HOME": "runtime/data", "XDG_STATE_HOME": "runtime/state",
        "APPDATA": "runtime/appdata", "LOCALAPPDATA": "runtime/localappdata",
        "GOCACHE": ".cache/go-build", "GOMODCACHE": ".cache/go-mod",
        "GOPATH": ".cache/go", "GOTMPDIR": ".tmp", "npm_config_cache": ".cache/npm",
    }
    for name, relative in paths.items():
        path = ROOT / relative
        path.mkdir(parents=True, exist_ok=True)
        env[name] = str(path)
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1", PYTHONUTF8="1",
               PYTHONUNBUFFERED="1", PIP_CONFIG_FILE=os.devnull, GOTELEMETRY="off",
               GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="Never")
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    prefix = ROOT / ".venv"
    binaries = prefix / ("Scripts" if os.name == "nt" else "bin")
    env["PATH"] = str(binaries) + os.pathsep + env.get("PATH", "")
    env["VIRTUAL_ENV"] = str(prefix)
    return env


@contextlib.contextmanager
def exclusive_lock(path: Path, wait_seconds: float = 0):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        handle.seek(0)
        if os.fstat(handle.fileno()).st_size == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        deadline = time.monotonic() + wait_seconds
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as error:
                import errno
                if error.errno not in {errno.EACCES, errno.EAGAIN} or time.monotonic() >= deadline:
                    raise
                time.sleep(0.05)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def managed_python() -> Path:
    return ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def run(command: str) -> int:
    if command not in {"start", "stop", "status"}:
        raise ValueError("Command must be start, stop or status")
    env = local_environment()
    with exclusive_lock(ROOT / ".tmp/launcher.lock", wait_seconds=60):
        python = managed_python()
        if not python.is_file():
            raise RuntimeError("Local .venv is missing. Run python install.py first.")
        if command == "start":
            expected = hashlib.sha256((ROOT / "requirements.txt").read_bytes()).hexdigest()
            marker = ROOT / ".venv/requirements.sha256"
            if not marker.is_file() or marker.read_text().strip() != expected:
                raise RuntimeError("Dependencies need installation. Run python install.py, then start again.")
        return subprocess.run([str(python), "-B", "-m", "localcodex.control", command],
                              cwd=ROOT, env=env, stdout=sys.stdout, stderr=sys.stderr,
                              creationflags=0x08000000 if os.name == "nt" else 0).returncode


def main(command: str, gui: bool = False) -> int:
    log = ROOT / "runtime/launcher.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as stream:
        stream.write(f"\n{time.strftime('%Y-%m-%d %H:%M:%S')} action={command} gui={gui}\n")
    try:
        if gui:
            with log.open("a", encoding="utf-8") as stream, contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
                code = run(command)
        else:
            code = run(command)
        if code:
            raise RuntimeError(f"{command} failed with exit code {code}. See runtime/service.log and runtime/launcher.log.")
        return 0
    except Exception as error:
        with log.open("a", encoding="utf-8") as stream:
            traceback.print_exc(file=stream)
        if gui and os.name == "nt":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, f"{error}\n\nLog: {log}", "WebCodex-Bare", 0x10)
        else:
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
