"""Pure aggregation of retained coverage, proof, and execution counters.

This module performs no synthesis or proof search.  It reads completed result
records, separates logical coverage from retained proof objects and actual
algorithmic calls, and checks the arithmetic identities used by the manuscript.
"""
from __future__ import annotations

import json
from pathlib import Path


def aggregate(results: Path) -> dict:
    proof = json.loads((results / "proof-frontiers" / "summary.json").read_text())
    projection = json.loads((results / "semantic-projection-check.json").read_text())
    fixed = json.loads((results / "fixed-codebook" / "X01-check.json").read_text())
    anchor = json.loads((results / "anchor-pam3-check.json").read_text())
    encoding = json.loads((results / "encoding-properties.json").read_text())
    case_results = [
        json.loads((results / f"{prefix}{index:02d}.json").read_text())
        for prefix in "BT"
        for index in range(1, 9)
    ]

    lower = int(proof["lower_bound_proof_search_nodes"])
    satisfying = int(proof["satisfying_witness_search_nodes"])
    earlier_unsat = int(proof["earlier_unsat_search_nodes"])
    all_generation = int(proof["all_generation_search_nodes"])
    replay = int(proof["lower_bound_proof_replay_node_visits"])
    if all_generation != lower + satisfying + earlier_unsat:
        raise ValueError("DPLL generation-node partition does not sum")
    if replay != lower:
        raise ValueError("replay visits differ from final lower-bound search nodes")

    semantic_rows = sum(int(item["received_rows_checked"]) for item in projection["cases"])
    fixed_plane_checks = int(fixed["planes_checked"])
    fixed_cube_checks = int(fixed["cubes_checked"])
    fixed_pair_checks = int(fixed["packing_pairs_checked"])
    exact_plane_certificates = int(proof["encoder_plane_certificates"]) + int(proof["decoder_relation_certificates"])
    anchor_slots = int(anchor["logical_row_bound_slots"])
    anchor_calls = int(anchor["executed_row_output_calls"])
    encoding_assignments = int(encoding["cardinality"]["assignments"])
    encoding_bounds = int(encoding["relational"]["bounds"])
    correlated_checks = int(encoding["relational"]["correlated_forbidden_tuple_checks"])
    candidate_obligations = sum(int(item["candidate_source_received_obligations_covered"]) for item in case_results)

    # This is a logical coverage sum, not a count of Python calls and not a
    # compact proof-object byte/record count.  It retains the historical 99,897
    # total with a precise, non-overstated definition.
    checker_visible_logical_units = (
        replay
        + semantic_rows
        + fixed_plane_checks
        + fixed_cube_checks
        + fixed_pair_checks
        + exact_plane_certificates
        + anchor_slots
        + encoding_assignments
        + encoding_bounds
        + correlated_checks
    )

    return {
        "logical_coverage": {
            "checker_visible_logical_units": checker_visible_logical_units,
            "components": {
                "final_lower_bound_replay_visits": replay,
                "joint_semantic_received_rows": semantic_rows,
                "fixed_codebook_planes": fixed_plane_checks,
                "fixed_codebook_cubes": fixed_cube_checks,
                "fixed_codebook_packing_pairs": fixed_pair_checks,
                "exact_plane_certificates": exact_plane_certificates,
                "anchor_full_row_bound_slots": anchor_slots,
                "encoding_cardinality_assignments": encoding_assignments,
                "encoding_relation_bounds": encoding_bounds,
                "encoding_correlated_forbidden_tuple_checks": correlated_checks,
            },
            "joint_semantic_received_rows": semantic_rows,
            "anchor_full_row_bound_slots": anchor_slots,
            "candidate_source_received_obligations": candidate_obligations,
            "definition": (
                "The checker-visible total sums final lower-bound replay visits, semantic rows, "
                "fixed-codebook plane/cube/packing checks, exact plane certificates, the full A01 "
                "mapping-row-bound slot product, and small encoding-oracle slots. It is a coverage "
                "index, not an executed-call count."
            ),
        },
        "retained_proof": {
            "lower_bound_replay_node_visits": replay,
            "stored_tree_records": int(proof["stored_proof_tree_records"]),
            "exact_plane_certificates": exact_plane_certificates,
            "fixed_codebook_planes": fixed_plane_checks,
            "fixed_codebook_cubes": fixed_cube_checks,
            "fixed_codebook_packing_pairs": fixed_pair_checks,
        },
        "actual_execution": {
            "all_dpll_generation_search_nodes": all_generation,
            "final_lower_bound_generation_nodes": lower,
            "satisfying_witness_generation_nodes": satisfying,
            "earlier_unsat_generation_nodes": earlier_unsat,
            "lower_bound_replay_node_visits": replay,
            "anchor_row_output_calls": anchor_calls,
        },
        "identities": {
            "dpll_partition": [all_generation, lower, satisfying, earlier_unsat],
            "anchor_slots_vs_calls": [anchor_slots, anchor_calls],
        },
    }
