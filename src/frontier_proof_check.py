"""Independent checker for proof-carrying frontier certificates.

This file deliberately does not import the producer, exhaustive synthesis code,
or the original frontier checker.  It reconstructs the finite domains, CNFs,
semantic row relations, branch proofs, circuits, objective profiles and encoder
coverage from the delivered certificate and locked input specification.
"""
from __future__ import annotations

import argparse
import itertools as it
import json
import resource
import signal
import time
from pathlib import Path


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def words(q: int, n: int) -> tuple[tuple[int, ...], ...]:
    return tuple(it.product(range(q), repeat=n))


def raw(word: tuple[int, ...], q: int) -> int:
    result = 0
    for symbol in word:
        result = (result << (1 if q == 2 else 2)) | (
            symbol if q == 2 else (0, 1, 3)[symbol]
        )
    return result


def cube_rows(width: int, domain: tuple[int, ...]) -> tuple[tuple[str, tuple[int, ...]], ...]:
    answer = []
    for pattern in it.product((-1, 0, 1), repeat=width):
        covered = tuple(
            row
            for row, value in enumerate(domain)
            if all(
                symbol == -1 or symbol == ((value >> (width - 1 - j)) & 1)
                for j, symbol in enumerate(pattern)
            )
        )
        if covered:
            answer.append(("".join("*" if s == -1 else str(s) for s in pattern), covered))
    return tuple(answer)


class Formula:
    def __init__(self) -> None:
        self.variables = 0
        self.names: dict[str, int] = {}
        self.clauses: list[tuple[int, ...]] = []

    def variable(self, name: str) -> int:
        if name not in self.names:
            self.variables += 1
            self.names[name] = self.variables
        return self.names[name]

    def add(self, *literals: int) -> None:
        values = set(literals)
        if any(-literal in values for literal in values):
            return
        self.clauses.append(tuple(sorted(values, key=lambda x: (abs(x), x < 0))))

    def at_most(self, variables: tuple[int, ...], limit: int) -> None:
        n = len(variables)
        if limit < 0:
            self.add()
            return
        if limit >= n:
            return
        if limit == 0:
            for variable in variables:
                self.add(-variable)
            return
        counter: dict[tuple[int, int], int] = {}
        for i in range(1, n):
            for j in range(1, limit + 1):
                counter[i, j] = self.variable(f"aux[{i},{j}]")
        self.add(-variables[0], counter[1, 1])
        for j in range(2, limit + 1):
            self.add(-counter[1, j])
        for i in range(2, n):
            self.add(-variables[i - 1], counter[i, 1])
            self.add(-counter[i - 1, 1], counter[i, 1])
            for j in range(2, limit + 1):
                self.add(-variables[i - 1], -counter[i - 1, j - 1], counter[i, j])
                self.add(-counter[i - 1, j], counter[i, j])
            self.add(-variables[i - 1], -counter[i - 1, limit])
        self.add(-variables[n - 1], -counter[n - 1, limit])


def plane_formula(
    domain: tuple[int, ...],
    width: int,
    output_count: int,
    legal: tuple[tuple[int, ...], ...],
    bound: int,
) -> Formula:
    require(len(domain) == len(legal), "plane row count mismatch")
    require(all(row for row in legal), "empty legal row in CNF certificate")
    formula = Formula()
    cubes = cube_rows(width, domain)
    selected = tuple(formula.variable(f"s[{c}]") for c in range(len(cubes)))
    connected = tuple(
        tuple(formula.variable(f"t[{c},{j}]") for j in range(output_count))
        for c in range(len(cubes))
    )
    outputs = tuple(
        tuple(formula.variable(f"d[{r},{j}]") for j in range(output_count))
        for r in range(len(domain))
    )
    for c in range(len(cubes)):
        for j in range(output_count):
            formula.add(-connected[c][j], selected[c])
        formula.add(-selected[c], *connected[c])
    match: list[list[int]] = [[] for _ in domain]
    for c, (_, rows) in enumerate(cubes):
        for row in rows:
            match[row].append(c)
        for j in range(output_count):
            for row in rows:
                formula.add(-connected[c][j], outputs[row][j])
    for row in range(len(domain)):
        for j in range(output_count):
            formula.add(-outputs[row][j], *(connected[c][j] for c in match[row]))
        allowed = set(legal[row])
        require(all(type(v) is int and 0 <= v < 1 << output_count for v in allowed), "invalid legal output")
        for value in range(1 << output_count):
            if value not in allowed:
                formula.add(
                    *(
                        outputs[row][j]
                        if ((value >> (output_count - 1 - j)) & 1) == 0
                        else -outputs[row][j]
                        for j in range(output_count)
                    )
                )
    formula.at_most(selected, bound)
    return formula


class BranchProofChecker:
    def __init__(self, formula: Formula, proof: dict) -> None:
        require(proof.get("format") == "unit-conflict-dpll-v1", "unknown proof format")
        self.formula = formula
        self.nodes = proof.get("nodes")
        self.root = proof.get("root")
        require(isinstance(self.nodes, list) and self.nodes, "missing proof nodes")
        require(self.nodes[0] == [0], "node zero is not the conflict leaf")
        require(type(self.root) is int and 0 <= self.root < len(self.nodes), "invalid proof root")
        self.assignment = [0] * (formula.variables + 1)
        self.trail: list[int] = []
        self.visits = 0
        self.conflicts = 0
        self.stack: set[int] = set()
        self.reached_internal: set[int] = set()

    def value(self, literal: int) -> int:
        assigned = self.assignment[abs(literal)]
        return assigned if literal > 0 else -assigned

    def put(self, literal: int) -> bool:
        variable = abs(literal)
        require(1 <= variable <= self.formula.variables, "proof branches outside the CNF")
        desired = 1 if literal > 0 else -1
        if self.assignment[variable] == 0:
            self.assignment[variable] = desired
            self.trail.append(variable)
            return True
        return self.assignment[variable] == desired

    def undo(self, mark: int) -> None:
        while len(self.trail) > mark:
            self.assignment[self.trail.pop()] = 0

    def propagate(self) -> bool:
        changed = True
        while changed:
            changed = False
            for clause in self.formula.clauses:
                satisfied = False
                unassigned = 0
                unit = 0
                for literal in clause:
                    value = self.value(literal)
                    if value > 0:
                        satisfied = True
                        break
                    if value == 0:
                        unassigned += 1
                        unit = literal
                if satisfied:
                    continue
                if unassigned == 0:
                    return False
                if unassigned == 1:
                    if not self.put(unit):
                        return False
                    changed = True
        return True

    def visit(self, index: int) -> None:
        require(type(index) is int and 0 <= index < len(self.nodes), "bad child index")
        require(index not in self.stack, "cyclic proof")
        self.visits += 1
        entry = len(self.trail)
        consistent = self.propagate()
        record = self.nodes[index]
        require(isinstance(record, list), "malformed proof node")
        if not consistent:
            require(record == [0], "branch node used where unit propagation already conflicts")
            self.conflicts += 1
            self.undo(entry)
            return
        require(index != 0 and len(record) == 3, "leaf without a unit conflict")
        variable, left, right = record
        require(type(variable) is int and 1 <= variable <= self.formula.variables, "invalid branch variable")
        require(self.assignment[variable] == 0, "branch variable already propagated")
        require(index not in self.reached_internal, "shared internal subtree is not a tree certificate")
        self.reached_internal.add(index)
        self.stack.add(index)
        propagated_mark = len(self.trail)
        require(self.put(-variable), "inconsistent false branch")
        self.visit(left)
        self.undo(propagated_mark)
        require(self.put(variable), "inconsistent true branch")
        self.visit(right)
        self.undo(propagated_mark)
        self.stack.remove(index)
        self.undo(entry)

    def check(self) -> dict:
        self.visit(self.root)
        require(self.reached_internal == set(range(1, len(self.nodes))), "unreachable or omitted proof records")
        return {"proof_node_visits": self.visits, "conflict_leaves": self.conflicts}


def evaluate_terms(
    terms: list[dict], domain: tuple[int, ...], width: int, output_count: int
) -> tuple[tuple[int, ...], int]:
    require(isinstance(terms, list), "terms are not a list")
    seen: set[str] = set()
    output_table = []
    connections = 0
    for term in terms:
        require(set(term) == {"cube", "outputs"}, "malformed term")
        cube = term["cube"]
        mask = term["outputs"]
        require(isinstance(cube, str) and len(cube) == width and not (set(cube) - set("01*")), "invalid cube")
        require(cube not in seen, "duplicate cube")
        seen.add(cube)
        require(type(mask) is int and 0 < mask < 1 << output_count, "invalid connection mask")
        connections += mask.bit_count()
    for value in domain:
        bits = format(value, f"0{width}b")
        output = 0
        for term in terms:
            if all(symbol == "*" or symbol == bit for symbol, bit in zip(term["cube"], bits)):
                output |= term["outputs"]
        output_table.append(output)
    return tuple(output_table), connections


def verify_plane(record: dict) -> dict:
    required = {
        "minimum_products",
        "terms",
        "connections",
        "lower_bound",
        "sat_cnf",
        "attempts",
        "generation_wall_seconds",
        "domain",
        "width",
        "outputs",
        "legal_outputs",
    }
    require(set(record) == required, "plane certificate fields differ")
    domain = tuple(record["domain"])
    width = record["width"]
    outputs = record["outputs"]
    legal = tuple(tuple(row) for row in record["legal_outputs"])
    minimum = record["minimum_products"]
    require(type(width) is int and width >= 1 and type(outputs) is int and outputs >= 1, "bad plane dimensions")
    require(type(minimum) is int and minimum >= 0, "bad minimum product count")
    table, connections = evaluate_terms(record["terms"], domain, width, outputs)
    require(len(record["terms"]) == minimum, "attaining circuit has wrong product count")
    require(connections == record["connections"], "connection count mismatch")
    require(len(table) == len(legal) and all(table[row] in set(legal[row]) for row in range(len(table))), "attaining circuit violates relation")
    sat = record["sat_cnf"]
    require(sat == {"bound": minimum, "variables": sat["variables"], "clauses": sat["clauses"]}, "malformed SAT metadata")
    sat_formula = plane_formula(domain, width, outputs, legal, minimum)
    require(sat["variables"] == sat_formula.variables and sat["clauses"] == len(sat_formula.clauses), "SAT CNF statistics mismatch")

    lower = record["lower_bound"]
    require(lower["bound"] == minimum - 1, "wrong lower-bound threshold")
    proof_report = {"proof_node_visits": 0, "conflict_leaves": 0}
    if minimum == 0:
        require(lower["proof"] is None and lower["cnf"] is None, "spurious proof below zero products")
    else:
        require(isinstance(lower["proof"], dict) and isinstance(lower["cnf"], dict), "missing lower-bound proof")
        formula = plane_formula(domain, width, outputs, legal, minimum - 1)
        require(
            lower["cnf"]
            == {
                "bound": minimum - 1,
                "variables": formula.variables,
                "clauses": len(formula.clauses),
            },
            "lower-bound CNF statistics mismatch",
        )
        proof_report = BranchProofChecker(formula, lower["proof"]).check()
    return {
        "minimum_products": minimum,
        "connections": connections,
        "table": table,
        **proof_report,
    }


def semantic_relation(spec: dict, encoder: tuple[int, ...], bound: int) -> tuple[tuple[int, ...], ...]:
    q, n, k = spec["q"], spec["n"], spec["k"]
    channel = words(q, n)
    pins = {row: message for message, row in enumerate(encoder)}
    answer = []
    for received, value in enumerate(channel):
        sources = [
            message
            for message, code_index in enumerate(encoder)
            if sum(a != b for a, b in zip(channel[code_index], value)) <= spec["radius"]
        ]
        answer.append(
            tuple(
                output
                for output in range(1 << k)
                if all((source ^ output).bit_count() <= bound for source in sources)
                and (received not in pins or pins[received] == output)
            )
        )
    return tuple(answer)


def check_obstruction(spec: dict, encoder: tuple[int, ...], bound: int, obstruction: dict) -> None:
    q, n, k = spec["q"], spec["n"], spec["k"]
    channel = words(q, n)
    received = obstruction.get("received_row")
    require(type(received) is int and 0 <= received < len(channel), "bad obstruction row")
    sources = [
        message
        for message, code_index in enumerate(encoder)
        if sum(a != b for a, b in zip(channel[code_index], channel[received])) <= spec["radius"]
    ]
    core = obstruction.get("source_messages")
    require(isinstance(core, list) and core and len(core) == len(set(core)) and set(core) <= set(sources), "bad obstruction core")
    pins = {row: message for message, row in enumerate(encoder)}
    if obstruction.get("kind") == "pin":
        require(received in pins and len(core) == 1, "invalid pin obstruction")
        pinned = pins[received]
        require(obstruction.get("pinned_message") == pinned, "wrong pinned message")
        require((core[0] ^ pinned).bit_count() > bound, "pin core does not conflict")
        return
    require(obstruction.get("kind") == "empty_intersection" and received not in pins, "unknown obstruction kind")
    require(
        not any(all((source ^ output).bit_count() <= bound for source in core) for output in range(1 << k)),
        "source-ball core is not empty",
    )
    for omitted in core:
        require(
            any(
                all((source ^ output).bit_count() <= bound for source in core if source != omitted)
                for output in range(1 << k)
            ),
            "source core is not deletion-minimal",
        )


def relation_name(rows: tuple[tuple[int, ...], ...]) -> str:
    return ";".join(",".join(str(v) for v in row) for row in rows)


def table_name(table: tuple[int, ...]) -> str:
    return ",".join(str(v) for v in table)


def actual_error(spec: dict, encoder: tuple[int, ...], decoder: tuple[int, ...]) -> int:
    channel = words(spec["q"], spec["n"])
    return max(
        (message ^ decoder[received]).bit_count()
        for message, code_index in enumerate(encoder)
        for received, value in enumerate(channel)
        if sum(a != b for a, b in zip(channel[code_index], value)) <= spec["radius"]
    )


def verify_case(certificate: dict, spec: dict, exhaustive: dict) -> dict:
    require(certificate.get("format") == "proof-carrying-frontier-v1", "wrong certificate format")
    require(certificate.get("case") == spec, "case specification mismatch")
    q, n, k = spec["q"], spec["n"], spec["k"]
    channel = words(q, n)
    width = n if q == 2 else 2 * n
    encoder_domain = tuple(range(1 << k))
    decoder_domain = tuple(raw(word, q) for word in channel)

    encoder_checked: dict[str, dict] = {}
    for key, plane in certificate["encoder_planes"].items():
        report = verify_plane(plane)
        require(tuple(plane["domain"]) == encoder_domain and plane["width"] == k and plane["outputs"] == width, "wrong encoder plane domain")
        singleton_table = tuple(row[0] for row in plane["legal_outputs"])
        require(all(len(row) == 1 for row in plane["legal_outputs"]), "encoder relation is not functional")
        require(key == table_name(singleton_table) and report["table"] == singleton_table, "encoder plane key/table mismatch")
        encoder_checked[key] = report

    decoder_checked: dict[str, dict] = {}
    for key, plane in certificate["decoder_planes"].items():
        report = verify_plane(plane)
        rows = tuple(tuple(row) for row in plane["legal_outputs"])
        require(tuple(plane["domain"]) == decoder_domain and plane["width"] == width and plane["outputs"] == k, "wrong decoder plane domain")
        require(key == relation_name(rows), "decoder relation key mismatch")
        decoder_checked[key] = report

    allowed_index = {"".join(map(str, word)): row for row, word in enumerate(channel)}
    allowed = tuple(allowed_index[word] for word in spec["allowed"])
    expected = set(it.permutations(allowed, 1 << k))
    seen: set[tuple[int, ...]] = set()
    best: list[dict | None] = [None] * (k + 1)
    semantic_rejections = 0
    relation_references = 0

    for mapping in certificate["mappings"]:
        encoder = tuple(mapping["encoder_rows"])
        require(encoder in expected and encoder not in seen, "missing, duplicate, or extraneous encoder mapping")
        seen.add(encoder)
        expected_table = tuple(raw(channel[row], q) for row in encoder)
        ekey = table_name(expected_table)
        require(mapping["encoder_plane"] == ekey and ekey in encoder_checked, "wrong encoder plane reference")
        require(len(mapping["bounds"]) == k + 1, "missing error bound record")
        encoder_report = encoder_checked[ekey]
        for bound, item in enumerate(mapping["bounds"]):
            require(item.get("error_bound") == bound, "bound order mismatch")
            rows = semantic_relation(spec, encoder, bound)
            empty = any(not row for row in rows)
            if empty:
                require(set(item) == {"error_bound", "semantic_obstruction"}, "infeasible profile carries circuit data")
                check_obstruction(spec, encoder, bound, item["semantic_obstruction"])
                semantic_rejections += 1
                continue
            require("semantic_obstruction" not in item, "feasible profile has semantic obstruction")
            dkey = relation_name(rows)
            require(item.get("decoder_plane") == dkey and dkey in decoder_checked, "wrong decoder relation reference")
            decoder_report = decoder_checked[dkey]
            minimum_gates = encoder_report["minimum_products"] + decoder_report["minimum_products"] + width + k
            connections = encoder_report["connections"] + decoder_report["connections"]
            require(item.get("minimum_gates") == minimum_gates, "profile cost mismatch")
            relation_references += 1
            if minimum_gates > spec["gate_cap"]:
                require(item.get("over_gate_cap") is True, "missing gate-cap rejection")
                continue
            require(set(item) == {"error_bound", "decoder_plane", "minimum_gates", "connections"}, "unexpected feasible-profile fields")
            require(item["connections"] == connections <= spec["connection_cap"], "connection-cap relaxation is not closed")
            candidate = {
                "error_bound": bound,
                "gates": minimum_gates,
                "connections": connections,
                "encoder_rows": list(encoder),
                "encoder_plane": ekey,
                "decoder_plane": dkey,
            }
            if best[bound] is None or minimum_gates < best[bound]["gates"]:
                best[bound] = candidate

    require(seen == expected, "certificate does not cover all injective encoders")
    profile = [None if item is None else item["gates"] for item in best]
    require(certificate["best_cost_by_error_bound"] == profile, "reported profile mismatch")
    require(profile == exhaustive["best_cost_by_error_bound"], "proof profile disagrees with exhaustive replay")
    expected_frontier = []
    prior = None
    for item in best:
        if item is not None and (prior is None or item["gates"] < prior):
            expected_frontier.append(item)
            prior = item["gates"]
    require(certificate["frontier"] == expected_frontier, "frontier witness list mismatch")
    require(
        [(point["error_bound"], point["gates"]) for point in expected_frontier]
        == [(point["error"], point["gates"]) for point in exhaustive["frontier"]],
        "proof frontier disagrees with original finite result",
    )
    for point in expected_frontier:
        encoder = tuple(point["encoder_rows"])
        encoder_table = encoder_checked[point["encoder_plane"]]["table"]
        require(encoder_table == tuple(raw(channel[row], q) for row in encoder), "frontier encoder circuit mismatch")
        decoder_table = decoder_checked[point["decoder_plane"]]["table"]
        require(all(decoder_table[row] == message for message, row in enumerate(encoder)), "frontier decoder is not inverse")
        require(actual_error(spec, encoder, decoder_table) == point["error_bound"], "frontier witness has wrong exact error")

    counts = certificate["counts"]
    require(counts["encoders"] == len(expected), "encoder count metadata mismatch")
    require(counts["encoder_plane_certificates"] == len(encoder_checked), "encoder certificate count mismatch")
    require(counts["decoder_relation_certificates"] == len(decoder_checked), "decoder certificate count mismatch")
    proof_visits = sum(r["proof_node_visits"] for r in encoder_checked.values()) + sum(r["proof_node_visits"] for r in decoder_checked.values())
    proof_leaves = sum(r["conflict_leaves"] for r in encoder_checked.values()) + sum(r["conflict_leaves"] for r in decoder_checked.values())
    require(counts["stored_proof_tree_records"] == sum(
        len(plane["lower_bound"]["proof"]["nodes"])
        for collection in (certificate["encoder_planes"], certificate["decoder_planes"])
        for plane in collection.values()
        if plane["lower_bound"]["proof"] is not None
    ), "stored proof-tree count mismatch")
    return {
        "case": spec["id"],
        "accepted": True,
        "encoders": len(expected),
        "semantic_rejections": semantic_rejections,
        "relation_references": relation_references,
        "encoder_plane_certificates": len(encoder_checked),
        "decoder_relation_certificates": len(decoder_checked),
        "proof_node_visits": proof_visits,
        "conflict_leaf_visits": proof_leaves,
        "frontier": [(point["error_bound"], point["gates"]) for point in expected_frontier],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", required=True)
    parser.add_argument("--inputs", type=Path, default=Path("inputs/cases.json"))
    parser.add_argument("--proof-dir", type=Path, default=Path("results/proof-frontiers"))
    parser.add_argument("--results", type=Path, default=Path("results"))
    args = parser.parse_args()
    signal.alarm(600)
    resource.setrlimit(resource.RLIMIT_AS, (3 * 1024**3, 3 * 1024**3))
    started_wall = time.perf_counter()
    started_cpu = time.process_time()
    specs = json.loads(args.inputs.read_text())
    spec = next((item for item in specs if item["id"] == args.case), None)
    if spec is None:
        raise ValueError("unknown case")
    certificate = json.loads((args.proof_dir / f"{args.case}.json").read_text())
    exhaustive = json.loads((args.results / f"{args.case}.json").read_text())
    report = verify_case(certificate, spec, exhaustive)
    report.update(
        {
            "cpu_seconds": time.process_time() - started_cpu,
            "wall_seconds": time.perf_counter() - started_wall,
            "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        }
    )
    output = args.proof_dir / f"{args.case}-check.json"
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
