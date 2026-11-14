"""Command line: `uv run official-lines <command>`; `uv run official-lines --help` lists them."""

import argparse
import functools
import http.server
import logging
import sys

from official_lines.catalog import load_catalog
from official_lines.config import get_settings
from official_lines.db import connect, now_iso, transaction


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="official-lines", description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("sources", help="list the catalog and each source's last result")
    p = sub.add_parser("check", help="test sources without storing anything (default: the"
                       " candidates in sources.yaml)")
    p.add_argument("--source", help="only this source id")
    p.add_argument("--status", default="candidate", help="sources with this status ('all': every"
                   " source)")
    p = sub.add_parser("collect", help="fetch new statements from all enabled sources")
    p.add_argument("--source", help="only this source id")
    p = sub.add_parser("extract", help="LLM step 1: read new statements")
    p.add_argument("--limit", type=int)
    sub.add_parser("group", help="LLM step 2: group statement parts into events")
    p = sub.add_parser("analyze", help="LLM step 3: compare actors on multi-actor events")
    p.add_argument("--event", help="analyse this event slug now (ignores the daily cap)")
    p = sub.add_parser("issues", help="LLM step 4: file propositions of compared events under"
                       " issues (the daily run does this; here for a check or a redo)")
    p.add_argument("--all", action="store_true", help="discard every issue and file every"
                   " compared event again (issue page addresses change)")
    sub.add_parser("build", help="generate the static website")
    p = sub.add_parser("run", help="collect + extract + group + analyze + build (the daily job)")
    p.add_argument("--no-llm", action="store_true", help="only collect and build")
    p = sub.add_parser("brief", help="draft the weekly newsletter (Markdown)")
    p.add_argument("--days", type=int, default=7)
    for name in ("feature", "unfeature"):
        p = sub.add_parser(name, help=f"{name} an event (editor's pick)")
        p.add_argument("slug")
    p = sub.add_parser("golden", help="re-run the hand-judged comparisons in tests/golden and"
                       " check them (after changing prompts or metrics)")
    p.add_argument("--export", metavar="SLUG", help="write a new case from this event")
    p.add_argument("--case", help="run only the case with this file stem")
    sub.add_parser("costs", help="LLM spend this month and per step")
    p = sub.add_parser("serve", help="preview the generated site at http://localhost:8000")
    p.add_argument("--port", type=int, default=8000)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    for noisy in ("httpx", "httpx2", "anthropic"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    settings = get_settings()
    catalog = load_catalog(settings.sources_dir)
    conn = connect(settings.db_path)
    return COMMANDS[args.command](args, settings, catalog, conn) or 0


def _llm(settings, conn):
    from official_lines.llm.client import AnthropicLLM
    return AnthropicLLM(conn, settings.monthly_budget_usd)


def cmd_sources(args, settings, catalog, conn):
    from official_lines.collect.run import sync_sources
    sync_sources(conn, catalog)
    health = {r["id"]: r for r in conn.execute("SELECT * FROM sources")}
    for s in sorted(catalog.sources, key=lambda s: s.id):
        h = health[s.id]
        state = "off" if not s.enabled else ("ERR" if h["last_error"] else "ok ")
        print(f"{state}  {s.id:28} {s.kind:18} last_ok={(h['last_ok_at'] or '-')[:16]:16} "
              f"{h['last_error'] or ''}")
    on = len(catalog.enabled_sources())
    covered = len({s.actor for s in catalog.enabled_sources()})
    print(f"\n{on} enabled, {len(catalog.sources) - on} disabled, "
          f"{covered} of {len(catalog.actors)} actors covered")


def cmd_check(args, settings, catalog, conn):
    from official_lines.collect.check import check_source, format_result
    from official_lines.collect.http import PoliteClient
    chosen = [s for s in catalog.sources
              if (s.id == args.source if args.source else args.status in ("all", s.status))]
    if not chosen:
        print("no matching sources")
        return 1
    client = PoliteClient(settings.user_agent)
    verdicts = {}
    try:
        for s in chosen:
            print(f"checking {s.id} ({s.url}) ...", flush=True)
            r = check_source(s, client)
            verdicts[r.verdict] = verdicts.get(r.verdict, 0) + 1
            print(format_result(r), "\n", flush=True)
    finally:
        client.close()
    print("summary: " + ", ".join(f"{n} {v}" for v, n in sorted(verdicts.items())))


def cmd_collect(args, settings, catalog, conn):
    from official_lines.collect.http import PoliteClient
    from official_lines.collect.run import collect
    client = PoliteClient(settings.user_agent)
    try:
        results = collect(conn, catalog, client, settings.max_new_items_per_source,
                          only=getattr(args, "source", None))
    finally:
        client.close()
    failed = [r for r in results if r.error]
    print(f"collected {sum(r.new for r in results)} new statements from {len(results)} sources"
          f" ({len(failed)} failed)")


def cmd_extract(args, settings, catalog, conn):
    from official_lines.pipeline.extract import extract_pending
    n = extract_pending(conn, catalog, _llm(settings, conn), settings.extract_model,
                        getattr(args, "limit", None) or settings.max_extract_per_run)
    print(f"extracted {n} statements")


def cmd_group(args, settings, catalog, conn):
    from official_lines.pipeline.events import group_pending, merge_duplicates
    llm = _llm(settings, conn)
    n = group_pending(conn, catalog, llm, settings.extract_model)
    merged = merge_duplicates(conn, llm, settings.extract_model)
    print(f"grouped {n} statement parts into events; merged {merged} duplicate events")


def cmd_analyze(args, settings, catalog, conn):
    from official_lines.pipeline.analyze import analyze_due
    from official_lines.pipeline.issues import map_due
    llm = _llm(settings, conn)
    n = analyze_due(conn, catalog, llm, settings.analyze_model,
                    settings.max_analyses_per_day, only_slug=getattr(args, "event", None))
    print(f"analysed {n} events")
    m = map_due(conn, llm, settings.extract_model)
    print(f"filed the propositions of {m} events under issues")


def cmd_issues(args, settings, catalog, conn):
    from official_lines.pipeline import issues
    n_issues = conn.execute("SELECT COUNT(*) FROM issues").fetchone()[0]
    if args.all:
        due = conn.execute("SELECT * FROM events WHERE analysis IS NOT NULL").fetchall()
        n_issues = 0
    else:
        due = issues.events_due(conn)
    if not due:
        print(f"nothing to file: every compared event is filed ({n_issues} issues)")
        return
    props = sum(len(issues.propositions_of(e)) for e in due) / len(due)
    est = issues.estimate_cost(len(due), n_issues, props, settings.extract_model)
    print(f"{len(due)} compared events to file ({props:.1f} propositions each, {n_issues} "
          f"issues so far): estimated cost ${est:.2f} with {settings.extract_model}")
    started = now_iso()
    llm = _llm(settings, conn)
    n = issues.remap_all(conn, llm, settings.extract_model) if args.all \
        else issues.map_due(conn, llm, settings.extract_model)
    dropped = issues.drop_empty_issues(conn)
    spent = conn.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM llm_calls WHERE purpose=? AND"
                         " at >= ?", (issues.PURPOSE, started)).fetchone()[0]
    total = conn.execute("SELECT COUNT(*) FROM issues").fetchone()[0]
    print(f"filed {n} of {len(due)} events; {total} issues now"
          f"{f' ({dropped} empty ones dropped)' if dropped else ''}; cost ${spent:.3f}")


def cmd_build(args, settings, catalog, conn):
    from official_lines.site.build import build_site
    n = build_site(conn, catalog, settings.site_dir, settings.site_url, settings.briefs_dir)
    print(f"built {n} pages in {settings.site_dir}")


def cmd_run(args, settings, catalog, conn):
    from official_lines.llm.client import BudgetExceeded
    cmd_collect(args, settings, catalog, conn)
    if not args.no_llm:
        try:
            cmd_extract(args, settings, catalog, conn)
            cmd_group(args, settings, catalog, conn)
            cmd_analyze(args, settings, catalog, conn)
        except BudgetExceeded as e:
            logging.warning("%s Skipping the remaining LLM steps.", e)
    cmd_build(args, settings, catalog, conn)


def cmd_brief(args, settings, catalog, conn):
    from official_lines.pipeline.brief import write_brief
    path = write_brief(conn, catalog, _llm(settings, conn), settings.analyze_model,
                       settings.site_url, settings.briefs_dir, days=args.days)
    if path is None:
        print("no analysed events in that period; nothing to write")
        return 1
    print(f"draft written to {path}\nEdit it, then run `uv run official-lines build` to publish "
          f"it on the site and paste it into Substack.")


def cmd_feature(args, settings, catalog, conn, value=1):
    with transaction(conn):
        cur = conn.execute("UPDATE events SET featured=? WHERE slug=?", (value, args.slug))
    if not cur.rowcount:
        print(f"no event with slug {args.slug!r}")
        return 1
    print(f"{'featured' if value else 'unfeatured'} {args.slug}")


def cmd_golden(args, settings, catalog, conn):
    from official_lines.pipeline.golden import GOLDEN_DIR, export_case, run_cases
    if args.export:
        path = export_case(conn, args.export)
        print(f"wrote {path}\nFill in its \"expect\" block (see official_lines/pipeline/golden.py"
              f" for the keys), then run `uv run official-lines golden`.")
        return
    paths = sorted(GOLDEN_DIR.glob(f"{args.case or '*'}.json"))
    if not paths:
        print("no golden cases found; add one with --export SLUG")
        return 1
    failed = run_cases(catalog, _llm(settings, conn), settings.analyze_model, paths)
    print(f"{len(paths) - failed} of {len(paths)} cases pass")
    return 1 if failed else 0


def cmd_costs(args, settings, catalog, conn):
    from official_lines.llm.client import month_spend
    month = now_iso()[:7]
    print(f"{'step':10} {'model':20} {'calls':>6} {'in tok':>10} {'out tok':>10} {'USD':>8}")
    for r in conn.execute(
        "SELECT purpose, model, COUNT(*), SUM(input_tokens), SUM(output_tokens), SUM(cost_usd)"
        " FROM llm_calls WHERE substr(at,1,7)=? GROUP BY purpose, model", (month,)
    ):
        print(f"{r[0]:10} {r[1]:20} {r[2]:6} {r[3]:10} {r[4]:10} {r[5]:8.2f}")
    print(f"\n{month}: ${month_spend(conn):.2f} of ${settings.monthly_budget_usd:.2f} budget "
          "(upper estimate: cached input is counted at full price)")


def cmd_serve(args, settings, catalog, conn):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                directory=str(settings.site_dir))
    print(f"serving {settings.site_dir} at http://localhost:{args.port} (Ctrl+C to stop)")
    http.server.ThreadingHTTPServer(("127.0.0.1", args.port), handler).serve_forever()


COMMANDS = {
    "sources": cmd_sources, "check": cmd_check, "collect": cmd_collect, "extract": cmd_extract,
    "group": cmd_group, "analyze": cmd_analyze, "build": cmd_build, "run": cmd_run,
    "issues": cmd_issues, "brief": cmd_brief, "feature": cmd_feature,
    "unfeature": functools.partial(cmd_feature, value=0),
    "golden": cmd_golden, "costs": cmd_costs, "serve": cmd_serve,
}

if __name__ == "__main__":
    sys.exit(main())
