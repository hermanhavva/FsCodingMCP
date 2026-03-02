import uuid
from pathlib import Path
from dataclasses import dataclass, field
from .exceptions import SandboxViolationError, InvalidExtensionError

class WorkspacePath:
    def __init__(self, raw_path: str, root_dir: Path):
        self._root = root_dir.resolve()
        # Resolve resolves symlinks and '..' components automatically
        self._path = (self._root / raw_path).resolve()
        
        # The ultimate guardrail: ensure the resolved path is inside the root
        if not self._path.is_relative_to(self._root):
            raise SandboxViolationError(f"Security violation: '{raw_path}' attempts to escape the workspace root.")

    @property
    def full_path(self) -> Path:
        return self._path

class FileExtension:
    # Strict whitelist to prevent reading binaries or modifying sensitive configs
    ALLOWED = {'.cpp', '.h', '.cs', '.swift', '.py', '.cmake', '.json', '.txt', '.md'}
    
    def __init__(self, path: Path):
        suffix = path.suffix.lower()
        if suffix not in self.ALLOWED:
            raise InvalidExtensionError(f"Security violation: Extension '{suffix}' is not permitted.")
        self.suffix = suffix

@dataclass
class FilePatch:
    """Represents a proposed, unapplied change to a file."""
    file_path: Path
    original_content: str
    modified_content: str
    unified_diff: str
    patch_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])