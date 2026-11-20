"""Reference の説明を、まとめて AI で作る（2026-11-19）。開発側の道具。AI を呼ぶので、Claude の予算を使う（1 件 約 2〜3 セント。推定）。

  uv run python scripts/build_reference_entries.py --set recipes --limit 2     # まず少しだけ試す
  uv run python scripts/build_reference_entries.py --set all --yes             # 優先の全部（ノード + VEX + 撮影レシピ）

  --set   recipes（撮影レシピのノード）/ nodes（よく使うノード）/ vex（VEX の関数）/ all（全部。既定）
  --redo  保存済みの説明も、作り直す（既定は、保存済みを飛ばす）
  --keys  このキーだけ（カンマ区切り。例: sop/scatter,vex/chf）
  --workers  同時に呼ぶ数（既定 3）

作った説明は、<保存先>/localRAG/reference/ に保存される。公開は scripts/publish_reference.py。
接続先・キー・モデルは、パネルの設定（~/.houdini/rag_chatbot_config.json）から、この中だけで読む（表示しない）。
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "houdini" / "python_panels"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "reference_capture"))

import reference_author as ra  # noqa: E402
import reference_data as rd  # noqa: E402
from publish_reference import DEFAULT_CONFIG, load_config, make_item  # noqa: E402

# よく使うノード（初学者向けの実験・固定課題 Pyro / RBD / 雲 で出てくるもの）。一覧データに無いものは、キーから作る（make_item）。
COMMON_NODES = (
    # 形を作る・整える
    "sop/box", "sop/grid", "sop/sphere", "sop/tube", "sop/circle", "sop/line", "sop/curve", "sop/null", "sop/merge", "sop/blast", "sop/delete",
    "sop/transform", "sop/copytopoints", "sop/copytransform", "sop/scatter", "sop/polyextrude", "sop/subdivide", "sop/smooth", "sop/resample",
    "sop/fuse", "sop/sort", "sop/facet", "sop/peak", "sop/normal", "sop/color", "sop/measure", "sop/remesh", "sop/polyreduce", "sop/boolean",
    "sop/ray", "sop/sweep", "sop/carve", "sop/polywire", "sop/convertline", "sop/mountain", "sop/twist", "sop/bend", "sop/lattice",
    "sop/pointjitter", "sop/pointdeform", "sop/trail", "sop/rest", "sop/timeshift", "sop/switch", "sop/foreach", "sop/solver", "sop/split",
    # アトリビュート・グループ
    "sop/attribwrangle", "sop/attribcreate", "sop/attribdelete", "sop/attribpromote", "sop/attribtransfer", "sop/attribblur", "sop/attribnoise",
    "sop/attribvop", "sop/attribfromvolume", "sop/groupcreate", "sop/groupcombine", "sop/groupexpression",
    # UV・ボリューム・VDB
    "sop/uvlayout", "sop/uvunwrap", "sop/uvproject", "sop/volumewrangle", "sop/volumevop", "sop/volumerasterizeparticles", "sop/volumeblur",
    "sop/volumevisualization", "sop/vdbfrompolygons", "sop/vdbsmooth", "sop/vdbcombine", "sop/convertvdb", "sop/isooffset",
    # Pyro・雲
    "sop/pyrosource", "sop/pyrosolver", "sop/gasdissipate", "sop/gasturbulence", "sop/cloudnoise", "sop/cloudlight",
    "sop/pyrobakevolume", "sop/volumerasterizeattributes",
    # RBD・Vellum・パーティクル
    "sop/rbdmaterialfracture", "sop/rbdconfigure", "sop/rbdbulletsolver", "sop/rbdconnectedfaces", "sop/rbdconstraintproperties",
    "sop/vellumconstraints", "sop/vellumsolver", "sop/vellumdrape", "sop/popnet", "sop/popsolver", "sop/pointsfromvolume",
    # 出力・キャッシュ
    "sop/filecache", "sop/file", "sop/rop_geometry", "sop/output",
    # オブジェクト・ライト・カメラ
    "obj/geo", "obj/cam", "obj/null", "obj/hlight", "obj/envlight",
)
RECIPE_KEYS = ("sop/mountain", "sop/scatter", "sop/twist", "sop/subdivide", "sop/polyextrude")

_local = threading.local()
CALL_INTERVAL_SECONDS = 3.0   # Worker は、60 秒に 30 回までしか受け付けない。全スレッドを合わせて、この間隔を空ける（60 ÷ 3 = 20 回 / 分）
RATE_LIMIT_RETRIES = 3
RATE_LIMIT_WAIT_SECONDS = 25


class Throttle:
    """全スレッドで共有する、呼び出しの間隔の制御。"""

    def __init__(self, interval: float) -> None:
        self._interval, self._next, self._lock = interval, 0.0, threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delay = max(0.0, self._next - now)
            self._next = max(now, self._next) + self._interval
        if delay:
            time.sleep(delay)


THROTTLE = Throttle(CALL_INTERVAL_SECONDS)


def build_agent(cfg: dict):
    from tutorial_agent import TutorialAgent

    return TutorialAgent(bridge_port=cfg.get("local_port", 8766), project_dir=cfg.get("local_bridge_dir", ""), rag_mode=cfg.get("mode", "local"),
                         model=cfg.get("tutorial_model", "claude-sonnet-5"), cf_url=cfg.get("cf_url", ""), cf_api_key=cfg.get("cf_api_key", ""),
                         rag_namespace=cfg.get("tutorial_rag_namespace", ""))


def complete_in_thread(cfg: dict):
    """このスレッド専用のエージェントの complete_text（共有すると、1 回きりの指定が、スレッド間で混ざる）。"""
    if not hasattr(_local, "agent"):
        _local.agent = build_agent(cfg)
    complete = _local.agent.complete_text

    def limited(*args, **kwargs):
        for attempt in range(RATE_LIMIT_RETRIES + 1):
            THROTTLE.wait()
            try:
                return complete(*args, **kwargs)
            except RuntimeError as exc:  # レート制限（429）は、待って、やり直す。予算切れ・その他は、そのまま出す
                if "レート制限" in str(exc) and attempt < RATE_LIMIT_RETRIES:
                    time.sleep(RATE_LIMIT_WAIT_SECONDS)
                    continue
                raise

    return limited


def resolve(key: str) -> dict:
    kind = "vex" if key.startswith("vex/") else "node"
    return rd.find_item(kind, key) or make_item(kind, key)


def select_items(which: str, keys: set[str]) -> list[dict]:
    node_keys = list(dict.fromkeys(RECIPE_KEYS if which == "recipes" else COMMON_NODES if which == "nodes" else RECIPE_KEYS + COMMON_NODES if which == "all" else ()))
    items = [resolve(k) for k in node_keys]
    if which in ("vex", "all"):
        items += rd.catalog("vex")
    if keys:
        items = [i for i in items if i["key"] in keys]
    seen: set[tuple[str, str]] = set()
    out = []
    for item in items:
        if (item["kind"], item["key"]) not in seen:
            seen.add((item["kind"], item["key"]))
            out.append(item)
    return out


def make_one(cfg: dict, item: dict) -> dict:
    """1 件を作って保存する。例外は、結果に入れる（1 件の失敗で、全体を止めない）。"""
    try:
        entry, usage, docs_n, refs_n = ra.make_entry(cfg, complete_in_thread(cfg), item)
        ra.save_made(str(cfg.get("local_bridge_dir") or ""), item, entry, docs_n, refs_n)
        return {"key": item["key"], "ok": True, "docs": docs_n, "refs": refs_n, "usage": usage}
    except ra.UnreadableAnswer as exc:
        return {"key": item["key"], "ok": False, "why": f"返事を読み取れませんでした: {exc.text[:100]!r}", "usage": {}}
    except Exception as exc:  # noqa: BLE001
        return {"key": item["key"], "ok": False, "why": str(exc)[:160], "usage": {}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--set", default="all", choices=("recipes", "nodes", "vex", "all"))
    parser.add_argument("--keys", default="")
    parser.add_argument("--limit", type=int, default=0, help="作る件数の上限（試すとき）")
    parser.add_argument("--redo", action="store_true")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--yes", action="store_true", help="確認を省く")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    args = parser.parse_args(argv)
    cfg = load_config(Path(args.config))
    base_dir = str(cfg.get("local_bridge_dir") or "")
    items = select_items(args.set, {k.strip() for k in args.keys.split(",") if k.strip()})
    todo = [i for i in items if args.redo or rd.load_entry(base_dir, i["kind"], i["key"]) is None]
    if args.limit > 0:
        todo = todo[: args.limit]
    print(f"対象 {len(items)} 件 / 作る {len(todo)} 件（保存済みは飛ばす）/ モデル {cfg.get('tutorial_model')} / 目安 約 ${len(todo) * 0.025:.2f}（推定）")
    if args.dry_run or not todo:
        for item in todo[:20]:
            print("  ", item["kind"], item["key"])
        return 0
    if not args.yes:
        if input("AI を呼んで、作りますか？ [y/N] ").strip().lower() != "y":
            return 1
    from tutorial_agent import usage_cost_for

    total_in = total_out = failed = 0
    cost = 0.0
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = [pool.submit(make_one, cfg, item) for item in todo]
        for n, future in enumerate(as_completed(futures), 1):
            r = future.result()
            usage = r.get("usage") or {}
            total_in += int(usage.get("input_tokens", 0) or 0)
            total_out += int(usage.get("output_tokens", 0) or 0)
            cost += usage_cost_for(str(cfg.get("tutorial_model") or ""), usage)
            failed += 0 if r["ok"] else 1
            note = f"資料 {r['docs']}・参考 {r['refs']}" if r["ok"] else r["why"]
            print(f"[{n}/{len(todo)}] {'OK' if r['ok'] else 'NG'} {r['key']:<34} {note}", flush=True)
    print(f"完了: 成功 {len(todo) - failed} / 失敗 {failed} / 入力 {total_in:,}・出力 {total_out:,} トークン / 概算 ${cost:.2f}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
