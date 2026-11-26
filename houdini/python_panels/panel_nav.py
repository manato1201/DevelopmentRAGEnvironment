"""
panel_nav.py — パネルの画面構成（常時のタブと、メニュー（≡）の中身）と、「別ウィンドウで開く」（Qt に依存しない。単体テストできる）

背景（2026-11-17の実証実験の感想）:
  ・タブを切り替えると別のタブが見られず、並行して見られない
  ・接続などの設定のタブが、ふだん使うタブと同じ比重で並んで目立つ
  → ふだん使わない画面（履歴・接続・設定・デバッグ）は、右上のメニュー（≡）の中に移す。
    並べて見たいときは、パネルをもう 1 つ別ウィンドウで開く（Houdini のペインを分けて、もう 1 つ開く方法でもよい）。

  ・MAIN_TABS / SUB_PAGES … 画面の構成（rag_chatbot.py が、これを見て組み立てる）
  ・visible_sub_pages()    … メニュー（≡）に出す項目（設定・デバッグは、設定者だけ）
  ・open_in_new_window()   … hou で、パネルを別ウィンドウ（フローティング）で開く。hou が無い・失敗のときは、理由を返す
  ・PARALLEL_VIEW_HELP     … 「並べて見る方法」の案内文
"""

from __future__ import annotations

# 常時のタブ。（キー, 見出し）。課題は、実証実験に参加するときだけ出る（rag_chatbot 側で切り替え）。
MAIN_TABS = (
    ("help", "はじめに"),
    ("chat", "Chat"),
    ("guide", "Guide"),
    ("tutorial", "Tutorial"),
    ("reference", "Reference"),
    ("video", "Movie"),
)

# 「はじめに」は、文字ではなくアイコン（本）だけのタブにする。Chat・Guide・Tutorial・Movie と同じ重さで並ぶと、毎回見るタブに見えるため
# （2026-11-18）。見出しは、ツールチップ・読み上げ用の名前に使う。
ICON_TABS = {"help": "book"}


# メニュー（≡）の中の画面。（キー, メニューの文, 画面の見出し, 設定者だけか）
SUB_PAGES = (
    ("history", "保存したチュートリアル（History）", "History（保存したチュートリアル）", False),
    ("connection", "接続・アカウント", "接続・アカウント", False),
    ("settings", "設定（設定者向け）", "設定", True),
    ("debug", "デバッグ（設定者向け）", "デバッグ", True),
)

# このパネルの定義の名前。配布版（install.cmd）も開発用のパッケージ（deploy_panels.py）も RAGReelTutorial。RAGChatBot は、以前のコピー方式の名残。
PANEL_INTERFACE_NAMES = ("RAGReelTutorial", "RAGChatBot")

PARALLEL_VIEW_HELP = (
    "別のタブを並べて見るには、パネルをもう 1 つ開きます。\n"
    "\n"
    "1. メニュー（≡）の「このパネルを別ウィンドウで開く」を選ぶ（新しいウィンドウに、もう 1 つのパネルが出ます）。\n"
    "2. または、Houdini のペインを分ける: ペインのメニューから「Split left/right」または「Split top/bottom」を選び、"
    "分けた側のペインのタブバーの、新しいタブのアイコンから「RAGReel Tutorial」をもう一度選びます。"
    "（Houdini の公式ドキュメント「Panes」の、Split a pane into two new panes と Create a new tab の項目）\n"
    "3. または、Houdini のメニューの Windows → New floating panel で、浮かぶウィンドウを作り、そこに「RAGReel Tutorial」を開く"
    "（2 台目のモニターに置くときに便利です）。\n"
    "\n"
    "それぞれのパネルは、別々に動きます。たとえば、片方で Guide を見ながら、もう片方で Chat に質問できます。\n"
    "Guide の「ノードの説明」と、Reference の「使っている手順」は、別のパネルが見えているときは、そちらのパネルで開きます"
    "（Guide を見たまま、もう片方が Reference に切り替わります）。メニュー（≡）の「ほかのパネルがあるとき、そちらで開く」で、オフにできます。\n"
    "接続先・キー・保存先などの設定は、同じ設定ファイルを使うので、どちらで変えても共通です"
    "（ほかのパネルで変えた設定は、そのパネルを開き直すと反映されます）。"
)


def visible_sub_pages(is_setup: bool) -> list[str]:
    """メニュー（≡）に出す画面のキー。設定・デバッグは、設定者（admin / editor / Local モード）だけ。"""
    return [key for key, _label, _title, setup_only in SUB_PAGES if is_setup or not setup_only]


def sub_page_title(key: str) -> str:
    for page_key, _label, title, _setup in SUB_PAGES:
        if page_key == key:
            return title
    return key


def open_in_new_window(hou_module=None, interface_names: tuple[str, ...] = PANEL_INTERFACE_NAMES) -> tuple[bool, str]:
    """パネルを、別ウィンドウ（フローティングのペイン）でもう 1 つ開く。戻り値は (成功したか, 失敗の理由)。

    使うのは、hou.ui.curDesktop().createFloatingPaneTab / hou.pypanel.interfaceByName / PythonPanel.setActiveInterface。
    実機の Houdini で未確認（2026-11-17。実機が無かった）。失敗しても、例外は出さず、理由を返す（呼び出し側が、手動の案内を出す）。
    """
    hou = hou_module
    if hou is None:
        try:
            import hou  # type: ignore[no-redef]
        except ImportError:
            return False, "Houdini の中でだけ使えます"
    try:
        interface = None
        for name in interface_names:
            interface = hou.pypanel.interfaceByName(name)
            if interface is not None:
                break
        if interface is None:
            return False, "パネルの定義が見つかりません（install.cmd をもう一度実行してください）"
        tab = hou.ui.curDesktop().createFloatingPaneTab(hou.paneTabType.PythonPanel)
        tab.setActiveInterface(interface)
        return True, ""
    except Exception as exc:  # noqa: BLE001 -- hou のエラーは、種類が多い。利用者には、理由を短く返す
        return False, f"{exc.__class__.__name__}: {exc}"


# ── キー 1 つで、浮かぶパネルを開く・閉じる（2026-11-21） ─────────────────────────────

FLOAT_TOOL_NAME = "ragreel_float"                                  # シェルフツールの名前（houdini/package/houdini/toolbar/ragreel_tutorial.shelf）
FLOAT_HOTKEY_SYMBOL = "h.pane.wsheet.tool:" + FLOAT_TOOL_NAME      # ネットワークビューで、このシェルフツールにキーを割り当てるときの名前
FLOAT_HOTKEY_CONTEXT = "h.pane.wsheet"
FLOAT_HOTKEY_CANDIDATES = ("alt+p", "ctrl+shift+p")                # Shift+P は、付箋（Add Sticky Note）が使っている。p は、パラメータ画面
FLOAT_SIZE = (560, 680)


def _interface_name(tab) -> str:
    try:
        return str(tab.activeInterface().name())
    except Exception:  # noqa: BLE001 -- Python パネル以外のタブ
        return ""


def find_floating(hou_module, interface_names: tuple[str, ...] = PANEL_INTERFACE_NAMES) -> list:
    """いま開いている、浮かぶ RAGReel のパネル（ペインタブ）。"""
    found = []
    for tab in hou_module.ui.curDesktop().paneTabs():
        try:
            if tab.type() == hou_module.paneTabType.PythonPanel and tab.isFloating() and _interface_name(tab) in interface_names:
                found.append(tab)
        except Exception:  # noqa: BLE001
            continue
    return found


def toggle_floating(hou_module=None, position: tuple | None = None, interface_names: tuple[str, ...] = PANEL_INTERFACE_NAMES) -> tuple[bool, str]:
    """浮かぶパネルが開いていれば閉じ、無ければ、マウスの近くに開く。戻り値は (成功したか, 画面に出す 1 文)。
    ネットワークビューの p（パラメータ画面）と同じ感覚で、キー 1 つで出し入れするためのもの。
    p の画面そのものには出せない（Houdini の専用の窓で、別の部品に替えられない）。実機で未確認（2026-11-21）。"""
    hou = hou_module
    if hou is None:
        try:
            import hou  # type: ignore[no-redef]
        except ImportError:
            return False, "Houdini の中でだけ使えます"
    try:
        existing = find_floating(hou, interface_names)
        if existing:
            for tab in existing:
                tab.close()
            return True, "浮かぶパネルを閉じました"
        interface = next((n for n in interface_names if hou.pypanel.interfaceByName(n) is not None), "")
        if not interface:
            return False, "パネルの定義が見つかりません（install.cmd をもう一度実行してください）"
        kwargs = {"size": FLOAT_SIZE, "python_panel_interface": interface}
        if position:
            kwargs["position"] = tuple(float(v) for v in position)
        hou.ui.curDesktop().createFloatingPaneTab(hou.paneTabType.PythonPanel, **kwargs)
        return True, "浮かぶパネルを開きました（もう一度押すと閉じます）"
    except Exception as exc:  # noqa: BLE001
        return False, f"{exc.__class__.__name__}: {exc}"


def ensure_float_hotkey(hou_module=None, done: bool = False, candidates: tuple[str, ...] = FLOAT_HOTKEY_CANDIDATES) -> tuple[str, str]:
    """シェルフツールに、キーを 1 つ割り当てる（ほかの割り当てと重ならないもの。すでに何か割り当ててあれば、何もしない）。
    戻り値: (状態, 説明)。状態: "assigned"（割り当てた）/ "exists"（すでにある）/ "skipped"（done が真）/ "failed"（できなかった。説明に理由）。
    hou.hotkeys は、Houdini の画面があるときだけ使える。シェルフツールが未登録だと、割り当ては False を返す。"""
    if done:
        return "skipped", ""
    hou = hou_module
    if hou is None:
        try:
            import hou  # type: ignore[no-redef]
        except ImportError:
            return "failed", "Houdini の中でだけ使えます"
    try:
        hotkeys = hou.hotkeys
        if list(hotkeys.assignments(FLOAT_HOTKEY_SYMBOL)):
            return "exists", ""
        for key in candidates:
            if list(hotkeys.findConflicts(FLOAT_HOTKEY_CONTEXT, key)):
                continue
            if hotkeys.addAssignment(FLOAT_HOTKEY_CONTEXT, FLOAT_HOTKEY_SYMBOL, key):
                hotkeys.saveOverrides()
                return "assigned", key
        return "failed", "割り当てられるキーが見つからない、またはシェルフツールが未登録です（シェルフ「RAGReel」を確認してください）"
    except Exception as exc:  # noqa: BLE001
        return "failed", f"{exc.__class__.__name__}: {exc}"


FLOAT_HOTKEY_HELP = (
    "ネットワークビューで、キー 1 つで、浮かぶパネルを出し入れできます。\n"
    "\n"
    "・割り当てたキーは、パネルを開いたとき、自動で決まります（Alt+P。重なるときは Ctrl+Shift+P）。\n"
    "・変えるには: Houdini の Edit → Preferences → Hotkeys を開き、「Network Editor」の中の「Shelf Tool: RAGReel Tutorial」に、好きなキーを割り当てます。\n"
    "・キーを使わないときは、シェルフ「RAGReel」のボタンでも、同じことができます。\n"
    "\n"
    "p で出るパラメータ画面は、Houdini の専用の窓で、中身を別の部品に替えられないため、その画面の中には出せません。"
)
