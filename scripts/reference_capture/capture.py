"""Reference の「適用前後」の画像・動きを、レシピ（recipes.py）から、自動で撮る（2026-11-19）。開発側の道具（参加者の端末では動かさない）。

  uv run --with pillow --with PySide6 python scripts/reference_capture/capture.py --out build/reference_media [--only sop/mountain,sop/scatter] [--no-clip]

出力: <out>/<種類>/<キー>/before.png・after.png・node.png・clip.gif と、meta.json（秒数・失敗の理由）
  ・before / after / clip は、hython（Houdini 22）の OpenGL ROP で撮る。1 回の起動で 1 枚（連番は 1 回）しか撮れない（hython_shot.py の説明）
  ・node.png は、保存済みのグラフの図（screen_capture.render_graph_diagram。Houdini を使わない）
  ・clip.gif は、連番を ffmpeg で GIF にする（480px・16fps。Reference の画面で、そのまま動かせる）
公開は publish_reference.py（画像は、内容のハッシュを名前に入れて置く）。
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "houdini" / "python_panels"))

from recipes import RECIPES  # noqa: E402

# screen_capture は、モジュールの先頭で hou を読み込む。この道具は、Houdini の外（普通の Python）で動くので、空の hou を差し込む
# （ここで使う関数は、hou を使わない: 背景色・ノード図の描画だけ）。
if "hou" not in sys.modules:
    import types

    sys.modules["hou"] = types.ModuleType("hou")

GIF_WIDTH = 480
GIF_FPS = 16
SHOT_TIMEOUT = 180


def find_hython() -> str:
    env = os.environ.get("HYTHON")
    if env and Path(env).is_file():
        return env
    hits = sorted(glob.glob("C:/Program Files/Side Effects Software/Houdini */bin/hython.exe"))
    if not hits:
        raise SystemExit("hython が見つかりません（環境変数 HYTHON に、hython.exe のパスを入れてください）")
    return hits[-1]


def slug_dir(out: Path, kind: str, key: str) -> Path:
    return out / kind / key.replace("/", "_")


def run_shot(hython: str, recipe_path: Path, mode: str, target: Path) -> tuple[bool, str, float]:
    started = time.time()
    try:
        proc = subprocess.run([hython, str(HERE / "hython_shot.py"), str(recipe_path), mode, str(target)],
                              capture_output=True, text=True, timeout=SHOT_TIMEOUT, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return False, f"{mode}: {SHOT_TIMEOUT} 秒で終わりませんでした", time.time() - started
    seconds = time.time() - started
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith(("OK", "REASON:"))]
    if proc.returncode == 0 and lines and lines[-1] == "OK":
        return True, "", seconds
    reason = next((ln[7:] for ln in reversed(lines) if ln.startswith("REASON:")), f"終了コード {proc.returncode}")
    return False, f"{mode}: {reason}", seconds


def flatten(path: Path) -> None:
    """透明な背景を、ビューポートの背景色で塗りつぶす（スクリーンショットと同じ見た目にそろえる）。"""
    from PIL import Image
    import screen_capture as sc

    image = Image.open(path)
    if image.mode == "RGBA":
        background = Image.new("RGBA", image.size, tuple(sc.VIEWPORT_BACKGROUND_RGB) + (255,))
        image = Image.alpha_composite(background, image)
    image.convert("RGB").save(path, "PNG", optimize=True)


def make_gif(frames_dir: Path, gif_path: Path) -> tuple[bool, str]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False, "ffmpeg が見つかりません"
    for frame in sorted(frames_dir.glob("frame.*.png")):
        flatten(frame)
    palette = f"fps={GIF_FPS},scale={GIF_WIDTH}:-1:flags=lanczos"
    proc = subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-framerate", "24", "-i", str(frames_dir / "frame.%04d.png"),
                           "-vf", f"{palette},split[a][b];[a]palettegen=max_colors=96[p];[b][p]paletteuse=dither=bayer:bayer_scale=4",
                           "-loop", "0", str(gif_path)], capture_output=True, text=True)
    return proc.returncode == 0 and gif_path.is_file(), proc.stderr.strip()[:200]


def render_node_image(recipe: dict, path: Path) -> bool:
    """ノード図（入力 → ノード）。保存済みグラフの描画を使う（Qt。Houdini は不要）。"""
    from PySide6.QtGui import QGuiApplication
    import screen_capture as sc

    app = QGuiApplication.instance() or QGuiApplication([])  # noqa: F841
    types = recipe["type"] if isinstance(recipe["type"], list) else [recipe["type"]]
    node_label = recipe["key"].split("/")[-1]
    inputs = recipe.get("inputs") or [recipe["input"]]
    nodes = [{"id": f"/obj/ref/in{i}", "label": spec["type"], "kind": spec["type"], "parent": "/obj/ref", "position": [float(i) * 160, 0.0]} for i, spec in enumerate(inputs)]
    nodes.append({"id": "/obj/ref/node", "label": node_label, "kind": types[-1].split("::")[0], "parent": "/obj/ref", "position": [0.0, 1.0]})
    edges = [{"source": f"/obj/ref/in{i}", "target": "/obj/ref/node", "targetInput": i} for i in range(len(inputs))]
    graph = {"sandbox": "/obj/ref", "nodes": nodes, "edges": edges}
    return sc.render_graph_diagram(graph, path, width=960, height=360)


def capture_one(hython: str, recipe: dict, out: Path, clip: bool = True) -> dict:
    target = slug_dir(out, recipe["kind"], recipe["key"])
    target.mkdir(parents=True, exist_ok=True)
    meta: dict = {"key": recipe["key"], "seconds": {}, "errors": []}
    with tempfile.TemporaryDirectory() as tmp:
        recipe_path = Path(tmp) / "recipe.json"
        recipe_path.write_text(json.dumps(recipe, ensure_ascii=False), encoding="utf-8")
        for mode in ("before", "after"):
            ok, reason, seconds = run_shot(hython, recipe_path, mode, target / f"{mode}.png")
            meta["seconds"][mode] = round(seconds, 1)
            if ok:
                flatten(target / f"{mode}.png")
            else:
                meta["errors"].append(reason)
        if clip and not meta["errors"] and recipe.get("sweep"):
            frames = Path(tmp) / "frames"
            ok, reason, seconds = run_shot(hython, recipe_path, "clip", frames)
            meta["seconds"]["clip"] = round(seconds, 1)
            if ok:
                started = time.time()
                good, why = make_gif(frames, target / "clip.gif")
                meta["seconds"]["gif"] = round(time.time() - started, 1)
                if not good:
                    meta["errors"].append(f"gif: {why}")
            else:
                meta["errors"].append(reason)
    started = time.time()
    if not render_node_image(recipe, target / "node.png"):
        meta["errors"].append("node: ノード図を描けませんでした")
    meta["seconds"]["node"] = round(time.time() - started, 1)
    meta["total"] = round(sum(meta["seconds"].values()), 1)
    meta["ok"] = not meta["errors"]
    (target / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", required=True, help="出力先のフォルダ")
    parser.add_argument("--only", default="", help="撮るキー（カンマ区切り。例: sop/mountain,sop/scatter）。省略すると、全部")
    parser.add_argument("--no-clip", action="store_true", help="動き（GIF）を撮らない")
    args = parser.parse_args()
    only = {k.strip() for k in args.only.split(",") if k.strip()}
    recipes = [r for r in RECIPES if not only or r["key"] in only]
    hython = find_hython()
    out = Path(args.out)
    print(f"hython: {hython} / {len(recipes)} 件")
    total = 0.0
    failed = 0
    for recipe in recipes:
        meta = capture_one(hython, recipe, out, clip=not args.no_clip)
        total += meta["total"]
        failed += 0 if meta["ok"] else 1
        status = "OK " if meta["ok"] else "NG "
        print(f"{status}{recipe['key']:<22} {meta['total']:>5.1f} 秒  {meta['seconds']}" + ("" if meta["ok"] else f"  {meta['errors']}"))
    print(f"合計 {total:.0f} 秒 / 失敗 {failed} 件")


if __name__ == "__main__":
    main()
