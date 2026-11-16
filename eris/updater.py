"""Self-update from GitHub: compare VERSION, download the repo zip, swap files, restart.

Your settings/API key live in %APPDATA%\\Eris, so updates never touch them.
"""
import hashlib
import io
import os
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

from . import config

ROOT = Path(__file__).resolve().parent.parent      # the folder with install.bat
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


def remote_version(manual=False):
    """Returns the newer version string, or None if up to date / offline / not set up /
    automatic checks are turned off (manual=True checks anyway)."""
    if not config.UPDATE_REPO or (config.UPDATES == "off" and not manual):
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


# Only these files may ever be written by an update, and only inside Eris's folder.
ALLOWED_TOP = {"VERSION", "CHANGES.txt", "README.md", "LICENSE", ".gitignore", "install.bat",
               "Eris.bat", "requirements.txt", "requirements-nodeps.txt", "requirements.lock",
               "requirements-nodeps.lock"}
MAX_DOWNLOAD = 20 * 1024 * 1024


def _allowed(rel):
    parts = rel.split("/")
    if any(p in ("", ".", "..") or ":" in p or "\\" in p for p in parts):
        return False
    if len(parts) == 1:
        return parts[0] in ALLOWED_TOP
    return len(parts) == 2 and parts[0] == "eris" and parts[1].endswith(".py")


def install_update(log=print, expected=None):
    """Download the latest version, check it, then swap it in. Returns True on success.

    Safety checks: downloaded over HTTPS from the one repo in config; size-capped; every
    file must be one of Eris's own (code in eris/*.py, a few known files at the top)
    and stay inside this folder; the version must be newer than this one (no
    downgrades) and match what was announced. Nothing is changed unless all of it
    checks out. New libraries are installed only from the fingerprint-checked lock."""
    url = f"https://codeload.github.com/{config.UPDATE_REPO}/zip/refs/heads/{config.UPDATE_BRANCH}"
    log("info", "Downloading update...")
    data = _get(url, timeout=60)
    if len(data) > MAX_DOWNLOAD:
        raise ValueError("update is unexpectedly large; not installing it")
    files = {}
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = [n for n in z.namelist() if not n.endswith("/")]
        top = names[0].split("/")[0] + "/"          # GitHub wraps everything in repo-branch/
        for name in names:
            if not name.startswith(top):
                raise ValueError(f"unexpected file in update: {name}")
            rel = name[len(top):]
            if _allowed(rel):
                files[rel] = z.read(name)
            else:
                log("debug", f"update: skipped {rel}")
    new_version = files.get("VERSION", b"").decode().strip()
    if _key(new_version) <= _key(local_version()):
        raise ValueError("that's not newer than what you have; not installing it")
    if expected and new_version != expected:
        raise ValueError("the update changed while downloading; try again")
    for rel in files:                                  # everything must land inside ROOT
        dest = (ROOT / rel).resolve()
        if ROOT.resolve() not in dest.parents:
            raise ValueError(f"unsafe path in update: {rel}")

    old_lock = _hash(ROOT / "requirements.lock") + _hash(ROOT / "requirements-nodeps.lock")
    for rel, content in files.items():
        dest = ROOT / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".new")
        tmp.write_bytes(content)
        os.replace(tmp, dest)
    new_lock = _hash(ROOT / "requirements.lock") + _hash(ROOT / "requirements-nodeps.lock")
    if new_lock != old_lock:
        log("info", "Installing new libraries (fingerprint-checked, can take a minute)...")
        py = Path(sys.executable).with_name("python.exe") if sys.platform == "win32" else Path(sys.executable)
        for args in (["-r", "requirements.lock"], ["--no-deps", "-r", "requirements-nodeps.lock"]):
            r = subprocess.run([str(py), "-m", "pip", "install", "-q", "--require-hashes", *args],
                               cwd=ROOT, capture_output=True, text=True, creationflags=NO_WINDOW)
            if r.returncode != 0:
                log("error", "Installing libraries failed:\n" + r.stderr[-1500:])
                return False
    return True


def restart():
    """Start a fresh copy of Eris, then the caller should close this one."""
    exe = sys.executable  # pythonw.exe when launched from the shortcut
    subprocess.Popen([exe, "-m", "eris", "--after-update"], cwd=ROOT, creationflags=NO_WINDOW)
