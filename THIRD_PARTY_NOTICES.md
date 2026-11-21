# Third-party notices / 第三者の権利の表記

このリポジトリ（RAGReel Tutorial の Houdini パネル・Cloudflare Worker・各種スクリプト）は、`LICENSE`（PolyForm Noncommercial 1.0.0）で公開しています。
次の第三者のものは、それぞれの条件が別に適用されます。

## 使っているソフトウェア
| 名前 | 使っている場所 | ライセンス |
|---|---|---|
| PySide6 / Qt | Houdini に同梱のものを使う（このリポジトリは、配布しない） | LGPL v3（Houdini 側の条件） |
| `@anthropic-ai/sdk` | Worker | MIT |
| Wrangler・`@cloudflare/workers-types`・TypeScript・tsx | Worker の開発 | Apache-2.0 / MIT |
| Pillow | 撮影・画像の処理 | HPND |
| その他の Python の依存（`pyproject.toml`） | ローカル RAG・スクリプト | 各パッケージのライセンス（`uv.lock` で固定） |

## このリポジトリに取り込んだ、第三者のコード（MIT）
`scripts/document_processor.py`・`scripts/embedding_generator.py`・`scripts/rag_service.py`・`scripts/mcp_server.py` などは、
[karaage0703/mcp-rag-server](https://github.com/karaage0703/mcp-rag-server) の検索エンジンのコードを取り込み、改変したものです。
その部分には、元の MIT ライセンスが適用されます（配布するときは、次の表示を残す義務があります）。

```
MIT License

Copyright (c) 2025 karaage

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

その他の依存の、ライセンスの一覧と判定は、[docs/operations/license-compliance.md](docs/operations/license-compliance.md) にあります。

## 非商用の範囲について
このリポジトリ全体の `LICENSE` は非商用です。MIT の部分は、元のコードに限り、MIT のままです（その部分だけを取り出して使うときは、MIT に従えます）。

## 配らないもの・リンクだけのもの
- **SideFX の公式ドキュメント**: 著作権は SideFX Software Inc. にあります。このリポジトリには入れていません。Reference の説明は、公式ドキュメントを材料に、AI が日本語で書き直した解説で、各項目から公式ページへのリンクを出しています。
- **HoudiniReference の項目**（Tips・動画・フォーラムの題名・出典・短い抜粋・URL）: 元のページの著作者のものです。Reference では、題名・出典・リンクだけを出し、リンク先の元のページを正とします。
- **Houdini・SideFX** は、SideFX Software Inc. の商標です。このプロジェクトは、SideFX と提携・承認の関係にありません。

## 動画エンジン
RAGReel（動画エンジン）は、別のリポジトリ（`manato1201/RAGReel`）です。その配布物の第三者の表記は、そちらの `THIRD_PARTY_NOTICES.md` にあります。
