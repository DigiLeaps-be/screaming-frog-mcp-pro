# screaming-frog-mcp-pro

Een uitgebreide MCP-server voor Screaming Frog SEO Spider. Drop-in superset van [acamolese/screaming-frog-mcp](https://github.com/acamolese/screaming-frog-mcp), gebouwd op de [screamingfrog Python library](https://github.com/Amaculus/screaming-frog-api) van Amaculus.

Toegevoegd boven de upstream:

- **Derby-direct backend** afgedwongen, omdat de auto-promotie naar DuckDB in praktijk een lege cache produceert die SQL-queries breekt.
- **Fix voor `_rows_to_dicts`** waardoor `query_tab` op tabs zoals `internal_html.csv` nu alle 1250+ kolommen toont in plaats van 4.
- **Zes nieuwe tools**:
  - `list_db_tables` — alle 53+ Derby-tabellen met rij-aantallen
  - `describe_db_table` — kolommen + types per tabel
  - `query_sql` — vrije read-only SELECT, met inline tips over Derby-specifieke quirks
  - `discover_api_data` — toon welke API-tabellen data hebben in deze crawl
  - `cross_data_audit` — dynamische join URLS + elke gevulde API-tabel
  - `inspect_url` — alle data over één URL uit alle gevulde tabellen
- **Automatische detectie van API-bronnen**: `cross_data_audit` en `inspect_url` skippen automatisch lege tabellen en pikken nieuwe data op zodra je een API in Screaming Frog activeert.
- **Uitbreidbare API-registry**: nieuwe API-bron toevoegen is één dictionary-entry in `server.py`.
- **Pagination en projectie** op `query_tab` via `offset`, `total_rows` en `columns`.

## Waarom deze fork

De Screaming Frog crawl-database (Apache Derby) bevat per crawl ongeveer 53 tabellen, waaronder dedicated tabellen voor `AHREFS_API` (242 kolommen), `GA4` (72 kolommen), `GOOGLE_SEARCH_CONSOLE` (6 kolommen) en `PAGE_SPEED_API` (97 kolommen). De upstream library exposeert via `crawl.tab(...)` slechts een gemapte subset van die kolommen, en de `mapping.json` is voor de API-tabs incompleet (alleen 5 placeholder-kolommen voor `search_console_*` en `analytics_*`).

In praktijk betekent dat: zelfs wanneer Screaming Frog correct GSC, GA4 en Ahrefs data heeft opgehaald, ziet een MCP-call slechts `Address, Status Code, Title 1, Indexability` terug. De volledige API-data is onbereikbaar.

Deze fork omzeilt dat door direct tegen Derby te queryen via `crawl.sql()`. De rauwe API-tabellen worden zo direct toegankelijk, en de `cross_data_audit` tool brengt ze in één call samen op URL-niveau, met de juiste URL-normalisatie tussen de bronnen (Ahrefs gebruikt `http(s):...` notatie, GA4 strip protocol, GSC en PSI zijn 1-op-1 met `URLS.ENCODED_URL`).

Zie `docs/derby-fixes.md` voor de technische details, en `CHANGELOG.md` voor de exacte verschillen met upstream.

## Installatie

### Voor eindgebruikers (via een installer-script)

Als je werkt vanuit de Digileaps installer-package, hoef je hier niets te doen — het script handelt alles af. Zie de installer-instructies in dat package.

### Vanuit deze repo

```bash
git clone https://github.com/digileaps/screaming-frog-mcp-pro.git
cd screaming-frog-mcp-pro
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### Vereisten

- macOS (Apple Silicon of Intel) of Linux
- Python 3.10+
- OpenJDK 21 (de Derby-driver in recente Screaming Frog releases is gecompileerd voor Java 19+)
- Apache Ant (sommige builds van JPype1 vallen terug op een source build die Ant nodig heeft)
- Een Screaming Frog SEO Spider licentie als je crawls in DB-mode wil maken
- Crawls opgeslagen in DB Storage Mode (`Configuration > System > Storage Mode > Database Storage` in de SF GUI)

### Claude Desktop configuratie

Voeg toe aan `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "screaming-frog-pro": {
      "command": "/Users/<username>/path/to/screaming-frog-mcp-pro/.venv/bin/screaming-frog-mcp-pro",
      "env": {
        "JAVA_HOME": "/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home"
      }
    }
  }
}
```

Vervang `<username>` en het Java-pad door je eigen waardes. Op Intel Macs is het Java-pad `/usr/local/...`. Verifieer met `/usr/libexec/java_home -v 21`.

Cmd+Q Claude Desktop volledig en heropen om de nieuwe server te laden.

## Gebruik

Voorbeelden van prompts in Claude Desktop:

```
Lijst mijn Screaming Frog crawls.
Doe een cross-data audit op crawl <UUID>, gesorteerd op impressies, top 30.
Welke pagina's hebben veel backlinks maar staan op een 404?
Geef me alle pagina's op positie 4-15 in GSC met een CTR onder 1%.
Beschrijf de kolommen van APP.AHREFS_API.
```

Claude zal automatisch de juiste tool kiezen (`cross_data_audit`, `query_sql`, `describe_db_table`, etc.).

## Beschikbare tools

Bestaande van upstream (allemaal nog werkend):

- `load_crawl`, `crawl_summary`, `list_crawls`, `list_tabs`, `query_tab`
- `get_pages`, `get_links`
- `broken_links_report`, `title_meta_audit`, `indexability_audit`
- `redirect_chains_report`, `canonical_issues_report`, `hreflang_issues_report`
- `orphan_pages_report`, `security_issues_report`, `redirect_issues_report`, `nofollow_inlinks_report`
- `compare_crawls`

Toegevoegd in deze fork:

- `list_db_tables` — alle Derby-tabellen + rij-aantallen
- `describe_db_table` — kolommen + types
- `query_sql` — vrije SELECT op Derby (alleen lezen, geen INSERT/UPDATE/DELETE)
- `discover_api_data` — welke API-tabellen hebben data in deze crawl
- `cross_data_audit` — dynamische join URLS + alle gevulde API-tabellen (GSC, GA4, PSI, Ahrefs, URL Inspection, en uitbreidbaar)
- `inspect_url` — voor één URL alle data uit alle gevulde tabellen aggregeren

## Een nieuwe API-bron toevoegen

Wanneer Screaming Frog een nieuwe API toevoegt (bv. een nieuwe Bing-koppeling, Cloudflare-data, etc.) zijn er twee paden:

**Pad 1: query_sql + describe_db_table** (zonder code-wijziging). De data is meteen toegankelijk via Derby SQL. Vraag Claude:

> Doe `list_db_tables` op crawl X, kijk welke tabel nieuw is met data, doe daar `describe_db_table` op, en schrijf een query die hem joint met URLS.

Dat werkt direct zonder iets aan de fork te wijzigen.

**Pad 2: API-registry uitbreiden** (voor convenience). Open `src/screaming_frog_mcp_pro/server.py` en voeg een entry toe aan `_API_REGISTRY`:

```python
"NIEUWE_TABEL": {
    "alias": "nt",
    "join_pattern": "direct",   # of 'strip_protocol' / 'ahrefs_prefix'
    "select_columns": ["KOLOM_1", "KOLOM_2", "KOLOM_3"],
},
```

Vanaf dan pikken `cross_data_audit` en `inspect_url` deze tabel automatisch op.

Het juiste `join_pattern` bepaal je door één rij van de nieuwe tabel te bekijken en te vergelijken met `URLS.ENCODED_URL`:

- Begint met `https://` zoals URLS → `direct`
- Begint zonder protocol → `strip_protocol`
- Begint met `http(s):` → `ahrefs_prefix`

## Credits

Gebouwd bovenop:

- [acamolese/screaming-frog-mcp](https://github.com/acamolese/screaming-frog-mcp) — de originele MCP-server
- [Amaculus/screaming-frog-api](https://github.com/Amaculus/screaming-frog-api) — de Python library die Derby/DuckDB-toegang levert

Beide projecten staan onder MIT-licentie. Deze fork blijft onder MIT.

## Licentie

MIT, zie `LICENSE`.

## Bijdragen

Issues en PR's welkom. Specifiek welkom: Derby SQL-snippets voor andere veelvoorkomende analyses (link reclaim, content gap, schema-audit), en zelfde-style convenience-tools.
