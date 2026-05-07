"""screaming-frog-mcp-pro: enhanced MCP server for Screaming Frog SEO Spider.

Drop-in superset van acamolese/screaming-frog-mcp met:
  - Derby-direct backend (omzeilt lege DuckDB-cache)
  - Fix voor _rows_to_dicts (uitpakken nested data dict)
  - Vier nieuwe tools voor directe Derby SQL-toegang
  - Dynamische cross-data audit met auto-skip lege tabellen
  - URL_INSPECTION + Ahrefs + GSC + GA4 + PSI + uitbreidbaar

Zie README.md, CHANGELOG.md, en docs/derby-fixes.md voor details.
"""
from __future__ import annotations

import json
import re
import traceback
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Screaming Frog SEO Pro")

# ---------------------------------------------------------------------------
# Crawl cache
# ---------------------------------------------------------------------------
_crawl_cache: dict[str, Any] = {}


def _get_crawl(crawl_path: str) -> Any:
    """Load a crawl, forcing Derby-direct backend (no DuckDB cache)."""
    from screamingfrog import Crawl

    path = str(Path(crawl_path).expanduser().resolve())
    if path not in _crawl_cache:
        _crawl_cache[path] = Crawl.load(
            path,
            dbseospider_backend="derby",
            csv_fallback=False,
        )
    return _crawl_cache[path]


# ---------------------------------------------------------------------------
# API table registry
# ---------------------------------------------------------------------------
# Hoe je een NIEUWE API-tabel toevoegt:
# 1. Voeg een entry toe aan _API_REGISTRY hieronder.
# 2. Geef alias (kort), join_pattern (zie _JOIN_PATTERNS), en kolommen.
# 3. Klaar; cross_data_audit en inspect_url pikken hem automatisch op.

_JOIN_PATTERNS = {
    "direct":
        "CAST({alias}.ENCODED_URL AS VARCHAR(4096)) = "
        "CAST(u.ENCODED_URL AS VARCHAR(4096))",
    "strip_protocol":
        "CAST({alias}.ENCODED_URL AS VARCHAR(4096)) = "
        "CAST(SUBSTR(CAST(u.ENCODED_URL AS VARCHAR(4096)), 9) AS VARCHAR(4096))",
    "ahrefs_prefix":
        "CAST({alias}.ENCODED_URL AS VARCHAR(4096)) = "
        "CAST('http(s):' || SUBSTR(CAST(u.ENCODED_URL AS VARCHAR(4096)), 9) "
        "AS VARCHAR(4096))",
}

_API_REGISTRY: dict[str, dict[str, Any]] = {
    "GOOGLE_SEARCH_CONSOLE": {
        "alias": "gsc",
        "join_pattern": "direct",
        "select_columns": [
            "CLICKS", "IMPRESSIONS", "CLICKTHROUGH_RATE", "POSITION",
        ],
    },
    "GA4": {
        "alias": "ga",
        "join_pattern": "strip_protocol",
        "select_columns": [
            "SESSIONS", "ENGAGEMENTRATE", "KEYEVENTS", "TOTALREVENUE",
        ],
    },
    "PAGE_SPEED_API": {
        "alias": "psi",
        "join_pattern": "direct",
        "select_columns": [
            "PERFORMANCE_SCORE", "LARGEST_CONTENTFUL_PAINT",
            "CUMULATIVE_LAYOUT_SHIFT", "TOTAL_BLOCKING_TIME",
        ],
    },
    "AHREFS_API": {
        "alias": "ah",
        "join_pattern": "ahrefs_prefix",
        "select_columns": [
            "BACKLINKS_EXACT", "REFDOMAINS_EXACT", "AHREFS_RANK_EXACT",
            "TRAFFIC", "KEYWORDS",
        ],
    },
    "URL_INSPECTION": {
        "alias": "uri",
        "join_pattern": "direct",
        "select_columns": [
            "COVERAGE_STATE", "INDEXING_STATE",
            "USER_CANONICAL", "GOOGLE_CANONICAL",
            "DAYS_SINCE_LAST_CRAWL", "RICH_RESULTS_VERDICT",
        ],
    },
    "GOOGLE_ANALYTICS": {
        "alias": "gau",
        "join_pattern": "strip_protocol",
        "select_columns": [],
    },
    "MAJESTIC_API": {
        "alias": "mj",
        "join_pattern": "direct",
        "select_columns": [],
    },
    "MOZSCAPE_API": {
        "alias": "moz",
        "join_pattern": "direct",
        "select_columns": [],
    },
}

_ORDER_BY_OPTIONS: dict[str, str] = {
    "impressions": "gsc.IMPRESSIONS DESC",
    "clicks": "gsc.CLICKS DESC",
    "position": "gsc.POSITION ASC",
    "sessions": "ga.SESSIONS DESC",
    "engagement": "ga.ENGAGEMENTRATE DESC",
    "lcp": "psi.LARGEST_CONTENTFUL_PAINT DESC",
    "cls": "psi.CUMULATIVE_LAYOUT_SHIFT DESC",
    "performance_score": "psi.PERFORMANCE_SCORE ASC",
    "backlinks": "ah.BACKLINKS_EXACT DESC",
    "ref_domains": "ah.REFDOMAINS_EXACT DESC",
    "ahrefs_traffic": "ah.TRAFFIC DESC",
    "days_since_crawl": "uri.DAYS_SINCE_LAST_CRAWL DESC",
}


def _table_row_count(crawl: Any, table: str) -> int | None:
    try:
        row = next(
            iter(crawl.sql(f'SELECT COUNT(*) AS C FROM APP."{table}"')),
            None,
        )
        return int(row["C"]) if row else 0
    except Exception:
        return None


def _populated_api_tables(crawl: Any) -> list[str]:
    populated = []
    for tbl in _API_REGISTRY:
        cnt = _table_row_count(crawl, tbl)
        if cnt and cnt > 0:
            populated.append(tbl)
    return populated


# ---------------------------------------------------------------------------
# Row normalization
# ---------------------------------------------------------------------------
def _normalize_row(row: Any) -> dict:
    if isinstance(row, dict):
        return dict(row)
    out: dict[str, Any] = {}
    if hasattr(row, "__dict__"):
        for k, v in row.__dict__.items():
            if k.startswith("_"):
                continue
            if k == "data" and isinstance(v, dict):
                for dk, dv in v.items():
                    out[dk] = dv
                continue
            out[k] = v
        return out
    if hasattr(row, "items"):
        return dict(row.items())
    if hasattr(row, "__dataclass_fields__"):
        for fname in row.__dataclass_fields__:
            v = getattr(row, fname, None)
            if fname == "data" and isinstance(v, dict):
                for dk, dv in v.items():
                    out[dk] = dv
            else:
                out[fname] = v
        return out
    return {"value": str(row)}


def _rows_to_dicts(rows: Any, limit: int = 200, offset: int = 0) -> list[dict]:
    results: list[dict] = []
    for i, row in enumerate(rows):
        if i < offset:
            continue
        if i - offset >= limit:
            break
        results.append(_normalize_row(row))
    return results


def _safe_json(obj: Any) -> str:
    return json.dumps(obj, default=str, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Bestaande tools (ongewijzigde signaturen, tenzij vermeld)
# ---------------------------------------------------------------------------


@mcp.tool()
def load_crawl(crawl_path: str) -> str:
    """Load a Screaming Frog crawl file and return basic info."""
    try:
        crawl = _get_crawl(crawl_path)
        info = {"status": "loaded", "path": crawl_path}
        if hasattr(crawl, "tabs"):
            info["available_tabs"] = (
                len(crawl.tabs) if not callable(crawl.tabs) else "unknown"
            )
        info["backend"] = type(crawl._backend).__name__
        info["populated_api_tables"] = _populated_api_tables(crawl)
        return _safe_json(info)
    except Exception as e:
        return _safe_json({"error": str(e), "traceback": traceback.format_exc()})


@mcp.tool()
def crawl_summary(crawl_path: str) -> str:
    """Get a high-level summary of the crawl."""
    try:
        crawl = _get_crawl(crawl_path)
        summary = crawl.summary()
        if isinstance(summary, dict):
            return _safe_json(summary)
        return str(summary)
    except Exception as e:
        return _safe_json({"error": str(e)})


@mcp.tool()
def get_pages(
    crawl_path: str,
    status_code: int | None = None,
    indexable: bool | None = None,
    search: str | None = None,
    section: str | None = None,
    fields: str | None = None,
    limit: int = 100,
) -> str:
    """Query pages from the crawl with optional filters."""
    try:
        crawl = _get_crawl(crawl_path)
        query = crawl.section(section) if section else crawl
        pages = query.pages()
        if status_code is not None:
            pages = pages.filter(status_code=status_code)
        if indexable is not None:
            pages = pages.filter(indexable=indexable)
        if search:
            pages = pages.search(search)
        if fields:
            field_list = [f.strip() for f in fields.split(",")]
            pages = pages.select(*field_list)
        rows = _rows_to_dicts(pages, limit=limit)
        return _safe_json({"count": len(rows), "pages": rows})
    except Exception as e:
        return _safe_json({"error": str(e), "traceback": traceback.format_exc()})


@mcp.tool()
def get_links(
    crawl_path: str,
    direction: str = "in",
    url: str | None = None,
    section: str | None = None,
    limit: int = 100,
) -> str:
    """Query inbound or outbound links."""
    try:
        crawl = _get_crawl(crawl_path)
        if url:
            links = crawl.inlinks(url) if direction == "in" else crawl.outlinks(url)
        else:
            query = crawl.section(section) if section else crawl
            links = query.links(direction)
        rows = _rows_to_dicts(links, limit=limit)
        return _safe_json({"count": len(rows), "direction": direction, "links": rows})
    except Exception as e:
        return _safe_json({"error": str(e), "traceback": traceback.format_exc()})


@mcp.tool()
def broken_links_report(crawl_path: str, limit: int = 200) -> str:
    """Report of all broken internal links with inlink counts."""
    try:
        crawl = _get_crawl(crawl_path)
        rows = _rows_to_dicts(crawl.broken_inlinks_report(), limit=limit)
        return _safe_json({"count": len(rows), "broken_links": rows})
    except Exception as e:
        return _safe_json({"error": str(e), "traceback": traceback.format_exc()})


@mcp.tool()
def title_meta_audit(crawl_path: str, limit: int = 200) -> str:
    """Audit page titles and meta descriptions."""
    try:
        crawl = _get_crawl(crawl_path)
        rows = _rows_to_dicts(crawl.title_meta_audit(), limit=limit)
        return _safe_json({"count": len(rows), "issues": rows})
    except Exception as e:
        return _safe_json({"error": str(e), "traceback": traceback.format_exc()})


@mcp.tool()
def indexability_audit(crawl_path: str, limit: int = 200) -> str:
    """Audit indexability of pages."""
    try:
        crawl = _get_crawl(crawl_path)
        rows = _rows_to_dicts(crawl.indexability_audit(), limit=limit)
        return _safe_json({"count": len(rows), "issues": rows})
    except Exception as e:
        return _safe_json({"error": str(e), "traceback": traceback.format_exc()})


@mcp.tool()
def redirect_chains_report(crawl_path: str, min_hops: int = 2, limit: int = 200) -> str:
    """Report redirect chains with at least min_hops hops."""
    try:
        crawl = _get_crawl(crawl_path)
        rows = _rows_to_dicts(
            crawl.redirect_chains_report(min_hops=min_hops), limit=limit
        )
        return _safe_json({"count": len(rows), "chains": rows})
    except Exception as e:
        return _safe_json({"error": str(e), "traceback": traceback.format_exc()})


@mcp.tool()
def canonical_issues_report(crawl_path: str, limit: int = 200) -> str:
    """Report of canonical issues."""
    try:
        crawl = _get_crawl(crawl_path)
        rows = _rows_to_dicts(crawl.canonical_issues_report(), limit=limit)
        return _safe_json({"count": len(rows), "issues": rows})
    except Exception as e:
        return _safe_json({"error": str(e), "traceback": traceback.format_exc()})


@mcp.tool()
def hreflang_issues_report(crawl_path: str, limit: int = 200) -> str:
    """Report of hreflang issues."""
    try:
        crawl = _get_crawl(crawl_path)
        rows = _rows_to_dicts(crawl.hreflang_issues_report(), limit=limit)
        return _safe_json({"count": len(rows), "issues": rows})
    except Exception as e:
        return _safe_json({"error": str(e), "traceback": traceback.format_exc()})


@mcp.tool()
def orphan_pages_report(
    crawl_path: str, only_indexable: bool = True, limit: int = 200
) -> str:
    """Report of orphan pages."""
    try:
        crawl = _get_crawl(crawl_path)
        rows = _rows_to_dicts(
            crawl.orphan_pages_report(only_indexable=only_indexable), limit=limit
        )
        return _safe_json({"count": len(rows), "orphans": rows})
    except Exception as e:
        return _safe_json({"error": str(e), "traceback": traceback.format_exc()})


@mcp.tool()
def security_issues_report(crawl_path: str, limit: int = 200) -> str:
    """Report of security issues."""
    try:
        crawl = _get_crawl(crawl_path)
        rows = _rows_to_dicts(crawl.security_issues_report(), limit=limit)
        return _safe_json({"count": len(rows), "issues": rows})
    except Exception as e:
        return _safe_json({"error": str(e), "traceback": traceback.format_exc()})


@mcp.tool()
def redirect_issues_report(crawl_path: str, limit: int = 200) -> str:
    """Report of redirect issues."""
    try:
        crawl = _get_crawl(crawl_path)
        rows = _rows_to_dicts(crawl.redirect_issues_report(), limit=limit)
        return _safe_json({"count": len(rows), "issues": rows})
    except Exception as e:
        return _safe_json({"error": str(e), "traceback": traceback.format_exc()})


@mcp.tool()
def nofollow_inlinks_report(crawl_path: str, limit: int = 200) -> str:
    """Report of pages reached only via nofollow inlinks."""
    try:
        crawl = _get_crawl(crawl_path)
        rows = _rows_to_dicts(crawl.nofollow_inlinks_report(), limit=limit)
        return _safe_json({"count": len(rows), "issues": rows})
    except Exception as e:
        return _safe_json({"error": str(e), "traceback": traceback.format_exc()})


@mcp.tool()
def compare_crawls(crawl_path_new: str, crawl_path_old: str) -> str:
    """Compare two crawls and return structural differences."""
    try:
        crawl_new = _get_crawl(crawl_path_new)
        crawl_old = _get_crawl(crawl_path_old)
        diff = crawl_new.compare(crawl_old)
        if hasattr(diff, "to_dict"):
            return _safe_json(diff.to_dict())
        if hasattr(diff, "__dict__"):
            return _safe_json(
                {k: v for k, v in diff.__dict__.items() if not k.startswith("_")}
            )
        return str(diff)
    except Exception as e:
        return _safe_json({"error": str(e), "traceback": traceback.format_exc()})


@mcp.tool()
def query_tab(
    crawl_path: str,
    tab_name: str,
    limit: int = 100,
    offset: int = 0,
    columns: list[str] | None = None,
) -> str:
    """Query a tab by name. Returns all mapped columns by default."""
    try:
        crawl = _get_crawl(crawl_path)
        iterator = crawl.tab(tab_name)
        rows = _rows_to_dicts(iterator, limit=limit, offset=offset)
        try:
            total = iterator.count() if hasattr(iterator, "count") else None
        except Exception:
            total = None
        if columns:
            wanted = set(columns)
            rows = [{k: v for k, v in r.items() if k in wanted} for r in rows]
        return _safe_json(
            {
                "tab": tab_name,
                "count": len(rows),
                "total_rows": total,
                "offset": offset,
                "rows": rows,
            }
        )
    except Exception as e:
        return _safe_json({"error": str(e), "traceback": traceback.format_exc()})


@mcp.tool()
def list_tabs(crawl_path: str) -> str:
    """List all available tabs in the crawl."""
    try:
        crawl = _get_crawl(crawl_path)
        tabs = crawl.tabs
        if callable(tabs):
            tabs = tabs()
        return _safe_json(
            {"tabs": list(tabs) if not isinstance(tabs, list) else tabs}
        )
    except Exception as e:
        return _safe_json({"error": str(e), "traceback": traceback.format_exc()})


@mcp.tool()
def list_crawls(project_root: str | None = None) -> str:
    """Discover available Screaming Frog crawls on this machine."""
    try:
        from screamingfrog import list_crawls as sf_list_crawls

        kwargs = {}
        if project_root:
            kwargs["project_root"] = project_root
        crawls = sf_list_crawls(**kwargs)
        results = []
        for info in crawls:
            entry = {}
            for attr in ("db_id", "url", "urls_crawled", "path"):
                if hasattr(info, attr):
                    entry[attr] = str(getattr(info, attr))
            results.append(entry)
        return _safe_json({"crawls": results})
    except Exception as e:
        return _safe_json({"error": str(e), "traceback": traceback.format_exc()})


# ---------------------------------------------------------------------------
# NIEUWE tools
# ---------------------------------------------------------------------------


@mcp.tool()
def list_db_tables(crawl_path: str) -> str:
    """List all tables in the underlying Derby DB with row + column counts."""
    try:
        crawl = _get_crawl(crawl_path)
        tables = list(
            crawl.sql(
                "SELECT s.TABLENAME "
                "FROM SYS.SYSTABLES s "
                "JOIN SYS.SYSSCHEMAS sc ON s.SCHEMAID = sc.SCHEMAID "
                "WHERE sc.SCHEMANAME = 'APP' "
                "ORDER BY s.TABLENAME"
            )
        )
        result = []
        for t in tables:
            name = t["TABLENAME"]
            try:
                cnt_row = next(
                    iter(crawl.sql(f'SELECT COUNT(*) AS C FROM APP."{name}"')),
                    None,
                )
                cnt = cnt_row["C"] if cnt_row else 0
            except Exception:
                cnt = None
            try:
                col_row = next(
                    iter(
                        crawl.sql(
                            "SELECT COUNT(*) AS N FROM SYS.SYSCOLUMNS c "
                            "JOIN SYS.SYSTABLES s ON c.REFERENCEID = s.TABLEID "
                            "JOIN SYS.SYSSCHEMAS sc ON s.SCHEMAID = sc.SCHEMAID "
                            "WHERE sc.SCHEMANAME = 'APP' AND s.TABLENAME = ?",
                            [name],
                        )
                    ),
                    None,
                )
                n_cols = col_row["N"] if col_row else None
            except Exception:
                n_cols = None
            result.append({"table": name, "columns": n_cols, "row_count": cnt})
        return _safe_json({"tables": result, "count": len(result)})
    except Exception as e:
        return _safe_json({"error": str(e), "traceback": traceback.format_exc()})


@mcp.tool()
def describe_db_table(crawl_path: str, table_name: str) -> str:
    """Show all columns (name + datatype) for a Derby table in APP schema."""
    try:
        if not re.match(r"^[A-Za-z0-9_]+$", table_name):
            return _safe_json({"error": "Invalid table name"})
        crawl = _get_crawl(crawl_path)
        cols = list(
            crawl.sql(
                "SELECT c.COLUMNNAME, c.COLUMNDATATYPE, c.COLUMNNUMBER "
                "FROM SYS.SYSCOLUMNS c "
                "JOIN SYS.SYSTABLES s ON c.REFERENCEID = s.TABLEID "
                "JOIN SYS.SYSSCHEMAS sc ON s.SCHEMAID = sc.SCHEMAID "
                "WHERE sc.SCHEMANAME = 'APP' AND s.TABLENAME = ? "
                "ORDER BY c.COLUMNNUMBER",
                [table_name.upper()],
            )
        )
        return _safe_json(
            {
                "table": table_name.upper(),
                "columns": [
                    {
                        "position": int(c["COLUMNNUMBER"]),
                        "name": c["COLUMNNAME"],
                        "type": str(c["COLUMNDATATYPE"]),
                    }
                    for c in cols
                ],
            }
        )
    except Exception as e:
        return _safe_json({"error": str(e), "traceback": traceback.format_exc()})


_SQL_FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|MERGE|CALL)\b",
    re.IGNORECASE,
)


@mcp.tool()
def query_sql(crawl_path: str, sql: str, limit: int = 200) -> str:
    """Run a read-only SELECT query against the Derby DB.

    Tips:
      - Tables: APP.URLS, APP.GOOGLE_SEARCH_CONSOLE, APP.GA4,
        APP.PAGE_SPEED_API, APP.AHREFS_API, APP.URL_INSPECTION, APP.LINKS, ...
        Use list_db_tables to see all tables.
      - Derby quirks:
        * No REPLACE() function. Use SUBSTR(...) and || for concat.
        * Compare strings of different types via CAST(... AS VARCHAR(4096)).
        * Pagination: FETCH FIRST n ROWS ONLY (not LIMIT n).
      - URL normalization for joins:
        * GSC, PSI, URL_INSPECTION use the same ENCODED_URL format as URLS.
        * GA4 strips the protocol: SUBSTR(URLS.ENCODED_URL, 9) for https://.
        * Ahrefs uses 'http(s):' prefix:
            'http(s):' || SUBSTR(URLS.ENCODED_URL, 9)
    """
    try:
        sql_clean = sql.strip().rstrip(";")
        upper = sql_clean.upper().lstrip()
        if not (upper.startswith("SELECT") or upper.startswith("WITH")):
            return _safe_json({"error": "Only SELECT/WITH statements allowed"})
        if _SQL_FORBIDDEN.search(sql_clean):
            return _safe_json({"error": "Write operations not allowed"})
        if (
            "FETCH FIRST" not in sql_clean.upper()
            and "FETCH NEXT" not in sql_clean.upper()
        ):
            sql_clean = f"{sql_clean} FETCH FIRST {int(limit)} ROWS ONLY"
        crawl = _get_crawl(crawl_path)
        rows = [dict(r) for r in crawl.sql(sql_clean)]
        return _safe_json({"count": len(rows), "rows": rows, "sql": sql_clean})
    except Exception as e:
        return _safe_json({"error": str(e), "traceback": traceback.format_exc()})


@mcp.tool()
def discover_api_data(crawl_path: str) -> str:
    """List which API tables in this crawl have data, with row counts."""
    try:
        crawl = _get_crawl(crawl_path)
        registered = []
        for tbl, cfg in _API_REGISTRY.items():
            cnt = _table_row_count(crawl, tbl)
            registered.append(
                {
                    "table": tbl,
                    "row_count": cnt,
                    "join_pattern": cfg["join_pattern"],
                    "default_columns": cfg["select_columns"],
                    "in_default_audit": bool(cfg["select_columns"]) and (cnt or 0) > 0,
                }
            )
        return _safe_json(
            {
                "registered_api_tables": registered,
                "note": (
                    "For non-registered tables (e.g. new SF API integrations), "
                    "use list_db_tables to discover them, describe_db_table to "
                    "see their schema, and query_sql for ad-hoc queries. "
                    "Or add them to _API_REGISTRY in server.py."
                ),
            }
        )
    except Exception as e:
        return _safe_json({"error": str(e), "traceback": traceback.format_exc()})


@mcp.tool()
def cross_data_audit(
    crawl_path: str,
    order_by: str = "impressions",
    min_impressions: int = 0,
    only_internal: bool = True,
    only_200: bool = True,
    limit: int = 50,
    include_extra: list[str] | None = None,
) -> str:
    """Cross-data audit join: URLS + every populated API table.

    Auto-skips empty API tables. Currently picks up: GSC, GA4, PSI, Ahrefs,
    URL Inspection. Plus opt-in via include_extra: GA Universal, Majestic,
    Mozscape.

    Args:
        crawl_path: Path to the crawl.
        order_by: 'impressions', 'clicks', 'position', 'sessions',
                  'engagement', 'lcp', 'cls', 'performance_score',
                  'backlinks', 'ref_domains', 'ahrefs_traffic',
                  'days_since_crawl'.
        min_impressions: Skip URLs with fewer GSC impressions than this.
        only_internal: Only internal URLs (default True).
        only_200: Only HTTP 200 URLs (default True).
        limit: Max rows.
        include_extra: Extra API tables to include, e.g. ['MAJESTIC_API'].
    """
    try:
        crawl = _get_crawl(crawl_path)
        populated = _populated_api_tables(crawl)

        extras = set(include_extra or [])
        for extra in extras:
            if extra not in populated and _table_row_count(crawl, extra):
                populated.append(extra)

        selects = [
            "CAST(u.ENCODED_URL AS VARCHAR(4096)) AS URL",
            "u.RESPONSE_CODE",
            "u.WORD_COUNT",
            "u.CRAWL_DEPTH",
        ]
        joins = []
        active_aliases = set()

        for tbl in populated:
            cfg = _API_REGISTRY[tbl]
            alias = cfg["alias"]
            active_aliases.add(alias)
            cols_to_select = cfg["select_columns"]
            if not cols_to_select and tbl in extras:
                schema_cols = list(
                    crawl.sql(
                        "SELECT c.COLUMNNAME FROM SYS.SYSCOLUMNS c "
                        "JOIN SYS.SYSTABLES s ON c.REFERENCEID = s.TABLEID "
                        "JOIN SYS.SYSSCHEMAS sc ON s.SCHEMAID = sc.SCHEMAID "
                        "WHERE sc.SCHEMANAME = 'APP' AND s.TABLENAME = ? "
                        "ORDER BY c.COLUMNNUMBER",
                        [tbl],
                    )
                )
                cols_to_select = [
                    c["COLUMNNAME"]
                    for c in schema_cols
                    if c["COLUMNNAME"] not in ("ENCODED_URL",)
                    and not c["COLUMNNAME"].endswith("_KEY")
                ][:10]

            for col in cols_to_select:
                selects.append(f'{alias}."{col}"')

            join_clause = _JOIN_PATTERNS[cfg["join_pattern"]].format(alias=alias)
            joins.append(f'LEFT JOIN APP."{tbl}" {alias} ON {join_clause}')

        where_parts = []
        if only_200:
            where_parts.append("u.RESPONSE_CODE = 200")
        if only_internal:
            where_parts.append("u.IS_INTERNAL = TRUE")
        if min_impressions > 0 and "gsc" in active_aliases:
            where_parts.append(f"gsc.IMPRESSIONS >= {int(min_impressions)}")
        elif min_impressions > 0:
            return _safe_json(
                {
                    "error": (
                        "min_impressions filter requested but GSC table is "
                        "empty in this crawl. Re-crawl with GSC API enabled "
                        "or set min_impressions=0."
                    )
                }
            )
        where_clause = " AND ".join(where_parts) if where_parts else "1=1"

        order_clause = _ORDER_BY_OPTIONS.get(order_by, _ORDER_BY_OPTIONS["impressions"])
        order_alias = order_clause.split(".")[0].strip()
        if order_alias not in active_aliases and order_alias != "u":
            order_clause = "u.CRAWL_DEPTH ASC"

        sql = (
            "SELECT " + ", ".join(selects) + " "
            "FROM APP.URLS u "
            + " ".join(joins) + " "
            + f"WHERE {where_clause} "
            + f"ORDER BY {order_clause} "
            + f"FETCH FIRST {int(limit)} ROWS ONLY"
        )

        rows = [dict(r) for r in crawl.sql(sql)]
        return _safe_json(
            {
                "count": len(rows),
                "order_by": order_by,
                "populated_api_tables": populated,
                "rows": rows,
            }
        )
    except Exception as e:
        return _safe_json({"error": str(e), "traceback": traceback.format_exc()})


@mcp.tool()
def inspect_url(crawl_path: str, url: str) -> str:
    """Aggregate ALL data about ONE URL across every populated API table.

    Future-proof: queries APP.URLS plus every populated API table
    (registered + new SF integrations) and returns one section per source.
    New API tables added by future Screaming Frog versions appear under
    'other_populated_tables' as a hint to extend the registry.

    Args:
        crawl_path: Path to the crawl.
        url: The full URL (including https://) to look up.
    """
    try:
        crawl = _get_crawl(crawl_path)
        result: dict[str, Any] = {"url": url, "sources": {}}

        def _strip_blobs(d: dict) -> dict:
            return {
                k: (str(v)[:300] if v is not None else None)
                for k, v in d.items()
                if "Blob" not in str(type(v)) and "Clob" not in str(type(v))
            }

        def _lookup(table: str, join_pattern: str) -> dict | None:
            if join_pattern == "direct":
                search_url = url
            elif join_pattern == "strip_protocol":
                if url.startswith("https://"):
                    search_url = url[8:]
                elif url.startswith("http://"):
                    search_url = url[7:]
                else:
                    search_url = url
            elif join_pattern == "ahrefs_prefix":
                if url.startswith("https://"):
                    search_url = "http(s):" + url[8:]
                elif url.startswith("http://"):
                    search_url = "http(s):" + url[7:]
                else:
                    search_url = "http(s):" + url
            else:
                search_url = url
            try:
                sql_q = (
                    f'SELECT * FROM APP."{table}" '
                    f"WHERE CAST(ENCODED_URL AS VARCHAR(4096)) = ? "
                    f"FETCH FIRST 1 ROW ONLY"
                )
                rows = list(crawl.sql(sql_q, [search_url]))
                return dict(rows[0]) if rows else None
            except Exception as e:
                return {"_error": str(e)[:200]}

        urls_row = _lookup("URLS", "direct")
        if urls_row:
            result["sources"]["URLS"] = _strip_blobs(urls_row)

        for tbl, cfg in _API_REGISTRY.items():
            cnt = _table_row_count(crawl, tbl)
            if not cnt:
                continue
            row = _lookup(tbl, cfg["join_pattern"])
            if row:
                result["sources"][tbl] = _strip_blobs(row)

        try:
            all_tables = list(
                crawl.sql(
                    "SELECT s.TABLENAME FROM SYS.SYSTABLES s "
                    "JOIN SYS.SYSSCHEMAS sc ON s.SCHEMAID = sc.SCHEMAID "
                    "WHERE sc.SCHEMANAME = 'APP'"
                )
            )
            unknown_with_data = []
            for t in all_tables:
                name = t["TABLENAME"]
                if name in _API_REGISTRY or name == "URLS":
                    continue
                if name.startswith("MULTIMAP_") or name.startswith("DUPLICATES_"):
                    continue
                cnt = _table_row_count(crawl, name)
                if cnt and cnt > 0:
                    unknown_with_data.append({"table": name, "row_count": cnt})
            if unknown_with_data:
                result["other_populated_tables"] = unknown_with_data[:20]
                result["hint"] = (
                    "Bovenstaande tabellen zijn niet in de API-registry. "
                    "Voor een nieuwe SF-integratie: voeg een entry toe aan "
                    "_API_REGISTRY in server.py, of gebruik query_sql voor "
                    "ad-hoc queries."
                )
        except Exception:
            pass

        return _safe_json(result)
    except Exception as e:
        return _safe_json({"error": str(e), "traceback": traceback.format_exc()})


# ---------------------------------------------------------------------------
def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
