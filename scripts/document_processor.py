"""
document_processor.py — ドキュメント処理モジュール

マークダウン、テキスト、パワーポイント、PDF などのファイルの読み込みと解析、
チャンク分割を行う。mcp-rag-server から独立させた版。
"""

import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List

import markitdown


class DocumentProcessor:
    """
    ドキュメント処理クラス

    Attributes:
        logger: ロガー
    """

    SUPPORTED_EXTENSIONS = {
        "text": [".txt", ".md", ".markdown"],
        "office": [".ppt", ".pptx", ".doc", ".docx"],
        "pdf": [".pdf"],
    }

    def __init__(self):
        self.logger = logging.getLogger("document_processor")
        self.logger.setLevel(logging.INFO)

    def read_file(self, file_path: str) -> str:
        try:
            ext = Path(file_path).suffix.lower()

            if ext in self.SUPPORTED_EXTENSIONS["text"]:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                    content = content.replace("\x00", "")
                self.logger.info(f"テキストファイル '{file_path}' を読み込みました")
                return content

            elif ext in self.SUPPORTED_EXTENSIONS["office"] or ext in self.SUPPORTED_EXTENSIONS["pdf"]:
                return self.convert_to_markdown(file_path)

            else:
                self.logger.warning(f"サポートしていないファイル形式です: {file_path}")
                return ""

        except FileNotFoundError:
            self.logger.error(f"ファイル '{file_path}' が見つかりません")
            raise
        except IOError as e:
            self.logger.error(f"ファイル '{file_path}' の読み込みに失敗しました: {str(e)}")
            raise

    def convert_to_markdown(self, file_path: str) -> str:
        try:
            file_uri = f"file://{os.path.abspath(file_path)}"
            markdown_content = markitdown.MarkItDown().convert_uri(file_uri).markdown
            markdown_content = markdown_content.replace("\x00", "")
            self.logger.info(f"ファイル '{file_path}' をマークダウンに変換しました")
            return markdown_content
        except Exception as e:
            self.logger.error(f"ファイル '{file_path}' のマークダウン変換に失敗しました: {str(e)}")
            raise

    def split_into_chunks(self, text: str, chunk_size: int = 500, overlap: int = 100) -> List[str]:
        if not text:
            return []

        chunks = []
        start = 0
        text_length = len(text)

        while start < text_length:
            end = min(start + chunk_size, text_length)

            if end < text_length:
                next_newline = text.find("\n", end)
                next_period = text.find("。", end)

                if next_newline != -1 and (next_period == -1 or next_newline < next_period):
                    end = next_newline + 1
                elif next_period != -1:
                    end = next_period + 1

            chunks.append(text[start:end])
            start = end - overlap if end - overlap > start else end

            if start >= text_length:
                break

        self.logger.info(f"テキストを {len(chunks)} チャンクに分割しました")
        return chunks

    def calculate_file_hash(self, file_path: str) -> str:
        try:
            with open(file_path, "rb") as f:
                return hashlib.sha256(f.read()).hexdigest()
        except Exception as e:
            self.logger.error(f"ファイル '{file_path}' のハッシュ計算に失敗しました: {str(e)}")
            return f"timestamp-{int(time.time())}"

    def get_file_metadata(self, file_path: str) -> Dict[str, Any]:
        file_stat = os.stat(file_path)
        return {
            "hash": self.calculate_file_hash(file_path),
            "mtime": file_stat.st_mtime,
            "size": file_stat.st_size,
            "path": file_path,
        }

    def load_file_registry(self, processed_dir: str) -> Dict[str, Dict[str, Any]]:
        registry_path = Path(processed_dir) / "file_registry.json"
        if not registry_path.exists():
            return {}
        try:
            with open(registry_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            self.logger.error(f"ファイルレジストリの読み込みに失敗しました: {str(e)}")
            return {}

    def save_file_registry(self, processed_dir: str, registry: Dict[str, Dict[str, Any]]) -> None:
        registry_path = Path(processed_dir) / "file_registry.json"
        try:
            os.makedirs(Path(processed_dir), exist_ok=True)
            with open(registry_path, "w", encoding="utf-8") as f:
                json.dump(registry, f, ensure_ascii=False, indent=2)
            self.logger.info(f"ファイルレジストリを保存しました: {registry_path}")
        except Exception as e:
            self.logger.error(f"ファイルレジストリの保存に失敗しました: {str(e)}")

    def process_file(
        self, file_path: str, processed_dir: str, chunk_size: int = 500, overlap: int = 100
    ) -> List[Dict[str, Any]]:
        try:
            content = self.read_file(file_path)
            if not content:
                return []

            file_path_obj = Path(file_path)
            relative_path = file_path_obj.relative_to(Path(file_path_obj.parts[0]) / Path(file_path_obj.parts[1]))
            parent_dirs = relative_path.parent.parts

            dir_suffix = "_".join(parent_dirs) if parent_dirs else ""

            processed_file_name = f"{file_path_obj.stem}{('_' + dir_suffix) if dir_suffix else ''}.md"
            processed_file_path = Path(processed_dir) / processed_file_name

            os.makedirs(Path(processed_dir), exist_ok=True)

            with open(processed_file_path, "w", encoding="utf-8") as f:
                f.write(content)

            self.logger.info(f"処理済みファイルを保存しました: {processed_file_path}")

            chunks = self.split_into_chunks(content, chunk_size, overlap)

            results = []
            for i, chunk in enumerate(chunks):
                document_id = f"{processed_file_name}_{i}"
                results.append(
                    {
                        "document_id": document_id,
                        "content": chunk,
                        "file_path": str(processed_file_path),
                        "original_file_path": file_path,
                        "chunk_index": i,
                        "metadata": {
                            "file_name": file_path_obj.name,
                            "directory": str(file_path_obj.parent),
                            "directory_suffix": dir_suffix,
                        },
                    }
                )

            self.logger.info(f"ファイル '{file_path}' を処理しました（{len(results)} チャンク）")
            return results

        except Exception as e:
            self.logger.error(f"ファイル '{file_path}' の処理中にエラーが発生しました: {str(e)}")
            raise

    def process_directory(
        self, source_dir: str, processed_dir: str, chunk_size: int = 500, overlap: int = 100, incremental: bool = False
    ) -> List[Dict[str, Any]]:
        results = []
        source_directory = Path(source_dir)

        if not source_directory.exists() or not source_directory.is_dir():
            self.logger.error(f"ディレクトリ '{source_dir}' が見つからないか、ディレクトリではありません")
            raise FileNotFoundError(f"ディレクトリ '{source_dir}' が見つからないか、ディレクトリではありません")

        all_extensions = []
        for ext_list in self.SUPPORTED_EXTENSIONS.values():
            all_extensions.extend(ext_list)

        files = []
        for ext in all_extensions:
            files.extend(list(source_directory.glob(f"**/*{ext}")))

        self.logger.info(f"ディレクトリ '{source_dir}' 内に {len(files)} 個のファイルが見つかりました")

        if incremental:
            file_registry = self.load_file_registry(processed_dir)
            self.logger.info(f"ファイルレジストリから {len(file_registry)} 個のファイル情報を読み込みました")
        else:
            file_registry = {}

        files_to_process = []
        for file_path in files:
            str_path = str(file_path)
            if incremental:
                current_metadata = self.get_file_metadata(str_path)
                if (
                    str_path not in file_registry
                    or file_registry[str_path]["hash"] != current_metadata["hash"]
                    or file_registry[str_path]["mtime"] != current_metadata["mtime"]
                    or file_registry[str_path]["size"] != current_metadata["size"]
                ):
                    files_to_process.append(file_path)
                    file_registry[str_path] = current_metadata
            else:
                files_to_process.append(file_path)
                file_registry[str_path] = self.get_file_metadata(str_path)

        self.logger.info(f"処理対象のファイル数: {len(files_to_process)} / {len(files)}")

        for file_path in files_to_process:
            try:
                file_results = self.process_file(str(file_path), processed_dir, chunk_size, overlap)
                results.extend(file_results)
            except Exception as e:
                self.logger.error(f"ファイル '{file_path}' の処理中にエラーが発生しました: {str(e)}")
                continue

        self.save_file_registry(processed_dir, file_registry)

        self.logger.info(f"ディレクトリ '{source_dir}' 内のファイルを処理しました（合計 {len(results)} チャンク）")
        return results
