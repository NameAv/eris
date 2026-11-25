"""Eris Unity reads your Unity project so she can teach from what's really there: its
scripts and scenes, the script open in your code editor, and the newest errors in Unity's
log. Only on your PC, only while teaching, and she never changes a file. Paths are sent to
the AI relative to the project (Assets/Scripts/Player.cs), never with your user folder.

Finding the project: the running Unity editor was started with -projectPath, so that's
read first; Unity Hub's list of projects is the fallback (matched by the name in Unity's
title bar)."""
import json
import os
import re
import sys
import time
from pathlib import Path

CODE_EDITORS = {"Visual Studio Code", "Visual Studio", "Rider"}
MAX_LINES = 400             # longer scripts are cut (with a note)
MAX_ERRORS = 5
LOG_TAIL = 512 * 1024       # bytes of the log read from its end
KEEP = 30.0                 # seconds the project folder and file lists are reused
RELOAD = ("Begin MonoManager ReloadAssembly", "Reloading assemblies")   # a successful compile
_ARG = re.compile(r'-projectpath\s+(?:"([^"]+)"|(\S+))', re.I)
_COMPILE = re.compile(r"^(?P<file>[^\s(][^(\n]*?\.cs)\((?P<line>\d+),\d+\): error (?P<code>CS\d+): (?P<msg>.+)$", re.M)
_EXCEPTION = re.compile(r"^(?P<name>\w+(?:\.\w+)*Exception): (?P<msg>.*)$", re.M)
_AT = re.compile(r"\(at (Assets[/\\][^:)]+\.cs):(\d+)\)")
_cache = {}


def _cached(key, make):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < KEEP:
        return hit[1]
    value = make()
    _cache[key] = (time.time(), value)
    return value


def _is_project(path):
    try:
        return bool(path) and (Path(path) / "Assets").is_dir()
    except OSError:
        return False


def _running():
    """Project folders of the Unity editors running now (from their command lines)."""
    if sys.platform != "win32":
        return []
    try:
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        procs = win32com.client.GetObject("winmgmts:").ExecQuery(
            "SELECT CommandLine FROM Win32_Process WHERE Name='Unity.exe'")
        found = [_ARG.search(p.CommandLine or "") for p in procs]
        return [m.group(1) or m.group(2) for m in found if m]
    except Exception:
        return []


def _hub():
    """Project folders in Unity Hub's list."""
    try:
        data = json.loads((Path(os.environ.get("APPDATA", "")) / "UnityHub" / "projects-v1.json")
                          .read_text(encoding="utf-8"))
        return [p.get("path", "") for p in (data.get("data") or {}).values()]
    except (OSError, ValueError, AttributeError):
        return []


def find(title=""):
    """The Unity project being worked on (a Path), or None. title: Unity's window title,
    which starts with the project's name, to choose between several."""
    name = title.split(" - ")[0].strip().lower() if title else ""

    def look():
        running = [p for p in _running() if _is_project(p)]
        for p in running:
            if not name or Path(p).name.lower() == name:
                return Path(p)
        if running:
            return Path(running[0])
        known = [p for p in _hub() if _is_project(p)]
        match = [p for p in known if name and Path(p).name.lower() == name]
        return Path(match[0]) if match else None
    return _cached(("project", name), look)


def _files(root, pattern, most):
    def look():
        try:
            found = sorted((root / "Assets").rglob(pattern), key=lambda f: -f.stat().st_mtime)
        except OSError:
            return []
        return found[:most]
    return _cached((str(root), pattern, most), look)


def _rel(root, path):
    try:
        return Path(path).resolve().relative_to(root.resolve()).as_posix()
    except (ValueError, OSError):
        return Path(path).name


def _read(path):
    try:
        return Path(path).read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError:
        return None


def overview(root):
    """A line about the project: its scripts (newest first) and scenes."""
    scripts = [f.name for f in _files(root, "*.cs", 40)]
    scenes = [f.stem for f in _files(root, "*.unity", 15)]
    return (f"Their Unity project: {root.name}. Scripts (newest first): "
            f"{', '.join(scripts) or 'none yet'}. Scenes: {', '.join(scenes) or 'none yet'}.")


def open_script(root, title):
    """The script open in their code editor (from its window title), numbered, or ""."""
    names = re.findall(r"([\w.\-]+\.cs)\b", title or "")
    if not names:
        return ""
    name = names[0]
    files = [f for f in _files(root, "*.cs", 2000) if f.name.lower() == name.lower()]
    lines = _read(files[0]) if files else None
    if lines is None:
        return ""
    unsaved = any(mark in title for mark in ("●", "•", "*"))
    cut = len(lines) > MAX_LINES
    body = "\n".join(f"{i:>4} | {text}" for i, text in enumerate(lines[:MAX_LINES], 1))
    return (f"The script open in their code editor, {_rel(root, files[0])}, as saved"
            + (" (the title shows unsaved changes: the screen is newer)" if unsaved else "")
            + (f" (first {MAX_LINES} of {len(lines)} lines)" if cut else "")
            + ":\n" + body)


def _log(root):
    """Unity's Editor log: the project's own (newer Unity 6) or the global one, newest."""
    logs = [root / "Logs" / "Editor.log",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Unity" / "Editor" / "Editor.log"]
    logs = [p for p in logs if p.is_file()]
    return max(logs, key=lambda p: p.stat().st_mtime) if logs else None


def _tail(path):
    try:
        with open(path, "rb") as f:
            f.seek(max(0, f.seek(0, 2) - LOG_TAIL))
            return f.read().decode("utf-8", errors="replace").replace("\r\n", "\n")
    except OSError:
        return ""


def _context(root, file, line):
    lines = _read(root / file)
    if not lines or not 0 < line <= len(lines):
        return ""
    return "\n".join(f"      {i:>4} | {lines[i - 1]}"
                     for i in range(max(1, line - 1), min(len(lines), line + 1) + 1))


def errors(root):
    """The newest errors in Unity's log since the last successful compile, with the lines
    they point at, or ""."""
    log = _log(root)
    text = _tail(log) if log else ""
    since = max((text.rfind(m) for m in RELOAD), default=-1)
    if since >= 0:      # a successful compile: compile errors before it are fixed
        text = text[since:]
    found = {}
    for m in _COMPILE.finditer(text):
        file = m.group("file").replace("\\", "/")
        found[(file, m.group("line"), m.group("code"))] = (
            m.start(), f"{file} line {m.group('line')}: error {m.group('code')}: {m.group('msg').strip()}",
            file, int(m.group("line")))
    for m in _EXCEPTION.finditer(text):
        at = _AT.search(text, m.end(), m.end() + 1500)
        file, line = (at.group(1).replace("\\", "/"), int(at.group(2))) if at else ("", 0)
        found[(m.group("name"), file, line)] = (
            m.start(), f"{m.group('name')}: {m.group('msg').strip()[:200]}"
            + (f" (at {file} line {line})" if file else ""), file, line)
    newest = sorted(found.values())[-MAX_ERRORS:]
    if not newest:
        return ""
    out = ["Errors in Unity's log since the last successful compile (newest last; some may "
           "already be fixed, so the Console on screen wins):"]
    for _, text_, file, line in newest:
        out.append("- " + text_)
        near = _context(root, file, line) if file else ""
        if near:
            out.append(near)
    return "\n".join(out)


def notes(win):
    """Everything she knows about the project for this look ("" if no project is found)."""
    win = win or {}
    title = win.get("title", "") if win.get("name") == "Unity" else ""
    root = find(title)
    if not root:
        return ""
    parts = [overview(root), errors(root)]
    if win.get("name") in CODE_EDITORS:
        parts.append(open_script(root, win.get("title", "")))
    return "\n\n".join(p for p in parts if p)
