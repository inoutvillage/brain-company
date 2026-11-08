"""設定の入口（環境変数）。どれも無ければ既定の値で動く。

どの関数も env（既定は os.environ）を受け取る。試しでは辞書を渡して確かめる。
置き場の決め方は tools/board_ctl.sh と同じ（変える時は両方を変える）。
"""
from __future__ import annotations

import os
import re

APP_DIR = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))  # tools/session-board
DEFAULT_PORT = 18790
DEFAULT_TMUX_SESSION = "brain-company"
PORT_RE = re.compile(r"^[1-9][0-9]{0,4}$")


def company_root(env=os.environ) -> str:
    """会社のルート。SESSION_BOARD_COMPANY_ROOT、無ければこの道具の置き場（tools/session-board）の 2 つ上"""
    root = env.get("SESSION_BOARD_COMPANY_ROOT") or os.path.dirname(os.path.dirname(APP_DIR))
    # Claude Code が書く作業の場所は、たどった先の形（getcwd）なので、こちらもたどった先で比べる
    return os.path.realpath(os.path.expanduser(root))


def projects_root(env=os.environ) -> str:
    """案件のフォルダーの根: 会社のフォルダーの置いてある所（aipair の案件を、この下の一番上のフォルダーごとにまとめる）"""
    return os.path.dirname(company_root(env))


def dept_session(env=os.environ) -> str:
    """部署側の tmux セッション名（start-agents-all.sh と同じ TMUX_SESSION）"""
    return env.get("TMUX_SESSION") or DEFAULT_TMUX_SESSION


def secretary_session(env=os.environ) -> str:
    """秘書の tmux セッション名（start-secretariat.sh と同じ）"""
    return dept_session(env) + "-secretariat"


def state_dir(env=os.environ) -> str:
    """置き場: SESSION_BOARD_STATE_DIR、無ければ ${XDG_STATE_HOME:-$HOME/.local/state}/brain-company/session-board"""
    d = env.get("SESSION_BOARD_STATE_DIR")
    if not d:
        base = env.get("XDG_STATE_HOME") or os.path.join(env.get("HOME") or os.path.expanduser("~"), ".local", "state")
        d = os.path.join(base, "brain-company", "session-board")
    return os.path.abspath(d)


def port(env=os.environ) -> int:
    """待ち受けの番号: SESSION_BOARD_PORT、無ければ 18790。形が違えば ValueError"""
    v = env.get("SESSION_BOARD_PORT")
    if not v:
        return DEFAULT_PORT
    if not PORT_RE.match(v) or int(v) > 65535:
        raise ValueError(f"SESSION_BOARD_PORT の形が違う（1〜65535 の数）: {v[:20]!r}")
    return int(v)


def claude_home(env=os.environ) -> str:
    """Claude Code の置き場: CLAUDE_CONFIG_DIR、無ければ ~/.claude"""
    return os.path.expanduser(env.get("CLAUDE_CONFIG_DIR") or "~/.claude")


def codex_home(env=os.environ) -> str:
    """Codex の置き場: CODEX_HOME、無ければ ~/.codex"""
    return os.path.expanduser(env.get("CODEX_HOME") or "~/.codex")
