"""ブラウザ（Playwright の Chromium・一時の置き場）で、画面の動きを確かめる。作り物の中身（demo.py）だけを使う。
Playwright が無ければ飛ばす"""
import os
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from board import render, server  # noqa: E402
from board.demo import demo_source  # noqa: E402

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None


@unittest.skipIf(sync_playwright is None, "Playwright が無い")
class BrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.real_state = server.STATE_DIR
        server.STATE_DIR = os.path.join(cls.tmp.name, "log")  # 失敗の記録も一時の場所へ
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        server.STATE_DIR = cls.real_state
        cls.tmp.cleanup()

    def setUp(self):
        self.state = tempfile.mkdtemp(dir=self.tmp.name)
        self.srv = server.make_server(0, demo_source, state_dir=self.state)
        self.port = self.srv.server_address[1]
        self.srv.allowed_hosts = {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.ctx = self.browser.new_context(color_scheme="dark")
        self.page = self.ctx.new_page()
        self.page.goto(f"http://127.0.0.1:{self.port}/")
        self.page.wait_for_selector(".groups")

    def tearDown(self):
        self.ctx.close()
        self.srv.shutdown()
        self.srv.server_close()

    def wait(self, fn, sec=8):
        end = time.time() + sec
        while time.time() < end:
            try:
                if fn():
                    return True
            except Exception:  # 読み直しの途中など、まだ問い合わせられない時は「まだ」
                pass
            time.sleep(0.2)
        return False

    def visible(self, sel):
        return self.page.locator(sel).evaluate_all("els => els.filter(e => e.offsetParent !== null).length")

    def open_all_groups(self):
        """畳んであるグループを全部開き、開いた形がサーバーに残って画面に出るまで待つ"""
        p = self.page
        while p.locator("details.group:not([open])").count():
            p.locator("details.group:not([open]) > summary .gname").first.click()
        self.assertTrue(self.wait(lambda: p.locator('details.group[data-open="0"]').count() == 0
                                  and p.locator("details.group:not([open])").count() == 0))

    def test_chip_filter_works_and_is_remembered(self):
        p = self.page
        self.open_all_groups()
        total = p.locator("article.card").count()
        self.assertTrue(self.wait(lambda: self.visible("article.card") == total))  # 絞り込みなしでは全部見える
        p.click('button[data-filter="yellow"]')
        self.assertEqual(p.get_attribute('button[data-filter="yellow"]', "aria-pressed"), "true")
        self.assertTrue(self.wait(lambda: self.visible("article.card") == self.visible("article.card.yellow") > 0))
        self.assertEqual(self.visible("details.group"), self.visible("details.group.has-yellow"))  # 黄の無いグループは出さない
        p.reload()
        p.wait_for_selector(".groups")
        self.assertEqual(p.get_attribute('button[data-filter="yellow"]', "aria-pressed"), "true")  # 開き直しても残る
        p.click('button[data-filter="yellow"]')  # もう一度押すと全部
        self.assertTrue(self.wait(lambda: self.visible("article.card") == p.locator("article.card").count()))
        p.click('button[data-filter="blue"]')
        self.assertTrue(self.wait(lambda: self.visible("article.card") == self.visible("article.card.blue") > 0))

    def test_menu_opens_with_keyboard_and_closes_with_escape_and_outside(self):
        p = self.page
        more = p.locator("details.group[open] article.card .more").first
        more.focus()
        p.keyboard.press("Enter")
        self.assertEqual(more.get_attribute("aria-expanded"), "true")
        self.assertTrue(p.evaluate("document.activeElement.getAttribute('role') === 'menuitem'"))
        p.keyboard.press("ArrowDown")
        self.assertTrue(p.evaluate("document.activeElement.getAttribute('role') === 'menuitem'"))
        p.keyboard.press("Escape")
        self.assertEqual(more.get_attribute("aria-expanded"), "false")
        self.assertEqual(self.visible(".menu"), 0)
        self.assertTrue(p.evaluate("document.activeElement.classList.contains('more')"))  # ⋯ に戻る
        more.click()
        self.assertEqual(self.visible(".menu"), 1)
        p.click("h1")  # メニューの外
        self.assertEqual(self.visible(".menu"), 0)

    def test_keyboard_focus_survives_the_automatic_refresh(self):
        p = self.page
        more = p.locator("details.group[open] article.card .more").nth(1)
        key = more.get_attribute("data-key")
        more.focus()
        p.evaluate("window.__marker = document.querySelector('#summary .stamp').textContent")
        self.assertTrue(self.wait(lambda: p.evaluate("document.querySelector('#summary .stamp').textContent !== window.__marker"),
                                  sec=8))  # 差し替えが 1 回あった
        self.assertEqual(p.evaluate("document.activeElement.classList.contains('more') && document.activeElement.dataset.key"), key)

    def test_menu_hide_move_and_pencil_rename(self):
        p = self.page
        card = p.locator("details.group[open] article.card").first
        name = card.locator("h2").inner_text()
        card.locator(".more").click()
        card.locator('[role=menuitem][data-act="hide"]').click()
        self.assertTrue(self.wait(lambda: p.locator("#hidden-list summary").inner_text().startswith("隠している 1")))
        card = p.locator("details.group[open] article.card").first
        name = card.locator("h2").inner_text()
        card.locator(".more").click()
        p.once("dialog", lambda d: d.accept("試しの組"))
        card.locator('[role=menuitem][data-group="new"]').click()
        self.assertTrue(self.wait(lambda: p.locator('details.group[data-group="user:1"] h2').all_inner_texts() == [name]))
        g = p.locator('details.group[data-group="user:1"]')
        p.once("dialog", lambda d: d.accept("<b>名前</b>"))
        g.locator(".edit").click()
        self.assertTrue(self.wait(lambda: g.locator(".gname").inner_text() == "<b>名前</b>"))  # 打った文字のまま
        self.assertEqual(g.get_attribute("data-open"), "1")  # 鉛筆を押しても畳まない

    def make_only_yellow(self, gid):
        """gid のグループのカードだけを黄にし、ほかを灰にする（並びを変える）"""
        from board import groups as g
        real = self.srv.board.source

        def changed():
            cards, notes, now = real()
            for c in cards:
                c.color, c.label = ("yellow", "l") if g.auto_group(c) == gid else ("gray", "l")
            return cards, notes, now
        self.srv.board.source = changed
        self.srv.board.snap = None

    def test_order_change_keeps_the_viewed_group_in_place_and_marks_moved_groups(self):
        p = self.page
        p.set_viewport_size({"width": 900, "height": 600})
        target = p.locator("details.group[open]").nth(1).get_attribute("data-group")
        sel = f'details.group[data-group="{target}"]'
        p.evaluate(f"document.querySelector('{sel}').scrollIntoView()")
        self.assertGreater(p.evaluate("window.scrollY"), 10)  # 下へ送ってある（上にいると、見ている所を保つ工夫は働かない）
        top_before = p.evaluate(f"document.querySelector('{sel}').getBoundingClientRect().top")
        self.make_only_yellow(target)
        self.assertTrue(self.wait(lambda: p.locator("details.group").first.get_attribute("data-group") == target, sec=8))
        top_after = p.evaluate(f"document.querySelector('{sel}').getBoundingClientRect().top")
        self.assertLess(abs(top_after - top_before), 3)  # 見ていたグループは、画面の同じ所にある
        self.assertGreater(p.locator("details.group.moved").count(), 0)  # 順が変わったグループを縁取りで知らせる

    def test_at_the_top_the_new_top_group_is_shown(self):
        p = self.page
        last = p.locator("details.group").last.get_attribute("data-group")
        self.make_only_yellow(last)
        self.assertTrue(self.wait(lambda: p.locator("details.group").first.get_attribute("data-group") == last, sec=8))
        self.assertLess(p.evaluate("window.scrollY"), 10)  # 上を見ていれば、上に来たグループが見える

    def test_demo_groups_are_in_order(self):
        names = self.page.locator("details.group .gname").all_inner_texts()
        self.assertEqual(names, ["案件 · ExampleApps", "会社", "案件 · ExampleMedia", "案件 · ExampleTools"])  # 黄 2 → 青 → 残り（待機・灰）
        self.page.click('button[data-filter="yellow"]')
        shown = self.page.locator("details.group").evaluate_all("gs => gs.filter(g => g.offsetParent !== null).map(g => g.dataset.group)")
        self.assertEqual(shown, ["auto:projects:ExampleApps"])  # 黄の丸では 1 の段だけ
        self.page.click('button[data-filter="yellow"]')
        self.page.click('button[data-filter="standby"]')
        shown = self.page.locator("details.group").evaluate_all("gs => gs.filter(g => g.offsetParent !== null).map(g => g.dataset.group)")
        self.assertEqual(shown, ["auto:projects:ExampleMedia", "auto:projects:ExampleTools"])  # 待機の丸もある

    def open_full(self, name, kind):
        card = self.page.locator("article.card").filter(has=self.page.locator("h2", has_text=name))
        card.locator(f'[data-full="{kind}"]').click()
        self.page.wait_for_selector("#full-dialog[open]")
        return card.locator(f'[data-full="{kind}"]')

    def pre(self, js):
        return self.page.evaluate(f"(() => {{ const p = document.getElementById('full-text'); return {js}; }})()")

    def test_short_text_opens_without_a_scroll_bar_and_esc_returns_focus(self):
        opener = self.open_full("recipe-app", "prompt")
        self.assertEqual(self.pre("p.textContent"), "検索の結果を 20 件ずつに分けて出して")
        self.assertTrue(self.pre("p.scrollHeight <= p.clientHeight"))
        self.page.keyboard.press("Escape")
        self.assertEqual(self.page.locator("#full-dialog[open]").count(), 0)
        self.assertTrue(opener.evaluate("e => e === document.activeElement"))  # 閉じたら元の所へ

    def test_long_text_scrolls_inside_and_is_shown_as_text(self):
        self.open_full("weather-bot", "reply")
        self.assertTrue(self.pre("p.scrollHeight > p.clientHeight"))
        self.page.evaluate("document.getElementById('full-text').scrollTop = 300")
        self.assertGreater(self.pre("p.scrollTop"), 0)  # 中で縦に送れる
        self.assertIn("<script>alert(1)</script>", self.pre("p.textContent"))
        self.assertEqual(self.pre("p.children.length"), 0)  # HTML として描いていない
        self.assertIn("<伏せた>", self.pre("p.textContent"))
        self.assertNotIn("xxxxxxxxxx", self.pre("p.textContent"))
        self.assertIn("伏せてあります", self.page.locator(".full-note").inner_text())

    def test_close_button_outside_click_and_keyboard_open(self):
        p = self.page
        self.open_full("recipe-app", "reply")
        p.click("#full-close")
        self.assertEqual(p.locator("#full-dialog[open]").count(), 0)
        self.open_full("recipe-app", "reply")
        p.mouse.click(5, 5)  # 暗い所（外）
        self.assertEqual(p.locator("#full-dialog[open]").count(), 0)
        card = p.locator("article.card").filter(has=p.locator("h2", has_text="recipe-app"))
        card.locator('[data-full="prompt"]').focus()
        p.keyboard.press("Enter")
        p.wait_for_selector("#full-dialog[open]")

    def test_refresh_does_not_close_the_dialog(self):
        p = self.page
        self.open_full("weather-bot", "reply")
        before = self.pre("p.textContent")
        stamp = p.evaluate("document.querySelector('#summary .stamp').textContent")
        time.sleep(6.5)  # 5 秒ごとの差し替えの時を過ぎる
        self.assertEqual(p.locator("#full-dialog[open]").count(), 1)
        self.assertEqual(self.pre("p.textContent"), before)
        self.assertEqual(p.evaluate("document.querySelector('#summary .stamp').textContent"), stamp)  # 開いている間は差し替えない

    def test_page_reloads_when_the_board_code_changes(self):
        p = self.page
        p.evaluate("window.__before = 1")
        old = render.VERSION
        try:
            render.VERSION = "changed-for-test"
            self.assertTrue(self.wait(lambda: p.evaluate("window.__before === undefined"), sec=10))
        finally:
            render.VERSION = old

    LOOK = """() => {
      const dpr = devicePixelRatio, px = s => parseFloat(getComputedStyle(document.querySelector(s)).fontSize) * dpr;
      const grid = document.querySelector('details.group[open] .grid'), cards = [...document.querySelectorAll('article.card')];
      return {columns: getComputedStyle(grid).gridTemplateColumns.split(' ').length,
              full: cards.filter(e => { const r = e.getBoundingClientRect(); return r.top >= 0 && r.bottom <= innerHeight; }).length,
              card_w: cards[0].getBoundingClientRect().width * dpr,
              chip: px('.card .chip'), time: px('.card .t'), count: px('.group > summary .count.small'), body: px('body')};
    }"""

    def look(self, width, height, zoom, scale=None):
        """幅・高さは画面の点の数。zoom はブラウザの拡大率、scale は --scale を置き換える時の値"""
        ctx = self.browser.new_context(color_scheme="dark", viewport={"width": round(width / zoom), "height": round(height / zoom)},
                                       device_scale_factor=zoom)
        try:
            p = ctx.new_page()
            p.goto(f"http://127.0.0.1:{self.port}/")
            p.wait_for_selector(".groups")
            if scale is not None:
                p.evaluate(f"document.documentElement.style.setProperty('--scale', '{scale}')")
            return p.evaluate(self.LOOK)
        finally:
            ctx.close()

    def test_scale_75_looks_like_the_browser_at_75_percent(self):
        """--scale:.75 は、ブラウザで 75% に縮めた時と同じ見え方になる（座標は 1 対 1 のまま）"""
        for w, h in ((1920, 945), (1080, 1785)):
            knob = self.look(w, h, 1, scale=.75)
            zoom = self.look(w, h, 0.75, scale=1)  # ふつうの大きさを、ブラウザで 75% に縮めた形
            self.assertEqual(knob["columns"], zoom["columns"], (w, knob, zoom))  # 1 行に並ぶ数
            self.assertEqual(knob["full"], zoom["full"], (w, knob, zoom))  # 1 画面に入る数
            self.assertAlmostEqual(knob["card_w"], zoom["card_w"], delta=2)
            for k in ("chip", "time", "count", "body"):
                self.assertAlmostEqual(knob[k], zoom[k], places=2)

    def test_smallest_text_is_12px_and_the_knob_changes_everything(self):
        p = self.page
        size = lambda s: p.evaluate(f"parseFloat(getComputedStyle(document.querySelector('{s}')).fontSize)")  # noqa: E731
        for s in (".card .chip", ".card .t", ".group > summary .count.small", ".card .where", "footer code"):
            self.assertEqual(size(s), 12, s)  # 色の丸の言い方・時刻・見出しの数などの、いちばん小さい字（既定の 100%）
        self.assertEqual(size("body"), 15)
        p.evaluate("document.documentElement.style.setProperty('--scale', '.75')")
        self.assertEqual(size(".card .chip"), 9)  # 1 か所を変えると、全部が同じ割合で変わる
        self.assertEqual(size("body"), 11.25)


if __name__ == "__main__":
    unittest.main()
