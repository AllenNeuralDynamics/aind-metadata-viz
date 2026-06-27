"""Unit tests for the LLM endpoint security helpers."""

from __future__ import annotations

import unittest

from aind_metadata_viz.chat.security import (
    extract_json_field,
    is_origin_allowed,
)


class OriginAllowlistTests(unittest.TestCase):
    def test_apex_allowed(self):
        self.assertTrue(
            is_origin_allowed("https://allenneuraldynamics.org")
        )

    def test_subdomain_allowed(self):
        self.assertTrue(
            is_origin_allowed("https://data.allenneuraldynamics.org")
        )

    def test_nested_subdomain_allowed(self):
        self.assertTrue(
            is_origin_allowed(
                "https://metadata-portal.allenneuraldynamics.org"
            )
        )

    def test_port_allowed(self):
        self.assertTrue(
            is_origin_allowed("https://data.allenneuraldynamics.org:8443")
        )

    def test_localhost_allowed(self):
        self.assertTrue(is_origin_allowed("http://localhost:5006"))
        self.assertTrue(is_origin_allowed("http://127.0.0.1:3000"))

    def test_missing_origin_allowed(self):
        # Same-origin / non-browser requests send no Origin header.
        self.assertTrue(is_origin_allowed(None))
        self.assertTrue(is_origin_allowed(""))

    def test_foreign_origin_blocked(self):
        self.assertFalse(is_origin_allowed("https://evil.example.com"))

    def test_lookalike_suffix_blocked(self):
        self.assertFalse(
            is_origin_allowed("https://allenneuraldynamics.org.evil.com")
        )

    def test_lookalike_substring_blocked(self):
        self.assertFalse(
            is_origin_allowed("https://notallenneuraldynamics.org")
        )

    def test_embedded_domain_blocked(self):
        self.assertFalse(
            is_origin_allowed(
                "https://allenneuraldynamics.org.attacker.net"
            )
        )


class ExtractJsonFieldTests(unittest.TestCase):
    def test_plain_json(self):
        self.assertEqual(
            extract_json_field('{"response": "hi"}', "response"), "hi"
        )

    def test_json_with_surrounding_prose(self):
        self.assertEqual(
            extract_json_field('foo {"summary": "bar"} baz', "summary"),
            "bar",
        )

    def test_strips_whitespace(self):
        self.assertEqual(
            extract_json_field('{"response": "  hi  "}', "response"), "hi"
        )

    def test_missing_field_returns_none(self):
        self.assertIsNone(
            extract_json_field('{"other": "x"}', "response")
        )

    def test_non_string_field_returns_none(self):
        self.assertIsNone(
            extract_json_field('{"response": 42}', "response")
        )

    def test_invalid_json_returns_none(self):
        self.assertIsNone(extract_json_field("not json at all", "response"))

    def test_empty_returns_none(self):
        self.assertIsNone(extract_json_field("", "response"))

    def test_nested_object_value_returns_none(self):
        self.assertIsNone(
            extract_json_field('{"response": {"x": 1}}', "response")
        )


if __name__ == "__main__":
    unittest.main()
