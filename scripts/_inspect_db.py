"""Quick read-only inspection of nl2dsl.db: schema and row counts."""
import sqlite3
import sys
import os

DB = os.path.join(os.path.dirname(__file__), "..", "nl2dsl.db")
con = sqlite3.connect(DB)
cur = con.cursor()

cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables = [r[0] for r in cur.fetchall()]
print("Tables:", tables)
print()

for t in tables:
    try:
        cur.execute(f"SELECT COUNT(*) FROM {t}")
        n = cur.fetchone()[0]
        cur.execute(f"PRAGMA table_info({t})")
        cols = [(r[1], r[2]) for r in cur.fetchall()]
        print(f"== {t}  rows={n}")
        for c in cols:
            print(f"   {c[0]:24s} {c[1]}")
        if n > 0 and t in ("order_fact", "product_dim", "customer_dim"):
            cur.execute(f"SELECT * FROM {t} LIMIT 3")
            for row in cur.fetchall():
                print("   sample:", row)
        print()
    except Exception as e:
        print(f"{t}: error {e}")

# distinct values
for t, c in [("order_fact","region"), ("order_fact","category"), ("order_fact","customer_type"), ("order_fact","brand"), ("order_fact","channel"), ("customer_dim","customer_type")]:
    try:
        cur.execute(f"SELECT DISTINCT {c} FROM {t}")
        print(f"distinct {t}.{c} =", [r[0] for r in cur.fetchall()])
    except Exception as e:
        print(f"{t}.{c}: {e}")
