"""Command-line entry point: `jobintel <command>`."""

from __future__ import annotations

import argparse
import logging
import sys

from jobintel import db
from jobintel.pipeline import collect_and_load, load_pending, replay
from jobintel.sources import REGISTRY


def _print_stats(s) -> None:
    print(f"  load_run={s.load_run_id} batch={s.batch_id} status={s.status} "
          f"collected={s.n_collected} accepted={s.n_accepted} rejected={s.n_rejected} "
          f"duplicate={s.n_duplicate} out_of_scope={s.n_out_of_scope} "
          f"new_postings={s.n_new_postings} new_versions={s.n_new_versions}"
          + (f" error={s.error}" if s.error else ""))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jobintel")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_db = sub.add_parser("db", help="database management")
    p_db.add_argument("action", choices=["migrate"])

    p_col = sub.add_parser("collect", help="fetch sources into the raw store and load them")
    g = p_col.add_mutually_exclusive_group(required=True)
    g.add_argument("--source", action="append", choices=sorted(REGISTRY))
    g.add_argument("--all", action="store_true")
    p_col.add_argument("--no-load", action="store_true",
                       help="only save raw data (the load can be replayed later)")

    p_ld = sub.add_parser("load", help="load raw batches that were collected but not loaded "
                                       "yet (no network)")
    p_ld.add_argument("--pending", action="store_true", required=True,
                      help="load every batch without a successful load run")
    p_ld.add_argument("--source", choices=sorted(REGISTRY))

    p_rep = sub.add_parser("replay", help="reprocess saved raw batches without network access")
    g = p_rep.add_mutually_exclusive_group(required=True)
    g.add_argument("--batch")
    g.add_argument("--source", choices=sorted(REGISTRY))
    g.add_argument("--all", action="store_true")

    p_st = sub.add_parser("status", help="show recent collection batches and load runs")
    p_st.add_argument("--limit", type=int, default=10)

    p_en = sub.add_parser("enrich", help="(re)compute skills and role/seniority for versions "
                                         "made by an older extractor or classifier")
    p_en.add_argument("--force", action="store_true", help="recompute every version")

    p_ev = sub.add_parser("evaluate", help="measure skill extraction on a labelled sample")
    p_ev.add_argument("set", choices=["tune", "eval"])
    p_ev.add_argument("--save", action="store_true", help="write eval/results_<set>_<ver>.json")

    p_tr = sub.add_parser("transform", help="run dbt (default: `build` = models + tests)")
    p_tr.add_argument("dbt_args", nargs=argparse.REMAINDER,
                      help="arguments passed to dbt, e.g. `test --select dim_postings`")

    p_da = sub.add_parser("dashboard", help="open the Streamlit dashboard (reads marts)")
    p_da.add_argument("streamlit_args", nargs=argparse.REMAINDER,
                      help="arguments passed to `streamlit run`, e.g. `--server.port 8502`")

    # Everything after `dashboard` / `transform` goes unchanged to streamlit / dbt
    # (e.g. `jobintel dashboard --server.port 8502`, `jobintel transform --select x`).
    argv = list(sys.argv[1:] if argv is None else argv)
    passthrough: list[str] = []
    for i, token in enumerate(argv):
        if token in ("dashboard", "transform"):
            argv, passthrough = argv[:i + 1], argv[i + 1:]
            break
        if not token.startswith("-"):
            break
    args = parser.parse_args(argv)
    if args.cmd == "dashboard":
        args.streamlit_args = passthrough
    if args.cmd == "transform":
        args.dbt_args = passthrough
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.cmd == "dashboard":
        import subprocess

        from jobintel.config import PROJECT_ROOT
        app = PROJECT_ROOT / "dashboard" / "app.py"
        # Run from the project root so .streamlit/config.toml applies.
        return subprocess.call([sys.executable, "-m", "streamlit", "run", str(app),
                                *args.streamlit_args], cwd=PROJECT_ROOT)

    if args.cmd == "transform":
        from jobintel.transform import run_dbt
        return run_dbt(args.dbt_args or ["build"])

    if args.cmd == "enrich":
        from jobintel.enrich.store import enrich_versions, stale_version_ids
        with db.connect() as conn, conn.transaction():
            n = enrich_versions(conn, stale_version_ids(conn, force=args.force))
        print(f"enriched {n} posting versions")
        return 0

    if args.cmd == "evaluate":
        import json

        from jobintel.enrich.evaluate import EVAL_DIR, evaluate, format_report
        res = evaluate(args.set)
        print(format_report(res))
        if args.save:
            out = EVAL_DIR / f"results_{args.set}_{res.extractor_version}.json"
            out.write_text(json.dumps(res.to_dict(), indent=1), encoding="utf-8")
            print(f"\nsaved {out}")
        return 0

    if args.cmd == "db":
        with db.connect() as conn:
            applied = db.migrate(conn)
        print("applied: " + (", ".join(applied) or "nothing (up to date)"))
        return 0

    if args.cmd == "collect":
        names = sorted(REGISTRY) if args.all else args.source
        conn = None
        if not args.no_load:
            try:
                conn = db.connect()
            except Exception as exc:
                # Still collect: raw batches are saved and can be loaded later with replay.
                print(f"WARNING: database unavailable ({exc}); collecting raw data only. "
                      "Run `jobintel replay --all` once the database is back.", file=sys.stderr)
        try:
            results = collect_and_load(conn, names)
        finally:
            if conn is not None:
                conn.close()
        failed = False
        for r in results:
            if r.skipped:
                print(f"{r.source}: skipped ({r.skipped})")
                failed |= not args.all   # asked for explicitly, so not running is a failure
                continue
            status = r.batch.status if r.batch else "failed"
            print(f"{r.source}: batch={r.batch.batch_id if r.batch else '-'} status={status}"
                  + (f" error={r.error}" if r.error else ""))
            if r.load:
                _print_stats(r.load)
            failed |= status == "failed" or (r.load is not None and r.load.status != "success")
        return 1 if failed else 0

    if args.cmd == "load":
        with db.connect() as conn:
            stats = load_pending(conn, source_name=args.source)
        if not stats:
            print("nothing to load")
        for s in stats:
            _print_stats(s)
        return 0 if all(s.status == "success" for s in stats) else 1

    if args.cmd == "replay":
        with db.connect() as conn:
            stats = replay(conn, batch_id=args.batch,
                           source_name=None if args.all else args.source)
        for s in stats:
            _print_stats(s)
        return 0 if all(s.status == "success" for s in stats) else 1

    if args.cmd == "status":
        with db.connect() as conn:
            _print_status(conn, args.limit)
        return 0
    return 2


def _print_status(conn, limit: int) -> None:
    print("Latest batch per source:")
    rows = conn.execute(
        """select s.source_id, b.started_at, b.status, b.n_items, b.n_failed_items,
                  (select max(started_at) from ops.collection_batch x
                    where x.source_id = s.source_id and x.status in ('success', 'partial'))
           from ops.source s
           left join lateral (select * from ops.collection_batch b
                              where b.source_id = s.source_id
                              order by started_at desc limit 1) b on true
           order by 1""").fetchall()
    for src, started, status, n, nf, last_ok in rows:
        if started is None:
            print(f"  {src:<11} never collected")
            continue
        last_ok_text = f"{last_ok:%Y-%m-%d %H:%M}" if last_ok else "never"
        print(f"  {src:<11} last={started:%Y-%m-%d %H:%M} status={status} items={n} "
              f"failed_items={nf} last_success={last_ok_text}")
    print(f"\nLast {limit} load runs:")
    for r in conn.execute(
            """select l.load_run_id, b.source_id, l.mode, l.status, l.started_at,
                      extract(epoch from l.finished_at - l.started_at), l.n_collected,
                      l.n_accepted, l.n_rejected, l.n_duplicate, l.n_out_of_scope
               from ops.load_run l join ops.collection_batch b using (batch_id)
               order by l.load_run_id desc limit %s""", (limit,)):
        rid, src, mode, st, at, secs, col, acc, rej, dup, oos = r
        print(f"  #{rid:<4} {src:<11} {mode:<6} {st:<8} {at:%Y-%m-%d %H:%M} "
              f"{(secs or 0):5.1f}s collected={col} accepted={acc} rejected={rej} "
              f"duplicate={dup} out_of_scope={oos}")


if __name__ == "__main__":
    sys.exit(main())
