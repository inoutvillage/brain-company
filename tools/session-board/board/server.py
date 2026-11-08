"""一覧の画面。127.0.0.1 だけで待ち受け、Host が 127.0.0.1:<番号>・localhost:<番号> 以外の要求は断る。

読む道は決まった 7 つだけ（URL から場所や命令を受け取らない）。全文の道（GET /text）は、今のカードの印と、
prompt・reply の 2 つだけを受け付け、ページだけが付ける見出しを求める。書く入り口は POST /prefs の 1 つだけで、
このページからの要求（Origin・JSON・専用の見出し）だけを受け付け、画面の設定のファイル 1 つだけに書く
（隠す・戻す・グループへ移す・グループの名前・畳む）。
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from . import config, groups, prefs, render
from .collect import Env, collect, full_texts
from .mask import mask_count

STATE_DIR = config.state_dir()  # SESSION_BOARD_STATE_DIR、無ければ ${XDG_STATE_HOME:-~/.local/state}/brain-company/session-board
CACHE_SEC = 2.0
MAX_BODY = 1024
CARD_RE = re.compile(r"^(?:claude|codex)-[0-9]{1,10}$")  # 全文の道で 1 枚を指すカードの番号（collect の Card.key）
MAX_TEXT = 200 * 1024  # 全文の上限（UTF-8 のバイト）。超えた分は切り、省いた字数を返す
REQUEST_FIELDS = {
    "hide": {"action", "key"},
    "show": {"action", "key"},
    "move": {"action", "key", "group"},
    "rename": {"action", "group", "name"},
    "fold": {"action", "group", "open"},
}
HEADERS = {
    "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
                               "img-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


def log(msg: str) -> None:
    """失敗は手元の記録に残す（中身は書かない。理由と数だけ）"""
    os.makedirs(STATE_DIR, mode=0o700, exist_ok=True)
    path = os.path.join(STATE_DIR, "board.log")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}\n")


class Board:
    def __init__(self, source):
        self.source = source  # () -> (cards, notes, now_ms)
        self.lock = threading.Lock()
        self.at = 0.0
        self.snap = None

    def get(self):
        with self.lock:
            if self.snap is None or time.monotonic() - self.at > CACHE_SEC:
                self.snap = self.source()
                self.at = time.monotonic()
            return self.snap


def valid_request(req) -> bool:
    """形だけを確かめる（印・グループが今あるか・名前の長さは prefs.change で確かめる）"""
    if not isinstance(req, dict) or req.get("action") not in REQUEST_FIELDS:
        return False
    need = set(REQUEST_FIELDS[req["action"]])
    if req["action"] == "move" and req.get("group") == "new":
        need.add("name")
    if set(req) != need:
        return False
    if "key" in req and not (isinstance(req["key"], str) and prefs.KEY_RE.match(req["key"])):
        return False
    if "group" in req:
        ok_new = req["action"] == "move" and req["group"] == "new"
        if not (isinstance(req["group"], str) and (ok_new or prefs.GROUP_RE.match(req["group"]))):
            return False
    if "name" in req and not isinstance(req["name"], str):
        return False
    return "open" not in req or isinstance(req["open"], bool)


def real_source():
    env = Env()
    cards, notes = collect(env)
    return cards, notes, env.now()


class Handler(BaseHTTPRequestHandler):
    server_version = "session-board"
    sys_version = ""

    def do_GET(self):
        self._serve(send_body=True)

    def do_HEAD(self):
        self._serve(send_body=False)

    def _refuse(self):
        self._send(405, "text/plain; charset=utf-8", "この道は読むだけです".encode(), True, {"Allow": "GET, HEAD"})

    do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _refuse

    def _state(self) -> str:
        return self.server.state_dir or STATE_DIR

    def _send(self, code, ctype, body, send_body, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in {**HEADERS, **(extra or {})}.items():
            self.send_header(k, v)
        self.end_headers()
        if send_body:
            self.wfile.write(body)

    def _text(self, code, msg):
        self._send(code, "text/plain; charset=utf-8", msg.encode(), True)

    # ---- 書く入り口（POST /prefs だけ） ----

    def do_POST(self):
        if self.headers.get("Host") not in self.server.allowed_hosts:
            self._text(421, "misdirected request")
            return
        if urlsplit(self.path).path != "/prefs" or urlsplit(self.path).query:
            self._refuse()
            return
        # よそのページ（同じ PC のブラウザで開いた物）からの書き込みを止める。Host の確かめだけでは止まらない
        if self.headers.get("Origin") not in {f"http://{h}" for h in self.server.allowed_hosts}:
            self._text(403, "このページからの要求だけを受け付けます")
            return
        if (self.headers.get("Content-Type") or "").split(";")[0].strip().lower() != "application/json":
            self._text(415, "JSON だけを受け付けます")
            return
        if self.headers.get("X-Session-Board") != "1":
            self._text(403, "このページからの要求だけを受け付けます")
            return
        if self.headers.get("Transfer-Encoding"):
            self._text(411, "長さの分かる要求だけを受け付けます")
            return
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self._text(411, "長さの分かる要求だけを受け付けます")
            return
        if not 0 < length <= MAX_BODY:
            self._text(413, "大きすぎます")
            return
        try:
            req = json.loads(self.rfile.read(length))
        except ValueError:
            self._text(400, "形が違います")
            return
        if not valid_request(req):
            self._text(400, "形が違います")
            return
        try:
            cards, _, _ = self.server.board.get()
            now_groups = {g.id for g in groups.layout(cards, prefs.load(self._state()))}
            saved = prefs.change(self._state(), req, {c.hide_key: c for c in cards}, now_groups)
        except ValueError as e:
            self._text(400, str(e))
            return
        except OverflowError as e:
            self._text(409, str(e))
            return
        except prefs.PrefsError as e:
            log(f"prefs failed: {e}")
            self._text(500, str(e))
            return
        except Exception as e:
            log(f"prefs failed: {type(e).__name__}")
            self._text(500, f"書けない（{type(e).__name__}）")
            return
        self._send(200, "application/json", json.dumps({"hidden": len(saved["hidden"])}).encode(), True)

    # ---- 読む道 ----

    def _serve(self, send_body):
        if self.headers.get("Host") not in self.server.allowed_hosts:
            self._send(421, "text/plain; charset=utf-8", b"misdirected request", send_body)
            return
        path = urlsplit(self.path).path
        if path == "/board.css":
            self._send(200, "text/css; charset=utf-8", render.CSS.encode(), send_body)
            return
        if path == "/board.js":
            self._send(200, "text/javascript; charset=utf-8", render.JS.encode(), send_body)
            return
        if path == "/favicon.ico":  # ブラウザが自分で取りに来る。断った記録に残さない
            self._send(204, "image/x-icon", b"", send_body)
            return
        if path == "/text":
            self._full_text(send_body)
            return
        if path not in ("/", "/cards", "/healthz"):
            self._send(404, "text/plain; charset=utf-8", b"not found", send_body)
            return
        try:
            cards, notes, now = self.server.board.get()
        except Exception as e:  # 集められない時は、空の画面ではなく理由を出す
            log(f"collect failed: {type(e).__name__}")
            self._send(500, "text/plain; charset=utf-8", f"集められない（{type(e).__name__}）".encode(), send_body)
            return
        notes = list(notes)
        try:
            saved = prefs.load(self._state())
        except prefs.PrefsError as e:
            saved = prefs.empty()  # 読めない時は全部を自動のグループで出し、読めないことを上に出す（隠したままにしない）
            notes.append(str(e))
        laid = groups.layout(cards, saved)
        visible = [c for g in laid for c in g.cards]
        if path == "/healthz":
            counts = {c: sum(1 for x in visible if x.color == c) for c in render.COLOR_NAMES}
            fields = sum(len(x.problems) for x in cards)
            data = {"cards": len(cards), **counts, "unreadable_fields": fields, "notes": len(notes),
                    "hidden": len(saved["hidden"]), "hidden_running": len(cards) - len(visible), "groups": len(laid)}
            self._send(200, "application/json", json.dumps(data).encode(), send_body)
            return
        fragment = render.board_html(laid, notes, now, saved["hidden"])
        html = fragment if path == "/cards" else render.page_html(fragment, self.server.banner)
        self._send(200, "text/html; charset=utf-8", html.encode(), send_body, {"X-Board-Version": render.VERSION})

    def _full_text(self, send_body):
        """押された時に、1 枚のカードの全文（頼んだこと・返事）を返す。伏せ字を当て、上限で切る"""
        if self.headers.get("X-Session-Board") != "1":
            self._send(403, "text/plain; charset=utf-8", "このページからの要求だけを受け付けます".encode(), send_body)
            return
        try:
            q = parse_qs(urlsplit(self.path).query, keep_blank_values=True, strict_parsing=True)
        except ValueError:
            q = None
        if not q or set(q) != {"card", "kind"} or any(len(v) != 1 for v in q.values()) \
                or q["kind"][0] not in ("prompt", "reply") or not CARD_RE.match(q["card"][0]):
            self._send(400, "text/plain; charset=utf-8", "形が違います".encode(), send_body)
            return
        card_id, kind = q["card"][0], q["kind"][0]
        try:
            cards, _, _ = self.server.board.get()
            # カードの番号で 1 枚に決める（隠す印 hide_key は、同じ場所の tmux の外の 2 つの会話で重なる）
            card = next((c for c in cards if c.key == card_id and c.hide_key), None)
            text = full_texts(card).get(kind) if card else None
        except Exception as e:
            log(f"text failed: {type(e).__name__}")
            self._send(500, "text/plain; charset=utf-8", f"読めない（{type(e).__name__}）".encode(), send_body)
            return
        if not text:
            self._send(404, "text/plain; charset=utf-8", "無い".encode(), send_body)
            return
        text, masked = mask_count(text)  # 伏せてから切る（鍵の途中で切って頭を見せないため）
        raw = text.encode("utf-8")
        omitted = 0
        if len(raw) > MAX_TEXT:
            kept = raw[:MAX_TEXT].decode("utf-8", "ignore")
            omitted, text = len(text) - len(kept), kept
        body = json.dumps({"text": text, "omitted": omitted, "masked": masked}, ensure_ascii=False).encode()
        self._send(200, "application/json; charset=utf-8", body, send_body)

    def log_message(self, fmt, *args):
        pass

    def log_request(self, code="-", size="-"):
        if str(code) not in ("200", "204", "304"):
            log(f"refused {code} {self.command} {urlsplit(self.path).path[:60]!r} "
                f"host={str(self.headers.get('Host'))[:60]!r} origin={str(self.headers.get('Origin'))[:60]!r}")


def make_server(port: int, source=real_source, banner: str = "", state_dir: str | None = None) -> ThreadingHTTPServer:
    """state_dir: 画面の設定の置き場（None なら本物の STATE_DIR。見本・試しは別の場所を渡す）"""
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    srv.allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    srv.board = Board(source)
    srv.banner = banner
    srv.state_dir = state_dir
    srv.daemon_threads = True
    return srv
