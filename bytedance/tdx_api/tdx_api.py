"""Reusable TDX helper functions.

This module provides a small, script-friendly API for generating TDX quotes,
attesting them, checking the guest type, and retrieving TD event logs.
All public functions return JSON-serializable dictionaries.
"""

from __future__ import annotations

import base64
import datetime
import json
import logging
import os
import sys
from io import StringIO
from pathlib import Path
from typing import Any, Dict, Optional

import requests

LOG = logging.getLogger(__name__)
DEFAULT_ATTEST_SERVICE_ENDPOINT = "your_attestation_service_address"


def _add_path(path: Path) -> None:
    if path.exists() and str(path) not in sys.path:
        sys.path.insert(0, str(path))


def _bootstrap_local_paths() -> None:
    repo_root = Path(__file__).resolve().parent
    parent_repo_root = repo_root.parent

    for path in (
        repo_root / "lib",
        parent_repo_root / "lib",
        repo_root
        / "myenv"
        / "lib"
        / f"python{sys.version_info.major}.{sys.version_info.minor}"
        / "site-packages",
        parent_repo_root
        / "myenv"
        / "lib"
        / f"python{sys.version_info.major}.{sys.version_info.minor}"
        / "site-packages",
    ):
        _add_path(path)


_bootstrap_local_paths()


def _import_quote_generator():
    try:
        import quote_generator  # type: ignore

        return quote_generator
    except ImportError as exc:
        raise ImportError(
            "Failed to import quote_generator. Build the Cython extension in lib/ first."
        ) from exc


def _encode_evidence(evidence: Dict[str, Any]) -> str:
    evidence_json = json.dumps(evidence)
    return base64.urlsafe_b64encode(evidence_json.encode("utf-8")).decode("utf-8").rstrip("=")


def _decode_urlsafe_segment(segment: str) -> str:
    padding_needed = (-len(segment)) % 4
    if padding_needed:
        segment += "=" * padding_needed
    return base64.urlsafe_b64decode(segment).decode("utf-8")


def get_raw_tdx_quote() -> Dict[str, Any]:
    """Generate a raw TDX quote and return Base64-encoded data plus parsed fields."""
    try:
        quote_generator = _import_quote_generator()
        quote_data, parse_result = quote_generator.generate_quote()
        return {
            "status": 200,
            "quote_data": base64.b64encode(quote_data).decode("utf-8"),
            "parse_result": parse_result,
        }
    except Exception as exc:
        return {"status": 500, "error": str(exc)}


def attest_tdx_quote(
    attestation_url: str,
    evidence: Optional[Dict[str, Any]] = None,
    timeout: int = 5,
) -> Dict[str, Any]:
    """Generate a TDX quote and submit it to an attestation service.

    Args:
        attestation_url: Attestation service endpoint.
        evidence: Optional evidence payload. If omitted, a minimal payload is
            generated using the raw quote.
        timeout: Request timeout in seconds.
    """
    try:
        quote_generator = _import_quote_generator()
        quote_data, _ = quote_generator.generate_quote()

        if evidence is None:
            evidence = {
                "quote": base64.b64encode(quote_data).decode("utf-8"),
                "cc_eventlog": None,
            }

        request_body = {
            "verification_requests": [
                {
                    "tee": "tdx",
                    "evidence": _encode_evidence(evidence),
                }
            ],
            "policy_ids": [],
        }

        LOG.info(
            "Starting attestation request to %s at %s",
            attestation_url,
            datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
        response = requests.post(attestation_url, json=request_body, timeout=timeout)
        response.raise_for_status()

        response_text = response.text
        try:
            token_segment = response_text.split(".")[1]
            decoded_result = _decode_urlsafe_segment(token_segment)
        except Exception:
            decoded_result = response_text

        return {"status": 200, "attest_result": decoded_result}
    except requests.exceptions.Timeout:
        return {"status": 500, "error": "Attestation service request timed out"}
    except requests.exceptions.ConnectionError:
        return {"status": 500, "error": "Failed to connect to attestation service: Connection refused"}
    except requests.exceptions.HTTPError as exc:
        response = exc.response
        status_code = response.status_code if response is not None else 500
        response_text = response.text if response is not None else str(exc)
        return {
            "status": status_code,
            "error": f"Attestation service returned HTTP {status_code}: {response_text}",
        }
    except Exception as exc:
        return {"status": 500, "error": f"Failed to connect to attestation service: {str(exc)}"}


def get_tee_status() -> Dict[str, Any]:
    """Inspect /proc/cpuinfo and decide whether the machine is a TDX guest."""
    try:
        with open("/proc/cpuinfo", "r", encoding="utf-8", errors="ignore") as cpuinfo_file:
            cpuinfo = cpuinfo_file.read()

        has_tdx_guest = any(
            "tdx_guest" in line.split(":", 1)[1].lower().split()
            for line in cpuinfo.splitlines()
            if line.lower().startswith("flags")
        )

        if has_tdx_guest:
            return {"status": 200, "message": "Current MCP Server is running in a TD Guest"}
        return {"status": 200, "message": "Current MCP Server is running in a normal environment"}
    except Exception as exc:
        return {"status": 500, "error": f"Command execution failed: {str(exc)}"}


def fetch_td_eventlog(output_file: Optional[str] = None) -> Dict[str, Any]:
    """Retrieve the TD event log from a confidential VM environment.

    Args:
        output_file: Optional path to store the captured event log text.
    """
    try:
        from cctrusted_base.api import CCTrustedApi
        from cctrusted_base.eventlog import TcgEventLog
        from cctrusted_base.tcgcel import TcgTpmsCelEvent
        from cctrusted_vm.cvm import ConfidentialVM
        from cctrusted_vm.sdk import CCTrustedVmSdk

        old_stdout = os.sys.stdout
        old_stderr = os.sys.stderr
        result = StringIO()
        os.sys.stdout = result
        os.sys.stderr = result

        old_log_handlers = logging.root.handlers[:]
        for handler in old_log_handlers:
            logging.root.removeHandler(handler)
        log_handler = logging.StreamHandler(result)
        logging.root.addHandler(log_handler)
        logging.root.setLevel(logging.INFO)

        try:
            print("Starting to retrieve TD Eventlog")

            if ConfidentialVM.detect_cc_type() == CCTrustedApi.TYPE_CC_NONE:
                print("This is not a confidential VM!")
                output = "Current environment is not a confidential VM, cannot retrieve TD Eventlog"
            elif os.geteuid() != 0:
                print("Please run as root which is required for this example!")
                output = "Root privileges required to retrieve TD Eventlog"
            else:
                class Args:
                    def __init__(self):
                        self.start = None
                        self.count = None
                        self.cel_format = False

                args = Args()
                event_logs = CCTrustedVmSdk.inst().get_cc_eventlog(args.start, args.count)

                if event_logs is None:
                    print("No event log fetched. Check debug log for issues.")
                    output = "No TD Eventlog data retrieved"
                else:
                    print(f"Total {len(event_logs)} of event logs fetched.")
                    res = CCTrustedApi.replay_cc_eventlog(event_logs)
                    print("Replayed result of collected event logs:")
                    for key in res.keys():
                        print(f"RTMR[{key}]: ")
                        print(f"     {res.get(key).get(12).hex()}")

                    print("Dump collected event logs:")
                    for event in event_logs:
                        if isinstance(event, TcgTpmsCelEvent):
                            print("TcgTpmsCelEvent")
                            if args.cel_format:
                                TcgTpmsCelEvent.encode(event, TcgEventLog.TCG_FORMAT_CEL_TLV).dump()
                            else:
                                event.to_pcclient_format().dump()
                        else:
                            event.dump()

                    output = result.getvalue()

        finally:
            output = result.getvalue()
            os.sys.stdout = old_stdout
            os.sys.stderr = old_stderr
            logging.root.handlers.clear()
            for handler in old_log_handlers:
                logging.root.addHandler(handler)

        if output_file:
            with open(output_file, "w", encoding="utf-8") as file_handle:
                file_handle.write(output)

        return {
            "status": 200,
            "message": "TD Eventlog retrieval successful",
            "td_eventlog": output,
        }
    except Exception as exc:
        return {"status": 500, "error": f"TD Eventlog retrieval failed: {str(exc)}"}


__all__ = [
    "DEFAULT_ATTEST_SERVICE_ENDPOINT",
    "get_raw_tdx_quote",
    "attest_tdx_quote",
    "get_tee_status",
    "fetch_td_eventlog",
]
