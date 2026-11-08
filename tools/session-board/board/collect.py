"""動いているセッションの今の状態を、Claude Code・Codex が自分で書いている記録と tmux から集める。

書く物は無い（読むだけ）。読めない所は、カードの欄に「読めない」と理由を入れる。
"""
from __future__ import annotations

import datetime as dt
import glob
import json
import os
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field

from . import config
from .mask import mask_secrets

KNOWN_STATUS = {"busy", "idle", "waiting", "shell"}
# Claude Code 2.1.312 の中身から読んだ: waiting の時の waitingFor。どれも人が答えるまで止まっている
WAITING_LABELS = {
    "permission prompt": "許可の問い",
    "sandbox request": "許可の問い（ネット）",
    "worker request": "許可の問い（係）",
    "goal proposal": "許可の問い（目標）",
    "input needed": "質問への答え待ち",
    "dialog open": "画面の操作待ち",
}
STALE_MS = 2 * 60 * 60 * 1000  # 待機（やることを終えた）は最後に動いてから 2 時間まで。それより前は灰
# tmux のセッション名（比べる時は完全一致。部署側の名前は秘書の名前の頭と同じなので、頭だけで比べると取り違える）
DEPT_SESSION = config.dept_session()
SECRETARY_SESSION = config.secretary_session()
PROJECTS_ROOT = config.projects_root()
# 知らせ（チケット・報告）で動く場所: 部署側のセッションの全部の窓と、秘書のセッションの抜き出しの係（extractor）。
# 手が空いても社長の番ではない。秘書の本体の窓（secretariat）は社長と話す所
NOTICE_DRIVEN = [(DEPT_SESSION, None), (SECRETARY_SESSION, "extractor")]
# 問いかけの見分け: 最後の 1 行の終わり（句点・閉じ括弧・強調の印を外した後）
QUESTION_END_RE = re.compile(
    r"([?？]|(ます|です|でしょう|ません|ましょう|ますでしょう)か|かな"
    r"|(教えて|選んで|決めて|答えて|返して)(ください|下さい)"
    r"|ご(判断|指示|回答|返事|確認)を?(ください|下さい|お願いします|お願いいたします))$")
# 決めごとの節の見分け: 返事の最後の見出しの言葉。案件・案内の「案」は当てない
DECISION_RE = re.compile(
    r"まだ決まっていない|決まっていない|決めてほしい|決めて欲しい|決めていただ|決めてもらいたい"
    r"|選んでほしい|選んで欲しい|選んでいただ|選べる|選択肢|ご判断|判断が要る|判断をお願い|判断していただ"
    r"|確かめていただきたい|確認していただきたい|伺いたい|お伺い|質問|提案|案(?!件|内)"
    r"|open questions?|decisions?|questions?", re.I)
HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$")
BOLD_HEADING_RE = re.compile(r"^\s*\*\*([^*]+)\*\*\s*[:：]?\s*$")
LIST_OR_TABLE_RE = re.compile(r"^\s*(\d+[.)．、]|[-*+・]|\|)\s*")
PLACE_LABELS = {
    "pm": "PM 部", "dev": "開発部", "research": "リサーチ部", "marketing": "マーケティング部",
    "accounting": "経理部", "legal": "法務部", "corporate-planning": "経営企画部",
    "secretariat": "秘書室", "extractor": "秘書室 · 抜き出しの係",
}
TAIL_STEPS = (2 << 20, 16 << 20)  # 会話の記録は後ろから 2MB、見つからなければ 16MB まで読む
CODEX_TAIL = 1 << 20
TODO_MAX = 2 << 20
PROMPT_MAX = 140
REPLY_MAX = 120
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
TMUX_RE = re.compile(r"^(?P<session>[^:]+):(?P<window>@\d+)\.(?P<pane>%\d+)$")
AIPAIR_RE = re.compile(r"^aipair-(?P<name>.+)-[0-9a-f]{12}$")
TASK_RE = re.compile(r"^\s*[-*+]\s+\[([ xX!])\]\s")
FENCE_RE = re.compile(r"^\s*(```|~~~)")


class Unreadable(Exception):
    """読めない（無い・形が違う）。文は画面に出す理由"""


@dataclass
class Codex:
    state: str  # "busy" | "idle" | "unreadable"
    last_ms: int | None = None
    why: str = ""


@dataclass
class Card:
    key: str
    name: str
    place: str
    path: str
    notice_driven: bool
    status: str | None = None
    waiting_for: str | None = None
    prompt: str | None = None
    prompt_ms: int | None = None
    reply: str | None = None
    progress: tuple[int, int, int] | None = None  # 済・未・人待ち（[!]）
    last_ms: int | None = None
    codex: Codex | None = None
    problems: dict[str, str] = field(default_factory=dict)  # 欄 → 読めない理由
    color: str = ""
    label: str = ""
    hide_key: str = ""  # 隠す印（起こし直しても変わらない物。§ hide_key）
    cwd: str = ""  # 作業の場所（グループの自動の分け方に使う）
    auto_group: str = ""  # 自動で入るグループ（groups.layout が決める）
    stopped: bool = False  # プロセスが止めてある（Ctrl-Z 等。/proc の状態が T・t）
    asks: bool = False  # 社長の最後の頼みへの最後の返事が、問いかけで終わっている（文は持たない）
    decides: bool = False  # その返事の最後の節が、社長に決めてほしいことの節（文は持たない）
    transcript: str = ""  # 会話の記録の場所（全文は、押された時にここから読む。画面には出さない）
    full_text: dict | None = None  # 見本だけ: 全文（{"prompt": ..., "reply": ...}）
    session_id: str = ""
    warn: str = ""  # カードに添える注意
    tmux_session: str | None = None


@dataclass
class Env:
    """読む場所（試しでは作り物の場所を渡す）。既定は CLAUDE_CONFIG_DIR・CODEX_HOME（無ければ ~/.claude・~/.codex）"""
    claude_home: str = field(default_factory=config.claude_home)
    proc: str = "/proc"
    now_ms: int | None = None
    tmux: Callable[[], list[str]] | None = None  # list-panes の行を返す
    codex_home: str = field(default_factory=config.codex_home)

    def now(self) -> int:
        return self.now_ms if self.now_ms is not None else int(dt.datetime.now().timestamp() * 1000)


def tmux_panes() -> list[str]:
    out = subprocess.run(
        ["tmux", "list-panes", "-a", "-F",
         "#{pane_id}\t#{pane_pid}\t#{session_name}\t#{window_id}\t#{window_name}\t#{window_index}\t#{automatic-rename}"],
        capture_output=True, text=True, timeout=5)
    if out.returncode != 0:
        raise Unreadable("tmux の一覧を読めない")
    return out.stdout.splitlines()


# ---- 生きているプロセス ----

def _stat(env: Env, pid: int) -> tuple[int, str, str] | None:
    """(親の番号, 起動の時刻, 状態の 1 字) を返す。プロセスが無ければ None"""
    try:
        with open(f"{env.proc}/{pid}/stat") as f:
            raw = f.read()
    except OSError:
        return None
    rest = raw.rsplit(")", 1)[1].split()
    return int(rest[1]), rest[19], rest[0]


def _pid_ns(env: Env) -> str:
    try:
        return os.readlink(f"{env.proc}/self/ns/pid")
    except OSError:
        return ""


def _alive(env: Env, rec: dict, ns: str) -> bool:
    """番号が使い回されていないか: 起動の時刻（procStart）とプロセスの名前空間で見分ける"""
    st = _stat(env, rec["pid"])
    if st is None or str(rec.get("procStart")) != st[1]:
        return False
    dom = rec.get("pidDomain")
    return not dom or not ns or dom.endswith(ns)


# ---- Claude Code の会話の記録 ----

def _ms(ts) -> int | None:
    if not isinstance(ts, str):
        return None
    try:
        return int(dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return None


def _human_text(rec: dict) -> str | None:
    """社長（か知らせの係）が打った依頼なら、その文"""
    if rec.get("type") != "user" or rec.get("isMeta") or rec.get("isCompactSummary") or rec.get("isSidechain"):
        return None
    origin = rec.get("origin")
    if not isinstance(origin, dict) or origin.get("kind") != "human":
        return None
    content = (rec.get("message") or {}).get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
            return None
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return None


def _reply_text(rec: dict) -> str | None:
    if rec.get("type") != "assistant" or rec.get("isSidechain"):
        return None
    content = (rec.get("message") or {}).get("content")
    if not isinstance(content, list):
        return None
    texts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
    texts = [t for t in texts if t.strip()]
    return texts[-1] if texts else None


def _auto_prompt(rec: dict) -> bool:
    """社長でない頼み（自動のターン: 作業の知らせ・道具が送った頼み 等）。origin が無いか、human でない物"""
    if rec.get("type") != "user" or rec.get("isMeta") or rec.get("isCompactSummary") or rec.get("isSidechain"):
        return False
    content = (rec.get("message") or {}).get("content")
    if isinstance(content, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
        return False
    if not isinstance(content, (str, list)):
        return False
    origin = rec.get("origin")
    return not (isinstance(origin, dict) and origin.get("kind") == "human")


def is_question(text: str | None) -> bool:
    """返事が社長への問いかけで終わっているか。迷う物は問いかけでない側（黄にしない側）に倒す"""
    if not text:
        return False
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    if not lines:
        return False
    last = re.sub(r"^(#{1,6}\s+|[-*+>]\s+|\d+[.)]\s+)", "", lines[-1])
    last = re.sub(r"[\s。．.!！」』）)\]】*_`~]+$", "", last)
    return bool(QUESTION_END_RE.search(last))


def has_decision_section(text: str | None) -> bool:
    """返事の最後の節が、社長に決めてほしいことの節か。最後の見出し（# の見出し・太字だけの行）の言葉で見る。
    見出しが無ければ、最後のかたまりが「決めごとの言葉の行＋番号つきの一覧・表」か。本文の途中だけの言葉は見ない"""
    if not text:
        return False
    lines, fenced, heading = text.strip().splitlines(), False, None
    for ln in lines:
        if FENCE_RE.match(ln):
            fenced = not fenced
            continue
        if fenced:
            continue  # コードのかたまりの中の # は見出しではない
        m = HEADING_RE.match(ln) or BOLD_HEADING_RE.match(ln)
        if m:
            heading = m.group(1)
    if heading is not None:
        return bool(DECISION_RE.search(heading))
    blocks = [b.splitlines() for b in re.split(r"\n\s*\n", text.strip()) if b.strip()]
    if not blocks:
        return False
    last = [ln for ln in blocks[-1] if ln.strip()]
    items = [ln for ln in last if LIST_OR_TABLE_RE.match(ln)]
    if not items:
        return False
    lead = next((ln for ln in last if not LIST_OR_TABLE_RE.match(ln)), None)
    if lead is None and len(blocks) > 1:  # 一覧だけのかたまりなら、その前のかたまりの最後の行が頭
        lead = blocks[-2][-1]
    return bool(lead and DECISION_RE.search(lead))


def read_transcript(path: str, steps=TAIL_STEPS) -> dict:
    """後ろから読み、最後の依頼・その後の最後の返事・最後の記録の時刻を返す。
    answer は、社長の最後の頼みへの最後の返事（自動のターンへの返事は飛ばす）"""
    size = os.path.getsize(path)
    saw_user_text = saw_origin = False
    for n in steps:
        start = max(0, size - n)
        with open(path, "rb") as f:
            f.seek(start)
            lines = f.read().split(b"\n")
        if start > 0:
            lines = lines[1:]  # 途中から読んだ最初の行は切れている
        out = {"prompt": None, "prompt_ms": None, "reply": None, "last_ms": None, "answer": None}
        pending = None  # 後ろから見て、今の区切り（次の頼みまで）の最後の返事
        for line in reversed(lines):
            if not (b'"user"' in line or b'"assistant"' in line or (out["last_ms"] is None and b'"timestamp"' in line)):
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if not isinstance(rec, dict):
                continue
            if out["last_ms"] is None:
                out["last_ms"] = _ms(rec.get("timestamp"))
            r = _reply_text(rec)
            if r is not None:
                if out["reply"] is None:
                    out["reply"] = r
                if pending is None:
                    pending = r
                continue
            if rec.get("type") == "user":
                saw_origin = saw_origin or isinstance(rec.get("origin"), dict)
                saw_user_text = saw_user_text or isinstance((rec.get("message") or {}).get("content"), str)
            text = _human_text(rec)
            if text is None:
                if _auto_prompt(rec):
                    pending = None  # ここから後ろの返事は、自動のターンへの返事
                continue
            out["prompt"], out["prompt_ms"], out["answer"] = text, _ms(rec.get("timestamp")), pending
            return out
        if start == 0:
            break
    if saw_user_text and not saw_origin:
        raise Unreadable("依頼の形が知っている形と違う")
    out["reply"] = None  # 依頼が見つからない時、返事だけを出さない
    out["none"] = True
    return out


COMMAND_RE = re.compile(r"<command-name>(.*?)</command-name>", re.S)
COMMAND_ARGS_RE = re.compile(r"<command-args>(.*?)</command-args>", re.S)
PASTED_RE = re.compile(r"</?pasted_content\b[^>]*>")
BASH_RE = re.compile(r"<bash-input>(.*?)</bash-input>", re.S)


def clean_prompt(text: str) -> str:
    """打った形に戻す: スラッシュの命令は「/名前 引数」、! の命令は「! 命令」、貼り付けは包みの印を外す"""
    m = COMMAND_RE.search(text)
    if m:
        args = COMMAND_ARGS_RE.search(text)
        return f"{m[1].strip()} {args[1].strip() if args else ''}".strip()
    b = BASH_RE.search(text)
    if b:
        return f"! {b[1].strip()}"
    return PASTED_RE.sub(" ", text)


def _one_line(text: str, limit: int, first_only: bool) -> str:
    text = mask_secrets(text)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return ""
    if first_only:
        s = re.sub(r"^(?:#{1,6}\s+|[-*+>]\s+|\*\*)", "", lines[0]).replace("**", "")
    else:
        s = " ".join(lines)
    s = re.sub(r"\s+", " ", s)
    return s if len(s) <= limit else s[: limit - 1] + "…"


# ---- tasks/todo.md ----

def read_progress(cwd: str) -> tuple[int, int, int] | None:
    path = os.path.join(cwd, "tasks", "todo.md")
    if not os.path.isfile(path):
        return None
    if os.path.getsize(path) > TODO_MAX:
        raise Unreadable("tasks/todo.md が大きすぎる")
    done = todo = blocked = 0
    fenced = False
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if FENCE_RE.match(line):
                fenced = not fenced
                continue
            m = None if fenced else TASK_RE.match(line)
            if not m:
                continue
            mark = m.group(1)
            if mark in "xX":
                done += 1
            elif mark == "!":
                blocked += 1
            else:
                todo += 1
    return done, todo, blocked


# ---- Codex ----

def _codex_rollout(env: Env, pid: int) -> str | None:
    """Codex のプロセスが開いている記録（<CODEX_HOME>/sessions/ の下の rollout-*.jsonl）"""
    try:
        fds = os.listdir(f"{env.proc}/{pid}/fd")
    except OSError:
        return None
    sessions = os.path.join(os.path.realpath(env.codex_home), "sessions") + "/"  # /proc の fd はたどった先の形
    for fd in fds:
        try:
            target = os.readlink(f"{env.proc}/{pid}/fd/{fd}")
        except OSError:
            continue
        if target.startswith(sessions) and os.path.basename(target).startswith("rollout-") and target.endswith(".jsonl"):
            return target
    return None


def codex_processes(env: Env) -> list[tuple[int, str]]:
    """(番号, 開いている記録のファイル)。Codex の本体だけ（node の包みと子のプロセスを除く）"""
    found = []
    try:
        pids = [int(p) for p in os.listdir(env.proc) if p.isdigit()]
    except OSError:
        return found
    for pid in pids:
        try:
            with open(f"{env.proc}/{pid}/cmdline", "rb") as f:
                argv0 = f.read().split(b"\0", 1)[0].decode("utf-8", "replace")
        except OSError:
            continue
        if "/@openai/codex" not in argv0 or os.path.basename(argv0) != "codex":
            continue
        rollout = _codex_rollout(env, pid)
        if rollout:
            found.append((pid, rollout))
    return found


def read_codex(path: str) -> Codex:
    """最後の task_started / task_complete で、作業中か待ちかを決める"""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            f.seek(max(0, size - CODEX_TAIL))
            lines = f.read().split(b"\n")
    except OSError:
        return Codex("unreadable", why="Codex の記録を開けない")
    last_ms = None
    for line in reversed(lines):
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not isinstance(rec, dict):
            continue
        if last_ms is None:
            last_ms = _ms(rec.get("timestamp"))
        p = rec.get("payload")
        if rec.get("type") == "event_msg" and isinstance(p, dict) and p.get("type") in ("task_started", "task_complete"):
            return Codex("busy" if p["type"] == "task_started" else "idle", last_ms)
    return Codex("unreadable", last_ms, "Codex の記録に作業の始まりと終わりの印が無い")


# ---- まとめる ----

def _place(tmux: str | None, panes: dict) -> tuple[str, str | None, str | None, dict | None]:
    """(場所の表示, tmux のセッション名, 窓の名前, tmux の窓の情報)"""
    m = TMUX_RE.match(tmux or "")
    if not m:
        return "", None, None, None
    pane = panes.get(m["pane"])
    if pane and pane["session"] != m["session"]:
        pane = None  # 別の tmux（-L の試し等）の同じ番号の窓。名前を取り違えない
    session = pane["session"] if pane else m["session"]
    window = pane["window_name"] if pane else None
    return f"{session}:{window or m['window']}", session, window, pane


def hide_key(cwd: str, pane: dict | None) -> str:
    """隠す印。プロセスの番号や会話の ID は、起こし直すと変わるので使わない。
    tmux の窓: 名前を付けた窓（部署・秘書室）は「セッション名:窓の名前」、名前が自動で変わる窓（aipair）は
    「セッション名:#窓の番号」。tmux の外（と、tmux の窓が分からない時）は作業の場所"""
    if pane:
        if pane["autorename"] == "1":
            return f"tmux:{pane['session']}:#{pane['index']}"
        return f"tmux:{pane['session']}:{pane['window_name']}"
    return f"cwd:{cwd}"


def _name(cwd: str, session: str | None, window: str | None) -> str:
    if session:
        m = AIPAIR_RE.match(session)
        if m:
            return m["name"]
        if window and session in (DEPT_SESSION, SECRETARY_SESSION):  # 完全一致
            return PLACE_LABELS.get(window, window)
    return os.path.basename(cwd.rstrip("/")) or cwd


def _notice_driven(session: str | None, window: str | None) -> bool:
    return any(session == s and (w is None or window == w) for s, w in NOTICE_DRIVEN)


def _short_path(cwd: str) -> str:
    """表示用に、会社のフォルダーの置いてある所（案件のフォルダーの根）か、ホームの頭を削る"""
    for root in (PROJECTS_ROOT + "/", os.path.expanduser("~") + "/"):
        if cwd.startswith(root):
            return cwd[len(root):]
    return cwd


def decide_color(card: Card, now_ms: int) -> None:
    """黄（社長の番）は、許可の問い等の waiting と、社長の最後の頼みへの返事が問いかけで終わった時・決めごとの節で終わった時だけ。
    社長と話す場所でやることを終えた物は待機（2 時間まで）、それより前は灰。部署と抜き出しの係は灰"""
    if card.stopped:  # 止めてある物は、記録の状態に関わらず社長の番にしない
        card.color, card.label = "gray", "一時停止中"
        return
    if card.problems.get("status"):
        card.color, card.label = "unreadable", "読めない"
        return
    codex_busy = card.codex is not None and card.codex.state == "busy"
    if card.status == "busy":
        card.color, card.label = "blue", "作業中"
    elif card.status == "shell":
        card.color, card.label = "blue", "裏で命令が動いている"
    elif card.status == "waiting":
        card.color, card.label = "yellow", WAITING_LABELS.get(card.waiting_for or "", "人の操作待ち")
    elif codex_busy:
        card.color, card.label = "blue", "Codex が作業中"
    elif card.notice_driven:
        card.color, card.label = "gray", "手が空いている（次の知らせ待ち）"
    elif card.asks:  # 時間の上限は付けない（答えるまで社長の番）
        card.color, card.label = "yellow", "社長への問いかけ（社長の番）"
    elif card.decides:  # 見出しに決めごとの言葉があれば黄に倒す（取りこぼしの方が害が大きい）
        card.color, card.label = "yellow", "決めてほしいことがある（社長の番）"
    elif card.last_ms is not None and now_ms - card.last_ms < STALE_MS:
        card.color, card.label = "standby", "待機（やることを終えた）"
    else:
        card.color, card.label = "gray", "しばらく動いていない"


ORDER = {"yellow": 0, "blue": 1, "unreadable": 2, "standby": 3, "gray": 4}


def sort_key(card: Card):
    """止めてある物は最後。同じ色の中では、許可の問い・質問が先、社長と話す所が知らせで動く所より先"""
    asking = card.color == "yellow" and card.status == "waiting"
    return (card.stopped, ORDER[card.color], 0 if asking else 1, card.notice_driven, -(card.last_ms or 0), card.name)


def collect(env: Env | None = None) -> tuple[list[Card], list[str]]:
    """カードと、全体の読めない所（tmux 等）を返す"""
    env = env or Env()
    notes: list[str] = []
    now = env.now()
    panes: dict = {}
    pane_pids: dict = {}
    try:
        for row in (env.tmux or tmux_panes)():
            parts = row.split("\t")
            if len(parts) != 7:
                raise Unreadable("tmux の一覧の形が違う")
            pane_id, pane_pid, session, window_id, window_name, index, autorename = parts
            panes[pane_id] = {"session": session, "window": window_id, "window_name": window_name,
                              "index": index, "autorename": autorename}
            pane_pids[int(pane_pid)] = pane_id
    except (Unreadable, OSError, ValueError, subprocess.SubprocessError) as e:
        notes.append(f"tmux: {e if isinstance(e, Unreadable) else '一覧を読めない'}")

    ns = _pid_ns(env)
    cards: list[Card] = []
    by_session: dict[str, Card] = {}
    for path in sorted(glob.glob(os.path.join(env.claude_home, "sessions", "*.json"))):
        try:
            with open(path) as f:
                rec = json.load(f)
        except (OSError, ValueError):
            notes.append(f"Claude Code の記録 1 本を読めない（{os.path.basename(path)}）")
            continue
        if not isinstance(rec, dict) or not isinstance(rec.get("pid"), int):
            notes.append(f"Claude Code の記録 1 本の形が違う（{os.path.basename(path)}）")
            continue
        if not _alive(env, rec, ns):
            continue
        cards.append(_claude_card(env, rec, panes, by_session, now, _stat(env, rec["pid"])[2] in ("T", "t")))
    _warn_same_conversation(cards)

    for pid, rollout in codex_processes(env):
        cx = read_codex(rollout)
        pane = _pane_of(env, pid, pane_pids, panes)
        session = pane["session"] if pane else None
        owner = by_session.get(session) if session else None
        if owner is not None and owner.codex is None:
            owner.codex = cx
            if cx.last_ms and (owner.last_ms or 0) < cx.last_ms:
                owner.last_ms = cx.last_ms
            continue
        cwd = _readlink(f"{env.proc}/{pid}/cwd") or ""
        card = Card(key=f"codex-{pid}", name=_name(cwd, session, None) + "（Codex だけ）", place=session or "",
                    path=_short_path(cwd), notice_driven=False, codex=cx, last_ms=cx.last_ms,
                    hide_key="codex:" + hide_key(cwd, pane), cwd=cwd, tmux_session=session)
        card.status = {"busy": "busy", "idle": "idle"}.get(cx.state)
        if cx.state == "unreadable":
            card.problems["status"] = cx.why
        cards.append(card)

    for card in cards:
        decide_color(card, now)
    cards.sort(key=sort_key)
    return cards, notes


def _readlink(p: str) -> str | None:
    try:
        return os.readlink(p)
    except OSError:
        return None


def _pane_of(env: Env, pid: int, pane_pids: dict, panes: dict) -> dict | None:
    """プロセスの親をたどり、どの tmux の窓で動いているかを返す"""
    for _ in range(12):
        if pid in pane_pids:
            return panes[pane_pids[pid]]
        st = _stat(env, pid)
        if st is None or st[0] <= 1:
            return None
        pid = st[0]
    return None


def _warn_same_conversation(cards: list[Card]) -> None:
    """止めてある物が、動いている物と同じ会話を持っていれば、止めてある方に一言添える"""
    running = {c.session_id for c in cards if not c.stopped and c.session_id}
    for c in cards:
        if c.stopped and c.session_id in running:
            c.warn = "動いているセッションと同じ会話。続けると記録が混ざる"


def _claude_card(env: Env, rec: dict, panes: dict, by_session: dict, now: int, stopped: bool = False) -> Card:
    cwd = rec.get("cwd") if isinstance(rec.get("cwd"), str) else ""
    place, session, window, pane = _place(rec.get("tmux"), panes)
    name, key = _name(cwd, session, window), hide_key(cwd, pane)
    if stopped:
        # 止めてある物は一時の物。同じ窓の動いている物と印がぶつからないよう、プロセスの番号と起動の時刻を足す
        name, key = name + "（一時停止中）", f"{key}:stopped:{rec['pid']}-{rec.get('procStart')}"
    card = Card(key=f"claude-{rec['pid']}", name=name, place=place,
                path=_short_path(cwd), notice_driven=_notice_driven(session, window), hide_key=key,
                cwd=cwd, tmux_session=session, stopped=stopped,
                session_id=rec.get("sessionId") if isinstance(rec.get("sessionId"), str) else "")
    if session and session not in by_session and not stopped:  # Codex は動いている方のカードに付ける
        by_session[session] = card
    status = rec.get("status")
    if status not in KNOWN_STATUS:
        card.problems["status"] = f"知らない状態（{str(status)[:20]}）" if status else "状態が書かれていない"
    card.status = status
    card.waiting_for = rec.get("waitingFor") if isinstance(rec.get("waitingFor"), str) else None
    times = [t for t in (rec.get("statusUpdatedAt"), rec.get("updatedAt")) if isinstance(t, int)]
    card.last_ms = max(times) if times else None

    sid = rec.get("sessionId")
    try:
        if not isinstance(sid, str) or not UUID_RE.match(sid):
            raise Unreadable("会話の番号の形が違う")
        found = glob.glob(os.path.join(env.claude_home, "projects", "*", f"{sid}.jsonl"))
        if not found:
            raise Unreadable("会話の記録が無い（最初の依頼の前か、置き場が変わった）")
        card.transcript = max(found, key=os.path.getmtime)
        tr = read_transcript(card.transcript)
        if tr.get("none"):
            card.prompt = None
        else:
            card.prompt = _one_line(clean_prompt(tr["prompt"]), PROMPT_MAX, first_only=False)
            card.prompt_ms = tr["prompt_ms"]
            # 返事の頭は、社長の最後の頼みへの返事（自動のターンの返事は飛ばす。全文のモーダルと同じ物）
            card.reply = _one_line(tr["answer"], REPLY_MAX, first_only=True) if tr.get("answer") else None
            card.asks = is_question(tr.get("answer"))
            card.decides = has_decision_section(tr.get("answer"))
        if tr["last_ms"] and (card.last_ms or 0) < tr["last_ms"]:
            card.last_ms = tr["last_ms"]
    except Unreadable as e:
        card.problems["prompt"] = str(e)
    except OSError:
        card.problems["prompt"] = "会話の記録を開けない"

    try:
        card.progress = read_progress(cwd) if cwd else None
    except Unreadable as e:
        card.problems["progress"] = str(e)
    except OSError:
        card.problems["progress"] = "tasks/todo.md を開けない"
    return card


def full_texts(card: Card) -> dict:
    """押された時に読む全文: 頼んだこと（社長の最後の頼み。貼り付けの印などは外す）と、その頼みへの最後の返事。
    伏せ字・大きさの上限は、返す所（server）で当てる"""
    if card.full_text is not None:
        return card.full_text
    if not card.transcript:
        return {"prompt": None, "reply": None}
    tr = read_transcript(card.transcript)
    if tr.get("none"):
        return {"prompt": None, "reply": None}
    return {"prompt": clean_prompt(tr["prompt"]), "reply": tr.get("answer")}
