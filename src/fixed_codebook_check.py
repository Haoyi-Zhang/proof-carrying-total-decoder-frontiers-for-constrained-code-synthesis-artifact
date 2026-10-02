"""Independent checker for forced-cell fixed-codebook frontier certificates.

The checker reconstructs every plane shape and semantic row relation from the
external specification.  Certificate-carried domains, widths, output counts,
and legal row lists are treated only as claims and must match that independent
reconstruction exactly.  Both the attaining circuit and the forced-cell packing
are checked on the same reconstructed Boolean domain.
"""
from __future__ import annotations

import argparse
import itertools as it
import json
import resource
import signal
import time
from pathlib import Path


def need(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def words(q: int, n: int) -> tuple[tuple[int, ...], ...]:
    return tuple(it.product(range(q), repeat=n))


def raw(word: tuple[int, ...], q: int) -> int:
    value = 0
    for symbol in word:
        value = (value << (1 if q == 2 else 2)) | (symbol if q == 2 else (0, 1, 3)[symbol])
    return value


def wire_width(spec: dict) -> int:
    return int(spec["n"]) * (1 if int(spec["q"]) == 2 else 2)


def relation(spec: dict, encoder: tuple[int, ...], bound: int) -> tuple[tuple[int, ...], ...]:
    channel = words(spec["q"], spec["n"])
    pins = {row: message for message, row in enumerate(encoder)}
    rows: list[tuple[int, ...]] = []
    for received, y in enumerate(channel):
        sources = [
            message
            for message, code in enumerate(encoder)
            if sum(a != b for a, b in zip(channel[code], y)) <= spec["radius"]
        ]
        allowed = tuple(
            output
            for output in range(1 << spec["k"])
            if all((source ^ output).bit_count() <= bound for source in sources)
            and (received not in pins or output == pins[received])
        )
        rows.append(allowed)
    return tuple(rows)


def first_obstruction(spec: dict, encoder: tuple[int, ...], bound: int) -> dict | None:
    channel = words(spec["q"], spec["n"])
    pins = {row: message for message, row in enumerate(encoder)}
    for received, allowed in enumerate(relation(spec, encoder, bound)):
        if allowed:
            continue
        y = channel[received]
        sources = [
            message
            for message, code in enumerate(encoder)
            if sum(a != b for a, b in zip(channel[code], y)) <= spec["radius"]
        ]
        if received in pins:
            pinned = pins[received]
            bad = next(source for source in sources if (source ^ pinned).bit_count() > bound)
            return {"kind": "pin", "received_row": received, "source_messages": [bad], "pinned_message": pinned}
        core = list(sources)
        for source in list(sources):
            smaller = [candidate for candidate in core if candidate != source]
            if not any(
                all((candidate ^ output).bit_count() <= bound for candidate in smaller)
                for output in range(1 << spec["k"])
            ):
                core = smaller
        return {"kind": "empty_intersection", "received_row": received, "source_messages": core}
    return None


def cube_rows(domain: tuple[int, ...], width: int) -> tuple[tuple[str, tuple[int, ...]], ...]:
    """Enumerate cubes against the actual Boolean values in ``domain``."""
    result = []
    for digits in it.product((-1, 0, 1), repeat=width):
        matching = tuple(
            row
            for row, value in enumerate(domain)
            if all(
                digit == -1 or digit == ((value >> (width - 1 - j)) & 1)
                for j, digit in enumerate(digits)
            )
        )
        if matching:
            result.append(("".join("*" if d == -1 else str(d) for d in digits), matching))
    return tuple(result)


def eval_terms(domain: tuple[int, ...], width: int, outputs: int, terms: list[dict]) -> tuple[int, ...]:
    table = []
    for value in domain:
        need(isinstance(value, int) and 0 <= value < (1 << width), "domain value outside declared width")
        bits = format(value, f"0{width}b")
        result = 0
        for term in terms:
            cube = term.get("cube")
            mask = term.get("outputs")
            need(isinstance(cube, str) and len(cube) == width and not (set(cube) - set("01*")), "bad term cube")
            need(isinstance(mask, int) and 0 < mask < (1 << outputs), "bad term mask")
            if all(c == "*" or c == bit for c, bit in zip(cube, bits)):
                result |= mask
        table.append(result)
    return tuple(table)


def validate_relation(legal: tuple[tuple[int, ...], ...], outputs: int) -> None:
    for allowed in legal:
        need(bool(allowed), "empty row in plane certificate")
        need(len(set(allowed)) == len(allowed), "duplicate legal output value")
        need(all(isinstance(value, int) and 0 <= value < (1 << outputs) for value in allowed), "legal output outside declared width")


def expected_forced(legal: tuple[tuple[int, ...], ...], outputs: int) -> tuple[set[tuple[int, int]], set[tuple[int, int]]]:
    ones: set[tuple[int, int]] = set()
    zeros: set[tuple[int, int]] = set()
    for row, allowed in enumerate(legal):
        for output in range(outputs):
            bit = 1 << (outputs - 1 - output)
            flags = [bool(value & bit) for value in allowed]
            if all(flags):
                ones.add((row, output))
            if not any(flags):
                zeros.add((row, output))
    return ones, zeros


def check_plane(
    record: dict,
    *,
    expected_domain: tuple[int, ...],
    expected_width: int,
    expected_outputs: int,
    expected_legal: tuple[tuple[int, ...], ...],
    label: str,
) -> dict:
    """Check one plane after binding all shape and semantics to external data."""
    need(record.get("format") == "forced-cell-packing-v1", "unknown plane proof format")
    claimed_domain = tuple(record["domain"])
    claimed_width = int(record["width"])
    claimed_outputs = int(record["outputs"])
    claimed_legal = tuple(tuple(row) for row in record["legal_outputs"])

    need(claimed_domain == expected_domain, f"{label} domain mismatch")
    need(claimed_width == expected_width, f"{label} width mismatch")
    need(claimed_outputs == expected_outputs, f"{label} output-count mismatch")
    need(claimed_legal == expected_legal, f"{label} legal-output relation mismatch")
    need(len(set(expected_domain)) == len(expected_domain), f"{label} domain has duplicate Boolean values")
    need(len(expected_domain) == len(expected_legal), f"{label} row count mismatch")
    validate_relation(expected_legal, expected_outputs)

    # Upper and lower bounds are evaluated over exactly the same true domain.
    produced = eval_terms(expected_domain, expected_width, expected_outputs, record["terms"])
    need(all(produced[row] in set(expected_legal[row]) for row in range(len(expected_domain))), f"{label} attaining circuit violates relation")
    need(len(record["terms"]) == record["minimum_products"], f"{label} product count mismatch")
    need(sum(term["outputs"].bit_count() for term in record["terms"]) == record["connections"], f"{label} connection count mismatch")

    forced_one, forced_zero = expected_forced(expected_legal, expected_outputs)
    listed_one = {tuple(cell) for cell in record["forced_one_cells"]}
    listed_zero = {tuple(cell) for cell in record["forced_zero_cells"]}
    need(listed_one == forced_one, f"{label} forced-one set mismatch")
    need(listed_zero == forced_zero, f"{label} forced-zero set mismatch")
    packing_list = [tuple(cell) for cell in record["packing"]]
    packing = set(packing_list)
    need(len(packing) == len(packing_list), f"{label} packing has duplicate cells")
    need(packing <= forced_one, f"{label} packing contains a non-forced-one cell")
    need(len(packing) == record["minimum_products"], f"{label} packing lower bound does not meet witness size")

    cubes = cube_rows(expected_domain, expected_width)
    checked_pairs = 0
    for left, right in it.combinations(sorted(packing), 2):
        checked_pairs += 1
        lr, lo = left
        rr, ro = right
        for cube, rows in cubes:
            if lr not in rows or rr not in rows:
                continue
            legal_left = not any((row, lo) in forced_zero for row in rows)
            legal_right = not any((row, ro) in forced_zero for row in rows)
            need(not (legal_left and legal_right), f"{label} packing pair {left},{right} is co-coverable by {cube}")
    return {
        "cubes": len(cubes),
        "packing_pairs": checked_pairs,
        "products": record["minimum_products"],
        "produced": produced,
    }


def recheck_decoder_semantics(
    spec: dict,
    encoder: tuple[int, ...],
    bound: int,
    decoder_table: tuple[int, ...],
) -> dict:
    """Recheck inverse pins and every radius-one source/error obligation."""
    channel = words(spec["q"], spec["n"])
    need(len(decoder_table) == len(channel), "decoder table row count mismatch")
    inverse_rows = 0
    source_received_obligations = 0
    exact_error = 0
    for message, code_row in enumerate(encoder):
        inverse_rows += 1
        need(decoder_table[code_row] == message, "decoder circuit violates the inverse relation")
    for received, y in enumerate(channel):
        output = decoder_table[received]
        for source, code_row in enumerate(encoder):
            if sum(a != b for a, b in zip(channel[code_row], y)) <= spec["radius"]:
                source_received_obligations += 1
                error = (source ^ output).bit_count()
                exact_error = max(exact_error, error)
                need(error <= bound, "decoder circuit violates the claimed total-error bound")
    return {
        "rows": len(channel),
        "inverse_rows": inverse_rows,
        "source_received_obligations": source_received_obligations,
        "exact_error": exact_error,
    }


def check_certificate(spec: dict, cert: dict) -> dict:
    started = time.perf_counter()
    cpu = time.process_time()
    need(cert.get("format") == "fixed-codebook-frontier-v1", "unknown certificate format")
    case = cert["case"]
    for key in ("id", "q", "n", "k", "radius", "gate_cap", "connection_cap", "encoder"):
        need(case[key] == spec[key], f"case mismatch at {key}")
    channel = words(spec["q"], spec["n"])
    index = {"".join(map(str, word)): i for i, word in enumerate(channel)}
    encoder = tuple(index[word] for word in spec["encoder"])
    need(tuple(cert["encoder_rows"]) == encoder, "encoder row mapping mismatch")
    need(len(encoder) == (1 << spec["k"]) and len(set(encoder)) == len(encoder), "encoder is not injective")

    e_domain = tuple(range(1 << spec["k"]))
    e_width = int(spec["k"])
    e_outputs = wire_width(spec)
    e_legal = tuple((raw(channel[row], spec["q"]),) for row in encoder)
    encoder_report = check_plane(
        cert["encoder_plane"],
        expected_domain=e_domain,
        expected_width=e_width,
        expected_outputs=e_outputs,
        expected_legal=e_legal,
        label="encoder plane",
    )
    need(encoder_report["produced"] == tuple(value[0] for value in e_legal), "encoder circuit does not realize the fixed codebook")
    stats = [encoder_report]

    d_domain = tuple(raw(word, spec["q"]) for word in channel)
    d_width = wire_width(spec)
    d_outputs = int(spec["k"])
    semantic_rows_rechecked = 0
    inverse_rows_rechecked = 0
    source_received_obligations_rechecked = 0
    exact_error_by_bound: dict[str, int] = {}

    best: list[int | None] = [None] * (spec["k"] + 1)
    bound_records = cert["bounds"]
    need([item["error_bound"] for item in bound_records] == list(range(spec["k"] + 1)), "bound coverage mismatch")
    for item in bound_records:
        bound = item["error_bound"]
        rows = relation(spec, encoder, bound)
        obstruction = first_obstruction(spec, encoder, bound)
        if obstruction is not None:
            need(item == {"error_bound": bound, "semantic_obstruction": obstruction}, "semantic obstruction mismatch")
            continue
        need("decoder_plane" in item, "feasible bound lacks plane proof")
        plane_report = check_plane(
            item["decoder_plane"],
            expected_domain=d_domain,
            expected_width=d_width,
            expected_outputs=d_outputs,
            expected_legal=rows,
            label=f"decoder plane at error bound {bound}",
        )
        stats.append(plane_report)
        semantic = recheck_decoder_semantics(spec, encoder, bound, plane_report["produced"])
        semantic_rows_rechecked += semantic["rows"]
        inverse_rows_rechecked += semantic["inverse_rows"]
        source_received_obligations_rechecked += semantic["source_received_obligations"]
        exact_error_by_bound[str(bound)] = semantic["exact_error"]

        gates = cert["encoder_plane"]["minimum_products"] + item["decoder_plane"]["minimum_products"] + e_outputs + spec["k"]
        connections = cert["encoder_plane"]["connections"] + item["decoder_plane"]["connections"]
        need(gates == item["gates"] and connections == item["connections"], "objective mismatch")
        need(gates <= spec["gate_cap"] and connections <= spec["connection_cap"], "cap violation")
        best[bound] = gates
    need(best == cert["best_cost_by_error_bound"], "best-cost profile mismatch")

    frontier = []
    previous = None
    for bound, gates in enumerate(best):
        if gates is not None and (previous is None or gates < previous):
            frontier.append({"error_bound": bound, "gates": gates, "connections": bound_records[bound]["connections"]})
            previous = gates
    need(frontier == cert["frontier"], "frontier mismatch")
    free_rows = len(channel) - (1 << spec["k"])
    completions = (1 << spec["k"]) ** free_rows
    need(cert["decoder_completion_count"] == completions, "decoder completion count mismatch")
    need(cert["decoder_completion_count_power_of_two"] == spec["k"] * free_rows, "completion exponent mismatch")
    return {
        "accepted": True,
        "case": spec["id"],
        "planes_checked": len(stats),
        "plane_domain_bindings_checked": len(stats),
        "cubes_checked": sum(item["cubes"] for item in stats),
        "packing_pairs_checked": sum(item["packing_pairs"] for item in stats),
        "decoder_semantic_rows_rechecked": semantic_rows_rechecked,
        "decoder_inverse_rows_rechecked": inverse_rows_rechecked,
        "decoder_source_received_obligations_rechecked": source_received_obligations_rechecked,
        "decoder_exact_error_by_bound": exact_error_by_bound,
        "frontier": [[point["error_bound"], point["gates"]] for point in frontier],
        "checker_cpu_seconds": time.process_time() - cpu,
        "checker_wall_seconds": time.perf_counter() - started,
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", required=True)
    parser.add_argument("--inputs", type=Path, default=Path("inputs/fixed-codebooks.json"))
    parser.add_argument("--certificate-dir", type=Path, default=Path("results/fixed-codebook"))
    args = parser.parse_args()
    signal.alarm(600)
    resource.setrlimit(resource.RLIMIT_AS, (3 * 1024**3, 3 * 1024**3))
    specs = json.loads(args.inputs.read_text())
    spec = next((item for item in specs if item["id"] == args.case), None)
    if spec is None:
        raise ValueError("unknown fixed-codebook case")
    cert = json.loads((args.certificate_dir / f"{args.case}.json").read_text())
    result = check_certificate(spec, cert)
    (args.certificate_dir / f"{args.case}-check.json").write_text(json.dumps(result, separators=(",", ":")) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
