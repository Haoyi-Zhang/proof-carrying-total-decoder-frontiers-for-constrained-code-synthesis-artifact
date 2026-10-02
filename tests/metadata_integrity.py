"""Check bibliographic, provenance, claim-ledger, and packaging metadata.

This is an offline structural audit.  It confirms that the frozen metadata used by
this artifact is internally complete and mutually consistent; it does not replace
inspection of the cited primary publications.
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
RESULT = ROOT / "results" / "metadata-integrity.json"

DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$", re.IGNORECASE)
DATE_RE = re.compile(r"^20\d\d-[01]\d-[0-3]\d$")
PLACEHOLDER_RE = re.compile(
    r"(?:\bTODO\b|\bTBD\b|REPLACE[_ -]?ME|anonymous\.4open\.science/r/|"
    r"github\.com/[^\s]*pareto-complete-certificates-error)",
    re.IGNORECASE,
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def read_csv(name: str) -> tuple[list[str], list[dict[str, str]]]:
    path = ROOT / name
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        require(reader.fieldnames is not None, f"{name} has no header")
        rows = list(reader)
    require(rows, f"{name} is empty")
    return list(reader.fieldnames), rows


def valid_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def main() -> None:
    lit_fields, literature = read_csv("literature-audit.csv")
    expected_lit_fields = {
        "key", "title", "authors", "year", "venue", "doi", "primary_url",
        "access_date", "read_depth", "supported_claim", "integration",
        "license_note", "cited_in_final", "citation_occurrences",
        "bibliography_entry_present",
    }
    require(set(lit_fields) == expected_lit_fields, "literature-audit.csv schema drift")
    require(len(literature) >= 55, "fewer than 55 audited scholarly references")
    require(len(literature) == 60, "the frozen manuscript contract requires exactly 60 audited references")

    keys = [row["key"].strip() for row in literature]
    titles = [row["title"].strip() for row in literature]
    dois = [row["doi"].strip().lower() for row in literature]
    urls = [row["primary_url"].strip() for row in literature]
    require(all(keys), "blank literature key")
    require(len(set(keys)) == len(keys), "duplicate literature key")
    require(len(set(titles)) == len(titles), "duplicate literature title")
    require(len(set(dois)) == len(dois), "duplicate or blank DOI")
    require(len(set(urls)) == len(urls), "duplicate or blank primary URL")

    for row in literature:
        key = row["key"].strip()
        require(re.fullmatch(r"[a-z][a-z0-9_-]*", key) is not None, f"invalid literature key {key!r}")
        require(row["title"].strip() and row["authors"].strip() and row["venue"].strip(), f"incomplete metadata for {key}")
        require(re.fullmatch(r"(?:19|20)\d\d", row["year"].strip()) is not None, f"bad year for {key}")
        require(DOI_RE.fullmatch(row["doi"].strip()) is not None, f"bad DOI for {key}")
        require(valid_url(row["primary_url"].strip()), f"bad primary URL for {key}")
        require(DATE_RE.fullmatch(row["access_date"].strip()) is not None, f"bad access date for {key}")
        require(row["read_depth"].strip() and row["supported_claim"].strip(), f"missing reading/claim audit for {key}")
        require(row["integration"].strip() and row["license_note"].strip(), f"missing provenance terms for {key}")
        require(row["cited_in_final"].strip().lower() == "yes", f"uncited audit row {key}")
        require(row["bibliography_entry_present"].strip().lower() == "yes", f"missing bibliography entry for {key}")
        try:
            occurrences = int(row["citation_occurrences"])
        except ValueError as exc:
            raise ValueError(f"bad citation count for {key}") from exc
        require(occurrences >= 1, f"zero citation occurrences for {key}")

    ext_fields, resources = read_csv("external_resources.csv")
    expected_ext_fields = {
        "name", "url", "license", "access_date", "resource_type",
        "acquisition_method", "integration_mode", "supported_claim",
        "internals_modified",
    }
    require(set(ext_fields) == expected_ext_fields, "external_resources.csv schema drift")
    require(len(resources) >= len(literature) + 7, "external-resource ledger is incomplete")
    scholarly = [row for row in resources if row["resource_type"].strip() == "scholarly literature"]
    require(len(scholarly) == len(literature), "scholarly resource count differs from literature audit")
    require({row["name"].strip() for row in scholarly} == set(titles), "scholarly resource titles differ from literature audit")
    for index, row in enumerate(resources, start=2):
        require(row["name"].strip() and row["license"].strip(), f"incomplete external resource row {index}")
        require(DATE_RE.fullmatch(row["access_date"].strip()) is not None, f"bad resource access date at row {index}")
        require(row["resource_type"].strip() and row["acquisition_method"].strip(), f"missing resource method at row {index}")
        require(row["integration_mode"].strip() and row["supported_claim"].strip(), f"missing resource use at row {index}")
        require(row["internals_modified"].strip().lower() in {"no", "not applicable"}, f"unreviewed internal modification at row {index}")
        if row["url"].strip():
            require(valid_url(row["url"].strip()), f"bad resource URL at row {index}")
        else:
            require(row["resource_type"].strip() == "scientific input", f"unexpected blank resource URL at row {index}")

    claim_fields, claims = read_csv("claim_evidence_ledger.csv")
    expected_claim_fields = {
        "claim_id", "claim", "manuscript_location", "argument_or_certificate",
        "artifact_source", "raw_result", "maturity", "fresh_recheck",
    }
    require(set(claim_fields) == expected_claim_fields, "claim_evidence_ledger.csv schema drift")
    require(len(claims) >= 21, "claim ledger is incomplete")
    claim_ids = [row["claim_id"].strip() for row in claims]
    require(len(set(claim_ids)) == len(claim_ids), "duplicate claim identifier")
    for row in claims:
        require(re.fullmatch(r"C\d\d", row["claim_id"].strip()) is not None, "bad claim identifier")
        require(all(value.strip() for value in row.values()), f"blank claim evidence field in {row['claim_id']}")
        require("proposed" not in row["maturity"].lower(), f"unmatured claim remains in {row['claim_id']}")
        for relative in [item.strip() for item in row["artifact_source"].split(";") if item.strip()]:
            matches = list(ROOT.glob(relative)) if any(ch in relative for ch in "*?[") else [ROOT / relative]
            require(any(path.exists() for path in matches), f"missing claim source {relative}")
        for relative in [item.strip() for item in row["raw_result"].split(";") if item.strip()]:
            # These files are finalized by the parent driver after all child
            # stages, so a child-stage metadata audit cannot require them yet.
            if relative in {
                "results/summary.csv",
                "results/campaign.json",
                "results/commands.json",
                "results/metadata-integrity.json",
                "results/evidence-counts.json",
            }:
                continue
            matches = list(ROOT.glob(relative)) if any(ch in relative for ch in "*?[") else [ROOT / relative]
            require(any(path.exists() for path in matches), f"missing claim result {relative}")

    required = {
        "README.md", "LICENSE", "reproduce.py", "inputs/cases.json",
        "inputs/fixed-codebooks.json", "proofs/derivations.md",
        "src/synthesis.py", "src/checker.py", "src/frontier_proofs.py",
        "src/frontier_proof_check.py", "inputs/anchor-pam3.json",
        "src/anchor_census.py", "src/anchor_census_check.py",
        "tests/anchor_census_controls.py", "tests/encoding_properties.py",
    }
    require(all((ROOT / item).is_file() for item in required), "required repository file is missing")

    text_files = [ROOT / "README.md", *(ROOT / "proofs").glob("*.md")]
    for path in text_files:
        match = PLACEHOLDER_RE.search(path.read_text(encoding="utf-8", errors="replace"))
        require(match is None, f"placeholder or fabricated repository address in {path.relative_to(ROOT)}")

    report = {
        "accepted": True,
        "scholarly_references_checked": len(literature),
        "unique_dois_checked": len(set(dois)),
        "primary_urls_checked": len(urls),
        "external_resources_checked": len(resources),
        "claim_records_checked": len(claims),
        "scope": "Offline structural consistency and provenance audit; primary-source reading depth remains as recorded per row.",
    }
    RESULT.parent.mkdir(exist_ok=True)
    RESULT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
