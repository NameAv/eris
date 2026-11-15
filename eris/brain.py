"""Talks to Claude. Streams the reply so the box and voice start early."""
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

    def turn(self, shot, text, on_event, alive):
        """Stream one step. Calls on_event(Event) as lines arrive. alive() -> False aborts."""
        client = self._get_client()
        if not client:
            on_event(Event("say", "I need an API key first. Open Settings and paste it in."))
            on_event(Event("done"))
            return
        user_text = f"{text}\n\n(Screenshot is {shot.img_w}x{shot.img_h} pixels.)"
        messages = self.history + [{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                         "data": shot.b64}},
            {"type": "text", "text": user_text},
        ]}]
        extra = {"speed": "fast"} if config.FAST_MODE else {}
        lines = LineStream()
        reply = []
        try:
            with client.beta.messages.stream(
                model=config.MODEL,
                max_tokens=config.MAX_TOKENS,
                system=SYSTEM,
                messages=messages,
                output_config={"effort": config.EFFORT},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                **extra,
            ) as stream:
                for chunk in stream.text_stream:
                    if not alive():
                        return  # user moved on; drop this reply
                    reply.append(chunk)
                    for ev in lines.feed(chunk):
                        on_event(ev)
                final = stream.get_final_message()
            for ev in lines.flush():
                on_event(ev)
            if final.stop_reason == "refusal":
                on_event(Event("say", "Sorry, I can't help with that one."))
                on_event(Event("done"))
                return
        except anthropic.AuthenticationError:
            on_event(Event("say", "My API key isn't working. Check it in Settings."))
            on_event(Event("done"))
            return
        except (anthropic.APIConnectionError, anthropic.RateLimitError, anthropic.APIStatusError) as e:
            self.log("error", f"API error: {e}")
            on_event(Event("say", "I couldn't reach my brain just now. Try again."))
            on_event(Event("done"))
            return

        self.history += [
            {"role": "user", "content": f"[screenshot] {text}"},
            {"role": "assistant", "content": "".join(reply).strip() or "NOBOX\nDONE"},
        ]
        self.history = self.history[-KEEP_MESSAGES:]
