"""評価まわりの画面（履歴の「未評価のみ」・保存直後の評価行・起動時の再送）を、実際に作って確かめる。
Houdini の hython が要る。単体テストの一覧には入れない。

実行例:  $env:QT_QPA_PLATFORM='offscreen'; & 'C:\\Program Files\\Side Effects Software\\Houdini 22.0.459\\bin\\hython.exe' houdini\\tests\\smoke_feedback_panels.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python_panels"))

from PySide6.QtWidgets import QApplication  # noqa: E402

import tutorial_feedback as fb  # noqa: E402
import tutorial_view as tv  # noqa: E402

app = QApplication.instance() or QApplication([])
tmp = Path(tempfile.mkdtemp())
tutorials = tmp / "localRAG" / "tutorials"
tutorials.mkdir(parents=True)
for name in ("a", "b", "c", "d"):
    (tutorials / f"{name}.md").write_text(f"---\ntitle: {name}\ndifficulty: basic\n---\n## 概要\nx\n", encoding="utf-8")
fb.save_feedback(tutorials / "a.md", 1, [], "")
fb.save_feedback(tutorials / "b.md", -1, [], "")

cfg = {"local_bridge_dir": str(tmp), "cf_url": "", "cf_api_key": ""}

# 履歴タブ: 未評価の数と、絞り込み
history = tv.TutorialHistoryPanel(lambda: cfg)
assert history._list.count() == 4
assert "未評価 2件" in history._status.text(), history._status.text()
history._unrated_btn.setChecked(True)
hidden = [history._list.item(i).isHidden() for i in range(history._list.count())]
assert sorted(hidden) == [False, False, True, True], hidden
assert "未評価のみ" in history._status.text()
history._unrated_btn.setChecked(False)
assert not any(history._list.item(i).isHidden() for i in range(history._list.count()))
# 接続先が未設定のときは、再送は何もしない（落ちない）
history._resend_pending_feedback()
assert history._resend_worker is None

# 保存直後の評価行
gen = tv.TutorialGeneratePanel(lambda: cfg)
assert not gen._rate_row.isVisible()
gen._show_rating_row(tutorials / "c.md")
gen.show()
app.processEvents()
assert gen._rate_row.isVisible()
gen._on_quick_rate(1)
gen._rate_worker.wait(5000)
app.processEvents()  # 別スレッドからのシグナルを、画面に反映する
assert not gen._rate_row.isVisible()
assert fb.read_feedback(tutorials / "c.md")["rating"] == 1
# 接続先が未設定なので送信は失敗し、「未送信」として残る（次回の起動で再送される）
assert not fb.read_feedback(tutorials / "c.md").get("uploaded_at")
assert tutorials / "c.md" in fb.pending_uploads(tutorials)
assert "未送信" in gen._status.text() or "評価を保存" in gen._status.text(), gen._status.text()
# 次の生成を始めるときと、破棄のときに、評価行が消える
gen._show_rating_row(tutorials / "d.md")
gen._on_discard()
assert not gen._rate_row.isVisible()
print("feedback panels smoke OK")
