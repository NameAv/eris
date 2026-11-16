"""What Eris learns about working with you, beyond whole-task recipes (recipes.py):
- lessons: when you press Wrong box and her next box is right, she notes what she mixed
  up ("for add a rigidbody, not Rigidbody 2D: Rigidbody"), and later tasks in that app
  get the lessons that fit them;
- familiarity: how many tasks you've finished in each app, so she can skip the basics
  where you're at home.
Kept on your PC only, in experience.json next to the log; Forget everything clears it."""
import json
import time

from . import recipes, settings

KEEP_LESSONS = 40
SHOW_LESSONS = 3     # at most this many lessons go with a task
AT_HOME = 5          # tasks finished in an app before she skips the basics there


def file():
    return settings.folder() / "experience.json"


def _load():
    try:
        data = json.loads(file().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(data):
    file().parent.mkdir(parents=True, exist_ok=True)
    file().write_text(json.dumps(data, indent=1), encoding="utf-8")


def learn(app, task, wrong, right):
    """She pointed at `wrong`, you said so, and `right` was it."""
    if not (app and wrong and right) or wrong.strip().lower() == right.strip().lower():
        return
    data = _load()
    lessons = [l for l in data.get("lessons", []) if not (l["app"] == app and l["wrong"] == wrong)]
    lessons.append({"app": app, "task": task, "wrong": wrong, "right": right, "saved": time.strftime("%Y-%m-%d")})
    data["lessons"] = lessons[-KEEP_LESSONS:]
    _save(data)


def finished(app):
    """A task in this app went well."""
    if not app:
        return
    data = _load()
    done = data.setdefault("tasks_done", {})
    done[app] = done.get(app, 0) + 1
    _save(data)


def notes(app, task):
    """What she's learned that fits this task in this app, as a note for the AI ("" if nothing)."""
    if not app:
        return ""
    data = _load()
    words = recipes.words(task)
    fits = [l for l in data.get("lessons", []) if l["app"] == app]
    fits.sort(key=lambda l: len(words & recipes.words(l["task"] + " " + l["right"])), reverse=True)
    parts = []
    if fits:
        parts.append("Mistakes to avoid (you mixed these up before in " + app + "):\n" + "\n".join(
            f'- for "{l["task"]}": not {l["wrong"]}, the right one was {l["right"]}' for l in fits[:SHOW_LESSONS]))
    n = data.get("tasks_done", {}).get(app, 0)
    if n >= AT_HOME:
        parts.append(f"They've finished {n} tasks in {app} with you: skip the very basics and keep it brisk.")
    return "\n\n".join(parts)


def summary():
    """(number of lessons, {app: tasks finished}) for Settings."""
    data = _load()
    return len(data.get("lessons", [])), dict(data.get("tasks_done", {}))


def forget():
    try:
        file().unlink()
    except OSError:
        pass
