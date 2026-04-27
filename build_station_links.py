#!/usr/bin/env python3
"""
Pre-builds station_links.json: a {station_name -> wikidata_qid} map.
Run once before serving the app:
    python3 build_station_links.py
"""
import json, re, time, urllib.parse, urllib.request

STATION_SUFFIXES = {"Hbf", "West", "Ost", "Nord", "Süd", "Mitte", "Flughafen"}
LOCATIVE_PREPS   = {"am", "im", "an", "bei", "ob", "a.", "i."}
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
    # Remaining PDF coordinate-gap artefacts (two spans too far apart to merge)
    "Hbf":    None,  # orphan suffix of Wiesbaden Hbf (dcx=13.7, just over threshold)
    "Berlin": None,  # orphan prefix of Berlin Gesundbrunnen (dcx=18.3)
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
    if nxt and nxt[0] != nxt[0].upper():   # lowercase start → always continue
        return True
    if nxt.startswith("("):
        return True
    if nxt.strip() in STATION_SUFFIXES:
        return True
    prev_words = prev.strip().split()
    # Single-word prefix like "Bad", "Lutherstadt", "Schwäbisch" — clearly incomplete
    if len(prev_words) == 1 and prev.strip() not in STATION_SUFFIXES:
        return True
    # Locative preposition ending: "Prien am" → "Chiemsee", always incomplete
    if prev_words and prev_words[-1].lower() in LOCATIVE_PREPS:
        return True
    return False


def merge_text(prev, nxt):
    if not prev.endswith("-"):
        return prev + " " + nxt
    return (prev[:-1] + nxt) if nxt[0] == nxt[0].lower() else (prev + nxt)


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
                if abs(tail["cx"] - b["cx"]) < 12 and 0 < dcy < 11 \
                        and is_continuation(tail["text"], b["text"]):
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

    # Load existing results so the script is safe to re-run / resume.
    try:
        links = json.load(open("station_links.json", encoding="utf-8"))
        print(f"Resuming — {len(links)} entries already cached")
    except FileNotFoundError:
        links = {}

    # Apply manual entries: always overwrite None (unresolved or intentional skip).
    # Already-resolved QIDs (non-None) are left untouched.
    added = sum(1 for k, v in MANUAL_QIDS.items() if links.get(k) is None)
    for name, qid in MANUAL_QIDS.items():
        if links.get(name) is None:
            links[name] = qid
    if added:
        print(f"Applied {added} manual entries")

    # Only process stations not yet in links (manual Nones are already present).
    todo = [s for s in stations if s["name"] not in links]
    print(f"{len(todo)} stations to look up via Wikidata API")

    for i, station in enumerate(todo):
        name = station["name"]
        qid = find_wikidata_qid(name)
        links[name] = qid
        status = qid if qid else "—"
        print(f"  [{i+1}/{len(todo)}] {name:45s} {status}")
        time.sleep(0.35)

    json.dump(links, open("station_links.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    found = sum(1 for v in links.values() if v)
    print(f"\nDone — {found}/{len(links)} stations matched. Saved station_links.json")


if __name__ == "__main__":
    main()
