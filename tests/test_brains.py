"""The brains: Claude request shapes, the free local brain (against a fake Ollama), and
the zoomed-in precision pass."""
import http.server
import json
import threading
import types

from helpers import check, done, fake_shot

from eris import brain, config, screen

CAP = {}


class FakeStream:
    def __init__(self, reply="NOBOX\nSAY Hi.\nDONE\n", **kw):
        CAP.clear()
        CAP.update(kw)
        self.reply = reply

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    @property
    def text_stream(self):
        return iter(self.reply.splitlines(keepends=True))

    def get_final_message(self):
        return types.SimpleNamespace(stop_reason="end_turn", usage=types.SimpleNamespace(
            input_tokens=10, cache_read_input_tokens=900, cache_creation_input_tokens=0, output_tokens=5))


def fake_client():
    stream = lambda **kw: FakeStream(**kw)
    create = lambda **kw: CAP.clear() or CAP.update(kw)
    ns = lambda: types.SimpleNamespace(stream=stream, create=create)
    return types.SimpleNamespace(messages=ns(), beta=types.SimpleNamespace(messages=ns()))


def claude_brain():
    b = brain.Brain(log=lambda *a: None)
    b._get_client = lambda: fake_client()
    return b


def test_claude_requests():
    config.BRAIN, config.EFFORT = "claude", "low"
    b = claude_brain()
    shot = fake_shot()
    for i in range(3):
        b.turn(shot, f"q{i}", lambda e: None, lambda: True)
    check("Opus: system prompt is cached", CAP["system"][0]["cache_control"] == {"type": "ephemeral"})
    check("Opus: end of history is cached", CAP["messages"][-2]["content"][0]["cache_control"])
    check("Opus: refusal fallback on, no thinking override",
          CAP["fallbacks"] == "default" and "thinking" not in CAP and CAP["model"] == config.MODEL)
    check("stored history stays plain text", isinstance(b.history[-1]["content"], str))
    for i in range(20):
        b.turn(shot, f"x{i}", lambda e: None, lambda: True)
    check("history is trimmed in chunks, starting on a user turn",
          len(b.history) <= brain.HISTORY_MAX and b.history[0]["role"] == "user")
    config.BRAIN = "claude-cheap"
    b.turn(shot, "hi", lambda e: None, lambda: True)
    check("Haiku on Low: no thinking", CAP["thinking"] == {"type": "disabled"} and CAP["model"] == config.CHEAP_MODEL)
    config.EFFORT = "medium"
    b.turn(shot, "hi", lambda e: None, lambda: True)
    check("Haiku on Medium: thinks", "thinking" not in CAP)
    config.BRAIN, config.EFFORT = "claude", "low"


def test_prewarm():
    config.BRAIN = "claude"
    b = claude_brain()
    b.history = [{"role": "user", "content": "[screenshot] hi"}, {"role": "assistant", "content": "DONE"}]
    b.prewarm()
    check("warm-up: zero tokens, same cached prefix as a real request",
          CAP["max_tokens"] == 0 and CAP["system"][0]["cache_control"]
          and CAP["messages"][-2]["content"][0]["cache_control"])
    CAP.clear()
    b.prewarm()
    check("no second warm-up while still warm", not CAP)


def test_app_and_elements_in_prompt():
    config.BRAIN = "claude"
    b = claude_brain()
    els = [{"type": 50005, "name": "Wikipedia", "rect": (200, 600, 380, 630)}]
    shot = screen.Shot("x", 0, 0, 2560, 1440, 2560 / 1400, 1440 / 788, 1400, 788, None, els,
                       {"name": "Google Chrome", "title": "Google"})
    b.turn(shot, "go", lambda e: None, lambda: True)
    text = CAP["messages"][-1]["content"][1]["text"]
    check("the AI is told which app is in front", 'App in front: Google Chrome' in text)
    check("...and gets the numbered list", '[1] link "Wikipedia" at 109,328 to 207,344' in text)


class Ollama(http.server.BaseHTTPRequestHandler):
    family, thinking, reply, last = "qwen3vl", True, "BOX 500 500 600 550\nSAY Click it.\nWAIT click\n", {}

    def log_message(self, *a):
        pass

    def _json(self, obj):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps(obj).encode())

    def do_GET(self):
        if self.path == "/api/ps":
            self._json({"models": [{"name": config.LOCAL_MODEL, "size": 8, "size_vram": 6}]})
        else:
            self._json({"models": [{"name": config.LOCAL_MODEL}]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/api/show":
            return self._json({"details": {"family": Ollama.family},
                               "capabilities": ["vision"] + (["thinking"] if Ollama.thinking else [])})
        Ollama.last = body
        if not body.get("stream"):
            return self._json({"message": {"content": Ollama.reply}})
        self.send_response(200)
        self.end_headers()
        for part in Ollama.reply.splitlines(keepends=True):
            self.wfile.write((json.dumps({"message": {"content": part}, "done": False}) + "\n").encode())
        self.wfile.write((json.dumps({"message": {"content": ""}, "done": True}) + "\n").encode())


def test_local_brain():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Ollama)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    config.BRAIN, config.OLLAMA_URL = "local", f"http://127.0.0.1:{srv.server_port}"
    # qwen3-vl: 0-1000 positions, a thinking model
    config.LOCAL_MODEL = "qwen3-vl:8b"
    brain._info.clear()
    b = brain.Brain(log=lambda *a: None)
    b.history = [{"role": "user" if i % 2 == 0 else "assistant", "content": "x"} for i in range(20)]
    shot = screen.Shot("IMG", 0, 0, 2560, 1440, 2560 / 1400, 1440 / 788, 1400, 788)
    evs = []
    b.turn(shot, "go", evs.append, lambda: True)
    body = Ollama.last
    check("qwen3: thinking switched off", body["think"] is False)
    check("steady answers, capped length",
          body["options"]["temperature"] == 0 and body["options"]["num_predict"] == 300)
    check("short instructions with the 0-1000 scale", "0-1000 scale" in body["messages"][0]["content"])
    check("only the last 8 turns of history", len(body["messages"]) == 10)
    box = next(e.value for e in evs if e.kind == "box")
    check("qwen3 positions translated to pixels", tuple(round(v) for v in box) == (700, 394, 840, 433))
    check("graphics card check", abs(brain.gpu_fit() - 0.75) < 0.01)
    # qwen2.5-vl: pixel positions, multiples of 28
    config.LOCAL_MODEL, Ollama.family, Ollama.thinking = "qwen2.5vl:7b", "qwen25vl", False
    Ollama.reply = "BOX 100 50 200 80\nSAY Click it.\nWAIT click\n"
    brain._info.clear()
    evs = []
    b.turn(shot, "go", evs.append, lambda: True)
    check("qwen2.5: pixels, image sides in 28s, no think flag",
          b.snap() == 28 and "think" not in Ollama.last
          and next(e.value for e in evs if e.kind == "box") == (100, 50, 200, 80))
    # Ollama not running
    config.OLLAMA_URL = "http://127.0.0.1:1"
    evs = []
    b.turn(shot, "go", evs.append, lambda: True)
    check("Ollama off: a friendly message, no crash",
          evs and evs[0].kind == "fail" and "Ollama" in evs[0].value)
    srv.shutdown()
    config.BRAIN = "claude"


def test_precision_pass():
    from PIL import Image, ImageDraw
    full = Image.new("RGB", (2560, 1440), "white")
    ImageDraw.Draw(full).rectangle((1500, 700, 1620, 740), fill="blue")
    shot = screen.Shot("", -2560, 0, 2560, 1440, 2.0, 2.0, 1280, 720, full)   # a monitor on the left
    rough = (-2560 + 1440, 660, -2560 + 1700, 780)
    _, left, top, sx, sy, w, h = screen.zoom(shot, rough)
    ans = (f"BOX {round((-1060 - left) / sx)} {round((700 - top) / sy)} "
           f"{round((-940 - left) / sx)} {round((740 - top) / sy)}")
    config.BRAIN = "claude"
    b = brain.Brain(log=lambda *a: None)
    reply = types.SimpleNamespace(stop_reason="end_turn", content=[types.SimpleNamespace(type="text", text=ans)])
    b._get_client = lambda: types.SimpleNamespace(beta=types.SimpleNamespace(
        messages=types.SimpleNamespace(create=lambda **k: reply)))
    tight = brain.locate(b, shot, rough, "the blue button", lambda: True)
    check("zoom check maps back to the screen exactly",
          tight and abs(tight[0] - (-1064)) <= 3 and abs(tight[3] - 744) <= 3, tight)
    for bad in ["NONE", "BOX 0 0 1 1", f"BOX 0 0 {w} {h}", "BOX -50 -50 10 10", "no idea"]:
        reply.content[0].text = bad
        if brain.locate(b, shot, rough, "x", lambda: True) is not None:
            check(f"bad answer rejected: {bad}", False)
            break
    else:
        check("bad zoom answers are rejected", True)


for name, fn in list(globals().items()):
    if name.startswith("test_"):
        fn()
done("brains")
