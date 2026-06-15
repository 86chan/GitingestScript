# Gitingester

Gitingest APIを利用してGitHubリポジトリのコードを取得し、指定したサイズごとに分割して保存するツール。

## 機能

- Gitingest API (`https://gitingest.com`) を利用してリポジトリ全体を一つのテキストとして取得
- ファイルセパレータで分割して、各ファイルが一定サイズ（デフォルト1MB）以下になるように複数ファイルに分割して保存
- リポジトリごとに含める・除外するファイルをパターンで指定可能
- 同期版 (`gitingester.py`) と非同期版 (`async_gitingester.py`) の2種類を用意

## インストール

```bash
pip install -r requirements.txt
# gitingester.py (同期版) も使う場合は requests も必要
pip install requests
```

## 設定

`repositories.yaml` に取得したいリポジトリを定義します。

```yaml
repositories:
  - name: "https://github.com/"
    pattern_type: "include"
    pattern: "/docs"
    output_dir: "./docs_output"

  - name: "dotnet/dotnet"
    pattern_type: "exclude"
    pattern: "*.md, *.json"
    output_dir: "./dotnet_output"
```

- `name`: リポジトリ名またはGitHub URL
- `pattern_type`: `include` (指定したパターンのみ) または `exclude` (指定したパターンを除外)
- `pattern`: ファイル/ディレクトリのパターン（カンマ区切り可）
- `output_dir`: 保存先ディレクトリ（未指定の場合は `./out`）

## 使い方

### 同期版（1つずつ順番に実行）

```bash
python gitingester.py
```

### 非同期版（並列実行）

```bash
# 同時並列数 3 で実行
python async_gitingester.py --concurrency 3
```

## 設定例

`repositories.yaml` のサンプル：

```yaml
repositories:
  - name: "https://github.com/"
    pattern_type: "include"
    pattern: "/docs"
    output_dir: "./docs_output"

  - name: "dotnet/dotnet"
    pattern_type: "exclude"
    pattern: "*.md, *.json"
    output_dir: "./efcore_output/relational"
```

また、`repositories_dotnet.yaml` にはより詳細な設定例が用意されています。

## 出力例

出力されたファイルは `./out` （または設定した `output_dir`）に保存されます。

`tart/cirruslabs_tart__part_1.txt` にはサンプル出力が含まれています。

## 出力形式

分割されたファイルは以下の形式で保存されます：

- `リポジトリ名_part_1.txt`
- `リポジトリ名_part_2.txt`
...

各ファイルの末尾には、続きのファイル名が記載されます：
`>>> NOTE: This file has been split. Continued in: リポジトリ名_part_N.txt`

## 依存関係

### async_gitingester.py (非同期版)
- `aiohttp`
- `aiofiles`
- `PyYAML`

### gitingester.py (同期版)
- `requests`
- `PyYAML`

## 開発者向け
`repositories_schema.json` には `repositories.yaml` のスキーマ定義が含まれています。
