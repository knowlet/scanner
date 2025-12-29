import argparse
import asyncio
import contextlib
import json
import re
from collections import deque
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import Page, async_playwright

from scanner.analyzer import detect_api_prefix


class AsyncCrawler:
    def __init__(
        self,
        start_url: str,
        max_depth: int = 2,
        output_har: str = "captured_traffic.har",
        headers: dict[str, str] = None,
        cookies: list[dict] = None,
    ):
        self.start_url = start_url
        self.max_depth = max_depth
        self.output_har = output_har
        self.headers = headers or {}
        self.cookies = cookies or []
        self.visited: set[str] = set()
        self.queue: deque[tuple[str, int]] = deque([(start_url, 0)])
        self.domain = urlparse(start_url).netloc
        self.root_url = f"{urlparse(start_url).scheme}://{self.domain}"
        self.state_path: Path | None = None

    def save_state(self):
        if not self.state_path:
            return
        state = {
            "visited": list(self.visited),
            "queue": list(self.queue),
        }
        with open(self.state_path, "w") as f:
            json.dump(state, f)

    def load_state(self, path: str):
        self.state_path = Path(path)
        if self.state_path.exists():
            with open(self.state_path) as f:
                state = json.load(f)
                self.visited = set(state.get("visited", []))
                self.queue = deque([(item[0], item[1]) for item in state.get("queue", [])])
            print(f"Loaded state from {path}: {len(self.visited)} visited, {len(self.queue)} in queue")
        else:
            print(f"State file {path} not found, starting fresh.")

    def is_valid_url(self, url: str) -> bool:
        parsed = urlparse(url)
        return (
            parsed.netloc == self.domain
            and parsed.scheme in ["http", "https"]
            and url not in self.visited
            and not self.is_static_asset(parsed.path)
        )

    def is_static_asset(self, path: str) -> bool:
        static_exts = {
            ".jpg",
            ".jpeg",
            ".png",
            ".gif",
            ".css",
            ".js",
            ".ico",
            ".svg",
            ".woff",
            ".woff2",
            ".ttf",
            ".eot",
            ".mp4",
            ".mp3",
            ".pdf",
        }
        return any(path.lower().endswith(ext) for ext in static_exts)

    async def crawl(self):
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            # Enable HAR recording context-wide
            context = await browser.new_context(
                record_har_path=self.output_har,
                record_har_url_filter=re.compile(".*"),  # Capture everything
                record_har_mode="minimal",  # Or 'full' for content
                extra_http_headers=self.headers,
            )

            if self.cookies:
                await context.add_cookies(self.cookies)

            page = await context.new_page()

            # Optional: Add simple console listener to catch printed API endpoints if any
            # page.on("console", lambda msg: print(f"CONSOLE: {msg.text}"))

            print(f"Starting crawl from {self.start_url} (debug mode)")

            try:
                while self.queue:
                    current_url, depth = self.queue.popleft()

                    if current_url in self.visited:
                        continue

                    if depth > self.max_depth:
                        continue

                    self.visited.add(current_url)
                    print(f"[{depth}] Visiting: {current_url}")

                    try:
                        await self.process_page(page, current_url, depth)
                    except Exception as e:
                        print(f"Failed to process {current_url}: {e}")

                    # Save state after each visit
                    self.save_state()

                    # Short sleep to be polite
                    await asyncio.sleep(0.5)

                print("Crawl finished.")

            finally:
                # Context close saves the HAR
                print(f"Closing browser context (saving HAR to {self.output_har})...")
                await context.close()
                print("Browser context closed.")
                await browser.close()
                print("Browser closed.")
                print(f"Traffic saved to {self.output_har}")

                # Cleanup state file on successful finish only if queue is empty
                if not self.queue and self.state_path and self.state_path.exists():
                    self.state_path.unlink()
                    print(f"Cleaned up state file {self.state_path}")

                # Auto-generate Spec
                # Only if output_spec is set (it might not be if just crawling)
                # We do this in finally to output spec even if interrupted
                if hasattr(self, "output_spec") and self.output_spec:
                    print(f"Generating OpenAPI Spec to {self.output_spec}...")

                    # Detect Prefix
                    detected_prefix = detect_api_prefix(self.output_har, target_url=self.start_url)
                    target_prefix = detected_prefix or self.root_url
                    print(f"Using API Prefix: {target_prefix}")

                    try:
                        from mitmproxy2swagger.mitmproxy2swagger import process_to_spec

                        process_to_spec(
                            input_file=self.output_har,
                            output_file=self.output_spec,
                            api_prefix=target_prefix,
                            input_format="har",
                            auto_approve_paths=True,
                        )
                        print(f"Spec generated successfully: {self.output_spec}")
                    except ImportError:
                        print("Could not import mitmproxy2swagger. Make sure it is in the python path.")
                    except Exception:
                        import traceback

                        traceback.print_exc()
                        print("Failed to generate spec due to an exception.")

    async def process_page(self, page: Page, url: str, depth: int):
        # Goto and wait for network idle to ensure XHRs fire
        await page.goto(url, wait_until="networkidle", timeout=10000)

        # 1. Handle Forms (Fill and Submit to capture POST/PUT)
        await self.handle_forms(page)

        # 2. Extract Links (if not at max depth)
        if depth < self.max_depth:
            links = await self.extract_links(page)
            for link in links:
                if self.is_valid_url(link):
                    self.queue.append((link, depth + 1))

    async def handle_forms(self, page: Page):
        """Finds forms, fills them with dummy data, and submits them."""
        try:
            forms = await page.locator("form").all()
            if not forms:
                return

            print(f"Found {len(forms)} forms on {page.url}")
            for i, form in enumerate(forms):
                # Re-query inputs to avoid stale elements if DOM updated
                inputs = await form.locator("input:not([type='hidden']), textarea").all()

                filled = False
                for input_el in inputs:
                    with contextlib.suppress(Exception):
                        # Check visibility
                        if not await input_el.is_visible():
                            continue

                        input_type = await input_el.get_attribute("type") or "text"
                        input_name = await input_el.get_attribute("name") or ""
                        input_val = ""

                        # Dummy data logic
                        if input_type == "password":
                            input_val = "Password123!"
                        elif input_type == "email" or "email" in input_name.lower():
                            input_val = "test@example.com"
                        elif input_type in ["text", "search", "url"]:
                            input_val = "testuser"

                        if input_val:
                            await input_el.fill(input_val)
                            filled = True

                if filled:
                    # Try to submit
                    submit_selector = (
                        "input[type='submit'], button[type='submit'], "
                        "button:has-text('Login'), button:has-text('Sign In'), "
                        "button:has-text('Submit')"
                    )
                    submit_button = form.locator(submit_selector).first
                    if await submit_button.count() > 0 and await submit_button.is_visible():
                        print(f"Submitting form {i + 1}...")
                        # We use a short timeout because submission might trigger navigation or just XHR
                        # We don't want to wait forever if it's just a validation error
                        try:
                            # Use Promise.all to catch navigation or just wait a bit
                            # But since we just want to trigger the request for HAR, clicking is often enough.
                            # We catch timeout in case it hangs.
                            await submit_button.click(timeout=3000)
                            # Give it a moment to fire requests
                            await page.wait_for_timeout(2000)
                        except Exception as e:
                            print(f"Form submission wait warning: {e}")

        except Exception as e:
            print(f"Error handling forms: {e}")

    async def extract_links(self, page: Page) -> set[str]:
        links = set()
        try:
            # Evaluate JS so we get links even if they are dynamic
            hrefs = await page.eval_on_selector_all("a", "(elements) => elements.map(e => e.href)")
            for href in hrefs:
                # Remove fragment
                clean_href = href.split("#")[0]
                # Normalize trailing slash
                if clean_href.endswith("/"):
                    clean_href = clean_href[:-1]
                links.add(clean_href)
        except Exception as e:
            print(f"Error extracting links: {e}")
        return links


async def run_crawler(
    url: str,
    depth: int,
    out: str,
    spec: str = None,
    headers: dict[str, str] = None,
    cookies: list[dict] = None,
    resume: bool = False,
    state_file: str = "crawler_state.json",
):
    crawler = AsyncCrawler(url, depth, out, headers=headers, cookies=cookies)
    if resume:
        crawler.load_state(state_file)
    else:
        # If not resuming, we still might want to enable saving state for future resumes
        crawler.state_path = Path(state_file)

    if spec:
        crawler.output_spec = spec
    await crawler.crawl()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Active API Crawler")
    parser.add_argument("url", help="Start URL")
    parser.add_argument("--depth", type=int, default=2, help="Max recursion depth")
    parser.add_argument("--out", default="captured_traffic.har", help="Output HAR file")
    parser.add_argument("--spec", default=None, help="Output OpenAPI Spec YAML file (Auto-generate)")
    parser.add_argument(
        "--header", action="append", help="Extra header (e.g. 'Authorization: Bearer X'). Can be used multiple times."
    )
    parser.add_argument(
        "--cookie", action="append", help="Extra cookie (e.g. 'session=123'). Can be used multiple times."
    )
    parser.add_argument("--resume", action="store_true", help="Resume from previous state")
    parser.add_argument("--state-file", default="crawler_state.json", help="Path to state file")

    args = parser.parse_args()

    # Parse headers
    headers = {}
    if args.header:
        for h in args.header:
            if ":" in h:
                key, val = h.split(":", 1)
                headers[key.strip()] = val.strip()

    # Parse cookies
    cookies = []
    if args.cookie:
        # We need domain for cookies in playwright
        domain = urlparse(args.url).netloc
        for c in args.cookie:
            if "=" in c:
                k, v = c.split("=", 1)
                cookies.append({"name": k.strip(), "value": v.strip(), "domain": domain, "path": "/"})

    asyncio.run(
        run_crawler(
            args.url,
            args.depth,
            args.out,
            args.spec,
            headers,
            cookies,
            resume=args.resume,
            state_file=args.state_file,
        )
    )
