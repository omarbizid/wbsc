"""Location text → structured fields (cities, country, UK flag).

Rules are gazetteer-based and deliberately conservative: a location we cannot
recognise yields no cities and country=None rather than a guess.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

UK_CITIES = {
    "london", "manchester", "birmingham", "leeds", "glasgow", "edinburgh", "bristol",
    "cardiff", "belfast", "liverpool", "sheffield", "newcastle", "newcastle upon tyne",
    "nottingham", "leicester", "cambridge", "oxford", "reading", "brighton", "southampton",
    "portsmouth", "milton keynes", "coventry", "bath", "york", "aberdeen", "dundee",
    "swansea", "exeter", "norwich", "plymouth", "derby", "stoke-on-trent", "sunderland",
    "guildford", "slough", "watford", "luton", "northampton", "peterborough", "ipswich",
    "chester", "warrington", "bradford", "hull", "preston", "bournemouth", "poole",
    "cheltenham", "gloucester", "basingstoke", "swindon", "crawley", "stevenage",
    "harrogate", "durham", "lincoln", "canterbury", "maidstone", "wolverhampton",
    "middlesbrough", "huddersfield", "blackpool", "bolton", "stockport", "salford",
    "inverness", "stirling", "leatherhead", "farnborough", "hemel hempstead", "st albans",
    "sale", "altrincham", "wakefield", "doncaster", "telford", "worcester", "hereford",
    "solihull", "hatfield", "welwyn garden city", "chelmsford", "colchester", "southend",
    "woking", "bracknell", "maidenhead", "high wycombe", "aylesbury", "bedford", "harlow",
    "dartford", "tunbridge wells", "horsham", "chichester", "winchester", "salisbury",
    "taunton", "truro", "newport", "wrexham", "bangor", "lancaster", "carlisle", "kendal",
    "scarborough", "grimsby", "loughborough", "burton upon trent", "stafford",
    "shrewsbury", "kidderminster", "redditch", "nuneaton", "rugby", "leamington spa",
    "warwick", "banbury", "didcot", "abingdon", "newbury", "epsom", "croydon", "kingston",
    "richmond", "uxbridge", "canary wharf", "city of london", "livingston",
    "paisley", "falkirk", "londonderry", "derry", "lisburn", "gateshead",
    "rotherham", "barnsley", "chesterfield", "mansfield", "oldham", "rochdale", "wigan",
    "st helens", "birkenhead", "knutsford", "crewe", "macclesfield", "cheadle",
}
UK_REGIONS = {
    "england", "scotland", "wales", "northern ireland", "greater london",
    "greater manchester", "west midlands", "east midlands", "south east", "south west",
    "north west", "north east", "yorkshire", "east anglia", "home counties",
}
UK_COUNTRY_TOKENS = {"uk", "u.k.", "united kingdom", "great britain", "gb", "gbr", "britain"}

# Non-UK countries and major cities that appear in multi-site postings. A location that
# names only these is not UK. Multi-word names are matched before single UK city names,
# so "New York" never matches the UK city "York".
OTHER_COUNTRIES = {
    "ireland": "IE", "republic of ireland": "IE", "united states": "US",
    "united states of america": "US", "usa": "US", "us": "US", "canada": "CA",
    "mexico": "MX", "brazil": "BR", "argentina": "AR", "chile": "CL", "colombia": "CO",
    "peru": "PE", "germany": "DE", "france": "FR", "netherlands": "NL", "the netherlands": "NL",
    "belgium": "BE", "luxembourg": "LU", "switzerland": "CH", "austria": "AT", "spain": "ES",
    "portugal": "PT", "italy": "IT", "greece": "GR", "malta": "MT", "cyprus": "CY",
    "poland": "PL", "czech republic": "CZ", "czechia": "CZ", "slovakia": "SK",
    "hungary": "HU", "romania": "RO", "bulgaria": "BG", "serbia": "RS", "croatia": "HR",
    "slovenia": "SI", "ukraine": "UA", "lithuania": "LT", "latvia": "LV", "estonia": "EE",
    "finland": "FI", "sweden": "SE", "norway": "NO", "denmark": "DK", "iceland": "IS",
    "turkey": "TR", "türkiye": "TR", "israel": "IL", "united arab emirates": "AE", "uae": "AE",
    "saudi arabia": "SA", "qatar": "QA", "egypt": "EG", "south africa": "ZA", "nigeria": "NG",
    "kenya": "KE", "morocco": "MA", "india": "IN", "pakistan": "PK", "singapore": "SG",
    "malaysia": "MY", "indonesia": "ID", "philippines": "PH", "vietnam": "VN",
    "thailand": "TH", "china": "CN", "hong kong": "HK", "taiwan": "TW", "japan": "JP",
    "south korea": "KR", "korea": "KR", "australia": "AU", "new zealand": "NZ",
    # cities
    "dublin": "IE", "cork": "IE", "galway": "IE", "new york": "US", "new york city": "US",
    "nyc": "US", "san francisco": "US", "sunnyvale": "US", "mountain view": "US",
    "seattle": "US", "austin": "US", "boston": "US", "chicago": "US", "denver": "US",
    "los angeles": "US", "atlanta": "US", "washington": "US", "toronto": "CA",
    "vancouver": "CA", "montreal": "CA", "são paulo": "BR", "sao paulo": "BR",
    "mexico city": "MX", "berlin": "DE", "munich": "DE", "hamburg": "DE", "frankfurt": "DE",
    "paris": "FR", "amsterdam": "NL", "rotterdam": "NL", "brussels": "BE", "zurich": "CH",
    "geneva": "CH", "vienna": "AT", "madrid": "ES", "barcelona": "ES", "lisbon": "PT",
    "porto": "PT", "milan": "IT", "rome": "IT", "athens": "GR", "warsaw": "PL",
    "krakow": "PL", "kraków": "PL", "prague": "CZ", "budapest": "HU", "bucharest": "RO",
    "sofia": "BG", "belgrade": "RS", "kyiv": "UA", "vilnius": "LT", "riga": "LV",
    "tallinn": "EE", "helsinki": "FI", "stockholm": "SE", "oslo": "NO", "copenhagen": "DK",
    "istanbul": "TR", "tel aviv": "IL", "dubai": "AE", "abu dhabi": "AE", "cape town": "ZA",
    "bangalore": "IN", "bengaluru": "IN", "hyderabad": "IN", "pune": "IN", "mumbai": "IN",
    "tokyo": "JP", "sydney": "AU", "melbourne": "AU", "auckland": "NZ",
    # regions: not UK, but no single country
    "emea": None, "europe": None, "eu": None, "apac": None, "americas": None, "latam": None,
    "north america": None,
}

_SPLIT = re.compile(r"\s*(?:;|\||/|\bor\b|\band\b|\+|,)\s*", re.I)
_PAREN = re.compile(r"[()\[\]]")


@dataclass
class LocationInfo:
    raw: str | None
    cities: list[str] = field(default_factory=list)
    country: str | None = None          # ISO alpha-2 of the UK part if any, else first other
    is_uk: bool = False
    mentions_remote: bool = False
    other_countries: list[str] = field(default_factory=list)


_OTHER_BY_LENGTH = sorted(OTHER_COUNTRIES, key=len, reverse=True)
_UK_BY_LENGTH = sorted(UK_CITIES, key=len, reverse=True)
_UK_COUNTRY_RX = re.compile(
    r"\b(uk|u\.k\.|united kingdom|great britain|england|scotland|wales|northern ireland)\b"
)


def _parse_part(part: str, info: LocationInfo) -> bool:
    """Parse one fragment; returns True if it refers to the UK."""
    # Remove non-UK place names first (longest first) so "new york" never yields "york".
    for name in _OTHER_BY_LENGTH:
        if re.search(rf"(?<![\w]){re.escape(name)}(?![\w])", part):
            code = OTHER_COUNTRIES[name]
            if code and code not in info.other_countries:
                info.other_countries.append(code)
            part = re.sub(rf"(?<![\w]){re.escape(name)}(?![\w])", " ", part)
    uk = False
    for city in _UK_BY_LENGTH:
        if re.search(rf"(?<![\w]){re.escape(city)}(?![\w])", part):
            name = " ".join(w if w in {"upon", "on", "of"} else w.capitalize()
                            for w in city.split())
            if name not in info.cities:
                info.cities.append(name)
            part = part.replace(city, " ")
            uk = True
    if _UK_COUNTRY_RX.search(part) or part.strip() in UK_REGIONS or part.strip() == "gb":
        uk = True
    return uk


def parse_location(raw: str | None, *fallback: str | None) -> LocationInfo:
    """Parse a location string.

    `fallback` strings (e.g. office names) are used only when `raw` contains no
    recognisable place at all. They must never override an explicit location such as
    "Riga, Latvia".
    """
    info = LocationInfo(raw=raw)
    uk_hit = _parse_text(raw, info)
    if not uk_hit and not info.other_countries and not info.cities:
        for text in fallback:
            uk_hit = _parse_text(text, info) or uk_hit
    info.is_uk = uk_hit
    if uk_hit:
        info.country = "GB"
    elif info.other_countries:
        info.country = info.other_countries[0]
    return info


def _parse_text(text: str | None, info: LocationInfo) -> bool:
    if not text:
        return False
    low = _PAREN.sub(" ", text.lower())
    if re.search(r"\bremote\b|\bwork from home\b|\bhome[- ]based\b", low):
        info.mentions_remote = True
    uk = False
    for part in _SPLIT.split(low):
        part = re.sub(r"\bremote\b|\bhybrid\b|\boffice\b|\bhq\b", " ", part)
        part = re.sub(r"\s+", " ", part).strip(" -–.")
        if part and _parse_part(part, info):
            uk = True
    return uk
