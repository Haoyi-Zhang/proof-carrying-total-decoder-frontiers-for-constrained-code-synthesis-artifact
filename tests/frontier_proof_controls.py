"""Mutation controls for the proof-carrying frontier checker."""
from __future__ import annotations

import copy
import json
import resource
import time
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from frontier_proof_check import verify_case  # independent checker under test

ROOT = Path(__file__).resolve().parents[1]


def load(case: str):
    specs = {s["id"]: s for s in json.loads((ROOT / "inputs/cases.json").read_text())}
    cert = json.loads((ROOT / "results/proof-frontiers" / f"{case}.json").read_text())
    exhaustive = json.loads((ROOT / "results" / f"{case}.json").read_text())
    return cert, specs[case], exhaustive


def rejected(name: str, mutation) -> dict:
    cert, spec, exhaustive = load(mutation[0])
    changed = copy.deepcopy(cert)
    mutation[1](changed)
    try:
        verify_case(changed, spec, exhaustive)
    except (ValueError, KeyError, TypeError, IndexError) as error:
        return {"name": name, "passed": True, "rejection": type(error).__name__ + ": " + str(error)}
    return {"name": name, "passed": False, "rejection": "mutation was accepted"}


def first_lower_plane(cert: dict, *, internal: bool = False) -> dict:
    for collection in (cert["encoder_planes"], cert["decoder_planes"]):
        for plane in collection.values():
            proof = plane["lower_bound"]["proof"]
            if proof is not None and (not internal or len(proof["nodes"]) > 1):
                return plane
    raise AssertionError("no suitable lower-bound proof")


def main() -> None:
    started = time.process_time()
    controls = []
    controls.append(rejected("omit-one-encoder", ("B05", lambda c: c["mappings"].pop())))
    controls.append(rejected("replace-proof-root-by-conflict-leaf", (
        "B05", lambda c: first_lower_plane(c, internal=True)["lower_bound"]["proof"].__setitem__("root", 0)
    )))
    controls.append(rejected("branch-outside-cnf", (
        "B05", lambda c: first_lower_plane(c, internal=True)["lower_bound"]["proof"]["nodes"][1].__setitem__(0, 10**6)
    )))
    controls.append(rejected("understate-product-minimum", (
        "B05", lambda c: first_lower_plane(c).__setitem__(
            "minimum_products", first_lower_plane(c)["minimum_products"] - 1
        )
    )))
    controls.append(rejected("flip-attaining-circuit-mask", (
        "B05", lambda c: first_lower_plane(c)["terms"][0].__setitem__("outputs", 0)
    )))
    controls.append(rejected("remove-semantic-core-source", (
        "B01", lambda c: next(
            item for mapping in c["mappings"] for item in mapping["bounds"]
            if "semantic_obstruction" in item
        )["semantic_obstruction"].__setitem__("source_messages", [])
    )))
    controls.append(rejected("alter-decoder-relation", (
        "B05", lambda c: next(iter(c["decoder_planes"].values()))["legal_outputs"][0].append(1)
    )))
    controls.append(rejected("drop-frontier-point", ("B05", lambda c: c["frontier"].pop())))
    if not all(item["passed"] for item in controls):
        raise RuntimeError("a proof-certificate mutation survived")
    output = {
        "controls": controls,
        "passed": len(controls),
        "cpu_seconds": time.process_time() - started,
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    }
    path = ROOT / "results/proof-frontiers/controls.json"
    path.write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
