#!/usr/bin/env python3
"""
123SoldCash.com — Florida Wholesale Comparable Fetcher
Fetches real property data, comps, photos and buyer type for any FL address.
Uses only free public sources.
"""

import re
import json
import time
import argparse
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

# ── Optional imports (graceful fallback) ─────────────────────────
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

# ── Config ────────────────────────────────────────────────────────
GOOGLE_STREET_VIEW_KEY = ""   # Optional — leave empty for unsigned URLs (limited)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Florida county → Property Appraiser domain mapping
FL_COUNTY_PA = {
    "broward":      "bcpa.net",
    "miami-dade":   "miamidade.gov/pa",
    "palm beach":   "pbcgov.com/papa",
    "orange":       "ocpafl.org",
    "hillsborough": "hcpafl.org",
    "pinellas":     "pcpao.gov",
    "duval":        "coj.net/departments/property-appraiser",
    "lee":          "leepa.org",
    "polk":         "polkpa.org",
    "volusia":      "volusia.org/property-appraiser",
    "seminole":     "scpafl.org",
    "sarasota":     "sc-pa.com",
    "manatee":      "manateepao.com",
    "collier":      "collierappraiser.com",
    "brevard":      "bcpao.us",
    "pasco":        "pascopa.com",
    "osceola":      "property.appraiser.osceola.org",
    "lake":         "lakecopropappr.com",
    "alachua":      "acpafl.org",
    "leon":         "leonpa.org",
    "escambia":     "escpa.org",
    "marion":       "marionpa.net",
    "st. lucie":    "paslc.gov",
    "st. johns":    "sjcpa.us",
    "charlotte":    "charlottepao.gov",
    "flagler":      "flaglerpa.com",
}


def get(url: str, timeout=15) -> str:
    """HTTP GET with browser headers."""
    if HAS_REQUESTS:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        r.raise_for_status()
        return r.text
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def soup(html: str):
    if HAS_BS4:
        return BeautifulSoup(html, "html.parser")
    return None


# ── 1. Parse address ──────────────────────────────────────────────
def parse_address(full_address: str) -> dict:
    """Split full address into components."""
    parts = [p.strip() for p in full_address.split(",")]
    result = {"full": full_address, "street": "", "city": "", "state": "FL", "zip": ""}
    if len(parts) >= 1:
        result["street"] = parts[0]
    if len(parts) >= 2:
        result["city"] = parts[1]
    if len(parts) >= 3:
        state_zip = parts[2].strip().split()
        result["state"] = state_zip[0] if state_zip else "FL"
        result["zip"] = state_zip[1] if len(state_zip) > 1 else ""
    return result


# ── 2. Detect Florida county ──────────────────────────────────────
def detect_county(city: str, zip_code: str) -> str:
    """Best-effort county detection from city or zip."""
    CITY_COUNTY = {
        "miami": "miami-dade", "miami beach": "miami-dade", "hialeah": "miami-dade",
        "fort lauderdale": "broward", "pompano beach": "broward", "hollywood": "broward",
        "miramar": "broward", "pembroke pines": "broward", "coral springs": "broward",
        "boca raton": "palm beach", "west palm beach": "palm beach", "boynton beach": "palm beach",
        "delray beach": "palm beach", "lake worth": "palm beach",
        "orlando": "orange", "kissimmee": "osceola", "sanford": "seminole",
        "tampa": "hillsborough", "brandon": "hillsborough", "clearwater": "pinellas",
        "st. petersburg": "pinellas", "st petersburg": "pinellas",
        "jacksonville": "duval", "tallahassee": "leon", "gainesville": "alachua",
        "fort myers": "lee", "cape coral": "lee", "naples": "collier",
        "sarasota": "sarasota", "bradenton": "manatee",
        "daytona beach": "volusia", "port st. lucie": "st. lucie",
        "pensacola": "escambia", "ocala": "marion",
    }
    city_lower = city.lower().strip()
    for city_key, county in CITY_COUNTY.items():
        if city_key in city_lower:
            return county

    # ZIP prefix fallback
    if zip_code:
        z = zip_code[:3]
        ZIP_COUNTY = {
            "330": "miami-dade", "331": "miami-dade", "332": "miami-dade",
            "333": "broward", "334": "palm beach",
            "327": "orange", "328": "orange",
            "335": "hillsborough", "337": "pinellas",
            "322": "duval", "323": "leon",
            "338": "lee", "341": "collier",
            "342": "sarasota", "345": "alachua",
        }
        if z in ZIP_COUNTY:
            return ZIP_COUNTY[z]
    return "unknown"


# ── 3. Street View photo URL ──────────────────────────────────────
def street_view_url(address: str, size="600x400") -> str:
    """Generate Google Street View URL (works without API key, lower resolution)."""
    encoded = urllib.parse.quote(address)
    if GOOGLE_STREET_VIEW_KEY:
        return (f"https://maps.googleapis.com/maps/api/streetview"
                f"?size={size}&location={encoded}&key={GOOGLE_STREET_VIEW_KEY}")
    # Unsigned fallback (works for display, may have usage limits)
    return f"https://maps.googleapis.com/maps/api/streetview?size={size}&location={encoded}"


def maps_link(address: str) -> str:
    return "https://www.google.com/maps/search/" + urllib.parse.quote(address)


# ── 4. Zillow search ─────────────────────────────────────────────
def zillow_search_url(address: str) -> str:
    encoded = urllib.parse.quote(address)
    return f"https://www.zillow.com/homes/{encoded}_rb/"


def redfin_search_url(address: str) -> str:
    encoded = urllib.parse.quote(address)
    return f"https://www.redfin.com/FL/{encoded}"


def fetch_zillow_comps(address_obj: dict) -> list:
    """
    Fetch recent sold comps from Zillow search page.
    Returns list of comp dicts. Falls back gracefully if blocked.
    """
    city  = address_obj["city"]
    state = address_obj["state"]
    zip_  = address_obj["zip"]
    search_q = f"{city}, {state} {zip_}" if zip_ else f"{city}, {state}"
    url = f"https://www.zillow.com/homes/recently_sold/{urllib.parse.quote(search_q)}_rb/"

    comps = []
    try:
        html = get(url, timeout=12)
        s = soup(html)
        if not s:
            return comps

        # Zillow embeds data in __NEXT_DATA__ or similar JSON
        scripts = s.find_all("script", {"type": "application/json"})
        for sc in scripts:
            try:
                data = json.loads(sc.string or "")
                # Navigate the JSON tree looking for listing data
                raw = json.dumps(data)
                if "soldPrice" in raw or "lastSoldPrice" in raw:
                    # Extract whatever we can find
                    prices = re.findall(r'"(?:soldPrice|lastSoldPrice)":(\d+)', raw)
                    addresses = re.findall(r'"streetAddress":"([^"]+)"', raw)
                    dates = re.findall(r'"dateSold":"([^"]+)"', raw)
                    beds = re.findall(r'"bedrooms?":(\d+)', raw)
                    baths = re.findall(r'"bathrooms?":(\d+\.?\d*)', raw)
                    sqfts = re.findall(r'"livingArea(?:Value)?":(\d+)', raw)
                    for i, price in enumerate(prices[:10]):
                        comp = {
                            "address": addresses[i] if i < len(addresses) else f"Comp #{i+1}, {city}",
                            "price": int(price),
                            "saleDate": dates[i][:10] if i < len(dates) else "",
                            "beds": beds[i] if i < len(beds) else "3",
                            "baths": baths[i] if i < len(baths) else "2",
                            "sf": sqfts[i] if i < len(sqfts) else "",
                            "source": "Zillow",
                            "sourceUrl": url,
                        }
                        comps.append(comp)
                    if comps:
                        break
            except (json.JSONDecodeError, TypeError):
                continue
    except Exception as e:
        print(f"  [Zillow] Could not fetch comps: {e}")

    return comps


# ── 5. Redfin sold comps ──────────────────────────────────────────
def fetch_redfin_comps(address_obj: dict) -> list:
    """Fetch sold comps from Redfin."""
    city  = address_obj["city"]
    state = address_obj["state"]
    zip_  = address_obj["zip"]
    comps = []

    try:
        # Redfin GIS API for sold homes
        search = urllib.parse.quote(f"{city}, {state}")
        url = f"https://www.redfin.com/stingray/api/gis?al=1&market=miami&region_id=&region_type=&status=9&uipt=1,2&sf=1,2,3,5,6,7&num_homes=20&ord=redfin-recommended-asc&page_number=1"
        # Use search autocomplete first
        ac_url = f"https://www.redfin.com/stingray/do/location-autocomplete?location={search}&v=2"
        html = get(ac_url, timeout=10)
        # Strip Redfin's {}&&{} wrapper
        clean = re.sub(r'^[^{]*', '', html).strip()
        data = json.loads(clean)
        region_id = None
        for item in data.get("payload", {}).get("sections", []):
            for row in item.get("rows", []):
                if row.get("type") == "2":  # city type
                    region_id = row.get("id", {}).get("tableId")
                    break
            if region_id:
                break

        if region_id:
            sold_url = (f"https://www.redfin.com/stingray/api/gis?al=1"
                        f"&region_id={region_id}&region_type=2&status=9"
                        f"&uipt=1,2&num_homes=20&ord=redfin-recommended-asc&page_number=1")
            html2 = get(sold_url, timeout=10)
            clean2 = re.sub(r'^[^{]*', '', html2).strip()
            data2 = json.loads(clean2)
            homes = data2.get("payload", {}).get("homes", [])
            for h in homes[:12]:
                price = h.get("price", {}).get("value", 0)
                addr  = h.get("streetLine", {}).get("value", "")
                city_ = h.get("cityStateZip", {}).get("value", "")
                beds_ = str(h.get("beds", ""))
                baths_= str(h.get("baths", ""))
                sqft_ = str(h.get("sqFt", {}).get("value", ""))
                sold_d= h.get("soldDate", "")
                url_  = "https://www.redfin.com" + h.get("url", "")
                photos= h.get("photos", [])
                photo = photos[0] if photos else ""
                if price:
                    comps.append({
                        "address": f"{addr}, {city_}",
                        "price": price,
                        "saleDate": sold_d[:10] if sold_d else "",
                        "beds": beds_,
                        "baths": baths_,
                        "sf": sqft_,
                        "photo": photo,
                        "source": "Redfin",
                        "sourceUrl": url_,
                    })
    except Exception as e:
        print(f"  [Redfin] Could not fetch comps: {e}")

    return comps


# ── 6. County Property Appraiser ─────────────────────────────────
def fetch_county_property(address_obj: dict) -> dict:
    """Fetch owner and sale history from county property appraiser."""
    county = detect_county(address_obj["city"], address_obj["zip"])
    result = {
        "owner": None,
        "lastSaleAmount": None,
        "lastSaleDate": None,
        "assessedValue": None,
        "yearBuilt": None,
        "sf": None,
        "beds": None,
        "baths": None,
        "lotSize": None,
        "county": county,
        "paUrl": None,
    }

    # Broward County (BCPA) — has good JSON API
    if county == "broward":
        try:
            street = address_obj["street"]
            num   = re.match(r"(\d+)", street)
            sname = re.sub(r"^\d+\s*", "", street)
            if num:
                url = (f"https://bcpa.net/RecMenu.asp?saddr={num.group(1)}"
                       f"&sname={urllib.parse.quote(sname)}")
                result["paUrl"] = url
                html = get(url, timeout=12)
                s = soup(html)
                if s:
                    text = s.get_text()
                    owner_m = re.search(r"Owner[:\s]+([A-Z][A-Z\s,\.]+?)(?:\n|Mailing)", text)
                    if owner_m:
                        result["owner"] = owner_m.group(1).strip()
                    sale_m = re.search(r"Sale Date[:\s]+([\d/]+).*?Sale Price[:\s]+\$([\d,]+)", text, re.S)
                    if sale_m:
                        result["lastSaleDate"] = sale_m.group(1)
                        result["lastSaleAmount"] = int(sale_m.group(2).replace(",", ""))
                    yb_m = re.search(r"Year Built[:\s]+(\d{4})", text)
                    if yb_m:
                        result["yearBuilt"] = yb_m.group(1)
                    sf_m = re.search(r"Living Area[:\s]+([\d,]+)", text)
                    if sf_m:
                        result["sf"] = sf_m.group(1).replace(",", "")
        except Exception as e:
            print(f"  [BCPA] {e}")

    # Miami-Dade (MDPA)
    elif county == "miami-dade":
        try:
            addr_enc = urllib.parse.quote(address_obj["street"])
            url = f"https://www.miamidade.gov/Apps/PA/PApublicServiceProxy/PaServicesProxy.ashx?Operation=GetPropertySearchByAddress&clientId=_mdcsearch&SearchValue={addr_enc}&SearchType=Adjusted"
            result["paUrl"] = f"https://www.miamidade.gov/propertysearch/#/?query={addr_enc}"
            html = get(url, timeout=12)
            data = json.loads(html)
            items = data.get("MinimumPropertyInfos", {}).get("MinimumPropertyInfo", [])
            if items:
                prop = items[0]
                result["owner"] = prop.get("PrimaryOwner", "")
                result["assessedValue"] = prop.get("AssessedValue", "")
        except Exception as e:
            print(f"  [MDPA] {e}")

    # Palm Beach County
    elif county == "palm beach":
        try:
            addr_enc = urllib.parse.quote(address_obj["street"])
            url = f"https://pbcgov.com/papa/Departments/PropertyAppraiser/PropertySearch/main/Search.aspx?s={addr_enc}"
            result["paUrl"] = url
        except Exception as e:
            print(f"  [PBCPA] {e}")

    # Generic Florida fallback — use Florida Department of Revenue search
    else:
        result["paUrl"] = (f"https://floridarevenue.com/property/Pages/Public_PropertyTax.aspx"
                           f"?county={urllib.parse.quote(county)}")

    return result


# ── 7. Sunbiz LLC lookup ──────────────────────────────────────────
def check_buyer_type(buyer_name: str) -> dict:
    """
    Check if buyer is LLC/Corp using Sunbiz.org (Florida corporate registry).
    Returns buyer type and Sunbiz URL.
    """
    if not buyer_name:
        return {"type": "UNKNOWN", "sunbizUrl": None}

    # Quick keyword check first
    keywords = ["LLC", "INC", "CORP", "HOLDINGS", "PROPERTIES", "INVESTMENTS",
                "GROUP", "CAPITAL", "ACQUISITIONS", "TRUST", "FUND", "REALTY",
                "VENTURES", "PARTNERS", "ASSOCIATES", "ENTERPRISES"]
    upper = buyer_name.upper()
    for kw in keywords:
        if kw in upper:
            sunbiz_url = ("https://search.sunbiz.org/Inquiry/CorporationSearch/SearchResults"
                          f"?inquiryType=EntityName&inquiryDirectionType=ForwardList"
                          f"&searchNameOrder=&masterDataToListOn=&EntityName="
                          f"{urllib.parse.quote(buyer_name)}&listNameOrder=")
            return {"type": "LLC/INVESTOR", "sunbizUrl": sunbiz_url}

    # Try Sunbiz search for any corporate match
    try:
        url = ("https://search.sunbiz.org/Inquiry/CorporationSearch/SearchResults"
               f"?inquiryType=EntityName&EntityName={urllib.parse.quote(buyer_name)}")
        html = get(url, timeout=8)
        if "No filing information found" not in html and len(html) > 500:
            s = soup(html)
            if s:
                rows = s.select("table.result-list tr")
                if len(rows) > 1:
                    return {"type": "LLC/INVESTOR", "sunbizUrl": url}
    except Exception:
        pass

    return {"type": "RETAIL BUYER", "sunbizUrl": None}


# ── 8. Build photo URLs for comps ─────────────────────────────────
def enrich_comp_photos(comps: list) -> list:
    """Add Street View photo and Zillow/Redfin links to each comp."""
    enriched = []
    for c in comps:
        addr = c.get("address", "")
        c["streetViewUrl"] = street_view_url(addr)
        c["googleMapsUrl"] = maps_link(addr)
        if not c.get("sourceUrl"):
            c["zillowUrl"] = zillow_search_url(addr)
            c["redfinUrl"] = redfin_search_url(addr)
        # Format price
        price = c.get("price", 0)
        if isinstance(price, int) and price > 0:
            sf = c.get("sf", "")
            if sf:
                try:
                    price_sf = round(price / int(str(sf).replace(",", "")))
                    c["priceSF"] = f"${price_sf}"
                except Exception:
                    c["priceSF"] = ""
            c["priceFormatted"] = f"${price:,}"
        enriched.append(c)
    return enriched


# ── 9. Classify all buyers ────────────────────────────────────────
def classify_buyers(comps: list) -> list:
    """Add buyer type classification to each comp."""
    for c in comps:
        buyer = c.get("buyerName", "")
        btype = check_buyer_type(buyer)
        c["buyerType"] = btype["type"]
        c["sunbizUrl"] = btype["sunbizUrl"]
    return comps


# ── 10. Main analysis function ────────────────────────────────────
def analyze_property(full_address: str) -> dict:
    """
    Main entry point — analyze a Florida property.
    Returns complete JSON with property data, comps, photos, buyer types.
    """
    print(f"\n{'='*60}")
    print(f"  123SoldCash — Florida Wholesale Analyzer")
    print(f"  Address: {full_address}")
    print(f"{'='*60}\n")

    addr = parse_address(full_address)
    county = detect_county(addr["city"], addr["zip"])
    print(f"  Detected county: {county}")

    # Step 1: County Property Appraiser data
    print("  [1/4] Fetching county property data...")
    prop_data = fetch_county_property(addr)
    time.sleep(1)

    # Step 2: Sold comps from Redfin
    print("  [2/4] Fetching sold comps from Redfin...")
    redfin_comps = fetch_redfin_comps(addr)
    time.sleep(1)

    # Step 3: Sold comps from Zillow (supplement)
    print("  [3/4] Fetching sold comps from Zillow...")
    zillow_comps = fetch_zillow_comps(addr)
    time.sleep(1)

    # Merge comps (Redfin first, Zillow supplements)
    all_comps = redfin_comps[:8] + zillow_comps[:4]
    # Deduplicate by address
    seen = set()
    unique_comps = []
    for c in all_comps:
        key = c.get("address", "")[:20].lower()
        if key not in seen:
            seen.add(key)
            unique_comps.append(c)

    # Step 4: Enrich with photos and buyer classification
    print("  [4/4] Enriching comps with photos and buyer classification...")
    enriched = enrich_comp_photos(unique_comps)
    classified = classify_buyers(enriched)

    # Split into 6-month and 12-month buckets
    now = datetime.now()
    six_months_ago = now - timedelta(days=180)
    sold6, sold12 = [], []
    for c in classified:
        date_str = c.get("saleDate", "")
        try:
            sale_date = datetime.strptime(date_str[:10], "%Y-%m-%d")
            if sale_date >= six_months_ago:
                sold6.append(c)
            else:
                sold12.append(c)
        except Exception:
            sold12.append(c)

    # Build output
    result = {
        "generatedAt": datetime.now().isoformat(),
        "address": full_address,
        "county": county,
        "property": {
            "address": full_address,
            "owner": prop_data.get("owner"),
            "sf": prop_data.get("sf"),
            "yearBuilt": prop_data.get("yearBuilt"),
            "beds": prop_data.get("beds"),
            "baths": prop_data.get("baths"),
            "lotSize": prop_data.get("lotSize"),
            "lastSaleAmount": prop_data.get("lastSaleAmount"),
            "lastSaleDate": prop_data.get("lastSaleDate"),
            "assessedValue": prop_data.get("assessedValue"),
            "paUrl": prop_data.get("paUrl"),
            "streetViewUrl": street_view_url(full_address),
            "googleMapsUrl": maps_link(full_address),
            "zillowUrl": zillow_search_url(full_address),
            "redfinUrl": redfin_search_url(full_address),
        },
        "sold6": sold6,
        "sold12": sold12,
        "compsTotal": len(classified),
        "investorCount": sum(1 for c in classified if c.get("buyerType") == "LLC/INVESTOR"),
        "cashCount": sum(1 for c in classified if c.get("buyerType") == "CASH BUYER"),
    }

    # Market stats
    all_prices = [c["price"] for c in classified if c.get("price", 0) > 0]
    if all_prices:
        result["avgSalePrice"] = round(sum(all_prices) / len(all_prices))
        result["medianSalePrice"] = sorted(all_prices)[len(all_prices) // 2]
        result["investorPct"] = round(result["investorCount"] / len(classified) * 100)
        result["cashPct"] = round((result["investorCount"] + result["cashCount"]) / len(classified) * 100)

    print(f"\n  Done! Found {len(classified)} comps ({len(sold6)} last 6 months)")
    print(f"  LLC/Investor buyers: {result['investorCount']} ({result.get('investorPct', 0)}%)")
    return result


# ── CLI ───────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="123SoldCash — Florida Wholesale Comparable Fetcher"
    )
    parser.add_argument(
        "address",
        nargs="?",
        default="438 NE 2nd St, Pompano Beach, FL 33060",
        help="Full property address (e.g. '438 NE 2nd St, Pompano Beach, FL 33060')"
    )
    parser.add_argument(
        "--output", "-o",
        default="comps_result.json",
        help="Output JSON file path"
    )
    parser.add_argument(
        "--street-view-key",
        default="",
        help="Optional Google Street View API key"
    )
    args = parser.parse_args()

    global GOOGLE_STREET_VIEW_KEY
    if args.street_view_key:
        GOOGLE_STREET_VIEW_KEY = args.street_view_key

    # Check dependencies
    if not HAS_REQUESTS:
        print("  TIP: Install 'requests' for better HTTP support: pip install requests")
    if not HAS_BS4:
        print("  TIP: Install 'beautifulsoup4' for HTML parsing: pip install beautifulsoup4")

    result = analyze_property(args.address)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"\n  Results saved to: {args.output}")
    print(f"\n{'='*60}")
    print("  SUMMARY")
    print(f"{'='*60}")
    print(f"  Address    : {result['address']}")
    print(f"  County     : {result['county']}")
    print(f"  Owner      : {result['property'].get('owner') or 'Not found'}")
    print(f"  Last Sale  : ${result['property'].get('lastSaleAmount') or 'N/A'}")
    print(f"  Comps found: {result['compsTotal']}")
    print(f"  LLC/Invest : {result['investorCount']} ({result.get('investorPct', 0)}%)")
    print(f"  Avg price  : ${result.get('avgSalePrice', 0):,}")
    print(f"  PA link    : {result['property'].get('paUrl') or 'N/A'}")
    print(f"  Zillow     : {result['property']['zillowUrl']}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
