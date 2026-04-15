import os
import csv
import requests
import pandas as pd
import io
from datetime import datetime, time
import time as t

# ==========================================
# 0. 11:35 まで待機（手動実行はスキップ）
# ==========================================
def wait_until_1135():
    # GitHub Actions の手動実行なら即通知
    if os.getenv("GITHUB_EVENT_NAME") == "workflow_dispatch":
        print("手動実行 → 11:35待機をスキップします")
        return

    # cron 実行時は 11:35 まで待機
    target = time(11, 35)
    while True:
        now = datetime.now().time()
        if now >= target:
            break
        t.sleep(5)


# ==========================================
# 1. Yahooポートフォリオ CSV取得
# ==========================================
def fetch_portfolio_csv(portfolio_id=2):
    url = f"https://finance.yahoo.co.jp/portfolio/download?portfolioId={portfolio_id}"
    r = requests.get(url)
    r.raise_for_status()

    csv_text = r.text
    f = io.StringIO(csv_text)
    reader = csv.DictReader(f)

    stocks = []
    for row in reader:
        try:
            code = row["コード"]
            name = row["銘柄名"]
            price = float(row["現在値"].replace(",", ""))
            shares = int(row["保有数"].replace(",", ""))
        except:
            continue

        if shares <= 0:
            continue

        stocks.append({
            "code": code,
            "name": name,
            "price": price,
            "shares": shares,
        })

    return stocks


# ==========================================
# 2. Twelve Data → Yahoo フェイルオーバー
# ==========================================
TWELVE_API_KEY = os.getenv("TWELVE_API_KEY")

def get_price_from_twelve(symbol_code):
    if not TWELVE_API_KEY:
        return None

    symbol = f"{symbol_code}.T"
    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": symbol,
        "interval": "1day",
        "outputsize": 60,
        "apikey": TWELVE_API_KEY,
        "timezone": "Asia/Tokyo",
        "order": "asc"
    }
    try:
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
        if "values" not in data:
            return None
        df = pd.DataFrame(data["values"])
        df["datetime"] = pd.to_datetime(df["datetime"])
        df.set_index("datetime", inplace=True)
        df["close"] = df["close"].astype(float)
        df = df.sort_index()
        return df
    except:
        return None


def get_price_from_yahoo(symbol_code):
    symbol = f"{symbol_code}.T"
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=2mo&interval=1d"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        data = r.json()
        result = data.get("chart", {}).get("result", [])
        if not result:
            return None
        result = result[0]
        timestamps = result.get("timestamp", [])
        closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])
        if not timestamps or not closes:
            return None
        df = pd.DataFrame({"timestamp": timestamps, "close": closes})
        df.dropna(subset=["close"], inplace=True)
        df["datetime"] = pd.to_datetime(df["timestamp"], unit="s")
        df.set_index("datetime", inplace=True)
        df["close"] = df["close"].astype(float)
        df = df.sort_index()
        return df
    except:
        return None


def get_price_with_failover(symbol_code):
    df = get_price_from_twelve(symbol_code)
    if df is not None and len(df) >= 25:
        return df

    df = get_price_from_yahoo(symbol_code)
    if df is not None and len(df) >= 25:
        return df

    return None


# ==========================================
# 3. ロジック計算（MA5/25・乖離・モメンタム・スコア）
# ==========================================
def calculate_logic(df_price):
    if len(df_price) < 25:
        return None

    close = df_price["close"]
    ma5 = close.rolling(5).mean()
    ma25 = close.rolling(25).mean()

    latest_close = float(close.iloc[-1])
    latest_ma5 = float(ma5.iloc[-1])
    latest_ma25 = float(ma25.iloc[-1])

    deviation = ((latest_close - latest_ma25) / latest_ma25) * 100
    momentum = (latest_ma5 - latest_ma25) / latest_ma25 * 100

    score_dev = max(0, 60 - deviation * 2)
    score_mom = max(0, 40 + momentum * 4)
    score_integ = min(100, score_dev + score_mom)

    if latest_ma5 > latest_ma25:
        trend = "UP"
    elif latest_ma5 < latest_ma25:
        trend = "DOWN"
    else:
        trend = "FLAT"

    is_buy = (momentum > -1.0) or (score_integ >= 45)

    return {
        "latest_close": latest_close,
        "deviation": deviation,
        "momentum": momentum,
        "score_integ": score_integ,
        "trend": trend,
        "is_buy": is_buy
    }


# ==========================================
# 4. 理由付け（自然文）
# ==========================================
def build_reason(dev, score, momentum):
    reasons = []

    if dev > 0:
        reasons.append("短期トレンドが上向きに転じています")
    elif dev > -2:
        reasons.append("下落が一服し、底打ちの兆しがあります")
    else:
        reasons.append("トレンドは弱いものの、反発余地があります")

    if score >= 85:
        reasons.append("総合スコアが非常に高く、基礎体力が強い銘柄です")
    elif score >= 70:
        reasons.append("総合スコアが良好で、安定した評価を受けています")
    else:
        reasons.append("スコアは中立で、様子見が必要です")

    if momentum > 0:
        reasons.append("モメンタムが強く、上昇圧力があります")
    else:
        reasons.append("モメンタムは弱めですが、反転の可能性があります")

    return "・" + "\n・".join(reasons)


# ==========================================
# 5. PF総括
# ==========================================
def build_portfolio_comment(stocks):
    top = max(stocks, key=lambda x: x["score"])
    comment = []

    comment.append("全体として、市場と同程度の値動きでバランスの取れた構造です。")
    comment.append(f"最も強いのは「{top['name']}」で、短期的な上昇余地が期待されます。")
    comment.append("全体として、短期の反発余地を探りつつ、リスクを抑えた運用ができています。")

    return "\n".join(comment)


# ==========================================
# 6. LINE送信
# ==========================================
LINE_TOKEN = os.getenv("LINE_TOKEN")
LINE_USER_ID = os.getenv("LINE_USER_ID")

def send_line(message):
    if not LINE_TOKEN or not LINE_USER_ID:
        print("LINE環境変数が未設定です")
        return

    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_TOKEN}"
    }
    data = {
        "to": LINE_USER_ID,
        "messages": [{"type": "text", "text": message}]
    }
    requests.post(url, headers=headers, json=data)


# ==========================================
# 7. メイン処理
# ==========================================
def main():
    wait_until_1135()

    stocks = fetch_portfolio_csv()
    results = []

    for s in stocks:
        df_price = get_price_with_failover(s["code"])
        if df_price is None:
            continue

        logic = calculate_logic(df_price)
        if logic is None:
            continue

        s.update({
            "dev": logic["deviation"],
            "momentum": logic["momentum"],
            "score": logic["score_integ"],
            "trend": logic["trend"],
            "is_buy": logic["is_buy"],
            "reason": build_reason(logic["deviation"], logic["score_integ"], logic["momentum"])
        })

        results.append(s)

    if not results:
        send_line("【本日の買い推奨Top7】\nデータ取得に失敗しました。")
        return

    final_df = (
        pd.DataFrame(results)
        .sort_values("score", ascending=False)
        .head(7)
    )

    msg = "【本日の買い推奨Top7】\n\n"
    for _, r in final_df.iterrows():
        msg += f"■{r['name']}（{'Buy' if r['is_buy'] else 'Sell'} / トレンド:{r['trend']}）\n"
        msg += f"   株価:{r['price']:,.1f}円 / 乖離:{r['dev']:.1f}% / モメンタム:{r['momentum']:.2f}% / スコア:{r['score']:.1f}\n"
        msg += f"{r['reason']}\n\n"

    msg += "【PF総括】\n" + build_portfolio_comment(results)

    send_line(msg)


if __name__ == "__main__":
    main()
