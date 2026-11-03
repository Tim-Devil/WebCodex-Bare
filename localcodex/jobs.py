"""One job record per execution; outputs and lifecycle are owned by this service."""
from __future__ import annotations

from datetime import datetime, timezone
import logging
from pathlib import Path
import subprocess
import threading
import time
import uuid

from bootstrap import ROOT, local_environment
from .config import atomic_yaml, read_yaml
from .processes import ProcessTree

log = logging.getLogger(__name__)
ACTIVE = {"starting", "running", "cancelling"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobManager:
    def __init__(self, configuration):
        self.configuration = configuration
        self.lock = threading.RLock()
        self.jobs: dict[str, dict] = {}
        self.trees: dict[str, ProcessTree] = {}
        self.threads: list[threading.Thread] = []
        self.closing = False
        self.failure = None
        directory = ROOT / "runtime/jobs"
        directory.mkdir(parents=True, exist_ok=True)
        for path in directory.glob("*/status.yaml"):
            record = read_yaml(path)
            if record["status"] in ACTIVE:
                record.update(status="interrupted", ended_at=now(), error="Service exited before this job completed")
                atomic_yaml(path, record)
            self.jobs[record["id"]] = record

    def _save(self, record):
        atomic_yaml(ROOT / "runtime/jobs" / record["id"] / "status.yaml", record)

    def start(self, project: str, cwd: Path, argv: list[str], timeout: int | None = None, stdin: str | None = None) -> dict:
        if not argv or any(not isinstance(arg, str) or "\x00" in arg for arg in argv):
            raise ValueError("argv must be a nonempty list of strings without NUL characters")
        if Path(argv[0]).name.lower() in {"powershell", "powershell.exe", "pwsh", "pwsh.exe"}:
            raise ValueError("PowerShell execution is disabled; use Python or literal program arguments")
        limits = self.configuration.current.jobs
        seconds = limits.timeout_seconds if timeout is None else timeout
        if type(seconds) is not int or not 1 <= seconds <= limits.timeout_seconds:
            raise ValueError(f"timeout must be an integer in 1..{limits.timeout_seconds}")
        with self.lock:
            if self.closing:
                raise RuntimeError("Service is stopping")
            if sum(job["status"] in ACTIVE for job in self.jobs.values()) >= limits.max_concurrent:
                raise RuntimeError("Concurrent job limit reached")
            identifier = uuid.uuid4().hex
            record = {"id": identifier, "project": project, "cwd": str(cwd), "argv": argv,
                      "status": "starting", "created_at": now(), "timeout_seconds": seconds,
                      "config_revision": self.configuration.revision, "pid": None, "exit_code": None,
                      "error": None, "ended_at": None}
            directory = ROOT / "runtime/jobs" / identifier
            directory.mkdir()
            output = (directory / "output.log").open("wb")
            source = None
            try:
                if stdin is not None:
                    source = (directory / "stdin.txt").open("w+b")
                    source.write(stdin.encode("utf-8"))
                    source.seek(0)
                tree = ProcessTree(argv, cwd=cwd, env=local_environment(),
                                   stdin=source if source else subprocess.DEVNULL,
                                   stdout=output, stderr=subprocess.STDOUT)
            except BaseException as error:
                record.update(status="failed", error=str(error), ended_at=now())
                self.jobs[identifier] = record
                self._save(record)
                log.exception("job_spawn_failed job=%s project=%s", identifier, project)
                raise
            finally:
                output.close()
                if source:
                    source.close()
            record.update(status="running", pid=tree.pid)
            self.jobs[identifier] = record
            self.trees[identifier] = tree
            try:
                self._save(record)
                thread = threading.Thread(target=self._monitor, args=(identifier, seconds, limits.max_output_bytes), name="job-" + identifier[:8])
                thread.start()
                self.threads.append(thread)
            except BaseException as exception:
                tree.stop()
                self.trees.pop(identifier)
                record.update(status="failed", error=str(exception), ended_at=now())
                log.exception("job_registration_failed job=%s", identifier)
                raise
            log.info("job_started job=%s project=%s pid=%s program=%s timeout=%s", identifier, project, tree.pid, argv[0], seconds)
            return dict(record)

    def _monitor(self, identifier, seconds, output_limit):
        tree = self.trees[identifier]
        deadline = time.monotonic() + seconds
        status, error = "failed", None
        try:
            while tree.poll() is None:
                if time.monotonic() >= deadline:
                    status, error = "timed_out", f"Job exceeded {seconds} seconds"
                    break
                if (ROOT / "runtime/jobs" / identifier / "output.log").stat().st_size > output_limit:
                    status, error = "failed", f"Job exceeded output limit of {output_limit} bytes"
                    break
                with self.lock:
                    if self.jobs[identifier]["status"] == "cancelling":
                        status, error = "cancelled", "Cancellation requested"
                        break
                time.sleep(0.1)
            else:
                status = "succeeded" if tree.process.returncode == 0 else "failed"
                if status == "failed":
                    error = f"Process exited with code {tree.process.returncode}"
            if (ROOT / "runtime/jobs" / identifier / "output.log").stat().st_size > output_limit:
                status, error = "failed", f"Job exceeded output limit of {output_limit} bytes"
        except BaseException as exception:
            status = "failed"
            error = str(exception)
            log.exception("job_monitor_failed job=%s", identifier)
        finally:
            cleaned = False
            try:
                tree.stop()
                cleaned = True
            except BaseException as exception:
                status, error = "failed", f"Process-tree cleanup failed: {exception}"
                self.failure = error
                log.exception("job_cleanup_failed job=%s", identifier)
            with self.lock:
                record = self.jobs[identifier]
                record.update(status=status, error=error, exit_code=tree.process.returncode, ended_at=now())
                self._save(record)
                if cleaned:
                    self.trees.pop(identifier, None)
                log.log(logging.INFO if status == "succeeded" else logging.ERROR,
                        "job_finished job=%s status=%s exit_code=%s error=%s", identifier, status, record["exit_code"], error)

    def read(self, identifier: str, offset: int = 0, limit: int = 32768) -> dict:
        if type(offset) is not int or offset < 0 or not 1 <= limit <= 262144:
            raise ValueError("offset must be >= 0 and limit must be in 1..262144")
        with self.lock:
            record = dict(self.jobs[identifier])
        path = ROOT / "runtime/jobs" / identifier / "output.log"
        with path.open("rb") as stream:
            stream.seek(offset)
            data = stream.read(limit)
        record.update(output=data.decode("utf-8", errors="replace"), next_offset=offset + len(data), output_bytes=path.stat().st_size)
        return record

    def cancel(self, identifier: str) -> dict:
        with self.lock:
            record = self.jobs[identifier]
            if record["status"] in ACTIVE:
                record["status"] = "cancelling"
                self._save(record)
                log.info("job_cancel_requested job=%s", identifier)
            return dict(record)

    def close(self) -> None:
        with self.lock:
            self.closing = True
            for identifier in list(self.trees):
                self.cancel(identifier)
        for thread in self.threads:
            thread.join(timeout=8)
            if thread.is_alive():
                raise RuntimeError(f"Job cleanup exceeded deadline: {thread.name}")
        for tree in list(self.trees.values()):
            tree.stop()
        self.trees.clear()
