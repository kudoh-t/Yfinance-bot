import os
import requests
import pandas as pd
import io
from datetime import datetime

# ==========================================
# 1. 設定：銘柄名とコードの対応マスタ（確定版）
# ==========================================
STOCK_MASTER = {
    "三菱重工": "7011",
    "ビジネスエンジ": "4828",
    "三井住友ＦＧ": "8316",
    "三菱ＵＦＪ": "8306",
    "三菱商事": "8058",
    "ＩＮＰＥＸ": "1605",
    "三井海洋": "6269",
    "三菱ＨＣ": "8593",
    "ＮＴＴ": "9432",
    "ＫＤＤＩ": "9433",
    "伊藤忠": "8001",
    "千葉銀行": "8331",
    "信越化学": "4063",
    "村田製作所": "6981",
    "オリックス": "8591",
    "日揮": "1963",
    "ヒューリック": "3003",
    "住友電工": "5802",
    "三菱ガス化学": "4182",
    "クオリプス": "4894",
    "トリケミカル": "4369",
    "パワーエックス": "485A"
}

# 環境変数（GitHub Actions から渡される）
CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vTnmbJ3DubdIL0DmokPDIn0u9uDUZBUL7UVPOQ48Mu8qFRLaUBqekdg6BTZbzmFcURPXKY3qlpDsev4/pub?output=csv"

LINE_TOKEN = os.getenv("LINE_TOKEN")
LINE_USER_ID = os.getenv("LINE_USER_ID")

print("=== Debug: Environment Variables ===")
print("LINE_TOKEN exists:", LINE_TOKEN is not None)
print("LINE_USER_ID:", LINE_USER_ID)
print("====================================")


def get_latest_price(ticker_code):
    """Yahoo FinanceのWEB APIから最新株価を取得"""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker_code}.T?range=2mo&interval=1d"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        data = response.json()
        closes = data['chart']['result'][0]['indicators']['quote'][0]['close']
        df = pd.DataFrame(closes, columns=['Close']).dropna()
        return df
    except Exception as e:
        print(f"Error fetching {ticker_code}: {e}")
        return None


def calculate_logic(df_price):
    """Python側での判定ロジック（MA乖離率・スコア）"""
    latest_close = float(df_price['Close'].iloc[-1])
    ma25 = float(df_price['Close'].tail(25).mean())
    deviation = ((latest_close - ma25) / ma25) * 100
    score = 60 - (deviation * 1.5)
    return latest_close, deviation, score


def main():
    # 1. スプレッドシート（CSV）の読み込み
    try:
        res = requests.get(CSV_URL, timeout=10)
        res.encoding = 'utf-8'
        df_list = pd.read_csv(io.StringIO(res.text))
    except Exception as e:
        print("Error loading CSV:", e)
        send_line("CSVの読み込みに失敗しました。")
        return

    results = []

    for index, row in df_list.iterrows():
        try:
            name = str(row.iloc[1]).strip()
            code = STOCK_MASTER.get(name)

            if not code:
                continue

            print(f"分析中: {name} ({code})...")
            df_price = get_latest_price(code)

            if df_price is not None and len(df_price) >= 25:
                price, dev, score = calculate_logic(df_price)
                if score >= 60:
                    results.append({
                        "name": name,
                        "price": price,
                        "dev": dev,
                        "score": score
                    })

        except Exception as e:
            print(f"行 {index} でエラー: {e}")
            continue

    # 2. 結果を通知
    if results:
        final_df = pd.DataFrame(results).sort_values("score", ascending=False).head(7)
        msg = "【Python分析：前場判定結果】\n"
        for _, r in final_df.iterrows():
            msg += f"■{r['name']}\n   株価:{r['price']:,.1f}円 / 乖離:{r['dev']:.1f}% / スコア:{r['score']:.1f}\n"
        send_line(msg)
    else:
        send_line("本日の判定条件（スコア60以上）に合致する銘柄はありませんでした。")


def send_line(message):
    """LINE Messaging APIで送信（レスポンス表示付き）"""
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_TOKEN}"
    }
    data = {
        "to": LINE_USER_ID,
        "messages": [{"type": "text", "text": message}]
    }

    try:
        response = requests.post(url, headers=headers, json=data, timeout=10)
        print("=== LINE API Response ===")
        print("Status Code:", response.status_code)
        print("Response Body:", response.text)
        print("==========================")
    except Exception as e:
        print("LINE送信エラー:", e)


if __name__ == "__main__":
    main()