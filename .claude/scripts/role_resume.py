#!/usr/bin/env python3
"""Pick the conversation a role session (the secretariat or a department) resumes at launch.

Called by claude-role.sh as `python3 role_resume.py <dir>`. Prints one tab-separated line:
  resume <session id> <last update MM/DD HH:MM>
  new <reason, Japanese>

Rules (measured on Claude Code 2.1.302):
  - Only conversations started in this dir: the .jsonl files in ~/.claude/projects/<dir, non-alphanumerics as "-">/
    whose recorded cwd is this dir (two dirs can share a folder name: /a-b and /a/b).
  - One-shot conversations (claude -p / SDK, entrypoint "sdk-*") are skipped.
  - The newest remaining one decides:
      a running claude uses it  -> new   (a plain --continue would join it; two processes writing one log mix it)
      use cannot be checked      -> new   (no /proc, e.g. macOS: resuming blind could join a running conversation)
      no readable record         -> new   (claude --resume stops with "No conversation found")
      otherwise                  -> resume
Never fails: any error prints a "new" line.
"""
import glob
import json
import os
import re
import sys
import time

PROC = "/proc"  # tests point this elsewhere to act as a machine without /proc
UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\Z")
META_LINES = 200


def claude_home():
    return os.path.join(os.path.expanduser("~"), ".claude")


def project_dir(cwd):
    return os.path.join(claude_home(), "projects", re.sub(r"[^A-Za-z0-9]", "-", cwd))


def same_dir(a, b):
    try:
        return os.path.samefile(a, b)
    except OSError:
        return os.path.realpath(a) == os.path.realpath(b)


def read_meta(path):
    """(cwd, entrypoint) from the first record that carries a cwd, or None when no such record is readable."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for i, line in enumerate(fh):
                if i >= META_LINES:
                    break
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if isinstance(rec, dict) and isinstance(rec.get("cwd"), str):
                    entry = rec.get("entrypoint")
                    return rec["cwd"], entry if isinstance(entry, str) else ""
    except OSError:
        pass
    return None


def proc_start(pid):
    try:
        with open(os.path.join(PROC, "%d" % pid, "stat")) as fh:
            stat = fh.read()
    except OSError:
        return None
    fields = stat[stat.rfind(")") + 2:].split()
    return fields[19] if len(fields) > 19 else None


def live_sessions():
    """{session id: tmux location} of the conversations running claude processes have open, or None without /proc.

    Claude Code writes ~/.claude/sessions/<pid>.json with the current sessionId. A file counts only while that pid
    runs with the same start time, so a reused pid never makes an old file look live. Without /proc the start time
    cannot be checked, so nothing can be told apart: None, and the caller starts a new conversation."""
    if not os.path.isdir(PROC):
        return None
    live = {}
    for path in glob.glob(os.path.join(claude_home(), "sessions", "*.json")):
        name = os.path.basename(path)[:-len(".json")]
        if not name.isdigit():
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                rec = json.load(fh)
        except (OSError, ValueError):
            continue
        if not isinstance(rec, dict) or rec.get("pid") != int(name):
            continue
        started = proc_start(int(name))
        if started is None or str(rec.get("procStart")) != started:
            continue
        sid = rec.get("sessionId")
        if isinstance(sid, str):
            tmux = rec.get("tmux")
            live[sid] = tmux if isinstance(tmux, str) else ""
    return live


def choose(cwd):
    """("resume", id, last update) or ("new", reason)."""
    files = []
    for path in glob.glob(os.path.join(project_dir(cwd), "*.jsonl")):
        sid = os.path.basename(path)[:-len(".jsonl")]
        if not UUID_RE.match(sid):
            continue
        try:
            files.append((os.path.getmtime(path), sid, path))
        except OSError:
            continue
    live = live_sessions()
    for mtime, sid, path in sorted(files, reverse=True):
        meta = read_meta(path)
        if meta is not None and (meta[1].startswith("sdk") or not same_dir(meta[0], cwd)):
            continue
        if live is None:
            return ("new", "ほかの claude が使っているかを確かめられない（/proc が無い）。混ざらないよう、新しい会話で起動")
        if sid in live:
            where = live[sid].split(":")[0]
            return ("new", "この dir の最新の会話は、ほかの claude が使っている（%s）。混ざらないよう、新しい会話で起動"
                    % ("tmux の " + where if where else "tmux の外"))
        if meta is None:
            return ("new", "この dir の最新の会話の記録が読めない（%s…）" % sid[:8])
        return ("resume", sid, time.strftime("%m/%d %H:%M", time.localtime(mtime)))
    return ("new", "この dir の対話の会話がまだ無い")


def main(argv):
    try:
        cwd = os.path.realpath(argv[0] if argv else os.getcwd())
        pick = choose(cwd)
        if pick[0] == "resume":
            print("resume\t%s\t%s" % (pick[1], pick[2]))
        else:
            print("new\t%s" % pick[1])
    except Exception as exc:  # the launcher must start claude whatever happens here
        print("new\t会話を選べなかった（%s）" % type(exc).__name__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
