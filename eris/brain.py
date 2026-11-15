"""The thinking part. Streams the reply so the box and voice start early.

Three brains: Claude Opus (best), Claude Haiku (very cheap), or a free local
vision model running on your own PC through Ollama.
"""
import json
import urllib.error
import urllib.request

import anthropic

from . import config, settings
from . import screen
from .protocol import Event, LineStream, parse_line

SYSTEM = """You are Eris, a guide who lives on the user's computer. They might be working \
in Unity, a web browser, Windows or anything else. You see their screen in each \
screenshot. Your job: guide them through doing a task THEMSELVES, one action at a time, \
by drawing a red box around exactly what to click and telling them what to do.

Personality: you're warm, quick and a little cheeky, like a clever friend who loves \
showing people things. You have your own tastes and opinions (you adore crimson red) and \
you're happy to pick things yourself when asked. A short playful remark or a bit of \
encouragement now and then ("Nice, nailed it.") is welcome, but the instruction always \
comes first and every spoken line stays short.

Treat them as a complete beginner. Never assume they know names, spellings, web \
addresses, shortcuts or jargon.

Reply with ONLY these lines, in this order, nothing else (no markdown):
BOX x1 y1 x2 y2   - pixel coords in the CURRENT screenshot of the ONE thing to click or \
type into now (see "Boxes" below). Or NOBOX if nothing needs pointing at.
WHAT <words>      - right after BOX: a short, specific description of that exact element, \
used to find it precisely in a zoomed-in view, e.g. "the browser address bar at the very \
top", "the blue Add Component button", "the Wikipedia link in the first search result", \
"the third image in the top row".
TYPE <text>       - only when they need to type: the exact short text to type. It is \
shown inside the box.
SAY <sentence>    - 1 to 3 SAY lines, spoken out loud: short, natural, plain. First SAY = \
the action. Optionally one more = how to recognise it or why, or a quick bit of you.
Then exactly one of:
WAIT click        - they need to click inside the box.
WAIT next         - they need to type, press a key, drag or wait for something. You \
watch the screen, so you'll see when it's done.
DONE              - the whole task is complete, or it was just a question.

Or, ONLY when you get an automatic look or the screen is still loading, the single line:
KEEP              - nothing worth saying yet; keep the current box and keep waiting.

Boxes (accuracy matters most):
- Box the exact clickable thing, tightly: the button, the link text itself, the text \
field itself, the one image thumbnail, the menu item. Never a whole panel, row, page \
section or a big area around it.
- Only box things you can actually see in THIS screenshot. If the target is hidden \
(behind a menu, scrolled away, in another window), box the thing that gets them closer.
- Whenever you choose something (an image, a search result, a file, a colour), box that \
exact one so they can see which you mean.

Know where you are (look carefully before pointing):
- First work out which app or window is in front and, in a browser, which website it is \
(read the address bar and the page).
- Don't mix up the three kinds of search box: the browser's address bar (the very top \
bar that shows the web address; typing there searches the web), a search engine's own \
box (e.g. the big box in the middle of google.com) and a website's own search box (e.g. \
Wikipedia's, which only searches Wikipedia). Pick the one that fits the task and call it \
by the right name. To go to a new website, use the address bar.

How to guide well:
- ONE action per reply. You'll get a fresh screenshot after they do it.
- Pick the easiest route for a beginner. Never make them type a full web address or \
anything long from memory. To open a website: click the address bar, TYPE just the \
simple name (e.g. TYPE wikipedia), press Enter, then pick the right result.
- When they must type, always add a TYPE line. If a word is tricky, also spell it out in \
SAY (e.g. "That's W, I, K, I, P, E, D, I, A.").
- When there's a list to choose from (search results, menus, files, components), box the \
exact right one and say how to recognise it. Tell them to skip ads marked Sponsored or Ad.
- Say which key to press when it matters ("then press Enter").
- Each new screenshot: first check what happened. If they did the step, move on. If \
something unexpected happened or they clicked the wrong thing, say so kindly and guide \
them back.
- If you can't tell what they mean, NOBOX, ask one short question, DONE.
- Be accurate about Unity: menu paths, component names, Inspector layout.

Automatic looks: while you're waiting, you're sent a new screenshot whenever their screen \
changes. Then: if the step is done, give the next step (or DONE). If they're still \
partway through (still typing, page still loading) or nothing important changed, reply \
KEEP. If they went off track, help them back.

Example:
BOX 412 66 980 92
WHAT the browser address bar at the very top
TYPE wikipedia
SAY Click the address bar at the very top and type wikipedia, then press Enter.
SAY No need for the full address, just the name.
WAIT next"""

LOCATE_SYSTEM = """You find one element in a zoomed-in part of a screenshot. Reply with \
ONLY one line: BOX x1 y1 x2 y2 - pixel coordinates in THIS image, tight around exactly \
that element (the button, link text, text field or image itself, nothing around it). \
If it isn't in this image, reply NONE."""

# History is trimmed in chunks (not one turn at a time) so the cached prefix
# stays the same for many steps in a row.
HISTORY_MAX = 28
HISTORY_KEEP = 12
CACHE = {"type": "ephemeral"}


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
            # Short timeout: a live helper should fail fast and say so, not hang.
            self.client = anthropic.Anthropic(api_key=key, timeout=60.0, max_retries=2)
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
        if len(self.history) > HISTORY_MAX:
            self.history = self.history[-HISTORY_KEEP:]

    def _fail(self, on_event, msg):
        on_event(Event("fail", msg))

    # ---------- Claude (paid, best) ----------
    def _claude(self, shot, user_text, feed, alive, on_event):
        client = self._get_client()
        if not client:
            self._fail(on_event, "I need an API key for that brain. Open Settings, or switch to the free one.")
            return None
        # Prompt caching: the system prompt and earlier conversation are re-read
        # from cache (much cheaper, and replies start sooner). Breakpoint 1 is the
        # system prompt; breakpoint 2 is the last message of the history.
        history = [dict(m) for m in self.history]
        if history:
            last = history[-1]
            history[-1] = {"role": last["role"], "content": [
                {"type": "text", "text": last["content"], "cache_control": CACHE}]}
        messages = history + [{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                         "data": shot.b64}},
            {"type": "text", "text": user_text},
        ]}]
        common = dict(max_tokens=config.MAX_TOKENS,
                      system=[{"type": "text", "text": SYSTEM, "cache_control": CACHE}],
                      messages=messages, output_config={"effort": config.EFFORT})
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
            u = final.usage
            self.log("debug", f"tokens: in={u.input_tokens} cache_read={u.cache_read_input_tokens} "
                              f"cache_write={u.cache_creation_input_tokens} out={u.output_tokens}")
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
        # num_ctx: Ollama's default context is too small for the instructions plus a
        # screenshot (~1200 tokens) plus history, and it silently drops the start
        # (the instructions!) when it overflows.
        body = json.dumps({"model": config.LOCAL_MODEL, "messages": messages, "stream": True,
                           "keep_alive": "30m",
                           "options": {"temperature": 0.2, "num_ctx": 8192}}).encode()
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


def _parse_locate(text):
    for line in text.splitlines():
        ev = parse_line(line)
        if ev and ev.kind == "box":
            return ev.value
        if ev and ev.kind == "none":
            return None
    return None


def locate(brain, shot, box, what, alive):
    """Precision pass: zoom into the area around a rough box and ask for the exact
    element. Returns a tight box in screen coords, or None to keep the rough one."""
    z = screen.zoom(shot, box, snap=brain.snap())
    if not z or not what:
        return None
    b64, left, top, sx, sy, w, h = z
    prompt = f"Find: {what}\n(This image is {w}x{h} pixels.)"
    try:
        if config.BRAIN == "local":
            body = json.dumps({"model": config.LOCAL_MODEL, "stream": False, "keep_alive": "30m",
                               "options": {"temperature": 0, "num_ctx": 4096},
                               "messages": [{"role": "system", "content": LOCATE_SYSTEM},
                                            {"role": "user", "content": prompt, "images": [b64]}]}).encode()
            req = urllib.request.Request(config.OLLAMA_URL.rstrip("/") + "/api/chat", data=body,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                text = json.loads(r.read()).get("message", {}).get("content", "")
        else:
            client = brain._get_client()
            if not client:
                return None
            req = dict(max_tokens=2000, system=LOCATE_SYSTEM, output_config={"effort": "low"},
                       messages=[{"role": "user", "content": [
                           {"type": "image", "source": {"type": "base64",
                                                        "media_type": "image/jpeg", "data": b64}},
                           {"type": "text", "text": prompt}]}])
            if config.BRAIN == "claude-cheap":
                msg = client.messages.create(model=config.CHEAP_MODEL, **req)
            else:
                msg = client.beta.messages.create(
                    model=config.MODEL, betas=["server-side-fallback-2026-07-01"],
                    fallbacks="default", **req)
            if msg.stop_reason == "refusal":
                return None
            text = "".join(b.text for b in msg.content if b.type == "text")
    except Exception as e:
        brain.log("debug", f"precision pass failed: {e}")
        return None
    if not alive():
        return None
    found = _parse_locate(text)
    if not found:
        return None
    x1, y1, x2, y2 = found
    # Sanity checks: inside the crop, not a sliver, not basically the whole crop.
    if x2 - x1 < 3 or y2 - y1 < 3 or x1 < -2 or y1 < -2 or x2 > w + 2 or y2 > h + 2:
        return None
    if (x2 - x1) * (y2 - y1) > 0.6 * w * h:
        return None
    p = config.BOX_PADDING
    return (int(left + x1 * sx) - p, int(top + y1 * sy) - p,
            int(left + x2 * sx) + p, int(top + y2 * sy) + p)


def local_models():
    """Names of models installed in Ollama, or None if Ollama isn't running."""
    try:
        with urllib.request.urlopen(config.OLLAMA_URL.rstrip("/") + "/api/tags", timeout=3) as r:
            return [m["name"] for m in json.loads(r.read()).get("models", [])]
    except Exception:
        return None
