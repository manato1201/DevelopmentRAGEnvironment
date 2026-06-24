"""
Gemini API 疎通確認スクリプト

使い方:
    uv run python scripts/check_gemini_api.py --gemini-key YOUR_KEY
"""
import sys
import argparse
import requests

def check(label: str, url: str, method: str = "GET", payload: dict = None):
    try:
        if method == "GET":
            res = requests.get(url, timeout=15)
        else:
            res = requests.post(url, json=payload, timeout=15)
        status = res.status_code
        icon = "✅" if status == 200 else "❌"
        print(f"{icon} [{status}] {label}")
        if status != 200:
            print(f"   {res.text[:200]}")
    except Exception as e:
        print(f"❌ [ERR] {label}: {e}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gemini-key", required=True)
    args = parser.parse_args()
    key = args.gemini_key

    base = "https://generativelanguage.googleapis.com/v1beta"

    print("=" * 60)
    print("Gemini API 疎通確認")
    print("=" * 60)

    # 1. モデル一覧（基本的な API 疎通）
    check("models.list（基本疎通）",
          f"{base}/models?key={key}")

    # 2. generateContent（通常のテキスト生成）
    check("generateContent（テキスト生成）",
          f"{base}/models/gemini-2.5-flash:generateContent?key={key}",
          method="POST",
          payload={"contents": [{"parts": [{"text": "Hello"}]}]})

    # 3. corpora.list（Semantic Retrieval API）
    check("corpora.list（Semantic Retrieval）",
          f"{base}/corpora?key={key}")

    print()
    print("=" * 60)
    print("判定:")
    print("  ✅✅✅ → APIキーとCorpus APIは正常。別の問題を調査。")
    print("  ✅✅❌ → Corpus APIのみNG。下記のいずれかが原因:")
    print("           ・日本リージョンでは利用不可（可能性高）")
    print("           ・APIキーにCorpus APIの権限なし")
    print("  ❌❌❌ → APIキー自体が無効。Google AI Studioで再発行。")
    print("=" * 60)

if __name__ == "__main__":
    main()
