"""Lightweight tests for durable progress, invalidation, failure, and timeout.

No scientific child is executed.  The mock queue has the same 81 unique-stage
cardinality as the real campaign and must finish after finitely many eight-stage
invocations without duplicate completion records.
"""
from __future__ import annotations

from pathlib import Path
import importlib.util
import json
import subprocess
import tempfile
from unittest.mock import patch

source = Path(__file__).resolve().parents[1] / 'reproduce.py'
spec = importlib.util.spec_from_file_location('runner_under_test', source)
module = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class SuccessRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, command, **_kwargs):
        self.calls.append(tuple(command))
        return subprocess.CompletedProcess(command, 0, '', '')


def prepare_state(results: Path, invocation_count: int = 1) -> None:
    module.write_json(results / module.RESUME_STATE, {
        'execution_fingerprint': 'mock',
        'invocation_count': invocation_count,
        'completed_prefix': 0,
    })


def run_multi_round_progress_control() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        results = root / 'results'
        results.mkdir()
        prepare_state(results)
        stages = [module.Stage(f'stage-{index:02d}', ('mock.py', str(index))) for index in range(81)]
        runner = SuccessRunner()
        records: dict[str, dict] = {}
        prefix = 0
        invocation = 1
        rounds = 0
        while prefix < len(stages):
            rounds += 1
            paused, prefix, _executed, records = module.run_stage_prefix(
                root=root,
                results=results,
                stages=stages,
                records=records,
                completed_prefix=prefix,
                invocation_count=invocation,
                stage_limit=8,
                env={},
                runner=runner,
            )
            invocation += 1
            state = json.loads((results / module.RESUME_STATE).read_text())
            state['invocation_count'] = invocation
            module.write_json(results / module.RESUME_STATE, state)
            if not paused:
                break
        assert prefix == 81
        assert rounds == 11
        assert len(records) == 81
        assert len(runner.calls) == 81
        assert len({record['stage'] for record in records.values()}) == 81
        assert len(json.loads((results / 'commands.json').read_text())) == 81


def run_missing_output_prefix_control() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / 'results').mkdir()
        (root / 'present').write_text('ok')
        stages = [
            module.Stage('one', ('a.py',), ('present',)),
            module.Stage('two', ('b.py',), ('missing',)),
            module.Stage('three', ('c.py',)),
        ]
        records = {name: {'stage': name, 'returncode': 0} for name in ('one', 'two', 'three')}
        assert module.valid_completed_prefix(root, stages, records) == 1


def run_source_change_invalidation_control() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / 'inputs').mkdir()
        (root / 'src').mkdir()
        (root / 'tests').mkdir()
        (root / 'results').mkdir()
        for name in ('reproduce.py', 'literature-audit.csv', 'external_resources.csv', 'claim_evidence_ledger.csv'):
            (root / name).write_text(name)
        (root / 'inputs' / 'x.json').write_text('{}')
        (root / 'src' / 'x.py').write_text('VALUE = 1\n')
        (root / 'tests' / 'x.py').write_text('pass\n')
        stages = [module.Stage('only', ('x.py',))]
        module.initialize_progress(root, root / 'results', stages, resume=False)
        (root / 'src' / 'x.py').write_text('VALUE = 2\n')
        try:
            module.initialize_progress(root, root / 'results', stages, resume=True)
        except RuntimeError as error:
            assert 'changed' in str(error)
        else:
            raise AssertionError('changed source did not invalidate resume')
        report = json.loads((root / 'results' / 'campaign.json').read_text())
        assert report['complete_locked_case_replay'] is False


def run_failure_control(timeout: bool = False) -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        results = root / 'results'
        results.mkdir()
        prepare_state(results)
        stages = [module.Stage('only', ('mock.py',))]
        if timeout:
            def runner(*_args, **_kwargs):
                raise subprocess.TimeoutExpired(['mock'], module.CHILD_TIMEOUT_SECONDS)
        else:
            def runner(command, **_kwargs):
                return subprocess.CompletedProcess(command, 2, '', 'controlled failure')
        try:
            module.run_stage_prefix(
                root=root,
                results=results,
                stages=stages,
                records={},
                completed_prefix=0,
                invocation_count=1,
                stage_limit=None,
                env={},
                runner=runner,
            )
        except (RuntimeError, subprocess.TimeoutExpired):
            pass
        else:
            raise AssertionError('failure was not propagated')
        report = json.loads((results / 'campaign.json').read_text())
        assert report['complete_locked_case_replay'] is False
        assert report['status'] == ('timeout' if timeout else 'failed')


def run_limit_control() -> None:
    calls = []
    with patch.object(module.resource, 'setrlimit', side_effect=lambda kind, value: calls.append((kind, value))):
        module.set_child_limits()
    expected = (module.CHILD_ADDRESS_SPACE_BYTES, module.CHILD_ADDRESS_SPACE_BYTES)
    assert calls == [(module.resource.RLIMIT_AS, expected)]


if __name__ == '__main__':
    run_multi_round_progress_control()
    run_missing_output_prefix_control()
    run_source_change_invalidation_control()
    run_failure_control()
    run_failure_control(timeout=True)
    run_limit_control()
    print('81-stage multi-round progress, source invalidation, missing-output prefix, failure, timeout, and 3 GiB limit controls passed; no scientific child executed.')
