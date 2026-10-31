# 新規プロジェクト案と「他アプリから借りる技術」調査

作成日: 2026-10-07 / 起点: [caustic-volume](https://github.com/ScottieFox/caustic-volume)(MIT)と、強化したい領域(Cloud / Server / 資格 / shader / Houdini / Unreal)

**この資料の読み方**
- 第1章: caustic-volume から何を借りられるか
- 第2章: 新規プロジェクト案(推し順)
- 第3章: Obsidian のように「他アプリの機能を再現して既存システムに入れる」候補の一覧
- 第4章: 強化したい6領域とのつながり
- 事実の出どころは末尾の「確認状況」に分けて書いた。リポジトリのコードは未読で、README相当の要約から判断している。

---

## 1. caustic-volume から借りられるもの

WebGL2 + three.js(r186)で水のコースティクス(水底に揺れる光の模様)をリアルタイム描画する MIT ライセンスのリポジトリ。Lite(単一HTML・約990行)と Sandbox(約7,500行・18モジュール)の2版がある。

| 技術要素 | 中身 | 流用先 |
|---|---|---|
| 光子追跡による集光率 | 水面で屈折した光が床に届く面積比を明るさにする | Unity Built-in RP / VRChat 向けの**コースティクス投影シェーダ**。事前ベイクでも動く(Built-in RP にはリアルタイムGIが無いため相性が良い) |
| GPU波動シミュレーション | `GPUComputationRenderer` でクリック波紋と物理を計算 | Unity の Custom Render Texture / Compute、Houdini の Heightfield |
| 24本の進行波 + FFT海面(Sandbox) | 短波長の波を重ねる / スペクトルから海面を作る | Houdini の Ocean Spectrum、Unreal の水系 |
| コースティクス・ボリューム(光の筋) | 水中の光芒を描く | 既存の動的GI設計書(DynamicGIMiddleware)への知見 |
| 色分散 + Beer–Lambert | 波長ごとの屈折と吸収 | 虹色コースティクス、水深で変わる色 |
| 適応解像度 | フレームレートを見て描画解像度を自動調整 | ProfilingTool の「品質ガバナー」機能 |
| 単一HTML + CPUフォールバック + オフライン動作 | 配布しやすさの設計 | 図鑑系・MagicCircleGenerator の配布方針 |
| Playwright でのヘッドレス検証 | `tools/` にテストスクリプト | VisualRegressionQATool にシェーダ描画の回帰テストを追加 |

**注意**: デモページ(Lite)の本文だけでは使用技術が読み取れなかった。上の表は GitHub の README 要約が根拠。着手前にソースを読んで確認する。MIT なので、移植するときは著作権表示とライセンス文を残す。

---

## 2. 新規プロジェクト案

### 案A: CausticLab(shader × Houdini × Web) — 最優先

**一言**: コースティクスを「Webで試す → Houdiniでベイク → Unity/VRChatのシェーダとして使う」まで一続きにするツール。

- **Web**: caustic-volume Lite の手法を three.js の WebGPU + TSL で作り直し、パラメータ(波の強さ・光源高さ・分散量)をスライダーで調整できるようにする。
- **Houdini**: Houdini 21 の Copernicus(GPU の2D合成)で、タイル可能なコースティクス連番テクスチャをベイクする HDA を作る。Houdini 21 には Copernicus のテクスチャベイク機能が入っている。
- **Unity**: Built-in RP / VRChat で動く投影シェーダ(連番テクスチャ + UV スクロール + 深度フェード)。
- **Cloud**: 作ったパラメータ設定を URL で共有する。Cloudflare Workers + R2 で保存する構成は MagicCircleGenerator の共有機能と共通化できる。

**既存資産との接点**: houdini21 名前空間のRAG、Houdini チュートリアル自動生成(ベイクHDAの作り方を自動でチュートリアル化)、VRCEffectFrameWork(投影先)、UnityHDRPBlackHole(光の表現の研究)。

**最小の一歩(1週間)**: caustic-volume Lite をローカルで動かして読む → パラメータ3つを抜き出して Houdini で1枚ベイク → Unity の Plane に流す。

### 案B: CertQuest(資格 × RAG × 間隔反復)

**一言**: 資格の学習内容を、既存のRAG名前空間から問題化し、忘れる頃に出題するアプリ。

- 既存の「理解度スコア」(トピック習熟度で検索範囲を調整)を、**FSRS** という間隔反復アルゴリズムに置き換える。FSRS は記憶の安定度・難しさ・想起確率を追跡する、Anki でも使われるオープンソースのスケジューラ。
- 問題は、名前空間のドキュメントから LLM が生成し、出典チャンクを必ず添える(RAGの引用機能を流用)。
- 器は FoundationsEncyclopedia(基礎学習図鑑)の `createContentLoader` / `useStepPlayer` を再利用できる。
- 対象資格の候補: クラウド系(AWS 等の入門〜アソシエイト)、情報処理系、CG系(CGエンジニア検定など)。**試験範囲と改定は公式で必ず確認する**(この資料では確認していない)。

**最小の一歩**: 1つの資格に絞り、既存ドキュメント20件から問題を自動生成 → FSRS のライブラリで出題順を決める。

### 案C: SandboxRunner(Cloud × Server)

**一言**: AIが生成したコードを、隔離環境で実行して検証する仕組み。

- Cloudflare の Containers と Sandbox SDK は 2026年4月に一般提供(GA)になった。コード実行・ファイル操作・プレビューURL・PTYターミナル・バックアップ/復元・ファイル監視に対応している。
- 既存の houdini21 チュートリアル自動生成は、cook エラーなし判定を手元の Houdini で行っている。Houdini 本体(GUI・ライセンス)は Sandbox 内では動かせないので、**Python / WGSL / シェーダの構文検証・ユニットテスト**だけを Sandbox に出す、という切り分けになる。
- Cloud / Server の学習と、実運用(RAG の取り込み処理の隔離)を兼ねられる。

### 案D: PCG Recipe Hub(Houdini × Unreal)— 中期

- Unreal Engine 5.7 は PCG を本番利用向けとし、PCG Editor Mode、GPU計算の最適化、Procedural Vegetation Editor、Nanite Foliage(実験的)、Substrate(本番対応)が入った。
- 実Editorを操作する MCP サーバがコミュニティ製で複数あるので、Blender MCP と同じ要領で ToolOrchestrationHub に Unreal を接続できる。
- Houdini の HDA → Unreal PCG のレシピをRAGに蓄積し、Houdini チュートリアル自動生成の「Unreal版」を作る。
- 既存の DeliveryService(Unreal共同制作)と学習がつながる。

### 案の比較

| 案 | 価値 | 工数 | 強化したい領域 | 先に必要なもの |
|---|---|---|---|---|
| A CausticLab | 高(作品として見せやすい) | 中 | shader / Houdini / Cloud | caustic-volume のソース確認 |
| B CertQuest | 高(自分の学習に直結) | 中 | 資格 / Cloud | 対象資格を1つ決める |
| C SandboxRunner | 中(基盤) | 中 | Cloud / Server | 検証対象の言語を決める |
| D PCG Recipe Hub | 中(学習が先) | 大 | Houdini / Unreal | Unreal 5.7 環境 |

**おすすめ順**: A → B → C。D は Unreal の学習が進んでから。

---

## 3. 他アプリから借りる技術(Obsidian方式)

Obsidian のグラフ表示を再現した方式を、他のアプリにも当てはめた一覧。右端は既存プロジェクトのどこに入るか。

### 3.1 ノート・知識管理系

| 元アプリ | 借りる機能 | 入れ先 | 効果 |
|---|---|---|---|
| Obsidian Canvas(JSON Canvas は公開仕様) | 検索結果のノートを自由配置して `.canvas` で保存 | cloudflare-rag-poc の chatUi | 調べ物の「作業盤面」を残せる |
| Obsidian Canvas の Link Exploder 系プラグイン | あるノートの被リンク・リンク先を一括配置 | グラフビューの詳細パネル | ノードクリックで周辺を展開 |
| Obsidian Bases | プロパティを表・カード表示 | 管理タブ | namespace・ファイルのメタデータ一覧 |
| Obsidian Smart Connections | 書きながら関連ノートを提示 | localRAG | 既存の検索の「書きながら版」 |
| Logseq / Roam | ブロック単位の参照と双方向リンク | `jumpToSource`(引用ジャンプ) | チャンク間の相互リンク |
| Tana / Anytype | 型付きメタデータ | namespace 設計 | 「チュートリアル」「設計書」などの型 |
| NotebookLM | ソース限定回答、学習ガイド、FAQ、音声解説 | RAGReel / CertQuest | 資料から「要点まとめ」「想定問答」を自動生成 |

### 3.2 検索・RAG の品質系

| 元の技術 | 借りる機能 | 入れ先 | 効果 / 注意 |
|---|---|---|---|
| LightRAG(MIT) | LLMで抽出した実体と関係のグラフ + 低レベル/高レベルの二段検索。差分更新に強い | グラフビュー | 今は埋め込みの類似度でエッジを作っている。意味のある関係線にできる。GraphRAG(Microsoft)は全再構築が前提でコストが重いので、LightRAG系を先に試す |
| Cursor 等のコード索引 | ハッシュ木(Merkle)で変更箇所だけ再索引 | auto_index / Cloudflare cron | 再索引コストの削減 |
| Langfuse / Phoenix 系 | 呼び出しの追跡と評価 | 監査ログ(JSONL) | ダッシュボード化 |
| Ragas / promptfoo 系 | 検索品質の自動評価 | 👍/👎評価 | 評価データを「正解セット」にして改善の前後を比較 |
| Docling / Marker 系 | PDF・Office を Markdown に変換 | document_pipeline | CEDEC資料PDFの取り込み精度 |
| Raycast / Linear | キーボード中心の操作とコマンドパレット | chatUi | 5タブの素早い切替、アクション実行 |

### 3.3 CG・開発ツール系

| 元の技術 | 借りる機能 | 入れ先 |
|---|---|---|
| caustic-volume | 適応解像度、Playwright検証 | ProfilingTool / VisualRegressionQATool |
| Houdini 21 Copernicus | GPU 2Dコンポジット、テクスチャベイク | MagicCircleGenerator(光・ノイズ素材のベイク)、案A |
| three.js TSL ライブラリ(tslfx、lib3) | WebGPU向けVFXシェーダ、波・レイマーチの部品 | MagicCircleGenerator、The-Algorithm-Illustrated |
| Tracy / RenderDoc | プロファイル・フレームキャプチャのAPI | ProfilingTool のアダプタ |
| OpenUSD | シーンの共通形式 | Houdini ⇔ Unreal ⇔ Blender の受け渡し |
| FSRS | 忘却曲線に基づく再出題 | 理解度スコア → 案B |
| Cloudflare Sandbox / Containers | 隔離実行、プレビューURL | 案C、ToolOrchestrationHub |

---

## 4. 強化したい6領域とのつながり

| 領域 | 今ある足場 | 次の一手 |
|---|---|---|
| Cloud | Cloudflare RAG POC(Workers / D1 / Vectorize) | 案Aの共有保存(R2)、案Cの Sandbox |
| Server | HTTPブリッジ、CodeRidge-Server | 案Cで実行環境の運用を学ぶ |
| 資格 | FoundationsEncyclopedia、理解度スコア | 案B |
| shader | UnityHDRPBlackHole、SpringWorks、VRCEffectFrameWork | 案A |
| Houdini | houdini21 チュートリアル自動生成、AdvancedVAT | 案A(Copernicus ベイク)、案D |
| Unreal | DeliveryService | 案D(PCG)、Unreal MCP |

---

## 5. 確認状況(正直な区分)

**Web で確認できたこと**
- caustic-volume の構成・技術・ライセンス(GitHub 要約)
- Houdini 21 の Copernicus(GPU Pyro・テクスチャベイク)、Solaris の更新
- Unreal 5.7 の PCG / Nanite Foliage / Substrate、MCP サーバの存在
- Cloudflare Containers / Sandbox の GA(2026年4月)
- LightRAG と GraphRAG の違い、FSRS の仕組み
- three.js TSL の水・コースティクス系の公開事例とライブラリ

**確認していないこと**
- caustic-volume のソースコードそのもの(デモページ本文からは技術が読めなかった)
- Obsidian Bases・JSON Canvas の最新仕様と、各アプリの現行バージョン(私の背景知識。導入前に公式で確認)
- 各資格の試験範囲・改定・費用

## 参考リンク
- [caustic-volume](https://github.com/ScottieFox/caustic-volume) / [Lite デモ](https://scottiefox.github.io/caustic-volume/lite/index.html)
- [Houdini 21 What's new](https://www.sidefx.com/docs/houdini/news/21/index.html)
- [Unreal Engine 5.7 の PCG・フォリッジ](https://digitalproduction.com/2025/11/12/unreal-engine-5-7-foliage-pcg-and-in-editor-ai/)
- [Cloudflare Containers / Sandboxes GA](https://developers.cloudflare.com/changelog/2026-04-13-containers-sandbox-ga)
- [LightRAG と GraphRAG](https://pub.towardsai.net/lightrag-and-graphrag-the-new-area-of-rag-applications-94ec48f8ec31)
- [FSRS4Anki](https://github.com/open-spaced-repetition/fsrs4anki)
- [tslfx](https://github.com/verekia/tslfx) / [lib3](https://github.com/pipefold/lib3)
- [Obsidian Smart Connections 等のプラグイン一覧](https://community.obsidian.md/plugins/excalink)
