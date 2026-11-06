"""Which engines exist, and which one a workspace uses for each stage."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from ..models import EngineChoice, Stage
from .captions import CaptionsFileEngine
from .moments_engines import ClaudeMomentEngine, OllamaMomentEngine, RulesMomentEngine
from .whisper import WhisperEngine

ENGINES = {
    e.info.id: e
    for e in (WhisperEngine(), CaptionsFileEngine(), RulesMomentEngine(), ClaudeMomentEngine(), OllamaMomentEngine())
}

DEFAULTS: dict[Stage, str] = {Stage.understand: "faster-whisper", Stage.moments: "rules"}


def engines_for(stage: Stage) -> list:
    return [e for e in ENGINES.values() if e.info.stage == stage]


def chosen_engine_id(s: Session, workspace_id: uuid.UUID, stage: Stage) -> str | None:
    row = s.get(EngineChoice, (workspace_id, stage))
    if row and row.engine_id in ENGINES:
        return row.engine_id
    return DEFAULTS.get(stage)
