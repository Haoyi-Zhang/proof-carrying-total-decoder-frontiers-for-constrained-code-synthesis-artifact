"""Independent tuple/set checker for semantic-projection records.
No import of the producer, the synthesis engine, or the frontier checker.
"""
from __future__ import annotations
import argparse
import itertools
import json
import math
import resource
import time
from pathlib import Path


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise ValueError(reason)


def verify_case(record: dict, spec: dict, result: dict) -> dict:
    require(record['case'] == spec, 'specification mismatch')
    q, n, k = spec['q'], spec['n'], spec['k']
    channel = tuple(itertools.product(range(q), repeat=n))
    messages = tuple(itertools.product((0, 1), repeat=k))
    m = len(messages)
    md = [[sum(a != b for a, b in zip(x, z)) for z in messages] for x in messages]
    asword = lambda y: ''.join(str(s) for s in y)
    encoders = set(itertools.permutations(spec['allowed'], m))
    expected = {(e, a) for e in encoders for a in range(k+1)}
    seen = set()
    totals = [0]*(k+1)
    rejected = [0]*(k+1)
    cores = {}
    row_checks = 0
    source_checks = 0
    for r in record['profiles']:
        key = (tuple(r['encoder']), r['bound'])
        require(key in expected and key not in seen, 'missing/extraneous or duplicated profile')
        seen.add(key)
        enc, bound = key
        require(len(r['rows']) == len(channel), 'missing received row')
        product = 1
        empty_words = []
        source_map = {}
        for row, y in zip(r['rows'], channel):
            yw = asword(y)
            require(row['received'] == yw, 'row order or word mismatch')
            sy = set()
            for x, cw in enumerate(enc):
                source_checks += 1
                if sum(int(s) != t for s, t in zip(cw, y)) <= spec['radius']:
                    sy.add(x)
            source_map[yw] = sy
            require(row['sources'] == sorted(sy), 'source set mismatch')
            valid = set(range(m))
            for x in sy:
                valid &= {z for z in range(m) if md[x][z] <= bound}
            if yw in enc:
                valid &= {enc.index(yw)}
            require(row['outputs'] == sorted(valid), 'output intersection/pin mismatch')
            row_checks += 1
            product *= len(valid)
            if not valid:
                empty_words.append(yw)
        require(type(r['decoder_count']) is int and r['decoder_count'] == product,
                'product count mismatch')
        totals[bound] += product
        cert = r['obstruction']
        if product:
            require(cert is None, 'spurious obstruction for feasible profile')
        else:
            rejected[bound] += 1
            require(isinstance(cert, dict), 'missing infeasibility witness')
            yw = cert['received']
            require(yw in empty_words, 'obstruction at nonempty row')
            core = cert['sources']
            require(len(core) == len(set(core)) and bool(core), 'invalid source core')
            require(set(core) <= source_map[yw], 'core has unreachable source')
            if cert['kind'] == 'pin':
                require(yw in enc, 'missing inverse pin')
                z = enc.index(yw)
                require(cert['pinned_message'] == z and len(core) == 1, 'wrong pin')
                require(md[core[0]][z] > bound, 'pin is not violated')
                cores['pin'] = cores.get('pin', 0)+1
            else:
                require(cert['kind'] == 'empty_intersection', 'unknown obstruction kind')
                require(not any(all(md[x][z] <= bound for x in core) for z in range(m)),
                        'core intersection not empty')
                require(bound < k and len(core) <= 2**(bound+1), 'Helly witness bound')
                # Actual deletion minimality, not minimum-cardinality.
                for omit in core:
                    require(any(all(md[x][z] <= bound for x in core if x != omit)
                                for z in range(m)), 'core not deletion-minimal')
                name = 'intersection_'+str(len(core))
                cores[name] = cores.get(name, 0)+1
    require(seen == expected, 'incomplete encoder-bound coverage')
    require(totals == record['cumulative_decoder_counts'], 'aggregate count mismatch')
    require(totals[-1] == len(encoders)*m**(len(channel)-m), 'unrestricted count mismatch')
    require(result['case'] == spec, 'frontier input mismatch')
    # Cost caps might remove functions in another family. Demand full coverage
    # before comparing these cost-independent semantic counts to its histogram.
    hist = result['histogram']
    require(sum(v['count'] for v in hist) == result['candidate_designs'] == totals[-1],
            'cost-filtered or incomplete histogram cannot validate projection')
    from_hist = [sum(v['count'] for v in hist if v['error'] <= a) for a in range(k+1)]
    require(totals == from_hist, 'semantic count disagrees with exhaustive histogram')
    return {'case': spec['id'], 'encoders': len(encoders), 'profiles': len(seen),
            'decoder_count_by_bound': totals, 'infeasible_encoders_by_bound': rejected,
            'obstruction_kinds': cores, 'received_rows_checked': row_checks,
            'channel_distance_comparisons': source_checks, 'accepted': True}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', default='results/semantic-projection.json')
    parser.add_argument('--output', default='results/semantic-projection-check.json')
    args = parser.parse_args()
    resource.setrlimit(resource.RLIMIT_AS, (3*1024**3, 3*1024**3))
    begin = time.process_time()
    data = json.loads(Path(args.input).read_text())
    specs = {s['id']: s for s in json.loads(Path('inputs/cases.json').read_text())}
    require(len(data['cases']) == len(specs), 'case list incomplete')
    ids = [c['case']['id'] for c in data['cases']]
    require(len(set(ids)) == len(ids) and set(ids) == set(specs), 'case identity mismatch')
    reports = [verify_case(c, specs[c['case']['id']],
                          json.loads(Path('results', c['case']['id']+'.json').read_text()))
               for c in data['cases']]
    count = sum(r['profiles'] for r in reports)
    require(data['profile_count'] == count, 'profile count mismatch')
    out = {'accepted': True, 'profiles_checked': count,
           'encoders_checked': sum(r['encoders'] for r in reports),
           'cases': reports, 'cpu_seconds': time.process_time()-begin,
           'peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
    Path(args.output).write_text(json.dumps(out, indent=2)+'\n')
    print(f"Accepted {count} profiles; all semantic counts match exhaustive histograms.")

if __name__ == '__main__':
    main()
