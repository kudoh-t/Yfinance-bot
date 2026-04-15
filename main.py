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
    if os.getenv("GITHUB_EVENT_NAME") == "workflow_dispatch":
        print("手動実行 → 待機スキップ")
        return

    target = time(11, 35)
    while True:
        now = datetime.now().time()
        if now >= target:
            break
        t.sleep(5)


# ==========================================
# 1. スプレッドシート CSV 読み取り（銘柄列だけ使う）
# ==========================================
CSV_URL = "https://docs.google.com/spreadsheets/d/1yEgThKuNfwvZ_3HAFFNNmHEunyHTms8B/export?format=csv"

def fetch_stock_names():
    try:
        r = requests.get(CSV_URL)
        r.raise_for_status()
        csv_text = r.text

        f = io.StringIO(csv_text)
        reader = csv.DictReader(f)

        names = []
        for row in reader:
            name = row.get("銘柄")
            if name and name.strip():
                names.append(name.strip())

        return names

    except Exception as e:
        print("CSV取得エラー:", e)
        return []


# ==========================================
# 2. 銘柄名 → 証券コード（あなた専用マッピング）
# ==========================================
NAME_TO_CODE = {
    "三菱重工": "7011",
    "ビジネスエンジ": "4828",
    "三井住友FG": "8316",
    "三菱UFJ": "8306",
    "千葉銀行": "8331",
    "信越化学": "4063",
    "村田製作所": "6981",
    "INPEX": "1605",
    "三井海洋": "6269",
    "日揮": "1963",
    "オリックス": "8591",
    "ヒューリック": "3003",
    "伊藤忠": "8001",
    "三菱商事": "8058",
    "NTT": "9432",
    "KDDI": "9433",
    "住友電工": "5802",
    "イオン": "8267",
    "三菱ガス化学": "4182",
    "純金信託": "1540",
    "ロボットETF": "2638",
    "三菱HCキャピタル": "8593",
    "クオリプス": "4894",
    "トリケミカル": "4369",
    "パワーエックス": "485A",
}


# ==========================================
# 3. 多重フェイルオーバーで株価取得（絶対 None にしない）
# ==========================================
TWELVE_API_KEY = os.getenv("TWELVE_API_KEY")

# --- ① Twelve Data ---
def fetch_twelve(code):
    if not TWELVE_API_KEY:
        return None
    try:
        url = "https://api.twelvedata.com/time_series"
        params = {
            "symbol": f"{code}.T",
            "interval": "1day",
            "outputsize": 60,
            "apikey": TWELVE_API_KEY,
            "timezone": "Asia/Tokyo",
            "order": "asc"
        }
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
        if "values" not in data:
            return None
        df = pd.DataFrame(data["values"])
        df["datetime"] = pd.to_datetime(df["datetime"])
        df.set_index("datetime", inplace=True)
        df["close"] = df["close"].astype(float)
        return df.sort_index()
    except:
        return None

# --- ② Yahoo JSON ---
def fetch_yahoo_json(code):
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{code}.T?range=2mo&interval=1d"
        r = requests.get(url, timeout=10)
        data = r.json()
        result = data.get("chart", {}).get("result", [])
        if not result:
            return None
        result = result[0]
        ts = result.get("timestamp", [])
        closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])
        if not ts or not closes:
            return None
        df = pd.DataFrame({"timestamp": ts, "close": closes})
        df.dropna(subset=["close"], inplace=True)
        df["datetime"] = pd.to_datetime(df["timestamp"], unit="s")
        df.set_index("datetime", inplace=True)
        df["close"] = df["close"].astype(float)
        return df.sort_index()
    except:
        return None

# --- ③ Yahoo HTML ---
def fetch_yahoo_html(code):
    try:
        url = f"https://finance.yahoo.co.jp/quote/{code}.T"
        r = requests.get(url, timeout=10)
        text = r.text

        import re
        m = re.search(r'"regularMarketPrice":\{"raw":([\d\.]+)', text)
        if not m:
            return None
        price = float(m.group(1))

        df = pd.DataFrame({"close": [price]}, index=[datetime.now()])
        return df
    except:
        return None

# --- ④ Yahoo 過去データ（最終手段） ---
def fetch_yahoo_hist(code):
    try:
        url = f"https://query1.finance.yahoo.com/v7/finance/download/{code}.T?interval=1d&events=history"
        r = requests.get(url, timeout=10)
        df = pd.read_csv(io.StringIO(r.text))
        df["Date"] = pd.to_datetime(df["Date"])
        df.set_index("Date", inplace=True)
        df.rename(columns={"Close": "close"}, inplace=True)
        return df[["close"]].sort_index()
    except:
        return None


# --- 総合フェイルオーバー ---
def get_price_df(code):
    for func in [fetch_twelve, fetch_yahoo_json, fetch_yahoo_html, fetch_yahoo_hist]:
        df = func(code)
        if df is not None and len(df) > 0:
            return df
    return None  # ここには基本到達しない


# ==========================================
# 4. ロジック計算
# ==========================================
def calc_logic(df):
    if len(df) < 25:
        return None

    close = df["close"]
    ma5 = close.rolling(5).mean()
    ma25 = close.rolling(25).mean()

    latest = float(close.iloc[-1])
    dev = (latest - ma25.iloc[-1]) / ma25.iloc[-1] * 100
    mom = (ma5.iloc[-1] - ma25.iloc[-1]) / ma25.iloc[-1] * 100

    score = min(100, max(0, 60 - dev * 2) + max(0, 40 + mom * 4))

    trend = "UP" if ma5.iloc[-1] > ma25.iloc[-1] else "DOWN"

    return {
        "price": latest,
        "dev": dev,
        "mom": mom,
        "score": score,
        "trend": trend
    }


# ==========================================
# 5. 理由付け
# ==========================================
def build_reason(dev, score, mom):
    reasons = []
    if dev > 0:
        reasons.append("短期トレンドが上向きです")
    elif dev > -2:
        reasons.append("下落が一服し、底打ちの兆しがあります")
    else:
        reasons.append("トレンドは弱いですが、反発余地があります")

    if score >= 80:
        reasons.append("総合スコアが高く、基礎体力が強い銘柄です")
    elif score >= 60:
        reasons.append("総合スコアが良好で安定しています")
    else:
        reasons.append("スコアは中立で、様子見が必要です")

    if mom > 0:
        reasons.append("モメンタムが強く、上昇圧力があります")
    else:
        reasons.append("モメンタムは弱めですが、反転の可能性があります")

    return "・" + "\n・".join(reasons)


# ==========================================
# 6. LINE送信
# ==========================================
LINE_TOKEN = os.getenv("LINE_TOKEN")
LINE_USER_ID = os.getenv("LINE_USER_ID")

def send_line(msg):
    if not LINE_TOKEN or not LINE_USER_ID:
        print("LINE環境変数が未設定")
        return
    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LINE_TOKEN}"}
    data = {"to": LINE_USER_ID, "messages": [{"type": "text", "text": msg}]}
    requests.post(url, headers=headers, json=data)


# ==========================================
# 7. メイン処理
# ==========================================
def main():
    wait_until_1135()

    names = fetch_stock_names()
    results = []

    for name in names:
        code = NAME_TO_CODE.get(name)
        if not code:
            continue

        df = get_price_df(code)
        if df is None:
            continue

        logic = calc_logic(df)
        if logic is None:
            continue

        results.append({
            "name": name,
            "code": code,
            **logic,
            "reason": build_reason(logic["dev"], logic["score"], logic["mom"])
        })

    if not results:
        send_line("データ取得に失敗しました（フェイルオーバー全滅）")
        return

    top7 = sorted(results, key=lambda x: x["score"], reverse=True)[:7]

    msg = "【本日のBuy Top7】\n\n"
    for r in top7:
        msg += f"■{r['name']}（{r['code']}）\n"
        msg += f"   株価:{r['price']:.1f}円 / 乖離:{r['dev']:.1f}% / モメンタム:{r['mom']:.2f}% / スコア:{r['score']:.1f}\n"
        msg += f"{r['reason']}\n\n"

    send_line(msg)


if __name__ == "__main__":
    main()
