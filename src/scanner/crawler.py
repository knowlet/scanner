import argparse
import asyncio
import re
from collections import deque
from urllib.parse import urlparse

from playwright.async_api import Page, async_playwright


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

            print(f"Starting crawl from {self.start_url}")

            while self.queue:
                current_url, depth = self.queue.popleft()

                if current_url in self.visited:
                    continue

                if depth > self.max_depth:
                    continue

                self.visited.add(current_url)
                print(f"[{depth}] Visiting: {current_url}")

                try:
                    # Goto and wait for network idle to ensure XHRs fire
                    await page.goto(current_url, wait_until="networkidle", timeout=10000)
                except Exception as e:
                    print(f"Failed to load {current_url}: {e}")
                    continue

                # If we are not at max depth, extract links
                if depth < self.max_depth:
                    links = await self.extract_links(page)
                    for link in links:
                        if self.is_valid_url(link):
                            self.queue.append((link, depth + 1))

                # Short sleep to be polite (and let more things load if needed)
                await asyncio.sleep(0.5)

            print("Crawl finished.")
            # Context close saves the HAR
            await context.close()
            await browser.close()
            print(f"Traffic saved to {self.output_har}")

            # Auto-generate Spec
            if hasattr(self, "output_spec") and self.output_spec:
                print(f"Generating OpenAPI Spec to {self.output_spec}...")
                try:
                    from mitmproxy2swagger.mitmproxy2swagger import process_to_spec

                    process_to_spec(
                        input_file=self.output_har,
                        output_file=self.output_spec,
                        api_prefix=self.root_url,
                        input_format="har",
                        auto_approve_paths=True,
                    )
                    print(f"Spec generated successfully: {self.output_spec}")
                except ImportError:
                    print("Could not import mitmproxy2swagger. Make sure it is in the python path.")
                except Exception as e:
                    print(f"Failed to generate spec: {e}")

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
):
    crawler = AsyncCrawler(url, depth, out, headers=headers, cookies=cookies)
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

    asyncio.run(run_crawler(args.url, args.depth, args.out, args.spec, headers, cookies))
