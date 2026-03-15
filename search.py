import os
import sys
import sqlite3
import time
import logging
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.WARNING,
    format="  [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from nlu.intent import IntentClassifier
from nlu.entities import EntityResolver

DB_PATH = os.getenv("DB_PATH", "db/aryaveda.db")

TEST_CASES = [
    ("amla tel 180 ml ka stock hai kya",                 "check_stock"),
    ("nimson amla hair oil badi wali available hai?",    "check_stock"),
    ("cool cool oil 90 ml stock batao",                  "check_stock"),
    ("badam ka tel 200 ml mein kitna bacha hai",         "check_stock"),
    ("keshsilk plus 450 hai kya",                        "check_stock"),
    ("boroneem talc 100 gram ka stock check karo",       "check_stock"),
    ("x-ice powder 100 gm ka kitna stock hai",           "check_stock"),
    ("fruit glow cream 50 gram available hai?",          "check_stock"),
    ("vasojelly strawberry wali 400 gm hai kya",         "check_stock"),
    ("gulab jal 100 ml ka stock batao",                  "check_stock"),
    ("sunscreen 60 ml hai kya",                          "check_stock"),
    ("charcoal face wash 100 ml stock hai kya bhai",     "check_stock"),
    ("petroleum jelly 42 gram ka stock",                 "check_stock"),
    ("colour plus shampoo 180 ka rate kya hai",          "get_price"),
    ("nimson himaryan oil 500 ml kitne ka hai",          "get_price"),
    ("olive oil 200 ml ka mrp batao",                    "get_price"),
    ("fruit glow bleach 43 gm ka offer rate kya hai",    "get_price"),
    ("oats olive lotion 90 ml kitne mein milega",        "get_price"),
    ("vitamin c face wash 60 ml ka MRP",                 "get_price"),
    ("honey almond cream 100 gm rate batao",             "get_price"),
    ("50 piece amla tel 180 ml bhejo",                   "place_order"),
    ("do doz colour plus shampoo 90 ml chahiye",         "place_order"),
    ("nimson rosemary shampoo 250 ml ka order karo",     "place_order"),
    ("vasojelly cocoa wali 400 gm teen doz order karo",  "place_order"),
    ("boroneem talc 300 gm combo pack mangwana hai",     "place_order"),
    ("glycerin 110 ml ka order bhijwa do",               "place_order"),
    ("kya kya shampoo hai tumhare paas",                 "list_skus"),
    ("hair oil ki poori list do",                        "list_skus"),
    ("face wash konse hain",                             "list_skus"),
    ("haan theek hai kar do",                            "confirm"),
    ("nahi rehne do cancel karo",                        "deny"),
    ("wahi wala tel phir se chahiye",                    "place_order"),
    ("manager se baat karni hai",                        "escalate"),
    ("theek hai bas shukriya",                           "end_call"),
]

RESET   = "\033[0m"
BOLD    = "\033[1m"
CYAN    = "\033[96m"
GREEN   = "\033[92m"
YELLOW  = "\033[93m"
RED     = "\033[91m"
DIM     = "\033[2m"
MAGENTA = "\033[95m"

def c(text, color):
    return f"{color}{text}{RESET}"

def divider():
    print(f"{DIM}{'-' * 62}{RESET}")

def header(title):
    print(f"\n{BOLD}{CYAN}{'-' * 62}\n  {title}\n{'-' * 62}{RESET}")


def fetch_product_row(product_id):
    if not product_id:
        return None
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        row  = conn.execute(
            "SELECT * FROM products WHERE id=? AND is_active=1", (product_id,)
        ).fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception as e:
        return {"error": str(e)}


def fuzzy_search_products(keyword, limit=5):
    if not keyword:
        return []
    try:
        words  = [w for w in keyword.lower().split() if len(w) > 2]
        if not words:
            return []
        conn   = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        clause = " AND ".join(f"LOWER(product_name) LIKE ?" for _ in words)
        rows   = conn.execute(
            f"SELECT id, product_name, weight, mrp_unit, offer_rate_new "
            f"FROM products WHERE {clause} AND is_active=1 LIMIT ?",
            [f"%{w}%" for w in words] + [limit]
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        return [{"error": str(e)}]


def print_intent_block(result, elapsed):
    intent     = result.get("intent", "unknown")
    conf       = result.get("confidence", 0.0)
    entities   = result.get("entities", {})
    lang       = result.get("language", "?")
    conf_color = GREEN if conf >= 0.8 else (YELLOW if conf >= 0.5 else RED)
    int_color  = GREEN if intent != "unknown" else RED

    print(f"\n  {BOLD}INTENT{RESET}")
    print(f"     intent      : {c(intent.upper(), int_color)}")
    print(f"     confidence  : {c(f'{conf:.2f}', conf_color)}  |  language: {lang}  |  {c(f'{elapsed:.2f}s', DIM)}")
    print(f"\n     entities:")
    print(f"       product_name : {c(repr(entities.get('product_name')), YELLOW)}")
    print(f"       weight_hint  : {c(repr(entities.get('weight_hint')), YELLOW)}")
    print(f"       quantity     : {c(repr(entities.get('quantity')), YELLOW)}")
    print(f"       order_ref    : {c(repr(entities.get('order_ref')), YELLOW)}")


def print_entity_block(resolved, elapsed):
    pid        = resolved.get("product_id")
    conf       = resolved.get("confidence", 0.0)
    conf_color = GREEN if conf >= 0.75 else (YELLOW if conf >= 0.5 else RED)

    print(f"\n  {BOLD}ENTITY RESOLUTION{RESET}")
    print(f"     product_id   : {c(pid or 'NULL', GREEN if pid else RED)}")
    print(f"     product_name : {c(resolved.get('product_name') or '-', CYAN)}")
    print(f"     weight       : {c(resolved.get('weight') or '-', CYAN)}")
    print(f"     confidence   : {c(f'{conf:.2f}', conf_color)}  |  {c(f'{elapsed:.2f}s', DIM)}")
    if resolved.get("candidates"):
        print(f"     candidates   : {c(', '.join(resolved['candidates']), MAGENTA)}")


def print_db_block(row, fuzzy, product_name):
    print(f"\n  {BOLD}DATABASE{RESET}")

    if row and "error" not in row:
        print(f"     status       : {c('MATCHED', GREEN)}")
        print(f"     id           : {row['id']}")
        print(f"     product_name : {row['product_name']}")
        print(f"     weight       : {row['weight']}")
        if row.get("mrp_unit"):
            print(f"     mrp_unit     : {row['mrp_unit']:.2f}")
        if row.get("offer_rate_new"):
            print(f"     offer_rate   : {row['offer_rate_new']:.2f}")
        if row.get("master_package"):
            print(f"     master_pack  : {row['master_package']}")
        if row.get("scheme_percentage"):
            print(f"     scheme       : {row['scheme_percentage']}  ({row.get('scheme_amount', 0):.2f} off)")
        if row.get("billing"):
            print(f"     billing      : {row['billing']:.2f}")
        if row.get("distributor_total"):
            print(f"     dist_total   : {row['distributor_total']:.2f}")
        if row.get("retail"):
            print(f"     retail       : {row['retail']:.2f}")
    elif fuzzy:
        print(f"     status       : {c('NO EXACT MATCH - fuzzy fallback', YELLOW)}")
        print(f"     {'id':<12} {'product_name':<44} {'weight':<10} {'mrp':>7}  {'offer':>9}")
        print(f"     {'-'*12} {'-'*44} {'-'*10} {'-'*7}  {'-'*9}")
        for r in fuzzy:
            if "error" in r:
                print(f"     db error: {r['error']}")
            else:
                print(
                    f"     {r['id']:<12} "
                    f"{r['product_name']:<44} "
                    f"{(r.get('weight') or ''):<10} "
                    f"{r.get('mrp_unit', 0):>7.2f}  "
                    f"{r.get('offer_rate_new', 0):>9.2f}"
                )
    else:
        print(f"     status       : {c('NOT FOUND', RED)}")
        print(f"     query was    : '{product_name}'")


def run_pipeline(query, classifier, resolver, verbose=True):
    if verbose:
        divider()
        print(f"\n  {BOLD}QUERY{RESET}  {c(query, YELLOW)}")

    t0            = time.time()
    if verbose:
        print(f"  {DIM}step 1/3  intent classification...{RESET}", flush=True)
    intent_result = classifier.classify(query)
    t1            = time.time()

    if verbose:
        if intent_result.get("intent") == "unknown" and intent_result.get("confidence") == 0.0:
            print(f"  {c('classifier returned empty — check logs above', RED)}", flush=True)
        print_intent_block(intent_result, t1 - t0)

    raw_entities = intent_result.get("entities", {})

    t2       = time.time()
    if verbose:
        print(f"  {DIM}step 2/3  entity resolution...{RESET}", flush=True)
    resolved = resolver.resolve(raw_entities)
    t3       = time.time()

    if verbose:
        print_entity_block(resolved, t3 - t2)

    if verbose:
        print(f"  {DIM}step 3/3  database fetch...{RESET}", flush=True)

    db_row = fetch_product_row(resolved.get("product_id"))
    fuzzy  = []
    if not db_row:
        fuzzy = fuzzy_search_products(raw_entities.get("product_name") or "")

    # Feed a concise agent turn back into history so the next classify()
    # call knows what information was already given to the caller.
    if db_row and "error" not in db_row:
        classifier.add_agent_turn(
            f"{db_row['product_name']} {db_row['weight']} — "
            f"MRP {db_row.get('mrp_unit', '')}, offer {db_row.get('offer_rate_new', '')}"
        )
    elif fuzzy:
        names = ", ".join(f"{r['product_name']} {r.get('weight','')}" for r in fuzzy[:3])
        classifier.add_agent_turn(f"Multiple variants found: {names}")

    if verbose:
        print_db_block(db_row, fuzzy, raw_entities.get("product_name", ""))
        print()

    return intent_result, resolved, db_row


def interactive_mode(classifier, resolver):
    header("AryanVeda Pipeline — Interactive")
    print(f"  {DIM}hinglish query | 'batch' for test suite | 'reset' to clear session | 'quit' to exit{RESET}\n")

    while True:
        try:
            query = input(f"{BOLD}query > {RESET}").strip()
        except (KeyboardInterrupt, EOFError):
            break

        if not query:
            continue
        if query.lower() in ("quit", "exit", "q"):
            break
        if query.lower() == "batch":
            batch_mode(classifier, resolver)
            continue
        if query.lower() == "reset":
            classifier.reset()
            print(f"  {DIM}session cleared{RESET}\n")
            continue

        run_pipeline(query, classifier, resolver, verbose=True)


def batch_mode(classifier, resolver):
    header(f"Batch Test — {len(TEST_CASES)} queries")
    print(f"  {'db':<5} {'intent match':<22} {'product_id':<12} {'resolved_name':<36} query")
    print(f"  {'-'*5} {'-'*22} {'-'*12} {'-'*36} {'-'*40}")

    passed = 0
    for query, expected_intent in TEST_CASES:
        intent_result, resolved, db_row = run_pipeline(
            query, classifier, resolver, verbose=False
        )
        actual_intent = intent_result.get("intent", "unknown")
        prod_id       = resolved.get("product_id") or "NULL"
        prod_nm       = (resolved.get("product_name") or "-")[:35]
        db_ok         = "OK  " if db_row and "error" not in db_row else "FAIL"
        intent_ok     = "OK" if actual_intent == expected_intent else f"FAIL ({actual_intent})"

        print(
            f"  {c(db_ok, GREEN if db_ok.strip() == 'OK' else RED):<5} "
            f"{intent_ok:<22} "
            f"{prod_id:<12} "
            f"{prod_nm:<36} "
            f"{query[:50]}"
        )
        if db_row and "error" not in db_row:
            passed += 1

    print(f"\n  {BOLD}db match rate: {passed}/{len(TEST_CASES)}{RESET}")
    divider()


def single_query_mode(query, classifier, resolver):
    header("Single Query")
    run_pipeline(query, classifier, resolver, verbose=True)


def main():
    if not os.path.exists(DB_PATH):
        print(f"{RED}database not found: {DB_PATH}{RESET}")
        print("run: python setup.py")
        sys.exit(1)

    print(f"\n{BOLD}loading pipeline...{RESET}", end=" ", flush=True)
    classifier = IntentClassifier()
    resolver   = EntityResolver()
    resolver.share_history(classifier._history)   # single shared history
    print(f"{GREEN}ready{RESET}")

    if len(sys.argv) > 1:
        if sys.argv[1] == "--batch":
            batch_mode(classifier, resolver)
        else:
            single_query_mode(" ".join(sys.argv[1:]), classifier, resolver)
    else:
        interactive_mode(classifier, resolver)

    print(f"\n{DIM}done{RESET}\n")


if __name__ == "__main__":
    main()