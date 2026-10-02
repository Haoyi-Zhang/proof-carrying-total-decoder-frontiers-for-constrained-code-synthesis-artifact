"""Exact row-list projection, counts and locally checkable obstructions.
This module never enumerates decoder completions or claims a circuit lower bound.
"""
from __future__ import annotations
import argparse
import itertools
import json
import math
import resource
import time
from pathlib import Path


def profile(spec: dict) -> dict:
    q, n, k = spec['q'], spec['n'], spec['k']
    if q not in (2, 3) or not (1 <= k <= 4) or q**n > 32:
        raise ValueError('outside the total-table grammar')
    words = [''.join(map(str, w)) for w in itertools.product(range(q), repeat=n)]
    allowed = spec['allowed']
    if len(set(allowed)) != len(allowed) or any(w not in words for w in allowed):
        raise ValueError('invalid allowed channel words')
    m = 1 << k
    records = []
    comparisons = 0
    for enc in itertools.permutations(allowed, m):
        pins = {w: x for x, w in enumerate(enc)}
        sources = []
        for y in words:
            sy = []
            for x, w in enumerate(enc):
                comparisons += 1
                if sum(s != t for s, t in zip(w, y)) <= spec['radius']:
                    sy.append(x)
            sources.append(sy)
        for bound in range(k+1):
            rows, obstruction = [], None
            for y, sy in zip(words, sources):
                choices = [z for z in range(m)
                           if all((x ^ z).bit_count() <= bound for x in sy)
                           and (y not in pins or z == pins[y])]
                rows.append({'received': y, 'sources': sy, 'outputs': choices})
                if not choices and obstruction is None:
                    if y in pins:
                        z = pins[y]
                        x = next(x for x in sy if (x ^ z).bit_count() > bound)
                        obstruction = {'kind': 'pin', 'received': y,
                                       'sources': [x], 'pinned_message': z}
                    else:
                        # Deterministic deletion-minimal core; no claim of
                        # minimum-cardinality extraction for general payloads.
                        core = list(sy)
                        for x in list(sy):
                            smaller = [t for t in core if t != x]
                            if not any(all((t ^ z).bit_count() <= bound for t in smaller)
                                       for z in range(m)):
                                core = smaller
                        obstruction = {'kind': 'empty_intersection',
                                       'received': y, 'sources': core}
            records.append({'encoder': list(enc), 'bound': bound,
                            'rows': rows,
                            'decoder_count': math.prod(len(r['outputs']) for r in rows),
                            'obstruction': obstruction})
    totals = [sum(r['decoder_count'] for r in records if r['bound'] == a)
              for a in range(k+1)]
    return {'case': spec, 'profiles': records, 'cumulative_decoder_counts': totals,
            'channel_distance_comparisons': comparisons}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--case', help='one exact case, for a bounded pilot')
    parser.add_argument('--output', default='results/semantic-projection.json')
    args = parser.parse_args()
    resource.setrlimit(resource.RLIMIT_AS, (3*1024**3, 3*1024**3))
    begin = time.process_time()
    specs = json.loads(Path('inputs/cases.json').read_text())
    if args.case:
        specs = [s for s in specs if s['id'] == args.case]
        if not specs:
            raise ValueError('unknown case')
    cases = [profile(s) for s in specs]
    out = {'cases': cases, 'profile_count': sum(len(c['profiles']) for c in cases),
           'cpu_seconds': time.process_time()-begin,
           'peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
           'scope': 'Unrestricted total-decoder semantics only; not circuit cost certification.'}
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2)+'\n')
    print(f"{len(cases)} cases, {out['profile_count']} encoder-bound profiles")

if __name__ == '__main__':
    main()
