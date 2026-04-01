import os
import requests
from bs4 import BeautifulSoup

LINE_TOKEN = os.getenv("LINE_TOKEN")
LINE_USER_ID = os.getenv("LINE_USER_ID")

def notify_line(message: str):
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_TOKEN}",
    }
    data = {"to": LINE_USER_ID, "messages": [{"type": "text", "text": message}]}
    requests.post(url, headers=headers, json=data)

def get_price_rakuten(ticker):
    url = f"https://www.rakuten-sec.co.jp/web/market/search/{ticker}.html"
    r = requests.get(url)
    soup = BeautifulSoup(r.text, "html.parser")

    tag1 = soup.select_one(".md-stockBoard_price")  # 旧UI
    tag2 = soup.select_one(".stockPrice")           # 新UI

    result = (
        f"【楽天証券テスト】\n"
        f"銘柄: {ticker}\n"
        f"tag1: {tag1.text.strip() if tag1 else 'None'}\n"
        f"tag2: {tag2.text.strip() if tag2 else 'None'}"
    )

    notify_line(result)

def main():
    get_price_rakuten("7011")  # 三菱重工

if __name__ == "__main__":
    main()


