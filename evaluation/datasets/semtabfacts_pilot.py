"""Import a small set of cell-anchored statements from official SEM-TAB-FACTS dev XML."""

import argparse
import json
import re
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree
from zipfile import ZipFile


def select_dev(archive_path):
    """Yield six labeled alignment cases while retaining original cell coordinates."""
    quotas = {"entailed": 3, "refuted": 3}
    with ZipFile(archive_path) as archive:
        for name in sorted(archive.namelist()):
            entry = PurePosixPath(name)
            if entry.parts[:2] != ("v1.1", "output") or entry.suffix != ".xml":
                continue
            if not entry.stem.isdecimal():
                continue
            root = ElementTree.fromstring(archive.read(name).decode("utf-8", errors="replace"))
            for table in root.iter("table"):
                for statement in table.iter("statement"):
                    verdict = statement.get("type")
                    text = statement.get("text", "")
                    if not quotas.get(verdict) or not re.search(r"\d", text):
                        continue
                    evidence = []
                    for cell in table.iter("cell"):
                        if any(
                            item.get("type") == "relevant"
                            and item.get("statement_id") == statement.get("id")
                            for item in cell.findall("evidence")
                        ):
                            evidence.append(
                                {
                                    key: int(cell.attrib[key])
                                    for key in ("row-start", "row-end", "col-start", "col-end")
                                }
                            )
                    if evidence:
                        quotas[verdict] -= 1
                        yield {
                            "external_document_id": entry.stem,
                            "external_table_id": table.get("id"),
                            "external_statement_id": statement.get("id"),
                            "claim_text": text,
                            "external_verdict": verdict,
                            "source_split": "development",
                            "external_cell_anchors": evidence,
                        }
                    if not any(quotas.values()):
                        return


def main():
    """Write a new secondary alignment sample from the official dev ZIP."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dev-zip", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    cases = list(select_dev(args.dev_zip))
    if len(cases) != 6:
        parser.error("Expected the six cases from the official v1.1 dev release.")
    with args.output.open("x", encoding="utf-8") as output:
        for row in cases:
            output.write(json.dumps(row, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
