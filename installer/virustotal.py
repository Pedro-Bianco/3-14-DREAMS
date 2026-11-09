"""Scan a release installer on VirusTotal before publishing it.

Usage, from the repository root:
    python installer\\virustotal.py installer\\Output\\PIDreams-Setup-<version>.exe

Needs a free VirusTotal API key in the VT_API_KEY environment variable (never in the repo).
The installer is public once released, so sending it to VirusTotal exposes nothing new.
Exit code 1 if any engine flags the file, so a release can be stopped and the case reviewed.
"""

import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid

API = "https://www.virustotal.com/api/v3"


def _request(url: str, key: str, data: bytes | None = None, content_type: str | None = None) -> dict:
    headers = {"x-apikey": key}
    if content_type:
        headers["Content-Type"] = content_type
    with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers), timeout=600) as r:
        return json.load(r)


def _known_report(sha256: str, key: str) -> dict | None:
    try:
        return _request(f"{API}/files/{sha256}", key)["data"]["attributes"]
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def _upload_and_wait(path: str, key: str) -> dict:
    upload_url = _request(f"{API}/files/upload_url", key)["data"]  # required for files > 32 MB
    boundary = uuid.uuid4().hex
    with open(path, "rb") as f:
        body = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
            f'filename="{os.path.basename(path)}"\r\nContent-Type: application/octet-stream\r\n\r\n'
        ).encode() + f.read() + f"\r\n--{boundary}--\r\n".encode()
    analysis_id = _request(upload_url, key, body, f"multipart/form-data; boundary={boundary}")["data"]["id"]
    print("uploaded; waiting for the engines (usually 2-10 min)...")
    while True:
        time.sleep(30)  # free API: 4 requests per minute
        attributes = _request(f"{API}/analyses/{analysis_id}", key)["data"]["attributes"]
        if attributes["status"] == "completed":
            return attributes


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    key = os.environ.get("VT_API_KEY")
    if not key:
        print("VT_API_KEY is not set (free key: virustotal.com > profile > API key)")
        return 2
    path = sys.argv[1]
    with open(path, "rb") as f:
        sha256 = hashlib.file_digest(f, "sha256").hexdigest()

    report = _known_report(sha256, key)
    if report is not None:
        stats, results = report["last_analysis_stats"], report["last_analysis_results"]
    else:
        report = _upload_and_wait(path, key)
        stats, results = report["stats"], report["results"]

    flagged = {name: r["result"] for name, r in results.items() if r["category"] in ("malicious", "suspicious")}
    print(f"sha256 {sha256}")
    print(f"engines: {stats.get('malicious', 0)} malicious, {stats.get('suspicious', 0)} suspicious, "
          f"{stats.get('undetected', 0)} undetected")
    for name, result in sorted(flagged.items()):
        print(f"  {name}: {result}")
    print(f"report: https://www.virustotal.com/gui/file/{sha256}")
    return 1 if flagged else 0


if __name__ == "__main__":
    sys.exit(main())
