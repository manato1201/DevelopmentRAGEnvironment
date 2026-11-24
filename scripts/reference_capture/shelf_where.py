"""シェルフツールの「操作する場所」の図を描く（2026-11-24。Qt だけ。Houdini は使わない）。

dump_shelf.py が hython で取り出した情報（シェルフのタブの並び・そのシェルフのボタン）から、Houdini の画面上部のシェルフを模した図を描く:
  上の段 … シェルフのタブ（そのツールがあるタブを強調）
  下の段 … そのタブのボタン（そのツールを赤い枠で囲み、「ここを押す」と書く）
アイコンは、Houdini 付属の icons.zip（SOP_mountain → SOP/mountain.svg）から読む。見つからないボタンは、名前の頭文字で代用する。
"""

from __future__ import annotations

import glob
import zipfile
from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QImage, QPainter, QPen
from PySide6.QtSvg import QSvgRenderer

WIDTH = 960
MARGIN = 16
BG = QColor("#2b2d31")
TAB = QColor("#3b3f46")
TAB_ACTIVE = QColor("#d98a1f")
BUTTON = QColor("#3a3d44")
TARGET = QColor("#ef4444")
TEXT = QColor("#e5e7eb")
MUTED = QColor("#9ca3af")
CELL_W, CELL_H, ICON = 122, 124, 56
MAX_BUTTONS = 7  # 横に並べるボタンの数（多いシェルフは、ツールを中心に前後を切り出す）


def find_icons_zip() -> Path | None:
    hits = sorted(glob.glob("C:/Program Files/Side Effects Software/Houdini */houdini/config/Icons/icons.zip"))
    return Path(hits[-1]) if hits else None


def icon_member(icon: str) -> str:
    """SOP_mountain → SOP/mountain.svg（最初の「_」までが、フォルダ名）。"""
    head, _, rest = (icon or "").partition("_")
    return f"{head}/{rest}.svg" if rest else ""


def window_of(tools: list[dict], name: str, size: int = MAX_BUTTONS) -> tuple[list[dict], bool, bool]:
    """name のボタンを中心に、size 個を切り出す。(切り出したボタン, 前に省いた分があるか, 後ろに省いた分があるか)。"""
    if len(tools) <= size:
        return tools, False, False
    index = next((i for i, t in enumerate(tools) if t["name"] == name), 0)
    start = max(0, min(index - size // 2, len(tools) - size))
    return tools[start:start + size], start > 0, start + size < len(tools)


def _wrap_tabs(labels: list[str], metrics: QFontMetrics, width: int) -> list[list[tuple[int, str]]]:
    """タブを、幅に収まるように、何段かに折り返す。[(元の番号, 文字), ...] の段の並び。"""
    rows: list[list[tuple[int, str]]] = [[]]
    used = 0
    for i, label in enumerate(labels):
        w = metrics.horizontalAdvance(label) + 22
        if used + w > width and rows[-1]:
            rows.append([])
            used = 0
        rows[-1].append((i, label))
        used += w + 4
    return rows


def render(info: dict, path: Path, zip_path: Path | None = None) -> bool:
    """info: dump_shelf.py の 1 件分。path に PNG を書く。"""
    app = QGuiApplication.instance() or QGuiApplication([])  # noqa: F841
    zip_path = zip_path or find_icons_zip()
    archive = zipfile.ZipFile(zip_path) if zip_path and Path(zip_path).is_file() else None  # 無ければ、アイコンの代わりに頭文字を描く
    try:
        return _draw(info, path, archive)
    finally:
        if archive:
            archive.close()


def _draw(info: dict, path: Path, archive: zipfile.ZipFile | None) -> bool:
    names = set(archive.namelist()) if archive else set()

    # 文字は大きめ（2026-11-25。パネルで縮めて出すと、小さい文字が潰れて読めなかった）
    font = QFont()
    font.setPixelSize(20)
    small = QFont()
    small.setPixelSize(16)
    big = QFont()
    big.setPixelSize(22)
    big.setBold(True)
    fm = QFontMetrics(font)

    tabs = info["tabs"]
    active = next((i for i, t in enumerate(tabs) if t["name"] == info["shelf"]["name"]), 0)
    rows = _wrap_tabs([t["label"] for t in tabs], fm, WIDTH - MARGIN * 2)
    buttons, more_before, more_after = window_of(info["tools"], next((t["name"] for t in info["tools"] if t["label"] == info["label"]), ""))
    target_name = next((t["name"] for t in info["tools"] if t["label"] == info["label"]), "")

    tab_h = 38
    height = MARGIN + 28 + len(rows) * (tab_h + 4) + 14 + 44 + CELL_H + 18 + 34 + MARGIN
    image = QImage(WIDTH, height, QImage.Format_ARGB32)
    image.fill(BG)
    p = QPainter(image)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    y = MARGIN
    p.setFont(small)
    p.setPen(MUTED)
    set_label = info["set"]["label"] if info.get("set") else "シェルフ"
    p.drawText(MARGIN, y + 16, f"Houdini の画面上部のシェルフ（{set_label}）")
    y += 28
    for row in rows:
        x = MARGIN
        for i, label in row:
            w = fm.horizontalAdvance(label) + 22
            p.setPen(Qt.NoPen)
            p.setBrush(TAB_ACTIVE if i == active else TAB)
            p.drawRoundedRect(QRectF(x, y, w, tab_h), 6, 6)
            p.setFont(font)
            p.setPen(QColor("#111827") if i == active else TEXT)
            p.drawText(QRectF(x, y, w, tab_h), Qt.AlignCenter, label)
            x += w + 4
        y += tab_h + 4
    y += 14
    p.setFont(small)
    p.setPen(MUTED)
    p.drawText(MARGIN, y + 14, f"「{info['shelf']['label']}」タブのボタン" + ("（前にも、続きがあります）" if more_before else "") + ("（後ろにも、続きがあります）" if more_after else ""))
    y += 44  # 「ここを押す」を書く段
    x = MARGIN
    for tool in buttons:
        is_target = tool["name"] == target_name
        rect = QRectF(x, y, CELL_W, CELL_H)
        p.setPen(QPen(TARGET, 4) if is_target else Qt.NoPen)
        p.setBrush(QColor("#4a3030") if is_target else BUTTON)
        p.drawRoundedRect(rect, 8, 8)
        icon_rect = QRectF(x + (CELL_W - ICON) / 2, y + 8, ICON, ICON)
        member = icon_member(tool.get("icon", ""))
        if archive and member in names:
            renderer = QSvgRenderer(QByteArray(archive.read(member)))
            renderer.render(p, icon_rect)
        else:
            p.setPen(MUTED)
            p.setFont(big)
            p.drawText(icon_rect, Qt.AlignCenter, (tool["label"] or "?")[:1])
        p.setFont(small)
        p.setPen(QColor("#ffffff") if is_target else TEXT)
        label = QFontMetrics(small).elidedText(tool["label"], Qt.ElideRight, CELL_W - 8)
        p.drawText(QRectF(x + 4, y + ICON + 14, CELL_W - 8, 44), Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap, tool["label"] if QFontMetrics(small).horizontalAdvance(tool["label"]) < (CELL_W - 8) * 2 else label)
        if is_target:
            p.setPen(TARGET)
            p.setFont(big)
            p.drawText(QRectF(x - 20, y - 24, CELL_W + 40, 22), Qt.AlignCenter, "▼ ここを押す")
        x += CELL_W + 6
    y += CELL_H + 18
    p.setFont(font)
    p.setPen(TEXT)
    p.drawText(MARGIN, y + 18, f"シェルフの「{info['shelf']['label']}」タブ →「{info['label']}」ボタン")
    p.end()
    path.parent.mkdir(parents=True, exist_ok=True)
    return image.save(str(path), "PNG")
