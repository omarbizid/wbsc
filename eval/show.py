"""Print sample postings for labelling, paginated by character budget.

Usage: python eval/show.py <tune|eval> <start_index> [budget_chars]
"""
import json
import re
import sys

name, start = sys.argv[1], int(sys.argv[2])
budget = int(sys.argv[3]) if len(sys.argv) > 3 else 26000
rows = [json.loads(line) for line in open(f"eval/sample_{name}.jsonl", encoding="utf-8")]
used = 0
for r in rows[start:]:
    desc = re.sub(r"\n+", " | ", r["description"])
    block = f"=== {r['id']} | {r['title']} | {r['company']}\n{desc}\n"
    if used and used + len(block) > budget:
        break
    print(block)
    used += len(block)
    start += 1
print(f"--- next start index: {start} of {len(rows)}")
