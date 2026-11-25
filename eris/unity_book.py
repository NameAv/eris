"""Eris Unity's handbook: checked facts about Unity 6 so she teaches it right.

CORE goes with every turn in Eris Unity (in the cached part of the prompt, so it costs
next to nothing after the first time): the editor, C# basics, what changed in Unity 6,
and common errors. PAGES are one per lesson, plus a few extra topics. Each task gets the
page for the lesson you're on and any page your question mentions ("prefab", "navmesh").

Only well-established facts. Where Unity versions differ, the page says so and tells her
to read the screen: a wrong menu path taught as fact is worse than none."""
import re

CORE = """Unity handbook (Unity 6, checked facts; when the screen differs, the screen wins: \
menu names shift between versions, so read the real menu before naming an item).

The editor:
- Hierarchy: the objects in the open scene. Inspector: the selected object's components. \
Project: the files in Assets. Console: messages and errors (Window > General > Console, \
Ctrl+Shift+C). Scene view: where you build. Game view: what the player sees.
- Scene view: hold the right mouse button and use WASD to fly (Q down, E up, Shift faster); \
Alt + left drag orbits; middle drag pans; scroll zooms; F frames the selected object \
(double-clicking it in the Hierarchy does too).
- Tools: W move, E rotate, R scale, T rect, Q the hand. Ctrl+D duplicates. Align an object \
with the view: GameObject > Align With View (Ctrl+Shift+F).
- Play: the button at the top centre (Ctrl+P). Changes made in Play mode are LOST when \
you stop, a classic beginner trap. Save the scene with Ctrl+S.
- Add a component: select the object, then Add Component at the bottom of the Inspector, \
and type its name.

C# scripts:
- Create one: Project window > right-click > Create > Scripting > MonoBehaviour Script (Unity \
6). Name it right away: the class name must match the file name exactly, or Unity can't add \
it to an object.
- Attach it by dragging it onto the object, or Add Component and type its name.
- Awake runs first, then Start once, Update every frame, FixedUpdate at a fixed rate (for \
physics), LateUpdate after every Update (for cameras).
- Public fields and private fields marked [SerializeField] show in the Inspector. Inspector \
values override the defaults in the code.
- C# is case-sensitive; every statement ends with ;. Multiply movement by Time.deltaTime so \
speed doesn't depend on frame rate. Debug.Log("...") prints to the Console.
- Get another component with GetComponent<T>(); cache it in Awake or Start, not every frame.
- Compare tags with other.CompareTag("Player").

Changed in Unity 6 (old tutorials still show the old names):
- Rigidbody.velocity is now linearVelocity (Rigidbody2D too); damping is linearDamping.
- FindObjectOfType is obsolete: use FindAnyObjectByType (or FindFirstObjectByType).
- Input: new projects use the Input System package. The old Input.GetAxis / GetKey throw \
"InvalidOperationException: You are trying to read Input using the UnityEngine.Input \
class..." when Active Input Handling (Edit > Project Settings > Player > Other Settings) is \
set to Input System Package (New). Teach the Input System; "Both" works as a stopgap.
- Building: File > Build Profiles (was File > Build Settings).
- Cinemachine 3: the namespace is Unity.Cinemachine and the camera component is \
CinemachineCamera (was CinemachineVirtualCamera).

Common errors (box the red line in the Console; double-clicking it opens the script at \
the line):
- CS1002 "; expected": a missing semicolon at the end of the line it names (or the line \
before).
- CS0103 "The name X does not exist in the current context": a typo, wrong capital letter, \
or a variable declared somewhere else.
- CS0246 "The type or namespace name X could not be found": a missing using line (e.g. using \
UnityEngine.InputSystem;) or a missing package.
- CS1061 "X does not contain a definition for Y": a typo, the wrong type, or an old Unity \
name (e.g. velocity).
- CS0029 "Cannot implicitly convert type": e.g. putting a Vector3 where a float goes.
- NullReferenceException: a field never set in the Inspector, or GetComponent found nothing. \
Check the object the error names.
- UnassignedReferenceException: a field shown in the Inspector is still empty: drag the \
object into it.
- "All compiler errors have to be fixed before you can enter playmode": fix the red errors \
first; nothing new runs until they're gone.
- "Can't add script component ... the script class can't be found": the file and class \
names differ, or there's a compile error."""

PAGES = {
    "tour": ("editor hierarchy inspector gizmo layout transform", """\
- Window > General lists the main windows; Window > Layouts > Default resets a messy layout.
- Create a test object: GameObject > 3D Object > Cube. Its Transform holds Position, Rotation \
and Scale; every object has one.
- The Scene view gizmo (top right) switches views; clicking its centre toggles perspective \
and isometric."""),
    "project": ("project unity hub template urp scene folder git", """\
- Unity Hub > Projects > New project. Templates: Universal 3D uses URP (the Universal Render \
Pipeline), the right choice for most open worlds on PC.
- New scene: File > New Scene; save it with File > Save As into Assets/Scenes. Create folders \
with Project window > right-click > Create > Folder.
- Back up from day one: Git with a Unity .gitignore (or Unity Version Control). Never put \
the Library folder in version control; Unity rebuilds it."""),
    "terrain": ("terrain sculpt hills paint texture layer height", """\
- Create: GameObject > 3D Object > Terrain. The tools are in its Inspector: Create \
Neighbor Terrains, Paint Terrain, Paint Trees, Paint Details, Terrain Settings.
- Paint Terrain has a dropdown: Raise or Lower Terrain (click raises, Shift+click lowers), \
Set Height, Smooth Height, Paint Texture, Stamp Terrain, Paint Holes.
- Paint Texture needs a Terrain Layer first: Edit Terrain Layers > Create Layer, then pick \
a texture. The first layer covers the whole terrain.
- Size and resolution: Terrain Settings > Mesh Resolution (Terrain Width / Length)."""),
    "move": ("move walk player charactercontroller input wasd script", """\
- The player: a Capsule with a CharacterController (remove its Capsule Collider: the \
CharacterController is its collider).
- CharacterController.Move(motion) moves by that amount this frame, sliding along walls. It \
applies NO gravity; add your own. SimpleMove adds gravity but ignores vertical speed (no \
jumping), so Move is what you'll grow into.
- Reading input (Input System, needs using UnityEngine.InputSystem;): the project-wide \
actions asset has a Player map with Move, Look, Jump and more (check the asset in Assets: \
names vary). Store the action once: moveAction = InputSystem.actions.FindAction("Move"); \
then each frame moveAction.ReadValue<Vector2>() gives x (A/D) and y (W/S).
- Turn Vector2 into a direction: new Vector3(input.x, 0, input.y); relative to the player: \
transform.right * input.x + transform.forward * input.y.
- Quick key check without actions: Keyboard.current.eKey.wasPressedThisFrame."""),
    "camera": ("camera cinemachine follow third person orbit mouse", """\
- Install: Window > Package Manager > Unity Registry > Cinemachine (Unity 6 uses Cinemachine \
3). The Main Camera gets a CinemachineBrain automatically.
- Create one: GameObject > Cinemachine > Targeted Cameras > FreeLook Camera (orbits with the \
mouse) or Third Person Aim Camera. Set its Tracking Target to the player.
- Cinemachine 3 puts the behaviours on the camera itself as components (e.g. Orbital Follow, \
Rotation Composer, Cinemachine Input Axis Controller for mouse input).
- Moving relative to the camera: use the camera's forward with y set to 0, normalised."""),
    "jump": ("jump gravity fall ground grounded velocity", """\
- Keep a vertical speed variable: each frame velocity.y += gravity * Time.deltaTime (gravity \
around -9.81, or stronger for snappier games), then Move by velocity * Time.deltaTime.
- controller.isGrounded is true after a Move pushed into the ground; when grounded, reset \
velocity.y to a small negative number (like -2) so it stays grounded.
- Jump height h: velocity.y = Mathf.Sqrt(h * -2f * gravity).
- jumpAction.WasPressedThisFrame() is true only on the frame the key goes down."""),
    "prefabs": ("prefab variant tree rock asset store licence", """\
- Make one: drag an object from the Hierarchy into the Project window (blue cube icon). Edit \
it by double-clicking; Overrides (top of the Inspector) applies or reverts per-instance \
changes.
- Prefab variant: Project window > right-click the prefab > Create > Prefab Variant.
- Terrain trees: Paint Trees > Edit Trees > Add Tree, choose a prefab, then paint. For \
collisions the tree prefab needs a collider and the Terrain Collider's Enable Tree \
Colliders must be on.
- Asset Store / packs: check the licence lets you use them in a commercial game."""),
    "daynight": ("day night sun light skybox cycle", """\
- The sun is a Directional Light: its position doesn't matter, only its rotation.
- Lighting window: Window > Rendering > Lighting > Environment: Skybox Material and Sun \
Source (set it to your directional light so the default skybox follows it).
- Rotating over time: transform.Rotate(Vector3.right, degreesPerSecond * Time.deltaTime), or \
set transform.rotation = Quaternion.Euler(angle, yaw, 0) from a time-of-day value.
- Dim the light's intensity at night (and lower ambient light) so nights get dark."""),
    "mood": ("fog post processing volume bloom colour grading atmosphere", """\
- Post-processing in URP: GameObject > Volume > Global Volume, New profile, then Add \
Override: Bloom, Color Adjustments, Tonemapping, Vignette...
- The camera must have Post Processing ticked (Camera > Rendering).
- Fog: Lighting window > Environment > Other Settings > Fog (colour, mode and density)."""),
    "interact": ("trigger collider ontriggerenter interact prompt interface", """\
- A trigger: a collider with Is Trigger ticked. OnTriggerEnter(Collider other) and \
OnTriggerExit fire when something enters or leaves it.
- At least one of the two needs a Rigidbody (a CharacterController also counts) for trigger \
messages to fire.
- 3D and 2D don't mix: OnTriggerEnter2D needs 2D colliders.
- An interface (e.g. IInteractable with an Interact() method) lets one "Press E" script work \
with doors, NPCs and items alike."""),
    "dialogue": ("dialogue npc talk text ui canvas textmeshpro scriptableobject", """\
- Text on screen: right-click the Hierarchy > UI > Text - TextMeshPro (the menu wording \
varies a little between versions). The first time, choose Import TMP Essentials. Unity adds \
a Canvas and an EventSystem.
- In code: using TMPro; and a TMP_Text field; set its .text.
- ScriptableObjects hold data as assets: a class deriving from ScriptableObject with \
[CreateAssetMenu(menuName = "Game/Dialogue")] above it, then Project window > Create > \
Game > Dialogue. Their lines are the player's own writing; keep story out of the code.
- Canvas Scaler > UI Scale Mode: Scale With Screen Size keeps UI right on any resolution."""),
    "quests": ("quest objective state event", """\
- A quest as a ScriptableObject (title, steps) plus a runtime state: an enum NotStarted, \
Active, Done.
- Events let scripts talk without knowing each other: a C# event (public event \
System.Action OnQuestChanged;) or a UnityEvent shown in the Inspector.
- Keep progress (which step) separate from the quest asset, so saving is easy later."""),
    "items": ("item inventory pickup list", """\
- An Item ScriptableObject (name, icon, description). The inventory: a List<Item> (using \
System.Collections.Generic;).
- A pickup: a trigger collider; on interact, add the item and Destroy(gameObject).
- Showing a list in UI: a Vertical Layout Group, instantiating a prefab row per item."""),
    "navmesh": ("navmesh npc walk path agent navigation waypoint", """\
- Pathfinding (classic, not generative AI). Install AI Navigation in the Package Manager.
- GameObject > AI > NavMesh Surface, then Bake in its Inspector (Unity 6 bakes there, not in \
the old Navigation window).
- The NPC gets a NavMeshAgent; agent.SetDestination(point) (using UnityEngine.AI;). Check \
!agent.pathPending && agent.remainingDistance < agent.stoppingDistance to know it arrived.
- Rebake after moving terrain or buildings."""),
    "animate": ("animation animator blend tree rig humanoid mixamo", """\
- A model's Rig tab (select the file in Project) > Animation Type: Humanoid lets animations \
be shared between characters.
- Window > Animation > Animator edits the state machine. Parameters (Float, Bool, Trigger) \
drive transitions; from code: animator.SetFloat("Speed", value).
- Blend tree: right-click in the Animator > Create State > From New Blend Tree; blends idle, \
walk and run by Speed.
- Untick Has Exit Time on transitions that should happen immediately."""),
    "sound": ("sound audio music footsteps mixer", """\
- An AudioSource plays a clip; Spatial Blend 1 makes it 3D (quieter with distance). Only ONE \
AudioListener in a scene (on the camera).
- audioSource.PlayOneShot(clip) for effects like footsteps.
- AudioMixer for volume groups (music, effects): Project window > Create > Audio Mixer (it \
may sit under an Audio submenu); expose a parameter to set volume from settings."""),
    "save": ("save load json file persistentdatapath", """\
- JsonUtility.ToJson / FromJson work on [System.Serializable] classes with public (or \
[SerializeField]) fields. They don't save Dictionaries or properties.
- Where: System.IO.Path.Combine(Application.persistentDataPath, "save.json"), written with \
File.WriteAllText (using System.IO;).
- Save data (position, items, quest states), never whole GameObjects."""),
    "menus": ("menu pause timescale playerprefs loadscene button", """\
- Load a scene: SceneManager.LoadScene("Name") (using UnityEngine.SceneManagement;). The scene \
must be in the scene list: File > Build Profiles > Scene List.
- Pause: Time.timeScale = 0 (Update still runs, but Time.deltaTime is 0; use \
Time.unscaledDeltaTime in menus). Set it back to 1 to resume.
- PlayerPrefs.SetFloat / GetFloat for small settings like volume and mouse speed.
- Buttons: UI > Button - TextMeshPro, then On Click () in its Inspector."""),
    "big": ("performance profiler lod occlusion additive streaming fps lag", """\
- Window > Analysis > Profiler shows what's slow; check the CPU and Rendering parts.
- LOD Group component: simpler models far away.
- Occlusion culling: mark objects Static (Occluder/Occludee), then Window > Rendering > \
Occlusion Culling > Bake.
- Big worlds: split them into scenes and load them with SceneManager.LoadSceneAsync(name, \
LoadSceneMode.Additive) when the player gets close; unload far ones."""),
    "steam": ("build steam steamworks release exe", """\
- File > Build Profiles > Windows > Build. Test the build itself, not just Play mode.
- Steam: a Steam Direct fee per game gets an App ID. Steamworks.NET or Facepunch.Steamworks are \
the common C# wrappers. A steam_appid.txt next to the exe lets you test before release.
- Steam's AI disclosure covers AI-made content shipped in the game or on its store page \
(art, sound, text). Tools that helped them learn don't count; as they make everything \
themselves, the answer is no. Point them to Steamworks' current wording."""),
    # extra topics (no lesson of their own)
    "physics": ("rigidbody physics force collision addforce kinematic", """\
- Rigidbody: physics moves it. Move it in FixedUpdate with AddForce or \
rb.linearVelocity (Unity 6 name), not by setting transform.position.
- OnCollisionEnter(Collision c) for solid hits; OnTriggerEnter for triggers.
- Is Kinematic: code moves it, physics doesn't push it."""),
    "debug": ("debug breakpoint log bug broken", """\
- Debug.Log values to see what's happening; Debug.DrawRay shows directions in the Scene view.
- Visual Studio / Rider: Attach to Unity, set a breakpoint, press Play to pause on that line.
- "Not working" checklist: errors in the Console? Is the script on the object and enabled? \
Are the Inspector fields set? Is it the right object?"""),
}


def _words(text):
    return set(re.findall(r"[a-z0-9]+", (text or "").lower()))


def notes(task, lesson_id=None, most=3):
    """The handbook pages that fit this task: the current lesson's, then any whose topic words
    the task mentions. "" if none."""
    words = _words(task)
    chosen = [lesson_id] if lesson_id in PAGES else []
    for key, (topic, _) in PAGES.items():
        if key not in chosen and words & _words(topic):
            chosen.append(key)
    chosen = chosen[:most]
    if not chosen:
        return ""
    return "Unity handbook pages for this:\n" + "\n".join(PAGES[k][1] for k in chosen)
