import argparse
import asyncio
import random
import sys
from typing import Any

import httpx
import yaml


class APIProber:
    def __init__(
        self,
        spec_file: str,
        api_prefix: str,
        proxy: str = None,
        samples: int = 5,
        headers: dict[str, str] = None,
        cookies: dict[str, str] = None,
    ):
        self.spec_file = spec_file
        self.api_prefix = api_prefix.rstrip("/")
        self.proxy = proxy
        self.samples = samples
        self.headers = headers or {}
        self.cookies = cookies or {}
        self.endpoints: list[dict[str, Any]] = []

    def load_spec(self):
        """Parse OpenAPI spec to find endpoints to probe."""
        try:
            with open(self.spec_file) as f:
                spec = yaml.safe_load(f)

            paths = spec.get("paths", {})
            for path, methods in paths.items():
                for method, details in methods.items():
                    if method.lower() in ["get", "post", "put", "delete", "patch"]:
                        self.endpoints.append(
                            {"path": path, "method": method.upper(), "summary": details.get("summary", "")}
                        )
            print(f"Loaded {len(self.endpoints)} endpoints from {self.spec_file}")

        except FileNotFoundError:
            print(f"Error: Spec file {self.spec_file} not found.")
            sys.exit(1)
        except Exception as e:
            print(f"Error loading spec: {e}")
            sys.exit(1)

    def _fill_params(self, path: str) -> str:
        """Replace path parameters like {id} with dummy values."""
        # Simple heuristic for now: replace any {.*} with '1'
        import re

        return re.sub(r"\{[^}]+\}", "1", path)

    async def probe(self):
        """Run the probing requests."""
        if not self.endpoints:
            self.load_spec()

        mounts = {}
        if self.proxy:
            mounts["http://"] = httpx.HTTPTransport(proxy=self.proxy)
            mounts["https://"] = httpx.HTTPTransport(proxy=self.proxy)
            # For httpx < 0.28, proxies arg in AsyncClient is deprecated in favor of mounts or proxy kwarg?
            # Actually httpx 0.28 supports `proxy` arg directly or mounts.
            # But specific proxy per scheme is best done via mounts or just a single proxy url string if all go there.
            # Let's simple check:
            # client = httpx.AsyncClient(proxy=self.proxy) is the modern way.

        print(f"Starting probe on {self.api_prefix} using proxy {self.proxy} for {self.samples} samples...")

        # Prepare default headers
        default_headers = {"User-Agent": "ActiveScanner/Prober"}
        default_headers.update(self.headers)

        async with httpx.AsyncClient(proxy=self.proxy, verify=False, cookies=self.cookies) as client:
            for endpoint in self.endpoints:
                path_template = endpoint["path"]
                method = endpoint["method"]

                # Construct actual URL path
                path = self._fill_params(path_template)
                full_url = f"{self.api_prefix}{path}"

                print(f"Probing {method} {path}...")

                for i in range(self.samples):
                    try:
                        # Slight delay to mimic real traffic and ensure distinct timestamps
                        await asyncio.sleep(random.uniform(0.1, 0.5))

                        await client.request(method, full_url, headers=default_headers)
                        # print(f"  [{i+1}/{self.samples}] Status: {response.status_code}")
                    except Exception as e:
                        print(f"  [{i + 1}/{self.samples}] Failed: {e}")

        print("Probing finished.")


async def run_prober(
    spec_file: str,
    api_prefix: str,
    proxy: str = None,
    samples: int = 5,
    headers: dict[str, str] = None,
    cookies: dict[str, str] = None,
):
    prober = APIProber(spec_file, api_prefix, proxy, samples, headers=headers, cookies=cookies)
    await prober.probe()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Active API Prober (Fuzzer)")
    parser.add_argument("spec", help="Input OpenAPI YAML spec")
    parser.add_argument("--url", help="Target API Base URL (e.g. https://httpbin.org)", required=True)
    parser.add_argument("--proxy", help="Proxy URL (e.g. http://127.0.0.1:8080)", default=None)
    parser.add_argument("--samples", type=int, default=5, help="Number of requests per endpoint")
    parser.add_argument("--header", action="append", help="Extra header. Can be used multiple times.")
    parser.add_argument("--cookie", action="append", help="Extra cookie. Can be used multiple times.")
    # Note: --out is removed as output is handled by the proxy (mitmdump)

    args = parser.parse_args()

    # If proxy is not provided, warn user (or just run without capturing?)
    # But purpose is capturing.
    if not args.proxy:
        print("Warning: No proxy specified. Traffic will NOT be captured unless you have another mechanism.")

    # Parse headers
    headers = {}
    if args.header:
        for h in args.header:
            if ":" in h:
                key, val = h.split(":", 1)
                headers[key.strip()] = val.strip()

    # Parse cookies
    cookies = {}
    if args.cookie:
        for c in args.cookie:
            if "=" in c:
                key, val = c.split("=", 1)
                cookies[key.strip()] = val.strip()

    asyncio.run(run_prober(args.spec, args.url, args.proxy, args.samples, headers, cookies))
