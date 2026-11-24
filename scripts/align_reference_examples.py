"""VEX の説明の「例」を、撮影したレシピの式に合わせる（2026-11-24）。開発側の道具。

  uv run python scripts/align_reference_examples.py [--only vex/noise,...] [--dry-run]

撮影した「適用前後」の画像は、scripts/reference_capture/recipes_vex.py の式で作ったもの。AI が書いた「例」の式と食い違うと、
画像と文章が合わなくなるので、保存してある説明の example（例）と example_point（見るところ）を、レシピの式と see の文で、置き換える。
（what・use・when は、そのまま。式と文は、レシピから機械的に作るので、AI を使わず、費用はかからない）
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "houdini" / "python_panels"))
sys.path.insert(0, str(ROOT / "scripts" / "reference_capture"))

import reference_data as rd  # noqa: E402
from recipe_common import input_specs  # noqa: E402
from recipes_more import VEX_MORE  # noqa: E402
from recipes_vex import VEX_RECIPES  # noqa: E402

DEFAULT_CONFIG = Path.home() / ".houdini" / "rag_chatbot_config.json"
BASE = {"grid": "板（Grid）", "sphere": "球（Sphere）", "box": "箱（Box）"}
AFTER = {"scatter": "{}に散らした点（Scatter）", "pointjitter": "{}の点を少しずらした、ざらざらの形（Point Jitter）", "attribwrangle": "{}に、色（Cd）を付けたもの"}


def describe(spec: dict) -> str:
    text = BASE.get(spec["type"].split("::")[0], spec["type"])
    for step in spec.get("after") or []:
        text = AFTER.get(step["type"].split("::")[0], "{}").format(text)
    return text


def example_text(recipe: dict) -> str:
    code = " ".join(line.strip() for line in recipe["parms"]["snippet"].splitlines())
    inputs = input_specs(recipe)
    if len(inputs) == 1:
        source = f"入力は、{describe(inputs[0])}です。"
    else:
        source = "".join(f"{i + 1} 番目の入力は、{describe(spec)}。" for i, spec in enumerate(inputs))[:-1] + "です。"
    run_over = "Primitives" if recipe["parms"].get("class") == 1 else "Points（初期値）"
    return f"Attribute Wrangle ノードを置き、Run Over を {run_over} にして、VEXpression に次の式を書きます: {code}　{source}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", default="")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    base_dir = str(os.environ.get("RAGREEL_BRIDGE_DIR") or cfg.get("local_bridge_dir") or "")
    only = {k.strip() for k in args.only.split(",") if k.strip()}
    done = missing = 0
    for recipe in [*VEX_RECIPES, *VEX_MORE]:
        if only and recipe["key"] not in only:
            continue
        path = rd.entry_path(base_dir, "vex", recipe["key"])
        if not path.is_file():
            missing += 1
            print(f"  --  {recipe['key']}: 保存した説明がありません")
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        data["example"] = example_text(recipe)
        data["example_point"] = recipe["see"] + "。"
        if len(data["example"]) > rd.MAX_FIELD_CHARS or len(data["example_point"]) > rd.MAX_FIELD_CHARS:
            print(f"  NG  {recipe['key']}: 長すぎます")
            continue
        if args.dry_run:
            print(f"  {recipe['key']}: {data['example'][:120]}")
        else:
            path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        done += 1
    print(f"{'（dry-run）' if args.dry_run else ''}置き換え {done} 件 / 説明なし {missing} 件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
