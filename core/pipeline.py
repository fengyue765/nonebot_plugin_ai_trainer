"""Pipeline state manager.

Tracks the state of an in-progress 4-stage painting pipeline for a
single user session:

    sketch → lineart → flat_color → final_render

State is persisted to a JSON file so that it survives bot restarts.
Each step's output image (PNG bytes) is stored alongside the state.
"""

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

from ..config import Config


@dataclass
class PipelineState:
    user_id: str
    prompt: str
    current_step_index: int = 0
    # Maps step name → filename (relative to data root) of the output image
    step_images: dict = field(default_factory=dict)
    active: bool = True

    @property
    def current_step(self) -> Optional[str]:
        steps = Config.PIPELINE_STEPS
        if self.current_step_index < len(steps):
            return steps[self.current_step_index]
        return None

    @property
    def is_complete(self) -> bool:
        return self.current_step_index >= len(Config.PIPELINE_STEPS)

    def advance(self) -> None:
        self.current_step_index += 1

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "PipelineState":
        return cls(
            user_id=d["user_id"],
            prompt=d["prompt"],
            current_step_index=d.get("current_step_index", 0),
            step_images=d.get("step_images", {}),
            active=d.get("active", True),
        )


class PipelineManager:
    """Persists and manages PipelineState objects, one per user."""

    def __init__(self, state_file: str = Config.PIPELINE_STATE_FILE) -> None:
        self._path = Path(state_file)
        self._states: dict[str, PipelineState] = self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> dict[str, PipelineState]:
        if self._path.exists():
            try:
                raw = json.loads(self._path.read_text(encoding="utf-8"))
                return {uid: PipelineState.from_dict(d) for uid, d in raw.items()}
            except (json.JSONDecodeError, OSError, KeyError):
                pass
        return {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        serialised = {uid: state.to_dict() for uid, state in self._states.items()}
        self._path.write_text(
            json.dumps(serialised, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def get_state(self, user_id: str) -> Optional[PipelineState]:
        state = self._states.get(user_id)
        if state and state.active:
            return state
        return None

    def create_state(self, user_id: str, prompt: str) -> PipelineState:
        """Create (or overwrite) a pipeline state for the given user."""
        state = PipelineState(user_id=user_id, prompt=prompt)
        self._states[user_id] = state
        self._save()
        return state

    def save_step_image(
        self,
        user_id: str,
        step: str,
        image_bytes: bytes,
    ) -> str:
        """Persist a step's output image and record its path in the state.

        Returns the absolute path to the saved file.
        """
        data_root = Path(Config.DATA_ROOT)
        step_dir = data_root / "pipeline" / user_id / step
        step_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{step}.png"
        abs_path = step_dir / filename
        abs_path.write_bytes(image_bytes)

        state = self._states[user_id]
        state.step_images[step] = str(abs_path)
        self._save()
        return str(abs_path)

    def advance_step(self, user_id: str) -> Optional[str]:
        """Advance to the next step. Returns the new step name, or None if complete."""
        state = self._states.get(user_id)
        if not state:
            return None
        state.advance()
        if state.is_complete:
            state.active = False
        self._save()
        return state.current_step

    def clear_state(self, user_id: str) -> None:
        """Remove the pipeline state for a user."""
        self._states.pop(user_id, None)
        self._save()


# Module-level singleton
pipeline_manager = PipelineManager()
