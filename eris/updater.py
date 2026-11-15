"""Self-update from GitHub: compare VERSION, download the repo zip, swap files, restart.

Your settings/API key live in %APPDATA%\\Eris, so updates never touch them.
"""
import hashlib
import io
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

from . import config

ROOT = Path(__file__).resolve().parent.parent      # the folder with install.bat
SKIP = {".venv", ".git", "__pycache__"}
NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def local_version() -> str:
    try:
        return (ROOT / "VERSION").read_text().strip()
    except OSError:
        return "0"


def _get(url, timeout=10) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "eris-updater"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _raw(path):
    return f"https://raw.githubusercontent.com/{config.UPDATE_REPO}/{config.UPDATE_BRANCH}/{path}"


def remote_version():
    """Returns the newer version string, or None if up to date / offline / not set up."""
    if not config.UPDATE_REPO:
        return None
    try:
        v = _get(_raw("VERSION")).decode().strip()
    except Exception:
        return None
    return v if _key(v) > _key(local_version()) else None


def _key(v):
    return tuple(int(p) if p.isdigit() else 0 for p in v.split("."))


def changes():
    try:
        return _get(_raw("CHANGES.txt")).decode().strip()
    except Exception:
        return ""


def _hash(p: Path):
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()
    except OSError:
        return ""


def install_update(log=print):
    """Download and unpack the latest version over this folder. Returns True on success."""
    url = f"https://codeload.github.com/{config.UPDATE_REPO}/zip/refs/heads/{config.UPDATE_BRANCH}"
    log("info", "Downloading update...")
    data = _get(url, timeout=60)
    old_req = _hash(ROOT / "requirements.txt")
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = z.namelist()
        top = names[0].split("/")[0] + "/"          # GitHub wraps everything in repo-branch/
        for name in names:
            rel = name[len(top):]
            if not rel or rel.endswith("/") or set(Path(rel).parts) & SKIP:
                continue
            dest = ROOT / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_suffix(dest.suffix + ".new")
            tmp.write_bytes(z.read(name))
            os.replace(tmp, dest)
    if _hash(ROOT / "requirements.txt") != old_req:
        log("info", "Installing new requirements (can take a minute)...")
        py = Path(sys.executable).with_name("python.exe") if sys.platform == "win32" else Path(sys.executable)
        r = subprocess.run([str(py), "-m", "pip", "install", "-q", "-r", str(ROOT / "requirements.txt")],
                           cwd=ROOT, capture_output=True, text=True, creationflags=NO_WINDOW)
        if r.returncode == 0 and (ROOT / "requirements-nodeps.txt").exists():
            r = subprocess.run([str(py), "-m", "pip", "install", "-q", "--no-deps", "-r",
                                str(ROOT / "requirements-nodeps.txt")],
                               cwd=ROOT, capture_output=True, text=True, creationflags=NO_WINDOW)
        if r.returncode != 0:
            log("error", "Installing requirements failed:\n" + r.stderr[-1500:])
            return False
    return True


def restart():
    """Start a fresh copy of Eris, then the caller should close this one."""
    exe = sys.executable  # pythonw.exe when launched from the shortcut
    subprocess.Popen([exe, "-m", "eris", "--after-update"], cwd=ROOT, creationflags=NO_WINDOW)
