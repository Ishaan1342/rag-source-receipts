"""Content-addressed ingestion receipts. This module never fetches a URL."""
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(data):
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def timestamp(value):
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        dt = datetime.fromtimestamp(value, timezone.utc)
    elif isinstance(value, str):
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            raise ValueError("Timestamps require an explicit timezone")
    else:
        raise ValueError("Invalid timestamp")
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def public_url(url):
    if not isinstance(url, str):
        raise ValueError("URL must be a string")
    parts = urlsplit(url)
    if parts.scheme not in ("https", "http") or not parts.hostname:
        raise ValueError("An absolute HTTP(S) URL is required")
    blocked = ("token", "secret", "password", "signature", "credential", "authorization", "api_key", "apikey", "access_key")
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not any(word in k.lower() for word in blocked) and
             k.lower() not in ("key", "auth", "sig", "x-amz-security-token")]
    host = parts.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    if parts.port and not (parts.scheme == "https" and parts.port == 443 or parts.scheme == "http" and parts.port == 80):
        host += f":{parts.port}"
    return urlunsplit((parts.scheme, host, parts.path or "/", urlencode(sorted(query)), ""))


@dataclass(frozen=True)
class ProcessingConfig:
    pipeline_version: str = "1"
    extractor: str = "provided-text"
    extractor_version: str = "1"
    markdown_variant: str = "raw_markdown"
    language: str = "unspecified"
    chunk_size: int = 1000
    chunk_overlap: int = 100

    def fingerprint(self):
        fields = asdict(self)
        if any(not isinstance(fields[k], str) or not fields[k].strip()
               for k in ("pipeline_version", "extractor", "extractor_version", "markdown_variant", "language")):
            raise ValueError("Processing identifiers must be non-empty strings")
        if type(self.chunk_size) is not int or type(self.chunk_overlap) is not int or not 0 <= self.chunk_overlap < self.chunk_size:
            raise ValueError("Require 0 <= chunk_overlap < chunk_size")
        return digest(canonical(fields))


def create_receipt(content, source_url, *, final_url=None, config=None,
                   observed_at=None, fetched_at=None, cache_status="unknown", artifact_cached_at=None):
    if not isinstance(content, str):
        raise ValueError("Selected text content must be a string")
    if cache_status not in ("unknown", "miss", "hit", "hit_validated", "hit_fallback"):
        raise ValueError("Unknown cache status")
    cfg = config or ProcessingConfig()
    source, final = public_url(source_url), public_url(final_url or source_url)
    content_bytes = content.encode("utf-8")
    recipe_hash = cfg.fingerprint()
    content_hash = digest(content_bytes)
    observed = timestamp(datetime.now(timezone.utc).isoformat() if observed_at is None else observed_at)
    fetched, cached = timestamp(fetched_at), timestamp(artifact_cached_at)
    if any(t and datetime.fromisoformat(t.replace("Z", "+00:00")) >
           datetime.fromisoformat(observed.replace("Z", "+00:00")) for t in (fetched, cached)):
        raise ValueError("Fetch/cache timestamp cannot be after observation")
    receipt = dict(schema_version=1, source_url=source, final_url=final,
                   content_sha256=content_hash, processing_sha256=recipe_hash,
                   artifact_id=digest(canonical([content_hash, recipe_hash])),
                   utf8_bytes=len(content_bytes), observed_at=observed,
                   fetched_at=fetched, artifact_cached_at=cached, cache_status=cache_status,
                   markdown_variant=cfg.markdown_variant)
    return receipt


def from_crawl_result(result, *, config=None, observed_at=None, fetched_at=None):
    """Duck-typed Crawl4AI adapter. Cached-at is NOT asserted to be network fetch time."""
    def get(key, default=None):
        return result.get(key, default) if isinstance(result, dict) else getattr(result, key, default)
    if not get("success", False):
        raise ValueError("Cannot receipt an unsuccessful crawl")
    cfg = config or ProcessingConfig(extractor="crawl4ai")
    markdown = get("markdown")
    if isinstance(markdown, str) and cfg.markdown_variant == "raw_markdown":
        text = markdown
    elif isinstance(markdown, dict):
        text = markdown.get(cfg.markdown_variant)
    else:
        text = getattr(markdown, cfg.markdown_variant, None)
    if not isinstance(text, str):
        raise ValueError(f"Requested markdown variant is unavailable: {cfg.markdown_variant}")
    return create_receipt(text, get("url"), final_url=get("redirected_url"), config=cfg,
        observed_at=observed_at, fetched_at=fetched_at,
        cache_status=get("cache_status") or "unknown", artifact_cached_at=get("cached_at"))


def _validate_receipt(receipt):
    if not isinstance(receipt, dict) or receipt.get("schema_version") != 1:
        raise ValueError("Unsupported receipt schema")
    for name in ("source_url", "final_url"):
        public_url(receipt.get(name))
    for name in ("content_sha256", "processing_sha256", "artifact_id"):
        value = receipt.get(name)
        if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError(f"Invalid receipt field: {name}")
    if receipt["artifact_id"] != digest(canonical([receipt["content_sha256"], receipt["processing_sha256"]])):
        raise ValueError("Inconsistent artifact identifier")
    if type(receipt.get("utf8_bytes")) is not int or receipt["utf8_bytes"] < 0:
        raise ValueError("Invalid content byte count")


def verify_receipt(receipt, content, config):
    """Integrity check, NOT an authenticity signature or evidence the page is truthful."""
    if not isinstance(content, str):
        return False
    try:
        _validate_receipt(receipt)
    except (ValueError, TypeError):
        return False
    content_hash = digest(content.encode("utf-8"))
    recipe_hash = config.fingerprint()
    return (receipt.get("content_sha256") == content_hash and
            receipt.get("processing_sha256") == recipe_hash and
            receipt.get("artifact_id") == digest(canonical([content_hash, recipe_hash])) and
            receipt.get("utf8_bytes") == len(content.encode("utf-8")))


def compare(previous, current):
    """Decides artifact regeneration; timestamps alone never trigger re-embedding."""
    _validate_receipt(current)
    if previous is not None:
        _validate_receipt(previous)
    if previous is None:
        return dict(reembed=True, metadata_changed=True, reasons=["new_source"])
    if previous["source_url"] != current["source_url"]:
        raise ValueError("Receipts refer to different sources")
    reasons = []
    for key, reason in (("content_sha256", "content_changed"), ("processing_sha256", "processing_changed")):
        if previous[key] != current[key]:
            reasons.append(reason)
    metadata_changed = previous["final_url"] != current["final_url"]
    return dict(reembed=bool(reasons), metadata_changed=metadata_changed,
                reasons=reasons or (["redirect_changed"] if metadata_changed else ["unchanged"]))
