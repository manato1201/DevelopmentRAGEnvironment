"""「課題」タブを、実際に作って通しで動かす（偽のサーバーを使う。Houdini の hython が要る。単体テストの一覧には入れない）。

実行例:  $env:QT_QPA_PLATFORM='offscreen'; & 'C:\\Program Files\\Side Effects Software\\Houdini 22.0.459\\bin\\hython.exe' houdini\\tests\\smoke_pilot_panel.py [画像の保存先.png]
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python_panels"))

from PySide6.QtWidgets import QApplication  # noqa: E402

import pilot_panel as pp  # noqa: E402

app = QApplication.instance() or QApplication([])
CFG = {"mode": "cloudflare", "cf_url": "https://w.example", "cf_api_key": "KEY"}


def plan(round_=1, profile=True, fixed_done=False, free_done=False, active=False, condition="docs_only", finished=False):
    if not profile:
        return {"status": "ok", "profile": False}
    return {
        "status": "ok", "profile": True, "pid": 1, "slot": 1, "round": round_, "completedRounds": round_ - 1, "finished": finished,
        "fixed": {"kind": "fixed", "taskId": "pyro", "label": "Pyro（煙・炎のシミュレーション）", "condition": condition, "done": fixed_done, "active": active},
        "free": {"kind": "free", "taskId": "free", "label": "自由課題（自分の作りたいもの）", "condition": "system", "done": free_done, "active": False},
        "criterion": "課題の題材として、作品物ができていること",
    }


class FakeClient:
    """サーバーの代わり。呼ばれた内容を覚える。"""
    calls: list = []
    state = {"profile": False, "fixed_done": False}

    def __init__(self, cfg):
        pass

    def pilot_plan(self):
        FakeClient.calls.append(("plan",))
        return plan(profile=FakeClient.state["profile"], fixed_done=FakeClient.state["fixed_done"])

    def pilot_profile(self, answers):
        FakeClient.calls.append(("profile", answers))
        FakeClient.state["profile"] = True
        return plan()

    def pilot_session_start(self, kind):
        FakeClient.calls.append(("start", kind))
        return {"status": "ok", "sessionId": "sid-1", "startedAt": int(time.time()) - 125, "kind": kind, "condition": "docs_only" if kind == "fixed" else "system", "label": "Pyro", "round": 1}

    def pilot_session_end(self, payload):
        FakeClient.calls.append(("end", payload))
        FakeClient.state["fixed_done"] = True
        return plan(fixed_done=True)


pp.RAGClient = FakeClient


def pump(until, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end and not until():
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()
    assert until(), "timed out"


panel = pp.PilotTaskPanel(lambda: CFG)
panel.show()

# 1) 事前アンケートが先
panel.refresh()
pump(lambda: panel._profile_box.isVisible())
assert not panel._plan_box.isVisible()
panel._years.setValue(1.5)
panel._background.setText("CG専攻")
panel._on_profile_send()
pump(lambda: panel._plan_box.isVisible())
assert not panel._profile_box.isVisible()
assert FakeClient.calls[-1][0] == "profile" and FakeClient.calls[-1][1]["experienceYears"] == 1.5
assert "第1回 / 3回" in panel._header.text() and "P01" in panel._header.text()
fixed = panel._cards["fixed"]
assert "Pyro" in fixed["title"].text()
assert "使わないでください" in fixed["condition"].text(), "the control round says not to use the system"
assert "作品物" in fixed["criterion"].text()
assert fixed["start"].isEnabled() and not fixed["finish"].isEnabled()

# 2) 固定課題を開始（記録中。他の課題は始められない）
panel._on_start("fixed")
pump(lambda: panel._active is not None)
assert not fixed["start"].isEnabled() and fixed["finish"].isEnabled()
assert not panel._cards["free"]["start"].isEnabled(), "one task at a time"
assert "記録中 0:02:0" in fixed["status"].text() or "記録中 0:02:1" in fixed["status"].text(), fixed["status"].text()
assert panel._sampler.samples >= 1
assert panel._tick.isActive() and panel._sample_timer.isActive()

# 3) 「あとで」: 課題は続いたまま
orig_exec = pp.TaskSurveyDialog.exec
pp.TaskSurveyDialog.exec = lambda self: 0
panel._on_finish()
assert panel._active is not None
assert not any(c[0] == "end" for c in FakeClient.calls)

# 4) 送信: 対照の回は、出典の質問が無い。答えなかった項目は送られない
captured = {}


def fake_exec(self):
    captured["questions"] = sorted(self._groups)
    self._reach_yes.setChecked(True)
    self._groups["selfMistakes"].button(2).setChecked(True)
    self._groups["difficulty"].button(4).setChecked(True)
    self._groups["clarity"].button(2).setChecked(True)
    self._comment.setPlainText("検索で迷った")
    return 1


pp.TaskSurveyDialog.exec = fake_exec
panel._on_finish()
pump(lambda: panel._active is None)
pp.TaskSurveyDialog.exec = orig_exec
assert "sourceUseful" not in captured["questions"], captured["questions"]
end = [c for c in FakeClient.calls if c[0] == "end"][0][1]
assert end["sessionId"] == "sid-1" and end["reached"] is True and end["selfMistakes"] == 2
assert end["survey"] == {"difficulty": 4, "clarity": 2}, end["survey"]
assert end["comment"] == "検索で迷った"
assert end["cookErrorNodes"] in (0, None), end["cookErrorNodes"]  # 空のシーン（hython）なら 0、hou が無ければ None
assert not panel._tick.isActive() and not panel._sample_timer.isActive()
assert "完了しました" in fixed["status"].text()
assert not fixed["start"].isEnabled(), "a finished task cannot be started again"
assert "送信しました" in panel._message.text()

# 5) 接続エラーは、利用者向けの短い文で出る
class Down(FakeClient):
    def pilot_plan(self):
        raise RuntimeError("HTTP Error 401: Unauthorized")


pp.RAGClient = Down
panel.refresh()
pump(lambda: "APIキー" in panel._message.text())

# 6) 本体のパネルへの組み込み: 課題タブは、既定で非表示。接続タブのチェックで出る
import panel_widgets  # noqa: E402

store = {}
panel_widgets.ui_state_get = lambda key, default=None: store.get(key, default)
panel_widgets.ui_state_set = lambda key, value: store.__setitem__(key, value)
import rag_chatbot as rc  # noqa: E402

rc._ui_state_get, rc._ui_state_set = panel_widgets.ui_state_get, panel_widgets.ui_state_set
rc._load_config = lambda: {**{"mode": "cloudflare", "cf_url": "", "cf_api_key": "", "cf_namespaces": "", "local_port": 8766}}
rc._save_config = lambda cfg: None
main = rc.RAGChatbotPanel()
main.show()
assert not main._tabs.isTabVisible(main._pilot_tab_idx), "hidden by default"
assert main._tabs.tabText(main._pilot_tab_idx) == "課題"
main._pilot_checkbox.setChecked(True)
assert main._tabs.isTabVisible(main._pilot_tab_idx)
assert store.get("pilot_enabled") is True
main._pilot_checkbox.setChecked(False)
assert not main._tabs.isTabVisible(main._pilot_tab_idx)

if len(sys.argv) > 1:
    panel.grab().save(sys.argv[1])
print("pilot panel smoke OK")
