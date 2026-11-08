"""画面で直した物（隠す一覧・グループの名前と移した先・畳んだか）を、手元のファイル 1 つに残す。

置き場は STATE_DIR/prefs.json（600）だけ。一時のファイルに書いてから入れ替える。
隠す側・直した所だけを覚える（新しく始まったセッションは、表示する側・自動のグループから始まる）。
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import tempfile
import threading

MAX_HIDDEN = 200
MAX_ASSIGN = 300
MAX_GROUPS = 100  # 名前を直した・畳んだを覚えるグループ（自分で作った物を含む）
MAX_USER_GROUPS = 30
MAX_NAME = 40
MAX_FILE = 64 * 1024
KEY_RE = re.compile(r"^(?:codex:)?(?:tmux|cwd):[^\x00-\x1f\x7f]{1,280}$")
GROUP_RE = re.compile(r"^(?:auto:(?:company|other|projects:[^\x00-\x1f\x7f]{1,120})|user:[0-9]{1,6})$")
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_lock = threading.Lock()


class PrefsError(Exception):
    """手元のファイルを読めない・書けない（文は画面と記録に出す理由）"""


def path(state_dir: str) -> str:
    return os.path.join(state_dir, "prefs.json")


def empty() -> dict:
    return {"hidden": {}, "assign": {}, "groups": {}}


def load(state_dir: str) -> dict:
    """{"hidden": {印: {name, place, at}}, "assign": {印: グループ}, "groups": {グループ: {name?, open?}}}"""
    p = path(state_dir)
    try:
        if os.path.getsize(p) > MAX_FILE:
            raise PrefsError("画面の設定のファイルが大きすぎる")
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return empty()
    except (OSError, ValueError):
        raise PrefsError("画面の設定のファイルを読めない")
    if not isinstance(data, dict):
        raise PrefsError("画面の設定のファイルの形が違う")
    out = empty()
    for part in out:
        value = data.get(part, {})
        if not isinstance(value, dict) or not all(isinstance(k, str) for k in value):
            raise PrefsError("画面の設定のファイルの形が違う")
        out[part] = value
    if not all(isinstance(v, dict) for v in out["hidden"].values()) \
            or not all(isinstance(v, str) for v in out["assign"].values()) \
            or not all(isinstance(v, dict) for v in out["groups"].values()):
        raise PrefsError("画面の設定のファイルの形が違う")
    return out


def _save(state_dir: str, prefs: dict) -> None:
    body = json.dumps({"version": 1, **prefs}, ensure_ascii=False, indent=1)
    if len(body.encode()) > MAX_FILE:
        raise OverflowError("画面の設定がいっぱい")
    os.makedirs(state_dir, mode=0o700, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".prefs-", suffix=".json", dir=state_dir)  # 600 で作られる
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path(state_dir))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def clean_name(name) -> str:
    """グループの名前（社長が打った文字）。前後の空白を外し、長さと制御文字を確かめる。出す時は必ず escape する"""
    if not isinstance(name, str):
        raise ValueError("名前の形が違う")
    name = name.strip()
    if not 1 <= len(name) <= MAX_NAME or CONTROL_RE.search(name):
        raise ValueError(f"名前は 1〜{MAX_NAME} 字（改行なし）")
    return name


def _prune(prefs: dict) -> None:
    """だれも入っていない、自分で作ったグループを消す"""
    used = set(prefs["assign"].values())
    for gid in [g for g in prefs["groups"] if g.startswith("user:") and g not in used]:
        del prefs["groups"][gid]


def change(state_dir: str, req: dict, cards_by_key: dict, groups_now: set[str]) -> dict:
    """1 つの操作を当てて残す。受け付けるのは、今のカードの印・今隠している印・今あるグループだけ。
    req は形を確かめ済み（server.valid_request）。読めないファイルには書かない（中身を消さないため）"""
    with _lock:
        prefs = load(state_dir)
        act = req["action"]
        if act == "hide":
            card = cards_by_key.get(req["key"])
            if card is None:
                raise ValueError("知らない印")
            if req["key"] not in prefs["hidden"]:
                if len(prefs["hidden"]) >= MAX_HIDDEN:
                    raise OverflowError("隠す一覧がいっぱい")
                prefs["hidden"][req["key"]] = {"name": card.name, "place": card.place,
                                               "at": dt.datetime.now().astimezone().isoformat(timespec="seconds")}
        elif act == "show":
            if req["key"] not in prefs["hidden"]:
                raise ValueError("知らない印")
            del prefs["hidden"][req["key"]]
        elif act == "move":
            card = cards_by_key.get(req["key"])
            if card is None:
                raise ValueError("知らない印")
            gid = req["group"]
            if gid == "new":
                users = [int(g[5:]) for g in prefs["groups"] if g.startswith("user:")]
                if len(users) >= MAX_USER_GROUPS:
                    raise OverflowError("作ったグループがいっぱい")
                gid = f"user:{max(users, default=0) + 1}"
                prefs["groups"][gid] = {"name": clean_name(req["name"])}
            elif gid not in groups_now and gid not in prefs["groups"]:
                raise ValueError("知らないグループ")
            if req["key"] not in prefs["assign"] and len(prefs["assign"]) >= MAX_ASSIGN:
                raise OverflowError("移した物がいっぱい")
            if gid == card.auto_group:
                prefs["assign"].pop(req["key"], None)  # 自動の行き先に戻すなら、覚えておかない
            else:
                prefs["assign"][req["key"]] = gid
        elif act in ("rename", "fold"):
            gid = req["group"]
            if gid not in groups_now and gid not in prefs["groups"]:
                raise ValueError("知らないグループ")
            if gid not in prefs["groups"] and len(prefs["groups"]) >= MAX_GROUPS:
                raise OverflowError("覚えるグループがいっぱい")
            entry = prefs["groups"].setdefault(gid, {})
            if act == "rename":
                entry["name"] = clean_name(req["name"])
            else:
                entry["open"] = bool(req["open"])
        else:
            raise ValueError("知らない操作")
        _prune(prefs)
        _save(state_dir, prefs)
        return prefs
