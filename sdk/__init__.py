"""AI Failure Investigator SDK."""

__version__ = "0.3.0"

from . import auto
from .client import FailureInvestigator
from .comparison import ShadowComparison

__all__ = ["FailureInvestigator", "ShadowComparison", "auto"]
