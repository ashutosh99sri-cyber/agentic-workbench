"""Source-grounded development agents with host-controlled authority."""

from importlib.metadata import version

__version__ = version("agentic-workbench")

from .config import CommandConfig, Config  # noqa: E402
from .errors import WorkbenchError  # noqa: E402
from .execution import (  # noqa: E402
    ExecutionContext,
    ExecutionLimits,
    Harness,
    Observation,
    Plan,
    PlanRequest,
    Step,
    Verification,
    VerificationRequest,
)
from .models import AgentResult, Evidence, Grant  # noqa: E402
from .orchestrator import Node  # noqa: E402
from .providers import Provider, ProviderRegistry, ProviderRejected  # noqa: E402
from .routing import ModelRegistry, ModelSpec, RoutedProvider, RoutingLimits  # noqa: E402
from .sdk import Workbench  # noqa: E402
from .tool_registry import ToolCall, ToolRegistry, ToolResult, ToolSpec  # noqa: E402

__all__ = [
    "AgentResult",
    "CommandConfig",
    "Config",
    "Evidence",
    "ExecutionContext",
    "ExecutionLimits",
    "Grant",
    "Harness",
    "ModelRegistry",
    "ModelSpec",
    "Node",
    "Observation",
    "Plan",
    "PlanRequest",
    "Provider",
    "ProviderRegistry",
    "ProviderRejected",
    "RoutedProvider",
    "RoutingLimits",
    "Step",
    "ToolCall",
    "ToolRegistry",
    "ToolResult",
    "ToolSpec",
    "Verification",
    "VerificationRequest",
    "Workbench",
    "WorkbenchError",
    "__version__",
]
