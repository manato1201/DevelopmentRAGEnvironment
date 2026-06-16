# Obsidian × LocalRAG 管理設計ドキュメント

**対象:** mcp-rag-server（pgvector）の長期管理  
**目的:** Obsidianを可視化・管理インターフェースとして活用し、インデックス状態を常に把握できる状態にする  
**更新日:** 2026-06-10

---

## 目次

1. [設計思想](#1-設計思想)
2. [vault構造設計](#2-vault構造設計)
3. [SOURCE_DIR設定](#3-source_dir設定)
4. [frontmatterによる鮮度管理](#4-frontmatterによる鮮度管理)
5. [watchdog改良版（自動インデックス + 書き戻し）](#5-watchdog改良版)
6. [ダッシュボードノート仕様](#6-ダッシュボードノート仕様)
7. [運用フロー](#7-運用フロー)
8. [トラブルシューティング](#8-トラブルシューティング)

---

## 1. 設計思想

### 現状の問題

| 問題 | 影響 |
|------|------|
| 何がインデックスされているか不明 | 古い情報や重複が気づかず蓄積する |
| pgvectorの中身を確認する術がない | 長期使用で検索精度が劣化しても原因不明 |
| namespace別の状態が把握できない | どこに何件あるか分からない |
| 手動CLIでインデックス化が必要 | 更新漏れが発生しやすい |

### 解決方針

**Obsidian vault = RAGのソースディレクトリ**として扱うことで、ファイルツリー自体がインデックス対象の一覧になる。加えてwatchdogがインデックス処理の度にObsidian内の管理ノートを自動更新することで、pgvectorの状態をObsidianから常に確認できるようにする。

```
Obsidian（可視化・管理）
    ↕ SOURCE_DIR
mcp-rag-server（インデックス化）
    ↕ 書き戻し
Obsidian _rag_dashboard/（状態管理）
```

---

## 2. vault構造設計

### ディレクトリ構成

```
obsidian-vault/
├── chat_logs/              ← namespace: chat_logs
│   ├── 2026-06-10_claude.md
│   └── 2026-06-11_claude.md
├── tutorials/              ← namespace: tutorials
│   ├── houdini_vex_wrangle.md
│   └── houdini_voronoi.md
├── personal_notes/         ← namespace: personal_notes
│   ├── progress/
│   │   └── 2026-06-10_daily.md
│   └── ideas/
│       └── thesis_memo.md
├── private_docs/           ← namespace: private_docs
│   └── draft_game_design.md
├── _rag_dashboard/         ← 管理専用（インデックス対象外）
│   ├── index_status.md     ← 自動生成: インデックス状態
│   ├── namespace_map.md    ← 自動生成: ファイル一覧
│   └── cleanup_log.md      ← 自動生成: 削除・更新履歴
└── _templates/             ← テンプレート（任意）
    ├── chat_log.md
    └── tutorial.md
```

### ディレクトリとnamespaceの対応

| フォルダ | namespace | 内容 |
|---------|-----------|------|
| `chat_logs/` | `chat_logs` | Claude等との会話ログ |
| `tutorials/` | `tutorials` | Houdiniチュートリアル生成結果 |
| `personal_notes/` | `personal_notes` | Obsidianノート・個人進捗 |
| `private_docs/` | `private_docs` | 共有NG文書・草稿 |
| `_rag_dashboard/` | — | 管理専用（スキャン除外） |

### 除外設定

`_rag_dashboard/` と `_templates/` はアンダースコア始まりでwatchdog側でスキップする。`.obsidian/`（設定ファイル）も同様に除外。

---

## 3. SOURCE_DIR設定

`.env` を以下のように設定する：

```bash
# mcp-rag-server/.env

POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER=postgres
POSTGRES_PASSWORD=password
POSTGRES_DB=ragdb

# Obsidian vault を SOURCE_DIR に指定
SOURCE_DIR=/home/tk_render/obsidian-vault
PROCESSED_DIR=/home/tk_render/obsidian-vault/_rag_dashboard/.processed

EMBEDDING_MODEL=intfloat/multilingual-e5-large
EMBEDDING_DIM=1024
EMBEDDING_PREFIX_QUERY="query: "
EMBEDDING_PREFIX_EMBEDDING="passage: "
```

> **注意:** `PROCESSED_DIR` を `_rag_dashboard/` 配下に置くことで、処理済みファイルの記録もvault内で管理できる。

---

## 4. frontmatterによる鮮度管理

### 標準テンプレート

各ノートの先頭に以下のYAMLフロントマターを付ける：

```yaml
---
title: Houdini VEX wrangle 基礎メモ
namespace: tutorials
status: active
created: 2026-06-10
updated: 2026-06-10
expires: 2026-12-10
tags: [houdini, vex, tutorial]
rag_indexed: false
---
```

### statusの値と挙動

| status | 意味 | watchdogの挙動 |
|--------|------|----------------|
| `active` | 有効（デフォルト） | インデックス化する |
| `stale` | 鮮度切れ（要確認） | インデックス化するが警告ログ |
| `archived` | 無効化済み | インデックス化をスキップ |

### expiresによる自動フラグ

watchdogは起動時に `expires` を過ぎたノートを検知して `status: stale` に自動変更する。Obsidianでは `status: stale` のノートが一覧に表示されるので、定期的に確認して削除または更新する。

### テンプレートファイル

```bash
# _templates/tutorial.md
---
title: 
namespace: tutorials
status: active
created: {{date}}
updated: {{date}}
expires: {{date+180d}}
tags: []
rag_indexed: false
---

## 概要

## 手順

## メモ
```

---

## 5. watchdog改良版

### auto_index.py（完全版）

```python
"""
Obsidian vault を監視して mcp-rag-server を自動インデックス化するスクリプト。
起動方法: python3 auto_index.py
実行場所: ~/mcp-rag-server/
"""
import subprocess
import time
import datetime
from pathlib import Path

import yaml
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# ===== 設定 =====
VAULT = Path("/home/tk_render/obsidian-vault")
MCP_RAG_DIR = Path("/home/tk_render/mcp-rag-server")
DASHBOARD = VAULT / "_rag_dashboard"
SKIP_DIRS = {"_rag_dashboard", "_templates", ".obsidian", ".processed"}
NAMESPACES = ["chat_logs", "tutorials", "personal_notes", "private_docs"]


# ===== frontmatter ユーティリティ =====

def read_frontmatter(path: Path) -> dict:
    """YAMLフロントマターを読み込む"""
    try:
        text = path.read_text(encoding="utf-8")
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 2:
                return yaml.safe_load(parts[1]) or {}
    except Exception:
        pass
    return {}


def write_frontmatter_field(path: Path, key: str, value) -> None:
    """フロントマターの特定フィールドを書き換える"""
    try:
        text = path.read_text(encoding="utf-8")
        old = f"{key}: false" if value is True else f"{key}: true"
        new = f"{key}: {str(value).lower()}"
        if old in text:
            path.write_text(text.replace(old, new, 1), encoding="utf-8")
    except Exception as e:
        print(f"  frontmatter書き換えエラー: {e}")


def check_expires(path: Path, fm: dict) -> bool:
    """expires を過ぎていれば status を stale に変更して True を返す"""
    expires = fm.get("expires")
    if not expires:
        return False
    try:
        exp_date = datetime.date.fromisoformat(str(expires))
        if datetime.date.today() > exp_date and fm.get("status") == "active":
            text = path.read_text(encoding="utf-8")
            path.write_text(
                text.replace("status: active", "status: stale", 1),
                encoding="utf-8"
            )
            print(f"  [期限切れ] {path.name} → status: stale")
            return True
    except Exception:
        pass
    return False


# ===== インデックス化 =====

def run_index() -> bool:
    """mcp-rag-server の差分インデックス化を実行する"""
    result = subprocess.run(
        ["uv", "run", "python", "-m", "src.cli", "index"],
        cwd=str(MCP_RAG_DIR),
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        print(f"  [エラー] インデックス化失敗: {result.stderr[:200]}")
        return False
    return True


# ===== ダッシュボード更新 =====

def update_dashboard() -> None:
    """_rag_dashboard/ 内の管理ノートをすべて更新する"""
    DASHBOARD.mkdir(exist_ok=True)
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    # --- index_status.md ---
    counts = {}
    stale_files = []
    for ns in NAMESPACES:
        ns_dir = VAULT / ns
        if not ns_dir.exists():
            counts[ns] = 0
            continue
        files = list(ns_dir.glob("**/*.md"))
        counts[ns] = len(files)
        for f in files:
            fm = read_frontmatter(f)
            if fm.get("status") == "stale":
                stale_files.append(f"[[{f.stem}]]")

    total = sum(counts.values())
    status_md = f"""# RAG インデックス状態

最終更新: {now}  
総ファイル数: {total}

## namespace 別件数

| namespace | ファイル数 |
|-----------|-----------|
"""
    for ns, count in counts.items():
        status_md += f"| `{ns}` | {count} |\n"

    if stale_files:
        status_md += f"""
## 要確認ファイル（stale）

以下のノートは `expires` を過ぎています。削除または更新してください。

"""
        for f in stale_files:
            status_md += f"- {f}\n"
    else:
        status_md += "\n## 要確認ファイル\n\nなし\n"

    (DASHBOARD / "index_status.md").write_text(status_md, encoding="utf-8")

    # --- namespace_map.md ---
    map_md = f"# namespace マップ\n\n最終更新: {now}\n\n"
    for ns in NAMESPACES:
        ns_dir = VAULT / ns
        map_md += f"## {ns}\n\n"
        if ns_dir.exists():
            files = sorted(ns_dir.glob("**/*.md"))
            for f in files:
                fm = read_frontmatter(f)
                status = fm.get("status", "active")
                indexed = "✓" if fm.get("rag_indexed") else "○"
                tags = ", ".join(fm.get("tags", []))
                map_md += f"- {indexed} [[{f.stem}]] `{status}`"
                if tags:
                    map_md += f" — {tags}"
                map_md += "\n"
        else:
            map_md += "_（フォルダなし）_\n"
        map_md += "\n"

    (DASHBOARD / "namespace_map.md").write_text(map_md, encoding="utf-8")
    print(f"  ダッシュボード更新完了: {now}")


# ===== watchdog ハンドラ =====

class VaultHandler(FileSystemEventHandler):
    def _should_skip(self, path: Path) -> bool:
        return any(s in path.parts for s in SKIP_DIRS)

    def on_modified(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path)
        if self._should_skip(path) or path.suffix != ".md":
            return

        fm = read_frontmatter(path)
        check_expires(path, fm)

        if fm.get("status") == "archived":
            print(f"  スキップ (archived): {path.name}")
            return

        print(f"変更検知: {path.name}")
        if run_index():
            write_frontmatter_field(path, "rag_indexed", True)
            update_dashboard()

    def on_deleted(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path)
        if self._should_skip(path) or path.suffix != ".md":
            return
        print(f"削除検知: {path.name} → ダッシュボード更新")
        update_dashboard()
        log_cleanup(path.name, "deleted")

    def on_created(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path)
        if self._should_skip(path) or path.suffix != ".md":
            return
        print(f"新規作成: {path.name}")


def log_cleanup(filename: str, action: str) -> None:
    log_path = DASHBOARD / "cleanup_log.md"
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = f"- {now} `{action}` {filename}\n"
    if log_path.exists():
        log_path.write_text(log_path.read_text() + entry, encoding="utf-8")
    else:
        log_path.write_text(f"# クリーンアップログ\n\n{entry}", encoding="utf-8")


# ===== エントリポイント =====

if __name__ == "__main__":
    DASHBOARD.mkdir(exist_ok=True)
    print(f"監視開始: {VAULT}")
    print(f"スキップディレクトリ: {SKIP_DIRS}")

    # 起動時に期限切れチェックとダッシュボード更新
    for ns in NAMESPACES:
        for f in (VAULT / ns).glob("**/*.md") if (VAULT / ns).exists() else []:
            fm = read_frontmatter(f)
            check_expires(f, fm)
    update_dashboard()

    observer = Observer()
    observer.schedule(VaultHandler(), path=str(VAULT), recursive=True)
    observer.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
    print("監視終了")
```

### インストールと起動

```bash
# 依存追加
cd ~/mcp-rag-server
uv add watchdog pyyaml

# バックグラウンドで起動
nohup python3 auto_index.py > auto_index.log 2>&1 &
echo "PID: $!"

# ログ確認
tail -f auto_index.log
```

---

## 6. ダッシュボードノート仕様

### index_status.md（自動生成）

```markdown
# RAG インデックス状態

最終更新: 2026-06-10 14:32  
総ファイル数: 47

## namespace 別件数

| namespace | ファイル数 |
|-----------|-----------|
| `chat_logs` | 12 |
| `tutorials` | 8 |
| `personal_notes` | 24 |
| `private_docs` | 3 |

## 要確認ファイル（stale）

- [[houdini_vex_2025]]
- [[unity_shader_old]]
```

### namespace_map.md（自動生成）

```markdown
# namespace マップ

最終更新: 2026-06-10 14:32

## tutorials

- ✓ [[houdini_vex_wrangle]] `active` — houdini, vex, tutorial
- ✓ [[houdini_voronoi]] `active` — houdini, geometry
- ○ [[unity_compute_shader]] `active` — unity, compute

（✓ = インデックス済み、○ = 未インデックス）
```

---

## 7. 運用フロー

### 日常的な使い方

```
1. Obsidianでノートを作成・編集（frontmatterにnamespaceを記載）
      ↓ watchdogが自動検知
2. mcp-rag-serverが差分インデックス化
      ↓ 処理完了後
3. _rag_dashboard/ が自動更新される
      ↓
4. Obsidianのindex_status.mdで状態確認
```

### 月次メンテナンス

```
1. index_status.md の「要確認ファイル」を確認
2. stale なノートを開いて内容を精査
3. 不要なら削除、まだ使えるなら updated / expires を更新
4. status を active に戻す
```

### 強制再インデックス（必要な場合）

```bash
cd ~/mcp-rag-server
uv run python -m src.cli index --force
```

---

## 8. トラブルシューティング

### watchdogが反応しない

```bash
# プロセス確認
ps aux | grep auto_index

# 再起動
kill <PID>
nohup python3 auto_index.py > auto_index.log 2>&1 &
```

### frontmatterのパースエラー

YAMLの記法ミスが原因。以下で検証できる：

```python
import yaml
text = open("problematic_note.md").read()
fm = yaml.safe_load(text.split("---")[1])
print(fm)
```

### ダッシュボードが更新されない

```bash
# 手動でダッシュボード更新を実行
python3 -c "
import sys; sys.path.insert(0, '.')
from auto_index import update_dashboard
update_dashboard()
"
```
