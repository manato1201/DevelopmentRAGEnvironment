# DevelopmentRAGEnvironment 改善・リファクタリング計画書

**改善指標: 学習レベル適応型RAG出力+VLM対応+スケール移行の準備**
作成日: 2026-08-11 / 調査範囲: Python≥3.13、`scripts/`(約30ファイル)、`houdini/python_panels/`(8ファイル・3,624行)

本計画はCloud RAG(Notion+Gemini)とLocal RAG(ChromaDB+BM25)の二本立て構成を前提に、学習者の習熟度に応じた出力レベリング・VLM対応・将来のスケール移行という3方向の技術判断を扱う。`docs/distribution-strategy.md`は配布方式のみを扱う調査書(コード変更不可・新規ドキュメントファイルのみ)であり、本計画のいずれのフェーズもその内容とは独立して進行する。

---

## Phase 0: 現状分析(調査済み)

### Cloud RAG / Local RAGの二本立て構成

| 系統 | 役割 | 実体ファイル |
|---|---|---|
| Cloud RAG | Notion文書+Gemini。GAS WebApp経由でチーム共有情報を検索 | `scripts/gas_cloud_rag.js`(272KB、単一ファイルのGoogle Apps Script) |
| Local RAG | 個人ノート・チャットログ(`localRAG/`Obsidianボルト)。ChromaDB+BM25ハイブリッド検索 | `scripts/rag_local_bridge.py`(HTTPブリッジ)+`vector_database.py`(523行)+`embedding_generator.py`(69行、`intfloat/multilingual-e5-large`をsentence-transformers経由でロード)。日本語トークナイズはSudachiPy |

コーパスは「公開してよい情報(Unity/Houdini/DirectX12ツールドキュメント・ゲームデザイン文書・キュレーション済み記事・セミナーノート)」と「個人情報(チャット履歴・個人メモ・下書き)」に物理的に分離されている(README.md「設計思想」節)。Unity6/Houdini21+のエディタへは`rag_local_bridge.py`がHTTP経由(既定ポート`:8766`、`X-API-Key`ヘッダ認証)で公開しており、`/health`/`/admin`/`/ui`のみ認証除外(`rag_local_bridge.py`の`_require_auth()`/`do_GET()`)。

### scripts/ と houdini/python_panels/ の構成

`scripts/`配下は約30本のフラットなファイル構成で、プラグイン機構やサービス境界は存在しない。中核は`document_pipeline.py`(SemanticChunker、512トークン/64オーバーラップ)/`document_processor.py`(247行)/`embedding_generator.py`/`vector_database.py`/`rag_service.py`(228行、処理段の統合層)/`score_engine.py`(153行)/`pep.py`(116行)。`houdini/python_panels/`の`tutorial_agent.py`(562行、Claude Sonnet系エージェントループ。`MAX_ITERATIONS=40`・`COST_LIMIT_USD=$5.00`で打ち切り)が自然言語の依頼からHoudiniノードグラフを組み立てるオーケストレーターで、`houdini_tools.py`(708行、`create_node`等のhouラッパーツール群)とセットで動く。全ノード操作は`/obj/ai_tutorial_<timestamp>`サンドボックス内に限定され、サンドボックス外パスは`SandboxViolation`で拒否・監査ログに記録される。

`docs/content-generation.md`はこの自動生成の設計文書で、houdini21向けは実装済み・実機検証済み、飲食店ドメイン(BrainTQ)向けは設計中と役割が分かれている。Phase1のレベル軸(`{level}`プレースホルダ)はhoudini21固有にせず、`_SYSTEM_PROMPT_TEMPLATE`の他ドメイン展開(BrainTQ等)でも再利用できる形で設計する。

### 既存ガバナンス: pep.py と理解度スコアの既存パターン

`pep.py`の`RAGPolicyEnforcementPoint`は`NAMESPACE_PERMISSIONS`(namespace別read/write/delete)と`_ROLE_NAMESPACES`(admin/developer/user)を持ち、`filter_namespaces()`はfail-closed設計(未指定時にロール全体へフォールバックしていた旧fail-open挙動を修正済み):

```python
# scripts/pep.py(既存・変更対象外。Phase1以降の新機能もこのマップ経由で判定させる)
NAMESPACE_PERMISSIONS: dict[str, dict[str, bool]] = {
    "tool_docs":      {"read": True,  "write": False, "delete": False},
    "game_info":      {"read": True,  "write": False, "delete": False},
    "research":       {"read": True,  "write": False, "delete": False},
    "team_notes":     {"read": True,  "write": True,  "delete": False},
    "personal_notes": {"read": True,  "write": True,  "delete": True},
    "houdini21":      {"read": True,  "write": False, "delete": False},
}
```

加えて`score_engine.py`の`UnderstandingScoreEngine.build_rag_query()`は理解度スコア(0.0-1.0、閾値`_BEGINNER_THRESHOLD=0.3`/`_INTERMEDIATE_THRESHOLD=0.7`、`data/auth.db`の`understanding_scores`テーブル)から`detail_level`("step_by_step"/"conceptual"/"reference_only")と検索namespaceを導出する仕組みを既に持つ。Phase1のレベリングは、この既存パターンを検索フィルタだけでなく生成物そのもの(チュートリアルのMarkdown/JSON)に適用する拡張として位置づけられる。

### 検索品質・評価まわりの既存機能(退行させてはならない基準線)

README記載の検索品質向上機能——HyDE(仮説文書埋め込み、ドメイン別プロンプト・重み)、ページ単位重複排除、閾値フィルタ(コサイン類似度0.58未満除外)、情報抽出度メトリクス(`extractionRate`/`extractionDetail`、`/query`レスポンスに既存)、👍/👎評価(Cloud RAGのpriority調整)——はPhase1・Phase2のいずれの変更でも退行させてはならない基準線として扱う。特に`extractionRate`は`/query`レスポンスの既存フィールドであり、Phase1のlevel追加後もフィールド自体の意味・算出方法を変えない。

### アンチパターン(全フェーズ共通)

- `docs/distribution-strategy.md`は「調査・提案書。本ドキュメントはコード変更を行わない(新規ドキュメントファイルのみ)」と明記された文書(同書冒頭「位置づけ」)。配布方式(PyInstaller/pipx/インストーラー/Docker)の実装は本計画のどのフェーズの対象にもしない
- 既存のnamespaceガバナンス(`pep.py`)を迂回する新規アクセス制御ルールを作らない。新機能は`authorize()`/`filter_namespaces()`経由で判定させる
- ECS・重量DIコンテナ・専用静的解析基盤の類は、後続フェーズ(Phase4/5)で理由とともに明示的に不採用と判断する。「大規模ゲームエンジン的パターンをとりあえず持ち込む」ことはしない

---

## Phase 1: RAGレベリング(basic→applied→advanced連続進行、最優先)

**現状:** `tutorial_agent.py`の`_SYSTEM_PROMPT_TEMPLATE`は`sandbox_path`/`common_node_types`/`rag_context`のみをプレースホルダに持ち、難易度という概念を持たない。ChromaDBのメタデータは`vector_database.py`の`_safe_meta()`でstr/int/float/boolのスカラー値のみ許可される(list等は保存不可)。

**実装内容:**
1. `_SYSTEM_PROMPT_TEMPLATE`に`{level}`と`{prior_level_summary}`を追加し、同一トピックをbasic→applied→advancedの順で生成する際、前段の`finish_tutorial`出力(steps/pitfalls/next_steps)の要約を次段プロンプトへ引き継ぐ。「どのレベルを生成するか」の決定はscore_engine.py側の理解度スコアに残し、tutorial_agent.py側はレベルを受け取って生成するだけに責務を絞る:
   ```python
   _LEVEL_INSTRUCTIONS = {
       "basic":    "初心者が最初に触るノード構成に限定する。3〜5ノード程度。",
       "applied":  "basic段の構成を前提に、パラメータ調整や分岐を1〜2個追加する。",
       "advanced": "applied段を前提に、実務で使う応用パターン(VEX/式/複数ノード連携)を含める。",
   }
   # _SYSTEM_PROMPT_TEMPLATE へ追記するブロック(既存の絶対ルール等は変更なし)
   #   ## レベル: {level}  (basic → applied → advanced の一貫進行)
   #   {level_instruction}
   #   ## 前段の要約(basicでは空文字。applied/advancedは前段のnext_steps/pitfallsを要約)
   #   {prior_level_summary}

   def build_level_chain(topic: str) -> list[TutorialResult]:
       """basic→applied→advancedを逐次生成し、前段の要約を次段へ引き継ぐ。"""
       results, prior_summary = [], ""
       for level in ("basic", "applied", "advanced"):
           result = generate(topic, level=level, prior_level_summary=prior_summary)
           prior_summary = _summarize_for_next_level(result)  # next_steps/pitfallsを要約
           results.append(result)
       return results
   ```
2. ChromaDBメタデータに`difficulty`フィールド(`"basic"|"applied"|"advanced"`、スカラー文字列)を追加。`tutorial_agent.py`が`localRAG/tutorials/`へ保存する`.md`/`.json`にレベルを持たせ、既存のインデックス経路(`rag_cli.py index`)がそのままChromaDBメタデータへ反映する形にする(新規インデクサは作らない)
3. `/search`/`/query`(`rag_local_bridge.py`)のリクエストボディに任意フィールド`level`を追加する。既存API契約への後方互換追加(省略時は全レベル対象、現行動作のまま):
   ```jsonc
   // POST /search リクエスト(既存の query/limit/namespaces に level を追加、省略可)
   { "query": "スキャッター基礎", "limit": 6, "namespaces": ["houdini21"], "level": "basic" }

   // レスポンス(sources[] に difficulty を追加。既存フィールド・型は変更なし)
   { "texts": ["..."], "sources": [{ "file": "...", "difficulty": "basic", "cited": true }], "status": "ok" }
   ```
4. 評価は`docs/houdini21-learning-effect-study.md`が定義する客観指標/主観指標(5段階Likert)・統計解析計画をそのまま評価基盤として再利用する。レベリング固有の追加指標(basic→advanced進行時の理解度スコア変化率)のみ新設する

**検証チェックリスト:**
- [ ] 同一トピックでbasic/applied/advancedを生成し、`prior_level_summary`が次段プロンプトに実際に含まれることをログで確認
- [ ] `level`未指定の既存`/search`/`/query`リクエストが従来と同じ結果件数・レスポンス形式で応答すること(後方互換)
- [ ] ChromaDBの`_safe_meta()`が`difficulty`フィールドを削除せず通過させること
- [ ] `houdini21-learning-effect-study.md`の客観指標でbasic→advanced進行後の理解度スコア変化を計測できること
- [ ] `extractionRate`/`extractionDetail`(既存の情報抽出度メトリクス)がlevel追加前後で同じ算出式のまま動作すること

**アンチパターン:** basic/applied/advancedの境界線はLLMの生成結果に依存するため、初回実装で確定させない。`houdini21-learning-effect-study.md`のA/Bテスト結果を見ながら`_LEVEL_INSTRUCTIONS`の文言を反復調整する前提で計画する(本フェーズが最優先かつ不確実性がやや高い理由)。

---

## Phase 2: VLM対応(画面キャプチャ入力の再利用)

**現状:** Cloud RAG(`gas_cloud_rag.js`)は画像アップロードをOCR経由(`ocrLanguage: 'ja'`、`MAX_DRIVE_CONVERT_MB`既定25MB)でテキスト化し知識ベースへ取り込む機能を既に持つ(Word/Excel/PPT/PDF/画像、`docs/cloud-rag.md`)が、これはコーパス投入時の一方向変換であり、クエリ時に画像を渡す質疑応答(VLM的な用途)はできない。Local RAGはテキスト埋め込み(`multilingual-e5-large`)のみで画像埋め込みを持たない。Houdini側には`screen_capture.py`(361行)があり、`capture_viewport()`/`capture_viewport_clip()`(いずれも実機検証済み)、`capture_network_editor()`(既知の不安定挙動がコメントに記録済み)を提供する。

**実装内容:**
1. Cloud RAG側: `gas_cloud_rag.js`の既存Gemini呼び出しプロキシを拡張し、クエリ時に画像(base64/inlineData)を添付できるようにする。OCR取り込み経路とは別の、質問応答用の入力チャネルとして追加する
2. Local RAG側: namespace別collectionと並行して、CLIP系モデルによる画像埋め込みを追加し、テキスト埋め込み(`multilingual-e5-large`)と同一ChromaDB内で共存させる(例: `{namespace}_images`コレクション)。既存のBM25+ベクトルのRRFマージ(`vector_database.py`)にモダリティを1軸追加する程度に留め、検索ロジック自体は作り直さない
3. 画像入力ソースは`screen_capture.py`の`capture_viewport()`/`capture_viewport_clip()`をそのまま流用する。新規キャプチャ機構は作らない。`capture_network_editor()`の既知の不安定挙動の修正はPhase2のスコープ外とする
4. 別文書「VLMAutoReplayTool設計書」も画面キャプチャ→VLM入力という同型の経路を扱う。両者が個別にキャプチャ実装を持たないよう、`screen_capture.py`の関数シグネチャを共通インターフェース候補として相互参照する

**検証チェックリスト:**
- [ ] Cloud RAGへ画像添付クエリを送り、テキストのみクエリと同じ`/query`系レスポンス形式で応答が返ること
- [ ] CLIP画像埋め込みの追加後も、既存のテキストのみ検索(BM25+multilingual-e5-large)のスコア・順位が変化しないこと(回帰確認)
- [ ] `capture_viewport()`で取得した画像がCloud RAG経由でVLM入力として解釈されること
- [ ] 「VLMAutoReplayTool設計書」とのキャプチャ関数共通化の要否を判断できるレベルまでインターフェースを揃えること
- [ ] Phase0で確認した既存品質機能(HyDE・情報抽出度メトリクス・閾値フィルタ)がVLM入力の有無に関わらず同じ算出結果を返すこと

**アンチパターン:** `screen_capture.py`の代替となる新しいキャプチャ機構を作らない。既知の`capture_network_editor()`不安定挙動を「VLM対応のついでに」直そうとしない(スコープ拡大の回避)。

---

## Phase 3: TiDB Cloud/TiKV移行設計(設計のみ、実装着手条件を明記)

**現状:** ベクトルストア(`data/chroma/`、ChromaDB PersistentClient)と認証/メタデータストア(`data/auth.db`、SQLite)が分離した二重ストア構成。`auth.db`は`users`(id/api_key_hash/display_name/allowed_namespaces/is_admin/created_at/last_used)・`access_logs`・`understanding_scores`(user_id/topic/score/updated_at)の3テーブル。BM25インデックスは`{chroma_path}/bm25/{namespace}.pkl`にpickle保存され、ChromaDBの内容を正として`_rebuild_bm25_from_chroma()`で再構築される。

**実装内容:**
1. 適用範囲を分離する。**認証/メタデータ(TiDB)** と **将来の高頻度KVアクセス(TiKV)** を別軸で設計し、一括で「DBを置き換える」計画にはしない
2. TiDB: `auth.db`のスキーマをそのまま移行対象にする(MySQL互換プロトコルのためスキーマ変更は最小限)。複数Unity/Houdiniクライアントからの同時アクセスで将来問題化しうるSQLiteのファイルロック粒度をスケールアウトする:
   ```sql
   -- TiDB移行後の users テーブル(auth.dbからの直接移植。型のみMySQL互換に調整)
   CREATE TABLE users (
       id                 VARCHAR(64)  PRIMARY KEY,
       api_key_hash       VARCHAR(128) NOT NULL UNIQUE,
       display_name       VARCHAR(255) NOT NULL,
       allowed_namespaces JSON         NOT NULL,   -- SQLite版はTEXT('[]')→JSON型に強化
       is_admin           TINYINT      NOT NULL DEFAULT 0,
       created_at         DATETIME     NOT NULL,
       last_used          DATETIME
   );
   -- understanding_scores / access_logs も主キー・列構成を維持したまま移植
   ```
3. TiKV: ChromaDBのベクトル本体は当面移行対象にしない(PersistentClientで規模的な問題が出ていないため)。TiKVは`understanding_scores`のようなユーザーID+トピック単位の高頻度・低レイテンシKVアクセスが将来ボトルネック化した場合の**適用候補**として設計のみ用意し、実装着手条件を明記する(目安: 同時接続ユーザー数が個人〜数名運用の範囲を超え、`access_logs`の書き込みレイテンシがSQLiteのfsync待ちで体感劣化する規模になった時点)
4. `distribution-strategy.md`が非推奨としたのは「個人配布用途でのDocker回帰」(同書§2.3、方式D)であり、TiDB Cloudのようなマネージドサービス接続はローカル実行バイナリの配布方式そのものを変えない。両者が矛盾しないことを本フェーズの前提として明記する

**検証チェックリスト:**
- [ ] `auth.db`の3テーブル全レコードがTiDBへ欠損なく移行できること(件数突合)
- [ ] `pep.py`の`authorize()`/`filter_namespaces()`がTiDB移行後もインターフェース変更なしに動作すること
- [ ] `score_engine.py`の`update_score()`/`get_score()`がTiDB接続でも既存のSQLite版と同じ戻り値形式を返すこと
- [ ] ChromaDB(ベクトル本体)が本フェーズの移行対象に含まれていないこと(スコープ確認)
- [ ] 配布方式(`distribution-strategy.md`方式A〜E)のいずれとも、TiDB接続設定(接続文字列の環境変数化等)が独立して両立すること

**アンチパターン:** 「TiDB/TiKVを入れる」こと自体を目的化しない。SQLiteのファイルロックやChromaDBのローカルディスクI/Oが実際にボトルネックとして観測されるまでは設計止まりとし、実装には着手しない。

---

## Phase 4: 軽量サービスレジストリ導入(collector/embedder/backend差し替え)

**現状:** `document_processor.py`/`embedding_generator.py`/`rag_service.py`(228行)が処理段(読込・チャンク分割/埋め込み生成/検索統合)を担うが、各クラスは直接構築・直接呼び出しされている。バッチ/CLI主体のETLパイプライン(`rag_cli.py index`)であり、大量エンティティを毎フレーム反復処理するようなランタイムではない。

**実装内容:**
1. ECS・重量DIコンテナは導入しない。理由: エンティティ反復処理が存在しないバッチ処理系にアーキタイプ/システムの概念は不要で、この規模のモジュール数(3〜4個の処理段)にDIコンテナはオーバースペック
2. 代わりに関数登録+ルックアップのみの軽量レジストリを`rag_service.py`に導入し、Phase1のレベリング(生成物のプロンプト構成差し替え)・Phase2のCLIP画像埋め込み(`_EMBEDDERS`への`"clip"`登録候補)・Phase3のバックエンド差し替え(SQLite↔TiDB、ChromaDB↔TiKV)が将来この境界に乗るようにする:
   ```python
   # scripts/rag_service.py への追加案(既存クラスの実装は変更しない、登録のみ)
   _EMBEDDERS: dict[str, Callable[[], EmbeddingGenerator]] = {}
   _VECTOR_BACKENDS: dict[str, Callable[[dict], VectorDatabase]] = {}

   def register_embedder(name: str, factory: Callable[[], EmbeddingGenerator]) -> None:
       _EMBEDDERS[name] = factory

   def get_embedder(name: str = "default") -> EmbeddingGenerator:
       return _EMBEDDERS[name]()   # 未登録は KeyError で即失敗させる(暗黙フォールバック禁止)
   ```
3. `document_processor.py`/`embedding_generator.py`本体のクラス実装には手を入れない。レジストリは差し替え可能にするための登録簿にとどめ、インターフェース分離までは行わない(実際に差し替えが必要になるPhase1/Phase3が来るまでは`"default"`登録のみで足りる)

**検証チェックリスト:**
- [ ] `rag_cli.py index`がレジストリ経由の`get_embedder()`/`get_vector_backend()`に置き換わった後も、既存インデックス処理の出力(チャンク数・埋め込み次元)が変化しないこと
- [ ] 未登録キーで`get_embedder()`を呼んだ場合に暗黙フォールバックせず即座にエラーになること
- [ ] `document_processor.py`/`embedding_generator.py`のpublic APIシグネチャに差分がないこと(`git diff`で確認)
- [ ] ECS/DIコンテナ相当のクラス階層が新規に追加されていないこと(コードレビューで確認)
- [ ] レジストリ導入後も`rag_local_bridge.py`の`/health`が従来どおり200を返すこと(起動経路の疎通確認)

---

## Phase 5: 静的解析の軽量強化(pep.py→CI組み込み)

**現状:** `pep.py`はnamespace権限のランタイムチェックのみで、CI(GitHub Actions)には組み込まれていない(`.github/workflows/`自体が存在しない)。ruff/mypy等の静的解析ツールチェーンも未導入。

**実装内容:**
1. `.github/workflows/ci.yml`を新設: `uv sync`→`ruff check scripts/ houdini/`→`mypy --strict scripts/`(段階的に対象を広げる。初回は`pep.py`/`score_engine.py`等の小さいモジュールから`--strict`対象にする)
2. `pep.py`のnamespace遵守ルールをCIの1ステップとして呼び出すスクリプト(例: `scripts/ci_check_namespaces.py`)を追加し、`NAMESPACE_PERMISSIONS`に定義のない名前空間へのドキュメント追加を検知したら失敗させる
3. 独自拡張子+専用ツールによる大規模静的解析基盤(別文書「LoreDesktopAndWebSystem改善計画書」方式)は本プロジェクトの対象外と明記する。理由: 本プロジェクトはPython+JS(GAS)+C#(Unity Editor拡張)の組み合わせで独自DSL・拡張子を持たず、専用パーサ基盤を必要とする問題がそもそも存在しない

**検証チェックリスト:**
- [ ] `.github/workflows/ci.yml`がpush時に緑になる
- [ ] ruffがゼロ警告、または既存指摘を`# noqa`+理由コメントで明示的に許容
- [ ] `pep.py`ベースのCIチェックが、意図的に不正なnamespaceを仕込んだテストケースで実際に失敗すること(検出力の実証)
- [ ] mypy strict対象モジュールが最低1つ(`pep.py`または`score_engine.py`)でエラーゼロになること
- [ ] `audit_logger.py`によるJSONL監査ログ(NIST SP 800-207準拠)がCI導入後も既存フォーマットのまま出力され続けること

**アンチパターン:** 「LoreDesktopAndWebSystem改善計画書」の専用静的解析基盤パターンを安易に輸入しない。本プロジェクトの言語構成にはruff/mypy/標準ツールで十分。

---

## Final Phase: 統合検証

- [ ] レベリング機能(Phase1)導入後もUnity(`LocalRAGClient.cs`)/Houdini双方から見た`:8766`のHTTP契約が無変更で動作すること(`level`/`difficulty`はオプショナル追加のみ)
- [ ] VLM入力(Phase2)追加後もテキストのみクエリの応答品質・レイテンシが劣化しないこと(回帰確認)
- [ ] `pep.py`ベースのCIチェック(Phase5)が実際にnamespace違反を検出できること
- [ ] TiDB/TiKV(Phase3)は設計のみが完了し、実装着手は観測されたボトルネックが基準を超えた場合に限ること
- [ ] ECS/ジョブシステムを意図的に採用しなかった判断根拠(Phase4)をREADME.mdまたは本書に明記し、将来同じ検討を再度やり直させないこと
- [ ] Phase0で列挙した既存機能(HyDE・情報抽出度メトリクス・👍/👎評価・理解度スコア)が全フェーズ完了後も一通り動作すること(最終回帰確認)

---

## 相互参照ドキュメント

- Phase2のVLM対応(`screen_capture.py`の画面キャプチャ→VLM入力という経路)は、別文書「VLMAutoReplayTool設計書」の入力形式と同型であり、共通化できるインターフェースがあれば相互参照すること
- 本書の`:8766`ローカルRAGブリッジ(`rag_local_bridge.py`)は、別文書「LoreDesktopAndWebSystem改善計画書」(RAGアシスタント機能)・「LearningQt改善計画書」(`VectorStoreClient`、`rag_local_bridge.py:8766`へのHTTPクライアント)・「VLMAutoReplayTool設計書」から再利用される前提である。本計画でこのブリッジのAPI契約を変更する場合(Phase1のlevel/difficultyフィールド追加を含む)は後方互換を必須とする

**優先度注記:** 中程度。構造的ギャップは「LearningQt改善計画書」ほど大きくない(実装済み機能が多く土台は安定している)が、Cloud/Local二重RAG構成に加えUnity/Houdini双方への外部連携があり関係箇所が多く、Phase1のレベリング機能はプロンプト設計の反復検証が必要で不確実性がやや高い。
