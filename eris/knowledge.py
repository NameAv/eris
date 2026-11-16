"""A few solid facts about popular apps, given to the AI only when that app is in front.
Short on purpose: the Free brain knows less, and a wrong menu path is worse than none,
so only well-established paths and shortcuts are here (with the Unity 6 differences)."""

_BROWSER = """\
- The address bar is the long bar at the very top; typing there searches the web. A site's own \
search box only searches that site.
- New tab: Ctrl+T. Back: Alt+Left. Find on the page: Ctrl+F. Downloads: Ctrl+J."""

NOTES = {
    "Unity": """\
- Hierarchy (left): the objects in the scene. Inspector (right): the selected object's components. \
Project (bottom): the project's files. Scene and Game views in the middle.
- To add a component, first select the object in the Hierarchy, then Inspector > Add Component \
(bottom of the Inspector) and type its name. 3D physics: Rigidbody / Box Collider; 2D: Rigidbody 2D / \
Box Collider 2D. Don't mix 2D and 3D.
- New object: GameObject menu > 3D Object > Cube (or right-click in the Hierarchy).
- New script: in the Project window, Assets > Create > Scripting > MonoBehaviour Script (Unity 6) \
or Assets > Create > C# Script (older). Attach it by dragging it onto the object in the Hierarchy or \
the Inspector, or Add Component and type its name.
- Play / Pause / Step: the buttons at the top centre (Ctrl+P plays). Changes made while playing are \
lost when you stop.
- Save the scene: Ctrl+S. Package Manager: Window > Package Manager. Building: File > Build Profiles \
(Unity 6) or File > Build Settings (older).
- A prefab: drag an object from the Hierarchy into the Project window.""",
    "Blender": """\
- Add an object: Shift+A in the 3D viewport, or the Add menu at the top of the viewport.
- Tab switches Object / Edit mode. G moves, R rotates, S scales (then X/Y/Z to lock an axis).
- The Properties editor (right, with the tabs down its side) holds materials, modifiers and render \
settings. N shows the sidebar in the viewport. F12 renders.""",
    "Visual Studio Code": """\
- Command Palette: Ctrl+Shift+P (find any command). Open a file by name: Ctrl+P.
- Terminal: Ctrl+` (or Terminal > New Terminal). Extensions: the squares icon in the left bar, \
or Ctrl+Shift+X. Save: Ctrl+S.""",
    "Windows Settings": """\
- Open Settings: Win+I. The sections are listed down the left side; there's a search box at the top \
of that list.
- Dark mode: Personalization > Colors. Display and scaling: System > Display. Bluetooth: \
Bluetooth & devices.""",
    "File Explorer": """\
- The address bar at the top shows the folder; the search box is at its right. The left pane lists \
Home, This PC and pinned folders.
- New folder: Ctrl+Shift+N. Rename: F2. Show file extensions: View > Show > File name extensions.""",
}
for _name in ("Google Chrome", "Microsoft Edge", "Firefox", "Opera", "Brave"):
    NOTES[_name] = _BROWSER


def notes(app_name):
    """The notes for this app (by the name apps.py gives it), as a short block, or ""."""
    text = NOTES.get(app_name or "")
    return f"Good to know about {app_name}:\n{text}" if text else ""
