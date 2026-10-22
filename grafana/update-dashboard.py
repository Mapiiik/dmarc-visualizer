#!/usr/bin/env python3
"""Takes parsedmarc's Grafana dashboard and adapts it to the OpenSearch data sources here.

    python3 grafana/update-dashboard.py [ref]

ref is a branch, tag or commit of github.com/domainaware/parsedmarc, master by default. The
dashboard is written to grafana/dashboards/dmarc-reports.json; name the commit it came from in
the commit message.
"""

import json
import sys
import urllib.request
from pathlib import Path

REPOSITORY = "domainaware/parsedmarc"
SOURCE = "dashboards/grafana/Grafana-DMARC_Reports.json"
TARGET = Path(__file__).parent / "dashboards" / "dmarc-reports.json"


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": "dmarc-visualizer"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8")


def main():
    ref = sys.argv[1] if len(sys.argv) > 1 else "master"
    commit = json.loads(fetch(f"https://api.github.com/repos/{REPOSITORY}/commits/{ref}"))["sha"]
    dashboard = json.loads(fetch(f"https://raw.githubusercontent.com/{REPOSITORY}/{commit}/{SOURCE}"))

    # The data source variables pick dmarc-ag and dmarc-fo by type, which is OpenSearch here
    for variable in dashboard["templating"]["list"]:
        if variable["type"] == "datasource" and variable["query"] == "elasticsearch":
            variable["query"] = "grafana-opensearch-datasource"

    # Failure Samples groups by "Arrival Date (UTC)", a column title rather than a field, so it never
    # shows anything. Under an "auto" interval its eight terms would also be refused by the OpenSearch
    # plugin as too many buckets; a fixed one with min_doc_count 1 makes a row per sample.
    # The column then gets the title its date format is set for.
    for panel in dashboard["panels"]:
        for target in panel.get("targets", []):
            for aggregation in target.get("bucketAggs", []):
                if aggregation["type"] == "date_histogram" and aggregation.get("field") == "Arrival Date (UTC)":
                    aggregation["field"] = "arrival_date"
                    aggregation["settings"]["interval"] = "1s"
                    for transformation in panel.get("transformations", []):
                        if transformation["id"] == "organize":
                            transformation["options"]["renameByName"]["arrival_date"] = "Arrival Date (UTC)"
                    print(f"{panel['title']}: grouped by arrival_date, every second")

    # Reports arrive a few times a day, reloading every panel every few seconds only loads OpenSearch
    dashboard["refresh"] = ""
    # Provisioned dashboards are found by uid, the id belongs to the database
    dashboard["id"] = None

    TARGET.write_text(json.dumps(dashboard, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(f"{TARGET.name}: {REPOSITORY}@{commit[:7]}")


if __name__ == "__main__":
    main()
