"""
Gitingest APIを利用してリポジトリのコードを取得し、
指定サイズごとに分割して保存するスクリプト
"""

import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
import time
from typing import Literal

import requests
import yaml

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# 正規表現のコンパイル（定数化によるパフォーマンス最適化）
SEPARATOR_PATTERN = re.compile(r"(^={16,}\nFILE: .+\n={16,}\n)", re.MULTILINE)


@dataclass(frozen=True)
class GitingestConfig:
    """
    APIおよびファイル出力のデフォルト設定状態
    """

    origin: str = "https://gitingest.com"
    api_url: str = "https://gitingest.com/api/ingest"
    max_file_size_bytes: int = 1024 * 1024
    output_dir: Path = Path("./out")
    yaml_config_path: Path = Path("repositories.yaml")


@dataclass(frozen=True)
class RepositoryTarget:
    """
    取得対象リポジトリとそのフィルタリング条件および出力先設定
    """

    name: str
    output_dir: Path
    pattern_type: Literal["exclude", "include"] = "exclude"
    pattern: str = ""

    def __post_init__(self) -> None:
        """
        初期化後のデータ正規化（URLプレフィックスの除去）
        """
        clean_name = self.name
        # httpおよびhttpsのプレフィックスに対応
        for prefix in ("https://github.com/", "http://github.com/"):
            if clean_name.startswith(prefix):
                clean_name = clean_name.removeprefix(prefix)
                break

        if clean_name != self.name:
            # frozen=Trueの制約を回避して正規化後の値をセット
            object.__setattr__(self, "name", clean_name)


class GitingestClient:
    """
    Gitingest APIとの通信クライアント
    """

    def __init__(self, config: GitingestConfig) -> None:
        self._config = config

    def fetch_repository_content(self, target: RepositoryTarget) -> str:
        """
        指定リポジトリのテキストコンテンツの取得

        Args:
            target: 取得対象リポジトリの設定

        Returns:
            取得されたプレーンテキスト（str型）

        Raises:
            requests.RequestException: API通信失敗時
            ValueError: APIレスポンス不正時
        """
        com_headers = {
            "sec-ch-ua": '"Chromium";v="148", "Microsoft Edge";v="148", "Not/A)Brand";v="99"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36 Edg/148.0.0.0",
        }

        origin_headers = {
            "sec-fetch-dest": "document",
            "sec-fetch-mode": "navigate",
            "sec-fetch-site": "none",
            "sec-fetch-user": "?1",
            "upgrade-insecure-requests": "1",
        }

        post_headers = {
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "origin": "https://gitingest.com",
            "referer": "https://gitingest.com/",
        }

        get_headers = {
            "sec-fetch-dest": "document",
            "sec-fetch-mode": "navigate",
            "sec-fetch-site": "cross-site",
            "sec-fetch-user": "?1",
            "upgrade-insecure-requests": "1",
            "referer": "https://gitingest.com/",
        }

        payload = {
            "input_text": target.name,
            "token": "",
            "max_file_size": 100000,
            "pattern_type": target.pattern_type,
            "pattern": target.pattern,
        }

        session = requests.Session()
        session.headers.update(com_headers)

        # トップページにアクセスしてCookieを取得
        logger.info("Getting TopPage...")
        session.get(self._config.origin, headers=origin_headers, timeout=30)

        # I/Oブロッキングのタイムアウト明示
        time.sleep(1)
        logger.info("Post... repository: %s", target.name)
        response = session.post(self._config.api_url, json=payload, headers=post_headers, timeout=300)
        response.raise_for_status()

        data = response.json()
        digest_url = data.get("digest_url")
        if not digest_url:
            raise ValueError("APIレスポンス内 'digest_url' の欠落")

        time.sleep(1)
        logger.info("DL... url: %s", digest_url)
        digest_response = session.get(digest_url, headers=get_headers, timeout=30)
        digest_response.raise_for_status()

        return digest_response.text


def load_targets(config: GitingestConfig) -> list[RepositoryTarget]:
    """
    YAML設定ファイルからのリポジトリ情報の読み込みおよび型付け

    Args:
        config: アプリケーション設定オブジェクト

    Returns:
        解析済みのRepositoryTargetインスタンスのリスト

    Raises:
        FileNotFoundError: 設定ファイルが存在しない場合
        yaml.YAMLError: YAMLの解析に失敗した場合
    """
    config_path = config.yaml_config_path
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not data or "repositories" not in data:
        logger.warning("No 'repositories' key found in %s", config_path)
        return []

    targets = []
    for item in data["repositories"]:
        # 個別の出力先指定がない場合は全体のデフォルト値を使用
        raw_output_dir = item.get("output_dir")
        target_output_dir = (
            Path(raw_output_dir) if raw_output_dir else config.output_dir
        )

        targets.append(
            RepositoryTarget(
                name=item.get("name", ""),
                output_dir=target_output_dir,
                pattern_type=item.get("pattern_type", "exclude"),
                pattern=item.get("pattern", ""),
            )
        )
    return targets


def generate_sections(content: str) -> Iterator[str]:
    """
    コンテンツのファイルセパレータ単位での分割および順次生成

    Args:
        content: 分割対象のプレーンテキスト

    Yields:
        セパレータとファイル内容を結合したテキストチャンク
    """
    
    # UTF-8 BOMコード
    UTF8BOM_CODE = b'\xef\xbb\xbf'
    UTF8BOM_UNICODE = '\ufeff'

    # 削除(gitingestがバイナリで結合している？)
    clean_content = content.replace(UTF8BOM_UNICODE, '')

    parts = SEPARATOR_PATTERN.split(clean_content)

    # プリアンブル（最初のファイル宣言より前のテキスト）の処理
    if parts[0]:
        yield parts[0]

    # セパレータと本体が交互に現れるため、ペアにして抽出
    for i in range(1, len(parts) - 1, 2):
        yield parts[i] + parts[i + 1]


def save_split_contents(
    repository_name: str,
    sections: Iterator[str],
    output_dir: Path,
    max_file_size_bytes: int,
) -> None:
    """
    サイズ制限に基づくセクション結合とファイルへの分割保存

    Args:
        repository_name: ファイル名生成元となるリポジトリ名
        sections: ファイルセクションのジェネレータ
        output_dir: 保存先ディレクトリパス
        max_file_size_bytes: 単一ファイルの最大許容バイト数
    """
    # ディレクトリの自動作成（存在しない場合は親ディレクトリ含め生成）
    output_dir.mkdir(parents=True, exist_ok=True)

    base_filename = repository_name.replace("/", "_")
    file_idx = 1
    current_content = ""

    # 状態の変更（副作用）をこの関数内に局所化
    for section in sections:
        section_bytes_len = len(section.encode("utf-8"))
        next_filename = f"{base_filename}_part_{file_idx + 1}.txt"
        footer = (
            f"\n\n>>> NOTE: This file has been split. Continued in: {next_filename}\n"
        )

        current_len = len(current_content.encode("utf-8"))
        footer_len = len(footer.encode("utf-8"))

        # 最大サイズ超過判定
        if (
            current_len > 0
            and (current_len + section_bytes_len + footer_len) > max_file_size_bytes
        ):
            filename = output_dir / f"{base_filename}_part_{file_idx}.txt"
            filename.write_text(current_content + footer, encoding="utf-8")
            logger.info("Created: %s", filename)

            current_content = section
            file_idx += 1
        else:
            current_content += section

    # 残余コンテンツの書き出し
    if current_content:
        filename = output_dir / f"{base_filename}_part_{file_idx}.txt"
        filename.write_text(current_content, encoding="utf-8")
        logger.info("Created: %s", filename)


def process_repository(
    target: RepositoryTarget, client: GitingestClient, config: GitingestConfig
) -> None:
    """
    単一リポジトリの取得から保存までのパイプライン処理

    Args:
        target: 対象リポジトリの設定
        client: APIクライアント
        config: アプリケーション設定
    """
    logger.info(
        "Processing repository: %s -> Output: %s", target.name, target.output_dir
    )
    try:
        # パイプライン（データフロー）の表現
        content = client.fetch_repository_content(target)
        sections = generate_sections(content)
        save_split_contents(
            repository_name=target.name,
            sections=sections,
            output_dir=target.output_dir,
            max_file_size_bytes=config.max_file_size_bytes,
        )
    except Exception as e:
        logger.error("Error processing %s: %s", target.name, e)


def main() -> None:
    """
    エントリーポイント
    """
    config = GitingestConfig()

    try:
        targets = load_targets(config)
    except Exception as e:
        logger.error("Failed to load targets: %s", e)
        return

    client = GitingestClient(config)

    for target in targets:
        process_repository(target, client, config)


if __name__ == "__main__":
    main()
