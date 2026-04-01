import os
import requests
import pandas as pd
import numpy as np
from collections import defaultdict
from datetime import date, timedelta

# ====== 設定 ======
BENCHMARK_TICKER = "1306.T"  # TOPIX ETF など
ALPHA_KEY = os.getenv("ALPHA_KEY")
LINE_TOKEN = os.getenv("LINE_TOKEN")
LINE_USER_ID = os.getenv("LINE_USER_ID")

# --- Holdings and Mappings (元コードからそのまま) ---
holdings = {
    '三菱重工': 2000, 'ビジネスエンジ': 18000, '三井住友FG': 1500, '三菱UFJ': 800,
    '千葉銀行': 200, '信越化学': 500, '村田製作所': 400, 'INPEX': 100,
    '三井海洋': 100, '日揮': 100, 'オリックス': 100, 'ヒューリック': 100,
    '伊藤忠': 100, '三菱商事': 300, 'NTT': 100,
    'KDDI': 100, '住友電工': 200, 'イオン': 300, '三菱ガス化学': 200,
    '純金信託': 10, 'ロボットETF': 1, '三菱HCキャピタル': 200, 'クオリプス': 300,
    'トリケミカル': 0,
    '(株)パワーエックス': 0
}

full_ticker_mapping = {
    '三菱重工': '7011.T', 'ビジネスエンジ': '4828.T', '三井住友FG': '8316.T', '三菱UFJ': '8306.T',
    '千葉銀行': '8331.T', '信越化学': '4063.T', '村田製作所': '6981.T', 'INPEX': '1605.T',
    '三井海洋': '6269.T', '日揮': '1963.T', 'オリックス': '8591.T', 'ヒューリック': '3003.T',
    '伊藤忠': '8001.T', '三菱商事': '8058.T', 'NTT': '9432.T',
    'KDDI': '9433.T', '住友電工': '5802.T', 'イオン': '8267.T', '三菱ガス化学': '4182.T',
    '純金信託': '1540.T', 'ロボットETF': '2522.T', '三菱HCキャピタル': '8593.T', 'クオリプス': '4894.T',
    'トリケミカル': '4369.T',
    '(株)パワーエックス': '485A.T'
}

sector_mapping = {
    '三菱重工': '製造業', 'ビジネスエンジ': '情報・通信業', '三井住友FG': '銀行業', '三菱UFJ': '銀行業',
    '千葉銀行': '銀行業', '信越化学': '化学', '村田製作所': '電気機器', 'INPEX': '鉱業',
    '三井海洋': 'サービス業', '日揮': '建設業', 'オリックス': 'その他金融業', 'ヒューリック': '不動産業',
    '伊藤忠': '卸売業', '三菱商事': '卸売業', 'NTT': '情報・通信業',
    'KDDI': '情報・通信業', '住友電工': '非鉄金属', 'イオン': '小売業', '三菱ガス化学': '化学',
    '純金信託': '商品ETF', 'ロボットETF': '国内ETF', '三菱HCキャピタル': 'その他金融業', 'クオリプス': '医薬品',
    'トリケミカル': '化学',
    '(株)パワーエックス': '製造業'
}

# ====== Alpha Vantage ラッパ ======

def av_daily(symbol: str, outputsize: str = "compact") -> pd.Series:
    """
    Alpha Vantage の日次終値を Series で返す（index: 日付, value: Close）
    """
    url = (
        "https://www.alphavantage.co/query"
        f"?function=TIME_SERIES_DAILY_ADJUSTED&symbol={symbol}"
        f"&outputsize={outputsize}&apikey={ALPHA_KEY}"
    )
    r = requests.get(url)
    data = r.json()
    ts = data.get("Time Series (Daily)", {})
    if not ts:
        return pd.Series(dtype=float)

    records = []
    for d, v in ts.items():
        records.append((pd.to_datetime(d), float(v["4. close"])))
    s = pd.Series(dict(records)).sort_index()
    return s

def av_dividend_rate(symbol: str) -> float:
    """
    ざっくり配当利回り用の年配当額を推定（簡易版）。
    Alpha Vantage の OVERVIEW を利用。
    """
    url = (
        "https://www.alphavantage.co/query"
        f"?function=OVERVIEW&symbol={symbol}&apikey={ALPHA_KEY}"
    )
    r = requests.get(url)
    data = r.json()
    # DividendPerShare を使う（なければ 0）
    try:
        return float(data.get("DividendPerShare", "0") or 0)
    except ValueError:
        return 0.0

# ====== 分析ロジック（yfinance版を Alpha Vantage に移植） ======

def build_df_latest() -> pd.DataFrame:
    # 2年分の期間
    end_date = date.today()
    start_date = end_date - timedelta(days=365 * 2)

    # ベンチマーク
    bench_series = av_daily(BENCHMARK_TICKER, outputsize="full")
    bench_series = bench_series[(bench_series.index.date >= start_date) & (bench_series.index.date <= end_date)]
    bench_returns = bench_series.pct_change().dropna()
    benchmark_var = bench_returns.var()

    if len(bench_returns) < 100:
        print(f"WARNING: benchmark data points = {len(bench_returns)}")

    results = []
    for name, qty in holdings.items():
        symbol = full_ticker_mapping[name]

        prices = av_daily(symbol, outputsize="full")
        prices = prices[(prices.index.date >= start_date) & (prices.index.date <= end_date)]
        if prices.empty:
            print(f"WARNING: no price data for {name} ({symbol})")
            continue

        ma5 = prices.rolling(window=5).mean().iloc[-1]
        ma25 = prices.rolling(window=25).mean().iloc[-1]
        momentum = (ma5 - ma25) / ma25 if ma25 != 0 else 0

        stock_returns = prices.pct_change().dropna()
        common_index = stock_returns.index.intersection(bench_returns.index)

        if len(common_index) < 50 or benchmark_var == 0:
            beta = 1.0
        else:
            cov = stock_returns.reindex(common_index).cov(bench_returns.reindex(common_index))
            beta = cov / benchmark_var

        current_price = prices.iloc[-1]
        eval_val = qty * current_price

        # 配当（Alpha Vantage OVERVIEW）
        div_rate = av_dividend_rate(symbol)
        div_amount = qty * div_rate
        yield_val = (div_rate / current_price) if current_price > 0 else 0

        score_integ = 50 + (momentum * 100 * beta)
        if beta < 0.8:
            score_integ += 10

        score_fund = max(0, min(100, round(((yield_val) * 1000) + (momentum * 200) + 50)))

        risk_char = 'ハイリスク' if beta > 1.2 else 'ディフェンシブ' if beta < 0.8 else '市場連動型'
        sig = ('High-Beta Momentum Buy' if momentum > 0 else 'High-Risk Sell') if beta > 1.2 else ('Standard Buy' if momentum > 0 else 'Standard Sell')

        results.append({
            'name': name,
            'sector': sector_mapping.get(name, 'Unknown'),
            'qty': qty,
            'price': current_price,
            'eval': eval_val,
            'momentum': momentum,
            'beta': beta,
            'score_integ': score_integ,
            'div_amount': div_amount,
            'yield': yield_val,
            'score_fund': score_fund,
            'risk_char': risk_char,
            'signal': sig,
        })

    df_latest = pd.DataFrame(results)

    # 加重平均Betaの安定化（クリップ）
    total_val = df_latest['eval'].sum()
    beta_clipped = df_latest['beta'].clip(lower=0, upper=2)
    weights = df_latest['eval'] / total_val
    weighted_beta = (beta_clipped * weights).sum()
    print(f"Weighted Beta (clipped): {weighted_beta:.3f}")

    return df_latest

# ====== Top7 抽出 & LINE 通知 ======

def pick_top7(df_latest: pd.DataFrame) -> pd.DataFrame:
    buy_df = df_latest[df_latest["signal"].str.contains("Buy")]
    top7 = buy_df.sort_values("score_integ", ascending=False).head(7)
    return top7

def notify_line(top7: pd.DataFrame):
    if top7.empty:
        message = "本日は Buy シグナルの銘柄がありませんでした。"
    else:
        lines = ["【今日の買い推奨 Top7】"]
        for _, r in top7.iterrows():
            line = (
                f"{r['name']} ({r['sector']})\n"
                f"  価格:{r['price']:.1f}  合体:{r['score_integ']:.1f}  "
                f"Beta:{r['beta']:.2f}  シグナル:{r['signal']}"
            )
            lines.append(line)
        message = "\n".join(lines)

    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_TOKEN}",
    }
    data = {
        "to": LINE_USER_ID,
        "messages": [{"type": "text", "text": message}],
    }
    r = requests.post(url, headers=headers, json=data)
    print("LINE status:", r.status_code, r.text)

def main():
    df_latest = build_df_latest()
    top7 = pick_top7(df_latest)
    notify_line(top7)

if __name__ == "__main__":
    main()

