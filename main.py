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
    data = {"to": LINE_USER_ID, "messages": [{"type": "text", "text": message[:4900]}]}
    requests.post(url, headers=headers, json=data)

def main():
    url = "https://www.rakuten-sec.co.jp/web/market/search/7011.html"
    r = requests.get(url)
    soup = BeautifulSoup(r.text, "html.parser")

    # 株価が含まれそうな部分を抽出（div, span, strong など）
    candidates = soup.find_all(["div", "span", "strong"], limit=50)

    text_dump = "【HTMLテスト】\n"
    for c in candidates:
        t = c.get_text(strip=True)
        if t:
            text_dump += t + "\n"

    notify_line(text_dump)

if __name__ == "__main__":
    main()


