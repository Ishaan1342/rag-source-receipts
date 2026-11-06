# RAG Source Receipts

> **Early MVP · MIT · Python 3.11+**. Scope and integration limits are documented below.

## Install from this repository

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -e .
```

See [Contributing](CONTRIBUTING.md), [Security](SECURITY.md) and the
[Changelog](CHANGELOG.md). GitHub CI results, once available, are separate from
local test results.


Small, offline ingestion receipts linking selected text to its public source,
processing recipe and content digest. Re-embed only when text or processing
changes; a new observation timestamp alone does not invalidate embeddings.

## Try it

Python 3.11+, standard library only:

```sh
python -m source_receipts demo --output artifacts/demo.json
python -m source_receipts create examples/page.md --url https://example.org/events --output artifacts/receipt.json
python -m source_receipts compare examples/before.json examples/after.json
python -m unittest discover -s tests -v
```

`create` reads a local UTF-8 file; it never requests the URL. To record a known
network-fetch time, explicitly supply `--fetched-at` with an offset-aware ISO
timestamp. Unknown times remain null. Receipts store SHA-256 hashes and public
URL metadata, not the document body or authentication headers.

## Crawl4AI adapter

```python
from source_receipts.core import ProcessingConfig, from_crawl_result

receipt = from_crawl_result(
    crawl_result,
    config=ProcessingConfig(
        extractor="crawl4ai", extractor_version="0.9.5",
        markdown_variant="raw_markdown", pipeline_version="events-v1"
    ),
    # Pass only if the actual network fetch time is known:
    fetched_at=None,
)
```

Also accepts a serialized CrawlResult dictionary:

```sh
python -m source_receipts crawl-result examples/crawl-result.json
```

Supported variants are selected explicitly; missing `fit_markdown` never falls
back silently to raw text. An unsuccessful crawl is rejected. Crawl4AI's
`cached_at` is preserved as `artifact_cached_at`, **not** claimed to be the
network-fetch time. `observed_at` means receipt creation/observation only. The
adapter is tested with serialized and object-shaped fixtures matching the
upstream model fields; full Crawl4AI browser execution is not part of this MVP.

## Change semantics

- Different content or recipe: `reembed=true` with the cause listed.
- Changed redirect, same text/recipe: metadata update only.
- New source: initial ingestion required.
- Different source identities or schema versions: error, not a silent comparison.

The recipe covers extractor/version, selected Markdown, language and chunking.
Bump `pipeline_version` for other content-affecting behavior, including model or
prompt changes. Embedding-model changes are not inferred; include them in that
version if using this receipt to gate embedding generation. The library does
not implement crawling, chunking or embeddings.

## Boundaries

Hashes detect mismatched artifacts; they are **not signed provenance** and do
not prove source authenticity. `verify_receipt` verifies the text, recipe,
artifact ID and byte count, not URL truthfulness or fetch-time attestation.
URLs lose userinfo, fragments and common credential query parameters. Other
query parameters are retained because they may identify the content; callers
must sanitize business-sensitive parameters before passing URLs. Do not put
secrets into processing identifiers.

This implements a portable sidecar for the demand described in
[Crawl4AI #2307](https://github.com/unclecode/crawl4ai/issues/2307), not an
upstream-approved change. It uses existing crawl outputs instead of creating a
new crawler. Persistent indexing, signed receipts and production adapters are
future work.
