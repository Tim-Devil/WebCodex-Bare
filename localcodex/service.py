"""One service owns HTTP, configuration reloads, the tunnel and every execution."""
from __future__ import annotations

import asyncio
import contextlib
import hmac
import logging
from logging.handlers import RotatingFileHandler
import os
import platform
import secrets
import socket
import subprocess
import sys
import time

import httpx
import psutil
from starlette.responses import JSONResponse
from starlette.routing import Route
import uvicorn

from bootstrap import ROOT, exclusive_lock, local_environment
from .config import Configuration, atomic_yaml, load_secrets
from .jobs import ACTIVE, JobManager
from .processes import ProcessTree
from .tools import create_mcp

log = logging.getLogger(__name__)


class RedactingFormatter(logging.Formatter):
    def __init__(self, values):
        super().__init__("%(asctime)s %(levelname)s %(name)s %(message)s")
        self.values = values

    def format(self, record):
        message = super().format(record)
        for value in self.values:
            message = message.replace(value, "[REDACTED]")
        return message


class Authentication:
    def __init__(self, app, token):
        self.app, self.token = app, token

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope["headers"])
            expected = ("Bearer " + self.token).encode()
            if not hmac.compare_digest(headers.get(b"authorization", b""), expected):
                log.warning("http_authentication_failed path=%s", scope["path"])
                await JSONResponse({"error": "Bearer authentication required"}, status_code=401)(scope, receive, send)
                return
        await self.app(scope, receive, send)


class Service:
    def __init__(self, instance: str):
        self.configuration = Configuration()
        self.credentials = load_secrets()
        self.token = secrets.token_urlsafe(32)
        settings = self.configuration.current
        handler = RotatingFileHandler(ROOT / "runtime/service.log", maxBytes=settings.logging.max_bytes,
                                      backupCount=settings.logging.backups, encoding="utf-8")
        handler.setFormatter(RedactingFormatter([self.credentials.tunnel_api_key, self.token]))
        logging.basicConfig(handlers=[handler], level=settings.logging.level, force=True)
        logging.getLogger("httpx").setLevel(logging.WARNING)
        self.jobs = JobManager(self.configuration)
        self.stopping = asyncio.Event()
        self.tunnel = None
        self.tunnel_output = None
        self.failure = None
        self.state = {"instance": instance, "pid": os.getpid(),
                      "process_created": psutil.Process().create_time(), "port": settings.server.port,
                      "token": self.token, "status": "starting", "error": None}
        self.write_state()

    def write_state(self):
        atomic_yaml(ROOT / "runtime/instance.yaml", self.state)
        (ROOT / "runtime/instance.yaml").chmod(0o600)

    def status(self):
        with self.jobs.lock:
            active = sum(record["status"] in ACTIVE for record in self.jobs.jobs.values())
        return {"instance": self.state["instance"], "pid": os.getpid(), "status": self.state["status"],
                "config_revision": self.configuration.revision, "active_jobs": active,
                "tunnel_enabled": self.configuration.current.tunnel.enabled,
                "error": self.failure}

    async def health(self, request):
        return JSONResponse(self.status(), status_code=200 if self.state["status"] == "ready" else 503)

    async def stop(self, request):
        log.info("service_stop_requested instance=%s", self.state["instance"])
        self.stopping.set()
        return JSONResponse({"status": "stopping"})

    def start_tunnel(self):
        system = {"Windows": "windows", "Linux": "linux"}[platform.system()]
        arch = {"AMD64": "amd64", "x86_64": "amd64", "aarch64": "arm64", "ARM64": "arm64"}[platform.machine()]
        binary = ROOT / "bin" / f"{system}-{arch}" / ("tunnel-client.exe" if os.name == "nt" else "tunnel-client")
        if not binary.is_file():
            raise RuntimeError(f"Official tunnel client is missing: {binary}; run python install.py")
        settings = self.configuration.current
        profile = {
            "config_version": 1,
            "control_plane": {"base_url": "https://api.openai.com", "tunnel_id": self.credentials.tunnel_id,
                              "api_key": "env:LOCALCODEX_TUNNEL_KEY"},
            "mcp": {"server_urls": [{"channel": "main", "url": f"http://127.0.0.1:{settings.server.port}/mcp"}],
                    "extra_headers": {"Authorization": "env:LOCALCODEX_MCP_AUTH"}},
            "health": {"listen_addr": f"127.0.0.1:{settings.tunnel.health_port}"},
            "log": {"level": "info", "format": "json", "file": str(ROOT / "runtime/tunnel.log")},
            "process": {"pid_file": str(ROOT / "runtime/tunnel.pid")},
            "admin_ui": {"open_browser": False},
        }
        atomic_yaml(ROOT / "runtime/tunnel.yaml", profile)
        env = local_environment()
        for key in list(env):
            if key.startswith(("TUNNEL_CLIENT_", "CONTROL_PLANE_", "MCP_")):
                del env[key]
        env.update(LOCALCODEX_TUNNEL_KEY=self.credentials.tunnel_api_key, LOCALCODEX_MCP_AUTH="Bearer " + self.token)
        self.tunnel_output = (ROOT / "runtime/tunnel-console.log").open("ab")
        self.tunnel = ProcessTree([str(binary), "run", "--config", str(ROOT / "runtime/tunnel.yaml")],
                                  cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                                  stdout=self.tunnel_output, stderr=subprocess.STDOUT)
        log.info("tunnel_started pid=%s source=openai/tunnel-client version=v0.0.19", self.tunnel.pid)

    async def tunnel_ready(self, client) -> bool:
        if self.tunnel.poll() is not None:
            raise RuntimeError(f"Official tunnel client exited with code {self.tunnel.process.returncode}; see runtime/tunnel.log")
        try:
            response = await client.get(f"http://127.0.0.1:{self.configuration.current.tunnel.health_port}/readyz")
        except httpx.ConnectError:
            if self.state["status"] == "starting":
                return False
            raise
        if response.status_code == 503 and self.state["status"] == "starting":
            return False
        response.raise_for_status()
        return True

    async def run(self):
        settings = self.configuration.current
        mcp = create_mcp(self.configuration, self.jobs, self.status)
        app = mcp.streamable_http_app(stateless_http=True, json_response=True, host=settings.server.host,
                                     max_request_body_size=8 * 1024 * 1024)
        app.routes.extend([Route("/health", self.health), Route("/control/stop", self.stop, methods=["POST"])])
        self.server = uvicorn.Server(uvicorn.Config(Authentication(app, self.token), host=settings.server.host,
                                                  port=settings.server.port, log_config=None, access_log=False,
                                                  timeout_graceful_shutdown=5))
        listener = socket.socket()
        server_task = None
        try:
            listener.bind((settings.server.host, settings.server.port))
            listener.listen(128)
            server_task = asyncio.create_task(self.server.serve(sockets=[listener]), name="http-server")
            deadline = time.monotonic() + settings.tunnel.startup_seconds
            while not self.server.started:
                if server_task.done():
                    await server_task
                    raise RuntimeError("HTTP server ended during startup")
                if time.monotonic() >= deadline:
                    raise TimeoutError("HTTP startup deadline exceeded")
                await asyncio.sleep(0.05)
            if settings.tunnel.enabled:
                self.start_tunnel()
                async with httpx.AsyncClient(trust_env=False, timeout=2) as client:
                    while not await self.tunnel_ready(client):
                        if time.monotonic() >= deadline:
                            raise TimeoutError("Tunnel readiness deadline exceeded; see runtime/tunnel.log")
                        await asyncio.sleep(0.25)
            self.state["status"] = "ready"
            self.write_state()
            log.info("service_ready instance=%s port=%s", self.state["instance"], settings.server.port)
            async with httpx.AsyncClient(trust_env=False, timeout=2) as client:
                while not self.stopping.is_set():
                    try:
                        await asyncio.wait_for(self.stopping.wait(), timeout=self.configuration.current.reload_seconds)
                    except TimeoutError:
                        if self.configuration.reload():
                            logging.getLogger().setLevel(self.configuration.current.logging.level)
                            log.info("configuration_reloaded revision=%s", self.configuration.revision)
                        if self.jobs.failure:
                            raise RuntimeError(self.jobs.failure)
                        if server_task.done():
                            await server_task
                            raise RuntimeError("HTTP server stopped unexpectedly")
                        if settings.tunnel.enabled:
                            await self.tunnel_ready(client)
        except BaseException as error:
            self.failure = f"{type(error).__name__}: {error}"
            log.exception("service_failed instance=%s", self.state["instance"])
            raise
        finally:
            self.state.update(status="stopping", error=self.failure)
            self.write_state()
            try:
                await asyncio.to_thread(self.jobs.close)
            finally:
                try:
                    if self.tunnel is not None:
                        self.tunnel.stop()
                    if self.tunnel_output is not None:
                        self.tunnel_output.close()
                finally:
                    self.server.should_exit = True
                    if server_task is not None:
                        await server_task
                    listener.close()
                    self.state.update(status="failed" if self.failure else "stopped", error=self.failure)
                    self.write_state()
                    log.info("service_stopped instance=%s status=%s", self.state["instance"], self.state["status"])


def main():
    os.environ.update(local_environment())
    with exclusive_lock(ROOT / "runtime/service.lock"):
        service = Service(sys.argv[1])
        try:
            asyncio.run(service.run())
        except BaseException as error:
            service.state.update(status="failed", error=f"{type(error).__name__}: {error}")
            service.write_state()
            log.exception("service_exit_failed instance=%s", service.state["instance"])
            raise


if __name__ == "__main__":
    main()
