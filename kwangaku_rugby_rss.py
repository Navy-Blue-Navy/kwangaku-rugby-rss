import os
import re
import time
import hashlib
import requests
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
from email.utils import format_datetime, parsedate_to_datetime
from urllib.parse import urljoin


# ============================================================
# 設定
# ============================================================

BASE_URL = "https://www.kwangaku-sports.com"
START_URL = "https://www.kwangaku-sports.com/club/rugby/"

OUTPUT_FILE = "kwangaku_rugby.xml"

FEED_TITLE = "関学スポーツ ラグビー部"
FEED_LINK = START_URL
FEED_DESCRIPTION = "関学スポーツ「ラグビー部」の独自RSS"

JST = timezone(timedelta(hours=9))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/154.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,*/*;q=0.8"
    ),
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}


# ============================================================
# HTML取得
# ============================================================

def fetch_html(url, retries=3):
    last_error = None

    for attempt in range(1, retries + 1):
        try:
            print(f"取得 {attempt}/{retries}: {url}")

            response = requests.get(
                url,
                headers=HEADERS,
                timeout=30,
            )

            print(
                f"HTTP: {response.status_code} / "
                f"{len(response.content)} bytes"
            )

            response.raise_for_status()

            return response.text

        except Exception as e:
            last_error = e

            print(f"取得失敗: {repr(e)}")

            if attempt < retries:
                print("10秒待って再試行します")
                time.sleep(10)

    raise RuntimeError(
        f"{url} の取得に{retries}回とも失敗しました: "
        f"{last_error}"
    )


# ============================================================
# 一覧ページから記事抽出
# ============================================================

def parse_list_page(html):
    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    articles = []
    seen = set()

    date_pattern = re.compile(
        r"\b(20\d{2})-(\d{2})-(\d{2})\b"
    )

    for a in soup.find_all(
        "a",
        href=True,
    ):
        text = a.get_text(
            " ",
            strip=True,
        )

        if not text:
            continue

        match = date_pattern.search(text)

        if not match:
            continue

        # ラグビー部の記事だけを対象
        if "ラグビー部" not in text:
            continue

        year = int(match.group(1))
        month = int(match.group(2))
        day = int(match.group(3))

        href = urljoin(
            BASE_URL,
            a.get("href"),
        )

        # ラグビー部一覧ページ自体などを除外
        if "/club/rugby" in href:
            continue

        if href in seen:
            continue

        seen.add(href)

        # 「ラグビー部 YYYY-MM-DD」の部分を除去してタイトル化
        title = re.sub(
            r"^\s*ラグビー部\s*"
            r"20\d{2}-\d{2}-\d{2}\s*",
            "",
            text,
        ).strip()

        if not title:
            continue

        try:
            dt = datetime(
                year,
                month,
                day,
                0,
                0,
                0,
                tzinfo=JST,
            )

        except ValueError:
            continue

        articles.append(
            {
                "title": title,
                "link": href,
                "datetime": dt,
                "pubDate": format_datetime(dt),
                "description": "",
                "guid": hashlib.sha256(
                    href.encode("utf-8")
                ).hexdigest(),
            }
        )

    return articles


# ============================================================
# 次ページURL検出
# ============================================================

def find_next_page(html, current_url):
    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    current_page = 1

    match = re.search(
        r"/page/(\d+)/?$",
        current_url,
    )

    if match:
        current_page = int(
            match.group(1)
        )

    expected_next = current_page + 1

    expected_path = (
        f"/club/rugby/page/"
        f"{expected_next}/"
    )

    for a in soup.find_all(
        "a",
        href=True,
    ):
        href = urljoin(
            BASE_URL,
            a.get("href"),
        )

        if expected_path in href:
            return href

    return None


# ============================================================
# 全ページ取得
# ============================================================

def fetch_all_articles():
    all_articles = {}
    visited_pages = set()

    url = START_URL
    page_number = 1

    while url:
        if url in visited_pages:
            print(
                "同じページURLを再検出したため終了します"
            )
            break

        visited_pages.add(url)

        print()
        print(
            f"===== 一覧ページ {page_number} ====="
        )

        html = fetch_html(url)

        articles = parse_list_page(
            html
        )

        print(
            f"このページの記事数: "
            f"{len(articles)}"
        )

        for article in articles:
            all_articles[
                article["link"]
            ] = article

        next_url = find_next_page(
            html,
            url,
        )

        if not next_url:
            break

        url = next_url
        page_number += 1

        time.sleep(1)

    articles = list(
        all_articles.values()
    )

    articles.sort(
        key=lambda x: x["datetime"],
        reverse=True,
    )

    print()
    print(
        f"サイトから取得した記事総数: "
        f"{len(articles)}"
    )

    return articles


# ============================================================
# 既存RSS読み込み
# ============================================================

def load_existing_items():
    existing = {}

    if not os.path.exists(
        OUTPUT_FILE
    ):
        return existing

    try:
        tree = ET.parse(
            OUTPUT_FILE
        )

        root = tree.getroot()

        for item in root.findall(
            "./channel/item"
        ):
            link = (
                item.findtext(
                    "link",
                    "",
                )
                or ""
            ).strip()

            if not link:
                continue

            title = (
                item.findtext(
                    "title",
                    "",
                )
                or ""
            ).strip()

            pub_date = (
                item.findtext(
                    "pubDate",
                    "",
                )
                or ""
            ).strip()

            description = (
                item.findtext(
                    "description",
                    "",
                )
                or ""
            ).strip()

            guid = (
                item.findtext(
                    "guid",
                    "",
                )
                or ""
            ).strip()

            existing[link] = {
                "title": title,
                "link": link,
                "pubDate": pub_date,
                "description": description,
                "guid": (
                    guid
                    or hashlib.sha256(
                        link.encode("utf-8")
                    ).hexdigest()
                ),
            }

    except Exception as e:
        print(
            "既存RSSの読み込みに失敗: "
            f"{repr(e)}"
        )

    return existing


# ============================================================
# RSS生成
# ============================================================

def build_rss(
    current_articles,
    existing_items,
):
    merged = {}

    # 既存RSSの記事を保持
    for link, item in (
        existing_items.items()
    ):
        merged[link] = item

    # 現在サイトから取得した記事を追加・更新
    for article in current_articles:
        merged[
            article["link"]
        ] = {
            "title": article["title"],
            "link": article["link"],
            "pubDate": article["pubDate"],
            "description": (
                article["description"]
            ),
            "guid": article["guid"],
        }

    def sort_key(item):
        try:
            dt = parsedate_to_datetime(
                item["pubDate"]
            )

            return dt.timestamp()

        except Exception:
            return 0

    sorted_items = sorted(
        merged.values(),
        key=sort_key,
        reverse=True,
    )

    rss = ET.Element(
        "rss",
        {
            "version": "2.0",
        },
    )

    channel = ET.SubElement(
        rss,
        "channel",
    )

    ET.SubElement(
        channel,
        "title",
    ).text = FEED_TITLE

    ET.SubElement(
        channel,
        "link",
    ).text = FEED_LINK

    ET.SubElement(
        channel,
        "description",
    ).text = FEED_DESCRIPTION

    ET.SubElement(
        channel,
        "language",
    ).text = "ja"

    ET.SubElement(
        channel,
        "lastBuildDate",
    ).text = format_datetime(
        datetime.now(JST)
    )

    for article in sorted_items:
        item = ET.SubElement(
            channel,
            "item",
        )

        ET.SubElement(
            item,
            "title",
        ).text = article["title"]

        ET.SubElement(
            item,
            "link",
        ).text = article["link"]

        ET.SubElement(
            item,
            "description",
        ).text = article["description"]

        ET.SubElement(
            item,
            "pubDate",
        ).text = article["pubDate"]

        guid = ET.SubElement(
            item,
            "guid",
            {
                "isPermaLink": "false",
            },
        )

        guid.text = article["guid"]

    tree = ET.ElementTree(rss)

    ET.indent(
        tree,
        space="  ",
    )

    tree.write(
        OUTPUT_FILE,
        encoding="utf-8",
        xml_declaration=True,
    )

    return len(sorted_items)


# ============================================================
# メイン
# ============================================================

def main():
    print("=" * 70)
    print(
        "関学スポーツ ラグビー部 RSS"
    )
    print("=" * 70)

    existing_items = (
        load_existing_items()
    )

    print(
        f"既存RSS件数: "
        f"{len(existing_items)}"
    )

    try:
        current_articles = (
            fetch_all_articles()
        )

        if not current_articles:
            raise RuntimeError(
                "記事を1件も取得できませんでした"
            )

    except Exception as e:
        print()
        print(
            f"エラー: {repr(e)}"
        )
        print(
            "RSSは更新せず、"
            "既存ファイルを保持します"
        )
        raise

    print()
    print("最新30件:")

    for i, article in enumerate(
        current_articles[:30],
        1,
    ):
        dt = article[
            "datetime"
        ].astimezone(JST)

        print(
            f"{i:2d}. "
            f"{dt.strftime('%Y-%m-%d')} "
            f"{article['title']}"
        )

        print(
            f"    {article['link']}"
        )

    existing_links = set(
        existing_items.keys()
    )

    new_articles = [
        article
        for article in current_articles
        if article["link"]
        not in existing_links
    ]

    print()
    print(
        f"新規記事数: "
        f"{len(new_articles)}"
    )

    total = build_rss(
        current_articles,
        existing_items,
    )

    print(
        f"保存完了: {OUTPUT_FILE}"
    )

    print(
        f"RSS総件数: {total}"
    )


if __name__ == "__main__":
    main()