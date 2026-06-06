import os
import json
import time
import hashlib
import requests
import gspread
import difflib
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
from google.oauth2.service_account import Credentials

# =====================================
# JST
# =====================================

JST = timezone(timedelta(hours=9))

# =====================================
# config
# =====================================

CHANNEL_ACCESS_TOKEN = os.environ["CHANNEL_ACCESS_TOKEN"]
USER_ID = os.environ["USER_ID"]
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
SHEET_ID = os.environ["SHEET_ID"]

WP_URL = os.environ.get("WP_URL")
WP_USER = os.environ.get("WP_USER")
WP_APP_PASS = os.environ.get("WP_APP_PASS")

CACHE_FILE = "/tmp/watcher_cache.json"

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
# cache
# =====================================

def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_cache(cache):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

# =====================================
# fetch
# =====================================

def fetch(url):
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get(url, timeout=20, headers=headers)

    if r.status_code != 200:
        raise Exception(f"HTTP {r.status_code}")

    r.encoding = r.apparent_encoding
    return r.text

# =====================================
# semantic filter
# =====================================

def semantic_filter(text):
    keywords = [
        "募集", "お知らせ", "講座", "イベント",
        "開催", "中止", "変更", "事業", "館報",
        "参加者", "申込", "受付", "図書"
    ]

    result = []
    for line in text.split("\n"):
        line = line.strip()

        if len(line) < 4 or len(line) > 120:
            continue

        if any(k in line for k in keywords):
            result.append(line)

    return "\n".join(list(dict.fromkeys(result)))

# =====================================
# template detection
# =====================================

def detect_template_type(soup, url):
    wp_score = 0
    if soup.select(".wp-block-post-title"):
        wp_score += 3
    if "wp" in url:
        wp_score += 2

    civic_score = sum(1 for k in ["公民館","講座","館報"] if k in soup.get_text())

    if wp_score >= 3:
        return "wordpress"
    if civic_score >= 5:
        return "civic"
    return "static"

# =====================================
# hash
# =====================================

def make_hash(title, text, pdfs):
    norm = {
        "title": title.strip(),
        "text": sorted(text.splitlines()),
        "pdfs": sorted(pdfs)
    }
    raw = json.dumps(norm, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()

# =====================================
# similarity
# =====================================

def similarity(a, b):
    sa, sb = set(a.split()), set(b.split())
    if not sa or not sb:
        return 0
    return len(sa & sb) / len(sa | sb)

# =====================================
# sheets
# =====================================

def get_sheet():
    creds = Credentials.from_service_account_info(
        json.loads(GOOGLE_SERVICE_ACCOUNT_JSON),
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    gc = gspread.authorize(creds)
    return gc.open_by_key(SHEET_ID).sheet1

def save_sheet(sheet, url, hash_value, memo, text):
    now = datetime.now(JST)

    sheet.append_row([
        now.strftime("%Y-%m-%d"),
        now.strftime("%H:%M:%S"),
        url,
        hash_value,
        memo,
        text[:5000]
    ])

# =====================================
# LINE
# =====================================

def send_line(msg):
    payload = {
        "to": USER_ID,
        "messages": [{"type": "text", "text": msg[:5000]}]
    }

    headers = {
        "Authorization": f"Bearer {CHANNEL_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    requests.post(
        "https://api.line.me/v2/bot/message/push",
        headers=headers,
        json=payload,
        timeout=30
    )

# =====================================
# WP
# =====================================

def post_wp(title, content):
    token = base64.b64encode(
        f"{WP_USER}:{WP_APP_PASS}".encode()
    ).decode()

    headers = {
        "Authorization": f"Basic {token}",
        "Content-Type": "application/json"
    }

    data = {
        "title": title,
        "content": f"<pre style='white-space:pre-wrap'>{content}</pre>",
        "status": "draft"
    }

    r = requests.post(
        WP_URL + "/wp-json/wp/v2/posts",
        headers=headers,
        json=data,
        timeout=30
    )

    return r.status_code in [200, 201]

# =====================================
# parse
# =====================================

def parse(html, url):
    soup = BeautifulSoup(html, "lxml")

    for t in soup(["script","style","noscript"]):
        t.decompose()

    title = soup.title.text.strip() if soup.title else ""
    template = detect_template_type(soup, url)

    if template == "wordpress":
        items = []
        for el in soup.select("article h1, article h2, .entry-title"):
            t = el.get_text(strip=True)
            if 5 <= len(t) <= 100:
                items.append(t)

        text = semantic_filter("\n".join(items))
        pdfs = [a["href"] for a in soup.select('a[href$=".pdf"]') if a.get("href")]

        return title, text, list(set(pdfs))

    body = soup.get_text("\n")
    lines = []

    for l in body.split("\n"):
        l = l.strip()
        if 8 <= len(l) <= 100:
            if any(k in l for k in ["募集","講座","イベント","開催","館報"]):
                lines.append(l)

    return title, semantic_filter("\n".join(lines)), []

# =====================================
# main
# =====================================

def run():
    cache = load_cache()
    sheet = get_sheet()

    notifications = []

    for url in URLS:
        try:
            html = fetch(url)
            title, text, pdfs = parse(html, url)

            if len(text) < 50:
                continue

            new_hash = make_hash(title, text, pdfs)
            old = cache.get(url)

            if old and old.get("hash") == new_hash:
                continue

            if old and similarity(old.get("text", ""), text) > 0.92:
                continue

            diff = ""
            if old:
                diff = "\n".join(difflib.unified_diff(
                    old["text"].splitlines(),
                    text.splitlines()
                ))

            cache[url] = {"hash": new_hash, "text": text}

            save_sheet(sheet, url, new_hash, "update", text)

            notifications.append(
                f"{title}\n{url}\n\n{diff[:2000]}"
            )

        except Exception as e:
            notifications.append(f"ERROR\n{url}\n{e}")

    if notifications:
        msg = "【公民館監視】\n\n" + "\n\n".join(notifications)
        send_line(msg)

        for n in notifications:
            lines = n.split("\n")
            title = lines[0] if lines else "update"
            post_wp(title[:100], n[:3000])

    save_cache(cache)

# =====================================
# entry
# =====================================

if __name__ == "__main__":
    run()
