"""Aggregate independently checked proof-frontier results into one compact report."""
from __future__ import annotations
import argparse
import json
import resource
import time
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--inputs', type=Path, default=Path('inputs/cases.json'))
    parser.add_argument('--results', type=Path, default=Path('results'))
    parser.add_argument('--proof-dir', type=Path, default=Path('results/proof-frontiers'))
    args = parser.parse_args()
    start = time.process_time()
    specs = json.loads(args.inputs.read_text())
    certs = []
    checks = []
    for spec in specs:
        case = spec['id']
        cert = json.loads((args.proof_dir / f'{case}.json').read_text())
        check = json.loads((args.proof_dir / f'{case}-check.json').read_text())
        if not check.get('accepted'):
            raise RuntimeError(f'{case} proof certificate not accepted')
        certs.append(cert)
        checks.append(check)
    controls = json.loads((args.proof_dir / 'controls.json').read_text())
    if controls.get('passed') != 8 or not all(item.get('passed') for item in controls['controls']):
        raise RuntimeError('proof controls incomplete')

    lower_nodes = sum(item['counts']['lower_bound_proof_search_nodes'] for item in certs)
    sat_nodes = sum(item['counts']['satisfying_witness_search_nodes'] for item in certs)
    earlier_unsat_nodes = sum(item['counts']['earlier_unsat_search_nodes'] for item in certs)
    all_generation_nodes = sum(item['counts']['all_generation_search_nodes'] for item in certs)
    replay_nodes = sum(item['proof_node_visits'] for item in checks)
    if all_generation_nodes != lower_nodes + sat_nodes + earlier_unsat_nodes:
        raise RuntimeError('aggregate DPLL generation-node accounting mismatch')
    if replay_nodes != lower_nodes:
        raise RuntimeError('checker replay count differs from final lower-bound proof search')

    per_case = []
    for cert, check in zip(certs, checks):
        counts = cert['counts']
        if counts['all_generation_search_nodes'] != (
            counts['lower_bound_proof_search_nodes']
            + counts['satisfying_witness_search_nodes']
            + counts['earlier_unsat_search_nodes']
        ):
            raise RuntimeError(f"{cert['case']['id']} DPLL accounting mismatch")
        per_case.append({
            'case': cert['case']['id'],
            'encoders': counts['encoders'],
            'encoder_planes': counts['encoder_plane_certificates'],
            'decoder_relations': counts['decoder_relation_certificates'],
            'lower_bound_replay_nodes': counts['lower_bound_proof_search_nodes'],
            'satisfying_witness_search_nodes': counts['satisfying_witness_search_nodes'],
            'earlier_unsat_search_nodes': counts['earlier_unsat_search_nodes'],
            'all_generation_search_nodes': counts['all_generation_search_nodes'],
            'proof_records': counts['stored_proof_tree_records'],
            'frontier': [(point['error_bound'], point['gates']) for point in cert['frontier']],
            'generation_cpu_seconds': cert['cpu_seconds'],
            'checking_cpu_seconds': check['cpu_seconds'],
        })

    summary = {
        'accepted': True,
        'cases': len(specs),
        'encoders_covered': sum(item['counts']['encoders'] for item in certs),
        'encoder_plane_certificates': sum(item['counts']['encoder_plane_certificates'] for item in certs),
        'decoder_relation_certificates': sum(item['counts']['decoder_relation_certificates'] for item in certs),
        'semantic_infeasible_profiles': sum(item['semantic_rejections'] for item in checks),
        'feasible_encoder_bound_relations': sum(item['relation_references'] for item in checks),
        'lower_bound_proof_search_nodes': lower_nodes,
        'satisfying_witness_search_nodes': sat_nodes,
        'earlier_unsat_search_nodes': earlier_unsat_nodes,
        'all_generation_search_nodes': all_generation_nodes,
        'stored_proof_tree_records': sum(item['counts']['stored_proof_tree_records'] for item in certs),
        'lower_bound_proof_replay_node_visits': replay_nodes,
        'proof_checker_conflict_leaf_visits': sum(item['conflict_leaf_visits'] for item in checks),
        'frontier_points': sum(len(item['frontier']) for item in certs),
        'generation_cpu_seconds': sum(item['cpu_seconds'] for item in certs),
        'generation_wall_seconds_sum': sum(item['wall_seconds'] for item in certs),
        'checking_cpu_seconds': sum(item['cpu_seconds'] for item in checks),
        'checking_wall_seconds_sum': sum(item['wall_seconds'] for item in checks),
        'certificate_bytes': sum((args.proof_dir / f"{spec['id']}.json").stat().st_size for spec in specs),
        'mutation_controls_passed': controls['passed'],
        'per_case': per_case,
        'scope': (
            'Exact finite grammar and locked cases only. The 88,664 replay visits are the final '
            'one-fewer-product lower-bound trees; total producer DPLL search also includes earlier '
            'unsatisfiable bounds and satisfying witness searches.'
        ),
        'aggregation_cpu_seconds': time.process_time() - start,
        'peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    }
    (args.proof_dir / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps({key: value for key, value in summary.items() if key != 'per_case'}, indent=2))


if __name__ == '__main__':
    main()
