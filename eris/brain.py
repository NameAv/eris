"""The thinking part. Streams the reply so the box and voice start early.

Three brains: Claude Opus (best), Claude Haiku (very cheap), or a free local
vision model running on your own PC through Ollama.
"""
import json
import urllib.error
import urllib.request

import anthropic

from . import config, settings
from .protocol import Event, LineStream

SYSTEM = """You are Eris, a friendly assistant sitting on the user's computer. They are \
usually working in Unity or other dev tools. You can see their screen in each screenshot. \
Your job: guide them through doing a task THEMSELVES, one action at a time, by drawing a \
red box around what to click and saying what to do. Explain briefly so they learn.

Reply with ONLY these lines, in this order, nothing else (no markdown):
BOX x1 y1 x2 y2   - pixel coords in the CURRENT screenshot of the ONE thing to interact \
with now. Tight around the actual clickable element (button, menu item, field, tab). \
Or NOBOX if nothing needs pointing at.
SAY <sentence>    - 1 to 3 SAY lines. Spoken out loud, so short, natural and plain. \
First SAY = the action ("Click Add Component."). Optionally one more = why/what it does.
Then exactly one of:
WAIT click        - they need to click inside the box.
WAIT next         - they need to type, drag or do something else; tell them to press F9 when done.
DONE              - the whole task is complete, or it was just a question with nothing to do.

Rules:
- ONE action per reply. You'll get a fresh screenshot after they do it.
- Only box things you can actually see in THIS screenshot. If the target is hidden \
(behind a menu, scrolled away, wrong window), box the thing that gets them closer.
- Each new screenshot: first check the previous step worked. If it didn't, briefly say \
so and correct course.
- If you can't tell what they mean, NOBOX, ask one short question, DONE.
- Be accurate about Unity: menu paths, component names, Inspector layout.

Example:
BOX 1012 388 1180 412
SAY Click Add Component at the bottom of the Inspector.
SAY That's where you attach things like physics to an object.
WAIT click"""

KEEP_MESSAGES = 16   # recent text-only history kept for context


class Brain:
    def __init__(self, log=print):
        self.log = log
        self.client = None
        self._key = None
        self.history = []   # text only; old screenshots aren't re-sent (keeps it fast)

    def _get_client(self):
        key = settings.api_key()
        if not key:
            return None
        if key != self._key:
            self.client = anthropic.Anthropic(api_key=key)
            self._key = key
        return self.client

    def reset(self):
        self.history = []

    @staticmethod
    def snap():
        """Local Qwen-VL models want image sides that are multiples of 28."""
        return 28 if config.BRAIN == "local" else 1

    def turn(self, shot, text, on_event, alive):
        """Stream one step. Calls on_event(Event) as lines arrive. alive() -> False aborts."""
        user_text = f"{text}\n\n(Screenshot is {shot.img_w}x{shot.img_h} pixels.)"
        lines = LineStream()

        def feed(chunk):
            for ev in lines.feed(chunk):
                on_event(ev)

        if config.BRAIN == "local":
            reply = self._local(shot, user_text, feed, alive, on_event)
        else:
            reply = self._claude(shot, user_text, feed, alive, on_event)
        if reply is None:
            return
        for ev in lines.flush():
            on_event(ev)
        self.history += [
            {"role": "user", "content": f"[screenshot] {text}"},
            {"role": "assistant", "content": reply.strip() or "NOBOX\nDONE"},
        ]
        self.history = self.history[-KEEP_MESSAGES:]

    def _fail(self, on_event, msg):
        on_event(Event("say", msg))
        on_event(Event("done"))

    # ---------- Claude (paid, best) ----------
    def _claude(self, shot, user_text, feed, alive, on_event):
        client = self._get_client()
        if not client:
            self._fail(on_event, "I need an API key for that brain. Open Settings, or switch to the free one.")
            return None
        messages = self.history + [{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                         "data": shot.b64}},
            {"type": "text", "text": user_text},
        ]}]
        common = dict(max_tokens=config.MAX_TOKENS, system=SYSTEM, messages=messages,
                      output_config={"effort": config.EFFORT})
        reply = []
        try:
            if config.BRAIN == "claude-cheap":
                cm = client.messages.stream(model=config.CHEAP_MODEL, **common)
            else:
                extra = {"speed": "fast"} if config.FAST_MODE else {}
                cm = client.beta.messages.stream(
                    model=config.MODEL, betas=["server-side-fallback-2026-07-01"],
                    fallbacks="default", **common, **extra)
            with cm as stream:
                for chunk in stream.text_stream:
                    if not alive():
                        return None  # user moved on; drop this reply
                    reply.append(chunk)
                    feed(chunk)
                final = stream.get_final_message()
            if final.stop_reason == "refusal":
                self._fail(on_event, "Sorry, I can't help with that one.")
                return None
        except anthropic.AuthenticationError:
            self._fail(on_event, "My API key isn't working. Check it in Settings.")
            return None
        except (anthropic.APIConnectionError, anthropic.RateLimitError, anthropic.APIStatusError) as e:
            self.log("error", f"API error: {e}")
            self._fail(on_event, "I couldn't reach my brain just now. Try again.")
            return None
        return "".join(reply)

    # ---------- Local (free, runs on your PC through Ollama) ----------
    def _local(self, shot, user_text, feed, alive, on_event):
        messages = [{"role": "system", "content": SYSTEM}] + self.history + [{
            "role": "user",
            "content": user_text + "\nAnswer ONLY with BOX/NOBOX, SAY and WAIT/DONE lines.",
            "images": [shot.b64],
        }]
        body = json.dumps({"model": config.LOCAL_MODEL, "messages": messages, "stream": True,
                           "keep_alive": "30m", "options": {"temperature": 0.2}}).encode()
        req = urllib.request.Request(config.OLLAMA_URL.rstrip("/") + "/api/chat", data=body,
                                     headers={"Content-Type": "application/json"})
        reply = []
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                for raw in r:
                    if not alive():
                        return None
                    obj = json.loads(raw)
                    if obj.get("error"):
                        raise RuntimeError(obj["error"])
                    chunk = obj.get("message", {}).get("content", "")
                    if chunk:
                        reply.append(chunk)
                        feed(chunk)
                    if obj.get("done"):
                        break
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="ignore")[:300]
            self.log("error", f"Local brain error: {detail}")
            if "not found" in detail:
                self._fail(on_event, f"I don't have the {config.LOCAL_MODEL} model yet. "
                                     "Check Settings for how to get it.")
            else:
                self._fail(on_event, "My local brain had a problem. Check the log.")
            return None
        except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
            self.log("error", f"Can't reach Ollama at {config.OLLAMA_URL}: {e}")
            self._fail(on_event, "I can't find my local brain. Is Ollama running?")
            return None
        except Exception as e:
            self.log("error", f"Local brain error: {e}")
            self._fail(on_event, "My local brain had a problem. Check the log.")
            return None
        return "".join(reply)


def local_models():
    """Names of models installed in Ollama, or None if Ollama isn't running."""
    try:
        with urllib.request.urlopen(config.OLLAMA_URL.rstrip("/") + "/api/tags", timeout=3) as r:
            return [m["name"] for m in json.loads(r.read()).get("models", [])]
    except Exception:
        return None
