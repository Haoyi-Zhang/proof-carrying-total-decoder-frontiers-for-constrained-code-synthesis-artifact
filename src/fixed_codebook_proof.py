"""Proof-carrying frontier for fixed codebooks beyond explicit decoder enumeration.

For each fixed encoder this producer computes the total-decoder row relation at
each error bound.  An attaining SOP circuit is supplied as a deterministic input
and checked.  Minimality is certified by a forced-cell packing: every selected
cell is forced to one by the row relation, and no legal product can cover two
selected cells without also asserting a forced-zero cell.  Therefore any SOP
needs at least one product per selected cell.  The checker independently
enumerates all cubes and validates that argument.
"""
from __future__ import annotations

import argparse
import itertools as it
import json
import resource
import signal
import time
from pathlib import Path

from frontier_proofs import channel_words, raw_word, semantic_obstruction, semantic_rows


def cube_patterns(width: int, domain: tuple[int, ...]) -> list[tuple[str, tuple[int, ...]]]:
    """Keep row indices as labels, but match cubes against Boolean values."""
    out: list[tuple[str, tuple[int, ...]]] = []
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
            out.append(("".join("*" if d == -1 else str(d) for d in digits), rows))
    return out


def evaluate_terms(domain: tuple[int, ...], width: int, outputs: int, terms: list[dict]) -> tuple[int, ...]:
    table: list[int] = []
    for value in domain:
        bits = format(value, f"0{width}b")
        result = 0
        for term in terms:
            cube = term["cube"]
            mask = int(term["outputs"])
            if len(cube) != width or set(cube) - set("01*"):
                raise ValueError("invalid cube")
            if mask <= 0 or mask >= 1 << outputs:
                raise ValueError("invalid output mask")
            if all(c == "*" or c == b for c, b in zip(cube, bits)):
                result |= mask
        table.append(result)
    return tuple(table)


def forced_cells(legal: tuple[tuple[int, ...], ...], outputs: int) -> tuple[tuple[tuple[int, int], ...], tuple[tuple[int, int], ...]]:
    ones: list[tuple[int, int]] = []
    zeros: list[tuple[int, int]] = []
    for row, allowed in enumerate(legal):
        if not allowed:
            raise ValueError("empty row has no forced-bit certificate")
        for output in range(outputs):
            bit = 1 << (outputs - 1 - output)
            values = [bool(value & bit) for value in allowed]
            if all(values):
                ones.append((row, output))
            if not any(values):
                zeros.append((row, output))
    return tuple(ones), tuple(zeros)


def can_share_product(
    left: tuple[int, int],
    right: tuple[int, int],
    cubes: list[tuple[str, tuple[int, ...]]],
    forced_zero: set[tuple[int, int]],
) -> bool:
    lr, lo = left
    rr, ro = right
    for _, rows in cubes:
        if lr not in rows or rr not in rows:
            continue
        if any((row, lo) in forced_zero for row in rows):
            continue
        if any((row, ro) in forced_zero for row in rows):
            continue
        return True
    return False


def maximum_packing(
    forced_one: tuple[tuple[int, int], ...],
    forced_zero: tuple[tuple[int, int], ...],
    cubes: list[tuple[str, tuple[int, ...]]],
) -> tuple[tuple[int, int], ...]:
    """Maximum clique in the graph of pairwise product-incompatible cells."""
    vertices = list(forced_one)
    zero = set(forced_zero)
    incompatible: dict[tuple[int, int], set[tuple[int, int]]] = {v: set() for v in vertices}
    for i, left in enumerate(vertices):
        for right in vertices[i + 1 :]:
            if not can_share_product(left, right, cubes, zero):
                incompatible[left].add(right)
                incompatible[right].add(left)

    best: tuple[tuple[int, int], ...] = ()

    def expand(chosen: tuple[tuple[int, int], ...], candidates: tuple[tuple[int, int], ...]) -> None:
        nonlocal best
        if len(chosen) + len(candidates) <= len(best):
            return
        if not candidates:
            if len(chosen) > len(best):
                best = chosen
            return
        ordered = sorted(candidates, key=lambda v: (-len(incompatible[v] & set(candidates)), v))
        while ordered:
            if len(chosen) + len(ordered) <= len(best):
                return
            vertex = ordered.pop(0)
            next_candidates = tuple(v for v in ordered if v in incompatible[vertex])
            expand(chosen + (vertex,), next_candidates)
        if len(chosen) > len(best):
            best = chosen

    expand((), tuple(vertices))
    return tuple(sorted(best))


def plane_certificate(
    domain: tuple[int, ...],
    width: int,
    outputs: int,
    legal: tuple[tuple[int, ...], ...],
    terms: list[dict],
) -> dict:
    produced = evaluate_terms(domain, width, outputs, terms)
    if any(produced[row] not in set(legal[row]) for row in range(len(domain))):
        raise ValueError("attaining circuit violates the row relation")
    ones, zeros = forced_cells(legal, outputs)
    cubes = cube_patterns(width, domain)
    packing = maximum_packing(ones, zeros, cubes)
    if len(packing) != len(terms):
        raise ValueError(
            f"packing lower bound {len(packing)} does not match the {len(terms)}-product witness"
        )
    return {
        "format": "forced-cell-packing-v1",
        "domain": list(domain),
        "width": width,
        "outputs": outputs,
        "legal_outputs": [list(row) for row in legal],
        "terms": terms,
        "minimum_products": len(terms),
        "connections": sum(int(term["outputs"]).bit_count() for term in terms),
        "forced_one_cells": [list(cell) for cell in ones],
        "forced_zero_cells": [list(cell) for cell in zeros],
        "packing": [list(cell) for cell in packing],
        "cube_count_checked_by_producer": len(cubes),
    }


def generate(spec: dict) -> dict:
    started = time.perf_counter()
    cpu = time.process_time()
    q, n, k = spec["q"], spec["n"], spec["k"]
    if q != 2:
        raise ValueError("fixed-codebook packing producer currently accepts binary cases")
    words = channel_words(q, n)
    index = {"".join(map(str, word)): i for i, word in enumerate(words)}
    encoder = tuple(index[word] for word in spec["encoder"])
    if len(encoder) != 1 << k or len(set(encoder)) != len(encoder):
        raise ValueError("fixed encoder is not an injective complete-payload map")

    encoder_domain = tuple(range(1 << k))
    encoder_table = tuple(raw_word(words[row], q) for row in encoder)
    encoder_legal = tuple((value,) for value in encoder_table)
    encoder_plane = plane_certificate(
        encoder_domain,
        k,
        n,
        encoder_legal,
        list(spec["encoder_witness"]),
    )

    decoder_domain = tuple(raw_word(word, q) for word in words)
    bounds: list[dict] = []
    best: list[int | None] = [None] * (k + 1)
    witnesses: dict[int, dict] = {}
    for bound in range(k + 1):
        rows = semantic_rows(spec, encoder, bound)
        obstruction = semantic_obstruction(spec, encoder, bound)
        if obstruction is not None:
            bounds.append({"error_bound": bound, "semantic_obstruction": obstruction})
            continue
        terms = list(spec["decoder_witnesses"][str(bound)])
        decoder_plane = plane_certificate(decoder_domain, n, k, rows, terms)
        gates = encoder_plane["minimum_products"] + decoder_plane["minimum_products"] + n + k
        connections = encoder_plane["connections"] + decoder_plane["connections"]
        if gates > spec["gate_cap"] or connections > spec["connection_cap"]:
            raise ValueError("attaining fixed-codebook design violates a configured cap")
        record = {
            "error_bound": bound,
            "gates": gates,
            "connections": connections,
            "decoder_plane": decoder_plane,
        }
        bounds.append(record)
        best[bound] = gates
        witnesses[bound] = record

    frontier: list[dict] = []
    previous: int | None = None
    for bound, gates in enumerate(best):
        if gates is None:
            continue
        if previous is None or gates < previous:
            frontier.append(
                {
                    "error_bound": bound,
                    "gates": gates,
                    "connections": witnesses[bound]["connections"],
                }
            )
            previous = gates

    free_rows = len(words) - (1 << k)
    decoder_completions = (1 << k) ** free_rows
    return {
        "format": "fixed-codebook-frontier-v1",
        "case": {key: value for key, value in spec.items() if not key.endswith("_witness") and key != "decoder_witnesses"},
        "encoder_rows": list(encoder),
        "encoder_plane": encoder_plane,
        "bounds": bounds,
        "best_cost_by_error_bound": best,
        "frontier": frontier,
        "decoder_completion_count": decoder_completions,
        "decoder_completion_count_power_of_two": k * free_rows,
        "cpu_seconds": time.process_time() - cpu,
        "wall_seconds": time.perf_counter() - started,
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", required=True)
    parser.add_argument("--inputs", type=Path, default=Path("inputs/fixed-codebooks.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("results/fixed-codebook"))
    args = parser.parse_args()
    signal.alarm(600)
    resource.setrlimit(resource.RLIMIT_AS, (3 * 1024**3, 3 * 1024**3))
    specs = json.loads(args.inputs.read_text())
    spec = next((item for item in specs if item["id"] == args.case), None)
    if spec is None:
        raise ValueError("unknown fixed-codebook case")
    result = generate(spec)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / f"{args.case}.json").write_text(json.dumps(result, separators=(",", ":")) + "\n")
    print(
        json.dumps(
            {
                "case": args.case,
                "frontier": [(point["error_bound"], point["gates"]) for point in result["frontier"]],
                "decoder_completion_count_power_of_two": result["decoder_completion_count_power_of_two"],
                "cpu_seconds": result["cpu_seconds"],
                "wall_seconds": result["wall_seconds"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
