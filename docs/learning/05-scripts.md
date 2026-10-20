# 05. Script編

**更新日:** 2026-10-17　**目安:** 2〜3日　**前提:** [01. 常識編](01-common-knowledge.md)、[02. 基礎編](02-fundamentals.md)
**ゴール:** コマンド・スクリプトを**読んで意味が分かり、安全に書ける**。プロジェクトの`scripts/`と`wrangler`を使いこなせる。

---

## 1. シェルの基本（PowerShellとBash）

このプロジェクトでは、**Windows 11のPowerShellが主**。Git Bashなど、Bash（POSIX）系も使える。**書き方が違う**ので、まず違いを知る。

| 項目 | PowerShell | Bash |
|---|---|---|
| 変数 | `$name = "x"` | `name="x"`（`=`の前後に空白を入れない） |
| 環境変数（設定） | `$env:ANTHROPIC_API_KEY = "…"` | `export ANTHROPIC_API_KEY="…"` |
| 環境変数（読む） | `$env:NAME` | `$NAME` |
| パスの区切り | `C:\Users\x`（`/`も通る） | `/c/Users/x`（Git Bashの場合） |
| 続きの行 | 行末に`` ` ``（バッククォート） | 行末に`\` |
| 出力のつなぎ | `cmd1 \| cmd2`（オブジェクトを渡す） | `cmd1 \| cmd2`（テキストを渡す） |
| 文字列の引用 | `'…'`は、そのまま／`"…"`は、`$var`を展開 | 同じ |
| 条件・繰り返し | `if (…) { }`、`foreach ($x in $xs) { }` | `if […]; then … fi`、`for x in …; do … done` |
| コマンドの結果コード | `$LASTEXITCODE` | `$?` |
| ヒアドキュメント（複数行） | `@' … '@` | `<<'EOF' … EOF` |

**ハマりどころ**
- **バックスラッシュとクォート:** 複数行の文字列やパスの中の`\`は、シェルによって解釈が変わる。**複雑な文字列は、ファイルに書いてから使う**方が確実。
- **スペースを含むパス**は、必ず`"…"`で囲む（`C:\Users\my name\`）。
- **PowerShellのスクリプト実行は、既定で制限されている**ことがある（実行ポリシー）。`.ps1`が動かないときは、これを疑う。
- **日本語の出力が文字化け**するときは、コンソールの文字コードの問題（ファイルは、UTF-8のままで正しいことが多い）。

## 2. 安全なスクリプトを書く原則

1. **読むだけのモードを先に作る**（`--dry-run`）。何をするかを表示して、実行しない。
2. **危険な操作の前に、確認する。** 本番を変更する・消す操作は、自動で「はい」にしない。
3. **冪等にする。** 二度実行しても、壊れない（既にあれば何もしない）。
4. **秘密を、引数・ログ・ファイルに出さない。** 環境変数から読み、表示するときは、先頭数文字だけ。
5. **対象を、明示的に指定させる。** 本番／ローカル（`--remote`の有無）、namespace、ユーザー。省略時に「全部」にしない。
6. **失敗したら、止まる。** 途中の失敗を無視して、続けない。（Bashは`set -e`、PowerShellは`$ErrorActionPreference = "Stop"`）
7. **何をしたか、ログを残す。** 後から、確認できるように。
8. **変更の前に、戻す方法を用意する。** バックアップ、`git`。
9. **使い捨てのスクリプトでも、消す・上書きする前に、対象を確認する。**（`ls`で中身を見てから`rm`）

> **やってはいけない例:** `echo y | wrangler d1 migrations apply … --remote`。確認プロンプトに自動で「はい」を答えてしまい、**何が適用されるかを見ずに、本番を変更する**。**一覧を見て（`migrations list`）、確認プロンプトには人が答える。**

## 3. `wrangler`コマンド集（Cloudflare）

**`cloudflare-rag-poc/`の中で実行する。** `npx wrangler …`（npmで入れた版を使う）。

| やりたいこと | コマンド | 本番に影響 |
|---|---|---|
| ログイン確認 | `npx wrangler whoami` | なし |
| ローカルで起動 | `npm run dev` | なし |
| 型チェック | `npm run typecheck` | なし |
| 未適用のマイグレーションを見る | `npx wrangler d1 migrations list rag-poc-db --remote` | なし（読むだけ） |
| ローカルDBにマイグレーション | `npm run db:migrate:local` | なし |
| **本番にマイグレーション** | `npm run db:migrate:remote` | **あり**（確認プロンプトに自分で答える） |
| **本番にデプロイ** | `npm run deploy` | **あり** |
| 直前の版に戻す | `npx wrangler rollback` | **あり** |
| 本番DBを読む | `npx wrangler d1 execute rag-poc-db --remote --command "SELECT …"` | なし（読むだけ。**書き込みのSQLなら、あり**） |
| ローカルDBを読む | `npx wrangler d1 execute rag-poc-db --command "SELECT …"` | なし |
| JSONで結果を得る | 上に`--json`を足す | |
| **DBの負荷を調べる**（どのSQLが何行読んだか） | `npx wrangler d1 insights rag-poc-db --timePeriod 1d` | なし |
| ログをリアルタイムで見る | `npx wrangler tail` | なし |
| 秘密の一覧（名前のみ） | `npx wrangler secret list` | なし |
| 秘密を登録・更新 | `npx wrangler secret put NAME` | **あり** |

**鉄則**
- **`--remote`の有無を、毎回確認する。** 付ければ本番、付けなければローカルの空DB。（「データが無い」と勘違いする事故の原因）
- **「読むだけ」と書いたコマンドでも、`d1 execute`に`INSERT`/`UPDATE`/`DELETE`を渡せば、書き込む。** SQLの中身を、実行前に読む。
- **読み取りも、D1の枠を使う。** 大きな表に`SELECT *`（全件）は、しない。`LIMIT`と`WHERE`、`COUNT(*)`を使う。

## 4. プロジェクトの`scripts/`の地図

実行は、リポジトリのルートから`uv run python scripts/<名前>.py`。

| 目的 | スクリプト | 補足 |
|---|---|---|
| **ローカルRAGの検索・索引** | `rag_cli.py`（`index`/`clear`/`count`）、`auto_index.py`（ファイル監視で自動索引） | まず`rag_cli.py index` |
| **UnityやHoudiniとつなぐ** | `rag_local_bridge.py`（`localhost:8766`のHTTPブリッジ） | `ANTHROPIC_API_KEY`が必要 |
| **ローカルRAGの中身** | `rag_service.py`（統合層）、`vector_database.py`（ChromaDB＋BM25）、`embedding_generator.py`、`document_processor.py`、`document_pipeline.py` | |
| **グラフ表示用のデータ** | `rag_graph_export.py` | `graph_data.json`を作る |
| **認証・権限** | `auth_manager.py`（初回管理者の作成など）、`pep.py`（namespaceのアクセス制御）、`knowledge_manager.py` | |
| **監査・点検** | `audit_logger.py`、`audit_report.py`、`ci_check_namespaces.py`（CIが実行） | |
| **MCPサーバー（ローカルRAG）** | `rag_mcp_server.py`、`mcp_server.py`、`rag_mcp_tools.py` | Claude Desktopへの登録用 |
| **Notion連携** | `notion_bulk_add.py`（YAMLから一括投入）、`notion_to_corpus.py`、`localrag_to_notion.py` | **`--dry-run`で確認してから** |
| **Houdiniドキュメント** | `sync_houdini21_db.py`、`extract_zip.py`、`delete_non_txt.py` | `delete_non_txt.py`は**削除する**。対象を必ず確認 |
| **取り込み補助** | `youtube_transcribe.py`、`rss_to_rag.py` | 外部コマンド（`ffmpeg`など）が必要なものがある |
| **保守** | `backup_data.py`、`check_gemini_api.py`（APIの疎通確認） | |
| **資料の生成** | `build_system_guide.py`、`guide_svg.py` | `docs/system-guide.html`などを作る |
| **GAS（旧クラウド）** | `gas_cloud_rag.js` | Apps Scriptに貼る。新機能は、Worker側 |

使う前に、**そのファイルの冒頭と`--help`を読む**。引数があるものは、たいてい、`--help`で一覧が出る。

## 5. Pythonのスクリプトを書く型

```python
#!/usr/bin/env python3
"""何をするスクリプトか、1〜3行で。"""
from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", help="対象（省略不可。「全部」を既定にしない）")
    parser.add_argument("--dry-run", action="store_true", help="実行せず、内容だけ表示")
    args = parser.parse_args(argv)

    items = find_items(args.target)          # まず、対象を集める
    print(f"対象: {len(items)}件")
    for it in items[:5]:
        print(" -", it)                       # 何をするか、見せる
    if args.dry_run:
        print("（dry-run: ここまで）")
        return 0

    if input("実行しますか？ [y/N] ").strip().lower() != "y":   # 確認する
        print("中止しました")
        return 1
    for it in items:
        do_one(it)                            # 1件ずつ。失敗は、止める
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- 外部のコマンドを呼ぶときは、`subprocess.run([...], check=True)`。**文字列を`shell=True`で渡さない**（引数に、不正な文字が混ざると、別の命令が実行される）。
- 秘密は`os.environ["NAME"]`から。**見つからなければ、分かる文で止まる。**
- 読み書きするファイルは、`pathlib.Path`で。**消す前に、対象のパスを表示する。**

## 6. 読み取り専用の「点検スクリプト」の例

**本番を書き換えずに、状態を確かめる**（PowerShell）。

```powershell
# 本番のD1の状態を、読むだけで確認する（書き込みのSQLは入れない）
Set-Location "$HOME\Desktop\GameDevelopment\DevelopmentRAGEnvironment\cloudflare-rag-poc"
$ErrorActionPreference = "Stop"

Write-Host "== 未適用のマイグレーション =="
npx wrangler d1 migrations list rag-poc-db --remote

Write-Host "== namespaceごとの文書数 =="
npx wrangler d1 execute rag-poc-db --remote --command `
  "SELECT namespace, COUNT(*) AS docs FROM kb_documents GROUP BY namespace ORDER BY docs DESC"

Write-Host "== 直近1日のエラー件数 =="
npx wrangler d1 execute rag-poc-db --remote --command `
  "SELECT COUNT(*) AS errors FROM kb_log WHERE status = 'error' AND created_at >= strftime('%s','now') - 86400"
```

- `kb_documents`と`kb_log`は索引があるので、読み取り行数が小さい。**`chunks_fts`を、直接`COUNT`しない**（全件を読む）。
- 結果をJSONで処理するなら、`--json`を付けて、`ConvertFrom-Json`で受ける。

## 練習

1. `rag_cli.py`を`--help`付きで実行（`uv run python scripts/rag_cli.py --help`）し、サブコマンドを書き出す。
2. 上の§6の点検スクリプトを、ファイルに保存して実行する。**どのコマンドが、D1の何行を読むか**を、`EXPLAIN QUERY PLAN`で確かめる。
3. §5の型で、「`localRAG/`の中の`.md`ファイルの数を、ディレクトリ別に表示する」スクリプトを書く（書き込みは、しない）。
4. 「確認なしで本番を変更するコマンド」の例を、このプロジェクトで3つ挙げ、それぞれ、どう安全にするか書く。
5. PowerShellとBashで、「環境変数`X`が設定されていなければ、メッセージを出して終了する」を、それぞれ書く。

**ヒント:** 5は、PowerShellは`if (-not $env:X) { Write-Error "…"; exit 1 }`、Bashは`: "${X:?メッセージ}"`が使える。

## 確認

- [README.md](README.md)の「Script」のチェック2項目に答えられる。
- 自分で書いたスクリプトに、§2の原則のうち、**少なくとも3つ**が入っている。
