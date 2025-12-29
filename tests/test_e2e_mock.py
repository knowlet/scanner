from unittest.mock import MagicMock, patch

import pytest

from scanner.main import async_main


@patch("scanner.main.run_crawler")
@patch("scanner.main.run_prober")
@patch("scanner.main.detect_api_prefix")
@patch("scanner.main.process_to_spec")
@patch("scanner.main.subprocess.Popen")
@patch("scanner.main.argparse.ArgumentParser.parse_args")
@pytest.mark.asyncio
async def test_main_e2e_flow(
    mock_parse_args, mock_popen, mock_process_to_spec, mock_detect_prefix, mock_run_prober, mock_run_crawler
):
    # Setup args
    mock_args = MagicMock()
    mock_args.url = "http://target.com"
    mock_args.depth = 2
    mock_args.header = ["Authorization: Bearer test"]
    mock_args.cookie = ["session=123"]
    mock_args.proxy_port = 8080
    mock_args.har_file = "traffic.har"
    mock_args.initial_spec = "init.yaml"
    mock_args.fuzzing_dump = "fuzz.mitm"
    mock_args.final_spec = "final.yaml"
    mock_args.resume = False
    mock_args.state_file = "state.json"

    mock_parse_args.return_value = mock_args

    # Setup detect_api_prefix return
    mock_detect_prefix.return_value = "http://target.com/api"

    # Setup Popen for mitmdump
    mock_process = MagicMock()
    mock_process.poll.return_value = None  # Process running
    mock_popen.return_value = mock_process

    # Run main
    await async_main()

    # Verify Step 1: Crawler
    mock_run_crawler.assert_called_once()
    args, kwargs = mock_run_crawler.call_args
    assert args[0] == "http://target.com"
    assert kwargs["headers"] == {"Authorization": "Bearer test"}
    assert kwargs["cookies"][0]["name"] == "session"

    # Verify Step 2: Proxy Start
    mock_popen.assert_called_once()
    assert "mitmdump" in mock_popen.call_args[0][0]

    # Verify Step 3: Probing
    mock_run_prober.assert_called_once()
    # Check that parsed prefix was passed
    # async_main calls: run_prober(args.initial_spec, target_prefix, proxy_url, ...)
    # where target_prefix comes from detect_api_prefix or fallback
    call_args = mock_run_prober.call_args
    # call_args could be positional or keyword
    # Signature: run_prober(spec_file, api_prefix, proxy, ...)
    # args: ('init.yaml', 'http://target.com/api', 'http://127.0.0.1:8080')
    assert call_args[0][1] == "http://target.com/api"

    # Verify Step 4: Spec Gen
    mock_process_to_spec.assert_called_once()
    path_gen_kwargs = mock_process_to_spec.call_args[1]
    assert path_gen_kwargs["api_prefix"] == "http://target.com/api"
    assert path_gen_kwargs["output_file"] == "final.yaml"
