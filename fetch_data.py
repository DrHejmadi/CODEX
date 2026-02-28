#!/usr/bin/env python3
"""
Fetch voting data from the Danish Parliament (Folketinget) OData API.

Usage:
    python3 fetch_data.py

This script fetches all votes (Afstemninger) since the 2022 election,
along with individual votes (Stemmer), party info, and case titles.
Data is saved as JSON in the data/ directory.
"""

import json
import os
import time
import urllib.request
import urllib.parse
import urllib.error
import sys

API_BASE = "https://oda.ft.dk/api"
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
PAGE_SIZE = 100
RATE_LIMIT_DELAY = 0.5  # seconds between requests


def fetch_json(url, retries=3):
    """Fetch JSON from a URL with retries and rate limiting."""
    for attempt in range(retries):
        try:
            print(f"  GET {url}")
            req = urllib.request.Request(url)
            req.add_header("Accept", "application/json")
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            time.sleep(RATE_LIMIT_DELAY)
            return data
        except urllib.error.HTTPError as e:
            print(f"  HTTP {e.code}: {e.reason} (attempt {attempt + 1}/{retries})")
            if e.code == 429:
                time.sleep(5 * (attempt + 1))
            elif attempt == retries - 1:
                raise
            else:
                time.sleep(2 * (attempt + 1))
        except Exception as e:
            print(f"  Error: {e} (attempt {attempt + 1}/{retries})")
            if attempt == retries - 1:
                raise
            time.sleep(2 * (attempt + 1))


def fetch_all_pages(base_url):
    """Fetch all pages from an OData endpoint using $skip pagination."""
    all_items = []
    skip = 0
    while True:
        sep = "&" if "?" in base_url else "?"
        url = f"{base_url}{sep}$skip={skip}"
        data = fetch_json(url)
        items = data.get("value", [])
        if not items:
            break
        all_items.extend(items)
        print(f"  Fetched {len(all_items)} items so far...")
        skip += PAGE_SIZE
        if len(items) < PAGE_SIZE:
            break
    return all_items


def fetch_stemmetyper():
    """Fetch vote types (For, Imod, Fraværende, etc.)."""
    print("\n=== Fetching Stemmetyper (vote types) ===")
    url = f"{API_BASE}/Stemmetype"
    data = fetch_json(url)
    types = data.get("value", [])
    print(f"  Found {len(types)} vote types")
    for t in types:
        print(f"    {t['id']}: {t.get('type', '?')}")
    return {t["id"]: t.get("type", "Ukendt") for t in types}


def fetch_afstemningstyper():
    """Fetch vote category types (Endelig vedtagelse, etc.)."""
    print("\n=== Fetching Afstemningstyper (vote category types) ===")
    url = f"{API_BASE}/Afstemningstype"
    data = fetch_json(url)
    types = data.get("value", [])
    print(f"  Found {len(types)} vote category types")
    for t in types:
        print(f"    {t['id']}: {t.get('type', '?')}")
    return {t["id"]: t.get("type", "Ukendt") for t in types}


def fetch_partier():
    """Fetch parties (Aktør with typeid=5 are groups/parties)."""
    print("\n=== Fetching Partier (parties) ===")
    # typeid=5 is parties/groups in Aktør
    url = f"{API_BASE}/Akt%C3%B8r?$filter=typeid eq 5&$top={PAGE_SIZE}"
    parties = fetch_all_pages(
        f"{API_BASE}/Akt%C3%B8r?$filter=typeid eq 5&$top={PAGE_SIZE}"
    )
    print(f"  Found {len(parties)} parties/groups")
    return {p["id"]: p for p in parties}


def fetch_medlemmer_parti_mapping():
    """
    Fetch the mapping of members to parties via AktørAktør.
    rolleid for party membership is typically 15 (Medlem af).
    """
    print("\n=== Fetching member-party mapping (AktørAktør) ===")
    # Fetch all AktørAktør relations — we filter for relevant roles later
    mappings = fetch_all_pages(
        f"{API_BASE}/Akt%C3%B8rAkt%C3%B8r?$top={PAGE_SIZE}"
    )
    print(f"  Found {len(mappings)} actor-actor relations")
    return mappings


def fetch_afstemninger():
    """Fetch all votes since 2022-11-01."""
    print("\n=== Fetching Afstemninger (votes since 2022-11-01) ===")
    # Expand Møde to get the date, and Sagstrin/Sag for case title
    url = (
        f"{API_BASE}/Afstemning"
        f"?$expand=M%C3%B8de,Sagstrin($expand=Sag)"
        f"&$top={PAGE_SIZE}"
    )
    afstemninger = fetch_all_pages(url)

    # Filter by meeting date >= 2022-11-01
    filtered = []
    for a in afstemninger:
        møde = a.get("Møde", {})
        dato = møde.get("dato", "")
        if dato and dato >= "2022-11-01":
            filtered.append(a)

    print(f"  Total votes: {len(afstemninger)}, after date filter: {len(filtered)}")
    return filtered


def fetch_stemmer_for_afstemning(afstemning_id):
    """Fetch individual votes for a specific vote, expanded with actor info."""
    url = (
        f"{API_BASE}/Stemme"
        f"?$filter=afstemningid eq {afstemning_id}"
        f"&$expand=Akt%C3%B8r,Stemmetype"
        f"&$top={PAGE_SIZE}"
    )
    return fetch_all_pages(url)


def build_processed_data(afstemninger, stemmetyper, afstemningstyper):
    """Process raw data into a clean structure for the dashboard."""
    processed = []

    total = len(afstemninger)
    for i, a in enumerate(afstemninger):
        afs_id = a["id"]
        print(f"\n  Processing vote {i + 1}/{total} (id={afs_id})...")

        # Get individual votes
        stemmer = fetch_stemmer_for_afstemning(afs_id)

        # Build party vote summary
        parti_stemmer = {}
        for s in stemmer:
            aktør = s.get("Aktør") or s.get("Akt\u00f8r") or {}
            stemmetype = s.get("Stemmetype", {})
            vote_type = stemmetype.get("type", stemmetyper.get(s.get("typeid"), "Ukendt"))

            # Get party from actor's gruppenavnkort
            parti = aktør.get("gruppenavnkort", "Ukendt")
            if not parti:
                parti = "Ukendt"

            if parti not in parti_stemmer:
                parti_stemmer[parti] = {"For": 0, "Imod": 0, "Fraværende": 0, "Hverken for eller imod": 0}

            if vote_type in parti_stemmer[parti]:
                parti_stemmer[parti][vote_type] += 1
            else:
                parti_stemmer[parti][vote_type] = 1

        # Extract meeting date
        møde = a.get("Møde") or a.get("M\u00f8de") or {}
        dato = møde.get("dato", "")
        if dato:
            dato = dato[:10]  # Just the date part

        # Extract case title from Sagstrin -> Sag
        sagstrin = a.get("Sagstrin") or {}
        sag = sagstrin.get("Sag") or {}
        sag_titel = sag.get("titel") or sag.get("titelkort") or sagstrin.get("titel") or a.get("konklusion", "")
        if sag_titel and len(sag_titel) > 200:
            sag_titel = sag_titel[:200] + "..."

        afstemningstype = afstemningstyper.get(a.get("typeid"), "Ukendt")

        entry = {
            "id": afs_id,
            "nummer": a.get("nummer"),
            "dato": dato,
            "vedtaget": a.get("vedtaget"),
            "konklusion": (a.get("konklusion") or "")[:300],
            "kommentar": a.get("kommentar"),
            "type": afstemningstype,
            "sag_titel": sag_titel,
            "sag_id": sag.get("id"),
            "parti_stemmer": parti_stemmer,
            "total_stemmer": len(stemmer),
        }
        processed.append(entry)

    return processed


def main():
    os.makedirs(DATA_DIR, exist_ok=True)

    # Step 1: Fetch reference data
    stemmetyper = fetch_stemmetyper()
    afstemningstyper = fetch_afstemningstyper()

    # Save reference data
    with open(os.path.join(DATA_DIR, "stemmetyper.json"), "w", encoding="utf-8") as f:
        json.dump(stemmetyper, f, ensure_ascii=False, indent=2)
    with open(os.path.join(DATA_DIR, "afstemningstyper.json"), "w", encoding="utf-8") as f:
        json.dump(afstemningstyper, f, ensure_ascii=False, indent=2)

    # Step 2: Fetch all votes
    afstemninger = fetch_afstemninger()

    # Save raw data
    with open(os.path.join(DATA_DIR, "afstemninger_raw.json"), "w", encoding="utf-8") as f:
        json.dump(afstemninger, f, ensure_ascii=False, indent=2)
    print(f"\nSaved {len(afstemninger)} raw votes to data/afstemninger_raw.json")

    # Step 3: Process data with individual votes
    print("\n=== Processing votes and fetching individual vote records ===")
    print(f"This will make ~{len(afstemninger)} additional API calls. Be patient...")
    processed = build_processed_data(afstemninger, stemmetyper, afstemningstyper)

    # Save processed data
    output_path = os.path.join(DATA_DIR, "afstemninger.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(processed, f, ensure_ascii=False, indent=2)
    print(f"\nSaved {len(processed)} processed votes to {output_path}")
    print("Done! You can now open index.html in a browser.")


if __name__ == "__main__":
    main()
