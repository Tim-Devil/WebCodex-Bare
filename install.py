"""Install the virtual environment and the verified official tunnel client."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import urllib.request
import venv
import zipfile

from bootstrap import ROOT, exclusive_lock, local_environment, managed_python

TUNNEL_VERSION = "v0.0.19"


def install_tunnel() -> None:
    system = {"Windows": "windows", "Linux": "linux"}[platform.system()]
    arch = {"AMD64": "amd64", "x86_64": "amd64", "aarch64": "arm64", "ARM64": "arm64"}[platform.machine()]
    name = f"tunnel-client-{TUNNEL_VERSION}-{system}-{arch}.zip"
    base = f"https://github.com/openai/tunnel-client/releases/download/{TUNNEL_VERSION}/"
    download = ROOT / ".tmp/downloads"
    download.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(base + "SHA256SUMS.txt", timeout=60) as response:
        sums = response.read().decode()
    matches = [line.split()[0] for line in sums.splitlines()
               if line.split() and line.split()[-1].lstrip("*") == name]
    if len(matches) != 1:
        raise RuntimeError(f"Expected exactly one official SHA256 entry for {name}")
    archive = download / name
    print(f"Downloading openai/tunnel-client {TUNNEL_VERSION} for {system}-{arch}", flush=True)
    with urllib.request.urlopen(base + name, timeout=180) as response, archive.open("wb") as output:
        shutil.copyfileobj(response, output)
    digest = hashlib.sha256()
    with archive.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != matches[0]:
        raise RuntimeError(f"SHA256 mismatch: {name}")
    executable = "tunnel-client.exe" if os.name == "nt" else "tunnel-client"
    destination = ROOT / "bin" / f"{system}-{arch}"
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as package:
        binaries = [item for item in package.infolist() if Path(item.filename).name == executable]
        if len(binaries) != 1:
            raise RuntimeError(f"Expected exactly one {executable} in official archive")
        with package.open(binaries[0]) as source, (destination / executable).open("wb") as target:
            shutil.copyfileobj(source, target)
        for item in package.infolist():
            if Path(item.filename).name in {"LICENSE", "NOTICE", "LICENSE.txt"}:
                (destination / Path(item.filename).name).write_bytes(package.read(item))
    (destination / executable).chmod(0o700)
    (destination / "provenance.yaml").write_text(
        f"repository: https://github.com/openai/tunnel-client\nversion: {TUNNEL_VERSION}\narchive: {name}\nsha256: {matches[0]}\n",
        encoding="utf-8")
    archive.unlink()
    print(f"Official tunnel client verified: {matches[0]}", flush=True)


def main() -> None:
    if sys.version_info < (3, 12):
        raise RuntimeError("Python 3.12 or newer is required")
    if platform.system() not in {"Windows", "Linux"}:
        raise RuntimeError("Supported platforms: Windows and Linux")
    if platform.machine() not in {"AMD64", "x86_64", "aarch64", "ARM64"}:
        raise RuntimeError(f"Unsupported CPU architecture: {platform.machine()}")
    env = local_environment()
    os.environ.update(env)
    with exclusive_lock(ROOT / ".tmp/launcher.lock", wait_seconds=60):
        state = ROOT / "runtime/instance.yaml"
        if state.exists():
            if not managed_python().is_file():
                raise RuntimeError("Existing runtime state found; restore .venv and stop the service before installation")
            # Querying through the existing environment preserves the exact process identity check.
            result = subprocess.run([str(managed_python()), "-B", "-c",
                                     "from localcodex.control import state, alive; raise SystemExit(1 if alive(state()) else 0)"],
                                    cwd=ROOT, env=env, creationflags=0x08000000 if os.name == "nt" else 0)
            if result.returncode:
                raise RuntimeError("Stop the service before installing dependencies; see the process check above")
        marker = ROOT / ".venv/requirements.sha256"
        marker.unlink(missing_ok=True)
        print(f"Creating .venv using Python {platform.python_version()}", flush=True)
        venv.EnvBuilder(with_pip=True).create(ROOT / ".venv")
        subprocess.run([str(managed_python()), "-B", "-m", "pip", "install", "--disable-pip-version-check",
                        "--require-virtualenv", "-r", str(ROOT / "requirements.txt")],
                       cwd=ROOT, env=env, check=True, creationflags=0x08000000 if os.name == "nt" else 0)
        install_tunnel()
        (ROOT / "workspace").mkdir(exist_ok=True)
        if (ROOT / "secrets.yaml").exists():
            (ROOT / "secrets.yaml").chmod(0o600)
        marker.write_text(hashlib.sha256((ROOT / "requirements.txt").read_bytes()).hexdigest() + "\n", encoding="ascii")
        print("Installation complete. Copy secrets.example.yaml to secrets.yaml and fill in your tunnel credentials.", flush=True)


if __name__ == "__main__":
    main()
