"""Explicit start, stop and status with exact service process identity."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback
import uuid

import httpx
import psutil

from bootstrap import ROOT, local_environment, managed_python
from .config import load_settings, read_yaml


def state():
    path = ROOT / "runtime/instance.yaml"
    return read_yaml(path) if path.exists() else None


def alive(record) -> bool:
    if record is None:
        return False
    try:
        process = psutil.Process(record["pid"])
        if process.create_time() != record["process_created"]:
            return False
        command = process.cmdline()
        if "localcodex.service" not in command or record["instance"] not in command:
            raise RuntimeError("Recorded PID belongs to an unexpected command")
        if not command or os.path.normcase(str(Path(command[0]).resolve())) != os.path.normcase(str(managed_python().resolve())):
            raise RuntimeError("Recorded service was launched from an unexpected virtual environment")
        # Windows venv uses a redirector; Linux normally uses an interpreter symlink.
        expected = Path(sys._base_executable).resolve()
        if os.path.normcase(str(Path(process.exe()).resolve())) != os.path.normcase(str(expected)):
            raise RuntimeError("Recorded service uses an unexpected Python executable")
        return True
    except psutil.NoSuchProcess:
        return False


def request(record, method="GET", path="/health"):
    with httpx.Client(trust_env=False, timeout=3) as client:
        return client.request(method, f"http://127.0.0.1:{record['port']}{path}",
                              headers={"Authorization": "Bearer " + record["token"]})


def start():
    settings = load_settings()
    old = state()
    if alive(old):
        response = request(old)
        response.raise_for_status()
        print(json.dumps(response.json(), ensure_ascii=False))
        return
    instance = uuid.uuid4().hex
    with (ROOT / "runtime/console.log").open("ab") as output:
        options = {"creationflags": 0x00000008 | 0x00000200} if os.name == "nt" else {"start_new_session": True}
        process = subprocess.Popen([str(managed_python()), "-B", "-m", "localcodex.service", instance],
                                   cwd=ROOT, env=local_environment(), stdin=subprocess.DEVNULL,
                                   stdout=output, stderr=subprocess.STDOUT, **options)
    deadline = time.monotonic() + settings.tunnel.startup_seconds + 10
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Service exited with code {process.returncode}; see runtime/service.log and runtime/console.log")
        record = state()
        if record and record["instance"] == instance and record["status"] == "ready":
            response = request(record)
            response.raise_for_status()
            print(json.dumps(response.json(), ensure_ascii=False))
            return
        time.sleep(0.1)
    raise TimeoutError(f"Startup exceeded deadline; inspect service PID {process.pid} and runtime/service.log")


def stop():
    record = state()
    if not alive(record):
        print("Service is stopped")
        return
    response = request(record, "POST", "/control/stop")
    response.raise_for_status()
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if not alive(record):
            final = state()
            if final["status"] != "stopped":
                raise RuntimeError(f"Service exited with status {final['status']}: {final['error']}")
            print("Service stopped; owned jobs and tunnel were closed")
            return
        time.sleep(0.1)
    raise TimeoutError("Service did not stop within 30 seconds; inspect runtime/service.log")


def main():
    command = sys.argv[1]
    if command == "start":
        start()
    elif command == "stop":
        stop()
    elif command == "status":
        record = state()
        if alive(record):
            response = request(record)
            response.raise_for_status()
            print(json.dumps(response.json(), ensure_ascii=False, indent=2))
        else:
            print("Service is stopped")
    else:
        raise ValueError("Expected start, stop or status")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
