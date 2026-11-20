"""Reference の説明を、本物の Houdini と突き合わせて点検する（2026-11-20）。開発側の道具。

  uv run python scripts/audit_reference.py [--out build/reference_parms.json] [--only sop/mountain,...]

やること:
  1. 保存してある説明（<保存先>/localRAG/reference/node/*.json）のキーを集め、hython（Houdini）で、本物のパラメータ名を書き出す（dump_parms.py）
  2. 説明の中で、「」『』で囲まれた英字の名前（パラメータ名・メニュー項目）が、そのノードに本当にあるかを調べる
  3. ノードの種類が Houdini に無い（キーが違う・別の文脈のノード）ものも、見つける

点検に通らない説明は、公開しない（publish_reference.py が、この出力 build/reference_parms.json を読んで、公開前に同じ点検をかける）。
VEX は、関数が本当に在るか（vcc で、その名前の関数を呼ぶコードをコンパイルして、「未定義の関数」と言われないか）だけを点検する。
APEX・シェルフは、この点検の対象外（実機にパラメータの一覧が無い）。そのことは、結果にも表示する。
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "houdini" / "python_panels"))

import reference_data as rd  # noqa: E402

DEFAULT_OUT = ROOT / "build" / "reference_parms.json"
DEFAULT_CONFIG = Path.home() / ".houdini" / "rag_chatbot_config.json"
_QUOTED = re.compile(r"[「『]([^」』]{1,60})[」』]")


def _norm(text: str) -> str:
    return re.sub(r"[\s_\-]+", "", str(text or "")).lower()


def unknown_terms(entry: dict, names: list[str], node_types: list[str] | None = None) -> list[str]:
    """説明の中の、「」『』で囲まれた英字の名前のうち、本物のパラメータ名・メニュー項目（names）にも、ほかのノードの名前にも無いもの。"""
    known = [_norm(n) for n in names]
    others = {_norm(n) for n in (node_types or [])}
    bad: list[str] = []
    for field in rd.SECTION_KEYS:
        for term in _QUOTED.findall(str((entry or {}).get(field) or "")):
            if not re.search(r"[A-Za-z]", term) or re.search(r"[぀-ヿ一-鿿]", term):
                continue  # 日本語の言葉・日本語まじりの言い回しは、パラメータ名ではない（強調・用語。本物の名前は、英字だけ）
            norm = _norm(term)
            if not norm or norm in others or any(norm == k or (len(norm) >= 4 and norm in k) for k in known):
                continue
            if term not in bad:
                bad.append(term)
    return bad


def recipe_names(key: str) -> list[str]:
    """撮影のレシピで設定する値の名前（つなぐ前のノードのものも含む）。説明が、これを挙げても、嘘とは見なさない。"""
    sys.path.insert(0, str(ROOT / "scripts" / "reference_capture"))
    from recipes import RECIPES

    for recipe in RECIPES:
        if recipe["key"] == key:
            names: list[str] = [*recipe["parms"]]
            for spec in recipe.get("inputs") or [recipe["input"]]:
                for part in (spec, *(spec.get("after") or [])):
                    names += [*(part.get("parms") or {}), part["type"]]
            if recipe.get("sweep"):
                names.append(recipe["sweep"]["parm"])
            return names
    return []


def entry_problems(kind: str, key: str, entry: dict | None, parms: dict | None, extra_names: list[str] | None = None) -> list[str]:
    """この説明を公開してよいかの点検。問題の一覧（空なら、通過）。node と vex が対象（apex・シェルフは、点検の対象外で、空）。parms は dump_parms.py の出力（vex は "__vex__"）。
    extra_names: このノード以外で、説明が挙げてよい名前（撮影のレシピで、つなぐ前のノードに設定した値の名前など）。"""
    if kind == "vex":
        if not isinstance(parms, dict) or key not in (parms.get("__vex__") or {}):
            return ["VEX の関数が実在するか、確かめていません（scripts/audit_reference.py を先に実行してください）"]
        return [] if parms["__vex__"][key] else ["VEX に、この名前の関数がありません（vcc が、未定義の関数と言いました）"]
    if kind != "node":
        return []
    if not isinstance(parms, dict):
        return ["本物の Houdini と突き合わせていません（scripts/audit_reference.py を先に実行してください）"]
    if key not in parms:
        return ["突き合わせの結果に、この項目がありません（scripts/audit_reference.py をもう一度実行してください）"]
    info = parms[key]
    if info is None:
        return ["Houdini 22 に、この種類のノードがありません（キーが違う・別の文脈のノードの可能性）"]
    extra = list(extra_names) if extra_names is not None else recipe_names(key)
    bad = unknown_terms(entry or {}, list(info.get("names") or []) + extra, parms.get("__node_types__") or [])
    return [f"「{t}」は、このノードの本物のパラメータ名・メニュー項目にありません" for t in bad]


def load_parms(path: Path) -> dict | None:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def find_hython() -> str:
    env = os.environ.get("HYTHON")
    if env and Path(env).is_file():
        return env
    hits = sorted(glob.glob("C:/Program Files/Side Effects Software/Houdini */bin/hython.exe"))
    if not hits:
        raise SystemExit("hython が見つかりません（環境変数 HYTHON に、hython.exe のパスを入れてください）")
    return hits[-1]


def dump_parms(keys: list[str], out: Path) -> dict:
    """hython で、キーごとの本物のパラメータ名を書き出して、読み直す。"""
    out.parent.mkdir(parents=True, exist_ok=True)
    keys_file = out.with_suffix(".keys.json")
    keys_file.write_text(json.dumps(sorted(keys)), encoding="utf-8")
    try:
        proc = subprocess.run([find_hython(), str(ROOT / "scripts" / "reference_capture" / "dump_parms.py"), str(keys_file), str(out)],
                              capture_output=True, text=True, timeout=300)
    finally:
        keys_file.unlink(missing_ok=True)
    data = load_parms(out)
    if data is None:
        raise SystemExit(f"パラメータ名を書き出せませんでした: {proc.stderr[-300:] or proc.stdout[-300:]}")
    return data


def find_vcc() -> str:
    hython = Path(find_hython())
    return str(hython.with_name("vcc.exe"))


def vex_function_exists(name: str, vcc: str, workdir: Path) -> bool:
    """その名前の VEX の関数が在るか。引数なしで呼ぶコードをコンパイルして、「未定義の関数」と言われなければ、在る（引数が合わない、は、在る）。"""
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        return False
    workdir.mkdir(parents=True, exist_ok=True)
    source = workdir / f"probe_{name}.vfl"
    source.write_text(f"cvex t() {{ {name}(); }}\n", encoding="utf-8")
    try:
        proc = subprocess.run([vcc, "-c", "cvex", str(source), "-o", str(workdir / f"probe_{name}.vex")], capture_output=True, text=True, timeout=60)
    finally:
        source.unlink(missing_ok=True)
        (workdir / f"probe_{name}.vex").unlink(missing_ok=True)
    return "undefined function" not in (proc.stdout + proc.stderr)


def saved_vex_keys(base_dir: str, only: set[str]) -> list[str]:
    folder = Path(base_dir) / "localRAG" / "reference" / "vex"
    keys = [p.stem.replace("_", "/", 1) for p in sorted(folder.glob("*.json"))] if folder.is_dir() else []
    return [k for k in keys if not only or k in only]


def saved_node_keys(base_dir: str, only: set[str]) -> list[str]:
    folder = Path(base_dir) / "localRAG" / "reference" / "node"
    keys = [p.stem.replace("_", "/", 1) for p in sorted(folder.glob("*.json"))] if folder.is_dir() else []
    return [k for k in keys if not only or k in only]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="書き出し先（既定: build/reference_parms.json）")
    parser.add_argument("--only", default="", help="点検するキー（カンマ区切り）。省略すると、保存してある全部")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    args = parser.parse_args(argv)
    try:
        cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cfg = {}
    base_dir = str(os.environ.get("RAGREEL_BRIDGE_DIR") or cfg.get("local_bridge_dir") or "")
    only = {k.strip() for k in args.only.split(",") if k.strip()}
    keys = saved_node_keys(base_dir, only)
    vex_keys = saved_vex_keys(base_dir, only)
    if not keys and not vex_keys:
        print("点検する説明がありません")
        return 0
    out = Path(args.out)
    parms = dump_parms(keys, out) if keys else {}
    vcc = find_vcc()
    parms["__vex__"] = {key: vex_function_exists(key.split("/", 1)[1], vcc, out.parent / "_vcc") for key in vex_keys}
    out.write_text(json.dumps(parms, ensure_ascii=False), encoding="utf-8")
    problems = 0
    for kind, kind_keys in (("node", keys), ("vex", vex_keys)):
        for key in kind_keys:
            found = entry_problems(kind, key, rd.load_entry(base_dir, kind, key), parms)
            if found:
                problems += 1
                print(f"  NG  {key}")
                for line in found:
                    print(f"        {line}")
    print(f"点検 ノード {len(keys)} 件・VEX {len(vex_keys)} 件 / 問題あり {problems} 件（APEX・シェルフは、点検の対象外）")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
