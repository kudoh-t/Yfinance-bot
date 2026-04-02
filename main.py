import os
import requests
import pandas as pd
import io

# ==========================================
# 1. 設定情報（ここを書き換えてください）
# ==========================================

# 先ほどコピーしたGoogleスプレッドシートの長いURLを貼り付けてください
CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vTnmbJ3DubdIL0DmokPDIn0u9uDUZBUL7UVPOQ48Mu8qFRLaUBqekdg6BTZbzmFcURPXKY3qlpDsev4/pub?output=csv"

# LINEのトークンとユーザーID
LINE_TOKEN = os.getenv("LINE_TOKEN")
LINE_USER_ID = os.getenv("LINE_USER_ID")

# ==========================================
# 2. LINE通知用の関数
# ==========================================
def notify_line(message):
    url = "https://api.line.me/v2/bot/message/push"
    headers_line = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_TOKEN}",
    }
    data = {
        "to": LINE_USER_ID,
        "messages": [{"type": "text", "text": message}]
    }
    try:
        response = requests.post(url, headers=headers_line, json=data)
        response.raise_for_status()
    except Exception as e:
        print(f"LINE通知に失敗しました: {e}")

# ==========================================
# 3. メイン処理
# ==========================================
def main():
    try:
        # スプレッドシート（CSV形式）を取得
        response = requests.get(CSV_URL)
        response.encoding = 'utf-8'
        
        # データを読み込む
        # アップロードされたシートの列名（銘柄, 現在値, 合体スコア, シグナル）を使用します
        df = pd.read_csv(io.StringIO(response.text))

        # 「シグナル」列に "Buy" という文字が含まれる銘柄を抽出
        buy_df = df[df['シグナル'].str.contains('Buy', na=False)]

        if buy_df.empty:
            notify_line("本日の分析：買い推奨(Buy)銘柄はありませんでした。")
            return

        # 「合体スコア」が高い順に最大7件選ぶ
        top7 = buy_df.sort_values("合体スコア", ascending=False).head(7)

        # 送信メッセージの作成
        msg = "【今日の買い推奨 Top7】\n"
        for _, r in top7.iterrows():
            # 銘柄名、現在値、スコアを1行ずつ追加
            msg += f"■{r['銘柄']}\n   価格:{r['現在値']} / スコア:{r['合体スコア']:.1f}\n"

        # LINEへ送信
        notify_line(msg)
        print("LINE通知が完了しました。")

    except Exception as e:
        error_msg = f"実行中にエラーが発生しました: {e}"
        print(error_msg)
        # エラーが起きたこともLINEで知らせる
        # notify_line(error_msg)

if __name__ == "__main__":
    main()