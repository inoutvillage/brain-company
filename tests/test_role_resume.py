"""Unit tests for .claude/scripts/role_resume.py and claude-role.sh with a fake HOME (no real conversations are read).

Run from the repository root: python3 -m unittest discover -s tests
"""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), ".claude", "scripts")
sys.path.insert(0, SCRIPTS)
sys.dont_write_bytecode = True
import role_resume as rr  # noqa: E402


class Env(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="role-resume-")
        self.home = os.path.join(self.tmp, "home")
        self.cwd = os.path.join(self.tmp, "work", "product-management")
        for d in (self.home, self.cwd):
            os.makedirs(d)
        self.old = {k: os.environ.get(k) for k in ("HOME", "CLAUDE_ROLE_LOG")}
        os.environ["HOME"] = self.home
        os.environ.pop("CLAUDE_ROLE_LOG", None)
        self.clock = time.time() - 1000

    def tearDown(self):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp)

    def conv(self, entry="cli", cwd=None, body=None, sid=None):
        """Write a conversation log; each call is newer than the last."""
        sid = sid or str(uuid.uuid4())
        pdir = rr.project_dir(self.cwd)
        os.makedirs(pdir, exist_ok=True)
        path = os.path.join(pdir, sid + ".jsonl")
        if body is None:
            recs = [{"type": "queue-operation"},
                    {"type": "user", "cwd": cwd or self.cwd, "entrypoint": entry, "sessionId": sid},
                    {"type": "assistant", "cwd": cwd or self.cwd, "entrypoint": entry, "sessionId": sid}]
            body = "".join(json.dumps(r) + "\n" for r in recs)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(body)
        self.clock += 10
        os.utime(path, (self.clock, self.clock))
        return sid

    def make_live(self, sid, pid=None, proc_start=None, tmux="brain-company:@1.%1"):
        pid = pid or os.getpid()
        sdir = os.path.join(self.home, ".claude", "sessions")
        os.makedirs(sdir, exist_ok=True)
        rec = {"pid": pid, "sessionId": sid, "procStart": proc_start or rr.proc_start(pid), "tmux": tmux}
        with open(os.path.join(sdir, "%d.json" % pid), "w", encoding="utf-8") as fh:
            json.dump(rec, fh)


class ChooseTest(Env):
    def test_no_conversation_starts_new(self):
        self.assertEqual(rr.choose(self.cwd)[0], "new")

    def test_resumes_the_newest_interactive(self):
        self.conv()
        newest = self.conv()
        self.assertEqual(rr.choose(self.cwd)[:2], ("resume", newest))

    def test_skips_one_shot_conversations(self):
        interactive = self.conv()
        self.conv(entry="sdk-cli")
        self.conv(entry="sdk-py")
        self.assertEqual(rr.choose(self.cwd)[:2], ("resume", interactive))

    def test_only_one_shot_conversations_start_new(self):
        self.conv(entry="sdk-cli")
        self.assertEqual(rr.choose(self.cwd)[0], "new")

    @unittest.skipUnless(os.path.isdir("/proc"), "needs /proc")
    def test_newest_in_use_starts_new_and_names_the_tmux_session(self):
        self.conv()
        live = self.conv()
        self.make_live(live)
        pick = rr.choose(self.cwd)
        self.assertEqual(pick[0], "new")
        self.assertIn("tmux の brain-company", pick[1])

    @unittest.skipUnless(os.path.isdir("/proc"), "needs /proc")
    def test_in_use_outside_tmux(self):
        self.make_live(self.conv(), tmux=None)
        self.assertIn("tmux の外", rr.choose(self.cwd)[1])

    @unittest.skipUnless(os.path.isdir("/proc"), "needs /proc")
    def test_old_session_file_of_a_dead_or_reused_pid_is_not_live(self):
        sid = self.conv()
        self.make_live(sid, proc_start="1")          # pid reused by this test process, start time differs
        self.assertEqual(rr.choose(self.cwd)[:2], ("resume", sid))

    def test_without_proc_use_cannot_be_checked_so_starts_new(self):
        self.conv()
        real, rr.PROC = rr.PROC, os.path.join(self.tmp, "no-proc")
        try:
            pick = rr.choose(self.cwd)
        finally:
            rr.PROC = real
        self.assertEqual(pick[0], "new")
        self.assertIn("/proc が無い", pick[1])

    def test_without_proc_and_no_conversation_says_none_yet(self):
        real, rr.PROC = rr.PROC, os.path.join(self.tmp, "no-proc")
        try:
            self.assertEqual(rr.choose(self.cwd), ("new", "この dir の対話の会話がまだ無い"))
        finally:
            rr.PROC = real

    def test_unreadable_newest_starts_new(self):
        self.conv()
        self.conv(body="this is not json\n" * 5)
        pick = rr.choose(self.cwd)
        self.assertEqual(pick[0], "new")
        self.assertIn("読めない", pick[1])

    def test_broken_head_lines_still_resume(self):
        sid = str(uuid.uuid4())
        good = json.dumps({"type": "user", "cwd": self.cwd, "entrypoint": "cli", "sessionId": sid}) + "\n"
        self.conv(body="{broken\n" * 3 + good, sid=sid)
        self.assertEqual(rr.choose(self.cwd)[:2], ("resume", sid))

    def test_truncated_last_line_still_resumes(self):
        sid = str(uuid.uuid4())
        good = json.dumps({"type": "user", "cwd": self.cwd, "entrypoint": "cli", "sessionId": sid}) + "\n"
        self.conv(body=good + '{"type": "assistant", "cwd": "' + self.cwd[:5], sid=sid)
        self.assertEqual(rr.choose(self.cwd)[:2], ("resume", sid))

    def test_folder_name_collision_is_skipped(self):
        mine = self.conv()
        self.conv(cwd=self.cwd.replace("product-management", "product/management"))
        self.assertEqual(rr.choose(self.cwd)[:2], ("resume", mine))

    def test_non_uuid_files_are_ignored(self):
        sid = self.conv()
        with open(os.path.join(rr.project_dir(self.cwd), "notes.jsonl"), "w") as fh:
            fh.write("{}\n")
        self.assertEqual(rr.choose(self.cwd)[:2], ("resume", sid))


class CliTest(Env):
    def run_cli(self):
        return subprocess.run([sys.executable, os.path.join(SCRIPTS, "role_resume.py"), self.cwd],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True,
                              env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))

    def test_resume_line(self):
        sid = self.conv()
        p = self.run_cli()
        kind, got, _when = p.stdout.rstrip("\n").split("\t")
        self.assertEqual((p.returncode, kind, got), (0, "resume", sid))

    def test_new_line(self):
        p = self.run_cli()
        self.assertEqual((p.returncode, p.stdout), (0, "new\tこの dir の対話の会話がまだ無い\n"))

    def test_any_error_prints_new(self):
        def boom(_cwd):
            raise OSError("disk")
        real, rr.choose = rr.choose, boom
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                self.assertEqual(rr.main([self.cwd]), 0)
        finally:
            rr.choose = real
        self.assertEqual(buf.getvalue(), "new\t会話を選べなかった（OSError）\n")


class WrapperTest(Env):
    """claude-role.sh with a fake `claude` that prints its arguments."""

    def setUp(self):
        super().setUp()
        self.bin = os.path.join(self.tmp, "bin")
        os.makedirs(self.bin)
        fake = os.path.join(self.bin, "claude")
        with open(fake, "w") as fh:
            fh.write('#!/bin/bash\necho "CLAUDE_ARGS $*"\n')
        os.chmod(fake, 0o755)

    def run_wrapper(self, *args, **env):
        e = dict(os.environ, PATH=self.bin + os.pathsep + os.environ["PATH"], PYTHONDONTWRITEBYTECODE="1", **env)
        p = subprocess.run(["bash", os.path.join(SCRIPTS, "claude-role.sh")] + list(args),
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True,
                           cwd=self.cwd, env=e)
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout

    def test_resume(self):
        sid = self.conv()
        out = self.run_wrapper("--add-dir", "..", "--dangerously-skip-permissions")
        self.assertIn("CLAUDE_ARGS --resume %s --add-dir .. --dangerously-skip-permissions" % sid, out)
        self.assertIn("最新の会話を再開します", out)

    def test_new_when_nothing_to_resume(self):
        out = self.run_wrapper("--dangerously-skip-permissions")
        self.assertIn("CLAUDE_ARGS --dangerously-skip-permissions\n", out)
        self.assertIn("新しい会話で起動します（この dir の対話の会話がまだ無い）", out)

    def test_fresh_escape(self):
        self.conv()
        out = self.run_wrapper("--dangerously-skip-permissions", CLAUDE_FRESH="1")
        self.assertIn("CLAUDE_ARGS --dangerously-skip-permissions\n", out)
        self.assertIn("CLAUDE_FRESH=1", out)

    def test_each_choice_is_logged(self):
        sid = self.conv()
        self.run_wrapper()
        self.run_wrapper(CLAUDE_FRESH="1")
        with open(os.path.join(self.home, ".local/state/brain-company/claude-role.log"), encoding="utf-8") as fh:
            lines = fh.read().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertIn(" %s resume %s " % (self.cwd, sid[:8]), lines[0])
        self.assertIn(" %s new - " % self.cwd, lines[1])

    def test_new_when_python_is_missing(self):
        self.conv()
        e = {"PATH": self.bin + os.pathsep + "/usr/bin/nonexistent"}
        p = subprocess.run(["/bin/bash", os.path.join(SCRIPTS, "claude-role.sh"), "-x"],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True,
                           cwd=self.cwd, env=dict(e, HOME=self.home))
        self.assertIn("新しい会話で起動します（会話を選べなかった）", p.stdout)
        self.assertIn("CLAUDE_ARGS -x", p.stdout)


if __name__ == "__main__":
    unittest.main()
