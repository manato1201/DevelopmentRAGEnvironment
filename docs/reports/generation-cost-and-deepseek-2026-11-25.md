# チュートリアル生成の費用の原因と、DeepSeek の採否（2026-11-25）

実証実験（第 2 回、11/24・25）で、Basic のチュートリアル生成が 1 回 約 2 ドルかかっていた。原因を記録から調べ、品質を落とさずに下げる。あわせて、DeepSeek の API に置き換えてよいかを調べた。

## 1. 結論

- **費用の主因は、既定のモデルが `claude-sonnet-5` のままだったこと。** このモデルには effort（思考の深さ）を送っていないため、1 回の生成で出力が多く、API の往復も上限（80）近くまで回っていた。開発で使っていた `claude-sonnet-5-5`（effort: medium。単価は同じ $2 / $10）は、同じ種類の題材で 0.2〜0.4 ドルだった。
- モデルの選択は「設定」（設定者だけ）にしかないため、参加者は以前の既定のまま動いていた。→ **既定を `claude-sonnet-5-5` に変え、以前の既定のままの設定は 1 回だけ移す**（`rag_client.migrate_config`）。新しいパネルを配った時点で効く。
- **DeepSeek は、いまは採用しない。** 理由は §4。

## 2. 記録から分かったこと

### 2.1 実証実験の生成（Worker の `audit_log`、11/24・25）

Claude の呼び出しは、すべて Worker（`/claude/messages`）を通り、呼び出しごとに入力・出力のトークン数が残る（キャッシュの読み込み・書き込みは残っていない）。参加者の呼び出しを、2 分以上の間で区切って 1 回の生成とみなした。

| 項目 | 値（参加者の生成 20 回） |
|---|---|
| モデル | すべて `claude-sonnet-5` |
| API の往復 | 中央値 78 回（上限 80） |
| 出力トークン | 中央値 約 65,000（出力だけで 約 0.65 ドル） |
| 1 回の呼び出しの出力 | 中央値 約 360。ただし 4,000 を超える 5% の呼び出しが、出力全体の 50% |
| 出力の上限（16,000）に達した呼び出し | 7 回（途中で切れて、やり直しになる） |
| キャッシュされない入力 | 少ない（ローリングキャッシュは効いている） |

### 2.2 キャッシュの読み込み（手元の生成の記録、`logs/tutorial_agent`）

手元の記録には、キャッシュの読み込みも残る。往復 20 回以上の 8 回では、**キャッシュの読み込みの費用が、出力の費用とほぼ同じ**（中央値 0.28 ドルと 0.26 ドル）。キャッシュの読み込みは、会話が伸びるほど 1 回あたりが重くなる（往復の回数の、ほぼ 2 乗で増える）。往復が 78 回の参加者の生成では、出力より大きく、出力 0.65 ドル ＋ 読み込み 約 1 ドル ＋ 書き込みで、**合計 約 2 ドルになり、報告と合う**。

### 2.3 モデルによる差（手元の生成の指標、`localRAG/tutorials/*_metrics.json`）

`claude-sonnet-5-5`（effort: medium）の生成 25 回（Basic・Applied・Advanced）:

| 題材の例 | レベル | 費用 | 出力トークン | 完成 |
|---|---|---|---|---|
| RBD の破壊 | Basic | 0.18 ドル | 6,908 | ○ |
| さびの質感 | Basic | 0.37 ドル | 13,117 | ○ |
| 炎の竜巻 | Applied | 0.82 ドル | 24,972 | ○ |
| 25 回の中央値 | 全レベル | 0.42 ドル | — | 23 / 25 が完成 |

`claude-sonnet-5` の過去の生成（手順書の末尾の記録）は 0.3〜3.0 ドルで、同じ題材の範囲では `sonnet-5-5` より高い。

## 3. 直したこと（品質を落とさない範囲）

1. **既定のモデルを `claude-sonnet-5-5` に**（`tutorial_agent.DEFAULT_MODEL`・パネルの既定の設定・生成の呼び出しの既定）。effort は medium（`tutorial_agent._MODEL_EFFORT`。以前からの設定）。
2. **以前の既定のままの設定を、1 回だけ移す**（`rag_client.migrate_config`。印 `tutorial_model_migrated` を残すので、設定者があとで `claude-sonnet-5` を選び直したときは、そのまま）。Opus など、ほかのモデルを選んでいる設定は変えない。

### 3.1 品質の確認（2026-11-25、`sonnet-5-5`・Basic で 2 回生成）

hython（画面の無い Houdini 22.0.506）で、パネルと同じ生成（`TutorialAgent`）を動かした。画面が無いので、ビューポートの画像による見た目の確認はできない（AI は数値で確かめる）。題材は、参加者の作業ファイルにあった内容に合わせた。

| | RBD（箱が割れて、地面に落ちて転がる） | Pyro（球から煙が立ち上る） | 参考: 参加者の生成（`sonnet-5`） |
|---|---|---|---|
| 費用 | **0.33 ドル** | **0.70 ドル** | 約 2 ドル |
| API の往復 | 19 回 | 51 回 | 中央値 78 回 |
| 出力トークン | 11,757 | 18,371 | 中央値 約 65,000 |
| 時間 | 2 分 | 5 分 | — |
| 完成・レッスンの点 | 完成・94 / 100 | 完成・94 / 100 | — |
| 中身 | SOP の RBD（Voronoi Fracture → Assemble → RBD Bullet Solver）。10 個の破片が落ちて広がる（1・24・48 フレームで確認）。Tab に出ないノード・つなぎ忘れなし | **問題あり**: SOP の一覧に `pyro_` で始まるノードが無いことから「SOP には Pyro が無い」と誤って判断し、Copernicus（COP）の Pyro で組んだ。表示フラグがソース（`pyro_sourceshape1`）に残り、煙が映らない | DOP の出力のつなぎ忘れ・Tab に出ないノード（修正リストの G） |

Pyro の問題を受けて直したこと:
- 生成の指示の「よく使うノード」に、Tab に出ない `pyrosolver::2.0`（DOP）と `mountain::2.0` が載っていた（第 2 回の Pyro の見本が古い DOP で作られた一因）。SOP の Pyro（`pyrosource → volumerasterizeattributes → pyrosolver`）・SOP の RBD を載せ、古いノードは「使わない」と書いた。
- 指示に、「Pyro は SOP で組む。COP の Pyro は、題材が画像・2D のときだけ」「SOP に `pyro_` で始まるノードが無いのは正常」「表示フラグは、最後のノードに付ける」を足した。
- 点検（`_structure_issues`）に、「SOP・COP のネットワークで、表示フラグが途中のノードに付いている」を足した（Houdini 付属の部品の中は見ない）。今回の Pyro の結果で 1 件見つかり、RBD の結果では 0 件だった。

残り: Pyro を、直したあとでもう一度生成して、SOP の Pyro で組まれ、煙が映ることを確かめる（約 0.5〜0.7 ドル）。実際の Houdini（画像の確認あり）でも、1 回ずつ確かめるとよい。

ほかの候補（今回は入れない）:
- **古い画像・大きなツール結果を、履歴から外す**: 読み込みは減るが、外した位置からあとのキャッシュが無効になり、書き込み（入力の 1.25 倍）が増える。効果が小さく、見た目の確認（画像）にも響くので、入れない。
- **往復の上限（80）を下げる**: 完成しない生成が増える恐れがある。`sonnet-5-5` での往復の数を見てから決める。

## 4. DeepSeek を採用するか

**いまは採用しない。** 調べた範囲（2026-11 時点。公式の料金ページ・モデルカードには届いていないため、第三者の集計）:

| 観点 | Claude Sonnet 5.5 | DeepSeek V4.1 Flash | DeepSeek V4 Pro |
|---|---|---|---|
| 単価（入力 / 出力、100 万トークン） | $2 / $10 | 昼 $0.30 / $1.20（夜は半額） | 昼 $1.32 / $3.96 |
| エージェントの作業（Terminal-Bench 2.1、Vals） | 83.1% | 74.5% | Sonnet 5 との比較で 54.7%（Sonnet 5 は 74.5%） |
| 画像の入力 | ○ | ○ | ×（このツールは、ビューポートの画像で見た目を確かめるので、使えない） |
| データの保存先 | Anthropic（米国） | 中国本土のサーバー（DeepSeek のプライバシーポリシー） | 同左 |
| このツールでの使い方 | いまの作り（キャッシュの位置の指定・effort・拒否の扱い） | Anthropic 互換の窓口があるとされるが、未確認。キャッシュは自動 | 同左 |

採用しない理由:
1. **品質**: エージェントの作業で、Sonnet 5.5 が明らかに上。手順書の不足（第 2 回の主な不満）は、モデルの判断の質で増える。画像が使えるのは Flash だけで、Flash は Pro より弱い。
2. **データ**: 参加者の作業（題材の文・Houdini の画面）が、中国本土のサーバーに送られる。大学によっては、DeepSeek の利用を禁止・制限している。実証実験の同意の範囲を越える。
3. **金額の差が小さくなる**: 上の修正で、Basic の生成は 0.2〜0.4 ドルの見込み。Flash にすると 0.05 ドル前後になりうるが、差は 1 回 0.3 ドル程度で、品質とデータの問題に見合わない。

もう一度考えるとき: 参加者のデータを送らない用途（Reference の説明文の下書きなど、公開資料だけを入れる処理）で、Flash を試すのは選択肢になる。その場合も、公式の料金・利用規約・API の互換性を、DeepSeek の公式ドキュメントで確かめてから。

## 5. 参考

- 記録: Worker の `audit_log`（`namespace_id = 'claude:proxy'`）、手元の `logs/tutorial_agent/*.jsonl`・`localRAG/tutorials/*_metrics.json`。参加者ごとの値・生データは、リポジトリに置かない（ここには、集計した値だけを書いた）。
- DeepSeek の料金: [morphllm](https://www.morphllm.com/deepseek-api)・[benchlm](https://benchlm.ai/deepseek/api-pricing)・[requesty](https://www.requesty.ai/blog/deepseek-api-pricing)・[nxcode](https://www.nxcode.io/resources/news/deepseek-api-pricing-complete-guide-2026)
- 比較: [Sonnet 5.5 vs DeepSeek V4.1 Flash（benchlm）](https://benchlm.ai/compare/claude-sonnet-5-5-vs-deepseek-v4-1-flash)・[Sonnet 5 vs DeepSeek V4 Pro（benchlm）](https://benchlm.ai/compare/claude-sonnet-5-vs-deepseek-v4-pro)
- 画像の入力: [codepick](https://codepick.dev/en/guides/deepseek-v4-flash-vision-guide/)・[apidog](https://apidog.com/blog/deepseek-v4-flash-vision-api/)
- データ: [DeepSeek Privacy Policy](https://cdn.deepseek.com/policies/en-US/deepseek-privacy-policy.html)・[University of Alberta の評価](https://www.ualberta.ca/en/information-services-and-technology/news/ciso-news/deepseek-privacy-security-assessment.html)・[UVic の制限](https://www.uvic.ca/systems/status/notices/deepseek.php)
- Sonnet 5.5 の料金: [eesel](https://www.eesel.ai/blog/claude-sonnet-5-5-pricing)・[developersdigest](https://www.developersdigest.tech/models/claude-sonnet-5-5)（キャッシュの読み込みが $0.10 に下がったとする情報もある。本ツールの見積もり `tutorial_agent._MODEL_PRICES` は $0.20 のまま。公式で確かめてから直す）
