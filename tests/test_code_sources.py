from types import SimpleNamespace
from typing import Any, cast

from langchain_core.messages import AIMessage, HumanMessage

from core.executor.sources import SourceOwner, file_name
from core.executor.storage import SharedStorage

OWNER = SourceOwner("u-1", "p-1", "s-1", "r-1")


def test_paths_follow_owner_run_and_operation():
    folder = OWNER.folder(2, "run_plan")
    assert folder == (
        "users/u-1/projects/p-1/sessions/s-1/runs/r-1/02-run_plan"
    )
    assert file_name(0, "setup") == "00-setup.py"
    assert file_name(3, "tool", "merge_data") == "03-tool-merge_data.py"
    assert (
        SourceOwner("a/../b", "p", "s", "r")
        .folder(1, "x")
        .startswith("users/a-..-b/")
    )


def test_write_once_and_cleanup(tmp_path):
    storage = SharedStorage(tmp_path / "svc", "svc", tmp_path / "results")
    relative = f"{OWNER.folder(1, 'run_plan')}/01-tool-a.py"
    first, size = storage.write_source("print(1)\n", relative)
    assert first["path"] == f"svc/sources/{relative}" and size == 9
    # a re-run after the tool file changed still sends the first code
    again, _ = storage.write_source("print(2)\n", relative)
    assert again == first
    storage.delete_source(first["path"])
    assert list((tmp_path / "svc" / "sources").iterdir()) == []


def test_operation_folder_counts_execution_calls_of_this_turn():
    from agent.tools.analysis import _source_folder

    def call(name, call_id):
        return AIMessage(
            "", tool_calls=[{"name": name, "args": {}, "id": call_id}]
        )

    messages = [
        HumanMessage("earlier turn", id="r-0"),
        call("run_plan", "old"),
        HumanMessage("this turn", id="r-1"),
        call("read_skill", "a"),
        call("run_plan", "b"),
        call("run_custom_code", "c"),
    ]
    context = SimpleNamespace(
        user_id="u-1",
        project_id="p-1",
        session_id="s-1",
        run_id="r-1",
    )
    runtime = SimpleNamespace(
        state={"messages": messages}, context=context, tool_call_id="c"
    )
    folder = _source_folder(cast(Any, runtime), "run_custom_code")
    assert folder.endswith("/runs/r-1/02-run_custom_code")
