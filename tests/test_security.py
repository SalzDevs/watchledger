import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from src.security import safe_external_url, safe_json_script, safe_slug, safe_text


def test_allows_https_url():
    assert safe_external_url("https://dealer.example/watch/123") == "https://dealer.example/watch/123"


def test_rejects_javascript_url():
    assert safe_external_url("javascript:alert(1)") == ""


def test_rejects_data_url():
    assert safe_external_url("data:text/html,<script>alert(1)</script>") == ""


def test_rejects_file_url():
    assert safe_external_url("file:///etc/passwd") == ""


def test_rejects_http_url():
    assert safe_external_url("http://dealer.example/watch/123") == ""


def test_rejects_relative_url():
    assert safe_external_url("/watch/123") == ""


def test_rejects_credentials_url():
    assert safe_external_url("https://user:password@example.com") == ""


def test_rejects_non_string():
    assert safe_external_url(None) == ""
    assert safe_external_url(12345) == ""


def test_json_script_cannot_be_terminated_by_listing_title():
    payload = {"title": "</script><script>alert(1)</script>"}
    encoded = safe_json_script(payload)
    assert "</script" not in encoded.lower()
    assert "\\u003c/script" in encoded.lower()


def test_json_script_escapes_ampersand():
    encoded = safe_json_script({"title": "a & b"})
    assert "\\u0026" in encoded


def test_safe_text_escapes_html():
    assert safe_text("<img src=x onerror=alert(1)>") == "&lt;img src=x onerror=alert(1)&gt;"


def test_safe_text_quotes_attributes():
    assert safe_text('"><script>') == "&quot;&gt;&lt;script&gt;"


def test_safe_text_none_is_empty():
    assert safe_text(None) == ""


def test_safe_slug_allows_canonical():
    assert safe_slug("rolex-submariner-126610ln") == "rolex-submariner-126610ln"


def test_safe_slug_rejects_traversal():
    assert safe_slug("../../etc/passwd") == ""
    assert safe_slug("/etc/passwd") == ""


def test_safe_slug_rejects_markup():
    assert safe_slug("<script>alert(1)</script>") == ""


def test_safe_slug_rejects_empty_and_long():
    assert safe_slug("") == ""
    assert safe_slug("a" * 200) == ""