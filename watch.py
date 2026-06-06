import os
import json
import hashlib
import requests
import gspread
import difflib
import base64
from bs4 import BeautifulSoup
from datetime import datetime
from google.oauth2.service_account import Credentials

# =====================================
# ① 意味差分フィルタ
# =====================================

def semantic_filter(text):
    keywords = [
        "募集", "お知らせ", "講座", "イベント",
        "開催", "中止", "変更", "事業", "館報",
        "参加者", "申込", "受付", "図書"
    ]

    lines = []

    for line in text.split("\n"):
        line = line.strip()

        if len(line) < 6:
            continue
        if len(line) > 120:
            continue

        if any(k in line for k in keywords):
            if len(line) >= 10:
                lines.append(line)

    return "\n".join(dict.fromkeys(lines))


# =====================================
# ② テンプレ判定モデル
# =====================================

def detect_template_type(soup, url):

    wp_score = 0
    if soup.select(".wp-block-post-title"):
        wp_score += 3
    if soup.select(".entry-title"):
        wp_score += 2
    if "wp" in url:
        wp_score += 2

    static_score = 0
    if soup.find("table"):
        static_score += 1
    if soup.find("main") or soup.find("#content"):
        static_score += 1
    if ".htm" in url:
        static_score += 2

    civic_score = 0
    text = soup.get_text()
    civic_keywords = ["公民館", "講座", "館報", "自主事業"]
    civic_score += sum(1 for k in civic_keywords if k in text)

    if wp_score >= 3 or "wp" in url:
        return "wordpress"
    if civic_score >= 5:
        return "civic_dynamic"
    if static_score >= 2:
        return "static_html"

    return "unknown"


# =====================================
# 環境変数
# =====================================

CHANNEL_ACCESS_TOKEN = os.environ["CHANNEL_ACCESS_TOKEN"]
USER_ID = os.environ["USER_ID"]
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
SHEET_ID = os.environ["SHEET_ID"]

WP_URL = os.environ.get("WP_URL")
WP_USER = os.environ.get("WP_USER")
WP_APP_PASS = os.environ.get("WP_APP_PASS")


# =====================================
# 監視対象
# =====================================

URLS = [
    "https://www.sagamihara-kouminkan.jp/oosawa-k/",
    "https://www.sagamihara-kouminkan.jp/kamimizo-k/",
    "https://www.sagamihara-kouminkan.jp/hashimoto-k/",
    "https://www.sagamihara-kouminkan.jp/aihara-k/aihara/right.html",
    "https://www.sagamihara-kouminkan.jp/oyama-k/",
    "https://www.sagamihara-kouminkan.jp/onominami-k/",
    "https://www.sagamihara-kouminkan.jp/araiso-k/",
    "https://www.sagamihara-kouminkan.jp/asamizo-k/",
    "https://www.sagamihara-kouminkan.jp/tana-k/right.htm",
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
            {"type": "text", "text": message[:5000]}
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
# WordPress投稿（下書き）
# =====================================

def post_to_wordpress(title, content):

    WP_URL = os.environ["WP_URL"]
    WP_USER = os.environ["WP_USER"]
    WP_APP_PASS = os.environ["WP_APP_PASS"]

    token = base64.b64encode(
        f"{WP_USER}:{WP_APP_PASS}".encode()
    ).decode()

    headers = {
        "Authorization": f"Basic {token}",
        "Content-Type": "application/json"
    }

    payload = {
        "title": title,
        "content": content,
        "status": "draft"
    }

    r = requests.post(
        WP_URL + "/wp-json/wp/v2/posts",
        headers=headers,
        json=payload,
        timeout=30
    )

    print("WP:", r.status_code, r.text)
    print("===== WP DEBUG =====")
    print("URL:", r.url)
    print("STATUS:", r.status_code)
    print("RESPONSE:", r.text)
    print("====================")

    return r.status_code in [200, 201]

# =====================================
# HTML解析
# =====================================

def extract_data(html, url):

    soup = BeautifulSoup(html, "lxml")

    for tag in ["script", "style", "noscript"]:
        for t in soup.find_all(tag):
            t.decompose()

    title = soup.title.text.strip() if soup.title else ""
    template_type = detect_template_type(soup, url)

    wp_selectors = [
        "article h1","article h2","article h3",
        ".entry-title",".post-title",
        ".wp-block-post-title",
        ".elementor-post__title",
        ".blog-title",".news-title"
    ]

    # =========================
    # WP
    # =========================
    if template_type == "wordpress":

        wp_posts = []
        for selector in wp_selectors:
            for tag in soup.select(selector):
                txt = tag.get_text(" ", strip=True)
                if 5 <= len(txt) <= 100:
                    wp_posts.append(txt)

        text = "\n".join(dict.fromkeys(wp_posts)[:50])
        text = semantic_filter(text)

        pdfs = list(set(
            a.get("href")
            for a in soup.select('a[href$=".pdf"]')
            if a.get("href")
        ))

        return title, text, pdfs

    # =========================
    # 館別
    # =========================
    if "hashimoto-k" in url:
        text = "\n".join(
            a.get_text(" ", strip=True)
            for a in soup.select("a")
            if len(a.get_text(strip=True)) >= 5
        )
        return title, semantic_filter(text), []

    if "aihara-k" in url:
        tab1 = soup.find("div", id="tab1")
        if tab1:
            text = "\n".join(
                a.get_text(" ", strip=True)
                for a in tab1.select("a")
            )
            return title, semantic_filter(text), []

    if "tana-k" in url:
        text = soup.get_text("\n", strip=True)
        return title, semantic_filter(text)[:3000], []

    # =========================
    # 汎用HTML
    # =========================
    target = soup.select_one("main") or soup.select_one("article") or soup

    keywords = ["募集","お知らせ","新着","中止","開催","講座","イベント","事業","館報","図書室"]
    date_keywords = ["令和","R9","R8","R7","2027","2026","2025"]

    lines = []
    for line in target.get_text("\n").split("\n"):
        line = line.strip()
        if 8 <= len(line) <= 100:
            if any(k in line for k in keywords + date_keywords):
                lines.append(line)

    return title, semantic_filter("\n".join(lines)), []


# =====================================
# ハッシュ
# =====================================

def make_hash(title, text, pdfs):
    src = json.dumps({"text": text, "pdfs": pdfs}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(src.encode()).hexdigest()


# =====================================
# Sheet
# =====================================

def get_old_data(sheet, url):
    for row in reversed(sheet.get_all_values()):
        if len(row) >= 6 and row[2] == url:
            return {"hash": row[3], "text": row[5]}
    return None


def save_hash(sheet, url, hash_value, memo, text):
    now = datetime.now()
    sheet.append_row([
        now.strftime("%m/%d"),
        now.strftime("%H:%M:%S"),
        url,
        hash_value,
        memo,
        text[:5000]
    ])


# =====================================
# メイン
# =====================================

def run():

    sheet = get_sheet()
    notifications = []

    for url in URLS:

        try:
            r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
            r.encoding = r.apparent_encoding

            title, text, pdfs = extract_data(r.text, url)

            # ノイズ防止（ここが重要）
            if len(text) < 50:
                continue

            new_hash = make_hash(title, text, pdfs)
            old = get_old_data(sheet, url)

            old_hash = old["hash"] if old else None
            old_text = old["text"] if old else ""

            if old_hash == new_hash:
                continue

            if old_hash is None:
                save_hash(sheet, url, new_hash, "初回登録", text)
                continue

            diff = "\n".join(
                difflib.unified_diff(
                    old_text.splitlines(),
                    text.splitlines(),
                    fromfile="before",
                    tofile="after"
                )
            )

            if not diff.strip():
                continue

            save_hash(sheet, url, new_hash, "更新検知", text)

            notifications.append(
                f"{title}\n{url}\n\n{diff[:3000]}"
            )

        except Exception as e:
            notifications.append(f"ERROR\n{url}\n{e}")

    if notifications:
        msg = "【公民館監視】\n\n" + "\n\n".join(notifications)
        send_line(msg)

        for n in notifications:
            lines = n.split("\n")
            title = lines[0] if lines else "公民館更新"
            post_to_wordpress(title[:100], n[:4000])

def test_wordpress_post():
    title = "テスト投稿（監視システム）"
    content = "テスト"

    result = post_to_wordpress(title, content)

    return result

    result = post_to_wordpress(title, content)

    print("テスト結果:", result)
    print("WP_URL:", WP_URL)
    print("USER:", WP_USER)
    print("PASS長:", len(WP_APP_PASS))
    print("WP STATUS:", r.status_code)
    print("WP RESPONSE:", r.text)

# =====================================
# 実行
# =====================================

if __name__ == "__main__":
    test_wordpress_post()
    run()
