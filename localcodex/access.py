"""Explicit tool switches and local file access rules."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

from .config import Settings

log = logging.getLogger(__name__)
READ_TOOLS = {"list_files", "read_file", "search_text"}
WRITE_TOOLS = {"write_file", "replace_text"}
EXECUTE_TOOLS = {"run_process", "run_python", "git"}


def tool_denial(settings: Settings, name: str) -> str | None:
    if not getattr(settings.tools, name):
        return f"tools.{name} is false"
    if name in READ_TOOLS and not settings.permissions.read:
        return "permissions.read is empty"
    if name in WRITE_TOOLS and not settings.permissions.write:
        return "permissions.write is empty"
    if name in EXECUTE_TOOLS and not settings.permissions.execute:
        return "permissions.execute is false"
    return None


def require_tool(settings: Settings, name: str) -> None:
    reason = tool_denial(settings, name)
    if reason:
        raise PermissionError(f"Tool {name!r} denied: {reason}")


def require_path(settings: Settings, operation: Literal["read", "write"], target: Path) -> None:
    roots = getattr(settings.permissions, operation)
    if roots == ["*"] or any(target.is_relative_to(Path(root)) for root in roots):
        log.debug("file_access_allowed operation=%s path=%r", operation, str(target))
        return
    log.warning("file_access_denied operation=%s path=%r allowed_roots=%r", operation, str(target), roots)
    raise PermissionError(f"{operation} access denied for {target}; allowed roots: {roots}")
