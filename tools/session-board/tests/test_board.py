"""作り物の記録（偽の ~/.claude・/proc・tmux）で確かめる。本物の中身は使わない"""
import http.client
import io
import json
import os
import runpy
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 利用者の設定（環境変数）に左右されないよう、外してから読み込む（この試しのプロセスの中だけ）
SETTINGS = ("TMUX_SESSION", "SESSION_BOARD_COMPANY_ROOT", "SESSION_BOARD_STATE_DIR", "SESSION_BOARD_PORT",
            "XDG_STATE_HOME", "CLAUDE_CONFIG_DIR", "CODEX_HOME")
for _k in SETTINGS:
    os.environ.pop(_k, None)

from board import collect as bc  # noqa: E402
from board import config, groups, prefs, render, server  # noqa: E402

NOW = 1_800_000_000_000  # 2027-01-15 08:00:00 UTC
MIN = 60_000
SID = "11111111-2222-3333-4444-555555555555"
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL_STATE = server.STATE_DIR
DEPT = bc.DEPT_SESSION  # 部署側の tmux セッション（既定 brain-company）
SEC = bc.SECRETARY_SESSION  # 秘書の tmux セッション（既定 brain-company-secretariat）
DEV_KEY = f"tmux:{DEPT}:dev"
BASH = shutil.which("bash") or "/bin/bash"
_state = None


def setUpModule():
    # 試しが本物の置き場（失敗の記録）に書かないよう、全部の試しで一時の場所に替える
    global _state
    _state = tempfile.TemporaryDirectory()
    server.STATE_DIR = _state.name


def tearDownModule():
    server.STATE_DIR = REAL_STATE
    _state.cleanup()


def iso(ms):
    import datetime as dt
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).isoformat().replace("+00:00", "Z")


def human(text, ms, **kw):
    return {"type": "user", "origin": {"kind": "human"}, "timestamp": iso(ms), "message": {"role": "user", "content": text}, **kw}


def reply(text, ms):
    return {"type": "assistant", "timestamp": iso(ms), "message": {"content": [{"type": "text", "text": text}]}}


class Fake:
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        r = os.path.realpath(self.tmp.name)  # 本物の /proc の fd の向け先は、たどった先の形
        self.home = os.path.join(r, "claude")
        self.proc = os.path.join(r, "proc")
        self.work = os.path.join(r, "work")
        self.codex = os.path.join(r, ".codex")
        for d in (f"{self.home}/sessions", f"{self.home}/projects/-work", f"{self.proc}/self/ns", self.work):
            os.makedirs(d)
        os.symlink("pid:[4026531836]", f"{self.proc}/self/ns/pid")
        self.panes = []

    def process(self, pid, start="777", ppid=1, argv0="claude", cwd=None, state="S"):
        d = f"{self.proc}/{pid}"
        os.makedirs(f"{d}/fd", exist_ok=True)
        with open(f"{d}/stat", "w") as f:
            f.write(f"{pid} (x) {state} {ppid} " + " ".join(["0"] * 17) + f" {start} 0 0\n")
        with open(f"{d}/cmdline", "wb") as f:
            f.write(argv0.encode() + b"\0")
        if cwd:
            os.symlink(cwd, f"{d}/cwd")
        return d

    def session(self, pid=100, sid=SID, tmux="aipair-demo-0123456789ab:@1.%1", status="idle", records=None, **kw):
        self.process(pid)
        rec = {"pid": pid, "sessionId": sid, "cwd": self.work, "procStart": "777", "status": status,
               "statusUpdatedAt": NOW - 5 * MIN, "pidDomain": "linux:x:pid:[4026531836]", "tmux": tmux, **kw}
        with open(f"{self.home}/sessions/{pid}.json", "w") as f:
            json.dump(rec, f)
        if records is not None:
            with open(f"{self.home}/projects/-work/{sid}.jsonl", "w") as f:
                for r in records:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
        if tmux:
            s, rest = tmux.split(":")
            win, pane = rest.split(".")
            # 名前を付けた窓（部署・秘書室）は自動の改名なし、aipair は自動の改名あり
            named = "window_name" in kw
            self.panes.append(f"{pane}\t{pid}\t{s}\t{win}\t{kw.pop('window_name', 'claude')}\t{kw.pop('index', '0')}\t{'0' if named else '1'}")

    def env(self):
        return bc.Env(claude_home=self.home, proc=self.proc, now_ms=NOW, tmux=lambda: self.panes, codex_home=self.codex)

    def todo(self, text):
        os.makedirs(f"{self.work}/tasks", exist_ok=True)
        with open(f"{self.work}/tasks/todo.md", "w") as f:
            f.write(text)


class LiveTests(unittest.TestCase):
    def setUp(self):
        self.f = Fake()

    def tearDown(self):
        self.f.tmp.cleanup()

    def test_reused_number_is_not_alive(self):
        self.f.session(pid=100, records=[])
        self.f.process(100, start="999")  # 同じ番号の別のプロセス
        cards, _ = bc.collect(self.f.env())
        self.assertEqual(cards, [])

    def test_other_pid_namespace_and_old_format_are_not_alive(self):
        self.f.session(pid=100, records=[], pidDomain="linux:x:pid:[999]")
        self.f.session(pid=101, sid="11111111-2222-3333-4444-555555555556", records=[], tmux=None)
        os.remove(f"{self.f.home}/sessions/101.json")
        with open(f"{self.f.home}/sessions/101.json", "w") as fh:
            json.dump({"pid": 101, "sessionId": "x", "cwd": "/", "status": "idle"}, fh)  # procStart が無い古い形
        cards, _ = bc.collect(self.f.env())
        self.assertEqual(cards, [])

    def test_key_files_are_never_opened(self):
        with open(f"{self.f.home}/sessions/.abc.key", "w") as fh:
            fh.write("not json")
        self.f.session(records=[human("a", NOW - MIN)])
        cards, notes = bc.collect(self.f.env())
        self.assertEqual(len(cards), 1)
        self.assertEqual(notes, [])


class ColorTests(unittest.TestCase):
    def setUp(self):
        self.f = Fake()

    def tearDown(self):
        self.f.tmp.cleanup()

    def one(self, **kw):
        self.f.session(records=kw.pop("records", [human("頼む", NOW - 10 * MIN)]), **kw)
        cards, _ = bc.collect(self.f.env())
        self.assertEqual(len(cards), 1)
        return cards[0]

    def test_busy_and_shell_are_blue(self):
        self.assertEqual(self.one(status="busy").color, "blue")

    def test_shell_is_blue(self):
        c = self.one(status="shell")
        self.assertEqual((c.color, c.label), ("blue", "裏で命令が動いている"))

    def test_waiting_reasons_are_yellow(self):
        c = self.one(status="waiting", waitingFor="permission prompt", statusUpdatedAt=NOW - 3 * 24 * 60 * MIN,
                     records=[human("頼む", NOW - 3 * 24 * 60 * MIN)])
        self.assertEqual((c.color, c.label), ("yellow", "許可の問い"))  # 何日たっても、許可の問いは黄のまま

    def test_waiting_question(self):
        c = self.one(status="waiting", waitingFor="input needed")
        self.assertEqual((c.color, c.label), ("yellow", "質問への答え待ち"))

    def test_idle_recent_without_question_is_standby(self):
        c = self.one(status="idle")
        self.assertEqual((c.color, c.label), ("standby", "待機（やることを終えた）"))  # 社長の番ではない

    def test_idle_old_is_gray(self):
        c = self.one(status="idle", statusUpdatedAt=NOW - 3 * 60 * MIN, records=[human("頼む", NOW - 3 * 60 * MIN)])
        self.assertEqual((c.color, c.label), ("gray", "しばらく動いていない"))

    def test_departments_idle_are_gray_even_when_recent(self):
        c = self.one(tmux=f"{DEPT}:@3.%3", window_name="dev")
        self.assertEqual((c.color, c.name), ("gray", "開発部"))

    def test_same_pane_number_on_another_tmux_server_is_not_borrowed(self):
        self.f.session(tmux="sbt:@0.%0", records=[])  # 別の tmux（-L）の窓
        self.f.panes = [f"%0\t999\t{SEC}\t@0\tsecretariat\t0\t0"]  # 既定の tmux には同じ番号の秘書室の窓
        c = bc.collect(self.f.env())[0][0]
        self.assertEqual((c.name, c.place, c.color), ("work", "sbt:@0", "standby"))

    def test_extractor_is_notice_driven(self):
        c = self.one(tmux=f"{SEC}:@1.%1", window_name="extractor")
        self.assertEqual(c.color, "gray")

    def test_secretariat_main_is_yellow_only_when_asking(self):
        c = self.one(tmux=f"{SEC}:@0.%0", window_name="secretariat")  # 返事がまだ無い・問いかけでない
        self.assertEqual((c.color, c.name), ("standby", "秘書室"))

    def test_unknown_status_is_unreadable(self):
        c = self.one(status="sleeping")
        self.assertEqual(c.color, "unreadable")
        self.assertIn("sleeping", c.problems["status"])

    def test_missing_status_is_unreadable(self):
        c = self.one(status=None)
        self.assertEqual(c.color, "unreadable")

    def test_order_yellow_first_asking_first(self):
        f = self.f
        f.session(pid=1, sid="11111111-2222-3333-4444-000000000001", status="busy", tmux="aipair-a-0123456789ab:@1.%1", records=[])
        f.session(pid=2, sid="11111111-2222-3333-4444-000000000002", status="idle", tmux="aipair-b-0123456789ab:@2.%2", records=[])
        f.session(pid=3, sid="11111111-2222-3333-4444-000000000003", status="waiting", waitingFor="permission prompt",
                  tmux="aipair-c-0123456789ab:@3.%3", records=[], statusUpdatedAt=NOW - 50 * MIN)
        f.session(pid=4, sid="11111111-2222-3333-4444-000000000004", status="idle", tmux=f"{DEPT}:@4.%4", records=[])
        cards, _ = bc.collect(f.env())
        self.assertEqual([c.name for c in cards][:3], ["c", "a", "b"])
        self.assertEqual([c.color for c in cards], ["yellow", "blue", "standby", "gray"])


class TranscriptTests(unittest.TestCase):
    def setUp(self):
        self.f = Fake()

    def tearDown(self):
        self.f.tmp.cleanup()

    def card(self, records):
        self.f.session(records=records)
        return bc.collect(self.f.env())[0][0]

    def test_last_human_prompt_and_reply_after_it(self):
        c = self.card([
            human("古い依頼", NOW - 30 * MIN), reply("古い返事", NOW - 29 * MIN),
            human("新しい依頼", NOW - 10 * MIN),
            {"type": "user", "timestamp": iso(NOW - 9 * MIN), "message": {"content": [{"type": "tool_result", "content": "x"}]}},
            {"type": "user", "isMeta": True, "origin": {"kind": "human"}, "timestamp": iso(NOW - 8 * MIN), "message": {"content": "meta"}},
            reply("## 返事の頭\n\n続きの行", NOW - 7 * MIN),
            # 作業の知らせのターン（社長の頼みではない）への返事は、返事の頭にしない
            {"type": "user", "origin": {"kind": "task-notification"}, "timestamp": iso(NOW - 6 * MIN), "message": {"content": "知らせ"}},
            reply("知らせへの返事", NOW - 5 * MIN),
        ])
        self.assertEqual(c.prompt, "新しい依頼")
        self.assertEqual(c.reply, "返事の頭")
        self.assertEqual(c.prompt_ms, NOW - 10 * MIN)
        self.assertEqual(c.last_ms, NOW - 5 * MIN)

    def test_reply_before_prompt_is_not_shown(self):
        c = self.card([reply("前の返事", NOW - 20 * MIN), human("今の依頼", NOW - 10 * MIN)])
        self.assertEqual(c.prompt, "今の依頼")
        self.assertIsNone(c.reply)

    def test_last_activity_uses_newest_record(self):
        c = self.card([human("依頼", NOW - 10 * MIN), reply("返事", NOW - MIN)])
        self.assertEqual(c.last_ms, NOW - MIN)

    def test_no_origin_field_means_unknown_format(self):
        c = self.card([{"type": "user", "timestamp": iso(NOW), "message": {"content": "依頼"}}])
        self.assertIn("形", c.problems["prompt"])

    def test_no_prompt_yet(self):
        c = self.card([])
        self.assertIsNone(c.prompt)
        self.assertNotIn("prompt", c.problems)

    def test_missing_transcript_is_unreadable(self):
        self.f.session(records=None)
        c = bc.collect(self.f.env())[0][0]
        self.assertIn("会話の記録が無い", c.problems["prompt"])

    def test_bad_session_id_is_unreadable(self):
        self.f.session(sid="../../etc/passwd", records=None)
        c = bc.collect(self.f.env())[0][0]
        self.assertEqual(c.problems["prompt"], "会話の番号の形が違う")

    def test_broken_lines_are_skipped(self):
        self.f.session(records=[human("依頼", NOW - MIN)])
        with open(f"{self.f.home}/projects/-work/{SID}.jsonl", "a") as fh:
            fh.write('{"type": "user", "broken\n[1,2]\n')
        c = bc.collect(self.f.env())[0][0]
        self.assertEqual(c.prompt, "依頼")

    def test_prompt_beyond_first_step_is_found(self):
        path = f"{self.f.work}/t.jsonl"
        with open(path, "w") as fh:
            fh.write(json.dumps(human("遠い依頼", NOW - 50 * MIN), ensure_ascii=False) + "\n")
            for i in range(200):
                fh.write(json.dumps({"type": "progress", "timestamp": iso(NOW - MIN), "pad": "x" * 100}) + "\n")
        out = bc.read_transcript(path, steps=(4096, 1 << 20))
        self.assertEqual(out["prompt"], "遠い依頼")

    def test_slash_command_and_paste_and_bang(self):
        self.assertEqual(bc.clean_prompt("<command-name>/review</command-name>\n<command-message>review</command-message>\n<command-args>12</command-args>"), "/review 12")
        self.assertEqual(bc.clean_prompt('<pasted_content id="1">貼った文</pasted_content id="1">').strip(), "貼った文")
        self.assertEqual(bc.clean_prompt("<bash-input>ls</bash-input>"), "! ls")

    def test_secrets_are_masked_before_cutting(self):
        key = "sk-ant-" + "A" * 40
        c = self.card([human("x" * 120 + " " + key, NOW - MIN)])
        self.assertNotIn("AAAAAAAAAA", c.prompt)
        c2 = self.card([human("token=abcdefgh12345678 を使って", NOW - MIN)])
        self.assertNotIn("abcdefgh12345678", c2.prompt)


class ProgressTests(unittest.TestCase):
    def setUp(self):
        self.f = Fake()

    def tearDown(self):
        self.f.tmp.cleanup()

    def test_counts_and_fences(self):
        self.f.todo("# 計画\n- [x] 一\n- [X] 二\n  - [ ] 三\n* [!] 四\n```\n- [ ] 例の行\n```\n- [] 形が違う\n")
        self.assertEqual(bc.read_progress(self.f.work), (2, 1, 1))

    def test_no_todo_means_no_bar(self):
        self.assertIsNone(bc.read_progress(self.f.work))
        self.f.session(records=[])
        c = bc.collect(self.f.env())[0][0]
        self.assertNotIn("bar", render.card_html(c, NOW))

    def test_too_big_is_unreadable(self):
        self.f.todo("- [ ] a\n" * (bc.TODO_MAX // 8 + 10))
        self.f.session(records=[])
        c = bc.collect(self.f.env())[0][0]
        self.assertIn("progress", c.problems)
        self.assertIn("読めない", render.card_html(c, NOW))


class CodexTests(unittest.TestCase):
    def setUp(self):
        self.f = Fake()

    def tearDown(self):
        self.f.tmp.cleanup()

    def rollout(self, events, name="rollout-a.jsonl"):
        d = f"{self.f.codex}/sessions/2026/10/28"
        os.makedirs(d, exist_ok=True)
        path = f"{d}/{name}"
        with open(path, "w") as fh:
            for i, e in enumerate(events):
                fh.write(json.dumps({"timestamp": iso(NOW - (10 - i) * MIN), "type": "event_msg", "payload": {"type": e}}) + "\n")
        return path

    def codex(self, pid, path, ppid, cwd=None):
        d = self.f.process(pid, ppid=ppid, argv0="/home/u/.npm-global/lib/node_modules/@openai/codex/node_modules/@openai/codex-linux-x64/vendor/codex", cwd=cwd)
        os.symlink(path, f"{d}/fd/7")

    def test_busy_and_idle(self):
        self.assertEqual(bc.read_codex(self.rollout(["task_started", "item_completed"])).state, "busy")
        self.assertEqual(bc.read_codex(self.rollout(["task_started", "task_complete", "token_count"], "rollout-b.jsonl")).state, "idle")
        self.assertEqual(bc.read_codex(self.rollout(["token_count"], "rollout-c.jsonl")).state, "unreadable")

    def test_codex_joins_the_pair_card_and_makes_it_blue(self):
        self.f.session(pid=100, tmux="aipair-demo-0123456789ab:@1.%1", records=[human("頼む", NOW - 30 * MIN)],
                       statusUpdatedAt=NOW - 30 * MIN)
        self.f.process(200)  # Codex の窓の殻
        self.f.panes.append("%2\t200\taipair-demo-0123456789ab\t@1\tclaude\t0\t1")
        self.f.process(201, ppid=200, argv0="node")  # node の包み
        self.codex(202, self.rollout(["task_started"]), ppid=201)
        cards, _ = bc.collect(self.f.env())
        self.assertEqual(len(cards), 1)
        self.assertEqual((cards[0].codex.state, cards[0].color, cards[0].label), ("busy", "blue", "Codex が作業中"))

    def test_codex_without_pair_gets_its_own_card(self):
        self.codex(300, self.rollout(["task_complete"]), ppid=1, cwd=self.f.work)
        cards, _ = bc.collect(self.f.env())
        self.assertEqual(len(cards), 1)
        self.assertIn("Codex だけ", cards[0].name)

    def test_only_rollouts_under_codex_home_are_read(self):
        """CODEX_HOME（無ければ ~/.codex）の sessions の下だけを Codex の記録と見なす。置き場がリンクでも当たる"""
        other = f"{self.f.tmp.name}/elsewhere/sessions"
        os.makedirs(other)
        with open(f"{other}/rollout-z.jsonl", "w") as fh:
            fh.write(json.dumps({"timestamp": iso(NOW), "type": "event_msg", "payload": {"type": "task_complete"}}) + "\n")
        self.codex(300, os.path.realpath(f"{other}/rollout-z.jsonl"), ppid=1, cwd=self.f.work)
        self.assertEqual(bc.collect(self.f.env())[0], [])
        self.codex(301, self.rollout(["task_complete"]), ppid=1, cwd=self.f.work)
        link = f"{self.f.tmp.name}/codex-link"
        os.symlink(self.f.codex, link)
        env = self.f.env()
        env.codex_home = link
        self.assertEqual([c.key for c in bc.collect(env)[0]], ["codex-301"])


class RenderTests(unittest.TestCase):
    def test_text_is_escaped(self):
        c = bc.Card(key="claude-1", name="<b>n</b>", place="p", path="q", notice_driven=False, status="idle",
                    prompt="<script>alert(1)</script>", reply="<img src=x onerror=1>", last_ms=NOW)
        bc.decide_color(c, NOW)
        html = render.board_html(groups.layout([c], prefs.empty()), [], NOW)
        self.assertNotIn("<script>", html)
        self.assertNotIn("<img", html)
        self.assertIn("&lt;script&gt;", html)

    def test_page_has_no_inline_script_or_style_attr(self):
        c = bc.Card(key="claude-1", name="n", place="", path="", notice_driven=False, status="idle", progress=(1, 1, 1), last_ms=NOW)
        bc.decide_color(c, NOW)
        html = render.page_html(render.board_html(groups.layout([c], prefs.empty()), [], NOW))
        self.assertNotIn("style=", html)
        self.assertNotIn("<script>", html)  # 外の /board.js だけ

    def test_page_size_is_one_knob(self):
        """大きさは --scale の 1 か所。px は全部それを掛ける（残すのは 1px の線・キーボードの枠・狭い窓の幅・丸の角だけ）"""
        import re
        self.assertEqual(re.findall(r"--scale:([^;}]+)", render.CSS), ["1"])  # 既定は 100%
        bare = re.findall(r"(?<!calc\()-?\d+(?:\.\d+)?px(?!\*var\(--scale\))", render.CSS)
        self.assertEqual(sorted(set(bare)), ["1px", "2px", "420px", "999px"])
        self.assertEqual(render.CSS.count("2px solid var(--blue);outline-offset:2px"), 1)  # 2px はキーボードの枠だけ
        self.assertIn("@media (max-width:420px)", render.CSS)


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        c = bc.Card(key="claude-1", name="n", place="", path="", notice_driven=False, status="idle",
                    prompt="ひみつの依頼", last_ms=NOW)
        bc.decide_color(c, NOW)
        cls.srv = server.make_server(0, lambda: ([c], [], NOW))
        cls.port = cls.srv.server_address[1]
        cls.srv.allowed_hosts = {f"127.0.0.1:{cls.port}", f"localhost:{cls.port}"}
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def req(self, path="/", method="GET", host=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.putrequest(method, path, skip_host=True)
        if host is not None:
            conn.putheader("Host", host)
        conn.endheaders()
        r = conn.getresponse()
        body = r.read()
        conn.close()
        return r, body

    def test_listens_on_loopback_only(self):
        self.assertEqual(self.srv.server_address[0], "127.0.0.1")

    def test_allowed_hosts(self):
        for host in (f"127.0.0.1:{self.port}", f"localhost:{self.port}"):
            r, body = self.req(host=host)
            self.assertEqual(r.status, 200, host)
            self.assertIn("ひみつの依頼", body.decode())
            self.assertIn("script-src 'self'", r.getheader("Content-Security-Policy"))

    def test_other_hosts_are_refused(self):
        for host in ("evil.example", f"evil.example:{self.port}", "127.0.0.1", f"127.0.0.1:{self.port + 1}", ""):
            r, body = self.req(host=host)
            self.assertEqual(r.status, 421, host)
            self.assertNotIn("ひみつ", body.decode())
        r, _ = self.req(host=None)
        self.assertEqual(r.status, 421)

    def test_read_only(self):
        for m in ("POST", "PUT", "DELETE", "PATCH", "OPTIONS"):
            r, _ = self.req(method=m, host=f"127.0.0.1:{self.port}")
            self.assertEqual(r.status, 405, m)

    def test_only_fixed_paths(self):
        for p in ("/../../etc/passwd", "/file?path=/etc/passwd", "/cards/x", "/x"):
            r, _ = self.req(p, host=f"127.0.0.1:{self.port}")
            self.assertEqual(r.status, 404, p)

    def test_favicon_is_empty_and_not_logged(self):
        log = os.path.join(server.STATE_DIR, "board.log")
        before = open(log).read() if os.path.exists(log) else ""
        r, body = self.req("/favicon.ico", host=f"127.0.0.1:{self.port}")
        self.assertEqual((r.status, body), (204, b""))
        after = open(log).read() if os.path.exists(log) else ""
        self.assertEqual(before, after)

    def test_healthz_has_numbers_only(self):
        r, body = self.req("/healthz", host=f"localhost:{self.port}")
        data = json.loads(body)
        self.assertEqual(data["cards"], 1)
        self.assertNotIn("ひみつ", body.decode())

    def test_collect_failure_is_shown_not_hidden(self):
        def broken():
            raise RuntimeError("x")
        srv = server.make_server(0, broken)
        port = srv.server_address[1]
        srv.allowed_hosts = {f"127.0.0.1:{port}"}
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            with tempfile.TemporaryDirectory() as d, mock.patch.object(server, "STATE_DIR", d):
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                conn.request("GET", "/", headers={"Host": f"127.0.0.1:{port}"})
                r = conn.getresponse()
                self.assertEqual(r.status, 500)
                self.assertIn("集められない", r.read().decode())
                self.assertTrue(os.path.exists(os.path.join(d, "board.log")))
        finally:
            srv.shutdown()
            srv.server_close()


class HideKeyTests(unittest.TestCase):
    def setUp(self):
        self.f = Fake()

    def tearDown(self):
        self.f.tmp.cleanup()

    def keys(self):
        return sorted(c.hide_key for c in bc.collect(self.f.env())[0])

    def test_aipair_uses_session_and_window_number(self):
        self.f.session(tmux="aipair-demo-0123456789ab:@7.%9", records=[])
        self.assertEqual(self.keys(), ["tmux:aipair-demo-0123456789ab:#0"])  # @7・%9（起こすたびに変わる）は使わない

    def test_named_windows_on_the_same_place_are_separate(self):
        self.f.session(pid=1, sid="11111111-2222-3333-4444-000000000001", tmux=f"{SEC}:@0.%0",
                       window_name="secretariat", records=[])
        self.f.session(pid=2, sid="11111111-2222-3333-4444-000000000002", tmux=f"{SEC}:@1.%1",
                       window_name="extractor", index="1", records=[])  # 同じ作業の場所
        self.assertEqual(self.keys(), [f"tmux:{SEC}:extractor", f"tmux:{SEC}:secretariat"])

    def test_outside_tmux_uses_the_work_place(self):
        self.f.session(tmux=None, records=[])
        self.assertEqual(self.keys(), [f"cwd:{self.f.work}"])

    def test_pid_and_session_id_are_not_in_the_key(self):
        self.f.session(pid=4321, tmux=f"{DEPT}:@3.%3", window_name="dev", records=[])
        (key,) = self.keys()
        self.assertNotIn("4321", key)
        self.assertNotIn(SID, key)

    def test_codex_only_card_has_its_own_key(self):
        d = f"{self.f.codex}/sessions/2026/10/28"
        os.makedirs(d)
        with open(f"{d}/rollout-x.jsonl", "w") as fh:
            fh.write(json.dumps({"timestamp": iso(NOW), "type": "event_msg", "payload": {"type": "task_complete"}}) + "\n")
        pd = self.f.process(300, ppid=1, cwd=self.f.work,
                            argv0="/x/node_modules/@openai/codex/node_modules/@openai/codex-linux-x64/vendor/codex")
        os.symlink(f"{d}/rollout-x.jsonl", f"{pd}/fd/7")
        self.assertEqual(self.keys(), [f"codex:cwd:{self.f.work}"])


class FakeCard:
    def __init__(self, key, name, color="gray", auto="auto:other"):
        self.hide_key, self.name, self.place, self.color, self.auto_group = key, name, "p", color, auto


class PrefsStoreTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.st = os.path.join(self.d.name, "state")
        self.cards = {"tmux:a:#0": FakeCard("tmux:a:#0", "a")}

    def tearDown(self):
        self.d.cleanup()

    def change(self, cards=None, groups_now=("auto:other",), **req):
        return prefs.change(self.st, req, self.cards if cards is None else cards, set(groups_now))

    def test_hide_and_show_with_owner_only_files(self):
        self.assertEqual(len(self.change(action="hide", key="tmux:a:#0")["hidden"]), 1)
        self.assertEqual(len(self.change(action="hide", key="tmux:a:#0")["hidden"]), 1)  # 二度押しても 1
        self.assertEqual(os.stat(self.st).st_mode & 0o777, 0o700)
        self.assertEqual(os.stat(prefs.path(self.st)).st_mode & 0o777, 0o600)
        self.assertEqual(os.listdir(self.st), ["prefs.json"])  # 一時のファイルが残らない
        self.assertEqual(list(prefs.load(self.st)["hidden"]), ["tmux:a:#0"])
        self.assertEqual(self.change(cards={}, action="show", key="tmux:a:#0")["hidden"], {})  # 今動いていなくても戻せる

    def test_unknown_keys_and_groups_are_refused(self):
        for req in ({"action": "hide", "key": "tmux:zzz:#0"}, {"action": "show", "key": "tmux:a:#0"},
                    {"action": "move", "key": "tmux:a:#0", "group": "auto:company"},
                    {"action": "rename", "group": "user:9", "name": "x"}):
            with self.assertRaises(ValueError, msg=req):
                self.change(**req)
        self.assertFalse(os.path.exists(prefs.path(self.st)))

    def test_there_are_limits(self):
        many = {f"tmux:s{i}:#0": FakeCard(f"tmux:s{i}:#0", str(i)) for i in range(3)}
        with mock.patch.object(prefs, "MAX_HIDDEN", 2):
            self.change(cards=many, action="hide", key="tmux:s0:#0")
            self.change(cards=many, action="hide", key="tmux:s1:#0")
            with self.assertRaises(OverflowError):
                self.change(cards=many, action="hide", key="tmux:s2:#0")
        with mock.patch.object(prefs, "MAX_USER_GROUPS", 1):
            self.change(cards=many, action="move", key="tmux:s0:#0", group="new", name="一つ目")
            with self.assertRaises(OverflowError):
                self.change(cards=many, action="move", key="tmux:s1:#0", group="new", name="二つ目")

    def test_names_are_checked(self):
        for bad in ("", "   ", "x" * (prefs.MAX_NAME + 1), "改行\nあり", 3):
            with self.assertRaises(ValueError, msg=repr(bad)):
                self.change(action="rename", group="auto:other", name=bad)
        self.assertEqual(self.change(action="rename", group="auto:other", name="  前後の空白  ")["groups"]["auto:other"]["name"],
                         "前後の空白")

    def test_move_new_group_back_and_prune(self):
        p = self.change(action="move", key="tmux:a:#0", group="new", name="作業")
        self.assertEqual(p["assign"], {"tmux:a:#0": "user:1"})
        self.assertEqual(p["groups"]["user:1"]["name"], "作業")
        p = self.change(action="move", key="tmux:a:#0", group="auto:other")  # 自動の行き先に戻す
        self.assertEqual(p["assign"], {})
        self.assertNotIn("user:1", p["groups"])  # だれもいない、作ったグループは消える

    def test_broken_or_huge_file_is_not_overwritten(self):
        os.makedirs(self.st)
        with open(prefs.path(self.st), "w") as fh:
            fh.write("{broken")
        with self.assertRaises(prefs.PrefsError):
            self.change(action="hide", key="tmux:a:#0")
        with open(prefs.path(self.st)) as fh:
            self.assertEqual(fh.read(), "{broken")
        with open(prefs.path(self.st), "w") as fh:
            fh.write('{"hidden": {}, "pad": "' + "x" * prefs.MAX_FILE + '"}')
        with self.assertRaises(prefs.PrefsError):
            prefs.load(self.st)


class WriteEndpointTests(unittest.TestCase):
    """POST /prefs の守り（このページからの要求だけ）と、隠す・戻す・グループ・起こし直し"""

    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.state = os.path.join(self.d.name, "state")
        self.cards = []
        for key, name, color in (("tmux:aipair-a-0123456789ab:#0", "alpha", "yellow"), (DEV_KEY, "beta", "gray")):
            c = bc.Card(key="claude-" + name, name=name, place="p", path="", notice_driven=False, status="idle",
                        last_ms=NOW, hide_key=key)
            c.color, c.label = color, "l"
            self.cards.append(c)
        self.start()

    def start(self):
        self.srv = server.make_server(0, lambda: (self.cards, [], NOW), state_dir=self.state)
        self.port = self.srv.server_address[1]
        self.srv.allowed_hosts = {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def stop(self):
        self.srv.shutdown()
        self.srv.server_close()

    def tearDown(self):
        self.stop()
        self.d.cleanup()

    def post(self, body=None, headers=None, path="/prefs", method="POST"):
        h = {"Host": f"127.0.0.1:{self.port}", "Origin": f"http://127.0.0.1:{self.port}",
             "Content-Type": "application/json", "X-Session-Board": "1"}
        h.update(headers or {})
        h = {k: v for k, v in h.items() if v is not None}
        data = body if isinstance(body, bytes) else json.dumps(body if body is not None else
                                                               {"action": "hide", "key": "tmux:aipair-a-0123456789ab:#0"}).encode()
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        for k, v in h.items():
            conn.putheader(k, v)
        if "Content-Length" not in h:
            conn.putheader("Content-Length", str(len(data)))
        conn.endheaders()
        conn.send(data)
        r = conn.getresponse()
        out = r.read()
        conn.close()
        return r, out

    def page(self, path="/"):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", path, headers={"Host": f"localhost:{self.port}"})
        r = conn.getresponse()
        body = r.read().decode()
        conn.close()
        return body

    def hidden_now(self):
        return prefs.load(self.state)["hidden"]

    def test_hide_show_and_it_survives_a_restart(self):
        r, body = self.post()
        self.assertEqual((r.status, json.loads(body)), (200, {"hidden": 1}))
        html = self.page()
        self.assertIn("隠している 1（うち黄 1）", html)
        self.assertNotIn('data-act="hide" data-key="tmux:aipair-a-0123456789ab:#0"', html)
        self.assertIn('data-act="show" data-key="tmux:aipair-a-0123456789ab:#0"', html)
        self.stop()
        self.start()  # 画面のプロセスを起こし直しても残る
        self.assertIn("隠している 1", self.page())
        self.cards = self.cards[1:]  # 隠した物が今は動いていなくても、一覧に出て消せる
        self.srv.board.snap = None
        self.assertIn("今は動いていない", self.page())
        r, _ = self.post({"action": "show", "key": "tmux:aipair-a-0123456789ab:#0"}, headers={"Origin": f"http://localhost:{self.port}", "Host": f"localhost:{self.port}"})
        self.assertEqual(r.status, 200)
        self.assertIn("隠している 0", self.page())
        self.assertEqual(self.hidden_now(), {})

    def test_requests_not_from_this_page_are_refused(self):
        cases = {
            "Origin が無い": ({"Origin": None}, 403),
            "よその Origin": ({"Origin": "http://evil.example"}, 403),
            "番号の違う Origin": ({"Origin": f"http://127.0.0.1:{self.port + 1}"}, 403),
            "null の Origin": ({"Origin": "null"}, 403),
            "https の Origin": ({"Origin": f"https://127.0.0.1:{self.port}"}, 403),
            "フォームの形（text/plain）": ({"Content-Type": "text/plain"}, 415),
            "フォームの形（urlencoded）": ({"Content-Type": "application/x-www-form-urlencoded"}, 415),
            "フォームの形（multipart）": ({"Content-Type": "multipart/form-data; boundary=x"}, 415),
            "見出しが無い": ({"X-Session-Board": None}, 403),
            "見出しの値が違う": ({"X-Session-Board": "0"}, 403),
            "よその Host": ({"Host": "evil.example"}, 421),
        }
        for why, (h, code) in cases.items():
            r, _ = self.post(headers=h)
            self.assertEqual(r.status, code, why)
            self.assertIsNone(r.getheader("Access-Control-Allow-Origin"), why)
        self.assertEqual(self.hidden_now(), {})

    def test_bad_bodies_are_refused(self):
        cases = {
            "知らない印": ({"action": "hide", "key": "tmux:nobody:#0"}, 400),
            "隠していない物を戻す": ({"action": "show", "key": DEV_KEY}, 400),
            "知らない操作": ({"action": "delete", "key": DEV_KEY}, 400),
            "余分な項目": ({"action": "hide", "key": DEV_KEY, "path": "/etc/passwd"}, 400),
            "印の形が違う": ({"action": "hide", "key": "../../etc/passwd"}, 400),
            "印に制御文字": ({"action": "hide", "key": "tmux:a\n:#0"}, 400),
            "JSON でない": (b"{not json", 400),
            "大きすぎる": (json.dumps({"action": "hide", "key": "tmux:" + "x" * 2000}).encode(), 413),
        }
        for why, (body, code) in cases.items():
            r, _ = self.post(body)
            self.assertEqual(r.status, code, why)
        r, _ = self.post(headers={"Content-Length": "abc"})
        self.assertEqual(r.status, 411)
        self.assertEqual(self.hidden_now(), {})

    def test_get_and_other_methods_cannot_write(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", f"/prefs?action=hide&key={DEV_KEY}", headers={"Host": f"127.0.0.1:{self.port}"})
        self.assertEqual(conn.getresponse().status, 404)
        conn.close()
        for method in ("PUT", "DELETE", "PATCH", "OPTIONS"):
            r, _ = self.post(method=method)
            self.assertEqual(r.status, 405, method)
            self.assertIsNone(r.getheader("Access-Control-Allow-Origin"), method)
        for path in ("/", "/cards", "/hidden", "/prefs?x=1", "/prefs/../x"):
            r, _ = self.post(path=path)
            self.assertEqual(r.status, 405, path)
        self.assertEqual(self.hidden_now(), {})

    def test_refusals_are_logged_without_the_body(self):
        marker = "ひみつの中身"
        self.post({"action": "hide", "key": "tmux:" + marker}, headers={"Origin": "http://evil.example"})
        with open(os.path.join(server.STATE_DIR, "board.log"), encoding="utf-8") as fh:
            log = fh.read()
        self.assertIn("origin='http://evil.example'", log)
        self.assertNotIn(marker, log)

    def test_broken_hidden_file_shows_everything_and_refuses_writes(self):
        os.makedirs(self.state, exist_ok=True)
        with open(prefs.path(self.state), "w") as fh:
            fh.write("{broken")
        html = self.page()
        self.assertIn("画面の設定のファイルを読めない", html)
        self.assertIn("alpha", html)
        self.assertIn("beta", html)
        r, _ = self.post()
        self.assertEqual(r.status, 500)
        with open(prefs.path(self.state)) as fh:
            self.assertEqual(fh.read(), "{broken")

    def test_keys_are_escaped_in_the_page(self):
        self.cards[0].hide_key = 'tmux:a"><script>x</script>:#0'
        self.srv.board.snap = None
        html = self.page()
        self.assertNotIn("<script>x", html)
        self.assertIn("&quot;&gt;&lt;script&gt;", html)


def mk(name, cwd, session=None, color="gray", key=None):
    c = bc.Card(key="claude-" + name, name=name, place="p", path="", notice_driven=False, status="idle",
                last_ms=NOW, hide_key=key or f"tmux:{name}:#0", cwd=cwd, tmux_session=session)
    c.color, c.label = color, "l"
    return c


CO = groups.COMPANY_ROOT
DEV = groups.DEV_ROOT


class AutoGroupTests(unittest.TestCase):
    def test_automatic_groups_by_work_place(self):
        cases = [
            (mk("legal", f"{CO}/legal", DEPT), "auto:company"),
            (mk("extractor", CO, SEC), "auto:company"),  # 会社のフォルダーそのもの
            (mk("demo", f"{CO}/development/projects/demo-project", "aipair-demo-0123456789ab"), "auto:projects:development/projects"),
            (mk("nested", f"{DEV}/Example/nested/demo-app", "aipair-nested-0123456789ab"), "auto:projects:Example"),
            (mk("tools", f"{DEV}/ExampleTools", "aipair-tools-0123456789ab"), "auto:projects:ExampleTools"),
            (mk("plain", f"{DEV}/Example/x", None), "auto:other"),  # tmux の外・aipair でない
            (mk("deep", f"{CO}/development/projects/x", "work"), "auto:other"),  # 会社の中でも、部署の場所でない
            (mk("home", "/home/u/x", "aipair-h-0123456789ab"), "auto:projects:そのほか"),
        ]
        for card, gid in cases:
            self.assertEqual(groups.auto_group(card), gid, card.name)

    def test_order_names_and_default_fold(self):
        laid = groups.layout([mk("legal", f"{CO}/legal", DEPT), mk("plain", "/x"),
                              mk("cp", f"{DEV}/A/cp", "aipair-cp-0123456789ab")], prefs.empty())
        self.assertEqual([(g.id, g.name, g.open) for g in laid],
                         [("auto:projects:A", "案件 · A", True), ("auto:company", "会社", False), ("auto:other", "そのほか", True)])

    def test_hidden_cards_are_not_in_heading_counts(self):
        cards = [mk("a", f"{CO}/a", DEPT, "yellow", f"tmux:{DEPT}:a"),
                 mk("b", f"{CO}/b", DEPT, "gray", f"tmux:{DEPT}:b")]
        p = prefs.empty()
        p["hidden"][f"tmux:{DEPT}:a"] = {"name": "a", "place": "p", "at": ""}
        (g,) = groups.layout(cards, p)
        self.assertEqual(([c.name for c in g.cards], [c.name for c in g.hidden]), (["b"], ["a"]))
        html = render.group_html(g, NOW, [(g.id, g.name)])
        self.assertIn('count small gray">灰 1</span>', html)
        self.assertIn("隠している 1・うち黄 1", html)
        self.assertNotIn("has-yellow", html)  # 隠した黄では、見出しを黄にしない（上の「隠している」に出る）


class GroupEndpointTests(WriteEndpointTests):
    """画面での移す・名前・畳む。WriteEndpointTests の作りを使う"""

    def setUp(self):
        super().setUp()
        self.cards[0].cwd, self.cards[0].tmux_session = f"{DEV}/A/alpha", "aipair-a-0123456789ab"
        self.cards[1].cwd, self.cards[1].tmux_session = f"{CO}/development", DEPT

    def test_groups_show_with_counts_and_yellow_heading(self):
        html = self.page()
        self.assertIn('data-group="auto:projects:A"', html)
        self.assertIn('data-group="auto:company"', html)
        self.assertRegex(html, r'<details class="group has-yellow" data-group="auto:projects:A" data-open="1" open>')
        self.assertRegex(html, r'<details class="group has-gray" data-group="auto:company" data-open="0">')  # 会社は畳んで始まる
        self.assertIn("黄 1", html)

    def test_move_rename_fold_survive_a_restart(self):
        r, _ = self.post({"action": "move", "key": DEV_KEY, "group": "new", "name": "<script>alert(1)</script>"})
        self.assertEqual(r.status, 200)
        r, _ = self.post({"action": "rename", "group": "auto:projects:A", "name": "わたしの案件"})
        self.assertEqual(r.status, 200)
        r, _ = self.post({"action": "fold", "group": "auto:projects:A", "open": False})
        self.assertEqual(r.status, 200)
        self.stop()
        self.start()  # 画面のプロセスを起こし直しても残る
        html = self.page()
        self.assertNotIn("<script>alert", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)  # 打った文字のまま出る
        self.assertIn("わたしの案件", html)
        self.assertRegex(html, r'data-group="auto:projects:A" data-open="0">')
        self.assertNotIn('data-group="auto:company"', html)  # 1 枚を移したので、会社のグループは空になって出ない
        self.assertRegex(html, r'data-group="user:1" data-open="1" open>')

    def test_bad_group_requests_are_refused(self):
        cases = {
            "知らないグループへ移す": ({"action": "move", "key": DEV_KEY, "group": "user:5"}, 400),
            "グループの形が違う": ({"action": "move", "key": DEV_KEY, "group": "../x"}, 400),
            "新しいのに名前が無い": ({"action": "move", "key": DEV_KEY, "group": "new"}, 400),
            "新しくないのに名前": ({"action": "move", "key": DEV_KEY, "group": "auto:company", "name": "x"}, 400),
            "名前が長すぎる": ({"action": "rename", "group": "auto:company", "name": "あ" * 41}, 400),
            "名前に改行": ({"action": "rename", "group": "auto:company", "name": "a\nb"}, 400),
            "名前が空": ({"action": "rename", "group": "auto:company", "name": "  "}, 400),
            "名前が文字でない": ({"action": "rename", "group": "auto:company", "name": ["x"]}, 400),
            "畳むの値が真偽でない": ({"action": "fold", "group": "auto:company", "open": "no"}, 400),
            "知らないグループの名前": ({"action": "rename", "group": "user:3", "name": "x"}, 400),
        }
        for why, (body, code) in cases.items():
            r, _ = self.post(body)
            self.assertEqual(r.status, code, why)
        self.assertEqual(prefs.load(self.state), prefs.empty())

    def test_refused_without_origin_even_for_group_changes(self):
        r, _ = self.post({"action": "rename", "group": "auto:company", "name": "x"}, headers={"Origin": None})
        self.assertEqual(r.status, 403)
        self.assertEqual(prefs.load(self.state), prefs.empty())


class ControlsTests(unittest.TestCase):
    """部品の形: 数の丸で絞り込む・見出しの鉛筆・カードの ⋯ のメニュー"""

    def setUp(self):
        self.cards = [mk("a", f"{DEV}/A/a", "aipair-a-0123456789ab", "yellow"), mk("b", f"{DEV}/A/b", "aipair-b-0123456789ab", "gray"),
                      mk("c", f"{CO}/legal", DEPT, "blue", f"tmux:{DEPT}:legal")]
        self.laid = groups.layout(self.cards, prefs.empty())
        self.html = render.page_html(render.board_html(self.laid, [], NOW))

    def test_count_chips_are_the_filter(self):
        for c in ("yellow", "blue", "gray"):
            self.assertIn(f'class="count {c}" data-filter="{c}" aria-pressed="false" title="', self.html)
        self.assertNotIn('data-filter="unreadable"', self.html)  # 0 の「読めない」は出さない
        self.assertNotIn('type="checkbox"', self.html)

    def test_group_heading_has_separate_chips_and_a_pencil_with_a_label(self):
        self.assertIn('<span class="gname">案件 · A</span><button class="icon edit"', self.html)
        self.assertIn('title="グループの名前を変える" aria-label="グループの名前を変える">✎</button>', self.html)
        self.assertIn('<span class="count small yellow">黄 1</span><span class="count small gray">灰 1</span>', self.html)
        self.assertIn('class="group has-yellow has-gray"', self.html)
        self.assertIn('class="group has-blue"', self.html)

    def test_card_menu(self):
        card = render.card_html(self.cards[0], NOW, "auto:projects:A", [(g.id, g.name) for g in self.laid])
        self.assertIn('aria-haspopup="menu" aria-expanded="false" title="このカードの操作', card)
        self.assertIn('<div class="menu" role="menu" hidden>', card)
        self.assertIn('data-act="move" data-key="tmux:a:#0" data-group="auto:company">会社</button>', card)
        self.assertNotIn('data-group="auto:projects:A">', card)  # 今いるグループへは移せない
        self.assertIn('data-group="new">＋ 新しいグループ…', card)
        self.assertIn('role="menuitem" data-act="hide" data-key="tmux:a:#0">表示しない', card)
        self.assertLess(card.index("menu-wrap"), card.index("</header>"))  # 右上（見出しの行）にある
        self.assertNotIn("<select", card)

    def test_dark_controls_and_version(self):
        self.assertIn("color-scheme:light dark", render.CSS)
        self.assertIn(f'<meta name="board-version" content="{render.VERSION}">', self.html)


class StoppedTests(unittest.TestCase):
    """止めてある Claude Code（Ctrl-Z 等）を見分ける。同じ窓に 2 つ・同じ会話の ID"""

    def setUp(self):
        self.f = Fake()

    def tearDown(self):
        self.f.tmp.cleanup()

    def two_in_one_window(self, state="T", same_conversation=True):
        f = self.f
        f.session(pid=405, tmux=f"{SEC}:@0.%0", window_name="secretariat", status="waiting", waitingFor="permission prompt",
                  records=[human("前の依頼", NOW - 3 * MIN)])
        f.process(405, state=state)  # 止めてある前のセッション
        sid2 = SID if same_conversation else "11111111-2222-3333-4444-999999999999"
        f.session(pid=900, sid=sid2, tmux=f"{SEC}:@0.%0", window_name="secretariat", status="idle",
                  statusUpdatedAt=NOW - 4 * 60 * MIN, records=[human("今の依頼", NOW - 4 * 60 * MIN)])
        f.session(pid=901, sid="11111111-2222-3333-4444-000000000901", tmux=f"{SEC}:@1.%1", window_name="extractor",
                  index="1", status="idle", statusUpdatedAt=NOW - MIN, records=[])
        return bc.collect(f.env())[0]

    def test_stopped_is_paused_gray_last_and_has_its_own_key(self):
        cards = self.two_in_one_window()
        names = [c.name for c in cards]
        self.assertEqual(names, ["秘書室", "秘書室 · 抜き出しの係", "秘書室（一時停止中）"])  # 抜き出しの係は本体の後ろ、止めてある物は最後
        main, extractor, paused = cards
        self.assertEqual((paused.color, paused.label), ("gray", "一時停止中"))  # 記録では許可の問いでも、黄にしない
        self.assertEqual(extractor.color, "gray")
        self.assertNotEqual(paused.hide_key, main.hide_key)  # 一緒に隠れない
        self.assertTrue(paused.hide_key.startswith(main.hide_key + ":stopped:405-"))
        self.assertEqual(paused.warn, "動いているセッションと同じ会話。続けると記録が混ざる")
        self.assertEqual(main.warn, "")
        self.assertIn("注意", render.card_html(paused, NOW))

    def test_traced_state_is_also_paused(self):
        cards = self.two_in_one_window(state="t")
        self.assertEqual(cards[-1].label, "一時停止中")

    def test_no_warning_without_a_running_twin(self):
        cards = self.two_in_one_window(same_conversation=False)
        self.assertEqual(cards[-1].warn, "")

    def test_codex_goes_to_the_running_card(self):
        f = self.f
        f.session(pid=405, tmux="aipair-demo-0123456789ab:@1.%1", records=[])
        f.process(405, state="T")
        f.session(pid=900, sid="11111111-2222-3333-4444-999999999999", tmux="aipair-demo-0123456789ab:@1.%1", records=[])
        f.process(200)
        f.panes.append("%2\t200\taipair-demo-0123456789ab\t@1\tclaude\t0\t1")
        d = f"{f.codex}/sessions/2026/10/28"
        os.makedirs(d)
        with open(f"{d}/rollout-x.jsonl", "w") as fh:
            fh.write(json.dumps({"timestamp": iso(NOW), "type": "event_msg", "payload": {"type": "task_started"}}) + "\n")
        pd = f.process(202, ppid=200, argv0="/x/node_modules/@openai/codex/node_modules/@openai/codex-linux-x64/vendor/codex")
        os.symlink(f"{d}/rollout-x.jsonl", f"{pd}/fd/7")
        running, paused = bc.collect(f.env())[0]
        self.assertFalse(running.stopped)
        self.assertIsNotNone(running.codex)
        self.assertIsNone(paused.codex)


class GroupOrderTests(unittest.TestCase):
    """黄のあるグループが上（黄の件数の多い順）→ 青のあるグループ → 残り。同じ段の中は決まった並び"""

    def order(self, spec, hidden=()):
        """spec: {フォルダー: [色, ...]}。フォルダーごとに aipair の案件のグループになる。"会社" は会社のグループ"""
        cards = []
        for folder, colors in spec.items():
            for i, color in enumerate(colors):
                if folder == "会社":
                    c = mk(f"co{i}", f"{CO}/d{i}", DEPT, color, f"tmux:{DEPT}:d{i}")
                else:
                    c = mk(f"{folder}{i}", f"{DEV}/{folder}/p{i}", f"aipair-{folder}{i}-0123456789ab", color,
                           f"tmux:{folder}{i}:#0")
                cards.append(c)
        p = prefs.empty()
        for k in hidden:
            p["hidden"][k] = {"name": "", "place": "", "at": ""}
        return [g.name.replace("案件 · ", "") for g in groups.layout(cards, p)]

    def test_yellow_only_goes_on_top(self):
        self.assertEqual(self.order({"A": ["gray"], "B": ["yellow"]}), ["B", "A"])

    def test_yellow_with_blue_is_in_the_yellow_tier(self):
        self.assertEqual(self.order({"A": ["blue", "blue"], "B": ["yellow", "blue"]}), ["B", "A"])

    def test_blue_only_is_above_gray_only(self):
        self.assertEqual(self.order({"A": ["gray"], "B": ["blue"]}), ["B", "A"])

    def test_gray_only_keeps_the_old_order(self):
        self.assertEqual(self.order({"会社": ["gray"], "B": ["gray"], "A": ["gray"]}), ["A", "B", "会社"])

    def test_more_yellow_first(self):
        self.assertEqual(self.order({"A": ["yellow"], "B": ["yellow", "yellow"], "会社": ["yellow", "yellow", "yellow"]}),
                         ["会社", "B", "A"])

    def test_same_yellow_count_keeps_the_old_order(self):
        self.assertEqual(self.order({"会社": ["yellow"], "B": ["yellow"], "A": ["yellow", "gray"]}), ["A", "B", "会社"])

    def test_standby_only_group_is_in_the_last_tier(self):
        self.assertEqual(self.order({"A": ["gray"], "B": ["standby", "standby"], "C": ["blue"]}), ["C", "A", "B"])

    def test_yellow_and_standby_group_is_in_the_top_tier(self):
        self.assertEqual(self.order({"A": ["blue"], "B": ["standby", "yellow"]}), ["B", "A"])

    def test_hidden_yellow_is_not_counted(self):
        self.assertEqual(self.order({"A": ["gray"], "B": ["yellow", "gray"]}, hidden=["tmux:B0:#0"]), ["A", "B"])

    def test_paused_counts_as_gray(self):
        f = Fake()
        try:
            f.session(pid=405, tmux="aipair-zz-0123456789ab:@1.%1", status="waiting", waitingFor="permission prompt",
                      records=[])
            f.process(405, state="T")
            f.session(pid=406, sid="11111111-2222-3333-4444-000000000406", tmux="aipair-aa-0123456789ab:@2.%2",
                      status="idle", statusUpdatedAt=NOW - 5 * 60 * MIN, records=[])
            laid = groups.layout(bc.collect(f.env())[0], prefs.empty())
            (g,) = laid  # 2 つとも同じ案件のグループ
            self.assertEqual((g.counts()["yellow"], g.counts()["gray"]), (0, 2))  # 止めてある許可の問いを黄に数えない
        finally:
            f.tmp.cleanup()


def auto_prompt(text, ms):
    """自動のターンの頼み（origin が無い。道具が送った知らせ 等）"""
    return {"type": "user", "timestamp": iso(ms), "message": {"role": "user", "content": text}}


class SecretariatQuestionTests(unittest.TestCase):
    """秘書室の本体（社長と話す所）は、社長の最後の頼みへの最後の返事が問いかけで終わった時だけ黄（作り物の返事で確かめる）"""

    def setUp(self):
        self.f = Fake()

    def tearDown(self):
        self.f.tmp.cleanup()

    def card(self, records, status="idle", window="secretariat", tmux=f"{SEC}:@0.%0", **kw):
        self.f.session(tmux=tmux, window_name=window, status=status, records=records,
                       statusUpdatedAt=kw.pop("updated", NOW - MIN), **kw)
        return bc.collect(self.f.env())[0][0]

    def test_question_is_yellow(self):
        c = self.card([human("明日の予定は？", NOW - 5 * MIN), reply("A と B があります。\n\nどちらにしますか？", NOW - 4 * MIN)])
        self.assertEqual((c.color, c.label), ("yellow", "社長への問いかけ（社長の番）"))

    def test_plain_report_is_not_yellow(self):
        c = self.card([human("今日の分をまとめて", NOW - 5 * MIN), reply("まとめて、控えに書きました。", NOW - 4 * MIN)])
        self.assertEqual((c.color, c.label), ("standby", "待機（やることを終えた）"))

    def test_reply_to_an_automatic_turn_is_skipped(self):
        c = self.card([human("始めて", NOW - 9 * MIN), reply("始めました。", NOW - 8 * MIN),
                       auto_prompt("作業の知らせ 1", NOW - 2 * MIN), reply("知らせを片付けた。次はどれにしますか？", NOW - MIN)])
        self.assertEqual(c.color, "standby")  # 自動のターンへの返事の問いかけでは黄にしない

    def test_question_survives_a_later_automatic_turn(self):
        c = self.card([human("どうしよう", NOW - 9 * MIN), reply("案を 2 つ出しました。どちらがよいですか。", NOW - 8 * MIN),
                       auto_prompt("作業の知らせ 2", NOW - 2 * MIN), reply("報告を読みました。", NOW - 90_000),
                       reply("知らせを片付けた 2", NOW - MIN)])
        self.assertEqual((c.color, c.label), ("yellow", "社長への問いかけ（社長の番）"))

    def test_task_notification_turn_is_also_skipped(self):
        c = self.card([human("どうしよう", NOW - 9 * MIN), reply("進めてよいでしょうか", NOW - 8 * MIN),
                       {"type": "user", "origin": {"kind": "task-notification"}, "timestamp": iso(NOW - 2 * MIN),
                        "message": {"content": "<task-notification>done</task-notification>"}},
                       reply("裏の作業が終わりました。", NOW - MIN)])
        self.assertEqual(c.color, "yellow")

    def test_answered_and_working_is_blue(self):
        c = self.card([human("どうしよう", NOW - 9 * MIN), reply("どちらにしますか？", NOW - 8 * MIN),
                       human("A で", NOW - 2 * MIN)], status="busy")
        self.assertEqual(c.color, "blue")

    def test_waiting_is_yellow(self):
        c = self.card([human("消して", NOW - 2 * MIN)], status="waiting", waitingFor="permission prompt")
        self.assertEqual((c.color, c.label), ("yellow", "許可の問い"))

    def test_extractor_is_never_yellow(self):
        c = self.card([human("抜き出して", NOW - 5 * MIN), reply("どれを抜き出しますか？", NOW - 4 * MIN)],
                      window="extractor", tmux=f"{SEC}:@1.%1", index="1")
        self.assertEqual(c.color, "gray")

    def test_no_time_limit_for_a_question(self):
        c = self.card([human("決めて", NOW - 3 * 1440 * MIN), reply("どちらにしますか？", NOW - 3 * 1440 * MIN)],
                      updated=NOW - 3 * 1440 * MIN)
        self.assertEqual(c.color, "yellow")  # 答えるまで社長の番

    def test_aipair_finished_without_question_is_standby(self):
        c = self.card([human("直して", NOW - 5 * MIN), reply("直しました。", NOW - 4 * MIN)],
                      window="claude", tmux="aipair-demo-0123456789ab:@1.%1")
        self.assertEqual((c.color, c.label), ("standby", "待機（やることを終えた）"))

    def test_aipair_question_is_yellow_even_after_two_hours(self):
        c = self.card([human("直して", NOW - 5 * 60 * MIN), reply("直す前に、A と B のどちらにしますか？", NOW - 5 * 60 * MIN)],
                      window="claude", tmux="aipair-demo-0123456789ab:@1.%1", updated=NOW - 5 * 60 * MIN)
        self.assertEqual((c.color, c.label), ("yellow", "社長への問いかけ（社長の番）"))

    def test_standby_turns_gray_after_two_hours(self):
        c = self.card([human("直して", NOW - 3 * 60 * MIN), reply("直しました。", NOW - 3 * 60 * MIN)],
                      window="claude", tmux="aipair-demo-0123456789ab:@1.%1", updated=NOW - 3 * 60 * MIN)
        self.assertEqual((c.color, c.label), ("gray", "しばらく動いていない"))

    def test_department_never_turns_standby(self):
        c = self.card([human("知らせ", NOW - 5 * MIN), reply("片付けました。", NOW - 4 * MIN)],
                      window="dev", tmux=f"{DEPT}:@3.%3", index="3")
        self.assertEqual((c.color, c.label), ("gray", "手が空いている（次の知らせ待ち）"))

    def test_question_endings(self):
        yes = ["どちらにしますか？", "よいですか?", "進めてよいでしょうか。", "A と B のどちらにしますか。", "これで合っていますか",
               "**どちらにしますか？**", "- 進めてよいですか？", "選んでください。", "ご判断をお願いします。", "これでいいかな"]
        no = ["まとめました。", "控えに書きました。", "結果 1", "次は A をします。", "```\nx = y?\n```",
              "確認しました（問題なし）", ""]
        for t in yes:
            self.assertTrue(bc.is_question("前置き\n\n" + t), t)
        for t in no:
            self.assertFalse(bc.is_question("前置き\n\n" + t), t)


class FullTextTests(unittest.TestCase):
    """全文の道（GET /text）: 今のカードの印と prompt・reply だけ。見出しを求め、伏せ字と上限を当てる"""

    def setUp(self):
        self.big = "あ" * (server.MAX_TEXT // 3 + 5000)  # UTF-8 で 3 バイトの字。上限を超える
        c = bc.Card(key="claude-1", name="n", place="p", path="", notice_driven=False, status="idle", last_ms=NOW,
                    hide_key="tmux:demo:#0", prompt="頭", reply="頭")
        c.full_text = {"prompt": "1 行目\n2 行目 <script>alert(1)</script>\n鍵 sk-ant-" + "A" * 30, "reply": self.big}
        c2 = bc.Card(key="claude-2", name="m", place="p", path="", notice_driven=False, status="idle", last_ms=NOW,
                     hide_key="tmux:empty:#0")
        c2.full_text = {"prompt": "", "reply": None}
        # 同じ場所の tmux の外の 2 つめの会話: 隠す印は c と同じになるが、全文は別の物を返さなければならない
        c3 = bc.Card(key="claude-3", name="n", place="p", path="", notice_driven=False, status="idle", last_ms=NOW,
                     hide_key="tmux:demo:#0", prompt="頭", reply="頭")
        c3.full_text = {"prompt": "2 つめの会話の頼み", "reply": "2 つめの会話の返事"}
        for x in (c, c2, c3):
            bc.decide_color(x, NOW)
        self.srv = server.make_server(0, lambda: ([c, c2, c3], [], NOW))
        self.port = self.srv.server_address[1]
        self.srv.allowed_hosts = {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()

    def get(self, query, headers=None, method="GET"):
        h = {"Host": f"127.0.0.1:{self.port}", "X-Session-Board": "1", **(headers or {})}
        h = {k: v for k, v in h.items() if v is not None}
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request(method, "/text" + query, headers=h)
        r = conn.getresponse()
        body = r.read()
        conn.close()
        return r, body

    def test_prompt_is_masked_and_keeps_newlines_and_tags_as_text(self):
        r, body = self.get("?card=claude-1&kind=prompt")
        d = json.loads(body)
        self.assertEqual(r.status, 200)
        self.assertIn("1 行目\n2 行目 <script>alert(1)</script>", d["text"])  # 文字のまま返す（画面は textContent で出す）
        self.assertNotIn("AAAAAAAAAA", d["text"])
        self.assertEqual((d["masked"], d["omitted"]), (1, 0))
        self.assertIsNone(r.getheader("Access-Control-Allow-Origin"))

    def test_long_text_is_cut_with_the_omitted_count(self):
        r, body = self.get("?card=claude-1&kind=reply")
        d = json.loads(body)
        self.assertLessEqual(len(d["text"].encode()), server.MAX_TEXT)
        self.assertEqual(len(d["text"]) + d["omitted"], len(self.big))
        self.assertGreater(d["omitted"], 0)

    def test_two_conversations_with_the_same_hide_key_each_return_their_own_text(self):
        r1, b1 = self.get("?card=claude-1&kind=prompt")
        r3, b3 = self.get("?card=claude-3&kind=prompt")
        self.assertEqual((r1.status, r3.status), (200, 200))
        self.assertIn("1 行目", json.loads(b1)["text"])
        self.assertEqual(json.loads(b3)["text"], "2 つめの会話の頼み")

    def test_guards(self):
        cases = {
            "見出しが無い": ("?card=claude-1&kind=prompt", {"X-Session-Board": None}, 403),
            "見出しの値が違う": ("?card=claude-1&kind=prompt", {"X-Session-Board": "0"}, 403),
            "よその Host": ("?card=claude-1&kind=prompt", {"Host": "evil.example"}, 421),
            "知らないカード": ("?card=claude-999&kind=prompt", {}, 404),
            "場所の形": ("?card=..%2F..%2Fetc%2Fpasswd&kind=prompt", {}, 400),
            "隠す印で指す": ("?card=tmux%3Ademo%3A%230&kind=prompt", {}, 400),
            "前の項目の名前": ("?key=tmux%3Ademo%3A%230&kind=prompt", {}, 400),
            "違う kind": ("?card=claude-1&kind=transcript", {}, 400),
            "余分な項目": ("?card=claude-1&kind=prompt&path=%2Fetc%2Fpasswd", {}, 400),
            "カードが 2 つ": ("?card=claude-1&card=claude-2&kind=prompt", {}, 400),
            "カードが無い": ("?kind=prompt", {}, 400),
            "空": ("", {}, 400),
            "文が無い": ("?card=claude-2&kind=reply", {}, 404),
        }
        for why, (q, h, code) in cases.items():
            r, _ = self.get(q, h)
            self.assertEqual(r.status, code, why)
            self.assertIsNone(r.getheader("Access-Control-Allow-Origin"), why)
        r, _ = self.get("?card=claude-1&kind=prompt", method="POST")
        self.assertEqual(r.status, 405)

    def test_refusals_do_not_log_the_key(self):
        self.get("?card=claude-424242&kind=prompt", {"X-Session-Board": None})
        with open(os.path.join(server.STATE_DIR, "board.log"), encoding="utf-8") as fh:
            log = fh.read()
        self.assertIn("'/text'", log)
        self.assertNotIn("424242", log)


class DecisionSectionTests(unittest.TestCase):
    """社長に決めてほしいことを残した返事は黄（最後の見出しの節で見る。作り物の文で確かめる）"""

    def setUp(self):
        self.f = Fake()

    def tearDown(self):
        self.f.tmp.cleanup()

    def card(self, answer, extra=(), tmux="aipair-demo-0123456789ab:@1.%1", window="claude"):
        self.f.session(tmux=tmux, window_name=window, status="idle", statusUpdatedAt=NOW - MIN,
                       records=[human("頼む", NOW - 9 * MIN), reply(answer, NOW - 8 * MIN), *extra])
        return bc.collect(self.f.env())[0][0]

    DECIDE = ("決めてほしいことがある（社長の番）", "yellow")

    def check(self, answer, expected, **kw):
        c = self.card(answer, **kw)
        self.assertEqual((c.label, c.color), expected, answer[-60:])

    def test_undecided_heading_with_three_numbered_items(self):
        self.check("作りました。\n\n## 提案を 1 つ\n\nA を足すとよいです。\n\n## まだ決まっていないこと\n\n1. 色\n2. 名前\n3. 置き場", self.DECIDE)

    def test_proposal_section(self):
        self.check("作りました。\n\n## 提案\n\n画面の上に数を出すと、見やすくなります。", self.DECIDE)

    def test_table_of_things_to_decide(self):
        self.check("直しました。\n\n### 決めていただきたいこと\n\n| # | 決めること | 勧め |\n|---|---|---|\n| 1 | 色 | 緑 |", self.DECIDE)

    def test_no_heading_lead_line_and_numbered_list(self):
        self.check("直しました。\n\n決めてほしいこと:\n1. 色\n2. 名前", self.DECIDE)

    def test_list_only_block_after_a_lead_line(self):
        self.check("直しました。\n\n次の 2 つを選んでほしいです。\n\n1. 色\n2. 名前", self.DECIDE)

    def test_open_questions_in_english(self):
        self.check("Done.\n\n## Open questions\n\n- Which color?\n- Which name", self.DECIDE)

    def test_bold_line_heading(self):
        self.check("作りました。\n\n**まだ決まっていないこと**\n\n1. 色\n2. 名前", self.DECIDE)

    def test_question_keeps_its_own_label(self):
        self.check("作りました。どちらの色にしますか？", ("社長への問いかけ（社長の番）", "yellow"))

    def test_finished_report_is_standby(self):
        self.check("作りました。\n\n## 変えたこと\n\n- 色\n\n## 確かめ\n\n1. 試しが通った\n2. 画面で見た", ("待機（やることを終えた）", "standby"))

    def test_words_only_in_the_middle_stay_standby(self):
        self.check("作りました。\n\n## 決めてほしいこと\n\n- 無し（前に決めてもらった形のまま）\n\n## 確かめ\n\n試しが通った。",
                   ("待機（やることを終えた）", "standby"))

    def test_remaining_and_next_steps_stay_standby(self):
        self.check("作りました。\n\n## 残ること\n\n1. 写しを撮る\n\n## 次にすること\n\n1. 仕上げ", ("待機（やることを終えた）", "standby"))

    def test_decision_section_survives_a_later_automatic_turn(self):
        c = self.card("まとめました。\n\n## ご判断をお願いしたいこと\n\n1. A\n2. B",
                      extra=[auto_prompt("作業の知らせ 3", NOW - 2 * MIN), reply("知らせを片付けた 3", NOW - MIN)],
                      tmux=f"{SEC}:@0.%0", window="secretariat")
        self.assertEqual((c.label, c.color), self.DECIDE)

    def test_weak_spots(self):
        self.assertFalse(bc.has_decision_section("作りました。\n\n```bash\n# 質問: これは注記\necho ok\n```"))  # コードの中の # は見出しではない
        self.assertFalse(bc.has_decision_section("作りました。\n\n## 案件の残り\n\n無し"))  # 案件の「案」は当てない
        self.assertFalse(bc.has_decision_section("作りました。\n\n1. 色を変えた\n2. 名前を変えた"))  # 頭の行が無い一覧
        self.assertFalse(bc.has_decision_section(""))
        self.assertTrue(bc.has_decision_section("作りました。\n\n## 案 A と案 B\n\n比べました。"))


class StateDirTests(unittest.TestCase):
    def test_tests_never_write_to_the_real_state_dir(self):
        self.assertNotEqual(server.STATE_DIR, REAL_STATE)
        server.log("試しの行")
        self.assertTrue(os.path.exists(os.path.join(_state.name, "board.log")))


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


CTL = os.path.join(HERE, "tools", "board_ctl.sh")
OPEN = os.path.join(HERE, "tools", "open_board.sh")
BIN = os.path.join(HERE, "bin", "session-board")
STATE_TAIL = os.path.join(".local", "state", "brain-company", "session-board")


class CtlTests(unittest.TestCase):
    """tools/board_ctl.sh を、一時の HOME・一時の置き場・空いている番号で動かす（本物の置き場・既定の 18790 番には触れない）"""

    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.port = str(free_port())
        self.assertNotEqual(self.port, str(config.DEFAULT_PORT))
        # 起こす Python は、この試しと同じ物（3.9 でも 3.11 でも確かめられるように）
        self.env = {**os.environ, "HOME": self.home.name, "PYTHON": sys.executable}
        self.state = os.path.join(self.home.name, STATE_TAIL)  # 既定の置き場の規則（$HOME/.local/state/…）

    def tearDown(self):
        self.ctl("stop")  # 置き場が違っても、番号と命令の行で見つけて止める
        self.home.cleanup()

    def ctl(self, *args, env=None, port=True):
        return subprocess.run([CTL, *args, *([self.port] if port else [])],
                              env=env or self.env, capture_output=True, text=True, timeout=30)

    def read(self, *parts):
        with open(os.path.join(*parts), encoding="utf-8") as fh:
            return fh.read()

    def test_start_is_idempotent_and_stop_logs_a_line(self):
        r = self.ctl("start")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("起動した", r.stdout)
        r2 = self.ctl("start")
        self.assertIn("もう動いている", r2.stdout)
        self.assertEqual(self.ctl("status").returncode, 0)
        self.assertIn("止めた", self.ctl("stop").stdout)
        self.assertEqual(self.ctl("status").returncode, 3)
        log = self.read(self.state, "board.log")
        self.assertIn(f"start port={self.port}", log)
        self.assertIn(f"stop port={self.port}", log)  # SIGTERM でも止めた行が残る

    def test_state_files_are_owner_only(self):
        self.ctl("start")
        self.assertEqual(os.stat(self.state).st_mode & 0o777, 0o700)
        for name in os.listdir(self.state):
            self.assertEqual(os.stat(os.path.join(self.state, name)).st_mode & 0o077, 0, name)

    def test_busy_port_fails_fast(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", int(self.port)))
            s.listen()
            t = time.monotonic()
            r = self.ctl("start")
            took = time.monotonic() - t
        self.assertEqual(r.returncode, 1)
        self.assertIn("起動できなかった", r.stderr)
        self.assertLess(took, 5)  # 待ち切り（10 秒）まで待たない

    def test_finds_a_running_board_without_the_pid_file(self):
        self.ctl("start")
        os.remove(os.path.join(self.state, f"board-{self.port}.pid"))
        self.assertIn("もう動いている", self.ctl("start").stdout)
        self.assertIn("止めた", self.ctl("stop").stdout)

    def test_state_dir_and_port_follow_the_environment(self):
        xdg = os.path.join(self.home.name, "xdg")
        env = {**self.env, "XDG_STATE_HOME": xdg, "SESSION_BOARD_PORT": self.port}
        self.assertEqual(self.ctl("start", env=env, port=False).returncode, 0)  # 番号は SESSION_BOARD_PORT から
        st = os.path.join(xdg, "brain-company", "session-board")
        self.assertTrue(os.path.exists(os.path.join(st, f"board-{self.port}.pid")))
        self.assertIn(f"start port={self.port}", self.read(st, "board.log"))  # 画面の側（Python）も同じ置き場に書く
        self.assertIn("止めた", self.ctl("stop", env=env, port=False).stdout)
        own = os.path.join(self.home.name, "own-state")
        env = {**env, "SESSION_BOARD_STATE_DIR": own}  # XDG_STATE_HOME より先
        self.assertEqual(self.ctl("start", env=env, port=False).returncode, 0)
        self.assertTrue(os.path.exists(os.path.join(own, f"board-{self.port}.pid")))
        self.assertIn(f"start port={self.port}", self.read(own, "board.log"))
        self.assertIn("止めた", self.ctl("stop", env=env, port=False).stdout)
        self.assertFalse(os.path.exists(self.state))  # 既定の置き場には何も作っていない

    def test_a_board_from_another_place_is_left_alone(self):
        """同じ番号でも、別の置き場の bin/session-board で起こした物は、自分の物と見なさない（止めない）"""
        other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)",
                                  "/elsewhere/tools/session-board/bin/session-board", "serve", "--port", self.port])
        self.addCleanup(other.wait)
        self.addCleanup(other.kill)
        os.makedirs(self.state)
        with open(os.path.join(self.state, f"board-{self.port}.pid"), "w") as fh:
            fh.write(str(other.pid))  # 番号の控えがよその物を指していても
        r = self.ctl("status")
        self.assertEqual((r.returncode, r.stdout.strip()), (3, "動いていない"))
        self.assertEqual(self.ctl("stop").stdout.strip(), "動いていない")
        self.assertIsNone(other.poll())  # 止めていない

    def test_bad_ports_are_refused(self):
        for bad in ("abc", "0", "65536", "018790", "-1", "1 2"):
            r = subprocess.run([CTL, "status", bad], env=self.env, capture_output=True, text=True, timeout=10)
            self.assertEqual(r.returncode, 2, bad)
            self.assertIn("番号の形が違う", r.stderr, bad)


class BinTests(unittest.TestCase):
    """bin/session-board の入口: 版の確かめ・番号の環境変数・数だけの check"""

    def test_old_python_stops_with_a_clear_message(self):
        err = io.StringIO()
        with mock.patch.object(sys, "version_info", (3, 8, 18, "final", 0)), mock.patch.object(sys, "stderr", err), \
                self.assertRaises(SystemExit) as cm:
            runpy.run_path(BIN, run_name="__main__")
        self.assertEqual(cm.exception.code, 2)
        self.assertIn("Python 3.9 以上", err.getvalue())

    def run_bin(self, *args, **env):
        with tempfile.TemporaryDirectory() as home:
            e = {**os.environ, "HOME": home, "CLAUDE_CONFIG_DIR": os.path.join(home, "claude"),
                 "CODEX_HOME": os.path.join(home, "codex"), "SESSION_BOARD_STATE_DIR": os.path.join(home, "state"), **env}
            return subprocess.run([sys.executable, BIN, *args], env=e, capture_output=True, text=True, timeout=30)

    def test_bad_port_env_is_refused(self):
        r = self.run_bin("serve", SESSION_BOARD_PORT="abc")
        self.assertEqual(r.returncode, 2)
        self.assertIn("SESSION_BOARD_PORT", r.stderr)

    def test_check_prints_numbers_only(self):
        r = self.run_bin("check")
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertEqual(set(data), {"cards", "colors", "unreadable_fields", "codex", "notes"})
        self.assertEqual(data["cards"], 0)  # 空の CLAUDE_CONFIG_DIR・CODEX_HOME（作り物）を読んだ


class ConfigTests(unittest.TestCase):
    """設定の環境変数（board/config.py）。辞書を渡して確かめる"""

    def test_company_root_is_two_above_the_tool_or_the_env(self):
        self.assertEqual(config.company_root({}), os.path.realpath(os.path.join(HERE, "..", "..")))
        self.assertEqual(config.projects_root({}), os.path.dirname(config.company_root({})))
        with tempfile.TemporaryDirectory() as d:
            real = os.path.join(d, "acme")
            os.makedirs(real)
            os.symlink(real, os.path.join(d, "link"))
            self.assertEqual(config.company_root({"SESSION_BOARD_COMPANY_ROOT": os.path.join(d, "link")}),
                             os.path.realpath(real))  # たどった先で比べる（Claude Code の作業の場所と同じ形）
        self.assertEqual(config.company_root({"SESSION_BOARD_COMPANY_ROOT": ""}), config.company_root({}))

    def test_tmux_session_names(self):
        self.assertEqual((config.dept_session({}), config.secretary_session({})), ("brain-company", "brain-company-secretariat"))
        self.assertEqual((config.dept_session({"TMUX_SESSION": "acme"}), config.secretary_session({"TMUX_SESSION": "acme"})),
                         ("acme", "acme-secretariat"))
        self.assertEqual(config.dept_session({"TMUX_SESSION": ""}), "brain-company")

    def test_state_dir_rules(self):
        self.assertEqual(config.state_dir({"HOME": "/h"}), "/h/.local/state/brain-company/session-board")
        self.assertEqual(config.state_dir({"HOME": "/h", "XDG_STATE_HOME": "/x"}), "/x/brain-company/session-board")
        self.assertEqual(config.state_dir({"HOME": "/h", "XDG_STATE_HOME": "/x", "SESSION_BOARD_STATE_DIR": "/s"}), "/s")
        self.assertEqual(config.state_dir({"HOME": "/h", "XDG_STATE_HOME": "", "SESSION_BOARD_STATE_DIR": ""}),
                         "/h/.local/state/brain-company/session-board")  # 空は無いのと同じ（board_ctl.sh の :- と同じ）

    def test_port(self):
        self.assertEqual(config.port({}), 18790)
        self.assertEqual(config.port({"SESSION_BOARD_PORT": "18799"}), 18799)
        for bad in ("abc", "0", "65536", "018790", " 1", "-1", "1.5"):
            with self.assertRaises(ValueError, msg=bad):
                config.port({"SESSION_BOARD_PORT": bad})

    def test_claude_and_codex_homes(self):
        self.assertEqual(config.claude_home({}), os.path.expanduser("~/.claude"))
        self.assertEqual(config.codex_home({}), os.path.expanduser("~/.codex"))
        self.assertEqual(config.claude_home({"CLAUDE_CONFIG_DIR": "/c"}), "/c")
        self.assertEqual(config.codex_home({"CODEX_HOME": "/x"}), "/x")

    def test_modules_read_the_environment(self):
        """読み込む時に環境変数を読む（別のプロセスで確かめる）"""
        code = ("import json; from board import collect, groups, server; e = collect.Env(); "
                "print(json.dumps([collect.DEPT_SESSION, collect.SECRETARY_SESSION, collect.NOTICE_DRIVEN, "
                "groups.COMPANY_ROOT, groups.DEV_ROOT, server.STATE_DIR, e.claude_home, e.codex_home]))")
        with tempfile.TemporaryDirectory() as d:
            co = os.path.realpath(d) + "/acme"
            env = {**os.environ, "TMUX_SESSION": "acme", "SESSION_BOARD_COMPANY_ROOT": co,
                   "SESSION_BOARD_STATE_DIR": f"{d}/st", "CLAUDE_CONFIG_DIR": f"{d}/c", "CODEX_HOME": f"{d}/x"}
            r = subprocess.run([sys.executable, "-c", code], cwd=HERE, env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(json.loads(r.stdout), ["acme", "acme-secretariat", [["acme", None], ["acme-secretariat", "extractor"]],
                                                    co, os.path.realpath(d), f"{d}/st", f"{d}/c", f"{d}/x"])


class SessionNameTests(unittest.TestCase):
    """部署側・秘書のセッションは名前の完全一致で見分ける（部署側の名前は秘書の名前の頭と同じ）"""

    def test_exact_names(self):
        f = Fake()
        self.addCleanup(f.tmp.cleanup)
        f.session(pid=1, sid="11111111-2222-3333-4444-000000000001", tmux=f"{SEC}:@0.%0", window_name="secretariat", records=[])
        f.session(pid=2, sid="11111111-2222-3333-4444-000000000002", tmux=f"{SEC}:@1.%1", window_name="extractor",
                  index="1", records=[])
        f.session(pid=3, sid="11111111-2222-3333-4444-000000000003", tmux=f"{DEPT}:@2.%2", window_name="pm", records=[])
        f.session(pid=4, sid="11111111-2222-3333-4444-000000000004", tmux=f"{DEPT}-other:@3.%3", window_name="dev", records=[])
        cards = {c.place: c for c in bc.collect(f.env())[0]}
        got = {p: (c.name, c.notice_driven, c.color) for p, c in cards.items()}
        self.assertEqual(got, {
            f"{SEC}:secretariat": ("秘書室", False, "standby"),  # 秘書の本体は社長と話す所
            f"{SEC}:extractor": ("秘書室 · 抜き出しの係", True, "gray"),
            f"{DEPT}:pm": ("PM 部", True, "gray"),  # 部署側は全部の窓が知らせで動く
            f"{DEPT}-other:dev": ("work", False, "standby"),  # 名前の頭だけが同じ別のセッションは部署ではない
        })


class TimeZoneTests(unittest.TestCase):
    """時刻はその PC の時間帯で出す（試しでは時間帯を決めて確かめる）"""

    def tz(self, name):
        p = mock.patch.dict(os.environ, {"TZ": name})
        p.start()
        time.tzset()
        self.addCleanup(time.tzset)  # 後に足した物から戻す: 環境変数を戻してから、時間帯を読み直す
        self.addCleanup(p.stop)

    def test_times_follow_the_local_time_zone(self):
        for name, near, far, stamp in (("UTC", "07:30（30 分前）", "01/14 23:00（9 時間前）", "08:00:00"),
                                       ("Asia/Tokyo", "16:30（30 分前）", "08:00（9 時間前）", "17:00:00")):
            with self.subTest(name):
                self.tz(name)
                self.assertEqual(render._when(NOW - 30 * MIN, NOW), near)
                self.assertEqual(render._when(NOW - 9 * 60 * MIN, NOW), far)  # 日付をまたぐかは、その時間帯で決まる
                self.assertIn(f"{stamp} に集めた", render.board_html([], [], NOW))

    def test_hidden_time_has_the_local_offset(self):
        with tempfile.TemporaryDirectory() as d:
            for name, offset in (("UTC", "+00:00"), ("Asia/Tokyo", "+09:00")):
                self.tz(name)
                st = os.path.join(d, name.replace("/", "-"))
                saved = prefs.change(st, {"action": "hide", "key": "tmux:a:#0"}, {"tmux:a:#0": FakeCard("tmux:a:#0", "a")}, set())
                self.assertTrue(saved["hidden"]["tmux:a:#0"]["at"].endswith(offset), name)


class OpenBoardTests(unittest.TestCase):
    """tools/open_board.sh: 作り物の道具だけを置いた PATH で確かめる（本物のブラウザは開かない）"""

    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.bin = os.path.join(d.name, "bin")
        self.log = os.path.join(d.name, "calls")
        self.home = d.name
        os.makedirs(self.bin)

    def fake(self, name, code=0):
        path = os.path.join(self.bin, name)
        with open(path, "w") as fh:
            fh.write(f'#!/bin/sh\necho "{name} $*" >> "{self.log}"\nexit {code}\n')
        os.chmod(path, 0o755)
        return path

    def run_open(self, *args, **env):
        e = {"PATH": self.bin, "HOME": self.home, **env}
        return subprocess.run([BASH, OPEN, *args], env=e, capture_output=True, text=True, timeout=10)

    def calls(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log) as fh:
            return fh.read().splitlines()

    def test_browser_env_comes_first(self):
        self.fake("wslview")
        r = self.run_open("18799", BROWSER=self.fake("mybrowser"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls(), ["mybrowser http://127.0.0.1:18799/"])

    def test_port_from_env_and_wslview(self):
        self.fake("wslview")
        self.fake("xdg-open")
        r = self.run_open(SESSION_BOARD_PORT="18798")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls(), ["wslview http://127.0.0.1:18798/"])

    def test_missing_or_failing_browser_falls_through_to_xdg_open(self):
        self.fake("xdg-open")
        self.run_open("18799", BROWSER="no-such-browser")
        self.run_open("18799", BROWSER=self.fake("broken", code=3))
        self.assertEqual(self.calls(), ["xdg-open http://127.0.0.1:18799/", "broken http://127.0.0.1:18799/",
                                        "xdg-open http://127.0.0.1:18799/"])

    def test_explorer_on_wsl(self):
        self.fake("explorer.exe", code=1)  # explorer.exe は開けた時も 1 を返す
        self.fake("xdg-open")
        r = self.run_open("18799", WSL_DISTRO_NAME="Example")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls(), ["explorer.exe http://127.0.0.1:18799/"])

    def test_explorer_that_cannot_run_falls_through(self):
        self.fake("explorer.exe", code=126)
        self.fake("xdg-open")
        self.run_open("18799", WSL_DISTRO_NAME="Example")
        self.assertEqual(self.calls(), ["explorer.exe http://127.0.0.1:18799/", "xdg-open http://127.0.0.1:18799/"])

    def test_nothing_to_open_with_prints_the_url(self):
        self.fake("open")  # macOS でなければ open は使わない（Linux の open は別の命令のことがある）
        r = self.run_open("18799")
        self.assertEqual(r.returncode, 1)
        self.assertIn("http://127.0.0.1:18799/", r.stderr)
        self.assertEqual(self.calls(), [])

    def test_bad_port(self):
        r = self.run_open("80a")
        self.assertEqual(r.returncode, 2)
        self.assertEqual(self.calls(), [])


class DemoTests(unittest.TestCase):
    def test_demo_groups_follow_the_settings(self):
        """見本の場所は会社のルートから作るので、どの PC でも同じグループに分かれる"""
        from board.demo import demo_source
        cards, _, _ = demo_source()
        laid = groups.layout(cards, prefs.empty())
        self.assertEqual([g.name for g in laid], ["案件 · ExampleApps", "会社", "案件 · ExampleMedia", "案件 · ExampleTools"])
        company = next(g for g in laid if g.id == "auto:company")
        self.assertEqual({c.tmux_session for c in company.cards}, {DEPT, SEC})


class TmuxFailureTests(unittest.TestCase):
    def test_tmux_failure_is_a_note_and_cards_remain(self):
        f = Fake()
        try:
            f.session(records=[])

            def bad():
                raise bc.Unreadable("tmux の一覧を読めない")
            env = f.env()
            env.tmux = bad
            cards, notes = bc.collect(env)
            self.assertEqual(len(cards), 1)
            self.assertEqual(notes, ["tmux: tmux の一覧を読めない"])
        finally:
            f.tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
