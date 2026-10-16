import io
import json

import pytest

from agentic_workbench.errors import WorkbenchError
from agentic_workbench.observability import EventLogger


def test_events_are_metadata_only_and_redacted():
    stream = io.StringIO()
    logger = EventLogger(lambda text: text.replace("private-value", "[REDACTED]"), stream)
    logger.emit("task.started", task_id="private-value", agent="discovery", elapsed_ms=12)
    payload = json.loads(stream.getvalue())
    assert payload["task_id"] == "[REDACTED]"
    assert payload["event"] == "task.started"
    assert payload["elapsed_ms"] == 12
    assert "private-value" not in stream.getvalue()
    assert "timestamp" in payload


@pytest.mark.parametrize("field", ["prompt", "source", "arguments", "api_key", "response"])
def test_untrusted_bodies_are_not_event_fields(field):
    stream = io.StringIO()
    logger = EventLogger(lambda text: text, stream)
    with pytest.raises(WorkbenchError):
        logger.emit("task.started", **{field: "sensitive-body"})
    assert not stream.getvalue()
