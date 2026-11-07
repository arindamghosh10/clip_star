"""Which engines exist, and which one a workspace uses for each stage.

Engines are keyed by (stage, id): the same provider (e.g. "claude") can serve several stages.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from ..models import EngineChoice, Stage
from .captions import CaptionsFileEngine
from .moments_engines import ClaudeMomentEngine, OllamaMomentEngine, OpenAIMomentEngine, RulesMomentEngine
from .package_engines import ClaudePackageEngine, OllamaPackageEngine, OpenAIPackageEngine, TemplatePackageEngine
from .hosted_stt import AssemblyAIEngine, DeepgramEngine
from .whisper import WhisperEngine
from ..engage.engines import ClaudeEngageEngine, OllamaEngageEngine, OpenAIEngageEngine, RulesEngageEngine

_ALL = (
    WhisperEngine(),
    CaptionsFileEngine(),
    DeepgramEngine(),
    AssemblyAIEngine(),
    RulesMomentEngine(),
    ClaudeMomentEngine(),
    OllamaMomentEngine(),
    OpenAIMomentEngine(),
    TemplatePackageEngine(),
    ClaudePackageEngine(),
    OllamaPackageEngine(),
    OpenAIPackageEngine(),
    RulesEngageEngine(),
    ClaudeEngageEngine(),
    OllamaEngageEngine(),
    OpenAIEngageEngine(),
)
ENGINES: dict[tuple[Stage, str], object] = {(e.info.stage, e.info.id): e for e in _ALL}

DEFAULTS: dict[Stage, str] = {Stage.understand: "faster-whisper", Stage.moments: "rules", Stage.package: "templates", Stage.engage: "rules"}


def get_engine(stage: Stage, engine_id: str):
    return ENGINES.get((stage, engine_id))


def engines_for(stage: Stage) -> list:
    return [e for (st, _), e in ENGINES.items() if st == stage]


def chosen_engine_id(s: Session, workspace_id: uuid.UUID, stage: Stage) -> str | None:
    row = s.get(EngineChoice, (workspace_id, stage))
    if row and (stage, row.engine_id) in ENGINES:
        return row.engine_id
    return DEFAULTS.get(stage)


def chosen_engine(s: Session, workspace_id: uuid.UUID, stage: Stage):
    eid = chosen_engine_id(s, workspace_id, stage)
    return get_engine(stage, eid) if eid else None
