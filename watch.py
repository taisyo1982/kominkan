import os
import json
import hashlib
import requests
import gspread

from bs4 import BeautifulSoup
from datetime import datetime
from google.oauth2.service_account import Credentials

# =====================================
# 環境変数
# =====================================

CHANNEL_ACCESS_TOKEN = os.environ["CHANNEL_ACCESS_TOKEN"]
USER_ID = os.environ["USER_ID"]
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
SHEET_ID = os.environ["SHEET_ID"]

# =====================================
# 監視対象
# =====================================

URLS = [
    "https://www.sagamihara-kouminkan.jp/oosawa-k/",
    "https://www.sagamihara-kouminkan.jp/kamimizo-k/",
    "https://www.sagamihara-kouminkan.jp/hashimoto-k/",
    "https://www.sagamihara-kouminkan.jp/aihara-k/",
    "https://www.sagamihara-kouminkan.jp/oyama-k/",
    "https://www.sagamihara-kouminkan.jp/onominami-k/",
    "https://www.sagamihara-kouminkan.jp/araiso-k/",
    "https://www.sagamihara-kouminkan.jp/asamizo-k/",
    "https://www.sagamihara-kouminkan.jp/tana-k/",
    "https://www.sagamihara-kouminkan.jp/onokita-k/",
    "https://www.sagamihara-kouminkan.jp/ononaka-k/",
    "https://www.sagamihara-kouminkan.jp/hoshigaoka-wp/",
    "https://www.sagamihara-kouminkan.jp/seishin-k/",
    "https://www.sagamihara-kouminkan.jp/chuuou-k/",
    "https://www.sagamihara-kouminkan.jp/sagamidai-k/",
    "https://www.sagamihara-kouminkan.jp/soubudai-k/",
    "https://www.sagamihara-kouminkan.jp/tourin-k/",
    "https://www.sagamihara-kouminkan.jp/yokoyama-wp/",
    "https://www.sagamihara-kouminkan.jp/hikarigaoka-k/",
    "https://www.sagamihara-kouminkan.jp/oonuma-k/",
    "https://www.sagamihara-kouminkan.jp/kamitsuruma-k/",
    "https://www.sagamihara-kouminkan.jp/oonodai-k/",
    "https://www.sagamihara-kouminkan.jp/youkoudai-k/",
    "https://www.sagamihara-kouminkan.jp/shiroyama-k/",
    "https://www.sagamihara-kouminkan.jp/t-chuuou-k/",
    "https://www.sagamihara-kouminkan.jp/sagamiko-k/",
    "https://www.sagamihara-kouminkan.jp/f-chuuou-wp/"
]

# =====================================
# Sheets接続
# =====================================

def get_sheet():

    creds = Credentials.from_service_account_info(
        json.loads(GOOGLE_SERVICE_ACCOUNT_JSON),
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )

    gc = gspread.authorize(creds)

    return gc.open_by_key(SHEET_ID).sheet1


# =====================================
# LINE送信
# =====================================

def send_line(message):

    headers = {
        "Authorization": f"Bearer {CHANNEL_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    payload = {
        "to": USER_ID,
        "messages": [
            {
                "type": "text",
                "text": message[:5000]
            }
        ]
    }

    r = requests.post(
        "https://api.line.me/v2/bot/message/push",
        headers=headers,
        json=payload,
        timeout=30
    )

    print("LINE:", r.status_code)


# =====================================
# HTML解析
# =====================================

def extract_data(html):

    soup = BeautifulSoup(html, "lxml")

    # 不要タグ削除
    for tag in ["script", "style", "noscript"]:
        for t in soup.find_all(tag):
            t.decompose()

    title = soup.title.text.strip() if soup.title else ""

    # =====================================
    # PDF監視
    # =====================================

    pdfs = sorted(
        set(
            a.get("href")
            for a in soup.select('a[href$=".pdf"]')
            if a.get("href")
        )
    )

    # =====================================
    # WordPress投稿タイトル監視
    # =====================================

    wp_posts = []

    wp_selectors = [
        "article h1",
        "article h2",
        "article h3",
        ".entry-title",
        ".post-title",
        ".wp-block-post-title",
        ".elementor-post__title",
        ".blog-title",
        ".news-title"
    ]

    for selector in wp_selectors:

        for tag in soup.select(selector):

            txt = tag.get_text(" ", strip=True)

            if len(txt) < 5:
                continue

            if len(txt) > 100:
                continue

            wp_posts.append(txt)

    wp_posts = list(dict.fromkeys(wp_posts))

    # 投稿タイトルが複数取れたらWPと判定
    if len(wp_posts) >= 3:

        text = "\n".join(wp_posts[:50])

        return title, text, pdfs

    # =====================================
    # 静的HTML監視
    # =====================================

    target = (
        soup.select_one("main")
        or soup.select_one("article")
        or soup.select_one("#content")
        or soup.select_one(".content")
        or soup
    )

    keywords = [
        "募集",
        "お知らせ",
        "新着",
        "中止",
        "開催",
        "講座",
        "イベント",
        "事業",
        "館報",
        "図書室"
    ]

    date_keywords = [
        "令和",
        "R9",
        "R8",
        "R7",
        "2027",
        "2026",
        "2025"
    ]

    important = []

    for line in target.get_text("\n").split("\n"):

        line = line.strip()

        if not line:
            continue

        # 短すぎる行除外
        if len(line) < 8:
            continue

        # 長すぎる行除外
        if len(line) > 100:
            continue

        # キーワード行
        if any(k in line for k in keywords):
            important.append(line)
            continue

        # 日付行
        if any(k in line for k in date_keywords):
            important.append(line)
            continue

    important = list(dict.fromkeys(important))

    text = "\n".join(important[:100])

    return title, text, pdfs


# =====================================
# ハッシュ生成
# =====================================

def make_hash(title, text, pdfs):

    src = json.dumps(
        {
            "text": text,
            "pdfs": pdfs
        },
        ensure_ascii=False,
        sort_keys=True
    )

    return hashlib.sha256(
        src.encode("utf-8")
    ).hexdigest()


# =====================================
# 前回ハッシュ取得
# =====================================

def get_old_hash(sheet, url):

    values = sheet.get_all_values()

    for row in reversed(values):
        if len(row) >= 5 and row[1] == url:

            return {
                "hash": row[2],
                "text": row[4]
            }

    return None


# =====================================
# 保存
# =====================================

def save_hash(sheet, url, hash_value, memo, text):

    sheet.append_row([
        datetime.now().isoformat(),
        url,
        hash_value,
        memo,
        text[:5000]
    ])


# =====================================
# メイン
# =====================================

def run():

    print("=" * 50)
    print("監視開始")
    print("=" * 50)

    sheet = get_sheet()

    notifications = []

    for url in URLS:

        try:

            print("取得開始:", url)

            r = requests.get(
                url,
                timeout=20,
                headers={
                    "User-Agent": "Mozilla/5.0"
                }
            )

            r.encoding = r.apparent_encoding

            print("HTTP:", r.status_code)

            title, text, pdfs = extract_data(r.text)

            print("TITLE:", title)
            print("TEXT SAMPLE:")
            print(text[:500])
            print("PDF:", pdfs[:10])

            new_hash = make_hash(
                title,
                text,
                pdfs
            )

            old_hash = get_old_hash(
                sheet,
                url
            )

            print("OLD:", old_hash)
            print("NEW:", new_hash)

            if old_hash == new_hash:
                print("変更なし")
                continue

            if old_hash is None:
                status = "初回登録"
            else:
                status = "更新検知"

            save_hash(
                sheet,
                url,
                new_hash,
                status,
                text
            )
            old_data = get_old_data(sheet, url)

            old_text = ""

            if old_data:
                old_text = old_data["text"]

            message = (
                f"{status}\n"
                f"{title}\n"
                f"{url}\n\n"
                f"検知内容:\n"
                f"{text[:1000]}"
            )

            notifications.append(message)



        except Exception as e:

            error_msg = f"ERROR\n{url}\n{str(e)}"

            print(error_msg)

            notifications.append(error_msg)

    if notifications:

        print("通知件数:", len(notifications))
        print("通知文字数:", len(
            "【公民館監視】\n\n" +
            "\n\n".join(notifications)
        ))
        
        send_line(
            "【公民館監視】\n\n" +
            "\n\n".join(notifications)
        )

    print("監視終了")


# =====================================
# 実行
# =====================================

if __name__ == "__main__":
    run()
