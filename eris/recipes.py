"""Recipes: tasks Eris has guided you through before. When a task finishes cleanly, its
steps are kept (on your PC only); the next time you ask for something similar in the
same app, she gets those steps as a guide. She still checks the real screen at every
step, so a recipe can only speed her up and steady her, never make her blindly click.
A task where you pressed Wrong box is never kept."""
import json
import re
import time

from . import settings

KEEP = 60            # recipes kept (the oldest go first)
MATCH = 0.6          # how alike two requests must be (shared words / all words)
SAME = 0.8           # ...this alike and it's the same recipe: the newer one replaces it
STOP = {"the", "and", "for", "you", "can", "how", "what", "with", "into", "onto", "this", "that",
        "please", "help", "want", "need", "would", "like", "could", "should", "just", "some",
        "have", "make", "get", "let", "lets", "there", "from", "your", "mine", "about"}


_STEP = re.compile(r"^(?P<say>.+?)(?: \((?P<what>[^()]+)\))?(?: - type (?P<type>.+?))?"
                   r"(?: - press (?P<key>.+?))?(?P<drag> - drag it to the drop target)?$")


def as_plan(step):
    """A kept step ("Click Add Component (the Add Component button) - type rigid") as a
    plan Eris can show at once: {"say", "what", "type", "key", "wait"}, or None."""
    m = _STEP.match(step or "")
    if not m or m.group("drag"):
        return None
    plan = {k: m.group(k) for k in ("say", "what", "type", "key") if m.group(k)}
    plan["what"] = plan.get("what") or plan["say"]
    plan["wait"] = "next" if plan.get("type") or plan.get("key") else "click"
    return plan


def file():
    return settings.folder() / "recipes.json"


def words(text):
    """The words that matter in a request ("how do I add a rigidbody to my player" ->
    {add, rigidbody, player})."""
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2 and w not in STOP}


def _alike(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


def load():
    try:
        recs = json.loads(file().read_text(encoding="utf-8"))
        return recs if isinstance(recs, list) else []
    except (OSError, ValueError):
        return []


def remember(task, app, steps):
    """Keep a finished task's steps (two or more)."""
    if len(steps) < 2 or not words(task):
        return
    w = words(task)
    old = [r for r in load() if r.get("app") == app and _alike(words(r.get("task", "")), w) >= SAME]
    recs = [r for r in load() if r not in old]
    uses = max([r.get("uses", 1) for r in old], default=0) + 1      # how often it's been done
    recs.append({"task": task.strip(), "app": app, "steps": steps[:12], "uses": uses,
                 "saved": time.strftime("%Y-%m-%d")})
    file().parent.mkdir(parents=True, exist_ok=True)
    file().write_text(json.dumps(recs[-KEEP:], indent=1), encoding="utf-8")


def find(task, app):
    """The recipe for a request like this one in this app, or None."""
    w = words(task)
    if len(w) < 2:
        return None
    best, score = None, 0.0
    for r in load():
        if r.get("app") != app:
            continue
        s = _alike(words(r.get("task", "")), w)
        if s > score:
            best, score = r, s
    return best if score >= MATCH else None


def describe(rec, step_no):
    """The recipe as a note for the AI."""
    steps = "\n".join(f"{i}. {s}" for i, s in enumerate(rec["steps"], 1))
    note = (f'You guided them through this before ("{rec["task"]}") and these steps worked:\n{steps}\n'
            f"They're probably at step {step_no}. Use this as a guide, but trust the screen: "
            "if it looks different, adapt.")
    if rec.get("uses", 1) >= 2:
        note += f" They've done this {rec['uses']} times now: keep it brief."
    return note


def forget():
    try:
        file().unlink()
    except OSError:
        pass
