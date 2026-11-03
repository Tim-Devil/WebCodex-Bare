"""Small, direct tools for project files and owned command jobs."""
from __future__ import annotations

import base64
import fnmatch
import hashlib
import logging
import os
from pathlib import Path
import threading
from typing import Any, Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from bootstrap import managed_python
from . import __version__
from .config import resolve_path

log = logging.getLogger(__name__)


class FileTools:
    def __init__(self, configuration):
        self.configuration = configuration
        self.lock = threading.RLock()

    def path(self, project: str, relative: str = ".") -> Path:
        base = resolve_path(self.configuration.current.projects[project])
        return resolve_path(relative, base)

    def read(self, project: str, path: str) -> bytes:
        target = self.path(project, path)
        if target.stat().st_size > self.configuration.current.files.max_bytes:
            raise ValueError("File exceeds files.max_bytes")
        data = target.read_bytes()
        if len(data) > self.configuration.current.files.max_bytes:
            raise ValueError("File grew beyond files.max_bytes during read")
        return data

    def write(self, project: str, path: str, data: bytes, expected_sha256: str | None) -> dict:
        import tempfile
        if len(data) > self.configuration.current.files.max_bytes:
            raise ValueError("Content exceeds files.max_bytes")
        with self.lock:
            target = self.path(project, path)
            previous_mode = None
            if target.exists():
                if not expected_sha256:
                    raise ValueError("Existing file requires expected_sha256 from read_file")
                actual = hashlib.sha256(self.read(project, path)).hexdigest()
                if actual != expected_sha256:
                    raise ValueError(f"File changed since read: {path}; read it again")
                if target.stat().st_nlink != 1:
                    raise ValueError("Writes to hard-linked files are disabled")
                previous_mode = target.stat().st_mode & 0o777
            elif expected_sha256 is not None:
                raise ValueError("Expected an existing file, but the target is absent")
            target.parent.mkdir(parents=True, exist_ok=True)
            target = self.path(project, path)
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".localcodex-", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            if previous_mode is not None:
                temporary.chmod(previous_mode)
            temporary.replace(target)
            log.info("file_written project=%s path=%s bytes=%s", project, path, len(data))
            return {"path": path, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def create_mcp(configuration, jobs, get_status):
    import functools
    import inspect
    import time

    mcp = MCPServer("WebCodex-Bare", version=__version__, instructions=
                    "Select a configured project. Read files before editing and pass the returned SHA-256. "
                    "run_process/run_python/git return job IDs; observe the same job with read_job. "
                    "Tool failures are explicit; inspect their cause before issuing another side effect. "
                    "Commands use literal argv and the current user's permissions. PowerShell is disabled.")
    files = FileTools(configuration)

    def tool(function):
        @functools.wraps(function)
        def checked(*args, **kwargs):
            started = time.monotonic()
            log.info("tool_started name=%s", function.__name__)
            try:
                result = function(*args, **kwargs)
                log.info("tool_finished name=%s elapsed_ms=%.1f", function.__name__, (time.monotonic() - started) * 1000)
                return result
            except Exception as error:
                log.exception("tool_failed name=%s", function.__name__)
                raise ToolError(f"{type(error).__name__}: {error}") from error
        checked.__signature__ = inspect.signature(function, eval_str=True)
        mcp.tool(structured_output=True)(checked)
        return checked

    @tool
    def get_status_tool() -> dict[str, Any]:
        """Read service readiness, configuration revision and active job count."""
        return get_status()

    @tool
    def list_projects() -> dict[str, Any]:
        """List project names and resolved absolute working directories from config.yaml."""
        return {"projects": configuration.current.projects, "config_revision": configuration.revision}

    @tool
    def list_files(project: str, path: str = ".", limit: int = 200) -> dict[str, Any]:
        """List one directory using an absolute path or a path relative to the selected project. limit: 1..1000."""
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be in 1..1000")
        directory = files.path(project, path)
        entries = sorted(directory.iterdir(), key=lambda p: p.name.casefold())
        rows = [{"name": p.name, "directory": p.is_dir(), "symlink": p.is_symlink(),
                 "bytes": p.lstat().st_size} for p in entries[:limit]]
        return {"entries": rows, "total": len(entries), "truncated": len(entries) > limit}

    @tool
    def read_file(project: str, path: str, encoding: Literal["utf-8", "base64"] = "utf-8",
                  offset: int = 0, limit: int = 65536) -> dict[str, Any]:
        """Read a byte range and the full-file SHA-256. limit: 1..262144. Continue at next_offset. Use base64 for binary files or UTF-8 byte boundaries."""
        if offset < 0 or not 1 <= limit <= 262144:
            raise ValueError("offset must be >= 0; limit must be in 1..262144")
        data = files.read(project, path)
        if offset > len(data):
            raise ValueError("offset exceeds the file size")
        chunk = data[offset:offset + limit]
        if encoding == "utf-8":
            import codecs
            decoder = codecs.getincrementaldecoder("utf-8")("strict")
            content = decoder.decode(chunk, final=offset + len(chunk) >= len(data))
            buffered = len(decoder.getstate()[0])
            chunk = chunk[:len(chunk) - buffered] if buffered else chunk
            if offset < len(data) and not chunk:
                raise ValueError("limit is too small for the next UTF-8 character")
        else:
            content = base64.b64encode(chunk).decode("ascii")
        return {"path": path, "content": content, "encoding": encoding,
                "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                "next_offset": offset + len(chunk), "complete": offset + len(chunk) >= len(data)}

    @tool
    def write_file(project: str, path: str, content: str, expected_sha256: str | None = None,
                   encoding: Literal["utf-8", "base64"] = "utf-8") -> dict[str, Any]:
        """Create or replace one bounded file. Existing files require the last read_file SHA-256; new files use null."""
        data = content.encode("utf-8") if encoding == "utf-8" else base64.b64decode(content, validate=True)
        return files.write(project, path, data, expected_sha256)

    @tool
    def replace_text(project: str, path: str, old: str, new: str, expected_sha256: str) -> dict[str, Any]:
        """Replace exactly one occurrence of old text, guarded by the full-file SHA-256 from read_file."""
        if not old:
            raise ValueError("old must be nonempty")
        with files.lock:
            content = files.read(project, path).decode("utf-8")
            count = content.count(old)
            if count != 1:
                raise ValueError(f"Expected one occurrence, found {count}")
            return files.write(project, path, content.replace(old, new, 1).encode("utf-8"), expected_sha256)

    @tool
    def search_text(project: str, text: str, path: str = ".", file_glob: str = "*", limit: int = 100) -> dict[str, Any]:
        """Search literal UTF-8 text in project files. Skips symlinks, binary/oversized files and generated directories. Reports scan limits."""
        if not text or not 1 <= limit <= 1000:
            raise ValueError("text must be nonempty; limit must be in 1..1000")
        base = files.path(project)
        directory = files.path(project, path)
        if not directory.is_dir():
            raise NotADirectoryError(f"Search directory is missing or is not a directory: {directory}")
        matches, skipped, scanned = [], 0, 0
        excluded = {".git", ".cache", ".tmp", ".venv", "__pycache__", "node_modules", "runtime", "bin"}
        for current, directories, names in os.walk(directory, followlinks=False):
            directories[:] = sorted(d for d in directories if d not in excluded and not (Path(current) / d).is_symlink())
            for name in sorted(names):
                target = Path(current) / name
                if not fnmatch.fnmatch(name, file_glob) or target.is_symlink():
                    continue
                scanned += 1
                if scanned > 10000:
                    return {"matches": matches, "truncated": True, "scan_limit": 10000, "skipped_files": skipped}
                relative = target.relative_to(base).as_posix() if target.is_relative_to(base) else str(target)
                if target.stat().st_size > configuration.current.files.max_bytes:
                    skipped += 1
                    continue
                data = files.read(project, relative)
                try:
                    content = data.decode("utf-8")
                except UnicodeDecodeError:
                    skipped += 1
                    continue
                for number, line in enumerate(content.splitlines(), 1):
                    if text in line:
                        matches.append({"path": relative, "line": number, "text": line[:2000]})
                        if len(matches) >= limit:
                            return {"matches": matches, "truncated": True, "skipped_files": skipped}
        return {"matches": matches, "truncated": False, "skipped_files": skipped, "scanned_files": scanned}

    @tool
    def run_process(project: str, argv: list[str], cwd: str = ".", timeout_seconds: int | None = None,
                    stdin: str | None = None) -> dict[str, Any]:
        """Start one background process using literal argv, without shell parsing. Returns a job ID. Poll read_job; use cancel_job to stop its process tree."""
        return jobs.start(project, files.path(project, cwd), argv, timeout_seconds, stdin)

    @tool
    def run_python(project: str, code: str, cwd: str = ".", timeout_seconds: int | None = None) -> dict[str, Any]:
        """Execute Python code in the local .venv as a background job. Code is passed on stdin."""
        return jobs.start(project, files.path(project, cwd), [str(managed_python()), "-B", "-"], timeout_seconds, code)

    @tool
    def git(project: str, args: list[str], timeout_seconds: int | None = None) -> dict[str, Any]:
        """Run explicit Git arguments in a project as a background job; returns a job ID. All Git side effects follow the supplied arguments."""
        return jobs.start(project, files.path(project), ["git", *args], timeout_seconds)

    @tool
    def read_job(job_id: str, offset: int = 0, limit: int = 32768) -> dict[str, Any]:
        """Read one job status and a bounded output chunk. Continue at next_offset. Terminal statuses: succeeded, failed, timed_out, cancelled, interrupted."""
        return jobs.read(job_id, offset, limit)

    @tool
    def list_jobs(limit: int = 50) -> dict[str, Any]:
        """List newest job records, including failures. limit: 1..200."""
        if not 1 <= limit <= 200:
            raise ValueError("limit must be in 1..200")
        with jobs.lock:
            values = sorted(jobs.jobs.values(), key=lambda job: job["created_at"], reverse=True)
            return {"jobs": [dict(value) for value in values[:limit]], "total": len(values)}

    @tool
    def cancel_job(job_id: str) -> dict[str, Any]:
        """Request cancellation of one owned job and its descendants; observe read_job until terminal."""
        return jobs.cancel(job_id)

    return mcp
