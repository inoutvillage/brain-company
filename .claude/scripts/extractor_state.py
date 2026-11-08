#!/usr/bin/env python3
"""State of the Claude Code running in one tmux pane (used before sending keys to the extractor window).

Usage: extractor_state.py <sessions dir> <tmux session name> <pane id, e.g. %3>
Prints one line: "<status> <waitingFor or ->" with status busy / idle / waiting / shell,
or "unknown <reason, Japanese>" when it cannot tell (the caller then falls back to reading the screen).

Why: Enter sent to an open confirmation prompt answers it with the default "Yes" without a human seeing it, and the
screen check (looking for a spinner) does not see prompts. So the callers read the session record instead.
Callers: .claude/scripts/extract-actions-daily.sh (cron) and .claude/hooks/on-session-end.sh (SessionEnd).

The record is ~/.claude/sessions/<pid>.json, an unpublished internal format of Claude Code. A record belongs to the
pane when its "tmux" field ("<session>:@<window>.%<pane>") names this session exactly (the department session's name
is a prefix of the secretariat's) and this pane, and /proc/<pid>/stat field 22 equals its procStart (pid reuse).
Linux / WSL2 only (/proc). Never fails: any problem prints an "unknown" line.
"""
import glob
import json
import os
import sys


def state(sessions_dir, session, pane):
    try:
        ns = os.readlink("/proc/self/ns/pid")
    except OSError:
        return "unknown /proc を読めない"
    hits = []
    for f in glob.glob(os.path.join(sessions_dir, "*.json")):
        try:
            with open(f, encoding="utf-8") as fh:
                r = json.load(fh)
            t = r.get("tmux") or ""
            if t.split(":", 1)[0] != session or not t.endswith("." + pane):
                continue
            if r.get("pidDomain") and not str(r["pidDomain"]).endswith(ns):
                continue
            with open("/proc/%d/stat" % int(r["pid"])) as fh:
                rest = fh.read().rsplit(")", 1)[1].split()
            if str(r.get("procStart")) != rest[19]:  # stat の 22 番目（番号の使い回しを見分ける）
                continue
            hits.append(r)
        except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError):
            continue
    if not hits:
        return "unknown 動いているセッションの記録が無い"
    r = max(hits, key=lambda x: x.get("updatedAt") or 0)
    st = r.get("status")
    if st in ("busy", "idle", "waiting", "shell"):
        return "%s %s" % (st, r.get("waitingFor") or "-")
    return "unknown 状態が分からない"


def main(argv):
    if len(argv) != 3:
        print("unknown 使い方の誤り")
        return 0
    try:
        print(state(*argv))
    except Exception as exc:  # the caller must get one line whatever happens
        print("unknown 読めない（%s）" % type(exc).__name__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
