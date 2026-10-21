<#
.SYNOPSIS
  RAGReel チュートリアル生成パネルを、Houdini のパッケージとして導入する（2026-10-21）。

.DESCRIPTION
  1. パネルの Python ファイルを、%LOCALAPPDATA%\RAGReelTutorial\python へコピーする
  2. パネル定義（.pypanel。薄い読み込み用）を、%LOCALAPPDATA%\RAGReelTutorial\houdini\python_panels へ置く
  3. 見つかった Houdini のバージョンごとに、Documents\houdiniXX.X\packages\ragreel_tutorial.json を書く
     （これだけで、Houdini の起動時にパネルが読み込まれる。Python Panel Editor での貼り付けは要らない）
  4. 設定ファイル（~\.houdini\rag_chatbot_config.json）に、接続先と動画エンジンの場所を書く（元の設定は退避する）

  管理者権限は要らない。何度実行しても同じ結果になる（更新にも使える）。
  元に戻すときは  -Uninstall。

.EXAMPLE
  .\install.ps1 -CloudflareUrl https://rag-poc.example.workers.dev
  .\install.ps1 -HoudiniVersion 22.0 -NoPrompt
  .\install.ps1 -Uninstall
#>
[CmdletBinding()]
param(
  [string]$HoudiniVersion = "",
  [string]$CloudflareUrl = "",
  [string]$ApiKey = "",
  [string]$VideoExe = "",
  [string]$InstallDir = (Join-Path $env:LOCALAPPDATA "RAGReelTutorial"),
  [string]$DocumentsDir = [Environment]::GetFolderPath("MyDocuments"),
  # 生成物（localRAG\tutorials）とログ（logs）の保存先。パネルの「Bridge Directory」に設定する（未設定だと保存できない）
  [string]$DataDir = (Join-Path ([Environment]::GetFolderPath("MyDocuments")) "RAGReelTutorial"),
  [string]$ConfigPath = (Join-Path $HOME ".houdini\rag_chatbot_config.json"),
  [switch]$NoPrompt,
  [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$AppId = "{16D15ECD-5C8C-4677-9B08-E7386D851014}_is1"   # RAGReel（動画エンジン）のインストーラーのID

function Write-Step([string]$Text) { Write-Host "  $Text" }

function Get-HoudiniFolders {
  # Documents の下の houdini21.0 / houdini22.0 のようなフォルダ（Houdini を一度でも起動すると作られる）
  $all = @(Get-ChildItem -Path $DocumentsDir -Directory -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match '^houdini\d+\.\d+$' })
  if ($HoudiniVersion) { $all = @($all | Where-Object { $_.Name -eq "houdini$HoudiniVersion" }) }
  return $all
}

function Find-VideoExe {
  if ($VideoExe -and (Test-Path $VideoExe)) { return (Resolve-Path $VideoExe).Path }
  $candidates = @(
    (Join-Path $env:LOCALAPPDATA "Programs\RAGReel\video_factory_cloudrag_poc.exe"),
    (Join-Path $env:ProgramFiles "RAGReel\video_factory_cloudrag_poc.exe")
  )
  foreach ($root in @("HKCU", "HKLM")) {
    $key = "${root}:\Software\Microsoft\Windows\CurrentVersion\Uninstall\$AppId"
    if (Test-Path $key) {
      $loc = (Get-ItemProperty $key).InstallLocation
      if ($loc) { $candidates += (Join-Path $loc "video_factory_cloudrag_poc.exe") }
    }
  }
  foreach ($c in $candidates) { if ($c -and (Test-Path $c)) { return $c } }
  return ""
}

function Read-Config {
  if (Test-Path $ConfigPath) {
    try { return (Get-Content -Raw -Encoding UTF8 $ConfigPath | ConvertFrom-Json) } catch { }
  }
  return ([pscustomobject]@{})
}

function Set-ConfigValue($Config, [string]$Name, $Value) {
  if ($Config.PSObject.Properties.Name -contains $Name) { $Config.$Name = $Value }
  else { $Config | Add-Member -NotePropertyName $Name -NotePropertyValue $Value }
}

if ($Uninstall) {
  Write-Host "RAGReel チュートリアル生成パネルを削除します"
  foreach ($h in Get-HoudiniFolders) {
    $pkg = Join-Path $h.FullName "packages\ragreel_tutorial.json"
    if (Test-Path $pkg) { Remove-Item $pkg -Force; Write-Step "パッケージを削除: $pkg" }
  }
  if (Test-Path $InstallDir) { Remove-Item $InstallDir -Recurse -Force; Write-Step "フォルダを削除: $InstallDir" }
  Write-Host "完了。設定ファイル（$ConfigPath）は残しています。Houdini を再起動してください。"
  return
}

Write-Host "RAGReel チュートリアル生成パネルを導入します"

# ── 0. 元のファイルの確認 ─────────────────────────────────────────────
$srcPython = Join-Path $PSScriptRoot "python"
$srcPanel = Join-Path $PSScriptRoot "houdini\python_panels"
if (-not (Test-Path (Join-Path $srcPython "rag_chatbot.py"))) {
  throw "python\rag_chatbot.py が見つかりません。zip を展開したフォルダで実行してください。"
}
$houdiniFolders = @(Get-HoudiniFolders)
if ($houdiniFolders.Count -eq 0) {
  throw "Houdini の設定フォルダ（$DocumentsDir\houdiniXX.X）が見つかりません。Houdini を一度起動してから、もう一度実行してください。"
}

# ── 1. ファイルのコピー ───────────────────────────────────────────────
New-Item -ItemType Directory -Force -Path (Join-Path $InstallDir "python"), (Join-Path $InstallDir "houdini\python_panels") | Out-Null
$copied = 0
Get-ChildItem -Path $srcPython -Filter *.py | ForEach-Object {
  Copy-Item $_.FullName (Join-Path $InstallDir "python\$($_.Name)") -Force; $copied++
}
Get-ChildItem -Path $srcPanel -Filter *.pypanel | ForEach-Object {
  Copy-Item $_.FullName (Join-Path $InstallDir "houdini\python_panels\$($_.Name)") -Force
}
if (Test-Path (Join-Path $PSScriptRoot "VERSION")) { Copy-Item (Join-Path $PSScriptRoot "VERSION") (Join-Path $InstallDir "VERSION") -Force }
Write-Step "$copied 個の Python ファイルを配置しました: $InstallDir"

# ── 2. Houdini のパッケージ定義 ───────────────────────────────────────
# Houdini はパスの区切りに / を使う。
$home_ = $InstallDir.Replace("\", "/")
$package = [ordered]@{
  enable = $true
  env    = @(
    [ordered]@{ RAGREEL_TUTORIAL_HOME = $home_ },
    [ordered]@{ PYTHONPATH = [ordered]@{ method = "append"; value = '$RAGREEL_TUTORIAL_HOME/python' } }
  )
  path   = '$RAGREEL_TUTORIAL_HOME/houdini'
}
$packageJson = $package | ConvertTo-Json -Depth 5
foreach ($h in $houdiniFolders) {
  $pkgDir = Join-Path $h.FullName "packages"
  New-Item -ItemType Directory -Force -Path $pkgDir | Out-Null
  [System.IO.File]::WriteAllText((Join-Path $pkgDir "ragreel_tutorial.json"), $packageJson, $Utf8NoBom)
  Write-Step "パッケージを登録: $($h.Name)"
}

# ── 3. 設定ファイル ───────────────────────────────────────────────────
if (-not $NoPrompt) {
  if (-not $CloudflareUrl) { $CloudflareUrl = Read-Host "接続先の URL（例: https://xxxx.workers.dev。あとで Settings タブでも入力できます。空のままで Enter）" }
  if (-not $ApiKey -and $CloudflareUrl) {
    $secure = Read-Host "あなたの API キー（入力は画面に出ません。空のままで Enter）" -AsSecureString
    $ApiKey = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
  }
}
$config = Read-Config
if (Test-Path $ConfigPath) {
  $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
  Copy-Item $ConfigPath "$ConfigPath.backup_$stamp" -Force
}
# チュートリアル生成は、Claude も検索も、接続先（Cloudflare）経由にする
Set-ConfigValue $config "tutorial_rag_mode" "cloudflare"
Set-ConfigValue $config "tutorial_claude_backend" "cloudflare"
if ($CloudflareUrl) { Set-ConfigValue $config "cf_url" $CloudflareUrl.Trim().TrimEnd("/") }
if ($ApiKey) { Set-ConfigValue $config "cf_api_key" $ApiKey.Trim() }
# 保存先（Bridge Directory）。すでに設定されていれば、そのまま使う。
$currentDir = if ($config.PSObject.Properties.Name -contains "local_bridge_dir") { [string]$config.local_bridge_dir } else { "" }
if (-not $currentDir) {
  New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
  Set-ConfigValue $config "local_bridge_dir" $DataDir
  Write-Step "生成物の保存先: $DataDir"
}
$exe = Find-VideoExe
if ($exe) {
  Set-ConfigValue $config "video_factory_exe_path" $exe
  Write-Step "動画エンジンを見つけました: $exe"
} else {
  Write-Step "動画エンジン（RAGReel）が見つかりません。先に RAGReel-Setup を実行するか、Settings タブの「video_factory_exe_path」に video_factory_cloudrag_poc.exe の場所を入力してください。"
}
New-Item -ItemType Directory -Force -Path (Split-Path $ConfigPath) | Out-Null
[System.IO.File]::WriteAllText($ConfigPath, ($config | ConvertTo-Json -Depth 5), $Utf8NoBom)
Write-Step "設定を書き込みました: $ConfigPath"

Write-Host ""
Write-Host "完了しました。次の手順で使います。"
Write-Host "  1. Houdini を起動（すでに起動しているときは、一度終了して起動し直す）"
Write-Host "  2. ペインのタブの「＋」→ New Pane Tab Type → Misc 付近 → 「RAGReel Tutorial」を選ぶ"
Write-Host "     （見つからないときは、Windows メニュー → Python Panel → RAGReel Tutorial）"
Write-Host "  3. 「Settings」タブで、接続先の URL と API キーが入っていることを確認する"
if (-not $CloudflareUrl -or -not $ApiKey) { Write-Host "     ※ URL または API キーが未入力です。Settings タブで入力してください。" }
