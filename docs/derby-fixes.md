# Technische analyse: waarom deze fork bestaat

## TL;DR

Bij een Screaming Frog DB-crawl met API-koppelingen voor Ahrefs, GA4, GSC en PSI bevat de Derby-database alle data correct. De `Amaculus/screamingfrog` Python-library (waar `acamolese/screaming-frog-mcp` op bouwt) maakt die data niet bereikbaar omdat:

1. De auto-promotie naar DuckDB-cache slaat de meeste tabellen over.
2. De `mapping.json` die `crawl.tab(name)` aandrijft is incompleet voor de API-tabs.

Resultaat: een MCP-call krijgt slechts 4 kolommen of leeg-rijen waar honderden gevulde kolommen klaar staan in Derby.

## De stack

```
Claude Desktop
    └── claude_desktop_config.json
        └── screaming-frog-mcp (acamolese)
            └── screamingfrog (Amaculus Python lib)
                ├── DuckDBBackend  (cache-laag)
                └── DerbyBackend   (de echte DB)
                    └── Apache Derby (.dbseospider files in ProjectInstanceData/)
```

Een SF-crawl in DB-mode produceert een UUID-map onder `~/.ScreamingFrogSEOSpider/ProjectInstanceData/<UUID>/` (of op recentere SF-versies onder `~/Library/Application Support/Screaming Frog SEO Spider/...`). Daarin staat een Apache Derby database met 53 tabellen.

## Bug 1: lege DuckDB-cache

`Crawl.load(path)` op een Derby-pad routeert standaard naar `Crawl.from_derby(...)` met `backend="duckdb"`. Die functie roept `ensure_duckdb_cache(...)` aan om Derby-data te promoveren naar een DuckDB-bestand voor snellere queries.

In praktijk eindigt die DuckDB-cache met slechts 2 tabellen:

```
main.sf_alpha_exports   (4 kolommen)
main.sf_alpha_imports   (4 kolommen)
```

Allebei metadata-tabellen, geen crawl-data. Resultaat: `crawl.sql("SELECT * FROM URLS")` faalt met `Catalog Error: Table URLS does not exist`.

Tegelijk werkt `crawl.tab("internal_html.csv")` wél, omdat dat via een fallback-pad de data uit Derby haalt (`_attach_lazy_duckdb_source`). Maar `crawl.sql()` heeft die fallback niet, en valt dus terug op de lege cache.

**Fix**: forceer Derby door `dbseospider_backend="derby"` en `csv_fallback=False` in `Crawl.load(...)`. Dat geeft een echte `DerbyBackend` waar alle SQL tegen werkt.

```python
crawl = Crawl.load(path, dbseospider_backend="derby", csv_fallback=False)
```

## Bug 2: incomplete mapping.json

In `screamingfrog/resources/mapping.json` (9,4 MB, 628 tab-definities) zijn de API-tabs nauwelijks gemapt:

| Tab | Gemapte kolommen | Werkelijk in Derby |
|---|---:|---:|
| `pagespeed_all.csv` | 53 | 97 in `APP.PAGE_SPEED_API` |
| `analytics_all.csv` | 5 (placeholders) | 67 in `APP.GA4` |
| `search_console_all.csv` | 5 (placeholders) | 6 in `APP.GOOGLE_SEARCH_CONSOLE` |
| `internal_html.csv` | 1350 entries waarvan 4 CrUX | 209 in `APP.URLS` (geen API-data inline) |

Voor `internal_html` zit ALL crawl-metadata correct in de mapping (1350 derived columns op 209 raw kolommen door blob-extracties), maar de mapping kent geen extra kolommen voor GSC, GA4 of Ahrefs op de URLS-tabel. Reden: in moderne SF-versies zit die data niet meer inline, maar in dedicated tabellen.

Voor de dedicated tabs (`search_console_*`, `analytics_*`) heeft de mapping slechts 5 placeholder-kolommen (Address, Status Code, Title 1, Indexability, Indexability Status). De 102 echte GSC/GA4-kolommen staan niet in de mapping.

**Fix**: voor de echte API-data is `crawl.tab()` onbruikbaar. We querien rechtstreeks Derby-tabellen via `crawl.sql()` op `APP.GOOGLE_SEARCH_CONSOLE`, `APP.GA4`, `APP.AHREFS_API` en `APP.PAGE_SPEED_API`.

## Derby-specifieke quirks

Wie `query_sql` gebruikt moet rekening houden met:

### Geen REPLACE-functie

Derby heeft geen `REPLACE(string, search, replace)`. Workaround met `SUBSTR` en concatenatie via `||`:

```sql
-- Knip 'https://' van een URL af (8 chars, dus start op positie 9)
SUBSTR(u.ENCODED_URL, 9)

-- Vervang 'https://' door 'http(s):' (Ahrefs-notatie)
'http(s):' || SUBSTR(u.ENCODED_URL, 9)
```

### VARCHAR vs LONG VARCHAR vergelijkingen

Derby weigert direct vergelijkingen tussen `VARCHAR` en `LONG VARCHAR`:

```
ERROR 42818: Comparisons between 'VARCHAR (UCS_BASIC)' and 'LONG VARCHAR (UCS_BASIC)' are not supported.
```

Cast beide kanten van de join expliciet:

```sql
ON CAST(t1.ENCODED_URL AS VARCHAR(4096)) = CAST(t2.ENCODED_URL AS VARCHAR(4096))
```

### Pagination

Derby gebruikt SQL Standard, geen MySQL-style `LIMIT`:

```sql
SELECT ... FROM ... ORDER BY ... FETCH FIRST 100 ROWS ONLY
SELECT ... FROM ... ORDER BY ... OFFSET 100 ROWS FETCH NEXT 100 ROWS ONLY
```

## URL-normalisatie tussen bronnen

Bij het joinen van URLS met de API-tabellen verschilt de `ENCODED_URL` per bron:

| Bron | Voorbeeld | Hoe te joinen met `URLS.ENCODED_URL` |
|---|---|---|
| `URLS` | `https://lovebody.be/` | (referentie) |
| `GOOGLE_SEARCH_CONSOLE` | `https://lovebody.be/nl/...` | direct: `gsc.ENCODED_URL = u.ENCODED_URL` |
| `PAGE_SPEED_API` | `https://lovebody.be/...` | direct |
| `GA4` | `lovebody.be/nl/...` (geen protocol) | `ga.ENCODED_URL = SUBSTR(u.ENCODED_URL, 9)` |
| `AHREFS_API` | `http(s):lovebody.be/` (Ahrefs-notatie) | `ah.ENCODED_URL = 'http(s):' || SUBSTR(u.ENCODED_URL, 9)` |

Deze conventies werken voor HTTPS-only sites. Voor mixed HTTP/HTTPS sites is een `CASE WHEN` nodig op het protocol.

## Inhoud van een typische lovebody.be crawl

Voor referentie, een lovebody.be DB-crawl met 2.597 URLs en API-koppelingen heeft:

```
APP.URLS                  209 kolommen   2.597 rijen
APP.LINKS                  17 kolommen  44.932 rijen
APP.AHREFS_API            242 kolommen     557 rijen
APP.GA4                    72 kolommen     563 rijen
APP.GOOGLE_SEARCH_CONSOLE   6 kolommen     436 rijen
APP.PAGE_SPEED_API         97 kolommen     536 rijen
APP.URL_INSPECTION         22 kolommen       0 rijen   (URL Inspection API niet aangezet)
APP.GOOGLE_ANALYTICS      110 kolommen       0 rijen   (legacy GA Universal)
APP.MAJESTIC_API           49 kolommen       0 rijen   (provider niet gebruikt)
APP.MOZSCAPE_API           33 kolommen       0 rijen   (provider niet gebruikt)
... + 43 andere tabellen voor duplicates, multimaps, htmlvalidation, etc.
```

De fork's `cross_data_audit` tool joint URLS + de 4 gevulde API-tabellen op één URL-niveau in één Derby-call met de juiste casts en URL-normalisatie. Resultaat: één rij per URL met response code, word count, GSC clicks/impressions/CTR/position, GA4 sessions/engagement/key events/revenue, PSI score/LCP/CLS/TBT, en Ahrefs backlinks/ref domains/rank/traffic/keywords.

## Upstream-route

Wie deze fork wil terugbrengen naar upstream zou minstens twee PR's moeten openen:

1. Op `Amaculus/screaming-frog-api`: onderzoek waarom `ensure_duckdb_cache` slechts 2 metadata-tabellen exporteert. Mogelijk een filter op tabel-prefix of een namespace-issue.
2. Op `Amaculus/screaming-frog-api`: vul `mapping.json` aan voor `search_console_*` en `analytics_*` tabs met de echte GSC/GA4-kolommen op basis van de Derby-schemas.
3. Op `acamolese/screaming-frog-mcp`: fix in `_rows_to_dicts` voor de nested `data`-dict van `InternalPage`-style dataclasses.

Tot die merges plaats hebben, biedt deze fork directe toegang via de Derby-route.
