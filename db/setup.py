import os
import sys
import uuid
import sqlite3
from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.getenv("DB_PATH", "db/aryaveda.db")


def run(label, fn):
    print(f"  → {label}...", end=" ", flush=True)
    try:
        fn()
        print("✅")
    except Exception as e:
        print(f"❌\n    {e}")
        sys.exit(1)


def get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def run_schema():
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    with open(schema_path) as f:
        sql = f.read()
    conn = get_conn()
    conn.executescript(sql)
    conn.commit()
    conn.close()


def seed():
    conn = get_conn()

    # ── Distributors ──────────────────────────────────────────
    distributors = [
        ("DIST_MUM_01", "Mumbai Central Distributor",  "मुंबई सेंट्रल",  "Mumbai",    "West"),
        ("DIST_MUM_02", "Mumbai Suburban Distributor", "मुंबई सबअर्बन",  "Mumbai",    "West"),
        ("DIST_DEL_01", "Delhi NCR Distributor",       "दिल्ली एनसीआर",  "Delhi",     "North"),
        ("DIST_DEL_02", "Delhi South Distributor",     "दिल्ली साउथ",    "Delhi",     "North"),
        ("DIST_BLR_01", "Bangalore Distributor",       "बैंगलोर",         "Bangalore", "South"),
        ("DIST_HYD_01", "Hyderabad Distributor",       "हैदराबाद",        "Hyderabad", "South"),
        ("DIST_CHN_01", "Chennai Distributor",         "चेन्नई",          "Chennai",   "South"),
        ("DIST_PUN_01", "Punjab Distributor",          "पंजाब",           "Ludhiana",  "North"),
        ("DIST_GUJ_01", "Gujarat Distributor",         "गुजरात",          "Ahmedabad", "West"),
        ("DIST_RAJ_01", "Rajasthan Distributor",       "राजस्थान",        "Jaipur",    "North"),
    ]
    conn.executemany("""
        INSERT OR IGNORE INTO distributors (id, code, name, name_hindi, city, region)
        VALUES (?, ?, ?, ?, ?, ?)
    """, [(str(uuid.uuid4()), *d) for d in distributors])

    # ── SKUs ──────────────────────────────────────────────────
    skus = [
        ("AV-001","Advanced Crack Heel Repair Cream 25 gm","cream",48.00,75.00),
        ("AV-002","Almond Hair Oil 100 ml","hair_oil",65.00,99.00),
        ("AV-003","Almond Hair Oil 200 ml","hair_oil",110.00,175.00),
        ("AV-004","Almond Hair Oil 500 ml","hair_oil",220.00,349.00),
        ("AV-005","Almond Olive Hair Oil 100 ml","hair_oil",72.00,110.00),
        ("AV-006","Almond Olive Hair Oil 200 ml","hair_oil",125.00,195.00),
        ("AV-007","Aloevera & Cucumber Hy Moist. Cr 15 ml","cream",28.00,45.00),
        ("AV-008","Aloevera & Cucumber Hy Moist. Cr. 50 gm","cream",58.00,89.00),
        ("AV-009","Aloevera & Cucumber Hy Moist. Cr.100 gm","cream",95.00,149.00),
        ("AV-010","Amla Hair Oil 180 ml","hair_oil",78.00,120.00),
        ("AV-011","Amla Hair Oil 20 ml","hair_oil",18.00,29.00),
        ("AV-012","Amla Hair Oil 300 ml","hair_oil",115.00,179.00),
        ("AV-013","Amla Hair Oil 35 ml","hair_oil",28.00,45.00),
        ("AV-014","Amla Hair Oil 450 ml","hair_oil",158.00,249.00),
        ("AV-015","Amla Hair Oil 50 ml","hair_oil",38.00,59.00),
        ("AV-016","Amla Hair Oil 70 ml","hair_oil",48.00,75.00),
        ("AV-017","Amla Hair Oil 90 ml","hair_oil",58.00,89.00),
        ("AV-018","Amla Hair Oil 1 Ltr","hair_oil",295.00,459.00),
        ("AV-019","Apple Face Wash 60 ml","face_wash",55.00,85.00),
        ("AV-020","Body Guard Talcum 100 gm","talcum",48.00,75.00),
        ("AV-021","Bodyguard Talcum 20 gm","talcum",18.00,29.00),
        ("AV-022","Boroneem Cream 20 gm","cream",38.00,59.00),
        ("AV-023","Boroneem Premium Antifungal Talcum 100 gm","talcum",72.00,110.00),
        ("AV-024","Boroneem Talcum 100 gm","talcum",55.00,85.00),
        ("AV-025","Boroneem Talcum 150 gm","talcum",72.00,110.00),
        ("AV-026","Boroneem Talcum 20 gm","talcum",18.00,29.00),
        ("AV-027","Boroneem Talcum 300 gm","talcum",118.00,185.00),
        ("AV-028","Boroneem Talcum 50 gm","talcum",32.00,49.00),
        ("AV-029","Charcoal Face Wash 60 gm","face_wash",62.00,95.00),
        ("AV-030","Charcoal Face Wash 100 gm","face_wash",88.00,135.00),
        ("AV-031","Coconut Oil 50 ml","hair_oil",32.00,49.00),
        ("AV-032","Coconut Oil 90 ml","hair_oil",52.00,79.00),
        ("AV-033","Coconut Oil 950 ml","hair_oil",398.00,619.00),
        ("AV-034","Coconut Oil 500 ml","hair_oil",215.00,335.00),
        ("AV-035","Coconut Pure Natural Oil 175 ml","hair_oil",85.00,130.00),
        ("AV-036","Color Plus Shampoo Mix Pouch 5 ml","shampoo",5.00,8.00),
        ("AV-037","Colour Plus Family Shampoo 180 ml","shampoo",78.00,120.00),
        ("AV-038","Colour Plus Family Shampoo 450 ml","shampoo",168.00,260.00),
        ("AV-039","Colour Plus Family Shampoo 90 ml","shampoo",45.00,69.00),
        ("AV-040","Diamond Bleach Cream 43 gm","bleach",55.00,85.00),
        ("AV-041","Divya Ratan Hair Oil 180 ml","hair_oil",85.00,130.00),
        ("AV-042","Divya Ratan Hair Oil 450 ml","hair_oil",178.00,275.00),
        ("AV-043","Divya Ratan Hair Oil 50 ml","hair_oil",35.00,55.00),
        ("AV-044","Divya Ratan Hair Oil 90 ml","hair_oil",58.00,89.00),
        ("AV-045","Divyaratan Cool Talc 100 gm","talcum",52.00,79.00),
        ("AV-046","Divyaratan Cool Talc 50 gm","talcum",32.00,49.00),
        ("AV-047","Fair and Gomarks Cream 25 gm","cream",42.00,65.00),
        ("AV-048","Fair and Kwik Cream 25 gm","cream",42.00,65.00),
        ("AV-049","Fruit Glow Bleach Cream 10 gm","bleach",22.00,35.00),
        ("AV-050","Fruit Glow Bleach Cream 43 gm","bleach",55.00,85.00),
        ("AV-051","Fruit Glow Cream 15 ml","cream",28.00,45.00),
        ("AV-052","Fruit Glow Cream 200 gm","cream",118.00,185.00),
        ("AV-053","Fruit Glow Cream 400 gm","cream",198.00,309.00),
        ("AV-054","Fruit Glow Cream 50 gm","cream",42.00,65.00),
        ("AV-055","Fruit Glow Cream 100 gm","cream",72.00,110.00),
        ("AV-056","Fruit Glow Hand & Body Lotion 180 ml","lotion",85.00,130.00),
        ("AV-057","Fruit Glow Hand & Body Lotion 20 ml","lotion",18.00,29.00),
        ("AV-058","Fruit Glow Hand & Body Lotion 450 ml","lotion",178.00,275.00),
        ("AV-059","Fruit Glow Hand & Body Lotion 90 ml","lotion",52.00,79.00),
        ("AV-060","Glycerine Solution 3 in 1 Benefits 110 gm","cream",65.00,99.00),
        ("AV-061","Glycerine Solution 3 in 1 Benefits 200 gm","cream",105.00,165.00),
        ("AV-062","Glycerine Solution 3 in 1 Benefits 50 gm","cream",38.00,59.00),
        ("AV-063","Gold Bleach Cream 10 gm","bleach",25.00,39.00),
        ("AV-064","Gold Bleach Cream 250 gm","bleach",215.00,335.00),
        ("AV-065","Gold Bleach Cream 43 gm","bleach",62.00,95.00),
        ("AV-066","Green Apple Shampoo 500 ml","shampoo",178.00,275.00),
        ("AV-067","Gulab Jal Premium 100 ml","toner",55.00,85.00),
        ("AV-068","Gulab Jal Premium 50 ml","toner",32.00,49.00),
        ("AV-069","Hair Removing Cream 25 gm MIX","cream",42.00,65.00),
        ("AV-070","Hair Removing Cream 25 gm ROSE","cream",42.00,65.00),
        ("AV-071","Hair Removing Cream 60 gm MIX","cream",78.00,120.00),
        ("AV-072","Hair Removing Cream 60 gm ROSE","cream",78.00,120.00),
        ("AV-073","Haldi Chandan Bleach 10 gm","bleach",22.00,35.00),
        ("AV-074","Happy Lip Balm Strawberry 5 ml","lip_care",18.00,29.00),
        ("AV-075","Happy Lips Strawberry Lip Balm 10 ml","lip_care",28.00,45.00),
        ("AV-076","Herbal Shampoo 500 ml","shampoo",158.00,245.00),
        ("AV-077","Himaryan Oil 100 ml","hair_oil",72.00,110.00),
        ("AV-078","Himaryan Oil 200 ml","hair_oil",118.00,185.00),
        ("AV-079","Himaryan Oil 500 ml","hair_oil",245.00,379.00),
        ("AV-080","Honey & Almond Cream 15 ml","cream",28.00,45.00),
        ("AV-081","Honey & Almond Cream 100 gm","cream",78.00,120.00),
        ("AV-082","Honey & Almond Cream 50 gm","cream",45.00,69.00),
        ("AV-083","Jasmine Coconut Hair Oil 180 ml","hair_oil",85.00,130.00),
        ("AV-084","Jasmine Coconut Hair Oil 20 ml","hair_oil",18.00,29.00),
        ("AV-085","Jasmine Coconut Hair Oil 35 ml","hair_oil",28.00,45.00),
        ("AV-086","Jasmine Coconut Hair Oil 450 ml","hair_oil",178.00,275.00),
        ("AV-087","Jasmine Coconut Hair Oil 50 ml","hair_oil",38.00,59.00),
        ("AV-088","Jasmine Coconut Hair Oil 70 ml","hair_oil",48.00,75.00),
        ("AV-089","Jasmine Coconut Hair Oil 90 ml","hair_oil",58.00,89.00),
        ("AV-090","Kashmir E Zafran Cream 50 gm","cream",98.00,149.00),
        ("AV-091","Kerala Ayurvedic Oil 150 ml","hair_oil",88.00,135.00),
        ("AV-092","Kesh Silk Hair Oil 180 ml","hair_oil",88.00,135.00),
        ("AV-093","Kesh Silk Hair Oil 450 ml","hair_oil",185.00,285.00),
        ("AV-094","Kesh Silk Hair Oil 50 ml","hair_oil",38.00,59.00),
        ("AV-095","Kesh Silk Hair Oil 90 ml","hair_oil",62.00,95.00),
        ("AV-096","Kesh Silk Plus Hair Oil 120 ml","hair_oil",78.00,120.00),
        ("AV-097","Lip Guard 9 gm","lip_care",22.00,35.00),
        ("AV-098","Lip Jelly Coffee 10 gm","lip_care",28.00,45.00),
        ("AV-099","Lip Jelly Strawberry 10 gm","lip_care",28.00,45.00),
        ("AV-100","Nature Fresh Brilliantine 90 ml","hair_care",55.00,85.00),
        ("AV-101","Nature Fresh Hydrating Shampoo 1000 ml","shampoo",298.00,459.00),
        ("AV-102","Nature Fresh Shampoo 180 ml","shampoo",85.00,130.00),
        ("AV-103","Nature Fresh Shampoo 500 ml","shampoo",185.00,285.00),
        ("AV-104","Neem Tulsi Face Wash 60 ml","face_wash",58.00,89.00),
        ("AV-105","Oats & Olive Body Lotion 180 ml","lotion",88.00,135.00),
        ("AV-106","Oats & Olive Body Lotion 20 ml","lotion",22.00,35.00),
        ("AV-107","Oats & Olive Body Lotion 450 ml","lotion",185.00,285.00),
        ("AV-108","Oats & Olive Body Lotion 90 ml","lotion",55.00,85.00),
        ("AV-109","Olive Body Oil 100 ml","body_oil",72.00,110.00),
        ("AV-110","Olive Body Oil 200 ml","body_oil",118.00,185.00),
        ("AV-111","Olive Body Oil 500 ml","body_oil",245.00,379.00),
        ("AV-112","Papaya D-Tan Face Wash 60 gm","face_wash",62.00,95.00),
        ("AV-113","Petroleum Jelly 50 gm","jelly",32.00,49.00),
        ("AV-114","Protein Shampoo 500 ml","shampoo",178.00,275.00),
        ("AV-115","Reshm-E-Zulf Hair Oil 100 ml","hair_oil",72.00,110.00),
        ("AV-116","Rosemary Hair Growth Spray 110 ml","hair_care",118.00,185.00),
        ("AV-117","Rosemary Hair Oil With Free Shampoo 150 ml","hair_oil",105.00,165.00),
        ("AV-118","Rosemary Shampoo 250 ml","shampoo",115.00,179.00),
        ("AV-119","Silk Plus Cold Cream 100 gm","cream",72.00,110.00),
        ("AV-120","Silk Plus Cold Cream 15 ml","cream",22.00,35.00),
        ("AV-121","Silk Plus Cold Cream 50 gm","cream",42.00,65.00),
        ("AV-122","Silk Plus Lavender Talcum Powder 20 gm","talcum",18.00,29.00),
        ("AV-123","Silk Plus Rose Talcum Powder 100 gm","talcum",55.00,85.00),
        ("AV-124","Silk Plus Rose Talcum Powder 300 gm","talcum",128.00,199.00),
        ("AV-125","Silk Plus Rose Talcum Powder 20 gm","talcum",18.00,29.00),
        ("AV-126","Strawberry Oil Control Face Wash 60 gm","face_wash",62.00,95.00),
        ("AV-127","Sunscreen Matte Gel Cream SPF30 200 gm","sunscreen",155.00,239.00),
        ("AV-128","Sunscreen Matte Gel Cream SPF30 60 gm","sunscreen",62.00,95.00),
        ("AV-129","Turmeric Cream 30 gm","cream",42.00,65.00),
        ("AV-130","Ubtan Face Wash 100 gm","face_wash",85.00,130.00),
        ("AV-131","Ubtan Face Wash 60 gm","face_wash",58.00,89.00),
        ("AV-132","Vasojelly Cocoa Cream 400 gm","cream",178.00,275.00),
        ("AV-133","Vasojelly Fresh Aloe Face & Body Cream 400 gm","cream",178.00,275.00),
        ("AV-134","Vasojelly Radiant Glow Face & Body Cream 400 gm","cream",178.00,275.00),
        ("AV-135","Vasojelly Strawberry Crush Face Hand Body Cream 400 gm","cream",178.00,275.00),
        ("AV-136","Vitamin C Face Wash 100 gm","face_wash",88.00,135.00),
        ("AV-137","Vitamin C Face Wash 60 gm","face_wash",62.00,95.00),
        ("AV-138","White Petroleum Jelly 100 gm","jelly",55.00,85.00),
        ("AV-139","White Petroleum Jelly 14 ml","jelly",15.00,25.00),
        ("AV-140","White Petroleum Jelly 21 ml","jelly",22.00,35.00),
        ("AV-141","White Petroleum Jelly 42 ml","jelly",38.00,59.00),
        ("AV-142","White Petroleum Jelly 7 ml","jelly",10.00,18.00),
        ("AV-143","X-Ice Talcum Powder 100 gm","talcum",48.00,75.00),
        ("AV-144","X-Ice Talcum Powder 120 gm Rose","talcum",58.00,89.00),
        ("AV-145","X-Ice Talcum Powder 120 gm Sandal","talcum",58.00,89.00),
        ("AV-146","X-Ice Talcum Powder 20 gm","talcum",18.00,29.00),
    ]
    conn.executemany("""
        INSERT OR IGNORE INTO skus (id, sku_code, name, category, base_price, mrp)
        VALUES (?, ?, ?, ?, ?, ?)
    """, [(str(uuid.uuid4()), *s) for s in skus])

    # ── Stock per distributor (synthetic) ─────────────────────
    cur = conn.execute("SELECT id, code FROM distributors")
    dist_rows = cur.fetchall()
    cur = conn.execute("SELECT id, sku_code FROM skus")
    sku_rows = cur.fetchall()

    stock_data = []
    for d in dist_rows:
        for s in sku_rows:
            qty = ((ord(s["sku_code"][-1]) * 3 + ord(d["code"][-1]) * 7) % 450) + 50
            if (ord(s["sku_code"][-1]) + ord(d["code"][-1])) % 7 == 0:
                qty = 0
            stock_data.append((str(uuid.uuid4()), d["id"], s["id"], qty))

    conn.executemany("""
        INSERT OR IGNORE INTO distributor_skus (id, distributor_id, sku_id, stock_qty)
        VALUES (?, ?, ?, ?)
    """, stock_data)

    conn.commit()
    conn.close()


def verify():
    conn = get_conn()
    d  = conn.execute("SELECT COUNT(*) FROM distributors").fetchone()[0]
    s  = conn.execute("SELECT COUNT(*) FROM skus").fetchone()[0]
    ds = conn.execute("SELECT COUNT(*) FROM distributor_skus WHERE stock_qty > 0").fetchone()[0]
    conn.close()
    print(f"\n  📦 {s} SKUs | 🏢 {d} Distributors | ✅ {ds} in-stock records")
    print(f"  📁 Database saved at: {os.path.abspath(DB_PATH)}")


if __name__ == "__main__":
    print("\n🗄️  AryanVeda — SQLite Setup")
    print("=" * 40)
    print(f"  DB path: {DB_PATH}\n")
    run("Running schema",  run_schema)
    run("Seeding data",    seed)
    run("Verifying",       verify)
    print("\n✅ Database ready. Run: python main.py\n")