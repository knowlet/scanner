# Active Scanner for Mitmproxy2Swagger

This module provides an automated way to crawl, inspect, and fuzz API endpoints to generate a high-quality OpenAPI specification with latency metrics.

## Components

1.  **Crawler (`src/scanner/crawler.py`)**: Explores a website, renders JavaScript (Playwright), and captures all network traffic.
2.  **Prober (`src/scanner/prober.py`)**: Actively probes discovered endpoints with multiple requests to gather statistical performance data.
3.  **Core (`mitmproxy2swagger`)**: Converts the captured traffic (HAR/Flow) into an OpenAPI Spec.

## Usage Guide



### Usage Guide

Run the full active scan in one click:

```bash
uv run scanner https://example.com
```

This will automatically:
1.  **Crawl** the website to discover endpoints.
2.  **Start a proxy** (mitmdump) in the background.
3.  **Probe/Fuzz** the endpoints through the proxy.
4.  **Generate** the final OpenAPI spec (`final_spec.yaml`).

#### With Authentication

**Using Headers (e.g., Bearer Token):**
```bash
uv run scanner https://api.example.com \
  --header "Authorization: Bearer YOUR_TOKEN"
```

**Using Cookies (e.g., Session ID):**
```bash
uv run scanner https://dashboard.example.com \
  --cookie "session_id=xyz123"
```

#### Advanced Usage

You can still customize the run:

```bash
uv run scanner https://example.com \
  --depth 3 \
  --proxy-port 8081 \
  --final-spec my_api.yaml
```



## Requirements
*   Python 3.10+
*   [uv](https://github.com/astral-sh/uv) package manager
*   Playwright (`uv run playwright install`)

## Setup

### 1. Installation

1.  **Install `uv`** (if not already installed):
    ```bash
    curl -LsSf https://astral.sh/uv/install.sh | sh
    ```

2.  **Sync dependencies**:
    ```bash
    uv sync
    ```

3.  **Install Playwright browsers**:
    ```bash
    uv run playwright install
    ```

### 2. Development Setup

To ensure code quality, we use `ruff` and `pre-commit`.

1.  **Install pre-commit hooks**:
    ```bash
    uv run pre-commit install
    ```

2.  **Run linting manually** (optional):
    ```bash
    uv run ruff check .
    uv run ruff format .
    ```
