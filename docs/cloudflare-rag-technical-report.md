# Cloudflare RAG POC 技術解説書

**作成日:** 2026-08-26（2026-09-22時点の実装に合わせて全面更新：知識ベース連携の拡張とOAuthクリック接続化を反映）
**対象:** [cloudflare-rag-poc/](../cloudflare-rag-poc/)（Cloudflare Workers + D1 + Vectorize によるRAG基盤の検証実装）
**位置づけ:** 既存の本番システム（`scripts/gas_cloud_rag.js`＝Google Apps Script + Google Sheets/ChromaDB、`scripts/rag_local_bridge.py`＝ローカルRAGブリッジ）を置き換える候補として、Cloudflareのサーバーレス基盤上に同等以上の機能を実装し、実データで検証した記録。本番システムには一切影響しない、独立した検証環境である。2026-08-26時点ではGAS版の機能パリティが主目的だったが、以降は**GAS版に無い新機能（再帰クローラー・重複検出・Jira/Backlog/Googleカレンダー/Googleマップ連携・OAuthクリック接続化）を追加する段階に移行**しており、両者は既に同一機能セットではない（[§9](#9-gas版との機能対応表サマリ)参照）。

---

## 目次

1. [概要](#1-概要)
2. [なぜCloudflareか](#2-なぜcloudflareか)
3. [システム全体構成](#3-システム全体構成)
4. [データモデル](#4-データモデル)
5. [主要フロー](#5-主要フロー)
6. [セキュリティ・アクセス制御](#6-セキュリティアクセス制御)
7. [知識ベース取り込みパイプライン](#7-知識ベース取り込みパイプライン)
8. [実装上の技術的な工夫と、実際に発見・修正したバグ](#8-実装上の技術的な工夫と実際に発見修正したバグ)
9. [GAS版との機能対応表（サマリ）](#9-gas版との機能対応表サマリ)
10. [今後の課題](#10-今後の課題)

---

## 1. 概要

GAS版（`gas_cloud_rag.js`、約3,450行・100関数超）が持つRAG機能一式を、Cloudflare Workers上でTypeScriptにより再実装した。方針は「どんどん機能を入れて最終的にGASと同等以上にする」で、単なる技術検証にとどまらず、実際のNotionデータベース・Google Driveフォルダを使った実データでの動作確認を継続的に行いながら開発した。

この過程で、実データ・実運用でしか顕在化しない複数のバグ（Vectorizeのベクトル長・件数上限、Cloudflareのサブリクエスト数上限、Workersのメモリ上限など）を発見し、その都度対処してきた。詳細は[README.mdのトラブルシューティング](../cloudflare-rag-poc/README.md#トラブルシューティング実際に遭遇したエラーと対処)を参照。

## 2. なぜCloudflareか

既存の検討資料（[docs/cloud-local-unification-plan.md](cloud-local-unification-plan.md)）が示す「Cloud RAG（Google Apps Script）とLocal RAG（Python + ChromaDB）の二重運用を統合したい」という課題に対し、Cloudflareを選んだ理由：

- **エッジで完結するサーバーレス**：Workers（compute）・D1（SQLite互換DB）・Vectorize（ベクトルDB）が単一プラットフォームに揃っており、GASのような「実行時間・呼び出し回数の制約が読みにくい」問題を避けられる
- **GASからの移行コストの低さ**：GASも「サーバーサイドでAPIキーを隠蔽し、クライアントに直接外部APIを叩かせない」という設計思想を持つため、Workersでも同じ構造（クライアント→Worker→外部API）をそのまま踏襲できる
- **明示的な制約が事前にわかる**：GASの「実行時間6分」「同時実行数」のような曖昧な制約と異なり、Workersの制約（後述のサブリクエスト数上限・CPU時間・メモリ128MB）はドキュメント化されており、対策を設計に織り込みやすい

ただし実装を進める中で、Workers特有の制約（Vectorizeバインディングを実行時に動的生成できない、サブリクエスト数上限、npm依存関係がedge-compatibleである必要がある等）も明らかになった。詳細は[§8](#8-実装上の技術的な工夫と実際に発見修正したバグ)、および[Firebaseで実装した場合との比較資料](cloudflare-vs-firebase-comparison.md)を参照。

## 3. システム全体構成

```mermaid
graph TB
    subgraph Client["クライアント"]
        Browser["ブラウザ（Webチャット画面）"]
        Houdini["Houdini（tutorial_agent.py）"]
    end

    subgraph Worker["Cloudflare Worker（1ファイルにバンドル、src/index.tsがルーター）"]
        direction TB
        RAG["RAGパイプライン<br/>hybrid.ts・retrieve.ts・embeddings.ts"]
        KB["知識ベース同期<br/>notionSync・driveSync・urlImport(再帰クローラー含む)<br/>qaImport・mediaImport・jiraSync・backlogSync<br/>calendarSync・mapsImport"]
        Dedup["重複検出・個別削除<br/>kbDocuments.ts"]
        DocExtract["文書変換<br/>docExtract.ts（PDF/DOCX/PPTX）<br/>mediaTranscribe.ts（音声/動画/YouTube）"]
        OAuth["OAuthクリック接続<br/>oauthConnections・jiraOAuth・backlogOAuth<br/>calendarOAuth・slackOAuth"]
        Admin["Admin API<br/>keyAdmin・namespaceAdmin・kbAdmin・kbRollback・backup"]
        ClaudeProxy["Claude APIプロキシ<br/>claude.ts"]
        Health["ヘルスチェック<br/>healthCheck.ts・alerts.ts"]
        Graph["グラフ可視化<br/>graph.ts"]
        Cron["Cron Trigger<br/>期限切れデータ削除・ヘルスチェック<br/>Jira/Backlog/カレンダー日次差分同期"]
    end

    subgraph Storage["Cloudflareストレージ"]
        D1[("D1 (SQLite)")]
        Vectorize[("Vectorize<br/>VEC_SHARED / VEC_PERSONAL")]
    end

    subgraph External["外部API・サービス"]
        Gemini["Gemini API"]
        Anthropic["Anthropic API"]
        Notion["Notion API"]
        Drive["Google Drive API"]
        Slack["Slack"]
        Gmail["Gmail API"]
        Jira["Jira Cloud API"]
        Backlog["Backlog API"]
        GCal["Google Calendar API"]
        GMaps["Google Places API"]
        Web["任意のWebサイト<br/>（再帰クローラー対象）"]
    end

    Browser & Houdini -->|Bearer APIキー| RAG & KB & Admin & ClaudeProxy & Graph & OAuth

    RAG <--> D1
    RAG <--> Vectorize
    RAG --> Gemini
    KB --> D1 & Vectorize & Gemini & Notion & Drive & Jira & Backlog & GCal & GMaps & Web
    KB --> DocExtract
    KB --> Dedup
    Dedup <--> D1
    Dedup <--> Vectorize
    DocExtract --> Gemini
    OAuth <--> D1
    OAuth --> Jira & Backlog & GCal & Slack
    KB -.->|OAuth接続があれば優先| OAuth
    Admin <--> D1
    ClaudeProxy --> Anthropic
    ClaudeProxy <--> D1
    Health <--> D1
    Health --> Slack & Gmail
    Graph <--> D1
    Graph <--> Vectorize
    Cron --> KB & Health
    Cron <--> D1
```

**設計判断：個人スコープの論理分離**（設計書§6-1からの変更点）。当初案の「ユーザーごとに物理的に別インデックス」は、Vectorizeバインディングが`wrangler.jsonc`に静的記述する必要があり実行時に動的生成できないため断念。代わりに個人スコープ用インデックスを1本（`VEC_PERSONAL`）にまとめ、`owner_user_id`メタデータでの厳格なフィルタを書き込み・検索の両方で強制することで、実質的に物理分離に近い安全性を確保した。

## 4. データモデル

```mermaid
erDiagram
    users ||--o{ token_budgets : "has"
    users ||--o{ namespaces : "owns (personal)"
    users ||--o{ key_namespace_grants : "granted"
    users ||--o{ memory : "creates"
    users ||--o{ audit_log : "logs"
    namespaces ||--o{ key_namespace_grants : "granted to"
    namespaces ||--o| kb_sources : "syncs from"
    namespaces ||--o{ kb_documents : "contains"
    namespaces ||--o{ crawl_jobs : "crawls into"

    users {
        text user_id PK "APIキーのSHA-256"
        text display_name
        text role "admin|member|guest"
        int created_at
    }
    namespaces {
        text namespace_id PK "shared:xxx / personal:xxx"
        text scope "shared|personal"
        text owner_user_id FK
        int result_limit "検索件数上限（任意）"
    }
    token_budgets {
        text user_id FK
        text budget_type "rag|claude"
        int limit_tokens
        int used_tokens
        int reset_at
        int reset_interval_hours
    }
    kb_sources {
        text namespace_id PK, FK
        text notion_database_id
        text drive_folder_id
        text jira_project_key
        text jira_extra_jql "任意のJQL絞り込み条件"
        int jira_last_synced_at "Cron差分同期の基準時刻"
        text backlog_project_id
        text backlog_keyword_filter
        int backlog_last_synced_at
        text calendar_id
    }
    kb_log {
        int id PK
        text op_id
        text namespace_id FK
        text source "notion|drive|jira|backlog|google_calendar|manual"
        text file
        text status "ok|error|skipped"
        text detail
    }
    kb_documents {
        text chunk_id PK "先頭チャンクのID＝ドキュメント代表ID"
        text file
        text namespace
        text scope
        text owner_user_id
    }
    oauth_connections {
        text service PK "jira|backlog|google_calendar|slack"
        text access_token
        text refresh_token
        int expires_at
        text extra_json "cloudId・スペースURL・webhook URL等"
        int connected_at
        text connected_by
    }
    oauth_pending_state {
        text state PK "CSRF対策トークン（10分で失効）"
        text service
        int created_at
        text extra_json
    }
    crawl_jobs {
        text op_id PK
        text namespace_id FK
        text queue_json "BFSキューの継続状態"
        text visited_json
        int processed_count
    }
    memory {
        int id PK
        text user_id FK
        text query
        text answer
        text sources_json
        int rating
    }
    audit_log {
        int id PK
        text user_id FK
        text namespace_id
        text query_hash
        int tokens_used
        int latency_ms
    }
    chunks_fts {
        text chunk_id PK
        text file
        text namespace
        text scope
        text owner_user_id
        text body "FTS5 trigram索引"
    }
```

`chunks_fts`（D1 FTS5仮想テーブル）はキーワード検索専用で、実際の本文全文とメタデータは**Vectorize側にも**メタデータとして重複して持たせている（`ChunkMetadata`：file/namespace/scope/chunk_index/text/source/size/ingested_at）。ベクトル検索・キーワード検索を1回のリクエストで独立に行い、結果をアプリケーション層でRRF統合する設計のため、両ストアが同じチャンクIDで対応付けられている必要がある。

**`kb_documents`**（2026-09追加）は`chunks_fts`本体（1チャンク=1行）とは別に、1ドキュメント=1行（先頭チャンクのIDのみ）を保持する軽量インデックス。グラフ可視化・重複検出（[§7](#7-知識ベース取り込みパイプライン)）・ドキュメント一覧表示が、チャンク数に比例するコスト（D1の日次Rows read上限に直結）を払わずにドキュメント単位の操作を行えるようにするために導入した。

**`oauth_connections`/`oauth_pending_state`**（2026-09-22追加）は、他のテーブルと異なり`namespace_id`を持たない＝**デプロイ単位で1接続**という設計（`JIRA_API_TOKEN`等の既存secretと同じスコープ感）。`oauth_pending_state`はOAuth認可フロー中の一時データで、コールバック受信時に検証・削除される（10分で自動失効）。

**`crawl_jobs`**（2026-09追加）は再帰URLクローラーのBFSキュー・訪問済みURL集合の継続状態を保持する一時テーブルで、クロール完了時に削除される。Cloudflare Workers Freeプランの CPU時間制限により1クロールを複数リクエストに分割して処理する必要があるため導入した（[§7](#7-知識ベース取り込みパイプライン)）。

## 5. 主要フロー

### 5.1 RAGクエリ（`/query`）

```mermaid
sequenceDiagram
    participant C as クライアント
    participant W as Worker
    participant G as Gemini API
    participant D as D1 (FTS5)
    participant V as Vectorize

    C->>W: POST /query {query, namespaces?, level?}
    W->>W: レート制限・トークン予算チェック
    W->>G: HyDE仮回答生成
    G-->>W: 仮回答テキスト
    W->>G: 仮回答をベクトル化
    par ベクトル検索
        W->>V: query(埋め込み, namespace絞り込み)
        V-->>W: 類似チャンク上位K件
    and キーワード検索
        W->>D: MATCH（BM25, trigram）
        D-->>W: 一致チャンク上位K件
    end
    W->>W: RRFで統合 + namespace別上限で間引き
    W->>G: 検索結果を根拠に最終回答生成
    G-->>W: 回答（[1][2]等の出典番号付き）
    W->>W: 出典引用率算出・予算消費
    W->>D: audit_log・memoryに記録
    W-->>C: {answer, sources, extractionRate}
```

**出典引用率（`extractionRate`）**は、回答文中に実際に出現した`[n]`番号を検出し、提示した参考情報のうち何割が実際に根拠として使われたかを表す。GAS版の`parseExtractionRate_`と同じ考え方で、「もっともらしいが根拠のない回答」を検知するハルシネーション対策指標として使っている。

### 5.2 知識ベース同期（バッチ処理パターン）

```mermaid
sequenceDiagram
    participant UI as 管理UI（クライアントJS）
    participant W as Worker
    participant Ext as Notion/Drive API
    participant G as Gemini API

    loop nextIndexがnullになるまで
        UI->>W: POST /admin/sync/notion {startIndex, batchSize, opId}
        W->>Ext: ページ/ファイル一覧・本文取得
        loop バッチ内の各ファイル
            W->>G: チャンクごとに埋め込み生成
            W->>W: Vectorize upsert + D1 FTS5 insert
        end
        W-->>UI: {documents, chunks, skipped, nextIndex}
        UI->>UI: 進捗表示、startIndex = nextIndex
    end
```

Cloudflare Workersの「1回の呼び出しあたりのサブリクエスト数上限」に対応するため、**1回のHTTPリクエストで全件を処理せず、クライアント側がループしてバッチを送り続ける**設計にしている（`startIndex`/`batchSize`/`opId`/`nextIndex`）。この設計は実際にHoudini21データベース（80ページ）の同期でサブリクエスト数上限エラーに遭遇したことから導入した。PDF/PPTX/音声動画の変換が絡むDrive同期はNotion同期よりさらに重いため、`batchSize`をより小さく（実運用では1）する必要があることも実機検証で判明している。同じバッチ処理パターンは、後発のJira/Backlog連携（`jiraSync.ts`/`backlogSync.ts`）・再帰URLクローラー（`urlImport.ts`、`crawl_jobs`テーブルでBFSキューを永続化）にもそのまま再利用している。

### 5.3 OAuthクリック接続（2026-09-22追加）

Jira/Backlog/Googleカレンダー/Slackの認証情報は、従来「APIトークンを発行してWranglerのシークレットとして登録する」というCLI操作が必須だった。非技術者でも接続作業を完結できるよう、ブラウザでの認可だけで完了するOAuthフローを追加した。

```mermaid
sequenceDiagram
    participant UI as 管理UI（ブラウザ）
    participant W as Worker
    participant Svc as 外部サービス（Jira/Backlog/Google/Slack）

    UI->>W: GET /admin/oauth/jira/start?key=<APIキー>
    Note over UI,W: 唯一この1回だけ、通常のAuthorizationヘッダーの<br/>代わりにcrypto.randomUUID()単位のstateで認可を検証
    W->>W: APIキー検証・stateをoauth_pending_stateに保存
    W-->>UI: 302 Redirect（Svcの認可画面へ、state付き）
    UI->>Svc: ブラウザがそのまま遷移・ログイン・許可
    Svc-->>UI: 302 Redirect（/admin/oauth/jira/callback?code&state）
    UI->>W: GET /admin/oauth/jira/callback?code&state
    W->>W: stateを検証・消費（1回限り）
    W->>Svc: POST トークンエンドポイント（code→access/refresh token）
    Svc-->>W: access_token, refresh_token, 付随情報
    W->>W: oauth_connectionsに保存
    W-->>UI: 簡易HTML（接続完了、2.5秒後に管理画面へ自動遷移）
```

OAuth開始エンドポイント（`GET /admin/oauth/<service>/start`）はブラウザの直接ナビゲーションで叩かれるため、他の全エンドポイントと異なり`Authorization`ヘッダーを付与できない。管理UIが既にlocalStorageに保持しているAPIキーをこの1回だけクエリパラメータとして渡す設計にしており、これに伴うトレードオフ（APIキーが一時的にブラウザ履歴・サーバーログに残りうる）は認識のうえで許容している（管理者専用の内部ツールという性質上）。コールバック（`GET /admin/oauth/<service>/callback`）はAuthorizationヘッダーを一切持たないため、`oauth_pending_state`のstate（10分で失効・1回限り消費）が認可の正当性を保証する唯一の手段になっている。

各連携の同期処理（`jiraSync.ts`等）は、OAuth接続があればそれを（有効期限が近ければ自動更新して）優先し、無ければ従来のsecret方式にフォールバックする設計にしているため、既存の設定を持つ環境は無変更で動作し続ける。GoogleカレンダーはGmail送信（`gmailOAuth.ts`）で登録済みのOAuthクライアントをスコープ違いでそのまま流用でき、新規のOAuthアプリ登録が不要な点が実装上の工夫。

## 6. セキュリティ・アクセス制御

- **APIキー認証**：生キーは発行時にしか表示されず、以後はSHA-256ハッシュのみをDBに保持する
- **namespace RBAC**：`key_namespace_grants`テーブルで「どのキーがどのshared namespaceを見られるか」を明示的に管理。adminロールは無条件に全shared namespaceを閲覧可能、それ以外は許可リストに無いnamespaceには一切アクセスできない
- **個人スコープの二重強制**：`personal:<userId>`への書き込み・検索は、リクエスト元ユーザー自身のnamespace以外を拒否する（他ユーザーの個人データへの越権アクセスを防止）
- **レート制限**：既存の`audit_log`の直近件数を数える固定ウィンドウ方式（60秒30回）。専用テーブルを追加せずに実現
- **トークン予算**：`token_budgets`（`budget_type`が`rag`/`claude`で分離）。呼び出し前にチェックし、呼び出し後に実測トークン数で消費する。予算超過は429で拒否
- **秘密情報の保持**：Gemini/Notion/Google/Anthropic/Slack/GmailのAPIキー・トークンはすべてWorkerのシークレット（`wrangler secret put`）にのみ保持し、クライアントには一切渡さない
- **OAuthトークンの保持**（2026-09-22追加）：Jira/Backlog/Googleカレンダー/Slackのアクセストークン・リフレッシュトークンは`oauth_connections`テーブルに平文で保持している（Cloudflare D1自体は保存時暗号化されるが、アプリケーション層での追加の暗号化は行っていない）。他のsecret類（Wranglerシークレット、Workerの実行環境変数として保持）と比べて、DBへの不正アクセス経路が増える点はトレードオフとして認識しており、今後の課題（[§10](#10-今後の課題)）としている
- **再帰クローラーのSSRF対策**：クロール起点URLはhttp/https以外のスキームを拒否し、リンクを辿る範囲を起点と同一オリジンに限定する。除外パターンは正規表現ではなく単純な部分一致とし、管理者が入力した任意パターンによるReDoSを避けている

## 7. 知識ベース取り込みパイプライン

```mermaid
flowchart LR
    Source["Notion / Drive / URL(単発・再帰クロール) /<br/>QA CSV / 直接アップロード /<br/>Jira / Backlog / Googleカレンダー / Googleマップ"] --> Extract{"形式判定"}
    Extract -->|"テキスト系"| Text["そのまま取得"]
    Extract -->|"PDF"| PDF["Geminiネイティブ文書理解<br/>(小: インライン / 大: File API)"]
    Extract -->|"DOCX/PPTX"| Zip["自前ZIPパーサ<br/>(DecompressionStream)<br/>+ XMLタグ除去"]
    Extract -->|"音声/動画"| Media["Gemini File API<br/>アップロード→ACTIVE待ち→文字起こし"]
    Extract -->|"YouTube URL"| YT["Gemini fileData<br/>(URLを直接渡す、DL不要)"]
    Extract -->|"HTML(URL・再帰クロール)"| HTML["HTMLRewriterで<br/>script/style除去→テキスト抽出<br/>+ リンク抽出でBFSキューに追加"]
    Extract -->|"Jira/Backlog課題"| Issue["要約+説明+種別+ステータスを結合<br/>（JiraはADF→プレーンテキスト変換）"]
    Extract -->|"カレンダー予定"| Cal["タイトル+日時+場所+説明を結合"]
    Extract -->|"地図の場所"| Place["Places APIの住所・電話番号・<br/>営業時間・評価を結合"]

    Text & PDF & Zip & Media & YT & HTML & Issue & Cal & Place --> Sanitize["制御文字・孤立サロゲート除去"]
    Sanitize --> Chunk["スライディングウィンドウ分割<br/>(1000文字, overlap 150)"]
    Chunk --> Embed["Geminiで埋め込み生成"]
    Embed --> Store["Vectorize upsert<br/>+ D1 FTS5 insert<br/>+ kb_documents更新"]
    Store --> Dedup{"重複チェック時<br/>（管理者が任意で実行）"}
    Dedup -->|"先頭チャンク本文+全体文字数が一致"| Flag["重複組として提示<br/>→管理者が個別に削除"]
```

DOCX/PPTXの変換は、外部ライブラリを追加せず**ZIP形式を自前でパース**する実装にしている（Workers組み込みの`DecompressionStream('deflate-raw')`でDEFLATE展開）。PDFは専用パーサを実装する代わりに**Geminiのマルチモーダル文書理解に丸ごと渡す**方式を採った。これによりレイアウト崩れに強く、実装コストも抑えられる一方、Gemini呼び出しの追加コスト・レイテンシが発生する点はトレードオフとして認識しておく必要がある。

**再帰URLクローラー**（`urlImport.ts`の`handleCrawlUrl`）は、起点URLからリンクを辿って同一オリジン配下の複数ページをまとめて登録する。1クロールを1リクエストで完結させず、BFSキューと訪問済みURL集合を`crawl_jobs`テーブルに永続化して複数リクエストに分割する設計（[§5.2](#52-知識ベース同期バッチ処理パターン)と同じバッチ処理パターン）。既存ページの重複登録を避ける`skipExisting`オプション、パス接頭辞・除外パターンによる絞り込みにも対応する。

**重複コンテンツ検出**（`kbDocuments.ts`の`handleFindDuplicateDocuments`）は、`kb_documents`テーブル（ソースに関わらず全ドキュメントを1行ずつ保持）を使い、各ドキュメントの先頭チャンク本文と文書全体の文字数（Vectorizeメタデータに既に保存済みの値）が完全一致するものを重複組として検出する。ソースをまたいだ重複（例：同じページをURL登録とクロールの両方で登録した、Notion/Drive/Jira間で内容が重複した）も、`kb_documents`がnamespace単位で全ソースを横断しているため自動的に検出対象になる。意味的な類似度（近似一致）ではなく完全一致のみを対象にしているのは、削除という取り消せない操作につながる機能のため、誤検出（似ているだけの別文書を巻き込む）を避ける側に倒したため。

**Jira/Backlog連携**（`jiraSync.ts`/`backlogSync.ts`）は、プロジェクト単位で課題（要約・説明・種別・ステータス）を一括登録する。namespaceごとにJQL条件（Jira）・キーワード（Backlog）で絞り込みでき、Cron Trigger（毎日UTC 4時）による自動差分同期にも対応する（前回同期以降に更新された課題だけを追加登録。初回の全件取り込みは管理タブからの手動実行が必要）。**Googleカレンダー連携**（`calendarSync.ts`）は差分検知をせず、毎回固定の時間窓（既定：過去7日〜未来90日）を丸ごと再取得する方式にしている（予定は件数が少なく、既存予定の編集も取りこぼさないための単純な設計）。**Googleマップ連携**（`mapsImport.ts`）はPlaces APIを使い、単発登録と複数件のCSV風一括登録（1行1件）の両方に対応する。

## 8. 実装上の技術的な工夫と、実際に発見・修正したバグ

開発を通じて、ローカル検証だけでは見つからない実運用特有のバグを複数発見した。代表的なもの：

| 症状 | 原因 | 対処 |
|---|---|---|
| `VECTOR_UPSERT_ERROR: id too long` | Vectorizeのベクトル ID は64バイト上限。日本語の長いタイトルをそのままIDに使うと超過 | ハッシュベースの固定長ID（`sha256(namespace+file)`の先頭40文字＋チャンク番号）に変更 |
| `Too many subrequests by single Worker invocation` | Notion/Drive同期で1ページごとに複数回の外部API呼び出しが積み重なる | `startIndex`/`batchSize`/`opId`によるバッチ処理化（クライアント側ループ） |
| `VECTOR_QUERY_ERROR: max top K is 50` | `returnMetadata:"all"`時のtopK上限を、候補プール拡大ロジックの二重乗算で超過 | 一箇所で`Math.min(limit*3, 50)`を計算し共有 |
| `getByIds(): too many ids` | Vectorizeの`getByIds()`は1回20件までしか受け付けない（`upsert`とは別の上限） | 20件ずつのチャンクに分割して複数回呼ぶ |
| `Memory limit exceeded before EOF` | 大きいPPTXファイルのダウンロード・ZIP展開でWorkers isolateのメモリ上限（128MB）に到達 | 応急処置としてダウンロード前に`Content-Length`で足切りしていたが、chunked転送で`Content-Length`が無いケースでは素通りしてしまう不備があった。最終的にはDOCX/PPTXについて「ファイル全体をダウンロードしない」設計に変更（下記参照） |
| PPTX/DOCXが20MB（後に約90MB）を超えると同期できない | 上記対策のダウンロード上限は、ファイル容量の大半を占める埋め込み動画・画像も含めた「ファイル全体」に対する足切りだった。抽出対象は実際には`word/document.xml`・`ppt/slides/slideN.xml`という小さなXMLのみ | HTTP RangeリクエストでZIPのEnd of Central Directory・central directory・対象XMLエントリだけを個別に取得する方式に変更（`docExtract.ts`の`ByteRangeSource`、`driveSync.ts`の`driveRangeSource`）。ファイル全体を一度もメモリに載せないため、実質的にファイルサイズの上限が無くなった（2026-08-27）。PDF・音声・動画はGeminiに実データを渡す必要がある性質上この手法は使えず、約90MBの上限が残る |
| 管理UIで`Unexpected token '<'`（JSON解析エラー） | Drive同期がPDF/PPTX変換込みで1リクエスト115秒かかり、ブラウザ/プロキシ側がタイムアウトしHTMLエラーページを返す | 管理UIのDrive同期ボタンの`batchSize`を1に縮小、非JSON応答時に分かりやすいエラーメッセージを表示 |
| GCPの`iam.disableServiceAccountKeyCreation`でサービスアカウントキーが作れない | Google Workspaceの「セキュアなデフォルト」ポリシーが個人プロジェクトにも自動適用 | プロジェクト単位でポリシーを無効化。Gmail送信は個人アカウント特有の制約（Domain-Wide Delegation不可）のため別途OAuthリフレッシュトークン方式に切り替え |
| 管理画面の全JSが構文エラーで機能停止（2026-09-22、本番で発生） | 管理画面（`chatUi.ts`）はHTML全体を外側のJS/TSテンプレートリテラルとして持つ構造で、内側のJS文字列に改行を入れるには`\\n`（バックスラッシュ2つ）と書く必要があるところを`\n`（1つ）のまま書いてしまい、外側のテンプレートリテラルの時点で実際の改行文字に変換されてしまっていた。ブラウザ側では「ダブルクォート文字列の中に生の改行がある」構文エラーになり、`<script>`ブロック全体が停止＝ページ上の全機能が止まる | 該当箇所を修正し、以降は生のソーステキストではなく**esbuildで実際にビルドした`chatUiHtml()`の出力**から`<script>`の中身を取り出して構文チェックする検証手順に切り替えた（ソーステキストだけの構文チェックでは、このテンプレートリテラル二重化に起因するエスケープ漏れを検出できないことが判明したため） |
| `wrangler d1 migrations apply --remote`が`code: 7403`で失敗する（同一コマンドの再実行では成功） | Cloudflare API側の一時的なエラーと推定（`wrangler d1 execute`による単発クエリは同時に成功していたため、認証情報自体は正しかった） | 単純リトライで解消。恒久対策ではなく運用上の既知事象として記録 |

これら以外にも、Windows/Git-Bash環境での日本語文字化け、PowerShellの`curl`エイリアス、workers.devドメインへのボット対策403など、開発環境特有の問題にも多数遭遇した。詳細と対処法は[README.mdのトラブルシューティング](../cloudflare-rag-poc/README.md#トラブルシューティング実際に遭遇したエラーと対処)に集約している。

## 9. GAS版との機能対応表（サマリ）

詳細な機能単位の対応表は[docs/gas-feature-parity.md](gas-feature-parity.md)を参照。2026-08-26時点のサマリ（コア機能のパリティ状況。2026-09以降に追加したJira/Backlog/Googleカレンダー/GoogleマップとOAuthクリック接続は、そもそもGAS版に対応機能が無い**Cloudflare POC限定の新機能**であり、パリティ表の対象外）：

- ✅ 完了：コア検索・回答生成、Admin API、Notion/Drive同期（PDF/DOCX/PPTX/音声動画/YouTube/URL/QA CSV含む）、UI（タブ構成・3Dグラフ・ブラウザ内Admin）、利用統計・評価統計、レート制限、期限切れ履歴の自動削除、バックアップ、ヘルスチェック・アラート（Slack/Gmail）、Claude APIプロキシ（Houdiniチュートリアル生成の移行先）
- 🚧 保留：チャット履歴検索のRAG統合（ユーザー判断により保留）
- 🚫 対象外：Houdiniチュートリアル生成専用のClaude呼び出しは、当初「RAGには不要」として対象外にしていたが、後に`tutorial_agent.py`のGAS依存を移行する目的で追加した経緯がある
- ➕ **GAS版を上回る新機能**（2026-09、GAS版への移植は未計画）：再帰URLクローラー、重複コンテンツ検出、Jira/Backlog/Googleカレンダー/Googleマップ連携、OAuthクリック接続化

## 10. 今後の課題

- Google Drive・Claude APIプロキシとも実データでの動作確認は済んだが、**Houdini実機での`tutorial_agent.py`統合テストは未実施**（開発環境にHoudiniが無いため）
- 大きいPPTX/DOCXは、ファイル全体をダウンロードせずHTTP Rangeで本文XMLだけ取得する方式に切り替え（2026-08-27）、事実上サイズ上限が無くなった（[§8](#8-実装上の技術的な工夫と実際に発見修正したバグ)参照）。ただしPDF・音声・動画はGeminiに実データを渡す必要がある性質上、引き続きダウンロード自体が必要で、Workersのメモリ上限（128MB）に対する安全マージンとして約90MBの上限が残っている
- チャット履歴を検索コンテキストとして再利用する機能（`searchMemory_`相当）は設計判断が必要なため保留中
- 利用統計ダッシュボードがGemini/Claude両方のトークン消費を合算表示しており、budget_type別の内訳表示は今後の改善候補
- OAuthアクセストークン・リフレッシュトークンの保存はアプリケーション層での暗号化を行っておらず（[§6](#6-セキュリティアクセス制御)）、より高いセキュリティ要件が必要になった場合は暗号化またはCloudflareのSecrets Store等への移行を検討する
- Jira/Backlog/Googleマップ連携は実際のOAuthアプリ登録・実データでの動作確認が未実施（Cloudflare Workers上の実装・型検査・ローカルD1マイグレーションまでは検証済みだが、外部サービスとの実際のOAuthハンドシェイクは未検証）
- `screen_capture.py`（Houdini側、ネットワークエディタのスクリーンショット取得）は、2026-09-26に原因（古いコピーの配置・誤ったAPIの使用・撮影対象の誤り）を特定して作り直した。実機での再検証待ち（[docs/houdini21-tutorial-gen-report.md](houdini21-tutorial-gen-report.md) §8.5参照）。Cloudflare POC自体の課題ではないが、動画生成連携の完成度に影響するため記録しておく

---

*関連ドキュメント: [cloudflare-rag-poc/README.md](../cloudflare-rag-poc/README.md) / [docs/gas-feature-parity.md](gas-feature-parity.md) / [docs/cloudflare-rag-operations-manual.md](cloudflare-rag-operations-manual.md) / [docs/cloudflare-vs-firebase-comparison.md](cloudflare-vs-firebase-comparison.md)*
