<#
.SYNOPSIS
  RAGReel チュートリアル生成パネルを、Houdini のパッケージとして導入する（2026-10-21。2026-11-17 に、実証実験の結果を受けて見直し）。

.DESCRIPTION
  1. パネルの Python ファイルを、%LOCALAPPDATA%\RAGReelTutorial\python へコピーする
  2. パネル定義（.pypanel。薄い読み込み用）を、%LOCALAPPDATA%\RAGReelTutorial\houdini\python_panels へ置く
  3. 見つかった Houdini のバージョンごとに、Documents\houdiniXX.X\packages\ragreel_tutorial.json を書く
     （これだけで、Houdini の起動時にパネルが読み込まれる。Python Panel Editor での貼り付けは要らない）
     ・Houdini 本体は入っているのに、Documents\houdiniXX.X がまだ無いときは、そのフォルダを作る（先に Houdini を起動しなくてよい）
     ・OneDrive に移された「ドキュメント」も探す
  4. 設定ファイル（~\.houdini\rag_chatbot_config.json）に、接続先・動画エンジンの場所・保存先を書く（元の設定は退避する）
     ・保存先（local_bridge_dir）が、空・空白だけ・欠けている・別の PC の値（存在しないドライブ）のときは、
       Documents\RAGReelTutorial を設定する。空のファイル・壊れたファイル・BOM つきのファイルでも止まらない
  5. 最後に、導入の結果を自己診断して表示する（書いたファイルの場所・Houdini のバージョンごとの登録・設定の接続先とキーが
     「入っている / 空」・保存先）。API キーなどの値は、表示しない。同じ内容を、導入先の install_report.txt にも書く

  管理者権限は要らない。何度実行しても同じ結果になる（更新にも使える）。
  元に戻すときは  -Uninstall。

.EXAMPLE
  .\install.ps1 -CloudflareUrl https://rag-poc.example.workers.dev
  .\install.ps1 -HoudiniVersion 22.0 -NoPrompt
  .\install.ps1 -Uninstall
#>
[CmdletBinding()]
param(
  # 例: 22.0（22 や 22.0.504 と書いても、22.0 として扱う）。省略すると、見つかった Houdini 21 以降の、すべて
  [string]$HoudiniVersion = "",
  [string]$CloudflareUrl = "",
  [string]$ApiKey = "",
  [string]$VideoExe = "",
  [string]$InstallDir = (Join-Path $env:LOCALAPPDATA "RAGReelTutorial"),
  [string]$DocumentsDir = [Environment]::GetFolderPath("MyDocuments"),
  # Houdini 本体の入っている場所（導入されている版の検出に使う。診断用）
  [string]$HoudiniInstallRoot = (Join-Path $env:ProgramFiles "Side Effects Software"),
  # 生成物（localRAG\tutorials）とログ（logs）の保存先。パネルの「保存先フォルダ（local_bridge_dir）」に設定する
  [string]$DataDir = (Join-Path ([Environment]::GetFolderPath("MyDocuments")) "RAGReelTutorial"),
  [string]$ConfigPath = (Join-Path $HOME ".houdini\rag_chatbot_config.json"),
  [switch]$NoPrompt,
  [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$Utf8Bom = New-Object System.Text.UTF8Encoding($true)
$AppId = "{16D15ECD-5C8C-4677-9B08-E7386D851014}_is1"   # RAGReel（動画エンジン）のインストーラーのID
$MinHoudiniMajor = 21                                    # パネルは PySide6 を使う（Houdini 21 以降）
$DocumentsExplicit = $PSBoundParameters.ContainsKey("DocumentsDir")
$script:Report = New-Object System.Collections.ArrayList
$script:Problems = 0

function Write-Step([string]$Text) { Write-Host "  $Text"; [void]$script:Report.Add("  $Text") }
function Write-Line([string]$Text) { Write-Host $Text; [void]$script:Report.Add($Text) }

# 導入を続けられないとき。PowerShell の例外の表示（長い英語の追跡）を出さず、理由と対処だけを出して止める
function Stop-Install([string]$Message) {
  Write-Host ""
  Write-Host "導入できませんでした" -ForegroundColor Red
  Write-Host $Message
  exit 1
}

# 診断の 1 行。Status は OK / NG / 注意。NG は、導入が使える状態でないことを示す（終了コード 1）
function Write-Check([string]$Status, [string]$Label, [string]$Detail = "") {
  $mark = @{ "OK" = "[OK]  "; "NG" = "[NG]  "; "注意" = "[注意]" }[$Status]
  if ($Status -eq "NG") { $script:Problems++ }
  $line = "  $mark $Label"
  if ($Detail) { $line += " : $Detail" }
  Write-Host $line
  [void]$script:Report.Add($line)
}

function Test-Blank($Value) { return (($null -eq $Value) -or (-not ($Value -is [string])) -or [string]::IsNullOrWhiteSpace($Value)) }

# 22 / 22.0 / houdini22.0 / 22.0.504 を、22.0 にそろえる
function ConvertTo-HoudiniVersion([string]$Text) {
  $v = ($Text.Trim() -replace '^(?i)houdini\s*', '')
  if ($v -match '^\d+$') { return "$v.0" }
  if ($v -match '^(\d+\.\d+)(\.\d+)+$') { return $Matches[1] }
  return $v
}
$TargetVersion = if ($HoudiniVersion) { ConvertTo-HoudiniVersion $HoudiniVersion } else { "" }

# 「ドキュメント」の候補。OneDrive に移されていると、Windows が指す場所と、%USERPROFILE%\Documents がずれることがある。
# -DocumentsDir を明示したときは、その場所だけを見る。
function Get-DocumentRoots {
  if ($DocumentsExplicit) { return @($DocumentsDir) }
  $candidates = @($DocumentsDir, (Join-Path $env:USERPROFILE "Documents"))
  foreach ($name in @("OneDrive", "OneDriveConsumer", "OneDriveCommercial")) {
    $base = [Environment]::GetEnvironmentVariable($name)
    if ($base) { $candidates += (Join-Path $base "Documents") }
  }
  $seen = @{}
  $roots = @()
  foreach ($c in $candidates) {
    if ($c -and (Test-Path -LiteralPath $c)) {
      $key = (Resolve-Path -LiteralPath $c).ProviderPath.ToLowerInvariant()
      if (-not $seen.ContainsKey($key)) { $seen[$key] = $true; $roots += $c }
    }
  }
  return $roots
}

# Documents の下の houdini21.0 / houdini22.0 のようなフォルダ（Houdini を一度でも起動すると作られる）
function Get-HoudiniFolders {
  $all = @()
  foreach ($root in (Get-DocumentRoots)) {
    $all += @(Get-ChildItem -LiteralPath $root -Directory -ErrorAction SilentlyContinue |
      Where-Object { $_.Name -match '^houdini\d+\.\d+$' })
  }
  if ($TargetVersion) { $all = @($all | Where-Object { $_.Name -eq "houdini$TargetVersion" }) }
  return $all
}

function Get-FolderMajor([string]$Name) {
  if ($Name -match '^houdini(\d+)\.') { return [int]$Matches[1] }
  return 0
}

# 導入されている Houdini 本体（C:\Program Files\Side Effects Software\Houdini 22.0.504 など）
function Get-HoudiniInstalls {
  $found = @()
  if ($HoudiniInstallRoot -and (Test-Path -LiteralPath $HoudiniInstallRoot)) {
    foreach ($d in (Get-ChildItem -LiteralPath $HoudiniInstallRoot -Directory -ErrorAction SilentlyContinue)) {
      if ($d.Name -match '^Houdini\s+((\d+\.\d+)(\.\d+)*)') {
        $found += [pscustomobject]@{ Name = $d.Name; Full = $Matches[1]; Minor = $Matches[2] }
      }
    }
  }
  return $found
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

# 設定ファイルを読む。空のファイル・壊れた JSON・{ } でない JSON・BOM つきでも止まらない（理由を返す）
function Read-Config {
  $config = [pscustomobject]@{}
  $note = ""
  if (Test-Path -LiteralPath $ConfigPath) {
    try {
      $raw = [System.IO.File]::ReadAllText($ConfigPath, [System.Text.Encoding]::UTF8)
      if ([string]::IsNullOrWhiteSpace($raw)) {
        $note = "設定ファイルが空でした"
      } else {
        $parsed = $raw | ConvertFrom-Json
        if ($parsed -is [System.Management.Automation.PSCustomObject]) { $config = $parsed }
        else { $note = "設定ファイルの形が違いました（{ ... } の形ではない）" }
      }
    } catch {
      $note = "設定ファイルが壊れていました"
    }
  }
  return [pscustomobject]@{ Config = $config; Note = $note }
}

function Get-ConfigValue($Config, [string]$Name) {
  if ($Config.PSObject.Properties.Name -contains $Name) { return $Config.$Name }
  return $null
}

function Set-ConfigValue($Config, [string]$Name, $Value) {
  if ($Config.PSObject.Properties.Name -contains $Name) { $Config.$Name = $Value }
  else { $Config | Add-Member -NotePropertyName $Name -NotePropertyValue $Value }
}

function Test-Writable([string]$Dir) {
  try {
    New-Item -ItemType Directory -Force -Path $Dir | Out-Null
    $probe = Join-Path $Dir ".write_test"
    [System.IO.File]::WriteAllText($probe, "ok")
    Remove-Item -LiteralPath $probe -Force
    return $true
  } catch { return $false }
}

# ── 削除 ──────────────────────────────────────────────────────────────────
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
  Stop-Install "python\rag_chatbot.py が見つかりません。zip を『すべて展開』したフォルダの中の install.cmd から実行してください（zip の中から直接開くと、他のファイルが無いため、失敗します）。"
}

# ── 0b. 導入先の Houdini を決める ─────────────────────────────────────
$installs = @(Get-HoudiniInstalls)
$houdiniFolders = @(Get-HoudiniFolders)
$created = @()
if ($houdiniFolders.Count -eq 0) {
  # Houdini 本体は入っているのに、Documents\houdiniXX.X がまだ無い（一度も起動していない）。パッケージの置き場所を、先に作る。
  $versions = @()
  if ($TargetVersion) { $versions = @($TargetVersion) }
  else { $versions = @($installs | ForEach-Object { $_.Minor } | Where-Object { (Get-FolderMajor "houdini$_") -ge $MinHoudiniMajor } | Select-Object -Unique) }
  $primaryRoot = @(Get-DocumentRoots)[0]
  if ($versions.Count -gt 0 -and $primaryRoot) {
    foreach ($v in $versions) {
      $dir = Join-Path $primaryRoot "houdini$v"
      New-Item -ItemType Directory -Force -Path $dir | Out-Null
      $created += $dir
    }
    $houdiniFolders = @(Get-HoudiniFolders)
  }
}
$skipped = @($houdiniFolders | Where-Object { (Get-FolderMajor $_.Name) -lt $MinHoudiniMajor })
$houdiniFolders = @($houdiniFolders | Where-Object { (Get-FolderMajor $_.Name) -ge $MinHoudiniMajor })
if ($houdiniFolders.Count -eq 0) {
  $roots = (@(Get-DocumentRoots) -join " , ")
  $existing = @()
  foreach ($root in (Get-DocumentRoots)) { $existing += @(Get-ChildItem -LiteralPath $root -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -match '^houdini' } | ForEach-Object { $_.Name }) }
  $msg = "導入先の Houdini（21.0 以降）が見つかりません。`n"
  $msg += "  探した場所: $roots`n"
  $msg += "  見つかった houdini* フォルダ: " + $(if ($existing.Count) { $existing -join ", " } else { "なし" }) + "`n"
  $msg += "  見つかった Houdini 本体: " + $(if ($installs.Count) { ($installs | ForEach-Object { $_.Name }) -join ", " } else { "なし（$HoudiniInstallRoot）" }) + "`n"
  $msg += "  対処: (1) Houdini を一度起動して終了し、もう一度実行する  (2) 使う版を指定して実行する:  install.cmd -HoudiniVersion 22.0`n"
  $msg += "        (3) それでも見つからないときは、Houdini の Python Shell で  hou.homeHoudiniDirectory()  を実行して、出た場所をお知らせください。"
  Stop-Install $msg
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
foreach ($dir in $created) { Write-Step "Houdini の設定フォルダを作りました（まだ起動していなかったため）: $dir" }
foreach ($h in $houdiniFolders) {
  $pkgDir = Join-Path $h.FullName "packages"
  New-Item -ItemType Directory -Force -Path $pkgDir | Out-Null
  [System.IO.File]::WriteAllText((Join-Path $pkgDir "ragreel_tutorial.json"), $packageJson, $Utf8NoBom)
  Write-Step "パッケージを登録: $($h.Name)（$($h.FullName)）"
}
foreach ($s in $skipped) { Write-Step "対象外（Houdini 21 より前）のため、登録しません: $($s.Name)" }

# ── 3. 設定ファイル ───────────────────────────────────────────────────
if (-not $NoPrompt) {
  if (-not $CloudflareUrl) { $CloudflareUrl = Read-Host "接続先の URL（例: https://xxxx.workers.dev。あとで「接続・アカウント」でも入力できます。空のままで Enter）" }
  if (-not $ApiKey -and $CloudflareUrl) {
    $secure = Read-Host "あなたの API キー（入力は画面に出ません。空のままで Enter）" -AsSecureString
    $ApiKey = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
  }
}
$loaded = Read-Config
$config = $loaded.Config
if ($loaded.Note) { Write-Step "注意: $($loaded.Note)。新しい設定で作り直します（元のファイルは、同じフォルダに .backup_日時 として残します）。" }
# チュートリアル生成は、Claude も検索も、接続先（Cloudflare）経由にする
Set-ConfigValue $config "mode" "cloudflare"
if ($CloudflareUrl) { Set-ConfigValue $config "cf_url" $CloudflareUrl.Trim().TrimEnd("/") }
if ($ApiKey) { Set-ConfigValue $config "cf_api_key" $ApiKey.Trim() }

# 保存先（local_bridge_dir）。空・空白だけ・欠けている・別の PC の値（存在しないドライブ）のときは、DataDir を設定する。
# 使える値が、すでに入っているときは、そのまま使う。
$currentDir = Get-ConfigValue $config "local_bridge_dir"
$replaceDir = $false
$replaceWhy = ""
if (Test-Blank $currentDir) {
  $replaceDir = $true; $replaceWhy = "それまでは未設定"
} else {
  $currentDir = $currentDir.Trim()
  # 使える値: フォルダがある、または、その 1 つ上のフォルダがある（保存のときに、パネルが作る）。
  # 別の PC のパス（C:\Users\<別の人>\Desktop\... など、1 つ上も無い）は、使えない。
  $parentDir = ""
  try { $parentDir = Split-Path -Path $currentDir -Parent -ErrorAction Stop } catch { $parentDir = "" }
  if ((Test-Path -LiteralPath $currentDir) -or ($parentDir -and (Test-Path -LiteralPath $parentDir))) {
    Set-ConfigValue $config "local_bridge_dir" $currentDir     # 前後の空白だけ、落とす
  } else {
    $replaceDir = $true; $replaceWhy = "別の PC の値とみられるため（$currentDir は、この PC では使えません）"
  }
}
if ($replaceDir) {
  if (Test-Writable $DataDir) {
    Set-ConfigValue $config "local_bridge_dir" $DataDir
    Write-Step "生成物の保存先を設定しました（$replaceWhy）: $DataDir"
  } else {
    Write-Step "注意: 保存先 $DataDir を作れません。パネルの「接続・アカウント」の「保存先フォルダ」に、書き込める場所を入力してください。"
  }
}
$exe = Find-VideoExe
if ($exe) {
  Set-ConfigValue $config "video_factory_exe_path" $exe
  Write-Step "動画エンジンを見つけました: $exe"
} else {
  Write-Step "動画エンジン（RAGReel）が見つかりません。先に RAGReel-Setup を実行するか、パネルの「接続・アカウント」→「動画・ギャラリー」の Video Factory exe パスに video_factory_cloudrag_poc.exe の場所を入力してください。"
}
New-Item -ItemType Directory -Force -Path (Split-Path $ConfigPath) | Out-Null
$newJson = $config | ConvertTo-Json -Depth 5
# 元のファイルの控え。内容が変わらないときは作らない（実行のたびに、API キーの入った控えが増えないように）。
# 控えは、新しいものから 3 つだけ残す。
if (Test-Path -LiteralPath $ConfigPath) {
  $oldText = ""
  try { $oldText = [System.IO.File]::ReadAllText($ConfigPath, $Utf8NoBom) } catch { }
  if ($oldText -ne $newJson) {
    $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    Copy-Item -LiteralPath $ConfigPath "$ConfigPath.backup_$stamp" -Force
  }
  $backups = @(Get-ChildItem -LiteralPath (Split-Path $ConfigPath) -Filter ((Split-Path $ConfigPath -Leaf) + ".backup_*") -File -ErrorAction SilentlyContinue | Sort-Object Name -Descending)
  if ($backups.Count -gt 3) { $backups | Select-Object -Skip 3 | Remove-Item -Force -ErrorAction SilentlyContinue }
}
# 一時ファイルに書いてから置き換える（途中で止まっても、空のファイルを残さない）
$tmpConfig = "$ConfigPath.tmp"
[System.IO.File]::WriteAllText($tmpConfig, $newJson, $Utf8NoBom)
Move-Item -LiteralPath $tmpConfig -Destination $ConfigPath -Force
Write-Step "設定を書き込みました: $ConfigPath"

# ── 4. 自己診断 ───────────────────────────────────────────────────────
Write-Line ""
Write-Line "導入の結果（自己診断。キーなどの値は表示しません）"

# 4a. ファイル
$srcFiles = @(Get-ChildItem -Path $srcPython -Filter *.py)
$missing = @($srcFiles | Where-Object {
  $dest = Join-Path $InstallDir "python\$($_.Name)"
  -not ((Test-Path -LiteralPath $dest) -and ((Get-Item -LiteralPath $dest).Length -eq $_.Length))
})
if ($missing.Count -eq 0) { Write-Check "OK" "パネルのファイル" "$($srcFiles.Count) 個（$InstallDir\python）" }
else { Write-Check "NG" "パネルのファイル" ("足りない・合わないもの: " + (($missing | ForEach-Object { $_.Name }) -join ", ")) }
$chatbot = Join-Path $InstallDir "python\rag_chatbot.py"
if (Test-Path -LiteralPath $chatbot) { Write-Check "OK" "rag_chatbot.py（パネル本体）" $chatbot }
else { Write-Check "NG" "rag_chatbot.py（パネル本体）" "$chatbot がありません" }
$pypanel = Join-Path $InstallDir "houdini\python_panels\RAGReelTutorial.pypanel"
if (Test-Path -LiteralPath $pypanel) { Write-Check "OK" "パネル定義（RAGReelTutorial.pypanel）" $pypanel }
else { Write-Check "NG" "パネル定義（RAGReelTutorial.pypanel）" "$pypanel がありません" }

# 4b. Houdini のバージョンごとの登録
foreach ($h in $houdiniFolders) {
  $pkgFile = Join-Path $h.FullName "packages\ragreel_tutorial.json"
  $detail = ""
  $status = "OK"
  try {
    $pkg = Get-Content -Raw -Encoding UTF8 -LiteralPath $pkgFile | ConvertFrom-Json
    $homeValue = ($pkg.env | Where-Object { $_.PSObject.Properties.Name -contains "RAGREEL_TUTORIAL_HOME" } | Select-Object -First 1).RAGREEL_TUTORIAL_HOME
    if (-not $pkg.enable) { $status = "NG"; $detail = "enable が false です" }
    elseif ($homeValue -ne $home_) { $status = "NG"; $detail = "RAGREEL_TUTORIAL_HOME が導入先と違います" }
    elseif (-not (Test-Path -LiteralPath (Join-Path $homeValue "python\rag_chatbot.py"))) { $status = "NG"; $detail = "指す先に rag_chatbot.py がありません" }
    elseif (-not (Test-Path -LiteralPath (Join-Path $homeValue "houdini\python_panels\RAGReelTutorial.pypanel"))) { $status = "NG"; $detail = "指す先にパネル定義がありません" }
    else { $detail = $pkgFile }
  } catch { $status = "NG"; $detail = "$pkgFile を読めません" }
  Write-Check $status "Houdini $($h.Name.Substring(7)) への登録" $detail
}
foreach ($i in $installs) {
  $folder = "houdini$($i.Minor)"
  $registered = @($houdiniFolders | Where-Object { $_.Name -eq $folder }).Count -gt 0
  if ($registered) { Write-Check "OK" "検出した Houdini 本体: $($i.Name)" "設定フォルダ $folder に登録済み（$($i.Full) の版は、すべて同じ $folder を使います）" }
  elseif ((Get-FolderMajor $folder) -lt $MinHoudiniMajor) { Write-Check "注意" "検出した Houdini 本体: $($i.Name)" "21 より前の版のため、対象外です" }
  elseif ($TargetVersion -and $TargetVersion -ne $i.Minor) { Write-Check "注意" "検出した Houdini 本体: $($i.Name)" "-HoudiniVersion $TargetVersion の指定のため、登録していません" }
  else { Write-Check "NG" "検出した Houdini 本体: $($i.Name)" "設定フォルダ $folder に登録されていません" }
}
if ($installs.Count -eq 0) { Write-Check "注意" "Houdini 本体の検出" "$HoudiniInstallRoot に Houdini が見つかりませんでした（別の場所に入れているときは、問題ありません）" }

# 4c. 設定ファイル（値は出さない）
try {
  $bytes = [System.IO.File]::ReadAllBytes($ConfigPath)
  $hasBom = ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF)
  $check = [System.IO.File]::ReadAllText($ConfigPath, $Utf8NoBom) | ConvertFrom-Json
  if ($hasBom) { Write-Check "NG" "設定ファイル" "BOM つきで書かれています（パネルが読めない形）: $ConfigPath" }
  else { Write-Check "OK" "設定ファイル" $ConfigPath }
  $mode = Get-ConfigValue $check "mode"
  Write-Check "OK" "モード" $(if ($mode) { $mode } else { "(空)" })
  if (Test-Blank (Get-ConfigValue $check "cf_url")) { Write-Check "注意" "接続先の URL（cf_url）" "空です。パネルの「接続・アカウント」で入力してください" }
  else { Write-Check "OK" "接続先の URL（cf_url）" "入っています" }
  if (Test-Blank (Get-ConfigValue $check "cf_api_key")) { Write-Check "注意" "API キー（cf_api_key）" "空です。パネルの「接続・アカウント」で入力してください" }
  else { Write-Check "OK" "API キー（cf_api_key）" "入っています" }
  $savedDir = Get-ConfigValue $check "local_bridge_dir"
  if (Test-Blank $savedDir) { Write-Check "注意" "保存先（local_bridge_dir）" "空です。パネルが、ドキュメント内の RAGReelTutorial を自動で使います" }
  elseif (Test-Writable $savedDir) { Write-Check "OK" "保存先（local_bridge_dir）" "$savedDir（書き込めます）" }
  else { Write-Check "NG" "保存先（local_bridge_dir）" "$savedDir に書き込めません。「接続・アカウント」の「保存先フォルダ」を変更してください" }
  $savedExe = Get-ConfigValue $check "video_factory_exe_path"
  if (Test-Blank $savedExe) { Write-Check "注意" "動画エンジン（video_factory_exe_path）" "空です（動画を作らないなら、問題ありません）" }
  elseif (Test-Path -LiteralPath $savedExe) { Write-Check "OK" "動画エンジン（video_factory_exe_path）" "入っています" }
  else { Write-Check "注意" "動画エンジン（video_factory_exe_path）" "入っていますが、その場所にファイルがありません" }
} catch {
  Write-Check "NG" "設定ファイル" "書いたあとに読み直せませんでした: $ConfigPath"
}

# ── 5. 結果 ───────────────────────────────────────────────────────────
Write-Line ""
if ($script:Problems -eq 0) { Write-Line "診断: 問題は見つかりませんでした。" }
else { Write-Line "診断: [NG] が $($script:Problems) 件あります。上の内容と、docs の導入手順の「困ったとき」を確認してください。" }
Write-Line ""
Write-Line "次の手順で使います。"
Write-Line "  1. Houdini を起動（すでに起動しているときは、一度終了して起動し直す）"
Write-Line "  2. 「Windows メニュー → Python Panel → RAGReel Tutorial」、または、ペインのタブの「＋」→ New Pane Tab Type →（Misc の中の）「RAGReel Tutorial」を選ぶ"
Write-Line "  3. 開けない・見つからないときは、Houdini の Python Shell で  import rag_chatbot  を実行して、出た内容を確認する（導入手順の「困ったとき」を参照）"
Write-Line "  4. パネル右上のメニュー（≡）→「接続・アカウント」で、接続先の URL と API キーが入っていることを確認する"
if (-not $CloudflareUrl -or -not $ApiKey) { Write-Line "     ※ この導入では、URL または API キーを入力していません。「接続・アカウント」で入力してください（すでに入っているなら、そのままで構いません）。" }
Write-Line "  この結果は、次のファイルにも書きました: $(Join-Path $InstallDir 'install_report.txt')"

try {
  [System.IO.File]::WriteAllText((Join-Path $InstallDir "install_report.txt"),
    ((Get-Date -Format "yyyy-MM-dd HH:mm:ss") + "`r`n" + ($script:Report -join "`r`n") + "`r`n"), $Utf8Bom)
} catch { }

if ($script:Problems -gt 0) { exit 1 }
