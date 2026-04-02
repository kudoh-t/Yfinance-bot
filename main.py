import os
import requests
import pandas as pd
import io
from datetime import datetime

# ==========================================
# 1. 設定
# ==========================================
CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vTnmbJ3DubdIL0DmokPDIn0u9uDUZBUL7UVPOQ48Mu8qFRLaUBqekdg6BTZbzmFcURPXKY3qlpDsev4/pub?output=csv"
 # 先ほどの pub?output=csv のURL
LINE_TOKEN = os.getenv("LINE_TOKEN")
LINE_USER_ID = os.getenv("LINE_USER_ID")

def get_latest_price(ticker_code):
    """Yahoo FinanceのWEB APIから直近の株価データを取得"""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker_code}.T?range=2mo&interval=1d"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        response = requests.get(url, headers=headers)
        data = response.json()
        result = data['chart']['result'][0]
        closes = result['indicators']['quote'][0]['close']
        df = pd.DataFrame(closes, columns=['Close'])
        return df.dropna()
    except Exception as e:
        print(f"Error fetching {ticker_code}: {e}")
        return None

def calculate_logic(df_price):
    """Python側での計算ロジック"""
    latest_close = float(df_price['Close'].iloc[-1])
    ma25 = float(df_price['Close'].tail(25).mean()) # 直近25日平均
    
    # MA乖離率 (%)
    deviation = ((latest_close - ma25) / ma25) * 100
    
    # 判定ロジック（スコア計算）
    # 例：乖離率がマイナス（売られすぎ）ならスコア加算
    score = 60 - (deviation * 1.5)
    
    return latest_close, deviation, score

def main():
    # 1. スプレッドシートから銘柄コードを取得
    res = requests.get(CSV_URL)
    # エラー対策：余計な空行などを無視して読み込む
    df_list = pd.read_csv(io.StringIO(res.text)).dropna(subset=['銘柄コード'])

    results = []
    for _, row in df_list.iterrows():
        # コードを整数にしてから文字列にする（9101.0のような浮動小数を防ぐ）
        code = str(int(row['銘柄コード']))
        name = row['銘柄']
        
        print(f"Analyzing: {name} ({code})...")
        df_price = get_latest_price(code)
        
        if df_price is not None and len(df_price) >= 25:
            price, dev, score = calculate_logic(df_price)
            
            # 判定：スコアが60以上なら採用
            if score >= 60:
                results.append({"name": name, "price": price, "dev": dev, "score": score})

    # 2. 結果を通知
    if results:
        final_df = pd.DataFrame(results).sort_values("score", ascending=False).head(7)
        msg = "【Python完全計算：前場判定】\n"
        for _, r in final_df.iterrows():
            msg += f"■{r['name']}\n   株価:{r['price']:,.1f} / 乖離:{r['dev']:.1f}% / スコア:{r['score']:.1f}\n"
        send_line(msg)
    else:
        send_line("本日の条件合致銘柄はありません。")

def send_line(message):
    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LINE_TOKEN}"}
    data = {"to": LINE_USER_ID, "messages": [{"type": "text", "text": message}]}
    requests.post(url, headers=headers, json=data)

if __name__ == "__main__":
    main()