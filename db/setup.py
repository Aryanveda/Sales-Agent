import os
import sys
import sqlite3
from dotenv import load_dotenv

load_dotenv(override=False)

DB_PATH      = os.getenv("DB_PATH",      "aryanveda.db")
CALLS_DB_PATH = os.getenv("CALLS_DB_PATH", os.path.join(os.path.dirname(DB_PATH), "call.db"))

HERE = os.path.dirname(__file__)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def run(label, fn):
    print(f"  -> {label}...", end=" ", flush=True)
    try:
        fn()
        print("OK")
    except Exception as e:
        print(f"ERROR\n    {e}")
        sys.exit(1)


def get_conn(path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ─────────────────────────────────────────────────────────────────────────────
# aryanveda.db  (products)
# ─────────────────────────────────────────────────────────────────────────────

def run_schema():
    schema_path = os.path.join(HERE, "schema.sql")
    with open(schema_path, encoding="utf-8") as f:
        sql = f.read()
    conn = get_conn(DB_PATH)
    conn.executescript(sql)
    conn.commit()
    conn.close()


def run_seed():
    seed_path = os.path.join(HERE, "seed.sql")
    with open(seed_path, encoding="utf-8") as f:
        sql = f.read()
    conn = get_conn(DB_PATH)
    conn.executescript(sql)
    conn.commit()
    conn.close()


def verify_products():
    conn = get_conn(DB_PATH)
    product_count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    sample = conn.execute(
        "SELECT id, product_name, mrp_unit, retail FROM products LIMIT 1"
    ).fetchone()
    conn.close()

    print(f"\n  Total Products : {product_count}")
    if sample:
        print(f"  Sample         : {sample['product_name']}")
        print(f"  MRP: {sample['mrp_unit']} | Retail: {sample['retail']}")
    print(f"  Database       : {os.path.abspath(DB_PATH)}")


# ─────────────────────────────────────────────────────────────────────────────
# call.db  (caller sessions & transcripts)
# ─────────────────────────────────────────────────────────────────────────────

def run_call_schema():
    call_schema_path = os.path.join(HERE, "call.sql")
    with open(call_schema_path, encoding="utf-8") as f:
        sql = f.read()
    conn = get_conn(CALLS_DB_PATH)
    conn.executescript(sql)
    conn.commit()
    conn.close()


def verify_calls():
    conn = get_conn(CALLS_DB_PATH)
    tables = [
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    ]
    conn.close()

    print(f"\n  Tables created : {', '.join(tables)}")
    print(f"  Database       : {os.path.abspath(CALLS_DB_PATH)}")


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\nAryanVeda Database Setup")
    print("=" * 50)

    # ── Products DB ──────────────────────────────────────────────────────────
    print(f"\n[1/2] Products DB  →  {DB_PATH}\n")
    run("Creating schema",       run_schema)
    run("Loading 119 products",  run_seed)
    run("Verifying data",        verify_products)

    # ── Calls DB ─────────────────────────────────────────────────────────────
    print(f"\n[2/2] Calls DB     →  {CALLS_DB_PATH}\n")
    run("Creating call schema",  run_call_schema)
    run("Verifying tables",      verify_calls)

    print("\nAll databases ready!")
    print("119 products loaded into aryanveda.db")
    print("call.db initialised with 6 tables (callers, sessions, transcripts,")
    print("       session_context, caller_memory, call_events)\n")