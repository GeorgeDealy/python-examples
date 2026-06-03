#!/usr/bin/env python3
"""Heating Fuel Cost Estimator — Streamlit web app."""

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import date

import streamlit as st

# ── Constants ─────────────────────────────────────────────────────────────────
EFFICIENCY  = 0.85
BTU_PER_GAL = 138_500
HDD_BASE    = 65
Cd          = 0.65

INSULATION_TIERS = {
    "New / tight":    (0.15, "new / tight construction"),
    "Average":        (0.35, "average insulation"),
    "Older / drafty": (0.75, "older / drafty construction"),
}

# ── Core logic ────────────────────────────────────────────────────────────────

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


@st.cache_data(show_spinner=False)
def geocode_zip(zip_code):
    try:
        data = fetch_json(f"https://api.zippopotam.us/us/{zip_code}")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise ValueError(f"Zip code {zip_code!r} not found.")
        raise
    place = data["places"][0]
    return {
        "lat":  float(place["latitude"]),
        "lon":  float(place["longitude"]),
        "name": f"{place['place name']}, {place['state abbreviation']}",
    }


@st.cache_data(show_spinner=False)
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


def season_hdd(dates, tmax, tmin, season):
    total = 0.0
    for d, hi, lo in zip(dates, tmax, tmin):
        if d < season["start"] or d > season["end"]:
            continue
        if hi is None or lo is None:
            continue
        total += max(0.0, HDD_BASE - (hi + lo) / 2)
    return round(total)


def estimate_cost(hdd, sqft, ua, price):
    btu_per_hdd     = sqft * ua * 24 * Cd
    gallons_per_hdd = btu_per_hdd / BTU_PER_GAL / EFFICIENCY
    gallons         = round(hdd * gallons_per_hdd)
    return gallons, gallons * price

# ── Page layout ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Heating Fuel Cost Estimator",
    page_icon="🔥",
    layout="centered",
)

st.title("🔥 Heating Fuel Cost Estimator")
st.caption("Estimate your seasonal heating oil cost using actual weather data for your zip code.")

col1, col2, col3 = st.columns(3)
with col1:
    zip_code = st.text_input("Zip code", placeholder="e.g. 02101", max_chars=5)
with col2:
    sqft = st.number_input("Home size (sq ft)", min_value=100, max_value=20_000, value=1_500, step=100)
with col3:
    price = st.number_input("Price per gallon ($)", min_value=0.01, value=4.50, step=0.01, format="%.2f")

insulation = st.radio(
    "Insulation quality",
    options=list(INSULATION_TIERS.keys()),
    index=1,
    horizontal=True,
)

run = st.button("Estimate →", type="primary", use_container_width=True)

if run:
    if not zip_code.isdigit() or len(zip_code) != 5:
        st.error("Please enter a valid 5-digit zip code.")
        st.stop()

    ua, insul_desc = INSULATION_TIERS[insulation]

    with st.spinner("Fetching data…"):
        try:
            location = geocode_zip(zip_code)
        except ValueError as e:
            st.error(str(e))
            st.stop()
        except Exception:
            st.error("Unable to look up that zip code. Please try again.")
            st.stop()

        seasons    = get_seasons()
        start_date = seasons[-1]["start"]
        end_date   = seasons[0]["end"]

        try:
            dates, tmax, tmin = fetch_weather(
                location["lat"], location["lon"], start_date, end_date
            )
        except Exception:
            st.error("Unable to fetch weather data. Please try again.")
            st.stop()

    # ── Results ───────────────────────────────────────────────────────────────
    st.divider()
    st.markdown(f"📍 **{location['name']}**")

    result_cols = st.columns(3)
    costs = []

    for i, (season, col) in enumerate(zip(seasons, result_cols)):
        hdd           = season_hdd(dates, tmax, tmin, season)
        gallons, cost = estimate_cost(hdd, sqft, ua, price)
        costs.append(cost)

        with col:
            st.metric(
                label=f"{season['label']} season" + (" 🔵" if i == 0 else ""),
                value=f"${cost:,.0f}",
            )
            st.caption(f"{hdd:,} heating degree days  \n~{gallons:,} gallons")

    avg = sum(costs) / len(costs)
    st.info(f"**3-year average estimated cost: ${avg:,.0f}**")
    st.caption(
        f"Assumes a {sqft:,.0f} sq ft home with {insul_desc}, oil furnace at 85% efficiency, "
        f"UA = {ua} BTU/hr/°F/sq ft, Cd = {Cd} (ASHRAE). "
        f"HDD calculated from actual daily temperature records via Open-Meteo. "
        f"Actual usage varies by thermostat settings and equipment efficiency."
    )
