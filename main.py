import os
import requests
import pandas as pd
import io
from datetime import datetime, time
import time as t
import re

# ==============================
# 0. 11:35 まで待機（GitHub Actions ではスキップ）
# ==============================
def wait_until_1135():
    # CI（GitHub Actions）では待機しない
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
# 1. 銘柄リスト（唯一のデータソース）
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
}

# ==============================
# 2. データ取得（Google Finance + Yahoo HTML）
# ==============================

def fetch_google(code):
    """
    過去データ（終値）を Google Finance から取得（1ヶ月分）
    """
    try:
        url = f"https://www.google.com/finance/quote/{code}:TSE?window=1M&output=csv"
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()

        df = pd.read_csv(io.StringIO(r.text))
        # Google Finance の CSV は "Date","Close" などの列を持つ想定
        if "Date" not in df.columns or "Close" not in df.columns:
            return None

        df["Date"] = pd.to_datetime(df["Date"])
        df.set_index("Date", inplace=True)
        df.rename(columns={"Close": "close"}, inplace=True)
        df = df[["close"]].sort_index()
        return df
    except Exception as e:
        print(f"Google取得失敗 {code}: {e}")
        return None


def fetch_yahoo_realtime(code):
    """
    当日リアルタイム価格（前場終値を含む）を Yahoo HTML から取得
    """
    try:
        url = f"https://finance.yahoo.co.jp/quote/{code}.T"
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        text = r.text

        m = re.search(r'"regularMarketPrice":\{"raw":\s*([\d\.]+)', text)
        if not m:
            return None

        price = float(m.group(1))
        df = pd.DataFrame({"close": [price]}, index=[datetime.now()])
        return df
    except Exception as e:
        print(f"Yahoo HTML取得失敗 {code}: {e}")
        return None


def get_price_df(code):
    """
    過去データ：Google
    当日価格：Yahoo HTML
    を組み合わせて、MA計算に使える DataFrame を返す
    """
    base_df = fetch_google(code)
    rt_df = fetch_yahoo_realtime(code)

    if base_df is None and rt_df is None:
        return None

    if base_df is None:
        return rt_df.sort_index()

    if rt_df is None:
        return base_df.sort_index()

    # index が被る場合はリアルタイムを優先
    df = pd.concat([base_df, rt_df])
    df = df[~df.index.duplicated(keep="last")]
    return df.sort_index()

# ==============================
# 3. ロジック計算
# ==============================
def calc_logic(df):
    try:
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
            "trend": trend,
        }
    except Exception as e:
        print("calc_logic error:", e)
        return None

# ==============================
# 4. 理由付け（強化版）
# ==============================
def build_reason(dev, score, mom):
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

def send_line(msg):
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
    requests.post(url, headers=headers, json=data)

# ==============================
# 6. メイン処理
# ==============================
def main():
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
        msg += f"■{r['name']}（{r['code']}）\n"
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
