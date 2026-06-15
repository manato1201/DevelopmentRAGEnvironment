"""
Houdini help zipファイルを展開するスクリプト
使用方法: python3 extract_zip.py
実行場所: ~/mcp-rag-server/
"""
import os
import zipfile


def extract_zip_files(directory: str) -> None:
    """指定ディレクトリ内のzipファイルをすべて展開する"""
    zip_files = [f for f in os.listdir(directory) if f.endswith(".zip")]

    if not zip_files:
        print("zipファイルが見つかりません")
        return

    print(f"{len(zip_files)}個のzipファイルを展開します...")

    for filename in zip_files:
        file_path = os.path.join(directory, filename)
        output_path = os.path.join(directory, filename[:-4])
        os.makedirs(output_path, exist_ok=True)
        try:
            with zipfile.ZipFile(file_path, "r") as zf:
                zf.extractall(output_path)
            os.remove(file_path)
            print(f"  ✓ 展開完了: {filename}")
        except Exception as e:
            print(f"  ✗ エラー: {filename} - {e}")

    print("展開完了")


if __name__ == "__main__":
    target = "data/source"
    if not os.path.exists(target):
        print(f"ディレクトリが存在しません: {target}")
        print("mkdir -p data/source を実行してからやり直してください")
    else:
        extract_zip_files(target)
