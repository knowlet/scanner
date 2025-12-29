import json
import statistics
from collections import Counter
from urllib.parse import urlparse


def detect_api_prefix(har_file_path: str, target_url: str = None) -> str:
    """
    Analyzes a HAR file to find the most common API prefix.
    Consider responses with JSON/XML content types.
    If target_url is provided, restricts analysis to that domain.
    """
    try:
        with open(har_file_path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"Error reading HAR file: {e}")
        return None

    entries = data.get("log", {}).get("entries", [])
    if not entries:
        return None

    api_urls = []

    # Heuristic for "API" response
    api_content_types = [
        "application/json",
        "application/xml",
        "text/xml",
        "application/hal+json",
        "application/vnd.api+json",
        "text/html",
        "application/x-www-form-urlencoded",
        "multipart/form-data",
        "text/plain",
    ]

    target_netloc = urlparse(target_url).netloc if target_url else None

    for entry in entries:
        response = entry.get("response", {})
        content = response.get("content", {})
        mime_type = content.get("mimeType", "").lower()

        # Check if it looks like an API
        is_api = any(t in mime_type for t in api_content_types)

        if is_api:
            url = entry["request"]["url"]
            # If target_url provided, filter by domain immediately?
            # Or collect all and filter later? Collecting all allows fallback.
            api_urls.append(url)

    if not api_urls:
        print("No API traffic detected in HAR.")
        return None

    # Parse URLs
    parsed_urls = [urlparse(u) for u in api_urls]

    # Filter by target domain if specified
    if target_netloc:
        if filtered_urls := [u for u in parsed_urls if u.netloc == target_netloc]:
            parsed_urls = filtered_urls
            print(f"Filtered to {len(parsed_urls)} API calls matching {target_netloc}")
        else:
            print(f"No API calls matched {target_netloc}, falling back to all captured traffic.")

    # 1. Majority Scheme and Netloc
    schemes = [u.scheme for u in parsed_urls]
    netlocs = [u.netloc for u in parsed_urls]

    common_scheme = statistics.mode(schemes)
    common_netloc = statistics.mode(netlocs)

    base_url = f"{common_scheme}://{common_netloc}"

    # 2. Path analysis
    # Filter to only those matching the common base
    paths = [u.path for u in parsed_urls if u.scheme == common_scheme and u.netloc == common_netloc]

    if not paths:
        return base_url

    # Split into segments. ignore empty start.
    # /api/v1/users -> ['api', 'v1', 'users']
    segment_lists = [p.strip("/").split("/") for p in paths]

    # Find common prefix segments that cover > 50% of API requests?
    # Or just looking for "dominant" prefix.
    # Let's walk level by level.

    common_segments = []
    current_level_lists = segment_lists
    total_apis = len(paths)
    threshold = 0.6  # The prefix must appear in 60% of API calls

    max_depth = max((len(s) for s in segment_lists), default=0)

    for i in range(max_depth):
        # Gather all segments at this index
        segments_at_i = [s[i] for s in current_level_lists if len(s) > i]
        if not segments_at_i:
            break

        counts = Counter(segments_at_i)
        most_common_seg, count = counts.most_common(1)[0]

        if count / total_apis >= threshold:
            common_segments.append(most_common_seg)
            # Filter lists to only those that match to continue deeper?
            # Actually, to be a "common prefix" implies we are narrowing down
            # to the subtree that has the most items.
            current_level_lists = [s for s in current_level_lists if len(s) > i and s[i] == most_common_seg]
            # Update total for calculating percentage of the REMAINING?
            # No, standard is usually percentage of TOTAL.
            # If we branch:
            # /api/v1 (40%)
            # /api/v2 (40%)
            # /auth   (20%)
            # 'api' is 80%. 'v1' is 40% of total.
            # So if we use total_apis, we stop at 'api'.
            # This seems correct for "grouping". We don't want to exclude v2.
        else:
            break

    prefix_path = "/".join(common_segments)
    return f"{base_url}/{prefix_path}" if prefix_path else base_url
