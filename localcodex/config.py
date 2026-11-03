"""One validated configuration snapshot; invalid reloads terminate the service."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
import yaml

from bootstrap import ROOT


class UniqueLoader(yaml.SafeLoader):
    pass


def unique_mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise ValueError(f"Duplicate YAML key {key!r}, line {key_node.start_mark.line + 1}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class Server(Model):
    host: Literal["127.0.0.1"]
    port: int = Field(ge=1024, le=65535)


class Jobs(Model):
    max_concurrent: int = Field(ge=1, le=64)
    timeout_seconds: int = Field(ge=1, le=86400)
    max_output_bytes: int = Field(ge=1024, le=1073741824)


class Files(Model):
    max_bytes: int = Field(ge=1024, le=104857600)


class Logging(Model):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"]
    max_bytes: int = Field(ge=1024, le=1073741824)
    backups: int = Field(ge=1, le=20)


class Tunnel(Model):
    enabled: bool
    health_port: int = Field(ge=1024, le=65535)
    startup_seconds: int = Field(ge=5, le=120)


class Settings(Model):
    server: Server
    projects: dict[str, str] = Field(min_length=1)
    jobs: Jobs
    files: Files
    logging: Logging
    tunnel: Tunnel
    reload_seconds: int = Field(ge=1, le=60)


class Secrets(Model):
    tunnel_id: str = Field(pattern=r"^tunnel_[A-Za-z0-9_-]+$")
    tunnel_api_key: str = Field(min_length=20, repr=False)


def read_yaml(path: Path):
    try:
        return yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueLoader)
    except (yaml.YAMLError, ValueError) as error:
        raise ValueError(f"Invalid YAML in {path.name}: {error}") from error


def confined(path: str | Path, base: Path = ROOT) -> Path:
    resolved = (base / path).resolve()
    if not resolved.is_relative_to(ROOT):
        raise ValueError(f"Path escapes the application directory: {path}")
    return resolved


def load_settings(path: Path = ROOT / "config.yaml") -> Settings:
    settings = Settings.model_validate(read_yaml(path))
    for name, value in settings.projects.items():
        if not name or len(name) > 80:
            raise ValueError("Project names must contain 1..80 characters")
        resolved = confined(value)
        if not resolved.is_dir():
            raise ValueError(f"Project {name!r} directory is missing: {resolved}")
    if settings.server.port == settings.tunnel.health_port:
        raise ValueError("server.port and tunnel.health_port must differ")
    return settings


def load_secrets() -> Secrets:
    try:
        return Secrets.model_validate(read_yaml(ROOT / "secrets.yaml"))
    except ValidationError as error:
        raise ValueError(f"Invalid secrets.yaml fields: {error.errors(include_input=False)}") from None


def fingerprint(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_yaml(path: Path, data) -> None:
    import os
    import uuid
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    with temporary.open("x", encoding="utf-8") as stream:
        yaml.safe_dump(data, stream, allow_unicode=True, sort_keys=False)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


class Configuration:
    def __init__(self, directory: Path = ROOT):
        self.directory = directory
        self.current = load_settings(directory / "config.yaml")
        self.revision = 1
        self.signature = fingerprint(directory / "config.yaml")
        self.secrets_signature = fingerprint(directory / "secrets.yaml")
        self.requirements_signature = fingerprint(directory / "requirements.txt")

    def reload(self) -> bool:
        if fingerprint(self.directory / "secrets.yaml") != self.secrets_signature:
            raise RuntimeError("secrets.yaml changed: service stopped; start again to apply credentials")
        if fingerprint(self.directory / "requirements.txt") != self.requirements_signature:
            raise RuntimeError("requirements.txt changed: service stopped; run python install.py, then start again")
        signature = fingerprint(self.directory / "config.yaml")
        if signature == self.signature:
            return False
        candidate = load_settings(self.directory / "config.yaml")
        if candidate.server != self.current.server or candidate.tunnel != self.current.tunnel:
            raise RuntimeError("server/tunnel configuration changed: service stopped; start again to apply it")
        if candidate.logging.max_bytes != self.current.logging.max_bytes or candidate.logging.backups != self.current.logging.backups:
            raise RuntimeError("Log rotation configuration changed: service stopped; start again to apply it")
        self.current = candidate
        self.signature = signature
        self.revision += 1
        return True
