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

from recipe_common import graph_nodes, input_specs  # noqa: E402
from recipes import RECIPES  # noqa: E402

# screen_capture は、モジュールの先頭で hou を読み込む。この道具は、Houdini の外（普通の Python）で動くので、空の hou を差し込む
# （ここで使う関数は、hou を使わない: 背景色・ノード図の描画だけ）。
if "hou" not in sys.modules:
    import types

    sys.modules["hou"] = types.ModuleType("hou")

GIF_WIDTH = 480
GIF_FPS = 16
SHOT_TIMEOUT = 600  # シミュレーション（Pyro のレシピなど）は、動かして撮るまでに数分かかる


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

    import io

    # バイト列から開く（ファイルから開くと、PGM・PPM は、ファイルを mmap したままになり、Windows では、同じファイルに書けない。COP で起きた）
    image = Image.open(io.BytesIO(path.read_bytes()))
    image.load()
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


def graph_diagram(recipe: dict) -> dict:
    """graph（つなぎ方を書くレシピ）のノード図。元のノードが上、後ろにつなぐほど下（深さは、入力の深さの最大 + 1）。"""
    depth: dict[str, int] = {}
    for spec in graph_nodes(recipe):
        refs = [r if isinstance(r, str) else r[0] for r in spec.get("inputs") or [] if r is not None]
        depth[spec["name"]] = 1 + max((depth[r] for r in refs), default=-1)
    levels = max(depth.values(), default=0)
    used: dict[int, int] = {}
    nodes, edges = [], []
    for spec in graph_nodes(recipe):
        level = depth[spec["name"]]
        column = used.get(level, 0)
        used[level] = column + 1
        kind = (spec["type"] if isinstance(spec["type"], str) else spec["type"][-1]).split("::")[0]
        nodes.append({"id": f"/obj/ref/{spec['name']}", "label": kind, "kind": kind, "parent": "/obj/ref", "position": [column * 160.0, float(levels - level)]})
        for i, ref in enumerate(spec.get("inputs") or []):
            if ref is not None:
                source, output = (ref, 0) if isinstance(ref, str) else ref
                edges.append({"source": f"/obj/ref/{source}", "target": f"/obj/ref/{spec['name']}", "targetInput": i, "sourceOutput": output})
    return {"sandbox": "/obj/ref", "nodes": nodes, "edges": edges}


def _caption_font(size: int):
    from PIL import ImageFont

    for name in ("YuGothB.ttc", "meiryob.ttc", "msgothic.ttc", "arial.ttf"):
        try:
            return ImageFont.truetype(f"C:/Windows/Fonts/{name}", size)
        except OSError:
            continue
    return ImageFont.load_default()


def make_toggle_gif(before: Path, after: Path, gif_path: Path) -> bool:
    """適用前と適用後を、交互に見せる GIF（動かせる値が無く、動きを撮れないものの、動き。2026-11-24）。左上に「適用前」「適用後」を書く。"""
    from PIL import Image, ImageDraw

    frames = []
    for label, source in (("適用前", before), ("適用後", after)):
        with Image.open(source) as opened:
            image = opened.convert("RGB")
        height = round(image.height * GIF_WIDTH / image.width)
        image = image.resize((GIF_WIDTH, height), Image.LANCZOS)
        draw = ImageDraw.Draw(image)
        font = _caption_font(22)
        box = draw.textbbox((12, 10), label, font=font)
        draw.rectangle((box[0] - 8, box[1] - 5, box[2] + 8, box[3] + 5), fill=(0, 0, 0))
        draw.text((12, 10), label, font=font, fill=(255, 255, 255))
        frames.append(image)
    frames[0].save(gif_path, save_all=True, append_images=frames[1:], duration=[1300, 1300], loop=0, optimize=True)
    return gif_path.is_file()


def fill_toggle_gifs(out: Path, only: set[str]) -> None:
    """撮ってある、適用前・適用後の画像があって、動き（clip.gif）が無い項目に、交互に見せる GIF を作る（Houdini は、使わない）。"""
    made = skipped = 0
    for folder in sorted(out.glob("*/*")):
        key = f"{folder.parent.name}/{folder.name}"
        if only and not any(key.endswith(k.replace("/", "_")) for k in only):
            continue
        before, after, clip = folder / "before.png", folder / "after.png", folder / "clip.gif"
        if clip.is_file() or not before.is_file() or not after.is_file():
            skipped += 1
            continue
        ok = make_toggle_gif(before, after, clip)
        made += 1 if ok else 0
        print(("OK  " if ok else "NG  ") + key)
    print(f"作った {made} 件 / 飛ばした {skipped} 件")


def vop_diagram(recipe: dict) -> dict:
    """VOP のレシピ（Attribute VOP の中）の図。Global が上、Output が下、そのあいだに、つないだ順のノード。"""
    vop = recipe["vop"]
    names = ["global", *[n["name"] for n in vop.get("nodes") or []], "out"]
    labels = {"global": "geometryvopglobal", "out": "geometryvopoutput"}
    labels.update({n["name"]: (n["type"] if isinstance(n["type"], str) else n["type"][0]) for n in vop.get("nodes") or []})
    depth = {"global": 0}
    for _ in names:  # つなぎから、深さ（上からの段）を決める
        for src, _out, dst, _in in vop.get("wires") or []:
            depth[dst] = max(depth.get(dst, 1), depth.get(src, 0) + 1)
    depth["out"] = max(depth.values()) + (0 if "out" in depth and depth["out"] > max(v for k, v in depth.items() if k != "out") else 1)
    levels = max(depth.values())
    used: dict[int, int] = {}
    nodes, edges = [], []
    for name in names:
        level = depth.get(name, 1)
        column = used.get(level, 0)
        used[level] = column + 1
        nodes.append({"id": f"/obj/ref/node/{name}", "label": labels[name], "kind": labels[name], "parent": "/obj/ref/node",
                      "position": [column * 180.0, float(levels - level)]})
    for i, (src, out, dst, inp) in enumerate(vop.get("wires") or []):
        edges.append({"source": f"/obj/ref/node/{src}", "target": f"/obj/ref/node/{dst}", "targetInput": inp if isinstance(inp, int) else i})
    return {"sandbox": "/obj/ref/node", "nodes": nodes, "edges": edges}


def render_node_image(recipe: dict, path: Path) -> bool:
    """ノード図（入力 → ノード）。保存済みグラフの描画を使う（Qt。Houdini は不要）。"""
    from PySide6.QtGui import QGuiApplication
    import screen_capture as sc

    app = QGuiApplication.instance() or QGuiApplication([])  # noqa: F841
    types = recipe["type"] if isinstance(recipe["type"], list) else [recipe["type"]]
    node_label = recipe["key"].split("/")[-1] if recipe["kind"] == "node" else types[-1].split("::")[0]  # VEX・シェルフの図は、実際に置くノードの名前（attribwrangle など）
    inputs = input_specs(recipe)
    nodes: list[dict] = []
    edges: list[dict] = []
    if recipe.get("graph") or recipe.get("cop"):
        return sc.render_graph_diagram(graph_diagram(recipe), path, width=720, height=300)
    if recipe.get("vop"):
        return sc.render_graph_diagram(vop_diagram(recipe), path, width=720, height=300)
    for i, spec in enumerate(inputs):
        chain = [spec, *(spec.get("after") or [])]  # 元のノード → 後ろにつなぐノード…（hython_shot.py の build_chain と同じ並び）
        for k, step in enumerate(chain):
            name = f"in{i}" if k == 0 else f"in{i}_{k - 1}"
            nodes.append({"id": f"/obj/ref/{name}", "label": step["type"], "kind": step["type"].split("::")[0], "parent": "/obj/ref",
                          "position": [float(i) * 160, float(len(chain) - k)]})
            if k:
                previous = f"in{i}" if k == 1 else f"in{i}_{k - 2}"
                edges.append({"source": f"/obj/ref/{previous}", "target": f"/obj/ref/{name}", "targetInput": 0})
    nodes.append({"id": "/obj/ref/node", "label": node_label, "kind": types[-1].split("::")[0], "parent": "/obj/ref", "position": [0.0, 0.0]})
    for i, spec in enumerate(inputs):
        last = f"in{i}" if not spec.get("after") else f"in{i}_{len(spec['after']) - 1}"
        edges.append({"source": f"/obj/ref/{last}", "target": "/obj/ref/node", "targetInput": i})
    graph = {"sandbox": "/obj/ref", "nodes": nodes, "edges": edges}
    return sc.render_graph_diagram(graph, path, width=720, height=300)  # 小さめの画面に描く: パネルで縮めても、ノード名が読める（2026-11-25）


def capture_one(hython: str, recipe: dict, out: Path, clip: bool = True) -> dict:
    target = slug_dir(out, recipe["kind"], recipe["key"])
    target.mkdir(parents=True, exist_ok=True)
    meta: dict = {"key": recipe["key"], "seconds": {}, "errors": []}
    with tempfile.TemporaryDirectory() as tmp:
        recipe_path = Path(tmp) / "recipe.json"
        recipe_path.write_text(json.dumps(recipe, ensure_ascii=False), encoding="utf-8")
        for mode in (("after",) if recipe.get("create") else ("before", "after")):
            ok, reason, seconds = run_shot(hython, recipe_path, mode, target / f"{mode}.png")
            meta["seconds"][mode] = round(seconds, 1)
            if ok:
                flatten(target / f"{mode}.png")
            else:
                meta["errors"].append(reason)
        if clip and not meta["errors"] and (recipe.get("sweep") or recipe.get("animate") or recipe.get("sim") or recipe.get("create")) and (not recipe.get("cop") or recipe.get("sweep")):
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


def capture_clip_only(hython: str, recipe: dict, out: Path) -> dict:
    """動き（clip.gif）だけを撮る。静止画・ノード図は、そのまま残す。"""
    target = slug_dir(out, recipe["kind"], recipe["key"])
    target.mkdir(parents=True, exist_ok=True)
    meta: dict = {"ok": True, "errors": []}
    with tempfile.TemporaryDirectory() as tmp:
        recipe_path = Path(tmp) / "recipe.json"
        recipe_path.write_text(json.dumps(recipe, ensure_ascii=False), encoding="utf-8")
        frames = Path(tmp) / "frames"
        ok, reason, _seconds = run_shot(hython, recipe_path, "clip", frames)
        if ok:
            good, why = make_gif(frames, target / "clip.gif")
            if not good:
                meta["errors"].append(f"gif: {why}")
        else:
            meta["errors"].append(reason)
    meta["ok"] = not meta["errors"]
    return meta


def capture_where(hython: str, out: Path, only: set[str]) -> None:
    """シェルフツール（recipes に無いものも含めた、保存してある全部）の、操作する場所の図を、<out>/shelf/<キー>/where.png に描く。"""
    import shelf_where

    base = ROOT / "localRAG" / "reference" / "shelf"
    keys = sorted(p.name[len("shelf_"):-len(".json")] for p in base.glob("shelf_*.json"))
    keys = [k for k in keys if not only or f"shelf/{k}" in only]
    with tempfile.TemporaryDirectory() as tmp:
        keys_file, info_file = Path(tmp) / "keys.json", Path(tmp) / "info.json"
        keys_file.write_text(json.dumps(keys), encoding="utf-8")
        proc = subprocess.run([hython, str(HERE / "dump_shelf.py"), str(keys_file), str(info_file)], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
        if proc.returncode != 0 or not info_file.is_file():
            raise SystemExit(f"シェルフの情報を取り出せませんでした: {(proc.stderr or proc.stdout)[-300:]}")
        info = json.loads(info_file.read_text(encoding="utf-8"))
    done = 0
    for key in keys:
        if key not in info:
            print(f"--  shelf/{key}: Houdini に、このツールがありません")
            continue
        target = slug_dir(out, "shelf", f"shelf/{key}") / "where.png"
        ok = shelf_where.render(info[key], target)
        done += 1 if ok else 0
        print(("OK  " if ok else "NG  ") + f"shelf/{key}")
    print(f"描いた {done} / {len(keys)} 件")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", required=True, help="出力先のフォルダ")
    parser.add_argument("--only", default="", help="撮るキー（カンマ区切り。例: sop/mountain,sop/scatter）。省略すると、全部")
    parser.add_argument("--no-clip", action="store_true", help="動き（GIF）を撮らない")
    parser.add_argument("--check", action="store_true", help="撮らずに、レシピだけを調べる（cook が通り、前後で形が変わり、値が全部効くか）。レシピを足すときの確かめ用")
    parser.add_argument("--toggles", action="store_true", help="適用前・適用後の画像があって、動き（clip.gif）が無い項目に、交互に見せる GIF を作る（Houdini は使わない）。--only で、キーを絞る")
    parser.add_argument("--clip-only", action="store_true", help="動き（clip.gif）だけを撮り直す（--only で絞る。入力が無いノードは、まわりを 1 周する）")
    parser.add_argument("--where", action="store_true", help="シェルフツールの「操作する場所」の図（where.png）だけを描く（Houdini は、シェルフの情報を取り出すときだけ使う）。--only で、キーを絞る")
    parser.add_argument("--kind", default="", help="撮る種類（node / vex / shelf。カンマ区切り）。省略すると、全部")
    args = parser.parse_args()
    only = {k.strip() for k in args.only.split(",") if k.strip()}
    kinds = {k.strip() for k in args.kind.split(",") if k.strip()}
    recipes = [r for r in RECIPES if (not only or r["key"] in only) and (not kinds or r["kind"] in kinds)]
    if args.toggles:
        fill_toggle_gifs(Path(args.out), only)
        return
    hython = find_hython()
    if args.clip_only:
        for recipe in recipes:
            meta = capture_clip_only(hython, recipe, Path(args.out))
            print(("OK  " if meta["ok"] else "NG  ") + f"{recipe['key']:<30} {meta['errors'] or ''}", flush=True)
        return
    if args.where:
        capture_where(hython, Path(args.out), only)
        return
    if args.check:
        bad = 0
        for recipe in recipes:
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "recipe.json"
                path.write_text(json.dumps(recipe, ensure_ascii=False), encoding="utf-8")
                ok, reason, seconds = run_shot(hython, path, "check", Path(tmp) / "x")
            bad += 0 if ok else 1
            print(("OK " if ok else "NG ") + f"{recipe['key']:<26} {seconds:>4.1f} 秒" + ("" if ok else f"  {reason}"), flush=True)
        print(f"確認 {len(recipes)} 件 / 不備 {bad} 件")
        return
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
