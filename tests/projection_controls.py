"""Negative controls for row semantics, count coverage, and bitwise relaxation."""
from __future__ import annotations
import copy
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from projection_check import verify_case


def main() -> None:
    data = json.loads(Path('results/semantic-projection.json').read_text())
    original = next(c for c in data['cases'] if c['case']['id'] == 'T02')
    spec = original['case']
    result = json.loads(Path('results/T02.json').read_text())
    records = []
    def reject(name, mutate):
        modified = copy.deepcopy(original)
        mutate(modified)
        try:
            verify_case(modified, spec, result)
        except ValueError as error:
            records.append({'control': name, 'passed': True, 'reason': str(error)})
        else:
            raise RuntimeError(name+' was accepted')
    reject('missing_source', lambda c: c['profiles'][0]['rows'][0]['sources'].pop())
    reject('false_output', lambda c: c['profiles'][0]['rows'][0]['outputs'].append(0))
    reject('missing_encoder_bound', lambda c: c['profiles'].pop())
    reject('wrong_decoder_count', lambda c: c['profiles'][0].update(decoder_count=1))
    def corrupt_core(c):
        row = next(r for r in c['profiles'] if r['obstruction'] is not None
                   and r['obstruction']['kind'] == 'empty_intersection')
        row['obstruction']['sources'].pop()
    reject('incomplete_obstruction', corrupt_core)
    # B_1(00) is a correlated legal-output list. Independent bit marginals
    # admit 11, which is not in that list; this is not a solver experiment.
    legal = {0, 1, 2}
    masks = [{(z >> b) & 1 for z in legal} for b in range(2)]
    relaxed = {z for z in range(4) if all(((z >> b) & 1) in masks[b] for b in range(2))}
    if relaxed != {0, 1, 2, 3} or 3 in legal:
        raise RuntimeError('relational-output control invalid')
    records.append({'control': 'bitwise_relaxation_exposes_forbidden_output',
                    'passed': True, 'legal_outputs': sorted(legal),
                    'bitwise_relaxation': sorted(relaxed)})
    Path('results/projection-controls.json').write_text(json.dumps(records, indent=2)+'\n')
    print(f"{len(records)} semantic controls passed.")

if __name__ == '__main__':
    main()
