from dataclasses import replace
from types import SimpleNamespace
import unittest
from source_receipts.core import (
    ProcessingConfig,
    compare,
    create_receipt,
    from_crawl_result,
    public_url,
    verify_receipt,
)

STAMP = "2026-11-05T18:00:00Z"


class ReceiptTests(unittest.TestCase):
    def make(self, content="Hallo 🌍", **kwargs):
        return create_receipt(
            content, "https://example.org/events", observed_at=STAMP, **kwargs
        )

    def test_unchanged_content_does_not_reembed_on_new_observation(self):
        a = self.make()
        b = create_receipt(
            "Hallo 🌍", a["source_url"], observed_at="2026-11-06T18:00:00Z"
        )
        self.assertFalse(compare(a, b)["reembed"])
        self.assertEqual(a["utf8_bytes"], len("Hallo 🌍".encode()))

    def test_content_and_recipe_changes_both_invalidate(self):
        a = self.make()
        self.assertEqual(compare(a, self.make("new"))["reasons"], ["content_changed"])
        b = self.make(config=ProcessingConfig(chunk_size=500))
        self.assertEqual(compare(a, b)["reasons"], ["processing_changed"])

    def test_redirect_only_updates_metadata(self):
        result = compare(self.make(), self.make(final_url="https://example.org/new"))
        self.assertFalse(result["reembed"])
        self.assertTrue(result["metadata_changed"])

    def test_cache_time_is_never_presented_as_network_fetch(self):
        obj = SimpleNamespace(
            success=True,
            url="https://example.org/events",
            redirected_url=None,
            markdown=SimpleNamespace(raw_markdown="cached text", fit_markdown=None),
            cache_status="hit",
            cached_at=1700000000,
        )
        r = from_crawl_result(obj, observed_at=STAMP)
        self.assertIsNone(r["fetched_at"])
        self.assertEqual(r["artifact_cached_at"], "2023-11-14T22:13:20Z")

    def test_missing_variant_and_failed_crawl_rejected(self):
        for obj in (
            {"success": False},
            {"success": True, "markdown": {"fit_markdown": None}},
        ):
            with self.assertRaises(ValueError):
                from_crawl_result(
                    obj, config=ProcessingConfig(markdown_variant="fit_markdown")
                )

    def test_userinfo_fragment_and_secret_query_not_retained(self):
        u = public_url(
            "https://user:private@example.org/x?api_key=hidden&lang=de&access_token=hidden2#private"
        )
        self.assertEqual(u, "https://example.org/x?lang=de")

    def test_hash_detects_tampering(self):
        r = self.make()
        self.assertTrue(verify_receipt(r, "Hallo 🌍", ProcessingConfig()))
        self.assertFalse(verify_receipt(r, "changed", ProcessingConfig()))
        self.assertFalse(
            verify_receipt(r, "Hallo 🌍", ProcessingConfig(pipeline_version="2"))
        )

    def test_naive_or_future_dates_and_invalid_chunking_rejected(self):
        for dt in (
            "2026-11-05T18:00:00",
            "2027-01-01T00:00:00Z",
            "2026-11-05T18:00:00.000001Z",
        ):
            with self.assertRaises(ValueError):
                self.make(fetched_at=dt)
        with self.assertRaises(ValueError):
            self.make(config=ProcessingConfig(chunk_size=0))

    def test_cross_source_comparison_is_not_silently_accepted(self):
        with self.assertRaises(ValueError):
            compare(
                self.make(),
                create_receipt("hi", "https://other.example/", observed_at=STAMP),
            )

    def test_dict_adapter_preserves_empty_selected_text(self):
        r = from_crawl_result(
            {
                "success": True,
                "url": "https://example.org",
                "markdown": {"raw_markdown": ""},
            },
            observed_at=STAMP,
        )
        self.assertEqual(r["utf8_bytes"], 0)

    def test_incomplete_receipts_are_rejected_before_comparison(self):
        for bad in (
            None,
            {},
            {"schema_version": 1},
            {**self.make(), "artifact_id": "0" * 64},
        ):
            with self.assertRaises(ValueError):
                compare(None, bad)
            self.assertFalse(verify_receipt(bad, "Hallo 🌍", ProcessingConfig()))

    def test_empty_observation_timestamp_is_not_silently_replaced(self):
        with self.assertRaises(ValueError):
            create_receipt("text", "https://example.org", observed_at="")


if __name__ == "__main__":
    unittest.main()
