"""Exact finite reference enumerator; no physical-synthesis or heuristic-completeness claims.

A product is an AND of positive, negative, or absent binary literals, including
constant and single-literal products. Every selected product costs one site.
A fixed OR site is charged for every output, even an unused output. Sharing is
allowed within, but not across, the encoder and decoder planes. Negations are
free. Only valid alphabet representations are constrained at decoder inputs.
"""
from __future__ import annotations
import argparse
import itertools as it
import json
import resource
import signal
import time
from functools import lru_cache
from pathlib import Path


def words(q: int, n: int) -> list[tuple[int, ...]]:
    return list(it.product(range(q), repeat=n))


def wire_word(w: tuple[int, ...], q: int) -> int:
    out = 0
    for t in w:
        out = (out << (1 if q == 2 else 2)) | (t if q == 2 else (0, 1, 3)[t])
    return out


def cube_patterns(width: int, domain: tuple[int, ...]):
    """Return all nonempty row-cover patterns; digits 0,1,2 mean 0,1,* ."""
    out = []
    for p in it.product(range(3), repeat=width):
        cover = 0
        for row, val in enumerate(domain):
            if all(t == 2 or t == ((val >> (width-1-j)) & 1)
                   for j, t in enumerate(p)):
                cover |= 1 << row
        if cover:
            out.append((p, cover))
    return out


class PlaneCosts:
    def __init__(self, domain: tuple[int, ...], width: int, outputs: int):
        self.domain = domain
        self.width = width
        self.outputs = outputs
        self.patterns = cube_patterns(width, domain)
        self.cache: dict[tuple[int, ...], dict] = {}
        self.states = 0

    def get(self, table: tuple[int, ...]) -> dict:
        old = self.cache.get(table)
        if old is not None:
            return old
        rows = len(table)
        ones = [sum(1 << r for r, v in enumerate(table) if (v >> b) & 1)
                for b in range(self.outputs)]
        target = sum(mask << (b*rows) for b, mask in enumerate(ones))
        options = {}
        for pattern, cover in self.patterns:
            enabled = sum(1 << b for b, mask in enumerate(ones)
                          if cover & ~mask == 0)
            if not enabled:
                continue
            coverage = sum(cover << (b*rows) for b in range(self.outputs)
                           if (enabled >> b) & 1)
            options.setdefault(coverage, (pattern, enabled))
        covers = sorted(options, key=lambda c: (-c.bit_count(), c))
        maximal = []
        for c in covers:
            if not any(c & ~d == 0 for d in maximal):
                maximal.append(c)
        by_bit = {b: tuple(c for c in maximal if (c >> b) & 1)
                  for b in range(rows*self.outputs) if (target >> b) & 1}

        @lru_cache(None)
        def solve(rem: int):
            if not rem:
                return ()
            candidates = min((by_bit[b] for b in by_bit if (rem >> b) & 1),
                             key=len)
            answer = None
            for c in candidates:
                tail = solve(rem & ~c)
                proposal = (c,) + tail
                if answer is None or len(proposal) < len(answer):
                    answer = proposal
                    if len(answer) == 1:
                        break
            assert answer is not None
            return answer

        selected = solve(target)
        self.states += solve.cache_info().currsize
        terms = [{'cube': ''.join('*' if t == 2 else str(t) for t in options[c][0]),
                  'outputs': options[c][1]} for c in selected]
        result = {'products': len(selected), 'terms': terms}
        self.cache[table] = result
        return result


def validate_spec(spec):
    import math
    q,n,k=(spec[t] for t in ('q','n','k'))
    if q not in (2,3) or not (1<=n<=(8 if q==2 else 6)) or not (1<=k<=4):
        raise ValueError('Unsupported alphabet or dimension')
    if q**n>32 or spec['radius']!=1 or spec['gate_cap']!=24 or spec['connection_cap']!=48:
        raise ValueError('Outside frozen table/cost/radius caps')
    allowed=spec['allowed']
    if len(allowed)!=len(set(allowed)) or any(len(s)!=n or any(c not in '012'[:q] for c in s) for s in allowed):
        raise ValueError('Malformed or duplicate allowed word')
    estimate=math.perm(len(allowed),1<<k)*(1<<k)**(q**n-(1<<k)) if len(allowed)>=(1<<k) else 0
    if estimate>300000:
        raise ValueError('Enumeration exceeds the candidate cap; no completeness claim')
    if len(spec['id'])!=3 or spec['id'][0] not in 'BTC' or not spec['id'][1:].isdigit():
        raise ValueError('Invalid case identifier')


def run_case(spec: dict, directory: Path) -> dict:
    validate_spec(spec)
    start = time.perf_counter()
    cpu_start = time.process_time()
    q, n, k = (spec[t] for t in ('q','n','k'))
    ws = words(q, n)
    index = {w: j for j, w in enumerate(ws)}
    allowed = [index[tuple(map(int, s))] for s in spec['allowed']]
    count = 1 << k
    cw = n * (1 if q == 2 else 2)
    enc_cost = PlaneCosts(tuple(range(count)), k, cw)
    dec_cost = PlaneCosts(tuple(wire_word(w,q) for w in ws), cw, k)
    near = [[j for j,v in enumerate(ws) if sum(a != b for a,b in zip(w,v)) <= 1]
            for w in ws]
    best = [None] * (k+1)
    best_pair = [None] * (k+1)
    candidates = 0
    candidate_source_received_obligations = 0
    pair_pass_total_fail = 0
    pair_nonexpanding_encoders = 0
    histogram = {}
    for enc in it.permutations(allowed, count):
        enc = tuple(enc)
        enc_table = tuple(wire_word(ws[c],q) for c in enc)
        ec = enc_cost.get(enc_table)
        off = [r for r in range(len(ws)) if r not in enc]
        pair_error = max(((a^b).bit_count() for a in range(count)
                          for b in range(count) if enc[b] in near[enc[a]]), default=0)
        nonexp = all((a^b).bit_count() <= sum(x != y for x,y in zip(ws[enc[a]],ws[enc[b]]))
                     for a in range(count) for b in range(count))
        pair_nonexpanding_encoders += int(nonexp)
        sources = [[] for _ in ws]
        for x,c in enumerate(enc):
            for r in near[c]: sources[r].append(x)
        row_errors = [[max(((x^z).bit_count() for x in xs), default=0)
                       for z in range(count)] for xs in sources]
        for completion in it.product(range(count), repeat=len(off)):
            candidates += 1
            d = [0] * len(ws)
            for x,c in enumerate(enc): d[c] = x
            for r,z in zip(off,completion): d[r] = z
            dec = tuple(d)
            dc = dec_cost.get(dec)
            products = ec['products'] + dc['products']
            gates = products + cw + k
            connections = sum(t['outputs'].bit_count() for plane in (ec,dc) for t in plane['terms'])
            # Lower-bound costs use a relaxation of the connection cap. Each
            # stored minimizer must meet the original cap to close that gap.
            if connections > spec['connection_cap']:
                raise RuntimeError('Relaxed minimum violates connection cap; no completeness claim.')
            if gates > spec['gate_cap']:
                continue
            error = max(row_errors[r][z] for r,z in enumerate(dec))
            candidate_source_received_obligations += sum(len(x) for x in sources)
            pair_pass_total_fail += int(pair_error <= 1 < error)
            histogram[(error,gates)] = histogram.get((error,gates),0)+1
            witness = {'error':error,'gates':gates,'products':products,
                       'connections':connections,'encoder_rows':list(enc),
                       'decoder_table':list(dec),'encoder_plane':ec,'decoder_plane':dc}
            for bound in range(error,k+1):
                if best[bound] is None or gates < best[bound]['gates']:
                    best[bound] = witness
            for bound in range(pair_error,k+1):
                if best_pair[bound] is None or gates < best_pair[bound]['gates']:
                    best_pair[bound] = witness
    frontier = []
    prior = None
    for bound,w in enumerate(best):
        if w is not None and (prior is None or w['gates'] < prior):
            assert w['error'] == bound
            frontier.append(w)
            prior = w['gates']
    pair_frontier = []
    prior = None
    for bound,w in enumerate(best_pair):
        if w is not None and (prior is None or w['gates'] < prior):
            pair_frontier.append({'pair_error_bound':bound,'gates':w['gates'],
                                  'total_error_of_witness':w['error']})
            prior = w['gates']
    result = {'case':spec,'candidate_designs':candidates,
              'candidate_source_received_obligations_covered':candidate_source_received_obligations,
              'pair_nonexpanding_encoders':pair_nonexpanding_encoders,
              'pair_radius1_pass_total_fail_designs':pair_pass_total_fail,
              'frontier':frontier,'pair_only_frontier':pair_frontier,
              'best_cost_by_error_bound':[None if w is None else w['gates'] for w in best],
              'histogram':[{'error':a,'gates':g,'count':c} for (a,g),c in sorted(histogram.items())],
              'distinct_encoder_tables':len(enc_cost.cache),'distinct_decoder_tables':len(dec_cost.cache),
              'cover_dynamic_program_states':enc_cost.states+dec_cost.states,
              'cpu_seconds':time.process_time()-cpu_start,
              'wall_seconds':time.perf_counter()-start,
              'peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
    directory.mkdir(parents=True,exist_ok=True)
    (directory/(spec['id']+'.json')).write_text(json.dumps(result,indent=2)+'\n')
    costs = {'encoder':[{'table':list(t),**v} for t,v in enc_cost.cache.items()],
             'decoder':[{'table':list(t),**v} for t,v in dec_cost.cache.items()]}
    (directory/(spec['id']+'-costs.json')).write_text(json.dumps(costs,separators=(',',':'))+'\n')
    return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--case',required=True)
    parser.add_argument('--inputs',type=Path,default=Path('inputs/cases.json'))
    parser.add_argument('--output',type=Path,default=Path('results'))
    args=parser.parse_args()
    signal.alarm(600)
    resource.setrlimit(resource.RLIMIT_AS,(3*1024**3,3*1024**3))
    specs=json.loads(args.inputs.read_text())
    spec=next(s for s in specs if s['id']==args.case)
    r=run_case(spec,args.output)
    print(json.dumps({t:r[t] for t in ('candidate_designs','best_cost_by_error_bound','cpu_seconds','wall_seconds','peak_rss_kib')},indent=2))

if __name__=='__main__': main()
