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

# このパネルの定義の名前。配布版（install.cmd）は RAGReelTutorial、開発用の手動配置（deploy_panels.py --pypanel）は RAGChatBot。
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
