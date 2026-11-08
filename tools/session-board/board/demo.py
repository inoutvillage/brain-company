"""作り物の中身のカード（画面の写し・試し用。本物の中身は入れない）。

場所とセッション名は、この PC の設定（会社のルート・TMUX_SESSION）から作る（自動のグループ分けが本物と同じに働くように）。
"""
from __future__ import annotations

import datetime as dt
import itertools

from .collect import DEPT_SESSION, SECRETARY_SESSION, Card, Codex, decide_color, has_decision_section, is_question, sort_key
from .groups import COMPANY_ROOT, DEV_ROOT

_calls = itertools.count(1)


def demo_source():
    now = int(dt.datetime.now().timestamp() * 1000)
    m = 60_000
    n = next(_calls)
    co, dev, dept, sec = COMPANY_ROOT, DEV_ROOT, DEPT_SESSION, SECRETARY_SESSION
    cards = [
        # 案件 · ExampleApps: 黄 2・青 1
        Card(key="claude-1", tmux_session="aipair-recipe-app-0123456789ab", cwd=f"{dev}/ExampleApps/recipe-app",
             name="recipe-app", place="aipair-recipe-app:claude", hide_key="tmux:aipair-recipe-app:#0", path="Example/recipe-app",
             notice_driven=False, status="waiting", waiting_for="permission prompt",
             prompt="検索の結果を 20 件ずつに分けて出して", prompt_ms=now - 6 * m,
             reply="ページ分けの部品を足します。テストを流す許可をください", progress=(12, 5, 1), last_ms=now - 2 * m,
             codex=Codex("idle", now - 9 * m)),
        Card(key="claude-3", tmux_session="aipair-weather-bot-0123456789ab", cwd=f"{dev}/ExampleApps/weather-bot",
             name="weather-bot", place="aipair-weather-bot:claude", hide_key="tmux:aipair-weather-bot:#0", path="Example/weather-bot",
             notice_driven=False, status="busy", prompt="毎朝 7 時に天気を送る仕組みを作って", prompt_ms=now - 14 * m,
             reply=None, progress=(3, 6, 0), last_ms=now - n * 1000 % 50_000, codex=Codex("busy", now - m)),
        Card(key="claude-8", tmux_session="aipair-todo-web-0123456789ab", cwd=f"{dev}/ExampleApps/todo-web",
             name="todo-web", place="aipair-todo-web:claude", hide_key="tmux:aipair-todo-web:#0", path="Example/todo-web",
             notice_driven=False, status="idle", prompt="期限の近い順に並べて", prompt_ms=now - 12 * m,
             reply="期限の近い順に並べました。期限の無い物は一番下でよいですか？", progress=(8, 2, 0), last_ms=now - 10 * m),
        Card(key="claude-12", tmux_session="aipair-shop-app-0123456789ab", cwd=f"{dev}/ExampleApps/shop-app",
             name="shop-app", place="aipair-shop-app:claude", hide_key="tmux:aipair-shop-app:#0", path="Example/shop-app",
             notice_driven=False, status="idle", prompt="見積もりの画面を作って", prompt_ms=now - 18 * m,
             reply="見積もりの画面を作り、試しが通りました。", progress=(9, 3, 0), last_ms=now - 15 * m),
        # 案件 · ExampleMedia: 黄 1・灰 1
        Card(key="claude-7", tmux_session="aipair-old-notes-0123456789ab", cwd=f"{dev}/ExampleMedia/old-notes",
             name="old-notes", place="aipair-old-notes:claude", hide_key="tmux:aipair-old-notes:#0", path="Example/old-notes",
             notice_driven=False, status="idle", last_ms=now - 30 * m,
             problems={"prompt": "依頼の形が知っている形と違う"}),
        Card(key="claude-6", tmux_session="aipair-photo-tool-0123456789ab", cwd=f"{dev}/ExampleMedia/photo-tool",
             name="photo-tool", place="aipair-photo-tool:claude", hide_key="tmux:aipair-photo-tool:#0", path="Example/photo-tool",
             notice_driven=False, status="idle", prompt="写真の向きを自動で直して", prompt_ms=now - 3 * 1440 * m,
             reply="向きを直す処理を足し、テストが通りました。", progress=(20, 0, 0), last_ms=now - 3 * 1440 * m,
             codex=Codex("idle", now - 3 * 1440 * m)),
        # 会社: 青だけ（一時停止中は灰）
        Card(key="claude-2", tmux_session=sec, cwd=f"{co}/secretariat", name="秘書室", place=f"{sec}:secretariat",
             hide_key=f"tmux:{sec}:secretariat", path="Example/secretariat", notice_driven=False, status="busy",
             prompt="来週の予定を 3 つにまとめて", prompt_ms=now - 2 * m, reply=None, last_ms=now - m, session_id="s-2"),
        Card(key="claude-9", tmux_session=sec, cwd=f"{co}/secretariat", name="秘書室（一時停止中）",
             place=f"{sec}:secretariat", hide_key=f"tmux:{sec}:secretariat:stopped:9-1", path="Example/secretariat",
             notice_driven=False, status="idle", prompt="来週の予定を 3 つにまとめて", prompt_ms=now - 2 * m,
             reply=None, last_ms=now - 2 * 1440 * m, stopped=True, session_id="s-2",
             warn="動いているセッションと同じ会話。続けると記録が混ざる"),
        Card(key="claude-4", tmux_session=dept, cwd=f"{co}/development", name="開発部", place=f"{dept}:dev",
             hide_key=f"tmux:{dept}:dev", path="Example/development", notice_driven=True, status="busy",
             prompt="tickets/ に新しい実装チケットが届きました", prompt_ms=now - 40 * m,
             reply="チケットを読み、画面の見本を作り始めます。", progress=(46, 2, 0), last_ms=now - m),
        Card(key="claude-5", tmux_session=dept, cwd=f"{co}/product-management", name="PM 部", place=f"{dept}:pm",
             hide_key=f"tmux:{dept}:pm", path="Example/product-management", notice_driven=True, status="idle",
             prompt="reports/ に開発部からの報告が届きました", prompt_ms=now - 90 * m,
             reply="報告を確かめ、秘書室へ回しました。", last_ms=now - 85 * m),
        # 案件 · ExampleTools: 待機 1・灰 1
        Card(key="claude-11", tmux_session="aipair-memo-app-0123456789ab", cwd=f"{dev}/ExampleTools/memo-app",
             name="memo-app", place="aipair-memo-app:claude", hide_key="tmux:aipair-memo-app:#0", path="Example/memo-app",
             notice_driven=False, status="idle", prompt="メモに日付の欄を足して", prompt_ms=now - 25 * m,
             reply="日付の欄を足し、試しが通りました。", progress=(6, 0, 0), last_ms=now - 20 * m),
        Card(key="claude-10", tmux_session="aipair-label-maker-0123456789ab", cwd=f"{dev}/ExampleTools/label-maker",
             name="label-maker", place="aipair-label-maker:claude", hide_key="tmux:aipair-label-maker:#0", path="Example/label-maker",
             notice_driven=False, status="idle", prompt="宛名のラベルを A4 に並べて", prompt_ms=now - 2 * 1440 * m,
             reply="A4 に 12 枚並べる形にしました。", last_ms=now - 2 * 1440 * m),
    ]
    long_reply = "\n\n".join(
        [f"{i}. 天気を送る仕組みの段取り {i}: 予報を取り、短い文にまとめ、朝 7 時に送る。失敗した時は 10 分後にもう一度だけ送る。" for i in range(1, 41)]
        + ["試しの鍵の形（作り物）: sk-ant-" + "x" * 32, "画面に出す時は文字のまま: <script>alert(1)</script>",
           "以上の段取りで進めます。気になる所があれば教えてください。"])
    for c in cards:
        c.full_text = {"prompt": c.prompt, "reply": c.reply}
        if c.name == "weather-bot":
            c.full_text = {"prompt": c.prompt + "\n\n" + "\n".join(f"- 条件 {i}: 雨の日は傘の一言を足す" for i in range(1, 6)),
                           "reply": long_reply}
            c.reply = "段取りを 40 に分けてまとめました。"
    for c in cards:
        if c.name == "shop-app":  # 決めごとの節で終わる返事（問いの言い方は無い）
            c.full_text["reply"] = ("見積もりの画面を作り、試しが通りました。\n\n## 提案\n\n合計の下に、税の内訳を出すと見やすくなります。\n\n"
                                    "## まだ決まっていないこと\n\n1. 端数を切り上げるか、切り捨てるか\n2. 見積もりの有効期限を何日にするか\n"
                                    "3. 宛名に「様」を付けるか")
        c.asks = is_question((c.full_text or {}).get("reply"))
        c.decides = has_decision_section((c.full_text or {}).get("reply"))
        decide_color(c, now)
    cards.sort(key=sort_key)
    return cards, [], now
