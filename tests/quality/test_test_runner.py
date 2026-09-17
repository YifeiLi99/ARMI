from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path

import pytest

from tools.pytest_groups import path_groups, web_files
from tools.run_tests import allocation, clean_environment, run

pytest_plugins = ("pytester",)


@pytest.mark.parametrize("jobs", [1, 2, 3, 8, 14, 32])
def test_pool_allocation_respects_individual_and_parallel_budgets(jobs: int) -> None:
    pools = allocation(jobs, 4, {"offline", "database", "web"})
    assert all(1 <= value <= jobs for value in pools.values())
    assert pools["database"] <= 4
    assert pools["web"] <= 2
    if jobs >= 3:
        assert sum(pools.values()) <= jobs
    assert allocation(jobs, 4, {"offline"}) == {"offline": jobs}


def test_group_names_match_complete_components() -> None:
    known = {"mind", "mood", "codex", "runtime", "live-voice"}
    assert path_groups(Path("tests/runtime/test_codex_result.py"), known) == {
        "runtime",
        "codex",
    }
    assert "mind" not in path_groups(Path("tests/runtime/test_reminder.py"), known)
    assert path_groups(Path("modules/live-voice/tests/test_service.py"), known) == {
        "live-voice"
    }


def test_web_discovery_includes_new_test_files(tmp_path: Path) -> None:
    source = tmp_path / "apps/armi-creator-web/src/features/dataRights"
    source.mkdir(parents=True)
    test = source / "NewPanel.test.tsx"
    test.touch()
    assert web_files(tmp_path)[test] == {"web", "creator-web", "data-rights"}


def test_runner_does_not_inherit_installed_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in (
        "ARMI_ENVIRONMENT_ROOT",
        "S009_ADMIN_DSN",
        "S026_LIVE_ENVIRONMENT_ROOT",
        "PYTEST_ADDOPTS",
    ):
        monkeypatch.setenv(key, "must-not-be-used")
    environment = clean_environment()
    assert not any(
        key.startswith(("ARMI_", "S009_", "S026_", "PYTEST_")) for key in environment
    )


def test_cancelled_subprocess_returns_failure_and_stops(tmp_path: Path) -> None:
    cancel = threading.Event()
    cancel.set()
    assert (
        run(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            cwd=tmp_path,
            environment=clean_environment(),
            log=tmp_path / "cancel.log",
            cancel=cancel,
        )
        == 130
    )


@pytest.fixture
def selection_project(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> pytest.Pytester:
    root = Path(__file__).resolve().parents[2]
    monkeypatch.setenv("PYTHONPATH", str(root))
    for key in tuple(os.environ):
        if key.startswith(("S009_", "ARMI_TEST_POSTGRESQL", "PYTEST_ADDOPTS")):
            monkeypatch.delenv(key, raising=False)
    pytester.makeini(
        "[pytest]\nmarkers=\n postgresql: database\n creator_system: browser\n"
    )
    tests = pytester.path / "modules/new-owner/tests"
    tests.mkdir(parents=True)
    (tests / "test_new.py").write_text(
        "import pytest\n"
        "def test_untagged(): pass\n"
        "@pytest.mark.test_group('cognition', 'expression')\n"
        "def test_joint(): pass\n"
        "@pytest.mark.postgresql\n"
        "def test_database(): pass\n"
        "@pytest.mark.postgresql\n"
        "@pytest.mark.creator_system\n"
        "def test_browser(): raise AssertionError('must not run')\n",
        encoding="utf-8",
    )
    return pytester


def test_full_collection_keeps_untagged_and_module_database_tests(
    selection_project: pytest.Pytester,
) -> None:
    project = selection_project
    inventory = project.path / "inventory.json"
    result = project.runpytest_subprocess(
        "-p",
        "tools.pytest_groups",
        "--collect-only",
        "--test-inventory",
        str(inventory),
    )
    assert result.ret == 0
    counts = json.loads(inventory.read_text())
    assert counts["collected"] == 4
    assert counts["selected"] == {"offline": 2, "database": 1}
    assert counts["excluded"] == 1
    assert list(counts["out_of_scope"].values()) == [["creator_system"]]


def test_overlapping_groups_execute_once(selection_project: pytest.Pytester) -> None:
    result = selection_project.runpytest_subprocess(
        "-p",
        "tools.pytest_groups",
        "--test-lane",
        "offline",
        "--test-group",
        "cognition",
        "--test-group",
        "expression",
    )
    result.assert_outcomes(passed=1, deselected=3)


def test_missing_database_fails_instead_of_skipping(
    selection_project: pytest.Pytester,
) -> None:
    result = selection_project.runpytest_subprocess(
        "-p", "tools.pytest_groups", "--test-lane", "database"
    )
    assert result.ret == pytest.ExitCode.USAGE_ERROR


def test_unknown_group_fails(selection_project: pytest.Pytester) -> None:
    result = selection_project.runpytest_subprocess(
        "-p", "tools.pytest_groups", "--test-group", "typo"
    )
    assert result.ret == pytest.ExitCode.USAGE_ERROR
