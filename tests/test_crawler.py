from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scanner.crawler import AsyncCrawler


@pytest.fixture
def mock_page():
    page = AsyncMock()
    # Mock locator for forms
    page.locator.return_value.all.return_value = []
    # Mock eval_on_selector_all for links
    page.eval_on_selector_all.return_value = []
    page.url = "http://test-site.com"
    return page


@pytest.fixture
def mock_context(mock_page):
    context = AsyncMock()
    context.new_page.return_value = mock_page
    return context


@pytest.fixture
def mock_browser(mock_context):
    browser = AsyncMock()
    browser.new_context.return_value = mock_context
    return browser


@pytest.fixture
def mock_playwright(mock_browser):
    pw = AsyncMock()
    pw.chromium.launch.return_value = mock_browser
    return pw


@pytest.mark.asyncio
async def test_crawler_initialization():
    crawler = AsyncCrawler("http://test.com", max_depth=3)
    assert crawler.start_url == "http://test.com"
    assert crawler.max_depth == 3
    assert crawler.domain == "test.com"
    assert "http://test.com" in [q[0] for q in crawler.queue]


@pytest.mark.asyncio
async def test_is_valid_url():
    crawler = AsyncCrawler("http://test.com")

    assert crawler.is_valid_url("http://test.com/path")
    assert not crawler.is_valid_url("http://google.com")  # External
    assert not crawler.is_valid_url("http://test.com/image.png")  # Static

    crawler.visited.add("http://test.com/visited")
    assert not crawler.is_valid_url("http://test.com/visited")  # Visited


@patch("scanner.crawler.async_playwright")
@pytest.mark.asyncio
async def test_crawl_flow(mock_pw_func, mock_playwright, mock_page):
    # Setup mock
    mock_pw_context = AsyncMock()
    mock_pw_context.__aenter__.return_value = mock_playwright
    mock_pw_context.__aexit__.return_value = None
    mock_pw_func.return_value = mock_pw_context

    # Specifics for this test
    # 1. First visit http://test.com -> found link http://test.com/page2
    # 2. Visit http://test.com/page2 -> found no links

    async def side_effect_eval(selector, fn):
        if selector == "a":
            if mock_page.url == "http://test.com":
                return ["http://test.com/page2", "http://google.com", "http://test.com/image.png"]
            elif mock_page.url == "http://test.com/page2":
                return []
        return []

    mock_page.eval_on_selector_all.side_effect = side_effect_eval

    # We also need to update mock_page.url when goto is called to simulate navigation
    async def side_effect_goto(url, **kwargs):
        mock_page.url = url

    mock_page.goto.side_effect = side_effect_goto

    crawler = AsyncCrawler("http://test.com", max_depth=2, output_har="test.har")
    await crawler.crawl()

    # Verify visited
    assert "http://test.com" in crawler.visited
    assert "http://test.com/page2" in crawler.visited

    # Verify ignored
    assert "http://google.com" not in crawler.visited

    # Verify calls
    assert mock_page.goto.call_count == 2


@patch("scanner.crawler.async_playwright")
@pytest.mark.asyncio
async def test_crawl_form_detection(mock_pw_func, mock_playwright, mock_page):
    # Setup mock
    mock_pw_context = AsyncMock()
    mock_pw_context.__aenter__.return_value = mock_playwright
    mock_pw_context.__aexit__.return_value = None
    mock_pw_func.return_value = mock_pw_context

    mock_page.url = "http://test.com/login"

    # Define mock form and input
    mock_form = AsyncMock()
    mock_input = AsyncMock()
    mock_input.is_visible.return_value = True

    # Side effects for attributes
    async def attr_side_effect(attr):
        if attr == "type":
            return "text"
        if attr == "name":
            return "username"
        return ""

    mock_input.get_attribute.side_effect = attr_side_effect

    # Mock submit button
    mock_submit = AsyncMock()
    mock_submit.count.return_value = 1
    mock_submit.is_visible.return_value = True

    # Let's construct a Mock Locator for input
    # Locator.all() IS async
    mock_input_locator = AsyncMock()
    mock_input_locator.all.return_value = [mock_input]

    # Mock Locator for submit
    mock_submit_locator = AsyncMock()
    mock_submit_locator.first = mock_submit
    mock_submit_locator.count.return_value = 1

    # form.locator("...") is SYNCHRONOUS, returns a locator
    # We use MagicMock for synchronous callable
    # form.locator("...") should return the appropriate locator
    mock_form.locator = MagicMock()

    def form_locator_side_effect(selector):
        # The submit selector contains 'submit'
        if "submit" in selector or "Login" in selector:
            return mock_submit_locator
        # The input selector is mostly implicit or generic 'input'
        elif "input" in selector or "textarea" in selector:
            return mock_input_locator
        else:
            # Fallback
            return MagicMock()

    mock_form.locator.side_effect = form_locator_side_effect

    # page.locator("form") is SYNCHRONOUS
    mock_form_locator = AsyncMock()
    mock_form_locator.all.return_value = [mock_form]

    mock_page.locator = MagicMock()
    mock_page.locator.return_value = mock_form_locator

    crawler = AsyncCrawler("http://test.com/login", max_depth=1)
    await crawler.process_page(mock_page, "http://test.com/login", 0)

    # Verify input was filled
    mock_input.fill.assert_called_with("testuser")

    # Verify submit clicked
    mock_submit.click.assert_called()
