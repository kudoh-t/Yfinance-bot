import os
import requests
import pandas as pd
import pandas_datareader.data as web
from datetime import datetime, timedelta
import io

# ==========================================
# 1. 設定
# ==========================================
CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vTnmbJ3DubdIL0DmokPDIn0u9uDUZBUL7UVPOQ48Mu8qFRLaUBqekdg6BTZbzmFcURPXKY3qlpDsev4/pub?output=csv"
 # 先ほどの pub?output=csv のURL
LINE_TOKEN = os.getenv("LINE_TOKEN")
LINE_USER_ID = os.getenv("LINE_USER_ID")

def get_stock_price_stooq(ticker_code):
    """Stooqから日本株の直近データを取得"""
    target = f"{ticker_code}.JP"
    end = datetime.now()
    start = end - timedelta(days=60) # 25日移動平均を出すために少し長めに取得
    try:
        df = web.DataReader(target, 'stooq', start, end)
        return df.sort_index() # 日付順に並び替え
    except Exception as e:
        print(f"Error fetching {ticker_code}: {e}")
        return None

def calculate_logic(df_price):
    """
    Python側での計算ロジック。
    ここでMA乖離率、総合スコア、合体スコアを算出します。
    """
    # 最新の終値
    latest_close = float(df_price['Close'].iloc[-1])
    
    # 25日移動平均線 (MA25)
    ma25 = float(df_price['Close'].rolling(window=25).mean().iloc[-1])
    
    # MA乖離率 (%)
    deviation = ((latest_close - ma25) / ma25) * 100
    
    # 【判定ロジック】
    # 例：乖離率が低い（売られすぎ）ほど高スコアにする独自の重み付け
    # スコア = (基準値100) - (乖離率の絶対値 * 係数) などのエンジニアリング数式
    base_score = 60
    logic_score = base_score - (deviation * 1.5) 
    
    return latest_close, deviation, logic_score

def main():
    # スプレッドシートから「銘柄コード」のリストだけを読み込む
    res = requests.get(CSV_URL)
    res.encoding = 'utf-8'
    stock_list = pd.read_csv(io.StringIO(res.text))

    hit_stocks = []
    
    for _, row in stock_list.iterrows():
        code = row['銘柄コード'] # スプレッドシートの列名に合わせてください
        name = row['銘柄']
        
        print(f"Analyzing: {name} ({code})...")
        df_price = get_stock_price_stooq(code)
        
        if df_price is not None and len(df_price) >= 25:
            price, dev, score = calculate_logic(df_price)
            
            # 判定：スコアが一定以上（例：60以上）ならLINE対象
            if score >= 60:
                hit_stocks.append({
                    "name": name,
                    "price": price,
                    "dev": dev,
                    "score": score
                })

    # 結果をスコア順に並び替えて上位7件を送信
    if hit_stocks:
        final_df = pd.DataFrame(hit_stocks).sort_values("score", ascending=False).head(7)
        msg = "【Python完全計算：前場判定】\n"
        for _, r in final_df.iterrows():
            msg += f"■{r['name']}\n   株価:{r['price']:,.1f} / 乖離:{r['dev']:.1f}% / スコア:{r['score']:.1f}\n"
        
        send_line(msg)
    else:
        send_line("本日の条件合致銘柄はありませんでした。")

def send_line(message):
    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LINE_TOKEN}"}
    data = {"to": LINE_USER_ID, "messages": [{"type": "text", "text": message}]}
    requests.post(url, headers=headers, json=data)

if __name__ == "__main__":
    main()