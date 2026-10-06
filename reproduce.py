"""One-worker bounded generation, independent replay, and durable resume.

Run from the artifact root. Every child has a 600-second deadline and a 3 GiB
address-space limit. A failed, timed-out, or source-mismatched invocation marks
the campaign incomplete. Bounded resume advances through a prefix of 81 unique
stages; it never counts repeated records as new completion.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import resource
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CHILD_ADDRESS_SPACE_BYTES = 3 * 1024**3
CHILD_TIMEOUT_SECONDS = 600
RESUME_STATE = "resume-state.json"


@dataclass(frozen=True)
class Stage:
    name: str
    command_args: tuple[str, ...]
    outputs: tuple[str, ...] = ()


def set_child_limits() -> None:
    """Apply the documented per-child address-space bound before exec."""
    resource.setrlimit(resource.RLIMIT_AS, (CHILD_ADDRESS_SPACE_BYTES, CHILD_ADDRESS_SPACE_BYTES))


def captured_text(value: str | bytes | None) -> str:
    """TimeoutExpired may carry bytes even when run() requested text=True."""
    if isinstance(value, bytes):
        return value.decode('utf-8', errors='replace')
    return value or ''


def write_json(path: Path, value: object) -> None:
    """Replace a JSON record only after the complete new record is written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        json.dump(value, handle, indent=2)
        handle.write("\n")
    temporary.replace(path)


def build_stages(cases: list[dict], fixed_cases: list[dict]) -> list[Stage]:
    stages: list[Stage] = []
    for spec in cases:
        case = spec["id"]
        stages.extend([
            Stage(f"generate-{case}", ("src/synthesis.py", "--case", case), (f"results/{case}.json", f"results/{case}-costs.json")),
            Stage(f"check-{case}", ("src/checker.py", "--case", case), (f"results/{case}-check.json",)),
        ])
    stages.extend([
        Stage("semantic-projection", ("src/semantic_projection.py",), ("results/semantic-projection.json",)),
        Stage("projection-check", ("src/projection_check.py",), ("results/semantic-projection-check.json",)),
        Stage("projection-controls", ("tests/projection_controls.py",), ("results/projection-controls.json",)),
    ])
    for spec in cases:
        case = spec["id"]
        stages.extend([
            Stage(f"proof-generate-{case}", ("src/frontier_proofs.py", "--case", case), (f"results/proof-frontiers/{case}.json",)),
            Stage(f"proof-check-{case}", ("src/frontier_proof_check.py", "--case", case), (f"results/proof-frontiers/{case}-check.json",)),
        ])
    stages.extend([
        Stage("proof-controls", ("tests/frontier_proof_controls.py",), ("results/proof-frontiers/controls.json",)),
        Stage("proof-summary", ("src/proof_summary.py",), ("results/proof-frontiers/summary.json",)),
    ])
    for spec in fixed_cases:
        case = spec["id"]
        stages.extend([
            Stage(f"fixed-generate-{case}", ("src/fixed_codebook_proof.py", "--case", case), (f"results/fixed-codebook/{case}.json",)),
            Stage(f"fixed-check-{case}", ("src/fixed_codebook_check.py", "--case", case), (f"results/fixed-codebook/{case}-check.json",)),
        ])
    stages.extend([
        Stage("fixed-controls", ("tests/fixed_codebook_controls.py",), ("results/fixed-codebook/controls.json",)),
        Stage("anchor-census", ("src/anchor_census.py",), ("results/anchor-pam3.json",)),
        Stage("anchor-census-check", ("src/anchor_census_check.py",), ("results/anchor-pam3-check.json",)),
        Stage("anchor-census-controls", ("tests/anchor_census_controls.py",), ("results/anchor-pam3-controls.json",)),
        Stage("encoding-properties", ("tests/encoding_properties.py",), ("results/encoding-properties.json",)),
        Stage("theory", ("src/theory_checks.py",), ("results/theory.json",)),
        Stage("controls", ("tests/controls.py",), ("results/controls.json",)),
        Stage("scalarization", ("src/baseline.py",), ("results/scalarization.json",)),
        Stage("metadata-integrity", ("tests/metadata_integrity.py",), ("results/metadata-integrity.json",)),
        Stage("orchestration-controls", ("tests/orchestration.py",)),
    ])
    if len(stages) != 81 or len({stage.name for stage in stages}) != 81:
        raise RuntimeError("The frozen campaign must contain exactly 81 unique stages")
    return stages


def execution_input_paths(root: Path) -> list[Path]:
    paths = [root / "reproduce.py", root / "literature-audit.csv", root / "external_resources.csv", root / "claim_evidence_ledger.csv"]
    for directory, pattern in (("inputs", "*.json"), ("src", "*.py"), ("tests", "*.py")):
        paths.extend(sorted((root / directory).glob(pattern)))
    return sorted(path for path in paths if path.is_file())


def execution_fingerprint(root: Path) -> str:
    digest = hashlib.sha256()
    for path in execution_input_paths(root):
        digest.update(str(path.relative_to(root)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def ordered_records(stages: list[Stage], records: dict[str, dict]) -> list[dict]:
    return [records[stage.name] for stage in stages if stage.name in records]


def load_records(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    records: dict[str, dict] = {}
    for record in json.loads(path.read_text()):
        name = record.get("stage")
        if not isinstance(name, str) or name in records:
            raise RuntimeError("commands.json contains a missing or duplicate stage record")
        records[name] = record
    return records


def valid_completed_prefix(root: Path, stages: list[Stage], records: dict[str, dict]) -> int:
    """Return the longest valid successful stage prefix.

    A missing output invalidates that stage and every later stage, preventing a
    stale checker or summary from being reused after an earlier result is lost.
    """
    prefix = 0
    for stage in stages:
        record = records.get(stage.name)
        if record is None or record.get("returncode") != 0:
            break
        if any(not (root / output).is_file() for output in stage.outputs):
            break
        prefix += 1
    return prefix


def initialize_progress(
    root: Path,
    results: Path,
    stages: list[Stage],
    *,
    resume: bool,
) -> tuple[dict[str, dict], int, int, str]:
    state_path = results / RESUME_STATE
    command_path = results / "commands.json"
    fingerprint = execution_fingerprint(root)
    if not resume:
        records: dict[str, dict] = {}
        if command_path.exists():
            command_path.unlink()
        state = {"execution_fingerprint": fingerprint, "invocation_count": 1, "completed_prefix": 0}
        write_json(state_path, state)
        return records, 0, 1, fingerprint

    if not state_path.exists():
        raise RuntimeError("No paused resume state exists; start with python reproduce.py --max-stages N")
    state = json.loads(state_path.read_text())
    if state.get("execution_fingerprint") != fingerprint:
        write_json(results / "campaign.json", {
            "complete_locked_case_replay": False,
            "status": "resume rejected because source or input content changed",
        })
        raise RuntimeError("Scientific source or input changed; start a fresh reproduction without --resume")
    records = load_records(command_path)
    prefix = valid_completed_prefix(root, stages, records)
    invocation_count = int(state.get("invocation_count", 1)) + 1
    write_json(state_path, {
        "execution_fingerprint": fingerprint,
        "invocation_count": invocation_count,
        "completed_prefix": prefix,
    })
    return records, prefix, invocation_count, fingerprint


def run_stage_prefix(
    *,
    root: Path,
    results: Path,
    stages: list[Stage],
    records: dict[str, dict],
    completed_prefix: int,
    invocation_count: int,
    stage_limit: int | None,
    env: dict[str, str],
    runner=subprocess.run,
) -> tuple[bool, int, int, dict[str, dict]]:
    """Run the next unfinished prefix; return (paused, prefix, executed, records)."""
    executed = 0
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    for index in range(completed_prefix, len(stages)):
        if stage_limit is not None and executed >= stage_limit:
            usage = resource.getrusage(resource.RUSAGE_CHILDREN)
            write_json(results / "campaign.json", {
                "complete_locked_case_replay": False,
                "status": "paused at durable stage boundary",
                "completed_stages": completed_prefix,
                "unique_command_records": len(records),
                "invocation_count": invocation_count,
                "executed_stages_this_invocation": executed,
                "child_cpu_seconds_this_invocation": usage.ru_utime + usage.ru_stime - before.ru_utime - before.ru_stime,
            })
            state = json.loads((results / RESUME_STATE).read_text())
            state["completed_prefix"] = completed_prefix
            write_json(results / RESUME_STATE, state)
            return True, completed_prefix, executed, records

        stage = stages[index]
        started = time.perf_counter()
        child_before = resource.getrusage(resource.RUSAGE_CHILDREN)
        try:
            process = runner(
                [sys.executable, *stage.command_args],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=CHILD_TIMEOUT_SECONDS,
                preexec_fn=set_child_limits,
            )
        except subprocess.TimeoutExpired as error:
            records[stage.name] = {
                "stage": stage.name,
                "command": ["python", *stage.command_args],
                "returncode": None,
                "status": "timeout",
                "wall_seconds": time.perf_counter() - started,
                "stdout": captured_text(getattr(error, "stdout", None)),
                "stderr": captured_text(getattr(error, "stderr", None)),
            }
            write_json(results / "commands.json", ordered_records(stages, records))
            write_json(results / "campaign.json", {
                "complete_locked_case_replay": False,
                "status": "timeout",
                "failed_stage": stage.name,
                "maximum_child_deadline_s": CHILD_TIMEOUT_SECONDS,
                "completed_stages": completed_prefix,
                "unique_command_records": len(records),
                "invocation_count": invocation_count,
            })
            raise

        child_after = resource.getrusage(resource.RUSAGE_CHILDREN)
        record = {
            "stage": stage.name,
            "child_cpu_seconds": child_after.ru_utime + child_after.ru_stime - child_before.ru_utime - child_before.ru_stime,
            "command": ["python", *stage.command_args],
            "returncode": process.returncode,
            "wall_seconds": time.perf_counter() - started,
            "child_peak_rss_kib_this_invocation": child_after.ru_maxrss,
            "stdout": process.stdout,
            "stderr": process.stderr,
        }
        records[stage.name] = record
        write_json(results / "commands.json", ordered_records(stages, records))
        print(stage.name, process.returncode, round(record["wall_seconds"], 3), flush=True)
        if process.returncode:
            write_json(results / "campaign.json", {
                "complete_locked_case_replay": False,
                "status": "failed",
                "failed_stage": stage.name,
                "returncode": process.returncode,
                "completed_stages": completed_prefix,
                "unique_command_records": len(records),
                "invocation_count": invocation_count,
            })
            raise RuntimeError(f"{stage.name} failed: {process.stderr}")
        if any(not (root / output).is_file() for output in stage.outputs):
            write_json(results / "campaign.json", {
                "complete_locked_case_replay": False,
                "status": "failed: successful child omitted required output",
                "failed_stage": stage.name,
                "completed_stages": completed_prefix,
                "unique_command_records": len(records),
                "invocation_count": invocation_count,
            })
            raise RuntimeError(f"{stage.name} omitted a required output")
        completed_prefix += 1
        executed += 1
        state = json.loads((results / RESUME_STATE).read_text())
        state["completed_prefix"] = completed_prefix
        write_json(results / RESUME_STATE, state)
        usage = resource.getrusage(resource.RUSAGE_CHILDREN)
        if usage.ru_utime + usage.ru_stime - before.ru_utime - before.ru_stime > 6 * 3600:
            raise RuntimeError("Reserved repair/reproduction CPU budget reached")

    return False, completed_prefix, executed, records


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--resume', action='store_true', help='Continue the unchanged paused stage prefix.')
    parser.add_argument('--max-stages', type=int, help='Run at most this many unfinished stages, then pause without a completion claim.')
    args = parser.parse_args()
    if args.max_stages is not None and args.max_stages < 1:
        parser.error('--max-stages must be positive')

    os.chdir(ROOT)
    env = os.environ.copy()
    env.update(OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', PYTHONDONTWRITEBYTECODE='1')
    cases = json.loads(Path('inputs/cases.json').read_text())
    fixed_cases = json.loads(Path('inputs/fixed-codebooks.json').read_text())
    json.loads(Path('inputs/anchor-pam3.json').read_text())
    selection = json.loads(Path('inputs/selection.json').read_text())
    estimate = 2 * selection['candidate_count_per_pass']
    if estimate + selection['pilot_candidate_count'] > 300000:
        raise RuntimeError('Aggregate planned candidate cap exceeded')

    results = Path('results')
    results.mkdir(exist_ok=True)
    stages = build_stages(cases, fixed_cases)
    records, initial_prefix, invocation_count, _ = initialize_progress(ROOT, results, stages, resume=args.resume)
    wall = time.perf_counter()
    parent_cpu_start = time.process_time()
    child_before_invocation = resource.getrusage(resource.RUSAGE_CHILDREN)
    write_json(results / 'campaign.json', {
        'complete_locked_case_replay': False,
        'status': 'running; no current completion claim',
        'resume': args.resume,
        'completed_stages': initial_prefix,
        'unique_command_records': len(records),
        'invocation_count': invocation_count,
    })

    paused, completed_prefix, executed_this_invocation, records = run_stage_prefix(
        root=ROOT,
        results=results,
        stages=stages,
        records=records,
        completed_prefix=initial_prefix,
        invocation_count=invocation_count,
        stage_limit=args.max_stages,
        env=env,
    )
    if paused:
        print('Paused; repeat the documented --resume command with unchanged sources to advance.', flush=True)
        return
    if completed_prefix != len(stages):
        raise RuntimeError('Stage queue ended without complete unique-stage coverage')

    summaries = [json.loads((results / f"{spec['id']}.json").read_text()) for spec in cases]
    checks = [json.loads((results / f"{spec['id']}-check.json").read_text()) for spec in cases]
    with (results / 'summary.csv').open('w', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(['case', 'q', 'n', 'payload_bits', 'designs', 'frontier', 'pair_only_frontier', 'generation_cpu_s', 'check_cpu_s', 'max_peak_rss_kib'])
        for result, check in zip(summaries, checks):
            spec = result['case']
            frontier = ';'.join(f"({point['error']},{point['gates']})" for point in result['frontier'])
            pair_frontier = ';'.join(f"({point['pair_error_bound']},{point['gates']})" for point in result['pair_only_frontier'])
            writer.writerow([spec['id'], spec['q'], spec['n'], spec['k'], result['candidate_designs'], frontier, pair_frontier, result['cpu_seconds'], check['cpu_seconds'], max(result['peak_rss_kib'], check['peak_rss_kib'])])

    controls = json.loads((results / 'controls.json').read_text())
    if len(controls) != 8 or not all(item['passed'] for item in controls):
        raise RuntimeError('A required control is missing or failed')
    theory = json.loads((results / 'theory.json').read_text())
    if not theory.get('ternary_cross_noncontractive'):
        raise RuntimeError('Explicit obstruction checks are missing')
    scalar = json.loads((results / 'scalarization.json').read_text())
    if len(scalar['cases']) != len(cases):
        raise RuntimeError('Scalarization audit is incomplete')
    projection = json.loads((results / 'semantic-projection-check.json').read_text())
    if not projection.get('accepted') or len(projection['cases']) != len(cases):
        raise RuntimeError('Semantic projection check incomplete')
    projection_controls = json.loads((results / 'projection-controls.json').read_text())
    if len(projection_controls) != 6 or not all(item['passed'] for item in projection_controls):
        raise RuntimeError('Semantic control missing or failed')
    proof_summary = json.loads((results / 'proof-frontiers' / 'summary.json').read_text())
    if not proof_summary.get('accepted') or proof_summary.get('cases') != len(cases):
        raise RuntimeError('Proof-carrying frontier replay incomplete')
    proof_controls = json.loads((results / 'proof-frontiers' / 'controls.json').read_text())
    if proof_controls.get('passed') != 8:
        raise RuntimeError('Proof-certificate controls incomplete')
    fixed_results = [json.loads((results / 'fixed-codebook' / f"{spec['id']}.json").read_text()) for spec in fixed_cases]
    fixed_checks = [json.loads((results / 'fixed-codebook' / f"{spec['id']}-check.json").read_text()) for spec in fixed_cases]
    if not all(item.get('accepted') for item in fixed_checks):
        raise RuntimeError('Fixed-codebook replay incomplete')
    fixed_controls = json.loads((results / 'fixed-codebook' / 'controls.json').read_text())
    if fixed_controls.get('passed') != 9:
        raise RuntimeError('Fixed-codebook controls incomplete')
    anchor = json.loads((results / 'anchor-pam3.json').read_text())
    anchor_check = json.loads((results / 'anchor-pam3-check.json').read_text())
    anchor_controls = json.loads((results / 'anchor-pam3-controls.json').read_text())
    encoding_properties = json.loads((results / 'encoding-properties.json').read_text())
    if not anchor_check.get('accepted') or anchor_check.get('pairwise_valid_mappings_checked') != anchor.get('pairwise_valid_mappings'):
        raise RuntimeError('Anchor printed-constraint census replay incomplete')
    if len(anchor_controls) != 8 or not all(item.get('passed') for item in anchor_controls):
        raise RuntimeError('Anchor census mutation controls incomplete')
    if not encoding_properties.get('accepted'):
        raise RuntimeError('Small-oracle encoding property checks incomplete')
    metadata = json.loads((results / 'metadata-integrity.json').read_text())
    if not metadata.get('accepted') or metadata.get('scholarly_references_checked', 0) < 55:
        raise RuntimeError('Metadata and literature integrity audit incomplete')

    sys.path.insert(0, str(ROOT / 'src'))
    from evidence_counts import aggregate as aggregate_evidence  # pylint: disable=import-outside-toplevel
    evidence = aggregate_evidence(results)
    write_json(results / 'evidence-counts.json', evidence)
    if evidence['logical_coverage']['checker_visible_logical_units'] > 150000:
        raise RuntimeError('Checker-visible logical coverage ceiling exceeded')

    after_invocation = resource.getrusage(resource.RUSAGE_CHILDREN)
    successful_records = [records[stage.name] for stage in stages if records[stage.name].get('returncode') == 0]
    report = {
        'complete_locked_case_replay': all(check['accepted'] for check in checks),
        'cases': len(cases),
        'generation_designs': sum(result['candidate_designs'] for result in summaries),
        'checker_design_visits': sum(check['candidate_designs_replayed'] for check in checks),
        'plane_cost_certificates_checked': sum(check['plane_minimality_certificates'] for check in checks),
        'frontier_points': sum(len(result['frontier']) for result in summaries),
        'semantic_projection_accepted': projection['accepted'],
        'encoder_bound_profiles_checked': projection['profiles_checked'],
        'encoders_checked_in_projection': projection['encoders_checked'],
        'semantic_controls_passed': len(projection_controls),
        'proof_frontier_cases': proof_summary['cases'],
        'proof_encoder_coverage': proof_summary['encoders_covered'],
        'proof_plane_certificates': proof_summary['encoder_plane_certificates'] + proof_summary['decoder_relation_certificates'],
        'lower_bound_proof_search_nodes': proof_summary['lower_bound_proof_search_nodes'],
        'satisfying_witness_search_nodes': proof_summary['satisfying_witness_search_nodes'],
        'earlier_unsat_search_nodes': proof_summary['earlier_unsat_search_nodes'],
        'all_dpll_generation_search_nodes': proof_summary['all_generation_search_nodes'],
        'lower_bound_proof_replay_node_visits': proof_summary['lower_bound_proof_replay_node_visits'],
        'stored_proof_tree_records': proof_summary['stored_proof_tree_records'],
        'proof_certificate_bytes': proof_summary['certificate_bytes'],
        'proof_mutation_controls_passed': proof_summary['mutation_controls_passed'],
        'semantic_received_rows_checked': evidence['logical_coverage']['joint_semantic_received_rows'],
        'checker_visible_logical_coverage_units': evidence['logical_coverage']['checker_visible_logical_units'],
        'candidate_source_received_obligations_covered': evidence['logical_coverage']['candidate_source_received_obligations'],
        'fixed_codebook_cases': len(fixed_cases),
        'fixed_codebook_frontier_points': sum(len(item['frontier']) for item in fixed_results),
        'fixed_codebook_decoder_completion_exponents': [item['decoder_completion_count_power_of_two'] for item in fixed_results],
        'fixed_codebook_planes_checked': sum(item['planes_checked'] for item in fixed_checks),
        'fixed_codebook_plane_domain_bindings_checked': sum(item['plane_domain_bindings_checked'] for item in fixed_checks),
        'fixed_codebook_cubes_checked': sum(item['cubes_checked'] for item in fixed_checks),
        'fixed_codebook_packing_pairs_checked': sum(item['packing_pairs_checked'] for item in fixed_checks),
        'fixed_codebook_decoder_semantic_rows_rechecked': sum(item['decoder_semantic_rows_rechecked'] for item in fixed_checks),
        'fixed_codebook_decoder_inverse_rows_rechecked': sum(item['decoder_inverse_rows_rechecked'] for item in fixed_checks),
        'fixed_codebook_decoder_source_received_obligations_rechecked': sum(item['decoder_source_received_obligations_rechecked'] for item in fixed_checks),
        'fixed_codebook_mutation_controls_passed': fixed_controls['passed'],
        'anchor_pairwise_valid_mappings': anchor['pairwise_valid_mappings'],
        'anchor_independent_pairwise_mappings_checked': anchor_check['pairwise_valid_mappings_checked'],
        'anchor_total_decoder_error_two_mappings': anchor_check['exact_total_error_two_mappings'],
        'anchor_source_reported_pairwise_count': anchor_check['source_reported_count'],
        'anchor_printed_rule_count': anchor_check['printed_rule_count'],
        'anchor_logical_row_bound_slots': anchor_check['logical_row_bound_slots'],
        'anchor_executed_row_output_calls': anchor_check['executed_row_output_calls'],
        'anchor_count_discrepancy_resolved': False,
        'anchor_mutation_controls_passed': len(anchor_controls),
        'encoding_property_assignments_checked': encoding_properties['cardinality']['assignments'],
        'encoding_relation_bounds_checked': encoding_properties['relational']['bounds'],
        'metadata_integrity_accepted': metadata['accepted'],
        'scholarly_references_checked': metadata['scholarly_references_checked'],
        'unique_dois_checked': metadata['unique_dois_checked'],
        'external_resources_checked': metadata['external_resources_checked'],
        'claim_records_checked': metadata['claim_records_checked'],
        'worker_processes_at_a_time': 1,
        'maximum_child_deadline_s': CHILD_TIMEOUT_SECONDS,
        'child_address_space_limit_bytes': CHILD_ADDRESS_SPACE_BYTES,
        'child_cpu_seconds_this_invocation': after_invocation.ru_utime + after_invocation.ru_stime - child_before_invocation.ru_utime - child_before_invocation.ru_stime,
        'recorded_completed_stage_child_cpu_seconds': sum(record.get('child_cpu_seconds', 0.0) for record in successful_records),
        'measured_generation_and_checker_cpu_seconds': sum(result['cpu_seconds'] for result in summaries) + sum(check['cpu_seconds'] for check in checks),
        'recorded_completed_stage_wall_seconds': sum(record['wall_seconds'] for record in successful_records),
        'cpu_accounting_note': (
            'Per-case generation/checker CPU excludes interpreter startup. The current-invocation child CPU covers only the last invocation; '
            'recorded completed-stage CPU and wall totals sum the 81 unique successful command records retained across all bounded invocations.'
        ),
        'bounded_invocations': invocation_count,
        'resume_invocations': max(invocation_count - 1, 0),
        'final_invocation_resumed_prefix': initial_prefix,
        'final_invocation_executed_stages': executed_this_invocation,
        'completed_stages': completed_prefix,
        'unique_command_records': len(records),
        'parent_cpu_seconds_this_invocation': time.process_time() - parent_cpu_start,
        'wall_seconds_this_invocation': time.perf_counter() - wall,
        'peak_child_rss_kib': max(record.get('child_peak_rss_kib_this_invocation', 0) for record in successful_records),
        'pilot_candidate_visits': selection['pilot_candidate_count'],
        'design_visits_for_this_reproduction_plus_original_pilot': estimate + selection['pilot_candidate_count'] + anchor['pairwise_valid_mappings'],
        'proof_format': (
            'Semantic row cores; deterministic relational-SOP CNF with independently replayed unit-conflict DPLL lower-bound trees for the '
            'locked joint cases; forced-cell packing proofs checked on spec-bound domains for the fixed-codebook case; and an independently '
            'replayed external printed-constraint census.'
        ),
        'research_gate': (
            'Implemented and independently replayed code-specific finite frontier certificates for the frozen grammar, a spec-bound '
            '2^72-completion fixed-codebook case, and a complete external PAM-3 printed-constraint census. The source-count discrepancy '
            'is disclosed rather than resolved; no generic MO-MaxSAT, physical-design, or asymptotic claim.'
        ),
    }
    if len(records) != len(stages):
        raise RuntimeError('Final commands.json does not contain exactly one record per stage')
    write_json(results / 'campaign.json', report)
    state_path = results / RESUME_STATE
    if state_path.exists():
        state_path.unlink()
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
