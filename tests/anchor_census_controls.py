"""Mutation controls for the external PAM-3 printed-constraint census."""
from __future__ import annotations
import copy
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from anchor_census_check import check

ROOT = Path(__file__).resolve().parents[1]
spec = json.loads((ROOT / "inputs/anchor-pam3.json").read_text())
base = json.loads((ROOT / "results/anchor-pam3.json").read_text())
controls = []

def rejected(name: str, mutate) -> None:
    trial = copy.deepcopy(base)
    mutate(trial)
    try:
        check(spec, trial)
    except Exception as error:
        controls.append({"name": name, "passed": True, "rejection": type(error).__name__})
    else:
        controls.append({"name": name, "passed": False, "rejection": None})

rejected("understated-pairwise-count", lambda x: x.__setitem__("pairwise_valid_mappings", 95))
rejected("deleted-mapping", lambda x: x["records"].pop())
rejected("duplicate-mapping", lambda x: x["records"].__setitem__(1, copy.deepcopy(x["records"][0])))
rejected("wrong-omitted-word", lambda x: x["records"][0].__setitem__("omitted_codeword", "0000"))
rejected("understated-total-error", lambda x: x["records"][0].__setitem__("minimum_total_decoder_error", 1))
rejected("wrong-obstruction-row", lambda x: x["records"][0]["first_bound_one_obstruction"].__setitem__("received_word", "0000"))
rejected("deleted-core-source", lambda x: x["records"][0]["first_bound_one_obstruction"]["source_messages"].pop())
rejected("false-source-agreement", lambda x: x.__setitem__("count_agrees_with_source_text", True))
if len(controls) != 8 or not all(item["passed"] for item in controls):
    raise SystemExit("anchor census control failed")
out = ROOT / "results/anchor-pam3-controls.json"
out.write_text(json.dumps(controls, indent=2) + "\n")
print(json.dumps(controls, indent=2))
