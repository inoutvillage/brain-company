"""カードを HTML にする。文は全部ここで escape する（画面の側では組み立てない）"""
from __future__ import annotations

import datetime as dt
import hashlib
from html import escape

from .collect import ORDER, STALE_MS, Card
from .groups import Group

COLOR_NAMES = {"yellow": "黄", "blue": "青", "standby": "待機", "gray": "灰", "unreadable": "読めない"}


def _local(ms: int) -> dt.datetime:
    """その PC の時間帯の時刻"""
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).astimezone()


def _when(ms: int | None, now_ms: int) -> str:
    if not ms:
        return "読めない（時刻が無い）"
    t, now = _local(ms), _local(now_ms)
    stamp = t.strftime("%H:%M") if t.date() == now.date() else t.strftime("%m/%d %H:%M")
    mins = max(0, (now_ms - ms) // 60000)
    ago = "今" if mins < 1 else f"{mins} 分前" if mins < 60 else f"{mins // 60} 時間前" if mins < 48 * 60 else f"{mins // 1440} 日前"
    return f"{stamp}（{ago}）"


def _unreadable(why: str) -> str:
    return f'<span class="unreadable">読めない（{escape(why)}）</span>'


def _progress(card: Card) -> str:
    if "progress" in card.problems:
        return f'<div class="row"><span class="k">進み具合</span>{_unreadable(card.problems["progress"])}</div>'
    if card.progress is None:
        return ""
    done, todo, blocked = card.progress
    total = done + todo + blocked
    if total == 0:
        return '<div class="row"><span class="k">進み具合</span><span class="v muted">tasks/todo.md に項目が無い</span></div>'
    pd, pb = 100 * done / total, 100 * blocked / total
    extra = f"・人の判断待ち {blocked}" if blocked else ""
    return (
        '<div class="row"><span class="k">進み具合</span><span class="v">'
        f'<svg class="bar" viewBox="0 0 100 10" preserveAspectRatio="none" role="img" aria-label="済 {done} / 全 {total}">'
        f'<rect class="done" width="{pd:.1f}" height="10"/><rect class="blocked" x="{pd:.1f}" width="{pb:.1f}" height="10"/></svg>'
        f'<span class="nums">済 {done} / 全 {total}{extra}</span></span></div>'
    )


def _menu(card: Card, group_id: str, choices: list[tuple[str, str]]) -> str:
    """カードの右上の「⋯」のメニュー（グループへ移す・表示しない）。グループを畳むのとは別の物"""
    if not card.hide_key:
        return ""
    key = escape(card.hide_key, quote=True)
    moves = "".join(f'<button type="button" role="menuitem" data-act="move" data-key="{key}" data-group="{escape(g, quote=True)}">'
                    f'{escape(n)}</button>' for g, n in choices if g != group_id)
    label = "このカードの操作（グループを移す・表示しない）"
    return (f'<div class="menu-wrap"><button class="icon more" type="button" data-key="{key}" aria-haspopup="menu" aria-expanded="false" '
            f'title="{label}" aria-label="{label}">⋯</button>'
            f'<div class="menu" role="menu" hidden><div class="menu-h">グループを移す</div>{moves}'
            f'<button type="button" role="menuitem" data-act="move" data-key="{key}" data-group="new">＋ 新しいグループ…</button>'
            f'<div class="menu-sep" role="separator"></div>'
            f'<button type="button" role="menuitem" data-act="hide" data-key="{key}">表示しない（上の「隠している」から戻せる）</button>'
            f'</div></div>')


def _full_opener(card: Card, kind: str, text: str, label: str) -> str:
    """押すと全文のモーダルを開く所（全文は押した時に /text へ取りに行く）。印の無いカードは押せない。
    取りに行く時はカードの番号（card.key = claude-<pid>・codex-<pid>）で指す。隠す印（hide_key）は同じ場所の 2 つの会話で重なりうるので使わない"""
    if not card.hide_key:
        return escape(text)
    return (f'<span class="full" role="button" tabindex="0" data-full="{kind}" data-card="{escape(card.key, quote=True)}" '
            f'aria-label="{label}" title="押すと全文">{escape(text)}</span>')


def card_html(card: Card, now_ms: int, group_id: str = "", choices: list[tuple[str, str]] | None = None) -> str:
    parts = [f'<article class="card {card.color}" data-color="{card.color}">',
             f'<header><h2>{escape(card.name)}</h2><span class="chip">{escape(card.label)}</span>{_menu(card, group_id, choices or [])}</header>']
    if card.warn:
        parts.append(f'<div class="row warn"><span class="k">注意</span><span class="v">{escape(card.warn)}</span></div>')
    if "status" in card.problems:
        parts.append(f'<div class="row"><span class="k">状態</span>{_unreadable(card.problems["status"])}</div>')
    where = " ・ ".join(escape(x) for x in (card.place, card.path) if x)
    if where:
        parts.append(f'<div class="where">{where}</div>')
    if card.key.startswith("claude-"):
        if "prompt" in card.problems:
            parts.append(f'<div class="row"><span class="k">頼んだこと</span>{_unreadable(card.problems["prompt"])}</div>')
        elif card.prompt is None:
            parts.append('<div class="row"><span class="k">頼んだこと</span><span class="v muted">（まだ依頼が無い）</span></div>')
        else:
            when = f'<span class="t">{escape(_when(card.prompt_ms, now_ms))}</span>' if card.prompt_ms else ""
            parts.append(f'<div class="row"><span class="k">頼んだこと</span><span class="v">'
                         f'{_full_opener(card, "prompt", card.prompt, "頼んだことの全文を開く")}{when}</span></div>')
            reply = (_full_opener(card, "reply", card.reply, "返事の全文を開く") if card.reply
                     else '<span class="muted">（この依頼への返事はまだ）</span>')
            parts.append(f'<div class="row"><span class="k">返事の頭</span><span class="v">{reply}</span></div>')
    parts.append(_progress(card))
    if card.codex is not None:
        cx = card.codex
        if cx.state == "unreadable":
            state = _unreadable(cx.why)
        else:
            state = f'<span class="cx {cx.state}">{"作業中" if cx.state == "busy" else "待ち"}</span>'
            if cx.last_ms:
                state += f'<span class="t">{escape(_when(cx.last_ms, now_ms))}</span>'
        parts.append(f'<div class="row"><span class="k">Codex</span><span class="v">{state}</span></div>')
    parts.append(f'<div class="row last"><span class="k">最後に動いた</span><span class="v">{escape(_when(card.last_ms, now_ms))}</span></div>')
    parts.append("</article>")
    return "".join(parts)


def hidden_html(hidden: dict[str, dict], hidden_cards: list[Card], now_ms: int) -> str:
    """隠している物の一覧（いつも上に数を出し、開くと戻せる）。今動いていない物も出す"""
    running = {c.hide_key: c for c in hidden_cards}
    yellow = sum(1 for c in hidden_cards if c.color == "yellow")
    head = f'隠している {len(hidden)}' + (f'（うち黄 {yellow}）' if yellow else "")
    rows = []
    order = sorted(hidden, key=lambda k: (k not in running, ORDER.get(running[k].color, 9) if k in running else 9,
                                          str(hidden[k].get("name", ""))))
    for k in order:
        meta, card = hidden[k], running.get(k)
        key = escape(k, quote=True)
        if card:
            state = f'<span class="chip {card.color}">{escape(card.label)}</span>'
            button = f'<button class="pill" type="button" data-act="show" data-key="{key}">表示に戻す</button>'
            name, place = card.name, card.place
        else:
            state = '<span class="chip">今は動いていない</span>'
            button = f'<button class="pill" type="button" data-act="show" data-key="{key}">一覧から消す</button>'
            name, place = str(meta.get("name", "")), str(meta.get("place", ""))
        rows.append(f'<li><b>{escape(name)}</b><span class="where">{escape(place)}</span>{state}'
                    f'<span class="t">隠した: {escape(str(meta.get("at", ""))[:16].replace("T", " "))}</span>{button}</li>')
    body = f'<ul>{"".join(rows)}</ul>' if rows else '<p class="muted">隠している物は無い</p>'
    cls = "hidden-list has-yellow" if yellow else "hidden-list"
    return f'<details id="hidden-list" class="{cls}"><summary>{head}</summary>{body}</details>'


def _small_counts(counts: dict[str, int]) -> str:
    return "".join(f'<span class="count small {c}">{COLOR_NAMES[c]} {counts[c]}</span>' for c in COLOR_NAMES if counts[c])


def group_html(g: Group, now_ms: int, choices: list[tuple[str, str]]) -> str:
    """畳めるグループ。見出しは名前・鉛筆・数の丸（隠した物は数に入れず、別の丸で添える）。黄があれば見出しを黄にする"""
    counts = g.counts()
    nums = _small_counts(counts) or '<span class="muted small">表示している物は無い</span>'
    if g.hidden:
        hy = sum(1 for c in g.hidden if c.color == "yellow")
        nums += f'<span class="count small hid">隠している {len(g.hidden)}' + (f"・うち黄 {hy}" if hy else "") + "</span>"
    gid = escape(g.id, quote=True)
    cls = " ".join(["group"] + [f"has-{c}" for c in COLOR_NAMES if counts[c]])
    label = "グループの名前を変える"
    body = "".join(card_html(c, now_ms, g.id, choices) for c in g.cards) or '<p class="muted">このグループで表示している物は無い</p>'
    return (f'<details class="{cls}" data-group="{gid}" data-open="{int(g.open)}"{" open" if g.open else ""}>'
            f'<summary><span class="gname">{escape(g.name)}</span>'
            f'<button class="icon edit" type="button" data-act="rename" data-group="{gid}" data-name="{escape(g.name, quote=True)}" '
            f'title="{label}" aria-label="{label}">✎</button><span class="gnums">{nums}</span>'
            f'</summary><div class="grid">{body}</div></details>')


def board_html(laid: list[Group], notes: list[str], now_ms: int, hidden: dict[str, dict] | None = None) -> str:
    """自動の更新で差し替える部分（数の丸＝絞り込み・隠している物・全体の読めない所・グループごとのカード）"""
    visible = [c for g in laid for c in g.cards]
    counts = {c: sum(1 for x in visible if x.color == c) for c in COLOR_NAMES}
    chips = "".join(
        f'<button type="button" class="count {c}" data-filter="{c}" aria-pressed="false" '
        f'title="{COLOR_NAMES[c]}のカードだけを出す（もう一度押すと全部）">{COLOR_NAMES[c]} {counts[c]}</button>'
        for c in COLOR_NAMES if counts[c] or c != "unreadable")
    stamp = _local(now_ms).strftime("%H:%M:%S")
    note_html = "".join(f'<div class="note">{_unreadable(n)}</div>' for n in notes)
    choices = [(g.id, g.name) for g in laid]
    body = "".join(group_html(g, now_ms, choices) for g in laid) or '<p class="muted">動いているセッションが見つからない</p>'
    hidden_cards = [c for g in laid for c in g.hidden]
    return (f'<div id="summary" data-yellow="{counts["yellow"]}"><span class="filter-label">絞り込み</span>{chips}'
            f'<span class="stamp">{stamp} に集めた</span></div>'
            f'{hidden_html(hidden or {}, hidden_cards, now_ms)}{note_html}<div class="groups">{body}</div>')


def page_html(fragment: str, banner: str = "") -> str:
    stale_h = STALE_MS // 3_600_000
    banner_html = f'<p class="banner">{escape(banner)}</p>' if banner else ""
    return f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>セッションの一覧</title>
<meta name="board-version" content="{VERSION}">
<link rel="stylesheet" href="/board.css">
<noscript><meta http-equiv="refresh" content="10"></noscript>
</head>
<body>
<header class="top">
<h1>セッションの一覧</h1>
<span id="fail" class="fail" hidden></span>
</header>
{banner_html}<main id="board">{fragment}</main>
<dialog id="full-dialog" aria-labelledby="full-title"><div class="full-box">
<div class="full-head"><h2 id="full-title"></h2><button type="button" class="icon" id="full-close" aria-label="閉じる" title="閉じる（Esc）">×</button></div>
<pre id="full-text"></pre>
<p class="full-note"><span id="full-omitted"></span>秘密らしい文字列は伏せてあります。</p>
</div></dialog>
<footer>
<p><b>色の決め方</b>　黄＝社長の番（許可の問い・質問への答え待ち、社長の最後の頼みへの返事が問いかけで終わった時、またはその返事の最後の節が決めてほしいことの節の時。自動のターン（作業の知らせ等）への返事は飛ばして見る。答えるまで黄のまま）・青＝作業中（Codex が作業中も青）・待機（緑）＝やることを終えた（最後に動いてから {stale_h} 時間まで。社長の番ではない）・灰＝しばらく動いていない（{stale_h} 時間より前）。部署と秘書室の抜き出しの係は、知らせで動くので、手が空いても灰。止めてある Claude Code は「一時停止中」（灰）。</p>
<p><b>決めてほしいことの節</b>　返事の最後の見出し（# の見出し・太字だけの行）に「まだ決まっていない・決めてほしい・決めていただ・選んでほしい・選んでいただ・選べる・選択肢・ご判断・判断が要る・判断をお願い・確かめていただきたい・伺いたい・質問・提案・案（案件・案内は除く）・Open questions・Decisions・Questions」のどれかがあれば黄。見出しが無ければ、最後のかたまりが、その言葉の行と番号つきの一覧・表なら黄。本文の途中だけの言葉や、「残ること」「次にすること」で終わる返事は待機。迷う時は、見出しにあれば黄に倒す。</p>
<p><b>絞り込み</b>　上の「黄・青・待機・灰」の丸を押すと、その色のカードと、その色があるグループだけを出す。もう一度押すと全部に戻る（このブラウザが覚える）。</p>
<p><b>グループの並び</b>　黄のあるグループが上（黄の件数の多い順）、次に青のあるグループ、その下に残り（待機・灰だけのグループ）。同じ段の中は、案件（名前の順）→ 作ったグループ → 会社 → そのほか。数えるのは見出しの数と同じ（隠したカードは数えない）。並びが変わったグループは、しばらく青い縁取りで知らせる。</p>
<p><b>グループ</b>　最初は自動で分ける（会社＝会社のフォルダーとそのすぐ下で動く物、案件＝aipair の各案件を上のフォルダーごと、そのほか）。見出しを押すと畳める。✎ で名前を変える。見出しの数は表示している物だけで、隠している物は別の丸で添える。黄のあるグループは、畳んでいても見出しが黄になる。直した分は、この PC の中のファイルに残る。</p>
<p><b>全文</b>　「頼んだこと」と「返事の頭」を押す（か、選んで Enter）と、全文を開く。長い時は中で縦に送る。秘密らしい文字列は伏せてある。×・Esc・外を押すと閉じる。</p>
<p><b>カードの ⋯</b>　別のグループへ移す・表示しない。隠したカードは、上の「隠している」の一覧から表示に戻せる。新しく始まったセッションは表示する。</p>
<p>進み具合は、作業の場所の tasks/todo.md の <code>- [x]</code>（済）・<code>- [ ]</code>（未）・<code>- [!]</code>（人の判断待ち。全体に数え、黄土色で出す）。無い案件はバーを出さない。5 秒ごとに新しくする。</p>
</footer>
<script src="/board.js"></script>
</body>
</html>
"""


CSS = """/* ページ全体の大きさ（字・余白・カードの幅）。ここ 1 か所だけを変える。1＝ふつうの大きさ、.75＝ブラウザで 75% に縮めた時と同じ見え方。
   1px の線・キーボードの枠・狭い窓の幅（420px）は変えない */
:root{--scale:1}
:root{color-scheme:light dark;--bg:#f6f7f9;--card:#fff;--ink:#1d2329;--muted:#5f6873;--line:#d3d9e0;--hover:#eef1f4;
--yellow:#f2b705;--yellow-bg:#fff8dc;--blue:#2f6fde;--blue-bg:#eef4ff;--standby:#1a8456;--standby-bg:#e6f4ec;--gray:#8b949e;--gray-bg:#f1f2f4;--bad:#c62828;--bad-bg:#fdecec;--blocked:#c9a227}
@media (prefers-color-scheme:dark){:root{--bg:#15181c;--card:#1e2329;--ink:#e6e9ed;--muted:#a3acb6;--line:#38414b;--hover:#2a3038;
--yellow-bg:#3a3215;--blue-bg:#17263f;--standby-bg:#13332a;--gray-bg:#262b32;--bad-bg:#3d1d1d}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:calc(15px*var(--scale))/1.55 system-ui,"Segoe UI","Yu Gothic UI","Hiragino Sans",sans-serif}
button{font:inherit;color:var(--ink)}
:focus-visible{outline:2px solid var(--blue);outline-offset:2px}
.top{display:flex;flex-wrap:wrap;gap:calc(12px*var(--scale)) calc(20px*var(--scale));align-items:center;padding:calc(14px*var(--scale)) calc(20px*var(--scale));border-bottom:1px solid var(--line);background:var(--card);position:sticky;top:0;z-index:10}
h1{font-size:calc(18px*var(--scale));margin:0}.banner{margin:calc(12px*var(--scale)) calc(20px*var(--scale)) 0;padding:calc(6px*var(--scale)) calc(12px*var(--scale));border:1px dashed var(--muted);border-radius:calc(8px*var(--scale));color:var(--muted)}.fail{color:var(--bad);font-weight:600}
main{padding:calc(16px*var(--scale)) calc(20px*var(--scale))}#summary{display:flex;flex-wrap:wrap;gap:calc(8px*var(--scale));align-items:center;margin-bottom:calc(12px*var(--scale))}
.filter-label{color:var(--muted);font-size:calc(13px*var(--scale))}
/* 数の丸・ボタン・鉛筆・⋯ を同じ形にそろえる（暗い地・細い枠・丸い角・同じ高さ） */
.count,.pill,.icon{display:inline-flex;align-items:center;justify-content:center;height:calc(28px*var(--scale));padding:0 calc(12px*var(--scale));border-radius:999px;
border:1px solid var(--line);background:var(--card);color:var(--ink);font-size:calc(13px*var(--scale));font-weight:600;line-height:1;white-space:nowrap}
.count.small{height:calc(22px*var(--scale));padding:0 calc(9px*var(--scale));font-size:calc(12px*var(--scale))}
.icon{width:calc(28px*var(--scale));padding:0;font-size:calc(15px*var(--scale));font-weight:400}
button.count,.pill,.icon{cursor:pointer}
button.count:hover,.pill:hover,.icon:hover{border-color:var(--muted);background:var(--hover)}
.pill:disabled,.icon:disabled,button.count:disabled{opacity:.5;cursor:default}
.count.yellow{background:var(--yellow-bg);border-color:var(--yellow)}.count.blue{background:var(--blue-bg);border-color:var(--blue)}
.count.standby{background:var(--standby-bg);border-color:var(--standby)}.count.gray{background:var(--gray-bg)}.count.unreadable{background:var(--bad-bg);border-color:var(--bad)}.count.hid{background:transparent;border-style:dashed;color:var(--muted)}
button.count[aria-pressed="true"]{box-shadow:0 0 0 calc(2px*var(--scale)) var(--bg),0 0 0 calc(4px*var(--scale)) var(--ink)}
button.count.yellow[aria-pressed="true"]{background:var(--yellow);color:#2b2200}button.count.blue[aria-pressed="true"]{background:var(--blue);color:#fff}
button.count.standby[aria-pressed="true"]{background:var(--standby);color:#fff}button.count.gray[aria-pressed="true"]{background:var(--gray);color:#111}button.count.unreadable[aria-pressed="true"]{background:var(--bad);color:#fff}
.stamp{color:var(--muted);font-size:calc(13px*var(--scale));margin-left:auto}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(calc(340px*var(--scale)),1fr));gap:calc(12px*var(--scale))}
.card{position:relative;background:var(--card);border:1px solid var(--line);border-left:calc(8px*var(--scale)) solid var(--gray);border-radius:calc(10px*var(--scale));padding:calc(10px*var(--scale)) calc(14px*var(--scale));min-width:0}
.card.yellow{border-left-color:var(--yellow);background:var(--yellow-bg)}.card.blue{border-left-color:var(--blue)}.card.standby{border-left-color:var(--standby)}
.card.gray .row,.card.gray .where{opacity:.82}.card.unreadable{border-left-color:var(--bad);border-style:dashed solid dashed solid}
.card header{display:flex;gap:calc(8px*var(--scale));align-items:center}
.card h2{font-size:calc(16px*var(--scale));margin:0;overflow-wrap:anywhere}.chip{font-size:calc(12px*var(--scale));padding:calc(1px*var(--scale)) calc(8px*var(--scale));border-radius:999px;background:var(--gray-bg);white-space:nowrap}
.yellow .chip,.chip.yellow{background:var(--yellow);color:#2b2200}.standby .chip,.chip.standby{background:var(--standby);color:#fff}.blue .chip,.chip.blue{background:var(--blue);color:#fff}.unreadable .chip,.chip.unreadable{background:var(--bad);color:#fff}
/* カードの右上の ⋯ と、そのメニュー */
.menu-wrap{position:relative;margin-left:auto;flex:none}
.menu[hidden]{display:none}
.menu{position:absolute;right:0;top:calc(34px*var(--scale));z-index:20;min-width:15em;max-width:22em;display:flex;flex-direction:column;gap:calc(2px*var(--scale));padding:calc(6px*var(--scale));
background:var(--card);border:1px solid var(--line);border-radius:calc(10px*var(--scale));box-shadow:0 calc(8px*var(--scale)) calc(28px*var(--scale)) rgba(0,0,0,.35)}
.menu button{display:block;width:100%;text-align:left;padding:calc(7px*var(--scale)) calc(10px*var(--scale));border:0;border-radius:calc(6px*var(--scale));background:transparent;font-size:calc(14px*var(--scale));cursor:pointer;overflow-wrap:anywhere}
.menu button:hover,.menu button:focus-visible{background:var(--hover);outline:none}
.menu-h{font-size:calc(12px*var(--scale));color:var(--muted);padding:calc(4px*var(--scale)) calc(10px*var(--scale)) calc(2px*var(--scale))}.menu-sep{height:1px;background:var(--line);margin:calc(4px*var(--scale)) calc(2px*var(--scale))}
.where{color:var(--muted);font-size:calc(12px*var(--scale));margin:calc(2px*var(--scale)) 0 calc(6px*var(--scale));overflow-wrap:anywhere}
.row{display:grid;grid-template-columns:6.4em 1fr;gap:calc(8px*var(--scale));margin:calc(3px*var(--scale)) 0;font-size:calc(14px*var(--scale))}.k{color:var(--muted)}.v{min-width:0;overflow-wrap:anywhere}
.t{color:var(--muted);font-size:calc(12px*var(--scale));margin-left:calc(6px*var(--scale));white-space:nowrap}.muted{color:var(--muted)}.small{font-size:calc(12px*var(--scale))}
.unreadable{color:var(--bad);font-weight:600}
.row.warn .v{color:var(--bad);font-weight:600}.card.gray .row.warn{opacity:1}
.bar{display:inline-block;width:calc(140px*var(--scale));height:calc(10px*var(--scale));border-radius:calc(5px*var(--scale));background:var(--line);vertical-align:middle;margin-right:calc(8px*var(--scale))}
.bar .done{fill:var(--blue)}.bar .blocked{fill:var(--blocked)}.nums{font-size:calc(13px*var(--scale))}
.cx.busy{color:var(--blue);font-weight:600}
/* 丸で絞り込む（その色のカードと、その色があるグループだけ） */
body[data-filter="yellow"] .card:not(.yellow),body[data-filter="blue"] .card:not(.blue),body[data-filter="standby"] .card:not(.standby),
body[data-filter="gray"] .card:not(.gray),body[data-filter="unreadable"] .card:not(.unreadable){display:none}
body[data-filter="yellow"] .group:not(.has-yellow),body[data-filter="blue"] .group:not(.has-blue),body[data-filter="standby"] .group:not(.has-standby),
body[data-filter="gray"] .group:not(.has-gray),body[data-filter="unreadable"] .group:not(.has-unreadable){display:none}
.groups{display:flex;flex-direction:column;gap:calc(12px*var(--scale))}
.group{border:1px solid var(--line);border-radius:calc(10px*var(--scale));background:var(--card);padding:0 calc(12px*var(--scale))}
.group>summary{display:flex;flex-wrap:wrap;gap:calc(6px*var(--scale)) calc(10px*var(--scale));align-items:center;padding:calc(8px*var(--scale)) calc(2px*var(--scale));cursor:pointer;font-size:calc(15px*var(--scale))}
.group>summary .gname{font-weight:700}.group>summary .gnums{display:inline-flex;flex-wrap:wrap;gap:calc(6px*var(--scale));margin-left:calc(4px*var(--scale))}
.group>summary .edit{height:calc(24px*var(--scale));width:calc(24px*var(--scale));font-size:calc(13px*var(--scale))}
.group.has-yellow>summary{background:var(--yellow-bg);border-left:calc(6px*var(--scale)) solid var(--yellow);margin:0 calc(-12px*var(--scale));padding:calc(8px*var(--scale)) calc(14px*var(--scale));border-radius:calc(10px*var(--scale)) calc(10px*var(--scale)) 0 0}
.group.has-yellow:not([open])>summary{border-radius:calc(10px*var(--scale))}
.group>.grid{padding:calc(4px*var(--scale)) 0 calc(12px*var(--scale))}
.group.moved{box-shadow:0 0 0 calc(3px*var(--scale)) var(--blue);transition:box-shadow .4s}
.hidden-list{margin:0 0 calc(12px*var(--scale));border:1px solid var(--line);border-radius:calc(10px*var(--scale));background:var(--card);padding:calc(6px*var(--scale)) calc(12px*var(--scale))}
.hidden-list summary{cursor:pointer;font-weight:600;font-size:calc(14px*var(--scale))}.hidden-list.has-yellow summary{color:var(--ink);background:var(--yellow-bg);border-radius:calc(6px*var(--scale));padding:0 calc(6px*var(--scale))}
.hidden-list ul{list-style:none;margin:calc(8px*var(--scale)) 0 calc(2px*var(--scale));padding:0}.hidden-list li{display:flex;flex-wrap:wrap;gap:calc(4px*var(--scale)) calc(10px*var(--scale));align-items:center;padding:calc(6px*var(--scale)) 0;border-top:1px solid var(--line);font-size:calc(14px*var(--scale))}
.hidden-list .where{margin:0}.hidden-list .pill{margin-left:auto;height:calc(26px*var(--scale))}
/* 全文のモーダル（文字のまま出す。長い時は中で縦に送る） */
.full{cursor:pointer;border-bottom:1px dotted var(--muted)}.full:hover{border-bottom-style:solid}
#full-dialog{padding:0;border:1px solid var(--line);border-radius:calc(12px*var(--scale));background:var(--card);color:var(--ink);width:min(calc(900px*var(--scale)),92vw);max-height:86vh}
#full-dialog::backdrop{background:rgba(0,0,0,.55)}
.full-box{display:flex;flex-direction:column;max-height:86vh;padding:calc(14px*var(--scale)) calc(16px*var(--scale))}
.full-head{display:flex;align-items:center;gap:calc(10px*var(--scale))}.full-head h2{font-size:calc(16px*var(--scale));margin:0;flex:1}
#full-text{margin:calc(10px*var(--scale)) 0;padding:calc(10px*var(--scale)) calc(12px*var(--scale));max-height:68vh;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;
font:calc(14px*var(--scale))/1.6 system-ui,"Segoe UI","Yu Gothic UI","Hiragino Sans",sans-serif;background:var(--bg);border:1px solid var(--line);border-radius:calc(8px*var(--scale));
scrollbar-width:auto;scrollbar-color:var(--muted) var(--bg)}
.full-note{margin:0;color:var(--muted);font-size:calc(12px*var(--scale))}
footer{color:var(--muted);font-size:calc(13px*var(--scale));padding:calc(4px*var(--scale)) calc(20px*var(--scale)) calc(24px*var(--scale))}footer p{margin:calc(6px*var(--scale)) 0}code{font-size:calc(12px*var(--scale))}
@media (max-width:420px){main,.top,footer{padding-left:calc(16px*var(--scale));padding-right:calc(16px*var(--scale))}.grid{grid-template-columns:1fr}}
"""

JS = """(function(){
var fail=document.getElementById('fail'),board=document.getElementById('board');
var meta=document.querySelector('meta[name="board-version"]'),version=meta?meta.content:'';
var KEY='board-filter',filter='';
try{filter=localStorage.getItem(KEY)||''}catch(e){}
function applyFilter(){
  if(filter)document.body.dataset.filter=filter;else delete document.body.dataset.filter;
  board.querySelectorAll('[data-filter]').forEach(function(b){b.setAttribute('aria-pressed',String(b.dataset.filter===filter))})}
function setFilter(f){filter=(f===filter)?'':f;try{if(filter)localStorage.setItem(KEY,filter);else localStorage.removeItem(KEY)}catch(e){}applyFilter()}
var last=Date.now(),listOpen=false,busy=false;
function openMenu(){return board.querySelector('.menu:not([hidden])')}
function closeMenus(focusBack){board.querySelectorAll('.menu:not([hidden])').forEach(function(m){m.hidden=true;
  var b=m.parentNode.querySelector('.more');b.setAttribute('aria-expanded','false');if(focusBack)b.focus()})}
function keepOpen(){var d=document.getElementById('hidden-list');if(d&&listOpen)d.open=true}
// 差し替えの後も、キーボードで選んでいたボタンに戻す（5 秒ごとに選んでいる場所が外れないように）
function focusSig(){var a=document.activeElement;if(!a||a===document.body||!board.contains(a))return null;
  return [a.className,a.dataset.key||'',a.dataset.group||'',a.dataset.act||'',a.dataset.filter||''].join('\u0001')}
function refocus(sig){if(!sig)return;var els=board.querySelectorAll('button,summary');
  for(var i=0;i<els.length;i++){var e=els[i];
    if([e.className,e.dataset.key||'',e.dataset.group||'',e.dataset.act||'',e.dataset.filter||''].join('\u0001')===sig){e.focus();return}}}
// 5 秒ごとの差し替えで並びが変わっても、見ている所が飛ばないように: 下を見ている時は、見ているグループの画面の上の位置を保つ。
// いちばん上を見ている時は保たない（上に来たグループが見えるように）。順が変わったグループは、しばらく縁取りで知らせる
function groupOrder(){return [].map.call(board.querySelectorAll('details.group'),function(g){return g.dataset.group})}
function anchorNow(){if(window.scrollY<10)return null;var y=window.innerHeight*0.3,gs=board.querySelectorAll('details.group'),first=null;
  for(var i=0;i<gs.length;i++){var r=gs[i].getBoundingClientRect();if(r.bottom<=0)continue;if(!first)first={id:gs[i].dataset.group,top:r.top};
    if(r.top<=y&&r.bottom>=y)return {id:gs[i].dataset.group,top:r.top}}  // 画面の上から 3 割の所にあるグループを、見ている所とする
  return first}
function keepPlace(a,before){var after=groupOrder();
  if(a){var g=null,gs=board.querySelectorAll('details.group');for(var i=0;i<gs.length;i++)if(gs[i].dataset.group===a.id)g=gs[i];
    if(g)window.scrollBy(0,g.getBoundingClientRect().top-a.top)}
  if(before.join('|')===after.join('|'))return;
  board.querySelectorAll('details.group').forEach(function(g){if(before.indexOf(g.dataset.group)!==after.indexOf(g.dataset.group)){
    g.classList.add('moved');setTimeout(function(){g.classList.remove('moved')},4000)}})}
var dialog=document.getElementById('full-dialog'),opener=null;
function fullOpen(){return dialog&&dialog.open}
function showFull(el){
  var kind=el.dataset.full,title=kind==='prompt'?'最後に頼んだこと（全文）':'返事（全文）';
  fetch('/text?card='+encodeURIComponent(el.dataset.card)+'&kind='+kind,{cache:'no-store',headers:{'X-Session-Board':'1'}})
  .then(function(r){if(!r.ok)return r.text().then(function(t){throw new Error(t||r.status)});return r.json()})
  .then(function(d){opener=el;document.getElementById('full-title').textContent=title;
    var pre=document.getElementById('full-text');pre.textContent=d.text;pre.scrollTop=0;  // 文字のまま（HTML として描かない）
    document.getElementById('full-omitted').textContent=d.omitted?('以下 '+d.omitted+' 字を省いた。'):'';
    dialog.showModal();document.getElementById('full-close').focus()})
  .catch(function(e){fail.textContent='全文を取れなかった（'+e.message+'）';fail.hidden=false})}
if(dialog){
  document.getElementById('full-close').addEventListener('click',function(){dialog.close()});
  dialog.addEventListener('click',function(ev){if(ev.target===dialog)dialog.close()});  // 外（暗い所）を押すと閉じる。Esc は dialog が閉じる
  dialog.addEventListener('close',function(){var id=opener&&opener.dataset.card,kind=opener&&opener.dataset.full;
    if(opener&&document.body.contains(opener))opener.focus();
    else if(id){var e=board.querySelector('[data-full="'+kind+'"][data-card="'+CSS.escape(id)+'"]');if(e)e.focus()}  // 閉じたら元の所へ
    opener=null})}
function tick(){
  if(busy||openMenu()||fullOpen())return;  // 送っている間・メニューや全文を開いている間は差し替えない
  fetch('/cards',{cache:'no-store'}).then(function(r){if(!r.ok)throw new Error(r.status);
    var v=r.headers.get('X-Board-Version');if(version&&v&&v!==version){location.reload();throw new Error('reload')}  // 画面のコードが変わったら読み直す
    return r.text()})
  .then(function(html){var sig=focusSig(),a=anchorNow(),before=groupOrder();board.innerHTML=html;keepOpen();applyFilter();keepPlace(a,before);refocus(sig);last=Date.now();fail.hidden=true})
  .catch(function(e){if(e.message==='reload')return;var t=new Date(last);fail.textContent='新しくできない（'+t.toLocaleTimeString('ja-JP')+' の時のまま）';fail.hidden=false})}
applyFilter();setInterval(tick,5000);
function send(body,el){busy=true;if(el)el.disabled=true;
  return fetch('/prefs',{method:'POST',cache:'no-store',headers:{'Content-Type':'application/json','X-Session-Board':'1'},body:JSON.stringify(body)})
  .then(function(r){if(!r.ok)return r.text().then(function(t){throw new Error(t||r.status)})})
  .then(function(){busy=false;tick()})
  .catch(function(e){busy=false;fail.textContent='変えられなかった（'+e.message+'）';fail.hidden=false;if(el)el.disabled=false})}
board.addEventListener('toggle',function(ev){var d=ev.target;
  if(d.id==='hidden-list'){listOpen=d.open;return}
  if(!d.classList||!d.classList.contains('group'))return;
  if(String(+d.open)===d.dataset.open)return;  // 書き出した時のままなら送らない（開いた形で作られた時も toggle が来る）
  d.dataset.open=String(+d.open);send({action:'fold',group:d.dataset.group,open:d.open})},true);
board.addEventListener('keydown',function(ev){var o=ev.target.closest&&ev.target.closest('[data-full]');
  if(o&&(ev.key==='Enter'||ev.key===' ')){ev.preventDefault();showFull(o)}});
board.addEventListener('click',function(ev){
  var o=ev.target.closest('[data-full]');if(o){showFull(o);return}
  var f=ev.target.closest('[data-filter]');if(f){setFilter(f.dataset.filter);return}
  var more=ev.target.closest('.more');
  if(more){var m=more.parentNode.querySelector('.menu'),was=!m.hidden;closeMenus(false);
    if(!was){m.hidden=false;more.setAttribute('aria-expanded','true');var first=m.querySelector('[role=menuitem]');if(first)first.focus()}return}
  var b=ev.target.closest('button[data-act]');if(!b)return;
  if(b.dataset.act==='rename'){ev.preventDefault();  // 見出しの中の鉛筆。押しても畳まない
    var n=window.prompt('グループの名前（40 字まで）',b.dataset.name||'');if(n===null||!n.trim())return;
    send({action:'rename',group:b.dataset.group,name:n.trim()},b);return}
  if(b.dataset.act==='move'){var body={action:'move',key:b.dataset.key,group:b.dataset.group};
    if(b.dataset.group==='new'){var n2=window.prompt('新しいグループの名前（40 字まで）','');if(n2===null||!n2.trim()){closeMenus(true);return}body.name=n2.trim()}
    closeMenus(false);send(body,null);return}
  closeMenus(false);send({action:b.dataset.act,key:b.dataset.key},b)});
document.addEventListener('click',function(ev){if(!ev.target.closest('.menu-wrap'))closeMenus(false)});  // メニューの外を押すと閉じる
document.addEventListener('keydown',function(ev){var m=openMenu();if(!m)return;
  if(ev.key==='Escape'){ev.preventDefault();closeMenus(true);return}
  if(ev.key==='Tab'){closeMenus(false);return}
  if(ev.key==='ArrowDown'||ev.key==='ArrowUp'){ev.preventDefault();
    var items=[].slice.call(m.querySelectorAll('[role=menuitem]')),i=items.indexOf(document.activeElement);
    i=ev.key==='ArrowDown'?(i+1)%items.length:(i-1+items.length)%items.length;items[i].focus()}});
})();
"""

VERSION = hashlib.sha256((CSS + JS).encode()).hexdigest()[:12]  # 開いているページが、画面のコードの変わり目に気づくため
