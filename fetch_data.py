#!/usr/bin/env python3
"""
Fetch voting data from the Danish Parliament (Folketinget) OData API.

Usage:
    python3 fetch_data.py              # Full fetch
    python3 fetch_data.py --update     # Only fetch new votes since last run
    python3 fetch_data.py --test       # Test API with 3 votes

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
from datetime import datetime

API_BASE = "https://oda.ft.dk/api"
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
PAGE_SIZE = 100
RATE_LIMIT_DELAY = 0.5  # seconds between requests
ELECTION_DATE = "2022-11-01"
CHECKPOINT_FILE = os.path.join(DATA_DIR, "checkpoint.json")


def fetch_json(url, retries=3):
    """Fetch JSON from a URL with retries and rate limiting."""
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url)
            req.add_header("Accept", "application/json")
            req.add_header("User-Agent", "FolketingetDashboard/1.0")
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            time.sleep(RATE_LIMIT_DELAY)
            return data
        except urllib.error.HTTPError as e:
            print(f"  HTTP {e.code}: {e.reason} (attempt {attempt + 1}/{retries})")
            body = ""
            try:
                body = e.read().decode("utf-8")[:200]
            except Exception:
                pass
            if body:
                print(f"  Response: {body}")
            if e.code == 429:
                wait = 5 * (attempt + 1)
                print(f"  Rate limited. Waiting {wait}s...")
                time.sleep(wait)
            elif e.code >= 500:
                wait = 3 * (attempt + 1)
                print(f"  Server error. Waiting {wait}s...")
                time.sleep(wait)
            elif attempt == retries - 1:
                raise
            else:
                time.sleep(2 * (attempt + 1))
        except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
            print(f"  Connection error: {e} (attempt {attempt + 1}/{retries})")
            if attempt == retries - 1:
                raise
            time.sleep(3 * (attempt + 1))


def fetch_all_pages(base_url, label="items"):
    """Fetch all pages from an OData endpoint using $skip pagination."""
    all_items = []
    skip = 0
    while True:
        sep = "&" if "?" in base_url else "?"
        url = f"{base_url}{sep}$skip={skip}"
        print(f"  [{label}] Fetching skip={skip}...")
        data = fetch_json(url)
        items = data.get("value", [])
        if not items:
            break
        all_items.extend(items)
        skip += PAGE_SIZE
        if len(items) < PAGE_SIZE:
            break
    print(f"  [{label}] Total: {len(all_items)}")
    return all_items


def fetch_stemmetyper():
    """Fetch vote types (For, Imod, Fraværende, etc.)."""
    print("\n--- Stemmetyper (vote types) ---")
    data = fetch_json(f"{API_BASE}/Stemmetype")
    types = data.get("value", [])
    for t in types:
        print(f"  {t['id']}: {t.get('type', '?')}")
    return {t["id"]: t.get("type", "Ukendt") for t in types}


def fetch_afstemningstyper():
    """Fetch vote category types (Endelig vedtagelse, etc.)."""
    print("\n--- Afstemningstyper (vote categories) ---")
    data = fetch_json(f"{API_BASE}/Afstemningstype")
    types = data.get("value", [])
    for t in types:
        print(f"  {t['id']}: {t.get('type', '?')}")
    return {t["id"]: t.get("type", "Ukendt") for t in types}


def fetch_afstemninger(since_date=ELECTION_DATE):
    """Fetch all votes since the given date."""
    print(f"\n--- Afstemninger since {since_date} ---")
    # Use $expand to get Møde (date) and Sagstrin->Sag (case title)
    url = (
        f"{API_BASE}/Afstemning"
        f"?$expand=M%C3%B8de,Sagstrin($expand=Sag)"
        f"&$top={PAGE_SIZE}"
    )
    afstemninger = fetch_all_pages(url, label="Afstemning")

    # Filter by meeting date
    filtered = []
    for a in afstemninger:
        møde = a.get("Møde") or a.get("M\u00f8de") or {}
        dato = møde.get("dato", "")
        if dato and dato >= since_date:
            filtered.append(a)

    print(f"  Total: {len(afstemninger)}, after {since_date}: {len(filtered)}")
    return filtered


def fetch_stemmer_for_afstemning(afstemning_id):
    """Fetch individual votes for a specific vote."""
    url = (
        f"{API_BASE}/Stemme"
        f"?$filter=afstemningid eq {afstemning_id}"
        f"&$expand=Akt%C3%B8r,Stemmetype"
        f"&$top={PAGE_SIZE}"
    )
    return fetch_all_pages(url, label=f"Stemme(afs={afstemning_id})")


def process_one_vote(a, stemmetyper, afstemningstyper):
    """Process a single Afstemning into dashboard format."""
    afs_id = a["id"]

    # Fetch individual votes
    stemmer = fetch_stemmer_for_afstemning(afs_id)

    # Build party vote summary
    parti_stemmer = {}
    for s in stemmer:
        aktør = s.get("Aktør") or s.get("Akt\u00f8r") or {}
        stemmetype = s.get("Stemmetype") or {}
        vote_type = stemmetype.get("type") or stemmetyper.get(s.get("typeid"), "Ukendt")

        parti = aktør.get("gruppenavnkort") or "Ukendt"

        if parti not in parti_stemmer:
            parti_stemmer[parti] = {
                "For": 0, "Imod": 0,
                "Fraværende": 0, "Hverken for eller imod": 0
            }

        if vote_type in parti_stemmer[parti]:
            parti_stemmer[parti][vote_type] += 1
        else:
            parti_stemmer[parti][vote_type] = 1

    # Extract meeting date
    møde = a.get("Møde") or a.get("M\u00f8de") or {}
    dato = (møde.get("dato") or "")[:10]

    # Extract case title
    sagstrin = a.get("Sagstrin") or {}
    sag = sagstrin.get("Sag") or {}
    sag_titel = (
        sag.get("titel") or sag.get("titelkort")
        or sagstrin.get("titel") or a.get("konklusion") or ""
    )
    if len(sag_titel) > 200:
        sag_titel = sag_titel[:200] + "..."

    return {
        "id": afs_id,
        "nummer": a.get("nummer"),
        "dato": dato,
        "vedtaget": a.get("vedtaget"),
        "konklusion": (a.get("konklusion") or "")[:300],
        "kommentar": a.get("kommentar"),
        "type": afstemningstyper.get(a.get("typeid"), "Ukendt"),
        "sag_titel": sag_titel,
        "sag_id": sag.get("id"),
        "parti_stemmer": parti_stemmer,
        "total_stemmer": len(stemmer),
    }


def load_checkpoint():
    """Load checkpoint to resume interrupted fetch."""
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"processed_ids": [], "last_run": None}


def save_checkpoint(processed_ids):
    """Save checkpoint for resuming."""
    with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "processed_ids": processed_ids,
            "last_run": datetime.now().isoformat(),
        }, f, ensure_ascii=False, indent=2)


def save_results(processed):
    """Save processed data to JSON."""
    output_path = os.path.join(DATA_DIR, "afstemninger.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(processed, f, ensure_ascii=False, indent=2)
    print(f"\nSaved {len(processed)} votes to {output_path}")


def main():
    os.makedirs(DATA_DIR, exist_ok=True)

    # Parse args
    test_mode = "--test" in sys.argv
    update_mode = "--update" in sys.argv

    if test_mode:
        print("=== TEST MODE: Fetching only 3 votes ===\n")

    # Step 1: Reference data
    stemmetyper = fetch_stemmetyper()
    afstemningstyper = fetch_afstemningstyper()

    with open(os.path.join(DATA_DIR, "stemmetyper.json"), "w", encoding="utf-8") as f:
        json.dump(stemmetyper, f, ensure_ascii=False, indent=2)
    with open(os.path.join(DATA_DIR, "afstemningstyper.json"), "w", encoding="utf-8") as f:
        json.dump(afstemningstyper, f, ensure_ascii=False, indent=2)

    # Step 2: Fetch votes
    afstemninger = fetch_afstemninger()

    # Save raw data
    with open(os.path.join(DATA_DIR, "afstemninger_raw.json"), "w", encoding="utf-8") as f:
        json.dump(afstemninger, f, ensure_ascii=False, indent=2)
    print(f"Saved {len(afstemninger)} raw votes")

    if test_mode:
        afstemninger = afstemninger[:3]

    # Step 3: Load existing data for incremental updates
    existing = []
    existing_ids = set()
    if update_mode:
        output_path = os.path.join(DATA_DIR, "afstemninger.json")
        if os.path.exists(output_path):
            with open(output_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
            existing_ids = {e["id"] for e in existing}
            print(f"\nLoaded {len(existing)} existing processed votes")

    # Load checkpoint for resuming interrupted fetches
    checkpoint = load_checkpoint()
    checkpoint_ids = set(checkpoint["processed_ids"])

    # Step 4: Process votes
    print(f"\n--- Processing {len(afstemninger)} votes ---")
    processed = list(existing)
    processed_ids = list(existing_ids | checkpoint_ids)

    for i, a in enumerate(afstemninger):
        afs_id = a["id"]

        # Skip already processed
        if afs_id in existing_ids or afs_id in checkpoint_ids:
            continue

        print(f"\n[{i + 1}/{len(afstemninger)}] Vote id={afs_id}")
        try:
            entry = process_one_vote(a, stemmetyper, afstemningstyper)
            processed.append(entry)
            processed_ids.append(afs_id)

            # Save checkpoint every 10 votes
            if len(processed_ids) % 10 == 0:
                save_results(processed)
                save_checkpoint(processed_ids)
                print(f"  Checkpoint saved ({len(processed)} votes)")

        except Exception as e:
            print(f"  ERROR processing vote {afs_id}: {e}")
            print(f"  Saving progress and continuing...")
            save_results(processed)
            save_checkpoint(processed_ids)
            continue

    # Final save
    save_results(processed)
    save_checkpoint(processed_ids)

    # Clean up checkpoint if we finished everything
    if len(processed) >= len(afstemninger):
        if os.path.exists(CHECKPOINT_FILE):
            os.remove(CHECKPOINT_FILE)

    print(f"\nDone! {len(processed)} votes processed.")
    print("Open index.html in a browser to view the dashboard.")


if __name__ == "__main__":
    main()
