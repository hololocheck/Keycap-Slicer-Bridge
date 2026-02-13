# Keycap Slicer Bridge

<p align="center">
  <img src="keycapgeneratorIcon.svg" width="80" alt="Keycap Slicer Bridge">
</p>

<p align="center">
  <strong>Keycap Generator ↔ Bambu Studio / OrcaSlicer ダイレクト連携ブリッジ</strong><br>
  <a href="https://github.com/hololocheck/Keycap_Generator">Keycap Generator</a> とスライサーをリアルタイム接続 — フィラメント同期 & 3MF ダイレクト転送
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-2.6.2-blue" alt="version">
  <img src="https://img.shields.io/badge/platform-Windows-0078D4" alt="platform">
  <img src="https://img.shields.io/badge/python-3.7+-3776AB" alt="python">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="license">
</p>

---

**[🇯🇵 日本語](#ja) | [🇬🇧 English](#en)**

---

<a id="ja"></a>

## 🇯🇵 日本語

### 概要

Keycap Slicer Bridge は、[Keycap Generator](https://github.com/hololocheck/Keycap_Generator) と Bambu Studio / OrcaSlicer をリアルタイムに接続するローカルブリッジサーバーです。

ローカル HTTP サーバー（`127.0.0.1:19876`）として動作し、以下の機能を提供します：

- **フィラメント同期** — スライサーのフィラメント色・名前・材料タイプを自動検出し、Keycap Generator の AMS 設定に反映
- **3MF ダイレクト転送** — エクスポートした3Dモデルをワンクリックでスライサーに送信して自動的に開く

### 特徴

| 機能 | 説明 |
| :--- | :--- |
| **フィラメント自動同期** | スライサーの設定ファイルからフィラメント色・名前・材料タイプを自動検出し、AMS スロットに反映 |
| **ワンクリック転送** | エクスポートダイアログから直接スライサーを起動してモデルを開く |
| **OrcaSlicer 対応** | BambuStudio に加え、OrcaSlicer の `orca_presets` 配列構造を解析してプリンター別フィラメント設定を取得 |
| **24色対応** | AMS（16色）+ AMS HT（8色）= 最大24色。16色超過分は自動的にHTスロットに振り分け |
| **4段階フォールバック** | conf JSON → backup path → Temp scan → .3mf scan の優先順で確実に取得 |
| **スライサー自動検出** | Bambu Studio / OrcaSlicer のインストールパスをファイルシステム＋レジストリで自動検出 |
| **セキュリティ** | CORS オリジン制限、ファイルタイプ制限、サイズ制限、ローカル専用（127.0.0.1） |

### 動作の仕組み

```
┌─────────────────────┐                     ┌──────────────────────┐                    ┌────────────────┐
│  Keycap Generator   │  GET /project-      │ Keycap Slicer Bridge │                    │  Bambu Studio  │
│  (ブラウザ)          │  filaments          │  (localhost:19876)   │  conf読み取り       │  / OrcaSlicer  │
│                     │ ←─────────────────── │                      │ ──────────────────→ │  (設定ファイル)  │
│  AMS設定に反映       │  フィラメント情報     │                      │  色・名前・タイプ    │                │
│                     │                     │                      │                    │                │
│  エクスポート実行     │  POST /open (3MF)   │                      │  subprocess        │                │
│                     │ ──────────────────→  │                      │ ──────────────────→ │  モデルを開く    │
└─────────────────────┘                     └──────────────────────┘                    └────────────────┘
```

### インストール

#### 方法 A: リリース版をダウンロード（推奨）

Python のインストールは不要です。

1. [Releases](../../releases) から最新の `.exe` をダウンロード
2. ダブルクリックで起動

> **Note:** Windows Defender 等が初回起動時に警告を出す場合があります。「詳細情報」→「実行」で起動してください。

#### 方法 B: ソースコードから実行

Python 環境がある方向けの方法です。追加パッケージは不要（標準ライブラリのみ）。

```bash
git clone https://github.com/hololocheck/Keycap-Slicer-Bridge.git
cd Keycap-Slicer-Bridge
python keycap_slicer_bridge.py
```

#### ソースからビルドする場合

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name "KeycapSlicerBridge" --icon=icon.ico --clean keycap_slicer_bridge.py
```

ビルド成果物: `dist/KeycapSlicerBridge.exe`

### 使い方

#### 起動確認

起動に成功すると、以下のメッセージが表示されます：

```
=== Keycap Slicer Bridge v2.6.2 ===
Server running at http://127.0.0.1:19876
```

Keycap Generator をブラウザで開くと、ブリッジが自動的に検出されます。
終了するには `Ctrl + C` を押すか、ウィンドウを閉じてください。

#### フィラメント同期

1. Keycap Slicer Bridge が起動中の状態で Keycap Generator を開く
2. AMS 設定ダイアログを開く
3. フッターの**スライサー同期ボタン**をクリック
4. スライサーのフィラメント色・名前がAMSスロットに自動反映

| ボタン状態 | 表示 |
| :--- | :--- |
| ブリッジ未接続 | グレー「スライサー同期」 |
| BambuStudio のみ | 緑色ボタン |
| OrcaSlicer のみ | ティール色ボタン |
| 両方接続 | スプリットボタン（▲で切替） |

#### 3MF ダイレクト転送

1. エクスポートボタンを押すと、ボタンがスプリットボタンに変化
2. ▲ をクリックしてドロップダウンから送信先を選択：
   - **エクスポート** — 通常のファイルダウンロード
   - **Bambu Studio で開く** — Bridge 経由で Bambu Studio に転送
   - **OrcaSlicer で開く** — Bridge 経由で OrcaSlicer に転送
3. メインボタンをクリックで実行

### フィラメント検出の仕組み

#### フォールバック戦略

| 優先度 | 戦略 | 説明 |
| :--- | :--- | :--- |
| **0** | **conf JSON** | 設定ファイルから直接取得（最も高速・確実） |
| **1** | **backup path** | `app.last_backup_path` 内の `Metadata/project_settings.config` |
| **2** | **Temp dir scan** | `%TEMP%\bamboo_model` / `orcaslicer_model` 内の .config ファイル |
| **3** | **.3mf scan** | 最近の .3mf プロジェクトファイルから抽出 |

#### BambuStudio

| キー | 形式 | 例 |
| :--- | :--- | :--- |
| `presets.filament_colors` | カンマ区切り文字列 | `"#DCDCDC,#FFFFFF,#161616"` |
| `presets.filaments` | 文字列配列 | `["ELEGOO PLA Silk @BBL P2S", ...]` |

> **Note:** `BambuStudio.conf` 末尾の `# MD5 checksum` 行は `raw_decode` 方式でハンドリングされます。

#### OrcaSlicer

プリンターごとにフィラメント設定を保持する配列構造です。

```
OrcaSlicer.conf
├── presets.machine         → "Anycubic Kobra S1 0.4 nozzle"  (現在のプリンター)
└── orca_presets[]          → プリンターごとの配列
    ├── [0] machine: "Anker M5 0.4"
    │       filament_colors: "#C0C0C0,#808080"
    ├── [1] machine: "Anycubic Kobra S1 0.4 nozzle"  ← マッチ！
    │       filament_colors: "#26A69A"
    └── [2] machine: "Bambu Lab P2S 0.4"
            filament_colors: "#FF0000,#00FF00,#0000FF,#FFFF00"
```

**プリンターマッチング:**

| 順序 | 方法 |
| :--- | :--- |
| 1 | `presets.machine` と `orca_presets[].machine` の完全一致 |
| 2 | プリンター名のベース部分による部分一致 |
| 3 | 配列の最終エントリ（フォールバック） |

### API リファレンス

#### `GET /health`

```json
{
  "status": "ok",
  "version": "2.6.2",
  "app": "Keycap Slicer Bridge",
  "slicers": {
    "bambu": { "available": true, "path": "C:\\Program Files\\Bambu Studio\\bambu-studio.exe" },
    "orca": { "available": true, "path": "C:\\Program Files\\OrcaSlicer\\orca-slicer.exe" }
  },
  "features": ["project-filaments"]
}
```

#### `GET /project-filaments?slicer=<type>`

スライサーのフィラメント情報を取得します。`slicer` = `bambu` または `orca`

```json
{
  "status": "ok",
  "count": 4,
  "filaments": [
    { "slot": 1, "name": "ELEGOO PLA Silk", "color": "#DCDCDC", "type": "PLA", "vendor": "" },
    { "slot": 2, "name": "ELEGOO PLA",      "color": "#FFFFFF", "type": "PLA", "vendor": "" },
    { "slot": 3, "name": "ELEGOO PLA",      "color": "#161616", "type": "PLA", "vendor": "" },
    { "slot": 4, "name": "Bambu PLA Basic",  "color": "#7C4B00", "type": "PLA", "vendor": "" }
  ],
  "source": "conf:presets.filament_colors"
}
```

#### `GET /debug?slicer=<type>`

設定ファイル構造と検出結果のデバッグ情報を返します。トラブルシューティング用。

#### `POST /open`

モデルファイルをスライサーに送信して開きます。`multipart/form-data` で送信。

| フィールド | 型 | 説明 |
| :--- | :--- | :--- |
| `file` | File | モデルファイル（.stl / .3mf / .obj / .step / .stp） |
| `slicer` | String | `bambu` または `orca` |

```json
{
  "success": true,
  "message": "Bambu Studioでモデルを開きました",
  "slicer": "Bambu Studio",
  "file": "keycap.3mf"
}
```

### セキュリティ

| 項目 | 内容 |
| :--- | :--- |
| **ローカル専用** | `127.0.0.1` のみでリスン（外部アクセス不可） |
| **CORS 制限** | 許可されたオリジンのみリクエスト可能 |
| **ファイルタイプ** | `.stl`, `.3mf`, `.obj`, `.step`, `.stp` のみ |
| **サイズ制限** | 100MB 上限 |
| **許可オリジン** | `keycapgenerator.com`, `localhost`, `127.0.0.1`, `hololocheck.github.io` |

### スライサー検出パス

#### Bambu Studio
```
%ProgramFiles%\Bambu Studio\bambu-studio.exe
%ProgramFiles(x86)%\Bambu Studio\bambu-studio.exe
%LocalAppData%\Programs\Bambu Studio\bambu-studio.exe
+ Windows レジストリ (HKLM / HKCU / HKCR)
+ PATH 環境変数
```

#### OrcaSlicer
```
%ProgramFiles%\OrcaSlicer\orca-slicer.exe
%ProgramFiles(x86)%\OrcaSlicer\orca-slicer.exe
%LocalAppData%\Programs\OrcaSlicer\orca-slicer.exe
+ Windows レジストリ (HKLM / HKCU / HKCR)
+ PATH 環境変数
```

### トラブルシューティング

| 症状 | 対処 |
| :--- | :--- |
| ボタンがグレーのまま | ブリッジが未起動。`.exe` またはスクリプトを起動してください。 |
| スライサーが見つかりません | スライサー未インストール。`/health` で状態を確認。 |
| 色が取得できない | スライサーを起動してプロジェクトを開いてから再試行。 |
| OrcaSlicer で色が違う | 現在のプリンターが `orca_presets` 内に無い可能性。`/debug?slicer=orca` で確認。 |
| ポートが使用中 | 既存のブリッジプロセスを終了してください。 |

### ファイル構成

```
Keycap-Slicer-Bridge/
├── keycap_slicer_bridge.py   # メインアプリケーション
├── generate_icon.py           # アイコン生成スクリプト (SVG → .ico)
├── keycapgeneratorIcon.svg    # アイコン元データ
└── README.md
```

### 動作環境

| 項目 | 方法 A（リリース版） | 方法 B（ソースコード） |
| :--- | :--- | :--- |
| **OS** | Windows 10 / 11 | Windows 10 / 11 |
| **Python** | 不要 | 3.7 以上 |
| **追加パッケージ** | なし | なし（標準ライブラリのみ） |
| **ビルド時のみ** | — | pyinstaller |

### ライセンス

MIT License

---

<a id="en"></a>

## 🇬🇧 English

### Overview

Keycap Slicer Bridge is a local bridge server that connects [Keycap Generator](https://github.com/hololocheck/Keycap_Generator) with Bambu Studio / OrcaSlicer in real time.

It runs as a local HTTP server (`127.0.0.1:19876`) and provides:

- **Filament Sync** — Auto-detect slicer filament colors, names, and material types, then apply to Keycap Generator's AMS settings
- **3MF Direct Transfer** — Send exported 3D models to your slicer with one click, opening them automatically

### Features

| Feature | Description |
| :--- | :--- |
| **Filament Auto-Sync** | Auto-detect filament colors, names, and material types from slicer config files and apply to AMS slots |
| **One-Click Transfer** | Launch the slicer and open the model directly from the export dialog |
| **OrcaSlicer Support** | In addition to BambuStudio, parses OrcaSlicer's `orca_presets` array structure to retrieve per-printer filament settings |
| **24-Color Support** | AMS (16 colors) + AMS HT (8 colors) = up to 24 filaments. Colors beyond 16 auto-distribute to HT slots |
| **4-Stage Fallback** | conf JSON → backup path → Temp scan → .3mf scan ensures reliable retrieval |
| **Slicer Auto-Detection** | Detects Bambu Studio / OrcaSlicer install paths via filesystem + registry |
| **Security** | CORS origin restriction, file type restriction, size limit, localhost only (127.0.0.1) |

### How It Works

```
┌─────────────────────┐                     ┌──────────────────────┐                    ┌────────────────┐
│  Keycap Generator   │  GET /project-      │ Keycap Slicer Bridge │                    │  Bambu Studio  │
│  (Browser)          │  filaments          │  (localhost:19876)   │  Read config       │  / OrcaSlicer  │
│                     │ ←─────────────────── │                      │ ──────────────────→ │  (Config file) │
│  Apply to AMS       │  Filament info      │                      │  Colors/Names/Type │                │
│                     │                     │                      │                    │                │
│  Export             │  POST /open (3MF)   │                      │  subprocess        │                │
│                     │ ──────────────────→  │                      │ ──────────────────→ │  Open model    │
└─────────────────────┘                     └──────────────────────┘                    └────────────────┘
```

### Installation

#### Method A: Download Release (Recommended)

No Python installation required.

1. Download the latest `.exe` from [Releases](../../releases)
2. Double-click to launch

> **Note:** Windows Defender may show a warning on first launch. Click "More info" → "Run anyway" to proceed.

#### Method B: Run from Source

For users with a Python environment. No additional packages needed (standard library only).

```bash
git clone https://github.com/hololocheck/Keycap-Slicer-Bridge.git
cd Keycap-Slicer-Bridge
python keycap_slicer_bridge.py
```

#### Building from Source

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name "KeycapSlicerBridge" --icon=icon.ico --clean keycap_slicer_bridge.py
```

Build output: `dist/KeycapSlicerBridge.exe`

### Usage

#### Verifying Launch

On successful startup:

```
=== Keycap Slicer Bridge v2.6.2 ===
Server running at http://127.0.0.1:19876
```

Keycap Generator automatically detects the bridge when opened in your browser.
To exit, press `Ctrl + C` or close the window.

#### Filament Sync

1. Open Keycap Generator while Keycap Slicer Bridge is running
2. Open the AMS settings dialog
3. Click the **Slicer Sync button** in the footer
4. Slicer filament colors and names are automatically applied to AMS slots

| Button State | Display |
| :--- | :--- |
| Bridge not connected | Gray "Slicer Sync" |
| BambuStudio only | Green button |
| OrcaSlicer only | Teal button |
| Both connected | Split button (▲ to switch) |

#### 3MF Direct Transfer

1. Press the export button — it transforms into a split button
2. Click ▲ to select a destination from the dropdown:
   - **Export** — Standard file download
   - **Open in Bambu Studio** — Transfer via Bridge
   - **Open in OrcaSlicer** — Transfer via Bridge
3. Click the main button to execute

### Filament Detection

#### Fallback Strategy

| Priority | Strategy | Description |
| :--- | :--- | :--- |
| **0** | **conf JSON** | Direct extraction from config file (fastest) |
| **1** | **backup path** | `Metadata/project_settings.config` within `app.last_backup_path` |
| **2** | **Temp dir scan** | `.config` files in `%TEMP%\bamboo_model` / `orcaslicer_model` |
| **3** | **.3mf scan** | Extract from recent .3mf project files |

#### BambuStudio

| Key | Format | Example |
| :--- | :--- | :--- |
| `presets.filament_colors` | Comma-separated string | `"#DCDCDC,#FFFFFF,#161616"` |
| `presets.filaments` | String array | `["ELEGOO PLA Silk @BBL P2S", ...]` |

> **Note:** The `# MD5 checksum` line appended to `BambuStudio.conf` is handled via `raw_decode`.

#### OrcaSlicer

Per-printer array structure for filament settings.

```
OrcaSlicer.conf
├── presets.machine         → "Anycubic Kobra S1 0.4 nozzle"  (current printer)
└── orca_presets[]          → per-printer array
    ├── [0] machine: "Anker M5 0.4"
    │       filament_colors: "#C0C0C0,#808080"
    ├── [1] machine: "Anycubic Kobra S1 0.4 nozzle"  ← Match!
    │       filament_colors: "#26A69A"
    └── [2] machine: "Bambu Lab P2S 0.4"
            filament_colors: "#FF0000,#00FF00,#0000FF,#FFFF00"
```

**Printer Matching:**

| Order | Method |
| :--- | :--- |
| 1 | Exact match: `presets.machine` = `orca_presets[].machine` |
| 2 | Partial match using base printer name |
| 3 | Last entry in array (fallback) |

### API Reference

#### `GET /health`

```json
{
  "status": "ok",
  "version": "2.6.2",
  "app": "Keycap Slicer Bridge",
  "slicers": {
    "bambu": { "available": true, "path": "C:\\Program Files\\Bambu Studio\\bambu-studio.exe" },
    "orca": { "available": true, "path": "C:\\Program Files\\OrcaSlicer\\orca-slicer.exe" }
  },
  "features": ["project-filaments"]
}
```

#### `GET /project-filaments?slicer=<type>`

Retrieve filament info. `slicer` = `bambu` or `orca`

```json
{
  "status": "ok",
  "count": 4,
  "filaments": [
    { "slot": 1, "name": "ELEGOO PLA Silk", "color": "#DCDCDC", "type": "PLA", "vendor": "" },
    { "slot": 2, "name": "ELEGOO PLA",      "color": "#FFFFFF", "type": "PLA", "vendor": "" },
    { "slot": 3, "name": "ELEGOO PLA",      "color": "#161616", "type": "PLA", "vendor": "" },
    { "slot": 4, "name": "Bambu PLA Basic",  "color": "#7C4B00", "type": "PLA", "vendor": "" }
  ],
  "source": "conf:presets.filament_colors"
}
```

#### `GET /debug?slicer=<type>`

Returns debug info about config structure and detection results. For troubleshooting.

#### `POST /open`

Send a model file to the slicer. `multipart/form-data`

| Field | Type | Description |
| :--- | :--- | :--- |
| `file` | File | Model file (.stl / .3mf / .obj / .step / .stp) |
| `slicer` | String | `bambu` or `orca` |

```json
{
  "success": true,
  "message": "Model opened in Bambu Studio",
  "slicer": "Bambu Studio",
  "file": "keycap.3mf"
}
```

### Security

| Item | Details |
| :--- | :--- |
| **Localhost only** | Listens on `127.0.0.1` only (no external access) |
| **CORS restriction** | Only allowed origins can make requests |
| **File types** | `.stl`, `.3mf`, `.obj`, `.step`, `.stp` only |
| **Size limit** | 100MB max |
| **Allowed origins** | `keycapgenerator.com`, `localhost`, `127.0.0.1`, `hololocheck.github.io` |

### Slicer Detection Paths

#### Bambu Studio
```
%ProgramFiles%\Bambu Studio\bambu-studio.exe
%ProgramFiles(x86)%\Bambu Studio\bambu-studio.exe
%LocalAppData%\Programs\Bambu Studio\bambu-studio.exe
+ Windows Registry (HKLM / HKCU / HKCR)
+ PATH environment variable
```

#### OrcaSlicer
```
%ProgramFiles%\OrcaSlicer\orca-slicer.exe
%ProgramFiles(x86)%\OrcaSlicer\orca-slicer.exe
%LocalAppData%\Programs\OrcaSlicer\orca-slicer.exe
+ Windows Registry (HKLM / HKCU / HKCR)
+ PATH environment variable
```

### Troubleshooting

| Symptom | Solution |
| :--- | :--- |
| Button stays gray | Bridge is not running. Launch the `.exe` or script. |
| Slicer not found | Slicer not installed. Check with `/health`. |
| Colors not retrieved | Launch slicer, open a project, then retry sync. |
| Wrong colors (OrcaSlicer) | Current printer may not be in `orca_presets`. Check `/debug?slicer=orca`. |
| Port in use | Terminate the existing bridge process. |

### File Structure

```
Keycap-Slicer-Bridge/
├── keycap_slicer_bridge.py   # Main application
├── generate_icon.py           # Icon generation script (SVG → .ico)
├── keycapgeneratorIcon.svg    # Icon source
└── README.md
```

### System Requirements

| Item | Method A (Release) | Method B (Source) |
| :--- | :--- | :--- |
| **OS** | Windows 10 / 11 | Windows 10 / 11 |
| **Python** | Not required | 3.7+ |
| **Additional packages** | None | None (standard library only) |
| **Build only** | — | pyinstaller |

### License

MIT License
