#!/usr/bin/env python3
"""Check latest.json and D1 results count."""
import json
import urllib.request


def main():
    # Check latest.json
    try:
        req = urllib.request.Request("https://pub.opencurelabs.ai/latest.json")
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())
        if isinstance(data, list):
            print(f"latest.json: {len(data)} entries")
            for i, e in enumerate(data[:5]):
                eid = e.get("id", "?")[:12]
                print(f"  [{i}] id={eid}... skill={e.get('skill')} date={e.get('date')}")
            if len(data) > 5:
                print(f"  ... and {len(data)-5} more")
        else:
            print(f"latest.json is not a list: {type(data)}")
    except Exception as ex:
        print(f"Error fetching latest.json: {ex}")

    # Check results count via API
    try:
        req2 = urllib.request.Request("https://pub.opencurelabs.ai/results?status=published")
        resp2 = urllib.request.urlopen(req2, timeout=10)
        data2 = json.loads(resp2.read())
        if isinstance(data2, dict):
            print(f"\nD1 published results: {data2.get('count', 'unknown')}")
        elif isinstance(data2, list):
            print(f"\nD1 published results: {len(data2)}")
    except Exception as ex:
        print(f"Error fetching results: {ex}")

if __name__ == "__main__":
    main()
