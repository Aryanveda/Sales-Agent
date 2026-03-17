import os
import time
import requests
from bs4 import BeautifulSoup
from collections import OrderedDict


# ================= CONFIG =================

OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "knowledge.txt")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
    "Accept-Language": "en-IN,en;q=0.9"
}


AMAZON_URLS = list(set([
    "https://www.amazon.in/dp/B0CPFDMGXD?th=1",
    "https://www.amazon.in/dp/B0CPYHLGF7",
    "https://www.amazon.in/dp/B078N1BWD2?th=1",
    "https://www.amazon.in/dp/B0CRHS8RX5",
    "https://www.amazon.in/dp/B0DF5H7GXV?th=1",
    "https://www.amazon.in/dp/B0DQKXLS1N",
    "https://www.amazon.in/dp/B0DFM8FZHQ",
    "https://www.amazon.in/dp/B0DDXJZV59",
    "https://www.amazon.in/dp/B0DDTWVY75",
    "https://www.amazon.in/dp/B0F3DD85X9",
    "https://www.amazon.in/dp/B0G937TZVM",
    "https://www.amazon.in/dp/B0DJT62L1L",
    "https://www.amazon.in/dp/B0FHDR6963",
    "https://www.amazon.in/dp/B0DKXQ6X4Z",
    "https://www.amazon.in/dp/B0BYSWLM4D",
    "https://www.amazon.in/dp/B0CWGN7LJT",
    "https://www.amazon.in/dp/B0F4KJK8BV?th=1",
    "https://www.amazon.in/dp/B0F4N9PTX8",
    "https://www.amazon.in/dp/B0DGLKPXCG",
    "https://www.amazon.in/dp/B0CPFK3LMD",
    "https://www.amazon.in/dp/B0CPYBF9V2?th=1",
    "https://www.amazon.in/dp/B0DJGZSGY3",
    "https://www.amazon.in/dp/B0DJFPRWBH",
    "https://www.amazon.in/dp/B0DJGZS83D",
    "https://www.amazon.in/dp/B07C6GBJFL"
]))


# ================= HELPERS =================

def fetch_page(url):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            print(f"[FAIL {resp.status_code}] {url}")
            return None
        return resp.text
    except Exception as e:
        print(f"[ERROR] {url} -> {e}")
        return None


def extract_product_data(html):
    soup = BeautifulSoup(html, "html.parser")

    # ---------- TITLE ----------
    title_tag = soup.find(id="productTitle")
    title = title_tag.get_text(strip=True) if title_tag else "Unknown Product"

    # ---------- BULLETS ----------
    bullets = []
    bullet_section = soup.find(id="feature-bullets")

    if bullet_section:
        for li in bullet_section.find_all("li"):
            text = li.get_text(strip=True)
            if text and len(text) > 5:
                bullets.append(text)

    # ---------- DESCRIPTION ----------
    description = ""

    desc_tag = soup.find(id="productDescription")
    if desc_tag:
        description = desc_tag.get_text(strip=True)

    # ---------- FALLBACK ----------
    if not description:
        meta = soup.find("meta", {"name": "description"})
        if meta:
            description = meta.get("content", "")

    return {
        "title": title,
        "bullets": bullets,
        "description": description
    }


def clean_text(text):
    if not text:
        return ""
    return " ".join(text.split())


# ================= STRUCTURING =================

def format_product(entry):
    title = clean_text(entry["title"])

    bullets = "\n".join(
        f"- {clean_text(b)}"
        for b in entry["bullets"][:8]
    )

    description = clean_text(entry["description"])

    return f"""
PRODUCT:
{title}

KEY FEATURES:
{bullets if bullets else "Not available"}

DESCRIPTION:
{description if description else "Not available"}

""" + "=" * 80 + "\n"


# ================= MAIN =================

def crawl():
    print(f"\nFetching {len(AMAZON_URLS)} Amazon products...\n")

    session = requests.Session()
    session.headers.update(HEADERS)

    seen_titles = set()
    structured_data = []

    for url in AMAZON_URLS:
        print(f"[FETCH] {url}")

        html = fetch_page(url)
        if not html:
            continue

        data = extract_product_data(html)

        if not data["title"] or data["title"] in seen_titles:
            continue

        seen_titles.add(data["title"])

        structured_data.append(format_product(data))

        time.sleep(2)  # important for amazon blocking

    write_output(structured_data)

    print(f"\nDone. {len(structured_data)} products saved → {OUTPUT_FILE}")


def write_output(data):
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("ARYANVEDA AMAZON KNOWLEDGE BASE\n")
        f.write("=" * 80 + "\n\n")

        for entry in data:
            f.write(entry)


# ================= ENTRY =================

if __name__ == "__main__":
    crawl()