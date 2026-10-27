"""評価の集計の画面を、実際に作って確かめる（Houdini の hython が要る。単体テストの一覧には入れない）。

実行例:  $env:QT_QPA_PLATFORM='offscreen'; & 'C:\\Program Files\\Side Effects Software\\Houdini 22.0.459\\bin\\hython.exe' houdini\\tests\\smoke_report_dialog.py [画像の保存先.png]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python_panels"))

from PySide6.QtWidgets import QApplication, QTableWidget  # noqa: E402

import report_dialog  # noqa: E402


def entry(key, rating=0, model="claude-sonnet-5-5", level="basic", domain="particles", tags=(), note="", metrics=None):
    return {
        "key": key, "path": f"/x/{key}.md", "title": key, "level": level, "model": model, "domain": domain,
        "metrics": {"iterations": 40, "cost_usd": 0.25, "cook_errors": 0, "completed": True} if metrics is None else metrics,
        "rating": rating, "tags": list(tags), "note": note, "status": "",
    }


ENTRIES = (
    [entry("old%d" % i, 0, model="", level="", domain="", metrics={}) for i in range(28)]
    + [entry("a", 1, level="basic", domain="copernicus", tags=["動画が良い"])]
    + [entry("b%d" % i, 0, level="advanced", domain="simulation") for i in range(6)]
    + [entry("c", -1, level="advanced", domain="simulation", tags=["形が違う"], note="ノードが多すぎて読めない")]
)

app = QApplication.instance() or QApplication([])
dialog = report_dialog.ReportDialog(None, lambda: ENTRIES)
dialog.show()
app.processEvents()

tabs = dialog._tabs
assert tabs.count() >= 4, tabs.count()
table = tabs.widget(0)
assert isinstance(table, QTableWidget)
assert table.rowCount() >= 1
# 件数の降順で並んでいる（未記録28件が先頭）
assert table.item(0, 1).text() == "28", table.item(0, 1).text()
# 評価が少ない行は、好評率が「—」
assert table.item(0, 3).text() == "—"
# 並べ替え: 好評率の列で昇順にしても、値の無い行が先頭に来ない
table.sortItems(3, report_dialog.Qt.AscendingOrder)
assert table.item(0, 3).text() != "—" or all(table.item(r, 3).text() == "—" for r in range(table.rowCount()))
assert dialog._warn.isVisible() and "評価済み" in dialog._warn.text()

if len(sys.argv) > 1:
    dialog.grab().save(sys.argv[1])
    print("saved", sys.argv[1])
print("report dialog smoke OK")
