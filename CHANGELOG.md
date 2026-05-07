# Changelog

Format gebaseerd op [Keep a Changelog](https://keepachangelog.com/).

## [0.3.0] — 2026-05-07

Stabiliteits-release. Lost drie reproduceerbare faalmodes op die de server
onbruikbaar maakten op crawls van enkele duizenden URL's met API-data.

### Toegevoegd

- **Vaste Derby system home.** Derby krijgt nu expliciet een schrijfbare
  map (`~/.cache/screaming-frog-mcp-pro/derby` of via `SF_MCP_DERBY_HOME`)
  als `derby.system.home` en `derby.stream.error.file`. Geen
  "FileNotFoundException: derby.log (Read-only file system)" warnings meer
  bij elke `load_crawl`.
- **Wall-clock time-out per query.** Configureerbaar via
  `SF_MCP_QUERY_TIMEOUT_S` (default 60s) en `SF_MCP_LOAD_TIMEOUT_S`
  (default 120s, gebruikt voor `load_crawl`). Geeft een nette
  `TimeoutError` terug aan de MCP-client in plaats van pas te falen op de
  4-minuten MCP-grens.
- **Crawl-eviction na time-out.** Bij een time-out wordt het Crawl-object
  uit de cache gegooid. De volgende call opent een verse Derby-connectie
  in plaats van te wachten op de geblokkeerde. Eén trage query maakt de
  sessie niet meer dood.
- **`list_tabs` cache + `refresh` parameter.** Eerste call vult de cache,
  daarna instant. `refresh=True` forceert een re-read.
- **Eager warm-up in `load_crawl`.** Roept meteen na de Derby-connectie
  ook `crawl_summary` op en cached die. Daarmee is `crawl_summary` de
  rest van de sessie instant. Output bevat nu ook `urls_total`.

### Veranderd

- **`crawl_summary` herschreven als directe Derby aggregaat.** Eén query
  tegen `APP.URLS` met `SUM(CASE WHEN ...)`. Vervangt de upstream
  `crawl.summary()` die per tab queries deed en op crawls van een paar
  duizend URL's voorbij de 4-minuten MCP-grens ging.
  Output-velden zijn `total`, `internal_total`, `external_total`,
  `internal_html`, `ok_200`, `redirects_3xx`, `client_errors_4xx`,
  `server_errors_5xx`, `no_response`, `flagged_redirect`, `canonicalised`,
  `blocked_by_robots`, `soft_404`, `indexable`. Dit is een
  schema-wijziging tegenover 0.2.0; eerdere callers die de exacte vorm
  van `crawl.summary()` verwachtten moeten op deze nieuwe sleutels
  switchen.
- **Alle tools die queries uitvoeren** lopen nu door `_safe_call`, een
  wrapper die de bewerking in een daemon-thread runt met time-out en bij
  overschrijding de crawl uit de cache evict.
- **Foutformat.** Bij `TimeoutError` retourneren tools een compacte JSON
  zonder traceback, met `"type": "TimeoutError"`. Bij andere fouten
  blijft de bestaande shape (`error` + `traceback`) behouden.

### Niet veranderd

- Alle 18 tool-signatures van 0.2.0 blijven werken zoals voorheen, met
  uitzondering van het hierboven vermelde nieuwe veld in `list_tabs`
  (`refresh`) dat default `False` is.

### Nog niet opgelost (gepland voor 0.4.0)

- **Echte cancellation propagation** via JDBC `Statement.cancel()`. De
  huidige time-out laat de runaway query doorlopen op de JVM. De crawl
  wordt geëvict, dus volgende calls werken, maar de oude JDBC-thread
  blijft bestaan tot Derby zelf de query opgeeft of de sessie eindigt.
  Voor een schone fix moet de SQL-laag overstappen op directe JPype/JDBC
  in plaats van `crawl.sql()`.
- **Bounded connection pool met validatie**. Vereist eveneens directe
  JDBC-toegang.

### Migratie van 0.2.0

Drop-in. Geen config-wijziging nodig. Optioneel kun je deze env-vars
zetten in je `claude_desktop_config.json`:

```json
"env": {
  "JAVA_HOME": "/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home",
  "SF_MCP_DERBY_HOME": "/Users/<username>/.cache/screaming-frog-mcp-pro/derby",
  "SF_MCP_QUERY_TIMEOUT_S": "60",
  "SF_MCP_LOAD_TIMEOUT_S": "120"
}
```

## [0.2.0] — 2026-05-07

### Toegevoegd

- `discover_api_data(crawl_path)`: lijst alle geregistreerde API-tabellen in deze crawl met rij-aantallen, join-pattern en standaard-kolommen. Maakt onmiddellijk duidelijk welke API's data hebben en welke (nog) niet.
- `inspect_url(crawl_path, url)`: future-proof tool die voor één URL alle data haalt uit elke gevulde Derby-tabel met een `ENCODED_URL` kolom. Pakt automatisch URLS plus alle geregistreerde API-bronnen, plus signaleert nog niet-geregistreerde tabellen met data (bv. nieuwe SF-integraties) onder `other_populated_tables`. Filter automatisch BLOB/CLOB-kolommen om de output leesbaar te houden.
- **URL Inspection** (`APP.URL_INSPECTION`) is nu een eersteklas API-bron: wordt automatisch meegenomen in `cross_data_audit` en `inspect_url` zodra de tabel rijen heeft. Standaard-kolommen: `COVERAGE_STATE`, `INDEXING_STATE`, `USER_CANONICAL`, `GOOGLE_CANONICAL`, `DAYS_SINCE_LAST_CRAWL`, `RICH_RESULTS_VERDICT`.
- **Uitbreidbare `_API_REGISTRY`** in `server.py`. Inclusief stubs voor `GOOGLE_ANALYTICS` (legacy GA Universal), `MAJESTIC_API` en `MOZSCAPE_API`. Een nieuwe API-bron toevoegen vraagt één dictionary-entry.
- `cross_data_audit` heeft nieuwe `order_by` opties: `position`, `engagement`, `cls`, `ref_domains`, `ahrefs_traffic`, `days_since_crawl`. Plus een `include_extra` parameter om opt-in tabellen mee te nemen die geen default-kolommen hebben.
- `cross_data_audit` `populated_api_tables` veld in de output: laat zien welke bronnen daadwerkelijk meegenomen zijn voor deze crawl. Handig voor diagnose.
- `load_crawl` toont nu ook `populated_api_tables` zodat in één call duidelijk is wat beschikbaar is.

### Veranderd

- `cross_data_audit` is **dynamisch** geworden: bouwt zijn `SELECT` en `LEFT JOIN`-clauses op runtime op basis van welke API-tabellen rijen hebben. Lege tabellen worden geskipt in plaats van een `NULL`-kolom toe te voegen aan elke rij. Crawls met enkel GSC en GA4 (geen Ahrefs of PSI) krijgen nu een compactere, snellere output zonder lege Ahrefs-kolommen.
- `min_impressions` filter geeft nu een duidelijke foutmelding als GSC leeg is in de crawl, in plaats van een Derby-error.
- Wanneer de gevraagde `order_by` kolom verwijst naar een tabel die geen rijen heeft in deze crawl, valt de query terug op `u.CRAWL_DEPTH ASC` in plaats van een SQL-fout.
- MCP server-naam is nu `Screaming Frog SEO Pro` (was `Screaming Frog SEO`) zodat hij in tooling onderscheidbaar is van de upstream.

### Niet veranderd

- Alle 18 bestaande tool-signatures van upstream + `query_tab` extras blijven werken zoals in 0.1.0.

## [0.1.0] — 2026-05-07

Eerste release. Fork van [acamolese/screaming-frog-mcp v0.1.0](https://github.com/acamolese/screaming-frog-mcp/blob/main/src/screaming_frog_mcp/server.py) met de volgende wijzigingen:

### Toegevoegd

- `list_db_tables(crawl_path)`: lijst alle 53 Derby-tabellen in APP-schema met rij-aantal en aantal kolommen.
- `describe_db_table(crawl_path, table_name)`: lijst alle kolommen + datatypes voor één tabel.
- `query_sql(crawl_path, sql, limit)`: vrije read-only SELECT/WITH query tegen Derby. Schrijf-operaties (INSERT, UPDATE, DELETE, DROP, ALTER, etc.) worden geweigerd. Voegt automatisch `FETCH FIRST n ROWS ONLY` toe wanneer ontbrekend. Inline tips in de docstring over Derby-quirks.
- `cross_data_audit(crawl_path, order_by, min_impressions, only_internal, only_200, limit)`: convenience-tool die `URLS`, `GOOGLE_SEARCH_CONSOLE`, `GA4`, `PAGE_SPEED_API` en `AHREFS_API` joint met de juiste URL-normalisatie.
- Pagination en projectie op `query_tab`: `offset` parameter en `columns` parameter. Plus `total_rows` in de response.

### Veranderd

- `_get_crawl()` forceert nu `dbseospider_backend='derby'` en `csv_fallback=False`. Reden: de auto-promotie naar DuckDB die de upstream library standaard doet, produceert in praktijk een lege cache (alleen 2 metadata-tabellen). Met de Derby-backend werken zowel `crawl.tab()` als `crawl.sql()`.
- `_normalize_row()`: pakt de nested `data` dict van `InternalPage`-style dataclasses uit zodat alle kolommen zichtbaar zijn. Voorheen retourneerde dit slechts 4 top-level velden waarbij de echte data verstopt zat in de geneste `data` dict.

### Niet veranderd

- Alle bestaande tool-signatures van acamolese/screaming-frog-mcp.
