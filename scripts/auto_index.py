"""
auto_index.py — Obsidian vault watchdog for mcp-rag-server (ChromaDB版)

Usage:
  cp scripts/auto_index.py ~/mcp-rag-server/
  cd ~/mcp-rag-server
  uv add watchdog pyyaml
  nohup python3 auto_index.py > auto_index.log 2>&1 &

Obsidian vault structure expected:
  obsidian-vault/
  ├── chat_logs/        ← namespace: chat_logs
  ├── tutorials/        ← namespace: tutorials
  ├── personal_notes/   ← namespace: personal_notes
  ├── private_docs/     ← namespace: private_docs
  └── _rag_dashboard/   ← 管理専用（インデックス対象外）

frontmatter の status フィールド:
  active   → インデックス化する（デフォルト）
  stale    → インデックス化するが警告ログ
  archived → スキップ
"""
import datetime
import subprocess
import time
from pathlib import Path

import yaml
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

# ===== 設定（環境に合わせて変更） =====
VAULT = Path(r"C:\Users\matuu\Desktop\GameDevelopment\DevelopmentRAGEnvironment\localRAG")
MCP_RAG_DIR = Path(r"C:\Users\matuu\Desktop\GameDevelopment\mcp-rag-server")
DASHBOARD = VAULT / "_rag_dashboard"

SKIP_DIRS = {"_rag_dashboard", "_templates", ".obsidian", ".processed"}
NAMESPACES = ["chat_logs", "tutorials", "personal_notes", "private_docs"]

DEBOUNCE_SECONDS = 3.0  # 連続変更時の待機時間


# ===== frontmatter ユーティリティ =====

def read_frontmatter(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8")
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                return yaml.safe_load(parts[1]) or {}
    except Exception:
        pass
    return {}


def write_frontmatter_field(path: Path, key: str, value) -> None:
    try:
        text = path.read_text(encoding="utf-8")
        str_value = str(value).lower() if isinstance(value, bool) else str(value)
        old_false = f"{key}: false"
        old_true = f"{key}: true"
        new = f"{key}: {str_value}"
        if old_false in text:
            path.write_text(text.replace(old_false, new, 1), encoding="utf-8")
        elif old_true in text:
            path.write_text(text.replace(old_true, new, 1), encoding="utf-8")
    except Exception as e:
        print(f"  frontmatter書き換えエラー: {e}")


def check_expires(path: Path, fm: dict) -> bool:
    """expires を過ぎていれば status を stale に変更して True を返す。"""
    expires = fm.get("expires")
    if not expires:
        return False
    try:
        exp_date = datetime.date.fromisoformat(str(expires))
        if datetime.date.today() > exp_date and fm.get("status") == "active":
            text = path.read_text(encoding="utf-8")
            path.write_text(
                text.replace("status: active", "status: stale", 1),
                encoding="utf-8",
            )
            print(f"  [期限切れ] {path.name} → status: stale")
            return True
    except Exception:
        pass
    return False


# ===== インデックス化 =====

def run_index() -> bool:
    """mcp-rag-server の差分インデックス化を実行する。"""
    result = subprocess.run(
        ["uv", "run", "python", "-m", "src.cli", "index", "--incremental"],
        cwd=str(MCP_RAG_DIR),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"  [エラー] インデックス化失敗:\n{result.stderr[:400]}")
        return False
    return True


# ===== ダッシュボード更新 =====

def update_dashboard() -> None:
    """_rag_dashboard/ 内の管理ノートをすべて更新する。"""
    DASHBOARD.mkdir(exist_ok=True)
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    counts: dict[str, int] = {}
    stale_files: list[str] = []

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

    # --- index_status.md ---
    rows = "\n".join(f"| `{ns}` | {cnt} |" for ns, cnt in counts.items())
    stale_section = (
        "## 要確認ファイル（stale）\n\n"
        + "\n".join(f"- {f}" for f in stale_files)
        if stale_files
        else "## 要確認ファイル\n\nなし"
    )

    status_md = f"""# RAG インデックス状態

最終更新: {now}
総ファイル数: {total}

## namespace 別件数

| namespace | ファイル数 |
|-----------|-----------|
{rows}

{stale_section}
"""
    (DASHBOARD / "index_status.md").write_text(status_md, encoding="utf-8")

    # --- namespace_map.md ---
    map_sections = []
    for ns in NAMESPACES:
        ns_dir = VAULT / ns
        lines = [f"## {ns}\n"]
        if ns_dir.exists():
            for f in sorted(ns_dir.glob("**/*.md")):
                fm = read_frontmatter(f)
                status = fm.get("status", "active")
                indexed = "✓" if fm.get("rag_indexed") else "○"
                tags = ", ".join(str(t) for t in fm.get("tags", []))
                tag_str = f" — {tags}" if tags else ""
                lines.append(f"- {indexed} [[{f.stem}]] `{status}`{tag_str}")
        else:
            lines.append("_（フォルダなし）_")
        map_sections.append("\n".join(lines))

    map_md = f"# namespace マップ\n\n最終更新: {now}\n\n" + "\n\n".join(map_sections) + "\n"
    (DASHBOARD / "namespace_map.md").write_text(map_md, encoding="utf-8")

    print(f"  ダッシュボード更新完了: {now}")


def log_cleanup(filename: str, action: str) -> None:
    log_path = DASHBOARD / "cleanup_log.md"
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = f"- {now} `{action}` {filename}\n"
    existing = log_path.read_text(encoding="utf-8") if log_path.exists() else "# クリーンアップログ\n\n"
    log_path.write_text(existing + entry, encoding="utf-8")


# ===== watchdog ハンドラ =====

class VaultHandler(FileSystemEventHandler):
    def __init__(self) -> None:
        super().__init__()
        self._last_run: float = 0.0

    def _should_skip(self, path: Path) -> bool:
        return any(s in path.parts for s in SKIP_DIRS)

    def _debounce_index(self, path: Path, fm: dict) -> None:
        """連続変更が DEBOUNCE_SECONDS 以内なら再実行しない。"""
        now = time.monotonic()
        if now - self._last_run < DEBOUNCE_SECONDS:
            return
        self._last_run = now

        if run_index():
            write_frontmatter_field(path, "rag_indexed", True)
            update_dashboard()

    def on_modified(self, event) -> None:
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
        self._debounce_index(path, fm)

        if fm.get("status") == "stale":
            print(f"  [警告] {path.name} は期限切れ（stale）です。内容を確認してください。")

    def on_deleted(self, event) -> None:
        if event.is_directory:
            return
        path = Path(event.src_path)
        if self._should_skip(path) or path.suffix != ".md":
            return
        print(f"削除検知: {path.name}")
        update_dashboard()
        log_cleanup(path.name, "deleted")

    def on_created(self, event) -> None:
        if event.is_directory:
            return
        path = Path(event.src_path)
        if self._should_skip(path) or path.suffix != ".md":
            return
        print(f"新規作成: {path.name}")


# ===== エントリポイント =====

if __name__ == "__main__":
    DASHBOARD.mkdir(exist_ok=True)
    print(f"監視開始: {VAULT}")
    print(f"スキップディレクトリ: {SKIP_DIRS}")

    # 起動時: 期限切れチェック + ダッシュボード初期更新
    for ns in NAMESPACES:
        ns_dir = VAULT / ns
        if ns_dir.exists():
            for f in ns_dir.glob("**/*.md"):
                check_expires(f, read_frontmatter(f))
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
