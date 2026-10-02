"""Export manuscript tables and plots from retained checked results only."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def export(results: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    figures = output / "figures"
    figures.mkdir(exist_ok=True)

    frontier_rows = []
    specification_rows = []
    for prefix in "BT":
        for index in range(1, 9):
            case = f"{prefix}{index:02d}"
            data = json.loads((results / f"{case}.json").read_text())
            check = json.loads((results / f"{case}-check.json").read_text())
            if not check["accepted"]:
                raise ValueError(f"{case} has no accepted replay")
            expected = [[point["error"], point["gates"]] for point in data["frontier"]]
            if check["frontier"] != expected:
                raise ValueError(f"{case} frontier/check disagreement")
            frontier = ", ".join(f"({point['error']},{point['gates']})" for point in data["frontier"])
            frontier_rows.append(
                f"{case} & {data['candidate_designs']:,} & ${frontier}$ & {check['plane_minimality_certificates']:,} \\\\"
            )
            spec = data["case"]
            allowed = ",".join(spec["allowed"])
            specification_rows.append(
                f"{spec['id']} & {spec['q']} & {spec['n']} & {spec['k']} & $\\{{{allowed}\\}}$ \\\\"
            )
    (output / "frontier-rows.tex").write_text(
        "\\newcommand{\\FrontierRows}{%\n" + "\n".join(frontier_rows) + "\n}\n"
    )
    (output / "specification-rows.tex").write_text(
        "\\newcommand{\\SpecificationRows}{%\n" + "\n".join(specification_rows) + "\n}\n"
    )

    for case in ("B05", "B06"):
        data = json.loads((results / f"{case}.json").read_text())
        (figures / f"{case}.csv").write_text(
            "error,gates\n" + "".join(f"{point['error']},{point['gates']}\n" for point in data["frontier"])
        )

    projection = json.loads((results / "semantic-projection-check.json").read_text())
    if not projection["accepted"] or len(projection["cases"]) != 16:
        raise ValueError("No complete semantic projection check")
    projection_rows = []
    for case in projection["cases"]:
        values = [f"{value:,}" for value in case["decoder_count_by_bound"]]
        values += ["---"] * (3 - len(values))
        projection_rows.append(
            case["case"]
            + " & "
            + " & ".join(values)
            + f" & {sum(case['infeasible_encoders_by_bound'])}"
            + r"\\"
        )
    (output / "projection-rows.tex").write_text(
        "\\newcommand{\\ProjectionRows}{%\n" + "\n".join(projection_rows) + "\n}\n"
    )

    proof_summary = json.loads((results / "proof-frontiers" / "summary.json").read_text())
    if not proof_summary["accepted"] or proof_summary["cases"] != 16:
        raise ValueError("No accepted proof-frontier summary")
    proof_rows = []
    for item in proof_summary["per_case"]:
        check = json.loads((results / "proof-frontiers" / f"{item['case']}-check.json").read_text())
        if not check["accepted"]:
            raise ValueError(f"{item['case']} proof check is not accepted")
        proof_rows.append(
            f"{item['case']} & {item['encoders']} & {check['semantic_rejections']} & "
            f"{item['encoder_planes'] + item['decoder_relations']} & {item['lower_bound_replay_nodes']:,} \\\\"
        )
    (output / "proof-rows.tex").write_text(
        "\\newcommand{\\ProofRows}{%\n" + "\n".join(proof_rows) + "\n}\n"
    )

    fixed = json.loads((results / "fixed-codebook" / "X01.json").read_text())
    fixed_check = json.loads((results / "fixed-codebook" / "X01-check.json").read_text())
    if not fixed_check["accepted"]:
        raise ValueError("X01 fixed-codebook proof is not accepted")
    eproducts = fixed["encoder_plane"]["minimum_products"]
    bound_by_error = {item["error_bound"]: item for item in fixed["bounds"] if "decoder_plane" in item}
    frontier = ", ".join(f"({p['error_bound']},{p['gates']})" for p in fixed["frontier"])
    fixed_row = (
        f"X01 & 2 & 5 & 3 & $2^{{{fixed['decoder_completion_count_power_of_two']}}}$ & "
        f"{eproducts}/{bound_by_error[1]['decoder_plane']['minimum_products']}/{bound_by_error[2]['decoder_plane']['minimum_products']} & "
        f"${frontier}$ \\\\"
    )
    (output / "fixed-codebook-row.tex").write_text(
        "\\newcommand{\\FixedCodebookRow}{%\n" + fixed_row + "\n}\n"
    )


    # Paired binary/ternary rows for compact two-column manuscript tables.
    proof_by_case = {item["case"]: item for item in proof_summary["per_case"]}
    paired_specs = []
    paired_eval = []
    for index in range(1, 9):
        left = f"B{index:02d}"
        right = f"T{index:02d}"
        ldata = json.loads((results / f"{left}.json").read_text())
        rdata = json.loads((results / f"{right}.json").read_text())
        ls, rs = ldata["case"], rdata["case"]
        lallowed = ",".join(ls["allowed"])
        rallowed = ",".join(rs["allowed"])
        paired_specs.append(
            f"{left} & {ls['q']} & {ls['n']} & {ls['k']} & $\\{{{lallowed}\\}}$ & "
            f"{right} & {rs['q']} & {rs['n']} & {rs['k']} & $\\{{{rallowed}\\}}$ " + r"\\"
        )
        lf = ",".join(f"({x['error']},{x['gates']})" for x in ldata["frontier"])
        rf = ",".join(f"({x['error']},{x['gates']})" for x in rdata["frontier"])
        paired_eval.append(
            f"{left} & {ldata['candidate_designs']:,} & ${lf}$ & {proof_by_case[left]['lower_bound_replay_nodes']:,} & "
            f"{right} & {rdata['candidate_designs']:,} & ${rf}$ & {proof_by_case[right]['lower_bound_replay_nodes']:,} " + r"\\"
        )
    (output / "paired-specification-rows.tex").write_text(
        "\\newcommand{\\PairedSpecificationRows}{%\n" + "\n".join(paired_specs) + "\n}\n"
    )
    (output / "paired-evaluation-rows.tex").write_text(
        "\\newcommand{\\PairedEvaluationRows}{%\n" + "\n".join(paired_eval) + "\n}\n"
    )

    campaign = json.loads((results / "campaign.json").read_text())
    obstruction_totals = {}
    for item in projection["cases"]:
        for kind, value in item["obstruction_kinds"].items():
            obstruction_totals[kind] = obstruction_totals.get(kind, 0) + value
    macros = {
        "ProofEncoders": proof_summary["encoders_covered"],
        "ProofPlanes": proof_summary["encoder_plane_certificates"] + proof_summary["decoder_relation_certificates"],
        "SemanticRejects": proof_summary["semantic_infeasible_profiles"],
        "ProofNodes": proof_summary["lower_bound_proof_replay_node_visits"],
        "ProofGenerationNodes": proof_summary["all_generation_search_nodes"],
        "ProofWitnessNodes": proof_summary["satisfying_witness_search_nodes"],
        "ProofEarlierUnsatNodes": proof_summary["earlier_unsat_search_nodes"],
        "ProofRecords": proof_summary["stored_proof_tree_records"],
        "ProofGenerationCPU": f"{proof_summary['generation_cpu_seconds']:.3f}",
        "ProofCheckingCPU": f"{proof_summary['checking_cpu_seconds']:.3f}",
        "GenerationDesigns": campaign["generation_designs"],
        "CheckerDesignVisits": campaign["checker_design_visits"],
        "PlaneCostCertificates": campaign["plane_cost_certificates_checked"],
        "FrontierPoints": campaign["frontier_points"],
        "ProjectionProfiles": campaign["encoder_bound_profiles_checked"],
        "SemanticRows": campaign["semantic_received_rows_checked"],
        "SemanticChannelComparisons": sum(item["channel_distance_comparisons"] for item in projection["cases"]),
        "PinConflicts": obstruction_totals.get("pin", 0),
        "TwoSourceIntersections": obstruction_totals.get("intersection_2", 0),
        "FourSourceIntersections": obstruction_totals.get("intersection_4", 0),
        "CampaignStages": campaign["completed_stages"],
        "CampaignStageWall": f"{campaign['recorded_completed_stage_wall_seconds']:.3f}",
        "PeakChildRSSKiB": campaign["peak_child_rss_kib"],
        "MeasuredGenerationCheckerCPU": f"{campaign['measured_generation_and_checker_cpu_seconds']:.3f}",
        "LogicalCoverageUnits": campaign["checker_visible_logical_coverage_units"],
        "CandidateObligations": campaign["candidate_source_received_obligations_covered"],
        "CandidateVisitAccount": campaign["design_visits_for_this_reproduction_plus_original_pilot"],
        "FixedExponent": fixed["decoder_completion_count_power_of_two"],
        "FixedPlanes": fixed_check["planes_checked"],
        "FixedCubes": fixed_check["cubes_checked"],
        "FixedPackingPairs": fixed_check["packing_pairs_checked"],
        "FixedDomainBindings": fixed_check["plane_domain_bindings_checked"],
        "FixedSemanticRows": fixed_check["decoder_semantic_rows_rechecked"],
        "FixedInverseRows": fixed_check["decoder_inverse_rows_rechecked"],
        "FixedControls": campaign["fixed_codebook_mutation_controls_passed"],
        "AuditedReferences": campaign["scholarly_references_checked"],
        "AnchorMappings": campaign["anchor_pairwise_valid_mappings"],
        "AnchorSourceCount": campaign["anchor_source_reported_pairwise_count"],
        "AnchorLogicalSlots": campaign["anchor_logical_row_bound_slots"],
        "AnchorExecutedCalls": campaign["anchor_executed_row_output_calls"],
        "BoundedInvocations": campaign["bounded_invocations"],
        "ResumeInvocations": campaign["resume_invocations"],
        "FinalResumedPrefix": campaign["final_invocation_resumed_prefix"],
        "FinalInvocationStages": campaign["final_invocation_executed_stages"],
        "UniqueCommandRecords": campaign["unique_command_records"],
        "EncodingAssignments": campaign["encoding_property_assignments_checked"],
        "EncodingRelationBounds": campaign["encoding_relation_bounds_checked"],
    }
    lines = [f"\\newcommand{{\\{name}}}{{{value:,}}}" if isinstance(value, int) else f"\\newcommand{{\\{name}}}{{{value}}}" for name, value in macros.items()]
    (output / "result-macros.tex").write_text("\n".join(lines) + "\n")
    print("Exported seven table-macro files, one result-macro file, and two frontier coordinate files.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, default=Path("results"))
    parser.add_argument("--output-dir", type=Path, default=Path("results/presentation"))
    args = parser.parse_args()
    export(args.results, args.output_dir)
