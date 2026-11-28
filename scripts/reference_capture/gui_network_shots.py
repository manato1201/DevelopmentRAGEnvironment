"""Reference のノード図を、実際のネットワークエディタの画面で撮る（2026-11-28）。Houdini の画面（GUI）の中で動かす。

  uv run python scripts/reference_capture/run_gui_network_shots.py [--only sop/vellumsolver,...]
  （Houdini を、この撮影だけのために起動する。終わると、Houdini は閉じる）

hython には画面が無く、ネットワークエディタを撮れない。そこで、Houdini の画面を起動し、起動時のスクリプト（123.py）から、
撮影のレシピと同じ作り方でネットワークを組み（dump_conditions.conditions_for）、ネットワークエディタのペインを、
hou.NetworkEditor.qtScreenGeometry() の矩形で画面から切り出す（screen_capture._grab_with_retry。生成の撮影と同じ方法）。
  ・適用前の画像を並べるためだけのノード（表示するノードに届かないもの）は、撮る前に消す（作らなくてよいものを、映さない）
  ・表示フラグを、表示するノードに付け、ノードを並べ（layoutChildren）、ノードの範囲に合わせて映し、余白を切り詰める
  ・前の図（ポートの名前つきの図）は node_ports.png として残す
環境変数 REF_GUI_ONLY（カンマ区切りのキー）で、撮るものを絞れる。結果は build/gui_network_shots.log。
"""

import json
import os
import sys
import time
import traceback
from pathlib import Path

import hou  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "houdini" / "python_panels"))

LOG = ROOT / "build" / "gui_network_shots.log"
MEDIA = Path(os.environ.get("REF_GUI_OUT") or (ROOT / "build" / "reference_media"))
MIN_VIEW_WIDTH = 7.0   # ネットワークの単位。ノードが少ないとき、巨大に映さない
LABEL_ROOM = 5.0       # ノードの右に出る名前（種類・名前）の分の幅
MAX_OUT_WIDTH = 1400


def log(text: str) -> None:
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(time.strftime("%H:%M:%S ") + text + "\n")


def _ancestors(nodes_by_name: dict, start: str) -> set:
    seen, stack = set(), [start]
    while stack:
        name = stack.pop()
        if name in seen or name not in nodes_by_name:
            continue
        seen.add(name)
        stack.extend(c["from"] for c in nodes_by_name[name].get("inputs") or [] if c.get("from"))
    return seen


def _find(name: str):
    for parent in [hou.node("/obj/ref"), hou.node("/stage")] + list(hou.node("/obj").children()):
        if parent is None:
            continue
        node = parent.node(name)
        if node is not None:
            return node
    return None


def _arrange(parent, by_name: dict, keep: set) -> None:
    """ノードを、つながりの深さで段に並べる（上から下へ。線が上に戻らない）。同じ段は、条件の順に左から。
    layoutChildren() は、ぶつかる相手（Collision）の球を、ソルバーより下に置き、線が上へ戻って読みにくかった。"""
    depth: dict = {}

    def level(name: str, trail: tuple = ()) -> int:
        if name in depth:
            return depth[name]
        if name in trail or name not in by_name:
            return 0
        sources = [c["from"] for c in by_name[name].get("inputs") or [] if c.get("from") in keep]
        depth[name] = 0 if not sources else 1 + max(level(s, trail + (name,)) for s in sources)
        return depth[name]

    rows: dict = {}
    for name in by_name:
        if name in keep:
            rows.setdefault(level(name), []).append(name)
    placed = 0
    for row, names in rows.items():
        for i, name in enumerate(names):
            node = parent.node(name)
            if node is None:
                continue
            node.setPosition(hou.Vector2((i - (len(names) - 1) / 2) * 3.6, -row * 1.25))
            placed += 1
    if not placed:
        try:
            parent.layoutChildren()
        except Exception:  # noqa: BLE001
            pass


def _grab(editor):
    """ネットワークエディタのペインを、画面から切り出す（qtScreenGeometry の矩形）。ほかのウィンドウが重なっていれば None。
    screen_capture._grab_network_pane と同じ重なりの検査をするが、「ほぼ単色」の検査はしない
    （ノードが 2〜3 個の小さなネットワークは、広いペインのほとんどが背景で、単色と判定されて撮れなかった。中身は _trim で確かめる）。"""
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication

    rect = editor.qtScreenGeometry()
    x, y, w, h = int(rect.x()), int(rect.y()), int(rect.width()), int(rect.height())
    if w < 200 or h < 120:
        return None
    windows = set()
    for fx in (0.08, 0.3, 0.5, 0.7, 0.92):
        for fy in (0.1, 0.35, 0.6, 0.9):
            widget = QApplication.widgetAt(QPoint(x + int(w * fx), y + int(h * fy)))
            if widget is None:
                return None
            windows.add(id(widget.window()))
    if len(windows) != 1:
        return None
    screen = QGuiApplication.screenAt(QPoint(x + w // 2, y + h // 2))
    if screen is None:
        return None
    origin = screen.geometry().topLeft()
    return screen.grabWindow(0, x - origin.x(), y - origin.y(), w, h).toImage()


def _close_start_dialogs() -> None:
    """起動時に出る「Start Here」などの小窓を閉じる（ネットワークエディタに重なり、撮れない）。"""
    from PySide6.QtWidgets import QApplication

    for widget in QApplication.topLevelWidgets():
        try:
            if widget.isVisible() and widget is not hou.qt.mainWindow() and "Start Here" in widget.windowTitle():
                widget.close()
                log(f"閉じた小窓: {widget.windowTitle()}")
        except Exception:  # noqa: BLE001
            continue
    QApplication.processEvents()


def _keep_on_top(on: bool) -> None:
    """撮るあいだだけ、Houdini の画面を最大化して、最前面に固定する（Windows）。終わったら戻す。"""
    try:
        import ctypes

        main = hou.qt.mainWindow()
        if on:
            main.showMaximized()
        hwnd = int(main.winId())
        flags = 0x0001 | 0x0002 | 0x0040  # SWP_NOSIZE | SWP_NOMOVE | SWP_SHOWWINDOW
        ctypes.windll.user32.SetWindowPos(hwnd, -1 if on else -2, 0, 0, 0, 0, flags)  # HWND_TOPMOST / HWND_NOTOPMOST
        if on:
            ctypes.windll.user32.SetForegroundWindow(hwnd)
        deadline = time.time() + (1.5 if on else 0.1)
        while time.time() < deadline:
            from PySide6.QtWidgets import QApplication

            QApplication.processEvents()
            time.sleep(0.05)
    except Exception as exc:  # noqa: BLE001
        log(f"最前面への固定に失敗: {exc!r}")


def _trim(image):
    """背景（左上の画素の色）と違う画素の範囲に、余白を付けて切り詰める。何も無ければ、そのまま。"""
    from PySide6.QtCore import Qt

    small = image.scaledToWidth(320, Qt.FastTransformation)
    bg = small.pixelColor(2, small.height() - 3)
    top = int(small.height() * 0.08)  # 上の道筋とメニューの帯は、範囲に入れない
    xs, ys = [], []
    for y in range(top, small.height()):
        for x in range(small.width()):
            c = small.pixelColor(x, y)
            if max(abs(c.red() - bg.red()), abs(c.green() - bg.green()), abs(c.blue() - bg.blue())) > 60:  # 透かしの文字（Geometry 等）は入れない
                xs.append(x)
                ys.append(y)
    if not xs:
        return image
    k = image.width() / small.width()
    pad = 28
    x0, y0 = max(0, int(min(xs) * k) - pad), max(0, int(min(ys) * k) - pad)
    x1, y1 = min(image.width(), int((max(xs) + 1) * k) + pad + 150), min(image.height(), int((max(ys) + 1) * k) + pad)
    return image.copy(x0, y0, x1 - x0, y1 - y0)


def shoot(editor, sc, dump, recipe: dict, cond: dict, target: Path) -> str:
    dump.conditions_for(recipe)  # 撮影と同じ作り方で組む（/obj/ref ほか）
    by_name = {n["name"]: n for n in cond.get("nodes") or []}
    display = _find(cond.get("display") or "")
    if display is None:
        return "表示するノードが見つかりません"
    keep = _ancestors(by_name, display.name())
    for name in list(by_name):
        if name not in keep:
            helper = _find(name)
            if helper is not None:
                helper.destroy()
    parent = display.parent()
    try:
        display.setDisplayFlag(True)
    except Exception:  # noqa: BLE001
        pass
    _arrange(parent, by_name, keep)
    editor.setPwd(parent)
    wait_until = time.time() + 3.0  # 開いた階層に切り替わるまで待つ（起動直後の 1 枚目が、/obj のまま撮れた）
    while editor.pwd().path() != parent.path() and time.time() < wait_until:
        sc._flush_qt_events()
        time.sleep(0.05)
    try:
        hou.clearAllSelected()  # 選んだノードがあると、パラメータの小窓がネットワークエディタに重なる
        editor.setCurrentNode(display, False)
        display.setSelected(False)
    except Exception:  # noqa: BLE001
        pass
    sc._flush_qt_events()
    children = list(parent.children())
    if not children:
        return "ネットワークが空です"
    xs0 = min(c.position()[0] for c in children)
    ys0 = min(c.position()[1] for c in children)
    xs1 = max(c.position()[0] + c.size()[0] for c in children)
    ys1 = max(c.position()[1] + c.size()[1] for c in children)
    cx, cy = (xs0 + xs1) / 2, (ys0 + ys1) / 2
    xs1 += LABEL_ROOM  # 名前は、ノードの右に出る（node.size() に入らない）
    cx, cy = (xs0 + xs1) / 2, (ys0 + ys1) / 2
    half_w = max(MIN_VIEW_WIDTH, xs1 - xs0 + 1.2) / 2
    half_h = max(MIN_VIEW_WIDTH * 0.4, ys1 - ys0 + 1.2) / 2
    editor.setVisibleBounds(hou.BoundingRect(cx - half_w, cy - half_h, cx + half_w, cy + half_h))
    sc._flush_qt_events()
    deadline = time.time() + (0.6 if editor.pwd().path() == parent.path() else 2.0)
    while time.time() < deadline:
        sc._flush_qt_events()
        time.sleep(0.05)
    image = None
    for _attempt in range(4):
        image = _grab(editor)
        if image is not None:
            break
        time.sleep(0.4)
        sc._flush_qt_events()
    if image is None:
        try:  # 何が重なっているかを、あとで確かめるため（画面全体の 1 枚と、重なっている部品の種類）
            from PySide6.QtCore import QPoint
            from PySide6.QtGui import QGuiApplication
            from PySide6.QtWidgets import QApplication

            QGuiApplication.primaryScreen().grabWindow(0).save(str(LOG.with_name("gui_debug.png")), "PNG")
            rect = editor.qtScreenGeometry()
            for fx, fy in ((0.08, 0.1), (0.5, 0.5), (0.92, 0.9)):
                w = QApplication.widgetAt(QPoint(rect.x() + int(rect.width() * fx), rect.y() + int(rect.height() * fy)))
                log(f"  widgetAt({fx},{fy}) = {type(w).__name__ if w is not None else None} / {w.window().windowTitle() if w is not None else ''}")
        except Exception as exc:  # noqa: BLE001
            log(f"  debug failed {exc!r}")
        return "ネットワークエディタを撮れませんでした"
    full_w, full_h = image.width(), image.height()
    image = _trim(image)
    for _retry in range(3):
        # 切り詰めがペインのほぼ全体のまま = ノードが描かれていない（起動直後の 1 枚目で、空の /obj が撮れた）。待って撮り直す
        if image.width() < full_w * 0.9 or image.height() < full_h * 0.9:
            break
        deadline = time.time() + 1.5
        while time.time() < deadline:
            sc._flush_qt_events()
            time.sleep(0.05)
        again = _grab(editor)
        if again is not None:
            image = _trim(again)
    else:
        if image.width() >= full_w * 0.9 and image.height() >= full_h * 0.9:
            image.save(str(LOG.with_name("gui_debug_full.png")), "PNG")
            return "ノードが描かれる前に撮れてしまいました"
    if image.width() > MAX_OUT_WIDTH:
        from PySide6.QtCore import Qt

        image = image.scaledToWidth(MAX_OUT_WIDTH, Qt.SmoothTransformation)
    target.mkdir(parents=True, exist_ok=True)
    node_png = target / "node.png"
    ports_png = target / "node_ports.png"
    if node_png.exists() and not ports_png.exists():
        node_png.replace(ports_png)
    if not image.save(str(node_png), "PNG"):
        return "保存できませんでした"
    return f"OK {image.width()}x{image.height()}"


def run() -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text("", encoding="utf-8")
    try:
        import screen_capture as sc
        import dump_conditions as dump
        from recipes import RECIPES

        conditions = json.loads((ROOT / "build" / "reference_conditions.json").read_text(encoding="utf-8"))
        only = {k for k in os.environ.get("REF_GUI_ONLY", "").split(",") if k}
        editor = hou.ui.paneTabOfType(hou.paneTabType.NetworkEditor)
        if editor is None:
            log("NG ネットワークエディタのペインがありません")
            return
        ok = ng = 0
        _close_start_dialogs()
        # 撮るあいだだけ、最大化したペインに出るパラメータの小窓（showparmdialogmax）と、メニューの帯（showmenu）を消す
        saved_prefs = {}
        for key in ("showparmdialogmax", "showparmdialog", "showmenu"):
            try:
                saved_prefs[key] = editor.getPref(key)
                editor.setPref(key, "0")
            except Exception:  # noqa: BLE001
                pass
        _keep_on_top(True)  # ほかのウィンドウ（ターミナル・ブラウザ）が重なると、撮れない（重なりの検査で断る）
        time.sleep(1.0)
        try:  # 慣らし: 起動直後の 1 枚目は、描き直しが間に合わず、空の画面が撮れる。仮のネットワークを開いて、少し待つ
            warm = hou.node("/obj").createNode("geo", "warmup")
            warm.createNode("null")
            editor.setPwd(warm)
            deadline = time.time() + 3.0
            while time.time() < deadline:
                sc._flush_qt_events()
                time.sleep(0.05)
            warm.destroy()
        except Exception:  # noqa: BLE001
            pass
        with sc.maximized_if_narrow(editor, LOG):
            for recipe in RECIPES:
                key = recipe["key"]
                cond = conditions.get(key)
                if only and key not in only:
                    continue
                if not isinstance(cond, dict) or "error" in cond or any(n.get("vop") for n in cond.get("nodes") or []):
                    continue
                target = MEDIA / recipe["kind"] / key.replace("/", "_")
                _close_start_dialogs()
                try:
                    result = shoot(editor, sc, dump, recipe, cond, target)
                except Exception as exc:  # noqa: BLE001 -- 1 件が壊れても、ほかは続ける
                    result = f"例外 {type(exc).__name__}: {exc}"
                good = result.startswith("OK")
                ok += good
                ng += not good
                log(("OK " if good else "NG ") + key + " " + result)
        for key, value in saved_prefs.items():  # ネットワークエディタの表示の設定を、元に戻す（ふだんの Houdini に残さない）
            try:
                editor.setPref(key, value)
            except Exception:  # noqa: BLE001
                pass
        log(f"DONE ok={ok} ng={ng}")
    except Exception:  # noqa: BLE001
        log("FATAL " + traceback.format_exc())
    finally:
        _keep_on_top(False)
        if os.environ.get("REF_GUI_KEEP_OPEN") != "1":
            hou.exit(suppress_save_prompt=True)
