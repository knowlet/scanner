import argparse
import asyncio
import os
import signal
import subprocess
import time
from urllib.parse import urlparse

from mitmproxy2swagger.mitmproxy2swagger import process_to_spec

# Imports from local modules
from scanner.crawler import run_crawler
from scanner.prober import run_prober


async def async_main():
    parser = argparse.ArgumentParser(description="One-click Active API Scanner")
    parser.add_argument("url", help="Target URL (e.g. https://example.com)")
    parser.add_argument("--depth", type=int, default=2, help="Crawling depth (default: 2)")
    parser.add_argument("--header", action="append", help="Header to use (e.g. 'Authorization: Bearer X')")
    parser.add_argument("--cookie", action="append", help="Cookie to use (e.g. 'session=123')")

    # Internal usage args
    parser.add_argument("--proxy-port", type=int, default=8080, help="Port to run mitmdump on")
    parser.add_argument("--har-file", default="traffic.har", help="Intermediate HAR file from crawler")
    parser.add_argument("--initial-spec", default="initial_spec.yaml", help="Initial Spec file")
    parser.add_argument("--fuzzing-dump", default="fuzzing.mitm", help="Intermediate mitm dump from prober")
    parser.add_argument("--final-spec", default="final_spec.yaml", help="Final OpenAPI Spec file")

    args = parser.parse_args()

    # Parse headers/cookies once
    headers = {}
    if args.header:
        for h in args.header:
            if ":" in h:
                key, val = h.split(":", 1)
                headers[key.strip()] = val.strip()

    cookies = []
    prober_cookies = {}
    if args.cookie:
        domain = urlparse(args.url).netloc
        for c in args.cookie:
            if "=" in c:
                k, v = c.split("=", 1)
                cookies.append({"name": k.strip(), "value": v.strip(), "domain": domain, "path": "/"})
                prober_cookies[k.strip()] = v.strip()

    print("=== Step 1: Crawling ===")
    await run_crawler(args.url, args.depth, args.har_file, args.initial_spec, headers=headers, cookies=cookies)

    print("\n=== Step 2: Starting Proxy ===")
    # Start mitmdump in background
    proxy_url = f"http://127.0.0.1:{args.proxy_port}"
    cmd = ["mitmdump", "-w", args.fuzzing_dump, "-p", str(args.proxy_port)]
    # Use preexec_fn=os.setsid to easily kill entire process group later
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, preexec_fn=os.setsid)

    try:
        # Give it a moment to start
        print(f"Waiting for proxy at {proxy_url}...")
        time.sleep(3)
        if process.poll() is not None:
            print("Error: Proxy failed to start.")
            print(process.stderr.read().decode())
            return

        print("\n=== Step 3: Probing/Fuzzing ===")
        await run_prober(args.initial_spec, args.url, proxy_url, samples=5, headers=headers, cookies=prober_cookies)

    finally:
        print("\n=== Stopping Proxy ===")
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            process.wait(timeout=5)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass
        print("Proxy stopped.")

    print("\n=== Step 4: Generating Final Spec ===")
    try:
        process_to_spec(
            input_file=args.fuzzing_dump,
            output_file=args.final_spec,
            api_prefix=args.url,
            input_format="flow",
            auto_approve_paths=True,
        )
        print(f"SUCCESS: Final spec generated at {args.final_spec}")
    except Exception as e:
        print(f"Error generating spec: {e}")


def main():
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
