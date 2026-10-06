"""Exhaustive small-oracle checks for cardinality and relational CNF encodings."""
from __future__ import annotations

import itertools as it
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from frontier_proofs import CNF, build_plane_cnf
from frontier_proof_check import Formula, plane_formula
from fixed_codebook_proof import cube_patterns, plane_certificate
from fixed_codebook_check import check_plane, cube_rows

ROOT = Path(__file__).resolve().parents[1]


def sat(variables: int, clauses: list[tuple[int, ...]], assumptions: tuple[int, ...] = ()) -> bool:
    assignment = [0] * (variables + 1)

    def put(literal: int, trail: list[int]) -> bool:
        var = abs(literal)
        wanted = 1 if literal > 0 else -1
        if assignment[var] == 0:
            assignment[var] = wanted
            trail.append(var)
            return True
        return assignment[var] == wanted

    initial: list[int] = []
    for literal in assumptions:
        if not put(literal, initial):
            return False

    def recurse() -> bool:
        mark: list[int] = []
        changed = True
        while changed:
            changed = False
            for clause in clauses:
                open_literals = []
                satisfied = False
                for literal in clause:
                    value = assignment[abs(literal)]
                    value = value if literal > 0 else -value
                    if value > 0:
                        satisfied = True
                        break
                    if value == 0:
                        open_literals.append(literal)
                if satisfied:
                    continue
                if not open_literals:
                    for var in reversed(mark):
                        assignment[var] = 0
                    return False
                if len(open_literals) == 1:
                    if not put(open_literals[0], mark):
                        for var in reversed(mark):
                            assignment[var] = 0
                        return False
                    changed = True
        if all(any((assignment[abs(l)] if l > 0 else -assignment[abs(l)]) > 0 for l in clause) for clause in clauses):
            for var in reversed(mark):
                assignment[var] = 0
            return True
        variable = next(var for var in range(1, variables + 1) if assignment[var] == 0)
        for literal in (-variable, variable):
            branch: list[int] = []
            put(literal, branch)
            if recurse():
                for var in reversed(branch):
                    assignment[var] = 0
                for var in reversed(mark):
                    assignment[var] = 0
                return True
            for var in reversed(branch):
                assignment[var] = 0
        for var in reversed(mark):
            assignment[var] = 0
        return False

    answer = recurse()
    for var in reversed(initial):
        assignment[var] = 0
    return answer


def cardinality_checks() -> dict:
    assignments = 0
    formulas = 0
    for count in range(1, 6):
        for limit in range(-1, count + 1):
            producer = CNF()
            pvars = [producer.variable(f"x[{i}]") for i in range(count)]
            producer.at_most(pvars, limit, "p")
            checker = Formula()
            cvars = tuple(checker.variable(f"x[{i}]") for i in range(count))
            checker.at_most(cvars, limit)
            if producer.variable_count != checker.variables or producer.clauses != checker.clauses:
                raise ValueError("producer/checker cardinality CNFs differ")
            formulas += 1
            for bits in it.product((0, 1), repeat=count):
                assumptions = tuple(var if bit else -var for var, bit in zip(pvars, bits))
                actual = sat(producer.variable_count, producer.clauses, assumptions)
                expected = sum(bits) <= limit
                if actual != expected:
                    raise ValueError(f"cardinality mismatch n={count} limit={limit} bits={bits}")
                assignments += 1
    return {"formulas": formulas, "assignments": assignments}


def direct_single_output(legal: tuple[tuple[int, ...], ...], bound: int) -> bool:
    cubes = ("*", "0", "1")
    domain = (0, 1)
    for selected_count in range(bound + 1):
        for selected in it.combinations(cubes, selected_count):
            table = []
            for value in domain:
                bit = str(value)
                table.append(1 if any(cube == "*" or cube == bit for cube in selected) else 0)
            if all(table[row] in set(legal[row]) for row in range(2)):
                return True
    return False


def relation_checks() -> dict:
    options = ((0,), (1,), (0, 1))
    relations = 0
    bounds = 0
    for left in options:
        for right in options:
            legal = (left, right)
            relations += 1
            for bound in range(4):
                producer = build_plane_cnf((0, 1), 1, 1, legal, bound)
                checker = plane_formula((0, 1), 1, 1, legal, bound)
                if producer.cnf.variable_count != checker.variables or producer.cnf.clauses != checker.clauses:
                    raise ValueError("producer/checker relational CNFs differ")
                actual = sat(producer.cnf.variable_count, producer.cnf.clauses)
                expected = direct_single_output(legal, bound)
                if actual != expected:
                    raise ValueError(f"relational mismatch legal={legal} bound={bound}")
                bounds += 1

    correlated = build_plane_cnf((0,), 1, 2, ((0, 1, 2),), 1)
    d0, d1 = correlated.outputs[0]
    if sat(correlated.cnf.variable_count, correlated.cnf.clauses, (d0, d1)):
        raise ValueError("correlated row illegally admits output 11")
    if not sat(correlated.cnf.variable_count, correlated.cnf.clauses):
        raise ValueError("correlated row relation is unexpectedly infeasible")
    return {"relations": relations, "bounds": bounds, "correlated_forbidden_tuple_checks": 2}


def packing_domain_checks() -> dict:
    # All 64 nonempty ordered subsets of the two-bit Boolean domain. Row
    # labels and Boolean values coincide only for the numeric-order prefix.
    domains = 0
    for count in range(1, 5):
        for domain in it.permutations(range(4), count):
            producer = tuple(cube_patterns(2, domain))
            checker = cube_rows(domain, 2)
            if producer != checker:
                raise ValueError(f'packing cube/domain mismatch: {domain}')
            domains += 1
    # True rows 00,01,11 with outputs 1,0,1 need two products. Relabeling
    # them as 00,01,10 incorrectly admits one cube *0 for both forced ones.
    domain = (0, 1, 3)
    legal = ((1,), (0,), (1,))
    terms = [{'cube': '00', 'outputs': 1}, {'cube': '11', 'outputs': 1}]
    record = plane_certificate(domain, 2, 1, legal, terms)
    check_plane(record, expected_domain=domain, expected_width=2,
                expected_outputs=1, expected_legal=legal, label='sparse regression')
    if record['minimum_products'] != 2 or len(record['packing']) != 2:
        raise ValueError('sparse-domain packing is not exact')
    return {'ordered_domains': domains, 'sparse_exact_planes': 1}


report = {
    "accepted": True,
    "cardinality": cardinality_checks(),
    "relational": relation_checks(),
    "packing_domains": packing_domain_checks(),
    "scope": "Exhaustive small-oracle tests; not a proof for arbitrary encodings.",
}
(ROOT / "results/encoding-properties.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
