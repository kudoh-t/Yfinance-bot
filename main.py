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

# ==========================================
# 2. 環境変数
# ==========================================
CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vTnmbJ3DubdIL0DmokPDIn0u9uDUZBUL7UVPOQ48Mu8qFRLaUBqekdg6BTZbzmFcURPXKY3qlpDsev4/pub?output=csv"

LINE_TOKEN = os.getenv("LINE_TOKEN")
LINE_USER_ID = os.getenv("LINE_USER_ID")
TWELVE_API_KEY = os.getenv("TWELVE_API_KEY")

print("=== Debug: Environment Variables ===")
print("LINE_TOKEN exists:", LINE_TOKEN is not None)
print("LINE_USER_ID:", LINE_USER_ID)
print("TWELVE_API_KEY exists:", TWELVE_API_KEY is not None)
print("====================================")


# ==========================================
# 3. データ取得系
# ==========================================
def get_price_from_twelve(symbol_code):
    """
    Twelve Data の time_series API から日足データを取得し、
    pandas.DataFrame（datetime index, close列）を返す
    """
    if not TWELVE_API_KEY:
        print("TWELVE_API_KEY が設定されていません。")
        return None

    symbol = f"{symbol_code}.T"
    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": symbol,
        "interval": "1day",
        "outputsize": 60,  # MA25計算に十分な日数
        "apikey": TWELVE_API_KEY,
        "timezone": "Asia/Tokyo",
        "order": "asc"
    }
    try:
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
        if "values" not in data:
            print(f"Twelve Data error for {symbol_code}: {data}")
            return None
        df = pd.DataFrame(data["values"])
        df["datetime"] = pd.to_datetime(df["datetime"])
        df.set_index("datetime", inplace=True)
        df["close"] = df["close"].astype(float)
        df = df.sort_index()
        return df
    except Exception as e:
        print(f"Error fetching from Twelve Data {symbol_code}: {e}")
        return None


def get_price_from_yahoo(symbol_code):
    """
    Yahoo Finance の chart API から日足データを取得し、
    pandas.DataFrame（datetime index, close列）を返す
    """
    symbol = f"{symbol_code}.T"
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=2mo&interval=1d"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        data = r.json()
        result = data.get("chart", {}).get("result", [])
        if not result:
            print(f"Yahoo result empty for {symbol_code}: {data}")
            return None
        result = result[0]
        timestamps = result.get("timestamp", [])
        closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])
        if not timestamps or not closes:
            print(f"Yahoo data missing for {symbol_code}")
            return None
        df = pd.DataFrame({"timestamp": timestamps, "close": closes})
        df.dropna(subset=["close"], inplace=True)
        df["datetime"] = pd.to_datetime(df["timestamp"], unit="s")
        df.set_index("datetime", inplace=True)
        df["close"] = df["close"].astype(float)
        df = df.sort_index()
        return df
    except Exception as e:
        print(f"Error fetching from Yahoo {symbol_code}: {e}")
        return None


def get_price_with_failover(symbol_code):
    """
    Twelve Data → 失敗したら Yahoo → それでもダメなら None
    """
    df = get_price_from_twelve(symbol_code)
    if df is not None and len(df) >= 25:
        return df

    print(f"Falling back to Yahoo for {symbol_code}...")
    df = get_price_from_yahoo(symbol_code)
    if df is not None and len(df) >= 25:
        return df

    print(f"Both Twelve Data and Yahoo failed or insufficient data for {symbol_code}.")
    return None


# ==========================================
# 4. ロジック計算
# ==========================================
def calculate_logic(df_price):
    """
    改良版ロジック：
    - MA5 / MA25
    - 乖離率（最新終値 vs MA25）
    - モメンタム（MA5とMA25の差）
    - 合成スコア（乖離＋モメンタム）
    - トレンド判定
    """
    if len(df_price) < 25:
        return None

    close = df_price["close"]
    ma5 = close.rolling(5).mean()
    ma25 = close.rolling(25).mean()

    latest_close = float(close.iloc[-1])
    latest_ma5 = float(ma5.iloc[-1])
    latest_ma25 = float(ma25.iloc[-1])

    # 25日線乖離率
    deviation = ((latest_close - latest_ma25) / latest_ma25) * 100

    # モメンタム（MA5 vs MA25）
    momentum = (latest_ma5 - latest_ma25) / latest_ma25 * 100

    # 乖離率スコア（最大60点）
    score_dev = max(0, 60 - deviation * 2)

    # モメンタムスコア（最大40点）
    score_mom = max(0, 40 + momentum * 4)

    # 合成スコア（最大100点）
    score_integ = min(100, score_dev + score_mom)

    # トレンド判定（シンプル版）
    if latest_ma5 > latest_ma25:
        trend = "UP"
    elif latest_ma5 < latest_ma25:
        trend = "DOWN"
    else:
        trend = "FLAT"

    # Buy 条件（緩和版）
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
# 5. メイン処理
# ==========================================
def main():
    # 1. スプレッドシート（CSV）の読み込み
    try:
        res = requests.get(CSV_URL, timeout=10)
        res.encoding = "utf-8"
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

            df_price = get_price_with_failover(code)
            if df_price is None:
                continue

            logic = calculate_logic(df_price)
            if logic is None:
                continue

            results.append({
                "name": name,
                "price": logic["latest_close"],
                "dev": logic["deviation"],
                "momentum": logic["momentum"],
                "score": logic["score_integ"],
                "trend": logic["trend"],
                "is_buy": logic["is_buy"]
            })

        except Exception as e:
            print(f"行 {index} でエラー: {e}")
            continue

    # 2. Top7 抽出（Buy 条件に関係なくスコア上位7件）
    if results:
        final_df = (
            pd.DataFrame(results)
            .sort_values("score", ascending=False)
            .head(7)
        )

        # Buy / Sell ラベル付与
        final_df["signal"] = final_df["is_buy"].apply(lambda x: "Buy" if x else "Sell")

        msg = "【本日の買い推奨Top7】\n"
        msg += "判定根拠：\n"
        msg += "・MA5/MA25の位置関係\n"
        msg += "・25日線乖離率\n"
        msg += "・モメンタム（直近の強さ）\n"
        msg += "・スコア上位7銘柄を抽出（Buy条件は参考情報）\n\n"

        for _, r in final_df.iterrows():
            msg += f"■{r['name']}（{r['signal']} / トレンド:{r['trend']}）\n"
            msg += (
                f"   株価:{r['price']:,.1f}円 / "
                f"乖離:{r['dev']:.1f}% / "
                f"モメンタム:{r['momentum']:.2f}% / "
                f"スコア:{r['score']:.1f}\n"
            )

        send_line(msg)
    else:
        msg = "【本日の買い推奨Top7】\n"
        msg += "判定根拠：\n"
        msg += "・MA5/MA25の位置関係\n"
        msg += "・25日線乖離率\n"
        msg += "・モメンタム（直近の強さ）\n"
        msg += "・スコア上位7銘柄を抽出（Buy条件は参考情報）\n\n"
        msg += "本日の条件に合致する銘柄はありませんでした。"
        send_line(msg)


# ==========================================
# 6. LINE 送信
# ==========================================
def send_line(message):
    """LINE Messaging APIで送信（レスポンス表示付き）"""
    if not LINE_TOKEN or not LINE_USER_ID:
        print("LINE 環境変数が設定されていません。")
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
