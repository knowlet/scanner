import json
import tempfile

import pytest

from scanner.analyzer import detect_api_prefix


@pytest.fixture
def har_data():
    return {
        "log": {
            "entries": [
                {
                    "request": {"url": "https://api.example.com/v1/users", "method": "GET"},
                    "response": {"status": 200, "content": {"mimeType": "application/json"}},
                },
                {
                    "request": {"url": "https://api.example.com/v1/posts", "method": "GET"},
                    "response": {"status": 200, "content": {"mimeType": "application/json"}},
                },
                {
                    "request": {"url": "https://google.com/analytics", "method": "POST"},
                    "response": {"status": 200, "content": {"mimeType": "application/json"}},
                },
                {
                    "request": {"url": "https://legacy-app.com/login.php", "method": "POST"},
                    "response": {"status": 200, "content": {"mimeType": "text/html"}},
                },
            ]
        }
    }


def create_har_file(data):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".har", delete=False) as f:
        json.dump(data, f)
        return f.name


def test_detect_api_prefix_json(har_data):
    har_file = create_har_file(har_data)
    # targeting the main API
    prefix = detect_api_prefix(har_file, target_url="https://api.example.com")
    assert prefix == "https://api.example.com/v1"


def test_detect_api_prefix_filter_third_party(har_data):
    har_file = create_har_file(har_data)
    # Should ignore google.com even though it has JSON
    prefix = detect_api_prefix(har_file, target_url="https://api.example.com")
    assert "google.com" not in prefix


def test_detect_api_prefix_html_legacy():
    # specifically test the fix for text/html content types
    data = {
        "log": {
            "entries": [
                {
                    "request": {"url": "https://legacy-app.com/auth/login", "method": "POST"},
                    "response": {"status": 200, "content": {"mimeType": "text/html"}},
                },
                {
                    "request": {"url": "https://legacy-app.com/auth/register", "method": "POST"},
                    "response": {"status": 200, "content": {"mimeType": "application/x-www-form-urlencoded"}},
                },
            ]
        }
    }
    har_file = create_har_file(data)
    prefix = detect_api_prefix(har_file, target_url="https://legacy-app.com")
    assert prefix == "https://legacy-app.com/auth"


def test_fallback_behavior(har_data):
    # If no target URL matches, it might return None or fallback.
    # Current implementation falls back to all traffic if target filter yields nothing.
    har_file = create_har_file(har_data)
    # Searching for a domain not in HAR
    prefix = detect_api_prefix(har_file, target_url="https://missing.com")
    # It should fall back to finding the most common prefix in *all* traffic (api.example.com)
    assert prefix == "https://api.example.com/v1"
