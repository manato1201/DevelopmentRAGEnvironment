"""
display_isolation.py — 「いま見せたいもの」以外のオブジェクトの表示を切る（2026-11-18）

背景（実証実験・動画の確認で分かったこと）:
  /obj の直下には、利用者のほかのオブジェクト（geo など）や、前に生成したサンドボックスがある。それらの表示フラグが
  入ったままだと、ビューポートに、関係ないものが重なって映る。生成中のビューポート画像（動画の素材）も、
  Guide で手順を示したときのビューポートも、「見せたいオブジェクトだけ」にしたい。

やること:
  isolate(hou, keep_paths)  … /obj の直下で、表示が入っているオブジェクトのうち、keep_paths に含まれないものの表示を切る。
                              切る前の状態を覚える（同じオブジェクトは、最初の状態だけを覚える）。戻り値: 切ったパスのリスト。
  restore(hou)              … 覚えている状態へ戻す（戻したパスのリスト）。覚えたものは、空になる。
  pending()                 … 覚えている（まだ戻していない）パスの数。「表示を元に戻す」ボタンの出し分けに使う。
  top_object_path(path)     … ノードのパスから、/obj 直下のオブジェクトのパス（/obj/a/b/c → /obj/a）。

hou は引数で受け取る（Houdini の外・テストでは、偽物で差し替える）。LOP ネットワークなど、表示フラグを持たないものは、触らない。
利用者のシーンを書き換えるのは、表示フラグだけ。ノードの削除・設定の変更はしない。
"""

from __future__ import annotations

OBJ_ROOT = "/obj"

# 切る前の表示の状態: パス → 表示が入っていたか（True のものだけ覚える）
_saved: dict[str, bool] = {}


def top_object_path(path: str) -> str:
    """/obj 直下のオブジェクトのパス。/obj の外・/obj そのものは、空の文字列。"""
    text = str(path or "").rstrip("/")
    if not text.startswith(OBJ_ROOT + "/"):
        return ""
    rest = text[len(OBJ_ROOT) + 1:]
    head = rest.split("/", 1)[0]
    return f"{OBJ_ROOT}/{head}" if head else ""


def _is_displayed(node) -> bool | None:
    """表示フラグが入っているか。フラグを持たないノードは None（触らない）。"""
    try:
        if not hasattr(node, "isDisplayFlagSet") or not hasattr(node, "setDisplayFlag"):
            return None
        return bool(node.isDisplayFlagSet())
    except Exception:  # noqa: BLE001 -- 読めないノードは、飛ばす
        return None


def isolate(hou, keep_paths) -> list[str]:
    """/obj 直下で、keep_paths 以外の、表示が入っているオブジェクトの表示を切る。切ったパスを返す。"""
    keep = {top_object_path(p) or str(p).rstrip("/") for p in (keep_paths or []) if p}
    try:
        root = hou.node(OBJ_ROOT)
        children = list(root.children()) if root is not None else []
    except Exception:  # noqa: BLE001 -- hou が使えない環境では、何もしない
        return []
    turned_off: list[str] = []
    for child in children:
        try:
            path = child.path()
        except Exception:  # noqa: BLE001
            continue
        if path in keep:
            continue
        displayed = _is_displayed(child)
        if not displayed:
            continue
        _saved.setdefault(path, True)
        try:
            child.setDisplayFlag(False)
        except Exception:  # noqa: BLE001 -- 切れなくても、ほかは続ける
            _saved.pop(path, None)
            continue
        turned_off.append(path)
    return turned_off


def show(hou, path: str) -> bool:
    """指定のオブジェクトの表示を入れる（見せたいものが、切れたままにならないように）。入れたら True。"""
    try:
        node = hou.node(top_object_path(path) or path)
        if node is None or _is_displayed(node) is None:
            return False
        if not node.isDisplayFlagSet():
            node.setDisplayFlag(True)
        return True
    except Exception:  # noqa: BLE001
        return False


def restore(hou) -> list[str]:
    """覚えている状態へ戻す（消えたノードは、飛ばす）。戻したパスを返す。"""
    restored: list[str] = []
    for path in list(_saved):
        try:
            node = hou.node(path)
            if node is not None and _is_displayed(node) is not None:
                node.setDisplayFlag(True)
                restored.append(path)
        except Exception:  # noqa: BLE001
            pass
        _saved.pop(path, None)
    return restored


def pending() -> int:
    """まだ戻していない（切ったままの）オブジェクトの数。"""
    return len(_saved)


def reset() -> None:
    """覚えている状態を捨てる（テスト用）。"""
    _saved.clear()
