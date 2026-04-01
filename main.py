import os
import requests
import pandas as pd
from bs4 import BeautifulSoup

LINE_TOKEN = os.getenv("LINE_TOKEN")
LINE_USER_ID = os.getenv("LINE_USER_ID")

# ====== User-Agent（みんかぶ対策：必須） ======
headers = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0"
    ),
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Connection": "keep-alive",
}

# ====== Holdings ======
holdings = {
    '三菱重工': 2000, 'ビジネスエンジ': 18000, '三井住友FG': 1500, '三菱UFJ': 800,
    '千葉銀行': 200, '信越化学': 500, '村田製作所': 400, 'INPEX': 100,
    '三井海洋': 100, '日揮': 100, 'オリックス': 100, 'ヒューリック': 100,
    '伊藤忠': 100, '三菱商事': 300, 'NTT': 100,
    'KDDI': 100, '住友電工': 200, 'イオン': 300, '三菱ガス化学': 200,
    '三菱HCキャピタル': 200, 'クオリプス': 300
}

ticker_map = {
    '三菱重工': '7011', 'ビジネスエンジ': '4828', '三井住友FG': '8316', '三菱UFJ': '8306',
    '千葉銀行': '8331', '信越化学': '4063', '村田製作所': '6981', 'INPEX': '1605',
    '三井海洋': '6269', '日揮': '1963', 'オリックス': '8591', 'ヒューリック': '3003',
    '伊藤忠': '8001', '三菱商事': '8058', 'NTT': '9432',
    'KDDI': '9433', '住友電工': '5802', 'イオン': '8267', '三菱ガス化学': '4182',
    '三菱HCキャピタル': '8593', 'クオリプス': '4894'
}

# ====== みんかぶ：株価取得 ======
def get_price_minkabu(code):
    url = f"https://minkabu.jp/stock/{code}"
    r = requests.get(url, headers=headers)
    soup = BeautifulSoup(r.text, "html.parser")

    tag = soup.select_one(".md_stockBoard_stockPrice")
    if tag:
        return float(tag.text.replace(",", ""))

    return None

# ====== みんかぶ：過去株価取得 ======
def get_history_minkabu(code):
    url = f"https://minkabu.jp/stock/{code}/daily"
    r = requests.get(url, headers=headers)
    soup = BeautifulSoup(r.text, "html.parser")

    rows = soup.select("table.stocksTable tbody tr")
    prices = []

    for row in rows:
        cols = row.select("td")
        if len(cols) >= 5:
            try:
                close = float(cols[4].text.replace(",", ""))
                prices.append(close)
            except:
                pass

    return pd.Series(prices[::-1])  # 古い→新しい順

# ====== LINE通知 ======
def notify_line(message):
    url = "https://api.line.me/v2/bot/message/push"
    headers_line = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_TOKEN}",
    }
    data = {"to": LINE_USER_ID, "messages": [{"type": "text", "text": message}]}
    requests.post(url, headers=headers_line, json=data)

# ====== 分析 ======
def build_df_latest():
    results = []

    for name, qty in holdings.items():
        code = ticker_map[name]

        prices = get_history_minkabu(code)
        if prices is None or len(prices) < 30:
            continue

        ma5 = prices.rolling(5).mean().iloc[-1]
        ma25 = prices.rolling(25).mean().iloc[-1]
        momentum = (ma5 - ma25) / ma25 if ma25 != 0 else 0

        current_price = prices.iloc[-1]

        beta = 1.0  # みんかぶでは取得不可 → 仮値

        score_integ = 50 + (momentum * 100 * beta)
        if beta < 0.8:
            score_integ += 10

        is_buy = (momentum > -0.005) or (score_integ > 45)
        sig = "Buy" if is_buy else "Sell"

        results.append({
            "name": name,
            "price": current_price,
            "momentum": momentum,
            "score_integ": score_integ,
            "signal": sig
        })

    return pd.DataFrame(results)

# ====== Top7 ======
def pick_top7(df):
    buy_df = df[df["signal"] == "Buy"]
    return buy_df.sort_values("score_integ", ascending=False).head(7)

# ====== main ======
def main():
    df = build_df_latest()

    if df.empty:
        notify_line("データ取得に失敗しました。")
        return

    top7 = pick_top7(df)

    if top7.empty:
        notify_line("本日は Buy シグナルがありませんでした。")
        return

    msg = "【今日の買い推奨 Top7】\n"
    for _, r in top7.iterrows():
        msg += f"{r['name']} 価格:{r['price']} 合体:{r['score_integ']:.1f}\n"

    notify_line(msg)

if __name__ == "__main__":
    main()
