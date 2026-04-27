#!/usr/bin/env python3
"""
Pre-builds route_links.json: {route_name -> {zugfinder, bahn_expert, fernbahn}} map.
Run once before serving the app:
    python3 build_route_links.py
"""
import json, re, urllib.parse


def parse_route(name):
    """Split 'ICE 77' → ('ICE', '77'), 'ICE/TGV 82/83' → ('ICE/TGV', '82/83')."""
    m = re.match(r'^([A-Z][A-Z/]*)\s+(.+)$', name.strip())
    if not m:
        return name.strip(), ""
    return m.group(1), m.group(2).strip()


def first_num(num_str):
    """Extract the first integer from '82/83', '55-56', '77' → '82', '55', '77'."""
    m = re.match(r'(\d+)', num_str)
    return m.group(1) if m else num_str


def make_links(name):
    rtype, num = parse_route(name)

    # Zugfinder: ICE_77, IC_55-56  (spaces → underscore, slashes → underscore)
    zf_key = f"{rtype}_{num}".replace(" ", "_").replace("/", "_")
    zugfinder = f"https://www.zugfinder.net/de/zug-{urllib.parse.quote(zf_key, safe='-_')}"

    # Fernbahn.de: just the first number (77, 55, 82, …)
    fn = first_num(num)
    fernbahn = f"https://www.fernbahn.de/datenbank/suche?zugnummer={urllib.parse.quote(fn)}"

    return {"zugfinder": zugfinder, "fernbahn": fernbahn}


def main():
    labels = json.load(open("route_labels.json", encoding="utf-8"))
    unique_names = sorted(set(e["name"] for e in labels))
    print(f"Computing links for {len(unique_names)} unique route names")

    links = {}
    for name in unique_names:
        links[name] = make_links(name)
        l = links[name]
        print(f"  {name:25s}  zf={l['zugfinder'].split('/')[-1]:<20s}  "
              f"fb=…{l['fernbahn'].split('=')[-1]}")

    json.dump(links, open("route_links.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"\nDone — {len(links)} routes saved to route_links.json")


if __name__ == "__main__":
    main()
