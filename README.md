# Eris

A voice helper that sits on your screen. Hold **F8**, ask "how do I add a Rigidbody?",
and Eris draws a red box around what to click and talks you through it one step at a time.

## Setup (Windows, once)

1. Install Python 3.11+ from python.org and tick **"Add python.exe to PATH"**.
2. Unzip this folder somewhere it can stay (e.g. Documents\Eris).
3. Double-click **install.bat**. It installs everything and puts an **Eris** icon on your Desktop.
4. Eris opens and asks for your API key (get one at console.anthropic.com). Paste it in and click Save.

After that, just open **Eris** from the Desktop. No command window.

## Using it

- **Hold F8** (or hold the red *Hold to talk* button) and ask. Or type in the box.
- Click inside the red box and Eris moves to the next step on her own.
- **Next step / F9** is for steps that aren't a click (typing, dragging).
- **Stop / F10** clears everything. **New task** makes her forget the last task.
- **Active** switch: turn it off and Eris ignores the hotkeys.
- **Settings**: API key, speed vs. carefulness, voice on/off and speed, speech accuracy,
  hotkeys, box timeout, keep-on-top, and a *Test the red box* button.

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

- `eris/app.py`: the window and settings
- `eris/core.py`: hotkeys and step flow
- `eris/settings.py`: saves your settings to %APPDATA%\Eris
- `eris/brain.py`: Claude prompt and streaming
- `eris/protocol.py`: parses `BOX / SAY / WAIT / DONE` lines as they stream in
- `eris/overlay.py`: transparent click-through red box window
- `eris/ears.py`: push-to-talk and speech-to-text
- `eris/speech.py`: Windows voice (interruptible)
- `eris/screen.py`: screenshots and coordinate mapping
