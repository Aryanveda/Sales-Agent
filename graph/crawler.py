import os
import re
import time
import requests
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from collections import deque

BASE_URL    = "https://www.aaryanveda.in"
OUTPUT_DIR  = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "aaryanveda_knowledge.txt")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

SKIP_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg",
    ".pdf", ".zip", ".mp4", ".mp3", ".ico", ".woff",
    ".woff2", ".ttf", ".eot", ".css", ".js"
}

SKIP_PATTERNS = [
    "/cdn/", "/assets/", "/checkouts/", "/cart",
    "/account", "/orders", "/search?",
    "javascript:", "mailto:", "tel:",
    "/policies/refund", "/policies/privacy", "/policies/terms",
]

NOISE_STRINGS = [
    "Add to cart", "Sold out", "Out of stock",
    "Free Shipping", "Use Code", "Skip to content",
    "Loading...", "Continue shopping", "View Cart",
    "Log in", "Check out", "Shopping cart",
    "Your cart is empty", "Tax included",
    "Shipping calculated", "Subtotal",
    "Popular searches", "Province",
    "Zip/Postal Code",
]

SEED_URLS = [
    "/",
    "/pages/about-us-2",
    "/pages/our-story-2",
    "/pages/contact-us",
    "/collections/all",
    "/collections/face-wash-all",
    "/collections/spf",
    "/collections/face-care-face-cream",
    "/collections/face-care-face-serum",
    "/collections/professional-facial-kit",
    "/collections/face-care-facial-kit",
    "/collections/diy-kit",
    "/collections/bleach",
    "/collections/face-care-face-scrub",
    "/collections/face-massage",
    "/collections/face-pack",
    "/collections/aloevera-gel",
    "/collections/toner",
    "/collections/bathing-bar",
    "/collections/hair-removal-creams",
    "/collections/body-lotion-moisturizer",
    "/collections/hair-care-hair-oil",
    "/collections/hair-care-hair-serum",
    "/collections/hair-care-hair-shampoo",
    "/collections/glowelle-face-serum",
    "/collections/new-arrivals",
    "/collections/tanend-care",
    "/collections/glowelle-treatment-hair-serum",
    "/collections/face-hampers",
    "/collections/occasion-combos",
    "/collections/hair-hampers",
    "/collections/joyful-bundles",
    "/collections/delightful-festive-finds",
    "/collections/luxury-festive-finds",
    "/collections/dryness",
    "/collections/tanning",
    "/collections/pimple-acne",
    "/collections/wrinkle",
    "/collections/blemish",
    "/collections/dullness",
    "/collections/sun-protection",
]


def should_skip(url):
    parsed = urlparse(url)

    if parsed.netloc and parsed.netloc not in ("www.aaryanveda.in", "aaryanveda.in"):
        return True

    path = parsed.path.lower()
    ext  = os.path.splitext(path)[1]
    if ext in SKIP_EXTENSIONS:
        return True

    for pattern in SKIP_PATTERNS:
        if pattern in url:
            return True

    return False


def clean_text(soup):
    for tag in soup(["script", "style", "noscript", "iframe",
                     "header", "footer", "nav", "form", "svg"]):
        tag.decompose()

    text  = soup.get_text(separator="\n")
    lines = []
    for line in text.splitlines():
        line = line.strip()
        if not line or len(line) < 3:
            continue
        if any(noise in line for noise in NOISE_STRINGS):
            continue
        lines.append(line)

    seen    = set()
    deduped = []
    for line in lines:
        if line not in seen:
            seen.add(line)
            deduped.append(line)

    return "\n".join(deduped)


def get_title(soup):
    t = soup.find("title")
    if t:
        return t.get_text(strip=True)
    h = soup.find("h1")
    if h:
        return h.get_text(strip=True)
    return "Untitled"


def extract_links(soup, current_url):
    links = set()
    for tag in soup.find_all("a", href=True):
        href     = tag["href"].strip()
        full_url = urljoin(current_url, href)
        parsed   = urlparse(full_url)
        clean    = parsed._replace(fragment="", query="").geturl()
        if not should_skip(clean):
            links.add(clean)
    return links


def crawl():
    visited = set()
    queue   = deque(urljoin(BASE_URL, p) for p in SEED_URLS)
    results = []

    session = requests.Session()
    session.headers.update(HEADERS)

    print(f"Crawling {BASE_URL}")
    print(f"Output  : {OUTPUT_FILE}\n")

    while queue:
        url = queue.popleft()

        if url in visited or should_skip(url):
            continue
        visited.add(url)

        try:
            resp = session.get(url, timeout=12)
            if resp.status_code != 200:
                print(f"  [{resp.status_code}] {url}")
                continue

            if "text/html" not in resp.headers.get("content-type", ""):
                continue

            soup  = BeautifulSoup(resp.text, "html.parser")
            title = get_title(soup)
            text  = clean_text(soup)

            if len(text) < 80:
                print(f"  [thin]  {url}")
                continue

            results.append({"url": url, "title": title, "text": text})
            print(f"  [ok]  {title[:60]}")

            for link in extract_links(soup, url):
                if link not in visited:
                    queue.append(link)

            time.sleep(0.5)

        except Exception as e:
            print(f"  [err]  {url}  {e}")

    write_output(results)
    print(f"\nDone. {len(results)} pages -> {OUTPUT_FILE}")


def write_output(results):
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("AARYANVEDA WEBSITE KNOWLEDGE BASE\n")
        f.write(f"Source : {BASE_URL}\n")
        f.write(f"Pages  : {len(results)}\n")
        f.write("=" * 70 + "\n\n")

        for i, page in enumerate(results, 1):
            f.write(f"PAGE {i}\n")
            f.write(f"URL   : {page['url']}\n")
            f.write(f"TITLE : {page['title']}\n")
            f.write("-" * 70 + "\n")
            f.write(page["text"])
            f.write("\n\n" + "=" * 70 + "\n\n")

if __name__ == "__main__":
    crawl()