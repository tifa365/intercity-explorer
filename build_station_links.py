#!/usr/bin/env python3
"""
Pre-builds station_links.json: a {station_name -> wikidata_qid} map.
Run once before serving the app:
    python3 build_station_links.py
"""
import json, re, time, urllib.parse, urllib.request

CENTER_ALIGN_MAX = 12
RIGHT_ALIGN_MAX = 20
RIGHT_EDGE_DELTA_MAX = 0.5
VERTICAL_GAP_MAX = 11

STATION_SUFFIXES    = {"Hbf", "West", "Ost", "Nord", "Süd", "Mitte", "Flughafen", "Ostbahnhof"}
LOCATIVE_PREPS      = {"am", "im", "an", "bei", "ob", "a.", "i."}
# German qualifying words that are never standalone station names
INCOMPLETE_PREFIXES = {"Bad", "Lutherstadt", "Schwäbisch", "Fränkisch"}
STATION_TERMS    = [
    "railway station", "railway halt", "train station",
    "bahnhof", "haltepunkt", "station in",
    "gare",            # French stations
    "airport station", # airport rail stations
    "hauptbahnhof",
]

# Manually verified QIDs for stations the API cannot match automatically.
# Fragments from false label splits are set to None (intentionally skipped).
MANUAL_QIDS = {
    # Real station whose German-only Wikidata description evades English search
    "Hude": "Q5928360",  # Bahnhof Hude (Oldenburg)
    # German stations (parentheticals / hyphens trip the auto-search)
    "Wiesloch-Walldorf":    "Q324979",   # Wiesloch-Walldorf station
    "Weinheim (Bergstr) Hbf": "Q324220", # Weinheim (Bergstraße) Hbf
    "Papenburg (Ems)":      "Q7132569",  # Bahnhof Papenburg
    "Iserlohn-Letmathe":    "Q29878878", # Bahnhof Iserlohn-Letmathe
    "Marburg (Lahn)":       "Q471844",   # Bahnhof Marburg (Lahn)
    "Horb":                 "Q9293808",  # Horb station
    "Stadtroda":            "Q801458",   # Haltepunkt Stadtroda
    # Airport stations
    "Köln/Bonn Flughafen":    "Q569474", # Cologne Bonn Airport station
    "Leipzig/Halle Flughafen":"Q325491", # Leipzig/Halle Airport railway station
    # French / Luxembourg stations
    "Metz":      "Q801179",  # Gare de Metz-Ville
    "Nancy":     "Q2178663", # Gare de Nancy-Ville
    "Mulhouse":  "Q801205",  # Gare de Mulhouse-Ville
    "Forbach":   "Q2717025", # Gare de Forbach
    "Luxemburg": "Q801140",  # Luxembourg railway station
    # Swiss stations
    "Luzern": "Q455450", # Lucerne railway station
    "Bern":   "Q28870",  # Bahnhof Bern
    "Chur":   "Q663869", # Bahnhof Chur
    "Thun":   "Q801516", # Bahnhof Thun
    # Austrian stations
    "Bregenz":             "Q15282663", # Bregenz railway station
    "Feldkirch":           "Q698785",   # Feldkirch railway station
    "Amstetten NÖ":        "Q800385",   # Amstetten railway station
    "St. Johann im Pongau":"Q37918335", # St. Johann im Pongau railway station
    # Czech station
    "Plzeň hl. n.": "Q1981595", # Plzeň hlavní nádraží
}


def is_continuation(prev, nxt):
    if prev.endswith("-"):
        return True
    if nxt.endswith("-"):                   # next span is itself a hyphen-continuation fragment
        return True
    if nxt and nxt[0] != nxt[0].upper():   # lowercase start → always continue
        return True
    if nxt.startswith("("):
        return True
    if nxt.strip() in STATION_SUFFIXES:
        return True
    prev_words = prev.strip().split()
    # Known German qualifying prefixes that never stand alone as station names
    if prev.strip() in INCOMPLETE_PREFIXES:
        return True
    # Locative preposition ending: "Prien am" → "Chiemsee", always incomplete
    if prev_words and prev_words[-1].lower() in LOCATIVE_PREPS:
        return True
    return False


def merge_text(prev, nxt):
    if not prev.endswith("-"):
        return prev + " " + nxt
    return (prev[:-1] + nxt) if nxt[0] == nxt[0].lower() else (prev + nxt)


def right_edge(span):
    return 2 * span["cx"] - span["x"]


def same_column(a, b):
    dcx = abs(a["cx"] - b["cx"])
    if dcx < CENTER_ALIGN_MAX:
        return "center"
    if dcx < RIGHT_ALIGN_MAX and abs(right_edge(a) - right_edge(b)) <= RIGHT_EDGE_DELTA_MAX:
        return "right"
    return None


def group_stations(spans):
    sorted_spans = sorted(spans, key=lambda s: (s["cy"], s["cx"]))
    used = set()
    result = []
    for i, span in enumerate(sorted_spans):
        if i in used:
            continue
        used.add(i)
        chain = [span]
        tail = span
        extended = True
        while extended:
            extended = False
            for j, b in enumerate(sorted_spans):
                if j in used:
                    continue
                dcy = b["cy"] - tail["cy"]
                column_match = same_column(tail, b)
                if 0 < dcy < VERTICAL_GAP_MAX and (
                        (column_match == "center" and is_continuation(tail["text"], b["text"]))
                        or column_match == "right"):
                    used.add(j)
                    chain.append(b)
                    tail = b
                    extended = True
                    break
        name = chain[0]["text"]
        for k in range(1, len(chain)):
            name = merge_text(name, chain[k]["text"])
        cx = sum(c["cx"] for c in chain) / len(chain)
        cy = sum(c["cy"] for c in chain) / len(chain)
        result.append({"name": name.strip(), "cx": cx, "cy": cy})
    return result


def _search_wikidata(query, limit=15):
    url = (
        "https://www.wikidata.org/w/api.php?action=wbsearchentities"
        "&search=" + urllib.parse.quote(query) +
        f"&language=en&uselang=en&type=item&limit={limit}&format=json"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "station-link-builder/1.0"})
    try:
        data = json.loads(urllib.request.urlopen(req, timeout=10).read())
        for item in data.get("search", []):
            desc = item.get("description", "").lower()
            if any(t in desc for t in STATION_TERMS):
                return item["id"]
    except Exception as e:
        print(f"  WARN: {e}")
    return None


def _simplify_name(name):
    """Generate fallback search variants for names with parentheticals or suffixes."""
    variants = []
    stripped = re.sub(r"\s*\(.*?\)\s*$", "", name).strip()
    if stripped and stripped != name:
        variants.append(stripped)
    if name.endswith(" Hbf"):
        variants.append(name[:-4].strip())
    if not any(name.endswith(s) for s in ("Hbf", "Bahnhof", "Flughafen")):
        variants.append(name + " Bahnhof")
    return variants


def find_wikidata_qid(name):
    qid = _search_wikidata(name)
    if qid:
        return qid
    for variant in _simplify_name(name):
        time.sleep(0.35)
        qid = _search_wikidata(variant)
        if qid:
            return qid
    return None


def main():
    spans = json.load(open("station_names_positions.json", encoding="utf-8"))
    stations = group_stations(spans)
    print(f"Grouped {len(spans)} spans → {len(stations)} stations")
    station_names = [s["name"] for s in stations]

    # Load existing results so the script is safe to re-run / resume.
    try:
        links = json.load(open("station_links.json", encoding="utf-8"))
        print(f"Resuming — {len(links)} entries already cached")
    except FileNotFoundError:
        links = {}

    # Apply manual entries to the cache before deciding which current stations need lookup.
    added = sum(1 for k in MANUAL_QIDS if links.get(k) is None)
    for name, qid in MANUAL_QIDS.items():
        if links.get(name) is None:
            links[name] = qid
    if added:
        print(f"Applied {added} manual entries")

    # Only process current grouped stations not yet present in the cache.
    todo = [s for s in stations if s["name"] not in links]
    print(f"{len(todo)} stations to look up via Wikidata API")

    for i, station in enumerate(todo):
        name = station["name"]
        qid = find_wikidata_qid(name)
        links[name] = qid
        status = qid if qid else "—"
        print(f"  [{i+1}/{len(todo)}] {name:45s} {status}")
        time.sleep(0.35)

    current_links = {name: links.get(name) for name in station_names}

    json.dump(current_links, open("station_links.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    found = sum(1 for v in current_links.values() if v)
    print(f"\nDone — {found}/{len(current_links)} stations matched. Saved station_links.json")


if __name__ == "__main__":
    main()
