# Eris

A voice helper that sits on your screen. Hold **F8**, ask "how do I add a Rigidbody?",
and Eris draws a red box around what to click and talks you through it one step at a time.

## Setup (Windows, once)

1. Install Python 3.11+ from python.org and tick **"Add python.exe to PATH"**.
2. Unzip this folder somewhere it can stay (e.g. Documents\Eris).
3. Double-click **install.bat**. It installs everything (fingerprint-checked) and puts an **Eris**
   icon on your Desktop. Windows may warn about it: click *More info*, then *Run anyway*.
4. Eris opens and asks for your API key (get one at console.anthropic.com). Paste it in and click Save.

After that, just open **Eris** from the Desktop. No command window.

## Using it

- **Click the big button to start a call.** Then just talk: she works out when you start and
  stop speaking, and keeps listening until you click again to hang up. She doesn't listen while
  she's talking, so she never hears herself.
- **Hold F8** (or hold the button) for push-to-talk. Or type in the box.
- Click inside the red box and Eris moves to the next step on her own.
- **She watches while she helps.** When your screen changes (you typed, a page loaded, you
  clicked something else) she takes a fresh look and carries on, or helps you get back on track.
  Turn it off in Settings, then Guiding.
- **Precise boxes:** she draws the box, then snaps it onto the real edges of the thing to click,
  using Windows' own element info (browsers, most apps) or the pixels on screen (Unity), and
  double-checks with a zoomed-in look.
- **Her own personality and memory:** ask her to pick a profile picture and it becomes her
  avatar in the app. She remembers things between sessions (Settings, then Forget everything).
- When you need to type something, she shows exactly what to type inside the box.
- **Next step / F9** is for steps that aren't a click (typing, dragging).
- **Stop / F10** clears everything. **New task** makes her forget the last task.
- **Active** switch: turn it off and Eris ignores the hotkeys.
- **Settings**: brain, voice, hotkeys, box timeout, keep-on-top, and a *Test the red box* button.

## Privacy

- While you type into a password, email, card or code box, Eris takes **no screenshots**.
- Those boxes are **blacked out** in every screenshot before it leaves your PC.
- Password managers (and any app you add in Settings, then Privacy) are never looked at.
- The keyboard hook only keeps her hotkeys and Enter. Everything you type is dropped instantly.
- The Free brain keeps everything on your PC.

Detection uses Windows' accessibility info (the same info screen readers use). Apps that draw their
own password boxes can't be detected, so use the blocklist or the Active switch for those.

## Safety

**What Eris connects to (and nothing else):**

| Where | Why |
|-------|-----|
| api.anthropic.com | the Claude brains (screenshots and your question) |
| localhost:11434 | the Free brain (Ollama, on your own PC) |
| speech.platform.bing.com | the Natural voice (only the sentences she says) |
| huggingface.co | one-time download of the speech-recognition model |
| github.com | checking for and downloading updates |

**How it's protected:**
- **Locked installs.** Every library is pinned to an exact version, and pip checks each
  download's fingerprint (hash), so a tampered package is refused.
- **Safe updates.** Updates only install when you click Update. They come only from this repo,
  over HTTPS, and must be newer than what you have. They can only replace Eris's own files,
  inside her folder, and new libraries come from the fingerprint-checked lock. You can turn off
  update checks in Settings, then App.
- **Your API key** is encrypted with Windows' own protection (DPAPI), tied to your Windows login.
  It's never stored in this repo or sent anywhere except Anthropic.
- **Privacy** (above): she looks away from passwords, blacks out private fields, and never hears
  what you type.
- **Scam-aware.** Text on screen is treated as content, never as instructions. She won't steer you
  to enter passwords on sites you didn't choose, download things, or disable security, and she
  warns you about obvious scams.

**If you run this repo:** turn on two-factor authentication on your GitHub account. Everyone's
updates come from here, so protect it.

## Brains (Settings, then Brain)

| Option | Cost | Notes |
|--------|------|-------|
| **Best** (Claude Opus) | about 2 cents a step | Smartest, most accurate boxes. Needs an API key. |
| **Cheap** (Claude Haiku) | about 40x less | $5 lasts thousands of steps. Needs an API key. |
| **Free** (local, Ollama) | free | Runs on your PC. Install [Ollama](https://ollama.com/download), pick a model in Settings, then Brain, and paste its download command into Command Prompt. `qwen3-vl:8b` is recommended for a 12 GB graphics card. |

### Getting the most out of the Free brain

- **She knows which app you're in** (Chrome, Blender, Discord...) and tells the AI, ignoring Eris's
  own window.
- **Pick-by-number boxes, in any app.** The AI gets a numbered list of what's on screen and picks
  one by number instead of guessing pixels. That's exact, and much easier for a small model.
  The list comes from:
  1. Windows' button list, for browsers and most apps.
  2. Windows' built-in text reader, for apps that don't share their buttons (Unity, Blender,
     games). It reads only that app's window, only when needed, and never private fields.
     A picked word's box grows to fill the button it's on.
  3. For icons with no words, she points by sight and the box snaps onto real edges.
- **Keep it on the graphics card.** Settings, then Brain, shows how much of the model fits. If it
  says less than 100% (Unity uses graphics memory too), click **Make Ollama lighter**, close
  GPU-heavy apps, or use `qwen3-vl:4b`.
- She uses short instructions written for small models, steady answers, and short memory, and
  keeps the model loaded for an hour.

## Test lab

**Settings, then App, then Test Eris** runs 17 tricky tests on made-up screens with her current
brain. The tests cover a Google results page with a sponsored ad, a site's own search box vs the
address bar, a login page, a fake "virus" scam pop-up, a page with hidden instructions aimed at AI,
a Unity editor (select the object, Add Component, Rigidbody vs Rigidbody 2D, the tiny play
button), a Blender-style editor and a game settings menu. Each reply is graded: did the box land on the right thing, did she avoid the ad, refuse
the password, spot the scam, ignore the hidden instructions, use the right format, and how fast
was she. The report (in the log folder, under `tests`) shows exactly where she needs work.
Also runnable as `python -m eris.bench`.

## Tests (for changes to Eris herself)

`python tests/run_all.py` checks the whole app without touching your real settings, memories
or API key: the step flow (boxes, clicks, the watcher, calls, push-to-talk, privacy), both
brains' requests (against fake Claude and Ollama servers, so it costs nothing), the box
snapping and text reading, the test lab's grader, and a scripted session in the real window.
Add `--quick` to skip the window. Run it after every change; it takes about half a minute.

## Voice

*Natural* uses Microsoft's free neural voices (Ava, Emma, Sonia...), so it needs internet.
If it can't connect, Eris switches to the built-in Windows voice by herself. Use *Preview* to pick one.

## How it stays fast and doesn't get stuck

- **The box goes away** as soon as you click in it, press F9/F10, ask something new, or after 20s.
- **The box shows up first.** Claude sends its coordinates before anything else, so it
  appears before she starts talking.
- **She talks while she's still thinking.** Each sentence is spoken as soon as it arrives.
- **Speech-to-text runs on your PC** (faster-whisper), and screenshots are shrunk before sending.
- **One step at a time.** After every step she takes a fresh screenshot and checks it worked.

## Tuning

- Slow? In Settings, turn on Fast mode (costs 2x) or pick *tiny.en* speech.
- Boxes in the wrong spot? Set Thinking to *medium*, or raise `SHOT_MAX_WIDTH` to 1568 in `eris/config.py`.
- Something broke? Settings, then *Open log folder*. Send `eris.log` to Claude.

## Files

- `eris/app.py`: the main window
- `eris/settings_ui.py`: the settings window (sidebar, saves instantly)
- `eris/theme.py`: colours
- `eris/core.py`: hotkeys and step flow (`Step` acts on each reply line as it arrives)
- `eris/settings.py`: saves your settings to %APPDATA%\Eris
- `eris/brain.py`: the prompt, plus the Claude and local (Ollama) brains
- `eris/protocol.py`: parses her reply lines (`ELEMENT / BOX / SAY / WAIT ...`) as they stream in
- `eris/privacy.py`: looking away from and blacking out private fields
- `eris/glowbox.py`: the rounded, glowing box
- `eris/apps.py`: which app is in front
- `eris/ocr.py`: Windows' built-in text reader, for apps without a button list
- `eris/bench.py`: the test lab
- `eris/elements.py`: Windows' numbered list of clickable things
- `eris/snap.py`: snaps boxes onto real edges (pixels)
- `eris/uia.py`: asks Windows for exact element rectangles
- `eris/watcher.py`: notices when your screen changes while she's waiting
- `eris/overlay.py`: the red box (four solid bars plus the in-box type hint)
- `eris/ears.py`: push-to-talk and speech-to-text
- `eris/speech.py`: natural and Windows voices (interruptible)
- `eris/screen.py`: screenshots and coordinate mapping
- `tests/`: the automatic checks (`python tests/run_all.py`)
