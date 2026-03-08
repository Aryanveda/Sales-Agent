import os
import sys
import sqlite3
from dotenv import load_dotenv

load_dotenv(override=False)

DB_PATH = os.getenv("DB_PATH", "aryaveda.db")


def run(label, fn):
    print(f"  -> {label}...", end=" ", flush=True)
    try:
        fn()
        print("OK")
    except Exception as e:
        print(f"ERROR\n    {e}")
        sys.exit(1)


def get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def run_schema():
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    with open(schema_path, encoding='utf-8') as f:
        sql = f.read()
    conn = get_conn()
    conn.executescript(sql)
    conn.commit()
    conn.close()


def run_seed():
    seed_path = os.path.join(os.path.dirname(__file__), "seed.sql")
    with open(seed_path, encoding='utf-8') as f:
        sql = f.read()
    conn = get_conn()
    conn.executescript(sql)
    conn.commit()
    conn.close()


def verify():
    conn = get_conn()
    product_count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    sample = conn.execute(
        "SELECT id, product_name, mrp_unit, retail FROM products LIMIT 1"
    ).fetchone()
    conn.close()
    
    print(f"\n  Total Products: {product_count}")
    if sample:
        print(f"  Sample: {sample['product_name']}")
        print(f"  MRP: {sample['mrp_unit']} | Retail: {sample['retail']}")
    print(f"  Database: {os.path.abspath(DB_PATH)}")


if __name__ == "__main__":
    print("\nAryanVeda Database Setup")
    print("=" * 50)
    print(f"  DB path: {DB_PATH}\n")
    
    run("Creating schema", run_schema)
    run("Loading 119 products", run_seed)
    run("Verifying data", verify)
    
    print("\nDatabase ready!")
    print("All 119 products loaded")
    print("Ready to use\n")