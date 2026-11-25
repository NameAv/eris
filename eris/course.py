"""Eris Unity: a course that teaches you to make your own open-world story game in Unity 6.

She teaches, you make. Every script, story line, quest and level is yours, so the game
needs no AI disclosure on Steam (Valve's rules cover AI-made content that ships in the
game, not tools that helped you learn). Each lesson builds on the last; your progress is
kept on your PC in course.json."""
import json
from dataclasses import dataclass

from . import settings


@dataclass(frozen=True)
class Lesson:
    id: str
    part: str
    title: str
    make: str       # what you'll have made by the end
    learn: str      # what it teaches


LESSONS = [
    # --- the basics ---
    Lesson("tour", "Basics", "Find your way around",
           "Move around a scene with confidence: fly the Scene view, frame an object, and find "
           "the Hierarchy, Inspector, Project and Console windows.",
           "The editor's windows, Scene view navigation (right mouse + WASD, F to frame), "
           "GameObjects and components."),
    Lesson("project", "Basics", "Start your game's project",
           "A new project from the Universal 3D template, with a scene called World saved in "
           "Assets/Scenes and a tidy folder layout (Scripts, Prefabs, Materials, Art).",
           "Unity Hub, project templates, URP, scenes, saving, why folders matter."),
    Lesson("terrain", "Basics", "Shape the land",
           "A Terrain with hills, a valley and a path, painted with at least two textures.",
           "Terrain tools: raise/lower, smooth, set height, paint texture layers."),
    Lesson("move", "Basics", "Your first script: walking",
           "A player capsule that walks around the terrain with WASD, from a C# script you "
           "write yourself.",
           "MonoBehaviour, Update, the Input System, CharacterController.Move, Vector3, "
           "Time.deltaTime, and reading the Console."),
    Lesson("camera", "Basics", "A third-person camera",
           "A camera that follows behind the player and turns with the mouse.",
           "The Package Manager, Cinemachine, follow and look-at targets."),
    Lesson("jump", "Basics", "Gravity and jumping",
           "The player falls, lands and jumps.",
           "Velocity, gravity as acceleration, ground checks, variables shown in the Inspector."),
    # --- the world ---
    Lesson("prefabs", "World", "Trees, rocks and prefabs",
           "A forest and scattered rocks, painted with the terrain tools and placed as prefabs.",
           "Prefabs and prefab variants, terrain tree painting, the Asset Store for free assets "
           "(and checking their licences)."),
    Lesson("daynight", "World", "Day and night",
           "A sun that moves across the sky, with nights that get dark.",
           "Directional lights, the skybox, rotating with Quaternion, serialized fields."),
    Lesson("mood", "World", "Atmosphere",
           "Fog, colour grading and bloom that give the world its own mood.",
           "URP Volumes and post-processing, fog in the Lighting window."),
    Lesson("interact", "World", "Press E to interact",
           "Things in the world that show \"Press E\" when you're close and react when you press it.",
           "Trigger colliders, OnTriggerEnter/Exit, interfaces, a simple UI prompt."),
    # --- the story ---
    Lesson("dialogue", "Story", "Characters who talk",
           "An NPC who says lines you wrote yourself, in a dialogue box, one line per key press.",
           "ScriptableObjects as data, UI panels and text, keeping story separate from code."),
    Lesson("quests", "Story", "Quests",
           "A quest an NPC gives you, with steps, that the game tracks and you can complete.",
           "Designing data, states (not started, active, done), events between scripts."),
    Lesson("items", "Story", "Items and an inventory",
           "Pickups that go into an inventory, and a quest step that needs one of them.",
           "Lists, item data as ScriptableObjects, showing a list in the UI."),
    # --- bringing it to life ---
    Lesson("navmesh", "Life", "NPCs that walk around",
           "NPCs that walk between places on the terrain and stop to talk to you.",
           "The AI Navigation package (classic pathfinding, not generative AI), NavMeshAgent, "
           "waypoints."),
    Lesson("animate", "Life", "Animation",
           "The player and NPCs walk, run and idle with real animations.",
           "Humanoid rigs, the Animator, blend trees, parameters set from your script."),
    Lesson("sound", "Life", "Sound",
           "Footsteps, wind and music that changes between places.",
           "AudioSource, AudioMixer, 3D sound, trigger zones."),
    # --- shipping it ---
    Lesson("save", "Ship", "Saving and loading",
           "Your position, inventory and quests are saved and come back when you load.",
           "JsonUtility, Application.persistentDataPath, what to save and what not to."),
    Lesson("menus", "Ship", "Menus and pause",
           "A main menu, a pause menu and settings for volume and mouse speed.",
           "Scene loading, Time.timeScale, PlayerPrefs."),
    Lesson("big", "Ship", "Making a big world run well",
           "The world split into parts that load as you travel, running smoothly.",
           "The Profiler, LODs, occlusion culling, additive scenes."),
    Lesson("steam", "Ship", "Build it and get ready for Steam",
           "A Windows build you can share, and a checklist for your Steam page.",
           "Build Profiles, Steamworks basics, store page assets, the content survey's AI "
           "questions (you made it all yourself, so they're a no)."),
]
BY_ID = {lesson.id: lesson for lesson in LESSONS}


def file():
    return settings.folder() / "course.json"


def _load():
    try:
        data = json.loads(file().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def done():
    return [i for i in _load().get("done", []) if i in BY_ID]


def current():
    """The first lesson you haven't finished (None once the course is done)."""
    finished = set(done())
    return next((lesson for lesson in LESSONS if lesson.id not in finished), None)


def number(lesson):
    return LESSONS.index(lesson) + 1


KEEP_FACTS = 40
KEEP_NOTES = 30     # per lesson


def _save(data):
    file().parent.mkdir(parents=True, exist_ok=True)
    file().write_text(json.dumps(data, indent=1), encoding="utf-8")


def complete(lesson):
    data = _load()
    data["done"] = [i for i in done() if i != lesson.id] + [lesson.id]
    _save(data)


def remember(fact):
    """Something lasting they made in their game ("Player has PlayerMovement.cs")."""
    fact = fact.strip()
    data = _load()
    facts = [f for f in data.get("project", []) if f.lower() != fact.lower()]
    data["project"] = (facts + [fact])[-KEEP_FACTS:]
    _save(data)


def facts():
    return list(_load().get("project", []))


def note(lesson, why):
    """Keep one of her "why"s in your notebook, under its lesson."""
    why = why.strip()
    data = _load()
    notes = data.setdefault("notes", {}).setdefault(lesson.id, [])
    if why and why not in notes:
        notes.append(why)
        del notes[:-KEEP_NOTES]
        _save(data)


def notebook():
    """[(lesson, [why, ...])] for the lessons with notes, in course order."""
    notes = _load().get("notes", {})
    return [(lesson, notes[lesson.id]) for lesson in LESSONS if notes.get(lesson.id)]


def forget():
    try:
        file().unlink()
    except OSError:
        pass


def task(lesson):
    """What she's asked when you start a lesson."""
    return (f"Teach me lesson {number(lesson)} of {len(LESSONS)}: {lesson.title}. By the end I'll "
            f"have made: {lesson.make} What it teaches: {lesson.learn} Start from what's on my "
            "screen; skip anything I've clearly done already.")


def summary():
    """For the AI: where you are in the course, and what's in their game so far."""
    lesson = current()
    finished = len(done())
    if lesson is None:
        text = f"Course: they've finished all {len(LESSONS)} lessons."
    else:
        text = (f"Course: {finished} of {len(LESSONS)} lessons finished; next is lesson "
                f"{number(lesson)}, {lesson.title}.")
    made = facts()
    if made:
        text += "\nWhat they've made in their game so far:\n" + "\n".join(f"- {f}" for f in made)
    return text
