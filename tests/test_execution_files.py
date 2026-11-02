"""Step output files are served only from the execution they belong to."""

from src.dtest.core.executor.storage import SharedStorage

MINE = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"


def _storage(tmp_path):
    for execution in (MINE, OTHER):
        folder = tmp_path / "executions" / execution / "steps"
        folder.mkdir(parents=True)
        (folder / "plot.png").write_bytes(b"png")
    (tmp_path / "secret.txt").write_text("x")
    return SharedStorage(tmp_path / "in", "agentic", tmp_path)


def test_own_files_are_found(tmp_path):
    storage = _storage(tmp_path)
    path = f"executions/{MINE}/steps/plot.png"
    assert storage.execution_file(MINE, path) == (tmp_path / path).resolve()


def test_paths_out_of_the_execution_are_refused(tmp_path):
    storage = _storage(tmp_path)
    for path in (
        f"executions/{MINE}/../{OTHER}/steps/plot.png",
        f"executions/{MINE}/../../secret.txt",
        f"executions/{OTHER}/steps/plot.png",
        f"executions/{MINE}/../../../etc/passwd",
        f"executions/{MINE}",
        f"executions/{MINE}/steps/missing.png",
    ):
        assert storage.execution_file(MINE, path) is None, path


def test_execution_id_cannot_climb(tmp_path):
    storage = _storage(tmp_path)
    assert storage.execution_file("..", "secret.txt") is None
    assert storage.execution_file(f"{MINE}/..", "secret.txt") is None


def _common_root(tmp_path):
    """The common root: executor results under executor/, ours beside."""
    for execution in (MINE, OTHER):
        folder = tmp_path / "executor" / "executions" / execution / "steps"
        folder.mkdir(parents=True)
        (folder / "plot.png").write_bytes(b"png")
    ours = tmp_path / "dtest-agent-service" / "executions" / MINE
    ours.mkdir(parents=True)
    (ours / "code.py").write_text("x")
    (tmp_path / "batch").mkdir()
    (tmp_path / "batch" / "input.csv").write_text("x")
    return SharedStorage(tmp_path / "dtest-agent-service", "x", tmp_path)


def test_paths_relative_to_the_common_root_are_used_as_given(tmp_path):
    storage = _common_root(tmp_path)
    path = f"executor/executions/{MINE}/steps/plot.png"
    assert storage.execution_file(MINE, path) == (tmp_path / path).resolve()


def test_common_root_paths_stay_in_the_execution(tmp_path):
    storage = _common_root(tmp_path)
    for path in (
        f"executor/executions/{OTHER}/steps/plot.png",
        f"executor/executions/{MINE}/../{OTHER}/steps/plot.png",
        f"executor/executions/{MINE}/../../../batch/input.csv",
        "batch/input.csv",
        f"dtest-agent-service/executions/{MINE}/code.py",
        f"executor/executions/{MINE}/../../../../etc/passwd",
    ):
        assert storage.execution_file(MINE, path) is None, path
