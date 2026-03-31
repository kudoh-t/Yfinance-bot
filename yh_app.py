import requests
import csv
import io
import os

# ====== 1. Yahooポートフォリオ CSV取得 ======
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


# ====== 2. LINE Token ======
LINE_ACCESS_TOKEN = os.getenv("LINE_ACCESS_TOKEN")
LINE_USER_ID = os.getenv("LINE_USER_ID")


# ====== 3. あなたの計算ロジック ======
def get_ma_deviation(code):
    return -0.03

def get_combo_score(code):
    return 70

def get_beta(code):
    return 1.2

def get_risk_contrib(code):
    return 0.05


# ====== 4. 反転確率 ======
def calc_reversal_prob(ma_dev, combo_score, beta):
    ma_norm = max(0.0, 1 - min(abs(ma_dev), 0.12) / 0.12)
    score_norm = max(0.0, min((combo_score - 40) / 40, 1.0))
    beta_norm = max(0.0, min(beta / 1.5, 1.0))
    p = 0.40 * ma_norm + 0.30 * score_norm + 0.20 * 1.0 + 0.10 * beta_norm
    return p * 100


# ====== 5. 買い増し額 ======
def allocate_buy_amount(stocks, total_capital):
    for s in stocks:
        s["weight"] = s["rev_prob"] * s["risk_contrib"]
    total_w = sum(s["weight"] for s in stocks)
    for s in stocks:
        s["buy_amount"] = 0 if total_w == 0 else total_capital * s["weight"] / total_w
    return stocks


# ====== 6. LINE通知 ======
def send_to_line(message):
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_ACCESS_TOKEN}",
    }
    data = {
        "to": LINE_USER_ID,
        "messages": [{"type": "text", "text": message}],
    }
    requests.post(url, headers=headers, json=data)


# ====== 7. メッセージ整形 ======
def format_line_message(stocks):
    if not stocks:
        return "【今日の反転候補TOP5】\nデータが取得できませんでした。"

    lines = ["【今日の反転候補TOP5】"]
    top5 = sorted(stocks, key=lambda x: x["rev_prob"], reverse=True)[:5]
    for s in top5:
        lines.append(
            f"{s['name']} ({s['code']}): "
            f"反転確率 {s['rev_prob']:.1f}%, "
            f"買い増し額 約{int(s['buy_amount']):,}円"
        )
    return "\n".join(lines)


# ====== 8. メイン ======
def main():
    stocks = fetch_portfolio_csv()
    print("取得銘柄数:", len(stocks))

    for s in stocks:
        s["ma_dev"] = get_ma_deviation(s["code"])
        s["combo_score"] = get_combo_score(s["code"])
        s["beta"] = get_beta(s["code"])
        s["risk_contrib"] = get_risk_contrib(s["code"])
        s["rev_prob"] = calc_reversal_prob(
            s["ma_dev"], s["combo_score"], s["beta"]
        )

    allocate_buy_amount(stocks, total_capital=300000)

    msg = format_line_message(stocks)
    send_to_line(msg)


if __name__ == "__main__":
    main()
