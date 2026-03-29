import os
import sys
import sqlite3
from dotenv import load_dotenv

load_dotenv(override=False)

DB_PATH       = os.getenv("DB_PATH",       "db/aryanveda.db")
CALLS_DB_PATH = os.getenv("CALLS_DB_PATH", os.path.join(os.path.dirname(DB_PATH), "call.db"))

HERE = os.path.dirname(__file__)


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


def run_schema():
    with open(os.path.join(HERE, "schema.sql"), encoding="utf-8") as f:
        sql = f.read()
    conn = get_conn(DB_PATH)
    conn.executescript(sql)
    conn.commit()
    conn.close()


def run_seed():
    with open(os.path.join(HERE, "seed.sql"), encoding="utf-8") as f:
        sql = f.read()
    conn = get_conn(DB_PATH)
    conn.executescript(sql)
    conn.commit()
    conn.close()


def run_inventory_schema():
    path = os.path.join(HERE, "inventory.sql")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            sql = f.read()
        conn = get_conn(DB_PATH)
        conn.executescript(sql)
        conn.commit()
        conn.close()


def verify_products():
    conn  = get_conn(DB_PATH)
    count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    sample = conn.execute("SELECT product_name, mrp_unit, retail FROM products LIMIT 1").fetchone()
    conn.close()
    print(f"\n  Total Products : {count}")
    if sample:
        print(f"  Sample         : {sample['product_name']} | MRP {sample['mrp_unit']} | Retail {sample['retail']}")
    print(f"  Database       : {os.path.abspath(DB_PATH)}")


def run_call_schema():
    with open(os.path.join(HERE, "call.sql"), encoding="utf-8") as f:
        sql = f.read()
    conn = get_conn(CALLS_DB_PATH)
    conn.executescript(sql)
    conn.commit()
    conn.close()


def run_call_patch():
    """Apply call_patch.sql — adds customer_type, caller_summary, orders tables."""
    patch_path = os.path.join(HERE, "call_patch.sql")
    if not os.path.exists(patch_path):
        print("  (call_patch.sql not found — skipping)")
        return
    with open(patch_path, encoding="utf-8") as f:
        statements = [s.strip() for s in f.read().split(";")
                      if s.strip() and not s.strip().startswith("--")]
    conn = get_conn(CALLS_DB_PATH)
    for stmt in statements:
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError as e:
            if "duplicate column" not in str(e).lower():
                print(f"\n  WARN: {e}")
    conn.commit()
    conn.close()


def verify_calls():
    conn   = get_conn(CALLS_DB_PATH)
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()]
    conn.close()
    print(f"\n  Tables : {', '.join(tables)}")
    print(f"  DB     : {os.path.abspath(CALLS_DB_PATH)}")


def create_export_dirs():
    for d in ["exports/orders", "exports/transcripts"]:
        os.makedirs(d, exist_ok=True)
        print(f"  Created: {d}")


if __name__ == "__main__":
    print("\nAryanVeda Database Setup")
    print("=" * 55)

    print(f"\n[1/4] Products DB  →  {DB_PATH}\n")
    run("Creating schema",       run_schema)
    run("Loading products",      run_seed)
    run("Adding inventory",      run_inventory_schema)
    run("Verifying data",        verify_products)

    print(f"\n[2/4] Calls DB     →  {CALLS_DB_PATH}\n")
    run("Creating call schema",  run_call_schema)
    run("Applying patch",        run_call_patch)
    run("Verifying tables",      verify_calls)

    print(f"\n[3/4] Export dirs\n")
    create_export_dirs()

    print(f"\n[4/4] Done!\n")
    print("All databases ready. Run the agent with:")
    print("  uvicorn server:app --host 0.0.0.0 --port 8000\n")