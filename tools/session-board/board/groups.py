"""グループ。最初は作業の場所で自動に分け、画面で直した分（名前・移した先・畳んだか）を prefs から重ねる。

自動の分け方:
- 会社: 作業の場所が会社のフォルダーそのものか、そのすぐ下（部署）のセッション（aipair を除く）
- 案件 · <上のフォルダー>: aipair の各案件を、案件のフォルダーの根（会社のフォルダーの置いてある所）の下の
  一番上のフォルダーごとに（会社の中は development/projects など 2 段）。
  数で分け方を変えると、名前を直した・移した先が消えるので、初めから分ける
- そのほか: どれにも当たらない物（tmux の外・Codex だけ 等）
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from . import config
from .collect import AIPAIR_RE, ORDER, Card, sort_key

COMPANY_ROOT = config.company_root()  # SESSION_BOARD_COMPANY_ROOT、無ければ tools/session-board の 2 つ上
DEV_ROOT = config.projects_root()  # 案件のフォルダーの根（会社のフォルダーの置いてある所）
DEFAULT_CLOSED = {"auto:company"}  # 会社は畳んで始める（部署はひとまとめに見る）


@dataclass
class Group:
    id: str
    name: str
    open: bool
    cards: list[Card] = field(default_factory=list)  # 表示する物
    hidden: list[Card] = field(default_factory=list)  # このグループで隠している、今動いている物

    def counts(self) -> dict[str, int]:
        return {c: sum(1 for x in self.cards if x.color == c) for c in ORDER}


def project_folder(cwd: str) -> str:
    if not cwd.startswith(DEV_ROOT + "/"):
        return "そのほか"
    parts = cwd[len(DEV_ROOT) + 1:].split("/")
    if parts[0] == os.path.basename(COMPANY_ROOT) and len(parts) >= 3:
        return "/".join(parts[1:3])
    return parts[0]


def auto_group(card: Card) -> str:
    cwd = card.cwd.rstrip("/")
    if card.tmux_session and AIPAIR_RE.match(card.tmux_session):
        return "auto:projects:" + project_folder(cwd)
    if cwd and (cwd == COMPANY_ROOT or os.path.dirname(cwd) == COMPANY_ROOT):
        return "auto:company"
    return "auto:other"


def default_name(gid: str) -> str:
    if gid == "auto:company":
        return "会社"
    if gid.startswith("auto:projects:"):
        return "案件 · " + gid[len("auto:projects:"):]
    return "そのほか"


def _tier(g: "Group") -> tuple[int, int]:
    """黄のあるグループが上（黄の件数の多い順。青もあっても黄が先）→ 青のあるグループ → 残り。
    数えるのは見出しの数と同じ物（隠したカードは数えない。一時停止中は灰）"""
    counts = g.counts()
    if counts["yellow"]:
        return 0, -counts["yellow"]
    return (1, 0) if counts["blue"] else (2, 0)


def _rank(gid: str, name: str):
    if gid.startswith("auto:projects:"):
        return (0, name)
    if gid.startswith("user:"):
        return (1, int(gid[5:]))
    return (2, 0) if gid == "auto:company" else (3, 0)


def layout(cards: list[Card], prefs: dict) -> list[Group]:
    """カードをグループに分ける。隠した物は、そのグループの hidden に入る（見出しの数には入れない）"""
    groups: dict[str, Group] = {}
    saved = prefs["groups"]
    for card in cards:
        card.auto_group = auto_group(card)
        gid = prefs["assign"].get(card.hide_key, card.auto_group)
        if gid.startswith("user:") and gid not in saved:
            gid = card.auto_group  # 作ったグループが消えていれば、自動の行き先へ
        g = groups.get(gid)
        if g is None:
            entry = saved.get(gid, {})
            g = groups[gid] = Group(gid, str(entry.get("name") or default_name(gid)),
                                    bool(entry.get("open", gid not in DEFAULT_CLOSED)))
        (g.hidden if card.hide_key in prefs["hidden"] else g.cards).append(card)
    for g in groups.values():
        g.cards.sort(key=sort_key)
    # 同じ段の中（黄の件数が同じ時も）は今までの並び（案件〈名前の順〉→ 作ったグループ → 会社 → そのほか）。色が同じなら場所が変わらない
    return sorted(groups.values(), key=lambda g: (_tier(g), _rank(g.id, g.name)))
