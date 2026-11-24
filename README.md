# Tyre Finder — сравнение на цени на гуми

A PySide6 desktop app that searches Bulgarian online tyre shops by **size** (width / profile /
rim) and **season**, groups identical tyres across shops and shows a price comparison with
images, links and filters. The UI is in Bulgarian; code and docs are in English.

## Run

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12+.

```bash
uv sync
uv run tyre-finder          # or: uv run python -m tyre_finder
```

Development:

```bash
uv run pytest               # parser tests use real saved HTML from every shop
uv run ruff check . && uv run ruff format --check .
QT_QPA_PLATFORM=offscreen uv run python tools/screenshot.py /tmp/shot   # live screenshots
```

## Features

* Dropdowns for width, profile, rim and season (summer / winter / all-season).
* Concurrent search of all enabled shops in a background `QThread` with a progress bar,
  per-shop status (offers, time, errors) and **Cancel** (Esc). A failing shop never breaks
  the others. Results stream in as each shop answers.
* **Grouped results (default view):** every tyre model (same brand + model/pattern + size +
  load/speed index, normalised; EAN when available) is one card with the best price, a
  "★ Най-добра цена" badge, the possible saving and an expandable list of **all shops** with
  price, difference to the cheapest and an **Отвори** button (opens the browser).
* Filters: min/max price (on the best price of a group), brand multi-select (searchable,
  all/clear, counts per brand, pre-selection possible before searching), "only tyres in 2+
  shops", sort by price ↑/↓, number of shops or brand.
* Thumbnails are loaded asynchronously (Qt network stack) with memory + disk cache.
* Light/dark theme (remembered), window size/position and last search are remembered,
  High-DPI aware, tooltips everywhere.
* **Sites dialog (Сайтове):** enable/disable, add, edit, remove, test and reset to defaults.
  New shops can be added as
  * **NK platform template** – shops built on the NK Software e-shop (bggumi.com,
    gumi3.com, gumi-varna.com …) need only the base URL;
  * **Generic scraper** – search URL template with `{width}` `{profile}` `{rim}` `{season}`
    (+ optional page suffix with `{page}`), season value mapping and CSS selectors for
    item / title / price / link / image / brand / size (`css@attr` reads an attribute).
    The **Тест** button runs a sample search and shows how many offers were recognised.
  The list is stored as JSON in the user config dir (e.g. `~/.config/tyre-finder/sites.json`
  on Linux, `%LOCALAPPDATA%\tyre-finder\sites.json` on Windows). Built-in shops can be
  disabled; their dedicated parsers always stay in the code.

## Promo codes (Промокодове)

While the tyres are being searched, a second background thread looks for **current** promo
codes for every enabled shop (cached for 6 h in the user cache dir, `promos.json`).

Sources, per shop:

1. **The shop's own site** – home page plus known promo pages (Диана `/promo`, Примекс
   `/vsichki-oferti.html`, SuperGumi `/promocii-na-gumi`, 24Gumi payment page). The text is
   scanned for codes right after "код", "промокод", "код за отстъпка", "coupon"…, and for
   code-less discounts such as "2% отстъпка при плащане с карта". Медина-Мед has a dedicated
   parser for `medina-med.com/promotsii/` campaign pages ("Промо код" field, Lidl Plus codes).
   Gumi7 product badges like "-3% с код: SUM26" are read from the search results.
2. **Bulgarian coupon sites** – kuponovo.bg (codes in clear text in the page JSON),
   cuponeria.bg and discounts.bg (codes hidden behind a click: only the hint, the
   conditions and the expiry date are shown, with a link to the source).
3. **Open web search** (`Промокодове → Настройки за търсене…`), two queries per shop
   (`"<shop>" OR "<domain>" промокод OR "промо код" OR "код за отстъпка"` and
   `"<domain>" promo code OR coupon`), restricted to the last month where the engine
   supports it. The top result pages that mention the shop are opened and code candidates
   near the keywords are scored (keyword right before the code, shop name nearby, a
   discount, a current date). Codes below the threshold are shown as **„възможен код“** and
   are never applied to the price unless „Включи и възможни кодове“ is ticked.
   Engines (`auto` = in this order):
   * **Google Programmable Search** (Custom Search JSON API) – your API key + CX,
     100 free queries/day, `dateRestrict=m1`;
   * **Brave Search API** – optional key, `freshness=pm`;
   * **Bing** and **DuckDuckGo HTML** – no key. Both often answer data-centre/VPN IPs with
     a bot challenge or an empty page; that is detected and shown as "блокирано".
   google.com itself is never scraped.

**Only current codes** are kept: a code with an expiry date in the past (BG formats like
"до 30.11.2026", "валиден до 5 декември 2026", "Период: 01.11.2026 – 30.11.2026",
ISO dates) is dropped; a code with no expiry is kept only if its page/listing was published
within the last 30 days (configurable) – taken from `article:published_time`, JSON-LD
`datePublished`, the aggregator's "last updated" or the search-result date. Every code shows
"валиден до …" or "публикуван на …".

**Effective price.** The promo price is computed only when the discount is unambiguous:
a percentage (per tyre and for a set of 4) or a fixed amount (taken off the order, shown
for 4 tyres). Minimum order value and minimum quantity are respected; brand restrictions
(e.g. Медина-Мед's Lidl Plus 6% for Nokian, Yokohama, Semperit, Kleber, Tigar, Radar) are
honoured; "up to X%" / "selected products" / non-tyre codes are shown but not computed.
With **„Смятай с промокод“** (default on) the best offer, price filter and sorting use the
effective price; cards show "с промокод …", the old price struck through and the code with a
copy button, conditions tooltip and a source link. Codes come from public sources and may
be expired — the app says so in the sidebar and in every tooltip.

**Manual codes:** `Сайтове → Промокод…` adds codes you know (newsletter, e-mail, Facebook)
per shop: code, % or €, min order, min quantity, brands, valid until. They are stored with
the site in `sites.json` and used like confirmed codes.

### Google API key + CX (2 minutes)

1. Open <https://programmablesearchengine.google.com/> → **Add**, choose *Search the entire
   web*, create it and copy the **Search engine ID** (this is the *CX*).
2. Open <https://console.cloud.google.com/>, create/select a project, go to
   *APIs & Services → Library*, enable **Custom Search API**, then *Credentials →
   Create credentials → API key*.
3. In the app: **Промокодове → Настройки за търсене…**, paste the key and the CX, choose
   "Google Programmable Search" or "Автоматично", **Запази**.

The keys are stored only in your user config file
(`~/.config/tyre-finder/promo_settings.json` on Linux,
`%LOCALAPPDATA%\tyre-finder\promo_settings.json` on Windows; file mode 600 where supported)
and never in the code. With a 6 h cache and 2 queries per shop, 12 shops stay within the
100 free queries/day.

### What was found on 23.11.2026

| Shop | Current code / discount | Source |
|------|-------------------------|--------|
| Медина-Мед | −6 % with a **personal** Lidl Plus code, Nokian/Yokohama/Semperit/Kleber/Tigar/Radar, 01–30.11.2026 | https://medina-med.com/promotsii/vzemi-6-otstapka-za-gumi-s-lidl-plus-2984/ |
| 24Gumi | −2 % automatically when paying by card (no code) | https://24gumi.bg/pages/15-плащане |
| Tirendo | none current (newsletter 10 % listing from 20.04.2026; Black Friday 5 % code expired 19.04.2026) | kuponovo.bg, discounts.bg |
| Gumi7 | none current (newsletter 10 % listing from 20.04.2026) | kuponovo.bg |
| eMAG | codes exist (MultiDeals1 until 02.12.2026, SmartGadgets …) but none for tyres | kuponovo.bg |
| Диана, Примекс, ProGumi, BG Gumi, SuperGumi, Gumi-Varna, Gumi3 | no published code | shop sites; not listed on the coupon sites |

## Default shops (12)

| Shop | URL | How it is searched |
|------|-----|--------------------|
| eMAG | https://www.emag.bg/ | text search in the tyre category, filtered by size/season |
| Гуми Диана | https://diana-ltd.com/ | `/tires?width=&aspect_ratio=&diameter=&tire_type[]=` |
| Gumi7 | https://gumi7.com/bg/ | `/bg/avtomobilni-gumi/?width=&height=&diameter=&tire_season=` (JSON in tiles) |
| Примекс | https://primex-bg.com/ | `/spisak-produkti.html?width=&ratio=&rim=&season[...]=1` |
| ProGumi | https://progumi.bg/ | `/bg/avtomobilni-gumi?tire-season=&tire-width=&tire-height=&tire-diameter=` |
| BG Gumi | https://www.bggumi.com/ | NK platform `eshop/search?...&season=` |
| SuperGumi | https://www.supergumi.bg/ | site search form `eshop/search?type=1&width=&height=&inch=&season={1 winter,2 summer,3 all}&page=` |
| Gumi-Varna | https://www.gumi-varna.com/ | NK platform |
| Tirendo | https://www.tirendo.bg/ | `/search?width=&profile=&size=&season={so,wi,gan}` (schema.org microdata) |
| 24Gumi | https://24gumi.bg/ | `/gumi/{season}/205-55-16/all/{page}/` |
| Медина-Мед | https://medina-med.com/ | `/katalog-gumi/?season_id=&width=&height=&rim=&p=` |
| Gumi3 | https://www.gumi3.com/ | NK platform |

All prices are shown as the shops show them (EUR — Bulgaria uses the euro since 2026; BGN
values, if a shop shows only BGN, are converted at 1.95583 for filtering and sorting).

## Project layout

```
src/tyre_finder/
  app.py               entry point, logging (rotating file in the user log dir), High-DPI
  models.py            dataclasses: TyreSize, SearchQuery, TyreOffer, TyreGroup, SiteResult
  data/                data layer
    http.py            polite httpx client: UA, timeouts, per-host delay, retries, cancel
    base.py            abstract TyreScraper (build_url, parse, search, filter_matching)
    parsing.py         price / size / season helpers
    brands.py          known brands, aliases, brand/model splitting
    site_config.py     SiteConfig, defaults, JSON store, scraper factory
    sites/             one module per shop + nk_platform.py + generic.py
    promo/             promo codes: shop pages, coupon sites, web search engines,
                       date/freshness rules, extraction, cache, settings, service
  logic/               logic layer
    search.py          SearchOrchestrator (ThreadPoolExecutor, per-site isolation)
    normalize.py       brand/model normalisation and match keys
    grouping.py        grouping identical tyres across shops
    filters.py         price/brand/multi-shop filters, sorting, brand counts
    promo.py           effective promo prices (percent / fixed / min order / brands)
  ui/                  PySide6 UI (main window, cards, sites dialog, theme, icons, workers)
tests/                 pytest; fixtures/ = real HTML responses saved from each shop,
                       fixtures/promo/ = promo pages (real + clearly marked synthetic)
tools/screenshot.py    offscreen live screenshots
```

## Politeness and limits

* Realistic browser User-Agent and headers (Accept, Accept-Language bg, Sec-Fetch-*,
  Referer = the shop home page), 20 s timeout, ≥0.8 s between requests to the same host,
  max 2 result pages per shop (NK platform, Diana and Primex: 1 page — the cheapest
  results / complete list), retries with back-off only for 403/429/502/503/511 (never for
  an anti-bot challenge page). If page 2 fails, the page-1 results are kept.
* **Gumi7** is behind Cloudflare. The app opens the home page once first (session
  cookies, like a visitor) and then searches. If Cloudflare answers with its JavaScript
  check ("Just a moment…", `cf-mitigated: challenge`), the app does **not** try to solve or
  bypass it; the status shows "Блокиран достъп: Cloudflare JavaScript проверка". This
  depends on Cloudflare's score for your IP/network and usually passes after some time.
* **eMAG** is protected by AWS WAF. From a normal home connection it answers, but from
  data-centre IPs or after many requests it returns HTTP 511 with a CAPTCHA. The app does
  not try to bypass it; the shop is then shown as failed ("сайтът поиска CAPTCHA").
* NK platform shops (BG Gumi, Gumi3, Gumi-Varna) load further results with JavaScript, so
  only the first 25 results sorted by price (cheapest) are read.
* Shops change their HTML; if a parser breaks, the per-site status shows the error and the
  parser tests (with saved fixtures) help to fix it.

## Error messages (per-shop status and the Sites dialog "Тест")

| Status text | Meaning |
|-------------|---------|
| Блокиран достъп (HTTP 403) / … Cloudflare JavaScript проверка / … CAPTCHA (HTTP 511) / … твърде много заявки (HTTP 429) | The shop's protection refused the request. Try later or from another network; the app does not bypass protections. |
| Страницата не е намерена (HTTP 404) — сайтът е сменил адресите | The search URL no longer exists; the scraper needs an update. |
| Изтече времето за отговор / Мрежова грешка / Сървърна грешка | Network or server problem. |

Hover a status row for the full explanation.

## Changelog

* **1.1.1** — SuperGumi: switched to the site's own search URL (`eshop/search`); the old
  SEO URLs return HTTP 404 for many size/season combinations (e.g. 235/50 R18 summer and
  winter). Gumi7: browser-like headers without the custom UA token, home-page warm-up,
  Referer, retry with back-off on 403, clear Cloudflare-challenge detection. Clearer
  "blocked" vs "not found" messages; a failing page 2 no longer discards page 1.
* **1.1.0** — promo codes.

## Quick start

Windows: double-click `start.bat`. Linux/macOS: `./start.sh`. Both use uv when installed, otherwise create a local `.venv` with pip.

## Build an .exe

Windows: double-click `build_exe.bat` (or `build_exe.bat onefile` for a single file). Result: `dist\TyreFinder\TyreFinder.exe`. Linux/macOS: `./build_exe.sh`. PyInstaller builds for the OS it runs on.
