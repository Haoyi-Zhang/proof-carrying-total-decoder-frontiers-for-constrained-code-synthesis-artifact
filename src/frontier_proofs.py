"""Proof-carrying exact frontiers for the locked finite code grammar.

The producer enumerates every allowed injective encoder.  For a fixed encoder
and error bound it projects total-decoder semantics to one finite set of legal
messages per received row.  Encoder and decoder planes are then synthesized
with a deterministic CNF encoding of the shared-product SOP grammar.

For every minimum plane cost the output contains:
  * an explicit attaining circuit; and
  * a DPLL branch certificate for infeasibility with one fewer product.

A branch certificate is a tree whose leaves must be unit-propagation conflicts.
It is intentionally simpler than DRAT/VeriPB and is checked by a separately
implemented program.  The certificate proves only the exact finite CNF emitted
for this grammar; it is not a proof-assistant theorem or a general SAT claim.
"""
from __future__ import annotations

import argparse
import itertools as it
import json
import resource
import signal
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


# ---------- finite domains ----------

def channel_words(q: int, n: int) -> list[tuple[int, ...]]:
    return list(it.product(range(q), repeat=n))


def raw_word(word: tuple[int, ...], q: int) -> int:
    value = 0
    for symbol in word:
        value = (value << (1 if q == 2 else 2)) | (
            symbol if q == 2 else (0, 1, 3)[symbol]
        )
    return value


def cube_patterns(width: int, domain: tuple[int, ...]) -> list[tuple[str, tuple[int, ...]]]:
    patterns: list[tuple[str, tuple[int, ...]]] = []
    for digits in it.product((-1, 0, 1), repeat=width):
        rows = tuple(
            row
            for row, value in enumerate(domain)
            if all(
                digit == -1 or digit == ((value >> (width - 1 - j)) & 1)
                for j, digit in enumerate(digits)
            )
        )
        if rows:
            patterns.append(("".join("*" if d == -1 else str(d) for d in digits), rows))
    return patterns


# ---------- deterministic CNF ----------

class CNF:
    def __init__(self) -> None:
        self.variable_count = 0
        self.clauses: list[tuple[int, ...]] = []
        self.names: dict[str, int] = {}
        self.application_variables: list[int] = []

    def variable(self, name: str, *, application: bool = True) -> int:
        old = self.names.get(name)
        if old is not None:
            return old
        self.variable_count += 1
        value = self.variable_count
        self.names[name] = value
        if application:
            self.application_variables.append(value)
        return value

    def auxiliary(self, name: str) -> int:
        return self.variable(name, application=False)

    def add(self, *literals: int) -> None:
        values = set(literals)
        if any(-literal in values for literal in values):
            return
        self.clauses.append(tuple(sorted(values, key=lambda x: (abs(x), x < 0))))

    def at_most(self, variables: list[int], limit: int, prefix: str) -> None:
        """Sinz sequential encoding of sum(variables) <= limit."""
        count = len(variables)
        if limit < 0:
            self.add()
            return
        if limit >= count:
            return
        if limit == 0:
            for variable in variables:
                self.add(-variable)
            return
        sequential: dict[tuple[int, int], int] = {}
        for i in range(1, count):
            for j in range(1, limit + 1):
                sequential[i, j] = self.auxiliary(f"{prefix}[{i},{j}]")
        self.add(-variables[0], sequential[1, 1])
        for j in range(2, limit + 1):
            self.add(-sequential[1, j])
        for i in range(2, count):
            self.add(-variables[i - 1], sequential[i, 1])
            self.add(-sequential[i - 1, 1], sequential[i, 1])
            for j in range(2, limit + 1):
                self.add(-variables[i - 1], -sequential[i - 1, j - 1], sequential[i, j])
                self.add(-sequential[i - 1, j], sequential[i, j])
            self.add(-variables[i - 1], -sequential[i - 1, limit])
        self.add(-variables[count - 1], -sequential[count - 1, limit])


@dataclass(frozen=True)
class PlaneEncoding:
    cnf: CNF
    cubes: tuple[tuple[str, tuple[int, ...]], ...]
    selected: tuple[int, ...]
    connected: tuple[tuple[int, ...], ...]
    outputs: tuple[tuple[int, ...], ...]
    preferred: tuple[int, ...]


def build_plane_cnf(
    domain: tuple[int, ...],
    width: int,
    output_count: int,
    legal_outputs: tuple[tuple[int, ...], ...],
    product_bound: int,
) -> PlaneEncoding:
    return _build_plane_cnf(domain, output_count, legal_outputs, product_bound,
                            _plane_cubes(domain, width, legal_outputs))


def _plane_cubes(domain, width, legal_outputs):
    """Validate before incidence construction, retaining public error ordering."""
    if len(domain) != len(legal_outputs):
        raise ValueError("row count mismatch")
    if any(not row for row in legal_outputs):
        raise ValueError("empty semantic row must use a semantic obstruction")
    return tuple(cube_patterns(width, domain))


def _build_plane_cnf(domain, output_count, legal_outputs, product_bound, cubes):
    """Fresh encoding at each bound; only immutable ordered incidence is reused."""
    formula = CNF()
    selected = tuple(formula.variable(f"s[{c}]") for c in range(len(cubes)))
    connected = tuple(
        tuple(formula.variable(f"t[{c},{j}]") for j in range(output_count))
        for c in range(len(cubes))
    )
    outputs = tuple(
        tuple(formula.variable(f"d[{row},{j}]") for j in range(output_count))
        for row in range(len(domain))
    )

    for c in range(len(cubes)):
        for j in range(output_count):
            formula.add(-connected[c][j], selected[c])
        formula.add(-selected[c], *connected[c])

    matching_by_row: list[list[int]] = [[] for _ in domain]
    for c, (_, rows) in enumerate(cubes):
        for row in rows:
            matching_by_row[row].append(c)
        for j in range(output_count):
            for row in rows:
                formula.add(-connected[c][j], outputs[row][j])

    for row in range(len(domain)):
        for j in range(output_count):
            formula.add(
                -outputs[row][j],
                *(connected[c][j] for c in matching_by_row[row]),
            )
        allowed = set(legal_outputs[row])
        for value in range(1 << output_count):
            if value in allowed:
                continue
            formula.add(
                *(
                    outputs[row][j]
                    if ((value >> (output_count - 1 - j)) & 1) == 0
                    else -outputs[row][j]
                    for j in range(output_count)
                )
            )

    formula.at_most(list(selected), product_bound, "product")
    preferred = selected + tuple(v for row in connected for v in row) + tuple(
        v for row in outputs for v in row
    )
    return PlaneEncoding(formula, cubes, selected, connected, outputs, preferred)


# ---------- deterministic DPLL and branch proof ----------

class BranchDPLL:
    """A small deterministic solver that emits a unit-conflict branch tree."""

    def __init__(
        self,
        encoding: PlaneEncoding,
        *,
        time_limit_seconds: float = 600.0,
        node_limit: int = 20_000_000,
    ) -> None:
        self.encoding = encoding
        self.formula = encoding.cnf
        self.clauses = [tuple(c) for c in self.formula.clauses]
        self.assignment = [0] * (self.formula.variable_count + 1)
        self.trail: list[int] = []
        self.nodes = 0
        self.leaves = 0
        self.started = time.perf_counter()
        self.time_limit_seconds = time_limit_seconds
        self.node_limit = node_limit
        self.occurrences = [0] * (self.formula.variable_count + 1)
        for clause in self.clauses:
            for literal in clause:
                self.occurrences[abs(literal)] += 1
        self.nodes_out: list[list[int]] = [[0]]  # shared conflict leaf

    def literal_value(self, literal: int) -> int:
        value = self.assignment[abs(literal)]
        return value if literal > 0 else -value

    def assign(self, literal: int) -> bool:
        variable = abs(literal)
        value = 1 if literal > 0 else -1
        if self.assignment[variable] == 0:
            self.assignment[variable] = value
            self.trail.append(variable)
            return True
        return self.assignment[variable] == value

    def backtrack(self, mark: int) -> None:
        while len(self.trail) > mark:
            self.assignment[self.trail.pop()] = 0

    def propagate(self) -> bool:
        changed = True
        while changed:
            changed = False
            for clause in self.clauses:
                satisfied = False
                unit = 0
                unassigned = 0
                for literal in clause:
                    value = self.literal_value(literal)
                    if value > 0:
                        satisfied = True
                        break
                    if value == 0:
                        unit = literal
                        unassigned += 1
                if satisfied:
                    continue
                if unassigned == 0:
                    return False
                if unassigned == 1:
                    if not self.assign(unit):
                        return False
                    changed = True
        return True

    def all_clauses_satisfied(self) -> bool:
        return all(any(self.literal_value(literal) > 0 for literal in clause) for clause in self.clauses)

    def choose_variable(self) -> int:
        shortest: list[int] | None = None
        for clause in self.clauses:
            if any(self.literal_value(literal) > 0 for literal in clause):
                continue
            candidates = [abs(literal) for literal in clause if self.literal_value(literal) == 0]
            if candidates and (shortest is None or len(candidates) < len(shortest)):
                shortest = candidates
                if len(shortest) == 2:
                    break
        if not shortest:
            raise RuntimeError("no branch variable in an unsatisfied formula")
        candidate_set = set(shortest)
        preferred = [
            variable
            for variable in self.encoding.preferred
            if variable in candidate_set and self.assignment[variable] == 0
        ]
        pool = preferred or shortest
        return max(pool, key=lambda variable: self.occurrences[variable])

    def recurse(self) -> tuple[bool, list[int] | None, int | None]:
        self.nodes += 1
        if self.nodes % 4096 == 0:
            if self.nodes > self.node_limit:
                raise RuntimeError("DPLL node limit exceeded")
            if time.perf_counter() - self.started > self.time_limit_seconds:
                raise TimeoutError("DPLL proof generation timed out")
        mark = len(self.trail)
        if not self.propagate():
            self.leaves += 1
            self.backtrack(mark)
            return False, None, 0
        if self.all_clauses_satisfied():
            model = self.assignment.copy()
            self.backtrack(mark)
            return True, model, None

        variable = self.choose_variable()
        children: list[int] = []
        for literal in (-variable, variable):
            child_mark = len(self.trail)
            if not self.assign(literal):
                sat, model, root = False, None, 0
            else:
                sat, model, root = self.recurse()
            self.backtrack(child_mark)
            if sat:
                self.backtrack(mark)
                return True, model, None
            assert root is not None
            children.append(root)
        proof_node = len(self.nodes_out)
        self.nodes_out.append([variable, children[0], children[1]])
        self.backtrack(mark)
        return False, None, proof_node

    def solve(self) -> tuple[bool, list[int] | None, dict | None]:
        satisfiable, model, root = self.recurse()
        if satisfiable:
            return True, model, None
        assert root is not None
        proof = {
            "format": "unit-conflict-dpll-v1",
            "root": root,
            "nodes": self.nodes_out,
            "search_nodes": self.nodes,
            "conflict_leaves": self.leaves,
        }
        return False, None, proof


def model_circuit(encoding: PlaneEncoding, model: list[int]) -> tuple[list[dict], int]:
    terms: list[dict] = []
    connections = 0
    for c, (cube, _) in enumerate(encoding.cubes):
        if model[encoding.selected[c]] <= 0:
            continue
        mask = 0
        for j, variable in enumerate(encoding.connected[c]):
            if model[variable] > 0:
                mask |= 1 << (len(encoding.connected[c]) - 1 - j)
        if mask == 0:
            raise RuntimeError("selected product has no output connection")
        terms.append({"cube": cube, "outputs": mask})
        connections += mask.bit_count()
    return terms, connections


def solve_plane(
    domain: tuple[int, ...],
    width: int,
    output_count: int,
    legal_outputs: tuple[tuple[int, ...], ...],
    maximum_products: int,
) -> dict:
    begin = time.perf_counter()
    lower_proof = None
    lower_stats = None
    attempts: list[dict] = []
    cubes = None
    for bound in range(maximum_products + 1):
        if cubes is None:
            cubes = _plane_cubes(domain, width, legal_outputs)
        encoding = _build_plane_cnf(domain, output_count, legal_outputs, bound, cubes)
        solver = BranchDPLL(encoding)
        satisfiable, model, proof = solver.solve()
        attempts.append(
            {
                "bound": bound,
                "satisfiable": satisfiable,
                "variables": encoding.cnf.variable_count,
                "clauses": len(encoding.cnf.clauses),
                "search_nodes": solver.nodes,
                "wall_seconds": time.perf_counter() - solver.started,
            }
        )
        if satisfiable:
            assert model is not None
            terms, connections = model_circuit(encoding, model)
            if len(terms) > bound:
                raise RuntimeError("SAT model violates product bound")
            return {
                "minimum_products": len(terms),
                "terms": terms,
                "connections": connections,
                "lower_bound": {
                    "bound": bound - 1,
                    "proof": lower_proof,
                    "cnf": lower_stats,
                },
                "sat_cnf": {
                    "bound": bound,
                    "variables": encoding.cnf.variable_count,
                    "clauses": len(encoding.cnf.clauses),
                },
                "attempts": attempts,
                "generation_wall_seconds": time.perf_counter() - begin,
            }
        lower_proof = proof
        lower_stats = {
            "bound": bound,
            "variables": encoding.cnf.variable_count,
            "clauses": len(encoding.cnf.clauses),
        }
    raise RuntimeError("no circuit within the configured product ceiling")


# ---------- semantic projection and complete cases ----------

def semantic_rows(spec: dict, encoder: tuple[int, ...], bound: int) -> tuple[tuple[int, ...], ...]:
    q, n, k = spec["q"], spec["n"], spec["k"]
    words = channel_words(q, n)
    pins = {row: message for message, row in enumerate(encoder)}
    rows: list[tuple[int, ...]] = []
    for received, y in enumerate(words):
        sources = [
            message
            for message, code_index in enumerate(encoder)
            if sum(a != b for a, b in zip(words[code_index], y)) <= spec["radius"]
        ]
        legal = [
            output
            for output in range(1 << k)
            if all((source ^ output).bit_count() <= bound for source in sources)
            and (received not in pins or output == pins[received])
        ]
        rows.append(tuple(legal))
    return tuple(rows)


def semantic_obstruction(spec: dict, encoder: tuple[int, ...], bound: int) -> dict | None:
    q, n, k = spec["q"], spec["n"], spec["k"]
    words = channel_words(q, n)
    pins = {row: message for message, row in enumerate(encoder)}
    for received, y in enumerate(words):
        sources = [
            message
            for message, code_index in enumerate(encoder)
            if sum(a != b for a, b in zip(words[code_index], y)) <= spec["radius"]
        ]
        legal = [
            output
            for output in range(1 << k)
            if all((source ^ output).bit_count() <= bound for source in sources)
            and (received not in pins or output == pins[received])
        ]
        if legal:
            continue
        if received in pins:
            pinned = pins[received]
            source = next(s for s in sources if (s ^ pinned).bit_count() > bound)
            return {
                "kind": "pin",
                "received_row": received,
                "source_messages": [source],
                "pinned_message": pinned,
            }
        core = list(sources)
        for source in list(sources):
            smaller = [candidate for candidate in core if candidate != source]
            if not any(
                all((candidate ^ output).bit_count() <= bound for candidate in smaller)
                for output in range(1 << k)
            ):
                core = smaller
        return {
            "kind": "empty_intersection",
            "received_row": received,
            "source_messages": core,
        }
    return None


def relation_key(rows: tuple[tuple[int, ...], ...]) -> str:
    return ";".join(",".join(str(v) for v in row) for row in rows)


def table_key(table: tuple[int, ...]) -> str:
    return ",".join(str(v) for v in table)


def verify_circuit_locally(
    domain: tuple[int, ...], width: int, output_count: int, terms: list[dict]
) -> tuple[int, ...]:
    table: list[int] = []
    for value in domain:
        bits = format(value, f"0{width}b")
        output = 0
        for term in terms:
            cube = term["cube"]
            if len(cube) != width or set(cube) - set("01*"):
                raise RuntimeError("invalid generated cube")
            if all(c == "*" or c == b for c, b in zip(cube, bits)):
                output |= term["outputs"]
        if output >= 1 << output_count:
            raise RuntimeError("generated output out of range")
        table.append(output)
    return tuple(table)


def generate_case(spec: dict) -> dict:
    begin_wall = time.perf_counter()
    begin_cpu = time.process_time()
    q, n, k = spec["q"], spec["n"], spec["k"]
    words = channel_words(q, n)
    word_index = {"".join(map(str, word)): i for i, word in enumerate(words)}
    allowed = tuple(word_index[word] for word in spec["allowed"])
    message_count = 1 << k
    width = n if q == 2 else 2 * n
    encoder_domain = tuple(range(message_count))
    decoder_domain = tuple(raw_word(word, q) for word in words)

    encoder_planes: dict[str, dict] = {}
    decoder_planes: dict[str, dict] = {}
    mappings: list[dict] = []
    best: list[dict | None] = [None] * (k + 1)

    for encoder in it.permutations(allowed, message_count):
        encoder = tuple(encoder)
        encoder_table = tuple(raw_word(words[row], q) for row in encoder)
        ekey = table_key(encoder_table)
        if ekey not in encoder_planes:
            legal = tuple((value,) for value in encoder_table)
            record = solve_plane(encoder_domain, k, width, legal, spec["gate_cap"])
            if verify_circuit_locally(encoder_domain, k, width, record["terms"]) != encoder_table:
                raise RuntimeError("generated encoder circuit mismatch")
            record.update(
                {
                    "domain": list(encoder_domain),
                    "width": k,
                    "outputs": width,
                    "legal_outputs": [list(row) for row in legal],
                }
            )
            encoder_planes[ekey] = record
        mapping_record = {"encoder_rows": list(encoder), "encoder_plane": ekey, "bounds": []}
        encoder_record = encoder_planes[ekey]
        for bound in range(k + 1):
            rows = semantic_rows(spec, encoder, bound)
            obstruction = semantic_obstruction(spec, encoder, bound)
            if obstruction is not None:
                mapping_record["bounds"].append(
                    {"error_bound": bound, "semantic_obstruction": obstruction}
                )
                continue
            dkey = relation_key(rows)
            if dkey not in decoder_planes:
                record = solve_plane(decoder_domain, width, k, rows, spec["gate_cap"])
                produced = verify_circuit_locally(decoder_domain, width, k, record["terms"])
                if any(produced[row] not in set(rows[row]) for row in range(len(rows))):
                    raise RuntimeError("generated decoder violates row relation")
                record.update(
                    {
                        "domain": list(decoder_domain),
                        "width": width,
                        "outputs": k,
                        "legal_outputs": [list(row) for row in rows],
                    }
                )
                decoder_planes[dkey] = record
            decoder_record = decoder_planes[dkey]
            fixed = width + k
            gates = (
                encoder_record["minimum_products"]
                + decoder_record["minimum_products"]
                + fixed
            )
            connections = encoder_record["connections"] + decoder_record["connections"]
            if connections > spec["connection_cap"]:
                raise RuntimeError("minimum-product witness does not close the connection-cap relaxation")
            if gates > spec["gate_cap"]:
                mapping_record["bounds"].append(
                    {
                        "error_bound": bound,
                        "decoder_plane": dkey,
                        "minimum_gates": gates,
                        "over_gate_cap": True,
                    }
                )
                continue
            candidate = {
                "error_bound": bound,
                "gates": gates,
                "connections": connections,
                "encoder_rows": list(encoder),
                "encoder_plane": ekey,
                "decoder_plane": dkey,
            }
            mapping_record["bounds"].append(
                {
                    "error_bound": bound,
                    "decoder_plane": dkey,
                    "minimum_gates": gates,
                    "connections": connections,
                }
            )
            if best[bound] is None or gates < best[bound]["gates"]:
                best[bound] = candidate
        mappings.append(mapping_record)

    frontier: list[dict] = []
    previous = None
    for bound, witness in enumerate(best):
        if witness is None:
            continue
        if previous is None or witness["gates"] < previous:
            frontier.append(witness)
            previous = witness["gates"]

    planes = [
        plane
        for collection in (encoder_planes, decoder_planes)
        for plane in collection.values()
    ]
    lower_bound_proof_nodes = sum(
        plane["lower_bound"]["proof"]["search_nodes"]
        for plane in planes
        if plane["lower_bound"]["proof"] is not None
    )
    satisfying_witness_nodes = sum(
        next(attempt["search_nodes"] for attempt in plane["attempts"] if attempt["satisfiable"])
        for plane in planes
    )
    earlier_unsat_nodes = sum(
        sum(attempt["search_nodes"] for attempt in plane["attempts"] if not attempt["satisfiable"])
        - (plane["lower_bound"]["proof"]["search_nodes"] if plane["lower_bound"]["proof"] is not None else 0)
        for plane in planes
    )
    all_generation_nodes = sum(
        sum(attempt["search_nodes"] for attempt in plane["attempts"])
        for plane in planes
    )
    if all_generation_nodes != lower_bound_proof_nodes + satisfying_witness_nodes + earlier_unsat_nodes:
        raise RuntimeError("DPLL search-node accounting mismatch")
    proof_tree_records = sum(
        len(plane["lower_bound"]["proof"]["nodes"])
        for plane in planes
        if plane["lower_bound"]["proof"] is not None
    )
    return {
        "format": "proof-carrying-frontier-v1",
        "case": spec,
        "encoder_planes": encoder_planes,
        "decoder_planes": decoder_planes,
        "mappings": mappings,
        "best_cost_by_error_bound": [None if item is None else item["gates"] for item in best],
        "frontier": frontier,
        "counts": {
            "encoders": len(mappings),
            "encoder_plane_certificates": len(encoder_planes),
            "decoder_relation_certificates": len(decoder_planes),
            "lower_bound_proof_search_nodes": lower_bound_proof_nodes,
            "satisfying_witness_search_nodes": satisfying_witness_nodes,
            "earlier_unsat_search_nodes": earlier_unsat_nodes,
            "all_generation_search_nodes": all_generation_nodes,
            "stored_proof_tree_records": proof_tree_records,
        },
        "cpu_seconds": time.process_time() - begin_cpu,
        "wall_seconds": time.perf_counter() - begin_wall,
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", required=True)
    parser.add_argument("--inputs", type=Path, default=Path("inputs/cases.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("results/proof-frontiers"))
    args = parser.parse_args()
    signal.alarm(600)
    resource.setrlimit(resource.RLIMIT_AS, (3 * 1024**3, 3 * 1024**3))
    specs = json.loads(args.inputs.read_text())
    spec = next((item for item in specs if item["id"] == args.case), None)
    if spec is None:
        raise ValueError("unknown case")
    result = generate_case(spec)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    path = args.output_dir / f"{args.case}.json"
    path.write_text(json.dumps(result, separators=(",", ":")) + "\n")
    print(
        json.dumps(
            {
                "case": args.case,
                "frontier": [(point["error_bound"], point["gates"]) for point in result["frontier"]],
                **result["counts"],
                "cpu_seconds": result["cpu_seconds"],
                "wall_seconds": result["wall_seconds"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
