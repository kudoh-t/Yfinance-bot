import os
import requests
import pandas as pd
from datetime import datetime, time
import time as t


def is_japanese_holiday():
    """日本の祝日APIで当日が祝日か判定"""
    try:
        url = "https://holidays-jp.github.io/api/v1/date.json"
        r = requests.get(url, timeout=5)
        r.raise_for_status()
        holidays = r.json()  # {"2026-01-01": "元日", ...}

        today = datetime.now().strftime("%Y-%m-%d")
        return today in holidays
    except Exception as e:
        print("祝日API取得失敗:", e)
        return False  # API失敗時は通知を止めない

def is_weekday():
    # Monday=0 ... Sunday=6
    return datetime.now().weekday() < 5

# ==============================
# 0. 11:35 まで待機（GitHub Actions ではスキップ）
# ==============================
def wait_until_1135():
    # GitHub Actions では待機しない（cron が JST 11:38 に起動してくれる）
    if os.getenv("GITHUB_ACTIONS") == "true":
        print("GitHub Actions → 待機スキップ")
        return

    target = time(11, 35)
    while True:
        now = datetime.now().time()
        if now >= target:
            break
        t.sleep(5)

# ==============================
# 1. 銘柄リスト
# ==============================
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
     # ★ 追加
    "iシェアーズオートメーション&ロボットETF": "2522",
}

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0 Safari/537.36"
    )
}

# ==============================
# 2. データ取得（Yahoo JSON）
# ==============================
def fetch_yahoo_json_daily(code: str):
    """
    過去データ（日足）を Yahoo JSON から取得（3ヶ月分）
    MA25 計算用
    """
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{code}.T"
        params = {
            "range": "3mo",
            "interval": "1d",
        }
        r = requests.get(url, headers=UA, params=params, timeout=10)
        r.raise_for_status()
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
    except Exception as e:
        print(f"Yahoo JSON（日足）取得失敗 {code}: {e}")
        return None


def fetch_yahoo_realtime(code: str):
    """
    当日リアルタイム価格（前場終値を含む）を Yahoo JSON から取得
    regularMarketPrice を使用
    """
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{code}.T"
        params = {
            "range": "1d",
            "interval": "1m",
        }
        r = requests.get(url, headers=UA, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()

        result = data.get("chart", {}).get("result", [])
        if not result:
            return None

        meta = result[0].get("meta", {})
        price = meta.get("regularMarketPrice")
        if price is None:
            return None

        df = pd.DataFrame({"close": [float(price)]}, index=[datetime.now()])
        return df
    except Exception as e:
        print(f"Yahoo JSON（リアルタイム）取得失敗 {code}: {e}")
        return None


def get_price_df(code: str):
    """
    過去日足（3ヶ月）＋当日リアルタイムを結合して返す
    → MA5 / MA25 計算に使用
    """
    base = fetch_yahoo_json_daily(code)
    rt = fetch_yahoo_realtime(code)

    if base is None and rt is None:
        return None
    if base is None:
        return rt.sort_index()
    if rt is None:
        return base.sort_index()

    df = pd.concat([base, rt])
    df = df[~df.index.duplicated(keep="last")]
    return df.sort_index()

# ==============================
# 3. ロジック計算
# ==============================
def calc_logic(df: pd.DataFrame):
    try:
        if len(df) < 25:
            return None

        close = df["close"]
        ma5 = close.rolling(5).mean()
        ma25 = close.rolling(25).mean()

        latest = float(close.iloc[-1])
        ma25_latest = float(ma25.iloc[-1])
        ma5_latest = float(ma5.iloc[-1])

        dev = (latest - ma25_latest) / ma25_latest * 100
        mom = (ma5_latest - ma25_latest) / ma25_latest * 100

        score = min(100, max(0, 60 - dev * 2) + max(0, 40 + mom * 4))
        trend = "UP" if ma5_latest > ma25_latest else "DOWN"

        return {
            "price": latest,
            "dev": dev,
            "mom": mom,
            "score": score,
            "trend": trend,
        }
    except Exception as e:
        print("calc_logic error:", e)
        return None

# ==============================
# 4. 理由付け（強化版）
# ==============================
def build_reason(dev: float, score: float, mom: float) -> str:
    reasons = []

    # トレンド
    if dev > 0:
        reasons.append("短期トレンドが上向きで、買い圧力が強まっています")
    elif dev > -2:
        reasons.append("下落が一服し、底打ちの兆しが見られます")
    else:
        reasons.append("トレンドは弱いものの、反発余地が残っています")

    # スコア
    if score >= 80:
        reasons.append("総合スコアが非常に高く、基礎体力の強さが際立っています")
    elif score >= 60:
        reasons.append("総合スコアが良好で、安定した推移が期待できます")
    else:
        reasons.append("スコアは中立圏で、慎重な判断が必要です")

    # モメンタム
    if mom > 0:
        reasons.append("モメンタムが強く、上昇の勢いが続いています")
    else:
        reasons.append("モメンタムは弱めですが、反転の可能性があります")

    return "・" + "\n・".join(reasons)

# ==============================
# 5. LINE送信
# ==============================
LINE_TOKEN = os.getenv("LINE_TOKEN")
LINE_USER_ID = os.getenv("LINE_USER_ID")

def send_line(msg: str):
    if not LINE_TOKEN or not LINE_USER_ID:
        print("LINE環境変数が未設定")
        print(msg)
        return

    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_TOKEN}",
    }
    data = {
        "to": LINE_USER_ID,
        "messages": [{"type": "text", "text": msg}],
    }
    try:
        r = requests.post(url, headers=headers, json=data, timeout=10)
        print("LINE status:", r.status_code, r.text[:200])
    except Exception as e:
        print("LINE送信エラー:", e)
        print(msg)

# ==============================
# 6. メイン処理
# ==============================
def main():
    # --- 土日は通知しない ---
    if not is_weekday():
        print("今日は土日 → 通知スキップ")
        return
    # --- 日本の祝日も通知しない ---
    if is_japanese_holiday():
        print("今日は祝日 → 通知スキップ")
        return
    wait_until_1135()

    results = []
    for name, code in NAME_TO_CODE.items():
        df = get_price_df(code)
        if df is None:
            print(f"{name}({code}) → データ取得失敗（スキップ）")
            continue

        logic = calc_logic(df)
        if logic is None:
            print(f"{name}({code}) → ロジック不可（スキップ）")
            continue

        results.append({
            "name": name,
            "code": code,
            **logic,
            "reason": build_reason(logic["dev"], logic["score"], logic["mom"]),
        })

    if not results:
        send_line("全銘柄でデータ取得に失敗しました（データソース障害の可能性）")
        return

    top7 = sorted(results, key=lambda x: x["score"], reverse=True)[:7]

    msg = "【本日の Buy Top7】\n\n"
    for r in top7:
        msg += f"■{r['code']} {r['name']}\n"
        msg += (
            f"   株価:{r['price']:.1f}円 / "
            f"乖離:{r['dev']:.1f}% / "
            f"モメンタム:{r['mom']:.2f}% / "
            f"スコア:{r['score']:.1f}\n"
        )
        msg += f"{r['reason']}\n\n"

    send_line(msg)

if __name__ == "__main__":
    main()
