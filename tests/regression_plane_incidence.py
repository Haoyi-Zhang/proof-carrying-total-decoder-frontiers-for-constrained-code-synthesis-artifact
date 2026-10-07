"""Pure finite incidence/plane regressions; no output files or measurements.

The separate CI step does not change the frozen 81-stage scientific campaign.
"""
import copy
import functools
import hashlib
import itertools
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
try:
    import resource
except ModuleNotFoundError:
    resource = types.ModuleType('resource')
    def deny(name):
        raise RuntimeError('POSIX CLI operation excluded from pure regression: ' + name)
    resource.__getattr__ = deny
    sys.modules['resource'] = resource
import frontier_proofs as producer
import frontier_proof_check as checker

def load(relative):
    return json.loads((ROOT / relative).read_text(encoding='utf-8'))

def without_clock(record):
    answer = copy.deepcopy(record)
    answer.pop('generation_wall_seconds')
    for attempt in answer['attempts']:
        attempt.pop('wall_seconds')
    return answer

def literal_cubes(domain, width):
    answer = []
    for pattern in itertools.product('*01', repeat=width):
        rows = tuple(i for i, value in enumerate(domain)
                     if all(p == '*' or p == bit for p, bit in
                            zip(pattern, format(value, f'0{width}b'))))
        if rows:
            answer.append((''.join(pattern), rows))
    return tuple(answer)

def literal_minimum(domain, width, outputs, legal):
    """Tiny SOP enumeration of cube/mask subsets, not producer or checker search."""
    options = [(cube, mask) for cube, unused in literal_cubes(domain, width)
               for mask in range(1, 1 << outputs)]
    for count in range(4):
        for terms in itertools.combinations(options, count):
            values = []
            for value in domain:
                bits = format(value, f'0{width}b'); result = 0
                for cube, mask in terms:
                    if all(c == '*' or c == bit for c, bit in zip(cube, bits)):
                        result |= mask
                values.append(result)
            if all(value in legal[i] for i, value in enumerate(values)):
                return count
    raise AssertionError('tiny enumeration ceiling')

def encoding_record(enc):
    return {'variables': enc.cnf.variable_count, 'names': enc.cnf.names,
            'application': enc.cnf.application_variables, 'clauses': enc.cnf.clauses,
            'cubes': enc.cubes, 'selected': enc.selected, 'connected': enc.connected,
            'outputs': enc.outputs, 'preferred': enc.preferred}

@functools.lru_cache(maxsize=1)
def snapshot():
    planes = []; cases = []; formulas = []; refusals = []
    with patch.object(producer.time, 'perf_counter', return_value=0.0):
        for spec in load('inputs/cases.json'):
            retained = load(f"results/proof-frontiers/{spec['id']}.json")
            current = copy.deepcopy(retained)
            for collection in ('encoder_planes', 'decoder_planes'):
                for key, original in retained[collection].items():
                    domain = tuple(original['domain']); width = original['width']
                    outputs = original['outputs']; legal = tuple(map(tuple, original['legal_outputs']))
                    result = producer.solve_plane(domain, width, outputs, legal, spec['gate_cap'])
                    result.update(domain=list(domain), width=width, outputs=outputs,
                                  legal_outputs=list(map(list, legal)))
                    assert without_clock(result) == without_clock(original)
                    report = checker.verify_plane(result)
                    current[collection][key] = result
                    planes.append({'case': spec['id'], 'collection': collection, 'key': key,
                                   'record': result, 'verification': report})
                    for bound in range(-1, result['minimum_products'] + 2):
                        enc = producer.build_plane_cnf(domain, width, outputs, legal, bound)
                        ref = checker.plane_formula(domain, width, outputs, legal, bound)
                        assert enc.cnf.variable_count == ref.variables and enc.cnf.clauses == ref.clauses
                        ordered = json.dumps(encoding_record(enc), sort_keys=True, separators=(',', ':'))
                        formulas.append([spec['id'], collection, key, bound,
                                         hashlib.sha256(ordered.encode()).hexdigest()])
            cases.append(checker.verify_case(current, spec, load(f"results/{spec['id']}.json")))
        for domain, width, legal, maximum in (
            ((0,), -1, (), 2), ((0,), -1, ((),), 2),
            ((0,), 1, ((1,),), -1), ((0,), 1, ((1,),), 0),
        ):
            try:
                producer.solve_plane(domain, width, 1, legal, maximum)
            except (ValueError, RuntimeError) as exc:
                refusals.append([type(exc).__name__, str(exc)])
            else:
                raise AssertionError('missing refusal')
    return {'planes': planes, 'cases': cases, 'ordered_formula_hashes': formulas, 'refusals': refusals}

class PlaneIncidenceTests(unittest.TestCase):
    def test_complete_current_planes_and_independent_replay(self):
        result = snapshot()
        self.assertEqual(len(result['planes']), 384)
        self.assertEqual(len(result['cases']), 16)
        self.assertEqual(sum(c['encoders'] for c in result['cases']), 174)
        self.assertEqual(sum(c['semantic_rejections'] for c in result['cases']), 234)
        self.assertEqual(sum(c['proof_node_visits'] for c in result['cases']), 88664)
        self.assertEqual(sum(len(c['frontier']) for c in result['cases']), 18)

    def test_literal_domains_relations_and_fresh_bound_state(self):
        for count in range(1, 5):
            for domain in itertools.permutations(range(4), count):
                cubes = producer._plane_cubes(domain, 2, ((0, 1),)*count)
                self.assertEqual(cubes, literal_cubes(domain, 2))
                old_enc = None
                for bound in (-1, 0, 1, 3):
                    enc = producer._build_plane_cnf(domain, 1, ((0, 1),)*count, bound, cubes)
                    direct = producer.build_plane_cnf(domain, 2, 1, ((0, 1),)*count, bound)
                    self.assertEqual(encoding_record(enc), encoding_record(direct))
                    if old_enc is not None:
                        self.assertIsNot(enc.cnf, old_enc.cnf)
                        self.assertIsNot(enc.cnf.clauses, old_enc.cnf.clauses)
                    old_enc = enc
        with patch.object(producer.time, 'perf_counter', return_value=0.0):
            for legal in itertools.product(((0,), (1,), (0, 1)), repeat=2):
                actual = producer.solve_plane((1, 0), 1, 1, legal, 3)
                self.assertEqual(actual['minimum_products'], literal_minimum((1, 0), 1, 1, legal))
            legal = ((0, 1, 2), (3,))
            actual = producer.solve_plane((0, 1), 1, 2, legal, 3)
            self.assertEqual(actual['minimum_products'], literal_minimum((0, 1), 1, 2, legal))
            original = producer.cube_patterns
            with patch.object(producer, 'cube_patterns', wraps=original) as counted:
                actual = producer.solve_plane((0, 1, 3), 2, 1, ((1,), (0,), (1,)), 3)
                self.assertEqual(actual['minimum_products'], 2)
                self.assertEqual(counted.call_count, 1)
        # Raw ternary 10 is not a domain row; unsorted valid representations stay bound.
        domain = (15, 0, 1, 3, 4, 5, 7, 12, 13)
        self.assertEqual(producer._plane_cubes(domain, 4, ((0, 1),)*9), literal_cubes(domain, 4))

    def test_all_eight_retained_mutation_controls(self):
        sys.path.insert(0, str(ROOT / 'tests'))
        import frontier_proof_controls as controls
        mutations = [
            ('omit', ('B05', lambda c: c['mappings'].pop())),
            ('root', ('B05', lambda c: controls.first_lower_plane(c, internal=True)['lower_bound']['proof'].__setitem__('root', 0))),
            ('branch', ('B05', lambda c: controls.first_lower_plane(c, internal=True)['lower_bound']['proof']['nodes'][1].__setitem__(0, 10**6))),
            ('minimum', ('B05', lambda c: controls.first_lower_plane(c).__setitem__('minimum_products', controls.first_lower_plane(c)['minimum_products']-1))),
            ('mask', ('B05', lambda c: controls.first_lower_plane(c)['terms'][0].__setitem__('outputs', 0))),
            ('core', ('B01', lambda c: next(i for m in c['mappings'] for i in m['bounds'] if 'semantic_obstruction' in i)['semantic_obstruction'].__setitem__('source_messages', []))),
            ('relation', ('B05', lambda c: next(iter(c['decoder_planes'].values()))['legal_outputs'][0].append(1))),
            ('frontier', ('B05', lambda c: c['frontier'].pop())),
        ]
        for name, mutation in mutations:
            self.assertTrue(controls.rejected(name, mutation)['passed'], name)

if __name__ == '__main__':
    unittest.main()
