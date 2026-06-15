"""
.txt以外のファイルを削除するスクリプト（Houdini helpデータ整理用）
使用方法: python3 delete_non_txt.py
実行場所: ~/mcp-rag-server/
"""
import os


def delete_non_txt_files(directory: str) -> None:
    """指定ディレクトリ以下の.txt以外のファイルをすべて削除する"""
    deleted = 0
    errors = 0

    for root, _, files in os.walk(directory):
        for file in files:
            if not file.endswith(".txt"):
                try:
                    os.remove(os.path.join(root, file))
                    print(f"  削除: {file}")
                    deleted += 1
                except Exception as e:
                    print(f"  エラー: {file} - {e}")
                    errors += 1

    print(f"\n完了: {deleted}件削除 / {errors}件エラー")


if __name__ == "__main__":
    target = "data/source"
    if not os.path.exists(target):
        print(f"ディレクトリが存在しません: {target}")
    else:
        print(".txt以外のファイルを削除します...")
        confirm = input("続行しますか？ (y/N): ")
        if confirm.lower() == "y":
            delete_non_txt_files(target)
        else:
            print("キャンセルしました")
