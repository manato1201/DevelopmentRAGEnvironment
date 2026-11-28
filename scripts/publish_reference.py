"""Reference の説明と画像・動きを、Cloudflare に公開する（2026-11-19）。開発側の道具（管理者のキーが要る）。

  uv run python scripts/publish_reference.py [--media build/reference_media] [--only sop/mountain,vex/chf] [--dry-run]

材料:
  ・説明 … 開発者モード（RAGREEL_REFERENCE_AUTHOR=1）で、Reference タブの「説明を作る」で作って保存したもの
           （<保存先>/localRAG/reference/<種類>/<キー>.json）。説明が無い項目は、公開しない（画像だけでは置けない）
  ・画像 … scripts/reference_capture/capture.py が撮ったもの（<media>/<種類>/<キー>/before.png・after.png・node.png・clip.gif）
やること: 画像を、内容のハッシュ入りの名前（<種類>/<キー>/<役割>.<ハッシュ8桁>.<拡張子>）で置く → 説明を置く（版が 1 つ上がる）。
  ・画像の名前にハッシュを入れるので、画像を撮り直すと、端末は新しい画像を取り直す（同じ名前のままだと、端末の古い保存が使われる）
  ・接続先・キー・保存先は、パネルの設定（~/.houdini/rag_chatbot_config.json の cf_url・cf_api_key・local_bridge_dir）から、この中だけで読む（表示しない）。
    --config で別の設定ファイルも指せる
  ・--dry-run は、通信せずに、何を公開するかだけを表示する
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "houdini" / "python_panels"))

sys.path.insert(0, str(ROOT / "scripts"))

import reference_data as rd  # noqa: E402
import reference_remote as rr  # noqa: E402
from audit_reference import DEFAULT_OUT as DEFAULT_PARMS  # noqa: E402
from audit_reference import entry_problems, load_parms  # noqa: E402

ROLE_FILES = (("where", "where.png"), ("before", "before.png"), ("after", "after.png"), ("node", "node.png"), ("clip", "clip.gif"))
ROLE_LABELS = {"where": "操作する場所", "before": "適用前", "after": "適用後", "node": "ノード画面", "clip": "適用の動き"}
DEFAULT_CONFIG = Path.home() / ".houdini" / "rag_chatbot_config.json"


def media_dir(media_root: Path, kind: str, key: str) -> Path:
    return media_root / kind / rd.slug(key)


def collect_media(media_root: Path | None, kind: str, key: str) -> list[dict]:
    """撮った画像・動きを、公開用の形にする: [{"id", "role", "label", "path"}]。ファイルが無い役割は、飛ばす。"""
    if media_root is None:
        return []
    folder = media_dir(media_root, kind, key)
    out = []
    for role, filename in ROLE_FILES:
        path = folder / filename
        if not path.is_file() or path.stat().st_size == 0:
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()[:8]
        ext = path.suffix.lower()
        out.append({"id": f"{kind}/{rd.slug(key)}/{role}.{digest}{ext}", "role": role, "label": ROLE_LABELS[role], "path": path})
    return out


def make_item(kind: str, key: str) -> dict:
    """一覧データに無い項目を、キーから作る（題名は、名前の頭を大文字にしたもの）。"""
    name = key.split("/")[-1]
    return {"kind": kind, "key": key, "name": name, "label": name.replace("_", " ").title(), "context": key.split("/")[0] if kind in ("node", "apex") else kind}


def media_keys(media_root: Path | None) -> list[tuple[str, str]]:
    """撮影の出力（<media>/<種類>/<キー>/meta.json）から、(種類, キー) の一覧。"""
    out = []
    if media_root is None or not media_root.is_dir():
        return out
    for meta in sorted(media_root.glob("*/*/meta.json")):
        try:
            key = json.loads(meta.read_text(encoding="utf-8")).get("key")
        except (OSError, ValueError, AttributeError):
            continue
        if isinstance(key, str) and "/" in key:
            out.append((meta.parent.parent.name, key))
    return out


def find_targets(base_dir: str, media_root: Path | None, only: set[str]) -> list[dict]:
    """公開する項目: 保存した説明（または、撮った画像）がある項目。only があれば、そのキー（例: sop/mountain）だけ。"""
    targets = []
    seen: set[tuple[str, str]] = set()
    items = [i for kind, _ in rd.KINDS for i in rd.catalog(kind)]
    for item in items:
        if only and item["key"] not in only:
            continue
        entry = rd.load_entry(base_dir, item["kind"], item["key"]) if base_dir else None
        media = collect_media(media_root, item["kind"], item["key"])
        if entry is None and not media:
            continue
        seen.add((item["kind"], item["key"]))
        targets.append({"item": item, "entry": entry, "media": media})
    # 一覧データ（公式ドキュメントの索引）に無い項目（Mountain・Twist など）は、撮影のフォルダの meta.json にあるキーから探す
    for kind, key in media_keys(media_root):
        if (kind, key) in seen or (only and key not in only):
            continue
        seen.add((kind, key))
        targets.append({"item": make_item(kind, key), "entry": rd.load_entry(base_dir, kind, key) if base_dir else None, "media": collect_media(media_root, kind, key)})
    # 一覧に無い名前（シェルフ・自分で作った項目）は、保存した説明のファイル名から探す
    kind_dirs = Path(base_dir) / "localRAG" / "reference" if base_dir else None
    if kind_dirs and kind_dirs.is_dir():
        for kind, _ in rd.KINDS:
            for path in sorted((kind_dirs / kind).glob("*.json")) if (kind_dirs / kind).is_dir() else []:
                if any(rd.slug(t["item"]["key"]) == path.stem and t["item"]["kind"] == kind for t in targets):
                    continue  # 保存した説明のファイル名は、キーの "/" を "_" にしたもの（sop_mountain）。すでに、対象に入っているものは、飛ばす
                if only and path.stem.replace("_", "/", 1) not in only:
                    continue  # キーを指定したときは、そのキーだけ（一覧に無い名前でも、指定されていれば公開する。2026-11-21）
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if isinstance(data, dict) and any(str(data.get(k) or "").strip() for k in rd.SECTION_KEYS):
                    key = path.stem.replace("_", "/", 1)  # sop_mountain → sop/mountain、shelf_billowy_smoke → shelf/billowy_smoke
                    targets.append({"item": make_item(kind, key), "entry": {k: data.get(k, "") for k in rd.SECTION_KEYS}, "media": collect_media(media_root, kind, key)})
    return targets


def publish_target(cfg: dict, target: dict, opener=None, parms: dict | None = None, audit: bool = True) -> dict:
    """1 項目を公開する（画像 → 説明の順）。失敗は例外のまま。戻り値: {"key", "version", "media"}。
    audit: 公開の前に、本物の Houdini と突き合わせる点検（audit_reference.py）に通らない説明は、公開しない（ValueError）。parms は、その材料。"""
    item, entry = target["item"], target["entry"]
    if entry is None:
        raise ValueError("保存した説明がありません（Reference タブの「説明を作る」で作ってください）")
    entry = rd.sanitize_entry(entry)  # 保存済みの説明にも、同じ点検をかける（調べた経過の混ざった欄は、空にする）
    if entry is None:
        raise ValueError("説明として使えません（「資料に無い」など、調べた経過が混ざっています。作り直すか、公開しないでください）")
    if audit:
        problems = entry_problems(item["kind"], item["key"], entry, parms)
        if problems:
            raise ValueError("本物の Houdini との点検に通りません: " + "; ".join(problems)[:300])
    for m in target["media"]:
        rr.publish_media(cfg, m["id"], Path(m["path"]).read_bytes(), opener=opener)
    media = [{"id": m["id"], "role": m["role"], "label": m["label"]} for m in target["media"]]
    result = rr.publish_entry(cfg, item["kind"], item["key"], item.get("label") or item.get("name") or "", entry, media, opener=opener)
    return {"key": item["key"], "version": result.get("version"), "media": len(media)}


def attach_conditions(targets: list[dict], path: Path) -> int:
    """撮影のネットワークの条件（同じ結果にする条件）を、説明に付ける。付けた数を返す。ファイルが無い・読めないときは、付けない。
    条件は、撮影のレシピと同じ作り方で、実機（hython）で組んで書き出したもの（dump_conditions.py）。キーは、レシピのキー（sop/vellumsolver など）。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    count = 0
    for t in targets:
        cond = data.get(t["item"]["key"]) if isinstance(data, dict) else None
        if t["entry"] is not None and isinstance(cond, dict) and "error" not in cond:
            t["entry"] = {**t["entry"], "conditions": cond}
            count += 1
    return count


def load_config(path: Path) -> dict:
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"設定を読めません（{path}）: {exc.__class__.__name__}")
    return cfg if isinstance(cfg, dict) else {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--media", default="", help="撮影の出力先（capture.py の --out）。省略すると、画像なし")
    parser.add_argument("--set", default="", choices=("", "recipes", "nodes", "vex", "all"),
                        help="build_reference_entries.py の --set と同じ範囲だけ公開する（試作や古い保存を、公開しないため）。省略すると、保存してある全部")
    parser.add_argument("--only", default="", help="公開するキー（カンマ区切り。例: sop/mountain,vex/chf）。省略すると、保存してある全部")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="パネルの設定ファイル")
    parser.add_argument("--dry-run", action="store_true", help="通信せずに、公開する内容だけを表示")
    parser.add_argument("--parms", default=str(DEFAULT_PARMS), help="audit_reference.py の出力（本物のパラメータ名）。公開の前の点検に使う")
    parser.add_argument("--skip-audit", action="store_true", help="点検を省く（通常は、使わない。嘘の内容が公開される恐れがある）")
    parser.add_argument("--conditions", default=str(ROOT / "build" / "reference_conditions.json"),
                        help="同じ結果にする条件（reference_capture/dump_conditions.py の出力）。あれば、説明に付けて公開する（2026-11-28）")
    parser.add_argument("--unpublish", default="", help="公開済みの説明を取り下げる（kind/key をカンマ区切り。例: node/sop/transform,vex/chf）。ほかは何もしない")
    args = parser.parse_args(argv)
    cfg = load_config(Path(args.config))
    base_dir = str(os.environ.get("RAGREEL_BRIDGE_DIR") or cfg.get("local_bridge_dir") or "")
    cfg = {**cfg, "local_bridge_dir": base_dir}
    if args.unpublish:
        for ref in [r.strip() for r in args.unpublish.split(",") if r.strip()]:
            kind, _, key = ref.partition("/")
            try:
                done = rr.delete_entry(cfg, kind, key)
                print(f"  取り下げ {ref}: {done.get('deleted', 0)} 件")
            except Exception as exc:  # noqa: BLE001
                print(f"  NG  {ref}: {rr.error_text(exc)}")
        return 0
    media_root = Path(args.media) if args.media else None
    only = {k.strip() for k in args.only.split(",") if k.strip()}
    if args.set:
        sys.path.insert(0, str(ROOT / "scripts"))
        from build_reference_entries import select_items

        in_set = {i["key"] for i in select_items(args.set, set())}
        only = (only & in_set) if only else in_set
    targets = find_targets(base_dir, media_root, only)
    attach_conditions(targets, Path(args.conditions))
    if not targets:
        print("公開するものがありません（説明は、開発者モードの Reference タブで作れます）")
        return 0
    parms = load_parms(Path(args.parms))
    if not args.skip_audit and not args.dry_run and parms is None and any(t["item"]["kind"] in ("node", "vex") for t in targets):
        raise SystemExit("公開の前の点検に使う、本物のパラメータ名がありません。先に、scripts/audit_reference.py を実行してください"
                         "（点検を省くなら --skip-audit。ただし、嘘の内容が公開される恐れがあります）")
    print(f"{len(targets)} 件" + ("（dry-run: 通信しません）" if args.dry_run else ""))
    failed = skipped = 0
    for t in targets:
        item = t["item"]
        has = "説明あり" if t["entry"] else "説明なし"
        roles = "・".join(m["role"] for m in t["media"]) or "画像なし"
        if args.dry_run:
            print(f"  {item['kind']}/{item['key']:<28} {has} / {roles}")
            continue
        try:
            result = publish_target(cfg, t, parms=parms, audit=not args.skip_audit)
            print(f"  OK  {item['key']:<28} 版 {result['version']} / 画像 {result['media']} 件")
        except ValueError as exc:  # 公開しない（説明が無い・使えない）。失敗ではない
            skipped += 1
            print(f"  --  {item['key']:<28} 公開しません: {exc}")
        except Exception as exc:  # noqa: BLE001 -- 1 件の失敗で、全体を止めない
            failed += 1
            print(f"  NG  {item['key']:<28} {rr.error_text(exc)}")
    print(f"完了: 公開 {len(targets) - failed - skipped} / 公開しない {skipped} / 失敗 {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
