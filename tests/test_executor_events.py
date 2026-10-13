from worker.executor_events import matches


def test_operation_wait_matches_only_its_operation():
    waiting = {"operation_id": "op-1"}
    assert matches(waiting, "execution.operation_completed", {"operation": {"id": "op-1"}})
    assert not matches(waiting, "execution.operation_completed", {"operation": {"id": "op-2"}})
    assert matches(waiting, "execution.completed", {})  # terminal execution always ends the wait


def test_finalize_wait_matches_completion_only():
    waiting = {"operation_id": None}
    assert not matches(waiting, "execution.operation_completed", {"operation": {"id": "x"}})
    assert matches(waiting, "execution.completed", {"status": "SUCCEEDED"})
