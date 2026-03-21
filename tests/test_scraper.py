"""Unit tests for the WOD scraper."""
import pytest
from unittest.mock import patch, MagicMock
from services.scraper import _fetch_wod
from datetime import date


def test_fetch_wod_success():
    """Test successful WOD fetch with CSS selector."""
    mock_response = MagicMock()
    mock_response.text = """
    <html>
        <body>
            <div class="wod">
                <p>5 Rounds For Time:</p>
                <p>10 Pull-ups</p>
                <p>20 Push-ups</p>
                <p>30 Air Squats</p>
            </div>
        </body>
    </html>
    """
    mock_response.raise_for_status = MagicMock()

    source = {"name": "Test Box", "url": "https://example.com/wod", "selector": ".wod"}
    with patch("services.scraper.requests.get", return_value=mock_response):
        content = _fetch_wod(source, date.today())

    assert content is not None
    assert "Pull-ups" in content
    assert "Push-ups" in content


def test_fetch_wod_network_error():
    """Test graceful handling of network errors."""
    import requests
    source = {"name": "Test", "url": "https://example.com/wod", "selector": ".wod"}
    with patch("services.scraper.requests.get", side_effect=requests.ConnectionError("timeout")):
        content = _fetch_wod(source, date.today())

    assert content is None


def test_fetch_wod_no_selector_match():
    """Test fallback when selector doesn't match."""
    mock_response = MagicMock()
    mock_response.text = "<html><body><p>No WOD here</p></body></html>"
    mock_response.raise_for_status = MagicMock()

    source = {"name": "Test", "url": "https://example.com/wod", "selector": ".very-specific-nonexistent"}
    with patch("services.scraper.requests.get", return_value=mock_response):
        # Should try fallback selectors; in this case nothing matches
        content = _fetch_wod(source, date.today())
    # Result may be None or contain fallback content
    # Just ensure it doesn't raise
