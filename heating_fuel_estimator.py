#!/usr/bin/env python3
"""Heating Fuel Cost Estimator — command-line version."""

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date

# ── Constants ────────────────────────────────────────────────────────────────
EFFICIENCY  = 0.85
BTU_PER_GAL = 138_500
HDD_BASE    = 65
Cd          = 0.65   # ASHRAE degree-day correction for internal heat gains

INSULATION_TIERS = [
    ("New / tight",    0.15, "new / tight construction"),
    ("Average",        0.35, "average insulation"),
    ("Older / drafty", 0.75, "older / drafty construction"),
]

# ── Helpers ──────────────────────────────────────────────────────────────────

def fetch_json(url, params=None):
    if params:
        url += "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.loads(resp.read())


def get_seasons():
    today = date.today()
    last_end_year = today.year if today.month > 4 else today.year - 1
    seasons = []
    for i in range(3):
        end_year = last_end_year - i
        seasons.append({
            "label": f"{end_year - 1}–{str(end_year)[2:]}",
            "start": f"{end_year - 1}-10-01",
            "end":   f"{end_year}-04-30",
        })
    return seasons


def geocode_zip(zip_code):
    try:
        data = fetch_json(f"https://api.zippopotam.us/us/{zip_code}")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise ValueError(f"Zip code {zip_code} not found.")
        raise
    place = data["places"][0]
    return {
        "lat":  float(place["latitude"]),
        "lon":  float(place["longitude"]),
        "name": f"{place['place name']}, {place['state abbreviation']}",
    }


def fetch_weather(lat, lon, start_date, end_date):
    params = {
        "latitude":         lat,
        "longitude":        lon,
        "start_date":       start_date,
        "end_date":         end_date,
        "daily":            "temperature_2m_max,temperature_2m_min",
        "temperature_unit": "fahrenheit",
        "timezone":         "auto",
    }
    data = fetch_json("https://archive-api.open-meteo.com/v1/archive", params)
    daily = data["daily"]
    return daily["time"], daily["temperature_2m_max"], daily["temperature_2m_min"]


def season_hdd(dates, tmax, tmin, season, hdd_base=HDD_BASE):
    total = 0.0
    for d, hi, lo in zip(dates, tmax, tmin):
        if d < season["start"] or d > season["end"]:
            continue
        if hi is None or lo is None:
            continue
        total += max(0.0, hdd_base - (hi + lo) / 2)
    return round(total)


def estimate_cost(hdd, sqft, ua, price):
    btu_per_hdd    = sqft * ua * 24 * Cd
    gallons_per_hdd = btu_per_hdd / BTU_PER_GAL / EFFICIENCY
    gallons        = round(hdd * gallons_per_hdd)
    return gallons, gallons * price

# ── Input prompts ─────────────────────────────────────────────────────────────

def ask(prompt, validate, default=None):
    hint = f" [default: {default}]" if default is not None else ""
    while True:
        raw = input(f"{prompt}{hint}: ").strip()
        if not raw and default is not None:
            raw = str(default)
        try:
            value = validate(raw)
            if value is not None:
                return value
        except (ValueError, TypeError):
            pass


def prompt_zip():
    def validate(v):
        if v.isdigit() and len(v) == 5:
            return v
    return ask("Zip code", validate)


def prompt_sqft():
    def validate(v):
        f = float(v)
        if 100 <= f <= 20_000:
            return f
    return ask("Home size (sq ft)", validate, default=1500)


def prompt_price():
    def validate(v):
        f = float(v)
        if f > 0:
            return f
    return ask("Price per gallon ($)", validate)


def prompt_thermostat():
    def validate(v):
        n = int(v)
        if 55 <= n <= 80:
            return n
    return ask("Thermostat setting (°F)", validate, default=68)


def prompt_insulation():
    print("\nInsulation quality:")
    for i, (label, _, _) in enumerate(INSULATION_TIERS, 1):
        print(f"  {i}. {label}")
    def validate(v):
        n = int(v)
        if 1 <= n <= len(INSULATION_TIERS):
            return INSULATION_TIERS[n - 1]
    return ask("Select (1–3)", validate, default=2)

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("Heating Fuel Cost Estimator")
    print("─" * 50)

    zip_code         = prompt_zip()
    sqft             = prompt_sqft()
    price            = prompt_price()
    thermostat               = prompt_thermostat()
    tier_label, ua, insul_desc = prompt_insulation()

    print("\nFetching location…", end="", flush=True)
    try:
        location = geocode_zip(zip_code)
    except Exception as e:
        print(f"\nError: {e}")
        sys.exit(1)
    print(f" {location['name']}")

    seasons    = get_seasons()
    start_date = seasons[-1]["start"]
    end_date   = seasons[0]["end"]

    print("Fetching weather data…", end="", flush=True)
    try:
        dates, tmax, tmin = fetch_weather(
            location["lat"], location["lon"], start_date, end_date
        )
    except Exception as e:
        print(f"\nError: {e}")
        sys.exit(1)
    print(" done")

    # ── Results table ────────────────────────────────────────────────────────
    W = 54
    print(f"\n{'─' * W}")
    print(f"  Location : {location['name']}")
    print(f"  Home     : {sqft:,.0f} sq ft  |  Insulation: {tier_label}")
    print(f"  Fuel     : ${price:.2f} / gallon")
    print(f"{'─' * W}")
    print(f"  {'Season':<12}  {'HDDs':>6}  {'Gallons':>8}  {'Est. cost':>10}")
    print(f"{'─' * W}")

    total_cost = 0.0
    for i, season in enumerate(seasons):
        hdd             = season_hdd(dates, tmax, tmin, season, hdd_base=thermostat)
        gallons, cost   = estimate_cost(hdd, sqft, ua, price)
        total_cost     += cost
        flag            = "  ◀ most recent" if i == 0 else ""
        print(f"  {season['label']:<12}  {hdd:>6,}  {gallons:>8,}  ${cost:>8,.0f}{flag}")

    avg = total_cost / len(seasons)
    print(f"{'─' * W}")
    print(f"  {'3-year average':<30}  ${avg:>8,.0f}")
    print(f"{'─' * W}")
    print(
        f"\n  Assumes {insul_desc}, 85% furnace efficiency,\n"
        f"  UA = {ua} BTU/hr/°F/sq ft, Cd = {Cd} (ASHRAE).\n"
        f"  HDD data via Open-Meteo archive, base 65°F.\n"
    )


if __name__ == "__main__":
    main()
