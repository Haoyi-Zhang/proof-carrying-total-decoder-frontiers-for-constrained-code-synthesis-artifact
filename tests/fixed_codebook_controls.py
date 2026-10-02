"""Mutation controls for the fixed-codebook packing checker."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from fixed_codebook_check import check_certificate, eval_terms, raw, wire_width, words  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
spec = json.loads((ROOT / "inputs" / "fixed-codebooks.json").read_text())[0]
base = json.loads((ROOT / "results" / "fixed-codebook" / "X01.json").read_text())
PSEUDO_DOMAIN_WITNESS: dict[str, object] = {}


def rejected(name: str, mutate, expected: str | None = None) -> dict:
    value = copy.deepcopy(base)
    mutate(value)
    try:
        check_certificate(spec, value)
    except Exception as error:
        message = str(error)
        if expected is not None and expected not in message:
            return {"name": name, "passed": False, "rejection": message, "expected_rejection": expected}
        return {"name": name, "passed": True, "rejection": message}
    return {"name": name, "passed": False, "rejection": "mutation accepted"}


def pseudo_domain_projection_collapse(value: dict) -> None:
    """Reproduce the pre-fix domain-confusion attack exactly.

    The forged domain is the first legal output value at each row, so the three
    message bits become trivial input projections.  On that pseudo-domain the
    forged three-product table passes the old local relation/packing checks, but
    on the true five-bit received-word domain it decodes codeword 00100 as 100
    instead of its pinned message 000.
    """
    bound_one = value["bounds"][1]
    plane = bound_one["decoder_plane"]
    plane["domain"] = [row[0] for row in plane["legal_outputs"]]
    plane["terms"] = [
        {"cube": "**1**", "outputs": 4},
        {"cube": "***1*", "outputs": 2},
        {"cube": "****1", "outputs": 1},
    ]
    plane["minimum_products"] = 3
    plane["connections"] = 3
    plane["packing"] = plane["packing"][:3]
    bound_one["gates"] = 18
    bound_one["connections"] = 13
    value["best_cost_by_error_bound"] = [None, 18, 18, 18]
    value["frontier"] = [{"error_bound": 1, "gates": 18, "connections": 13}]

    # Verify both halves of the regression witness before asking the repaired
    # checker to reject it: the three projections are legal on the forged
    # pseudo-domain, but on the true received-word domain codeword 00100 is
    # decoded as 100 rather than its inverse-pinned message 000.
    pseudo_domain = tuple(plane["domain"])
    legal = tuple(tuple(row) for row in plane["legal_outputs"])
    pseudo_table = eval_terms(pseudo_domain, plane["width"], plane["outputs"], plane["terms"])
    assert all(pseudo_table[row] in legal[row] for row in range(len(legal)))
    channel = words(spec["q"], spec["n"])
    true_domain = tuple(raw(word, spec["q"]) for word in channel)
    true_table = eval_terms(true_domain, wire_width(spec), spec["k"], plane["terms"])
    true_row = channel.index(tuple(int(bit) for bit in "00100"))
    assert true_table[true_row] == 0b100 and true_table[true_row] != 0b000
    PSEUDO_DOMAIN_WITNESS.update({
        "pseudo_domain_rows_locally_legal": len(legal),
        "true_codeword": "00100",
        "required_message": "000",
        "forged_output": "100",
    })


pseudo_domain_control = rejected(
    "pseudo-domain-projection-collapse",
    pseudo_domain_projection_collapse,
    "decoder plane at error bound 1 domain mismatch",
)
pseudo_domain_control["static_witness"] = PSEUDO_DOMAIN_WITNESS

controls = [
    pseudo_domain_control,
    rejected("drop-packing-cell", lambda x: x["bounds"][1]["decoder_plane"]["packing"].pop()),
    rejected("duplicate-packing-cell", lambda x: x["bounds"][1]["decoder_plane"]["packing"].append(x["bounds"][1]["decoder_plane"]["packing"][0])),
    rejected("mutate-circuit-cube", lambda x: x["bounds"][1]["decoder_plane"]["terms"][0].update(cube="*****")),
    rejected("zero-output-mask", lambda x: x["encoder_plane"]["terms"][0].update(outputs=0)),
    rejected("drop-frontier-point", lambda x: x["frontier"].pop()),
    rejected("alter-encoder-row", lambda x: x["encoder_rows"].__setitem__(0, x["encoder_rows"][1])),
    rejected("understate-minimum", lambda x: x["bounds"][1]["decoder_plane"].update(minimum_products=4)),
    rejected("alter-forced-zero-set", lambda x: x["bounds"][2]["decoder_plane"]["forced_zero_cells"].pop()),
]

if not all(item["passed"] for item in controls):
    raise SystemExit("a fixed-codebook mutation was accepted")
out = {"passed": len(controls), "controls": controls}
path = ROOT / "results" / "fixed-codebook" / "controls.json"
path.write_text(json.dumps(out, indent=2) + "\n")
print(json.dumps(out, indent=2))
