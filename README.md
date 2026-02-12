# Keycap Slicer Bridge

<p align="center">
  <img src="keycapgeneratorIcon.svg" width="80" alt="Keycap Slicer Bridge">
</p>

<p align="center">
  <strong>Keycap Generator → Bambu Studio / OrcaSlicer ダイレクト転送ブリッジ</strong><br>
  <a href="https://keycapgenerator.com">Keycap Generator</a> でエクスポートした3Dモデルをワンクリックでスライサーに送信
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-2.1.0-blue" alt="version">
  <img src="https://img.shields.io/badge/platform-Windows-0078D4" alt="platform">
  <img src="https://img.shields.io/badge/python-3.9+-3776AB" alt="python">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="license">
</p>

---

## 概要

Keycap Slicer Bridge は、[Keycap Generator](https://keycapgenerator.com) のエクスポートダイアログから Bambu Studio / OrcaSlicer にモデルファイルを直接転送するための軽量ブリッジアプリケーションです。

タスクトレイに常駐し、ローカル HTTP サーバー（`127.0.0.1:19876`）として動作します。

## 特徴

- **ワンクリック転送** — エクスポートダイアログから直接スライサーを起動してモデルを開く
- **スライサー自動検出** — Bambu Studio / OrcaSlicer のインストールパスを自動検出（ファイルシステム + レジストリ）
- **タスクトレイ常駐** — バックグラウンドで動作、リソース消費ほぼゼロ
- **インストーラー付き** — 初回起動時にセットアップ画面を表示
- **自動起動** — Windows 起動時に自動で常駐開始（オプション）
- **セキュリティ** — CORS オリジン制限、ファイルタイプ制限、サイズ制限

## 動作の仕組み

```
┌─────────────────────┐     HTTP POST      ┌──────────────────────┐     subprocess     ┌────────────────┐
│  Keycap Generator   │ ──────────────────→ │ Keycap Slicer Bridge │ ─────────────────→ │  Bambu Studio  │
│  (ブラウザ)          │   /open (3MF等)     │  (localhost:19876)   │   .exe + file      │  / OrcaSlicer  │
└─────────────────────┘                     └──────────────────────┘                    └────────────────┘
```

## インストール

### ビルド済み exe を使う場合

1. [Releases](../../releases) から `KeycapSlicerBridge.exe` をダウンロード
2. ダブルクリックで起動 → インストーラー画面が表示される
3. 「インストール」をクリック → セットアップ完了

### ソースからビルドする場合

```bash
# 依存パッケージ
pip install pystray Pillow pyinstaller

# アイコン生成
python generate_icon.py

# exe ビルド
pyinstaller --onefile --windowed --name "KeycapSlicerBridge" --icon=icon.ico --clean keycap_slicer_bridge.py
```

ビルド成果物: `dist/KeycapSlicerBridge.exe`

## 使い方

### Keycap Generator での操作

1. Keycap Slicer Bridge が起動中の状態で [Keycap Generator](https://keycapgenerator.com) を開く
2. エクスポートボタンを押すと、ダイアログのエクスポートボタンがスプリットボタンに変化
3. ▲ をクリックしてドロップダウンから送信先を選択
   - **エクスポート** — 通常のファイルダウンロード
   - **Bambu Studio で開く** — Bridge 経由で Bambu Studio に転送
   - **OrcaSlicer で開く** — Bridge 経由で OrcaSlicer に転送
4. 選択後、メインボタンをクリックで実行

### タスクトレイメニュー

タスクトレイのアイコンを右クリック:

| メニュー | 説明 |
|:--|:--|
| **ヘルスチェック** | ブラウザで接続状態を確認 |
| **Windows起動時に自動起動** | チェックでオン/オフ切替 |
| **アンインストール** | 設定・ショートカット・フォルダを完全削除 |
| **終了** | アプリを終了 |

## API リファレンス

### `GET /health`

Bridge の接続状態とスライサーの検出状態を返します。

**レスポンス:**
```json
{
  "status": "ok",
  "version": "2.1.0",
  "app": "Keycap Slicer Bridge",
  "slicers": {
    "bambu": { "available": true, "path": "C:\\Program Files\\Bambu Studio\\bambu-studio.exe" },
    "orca": { "available": false, "path": "" }
  }
}
```

### `POST /open`

モデルファイルをスライサーに送信して開きます。

**リクエスト:** `multipart/form-data`

| フィールド | 型 | 説明 |
|:--|:--|:--|
| `file` | File | モデルファイル（.stl / .3mf / .obj / .step / .stp） |
| `slicer` | String | `bambu` または `orca` |

**レスポンス（成功）:**
```json
{
  "success": true,
  "message": "Bambu Studioでモデルを開きました",
  "slicer": "Bambu Studio",
  "file": "keycap.3mf"
}
```

**制限事項:**
- ファイルサイズ: 最大 100MB
- 許可される拡張子: `.stl`, `.3mf`, `.obj`, `.step`, `.stp`
- 許可されるオリジン: `keycapgenerator.com`, `localhost`, `127.0.0.1`, `sireai.github.io`

## セキュリティ

- **ローカル専用** — `127.0.0.1` のみでリスン（外部からアクセス不可）
- **CORS 制限** — 許可されたオリジンのみリクエスト可能
- **ファイルタイプ制限** — 3D モデルファイルのみ受付
- **サイズ制限** — 100MB 上限

## スライサー検出パス

### Bambu Studio
```
%ProgramFiles%\Bambu Studio\bambu-studio.exe
%ProgramFiles(x86)%\Bambu Studio\bambu-studio.exe
%LocalAppData%\Programs\Bambu Studio\bambu-studio.exe
+ Windows レジストリ (HKLM / HKCU / HKCR)
+ PATH 環境変数
```

### OrcaSlicer
```
%ProgramFiles%\OrcaSlicer\orca-slicer.exe
%ProgramFiles(x86)%\OrcaSlicer\orca-slicer.exe
%LocalAppData%\Programs\OrcaSlicer\orca-slicer.exe
+ Windows レジストリ (HKLM / HKCU / HKCR)
+ PATH 環境変数
```

## ファイル構成

```
keycap-slicer-bridge/
├── keycap_slicer_bridge.py   # メインアプリケーション
├── generate_icon.py           # アイコン生成スクリプト (SVG → .ico)
├── keycapgeneratorIcon.svg    # アイコン元データ
└── README.md
```

## 動作環境

- **OS:** Windows 10 / 11
- **Python:** 3.9+（ソースから実行する場合）
- **依存:** pystray, Pillow（exe は依存なし）

## ライセンス

MIT License
