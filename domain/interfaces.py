from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Set
from .value_objects import FilePatch

class IFileSystemRepository(ABC):
    @abstractmethod
    def read_file(self, path: Path) -> str: pass
    
    # Renamed from write_file to enforce scaffolding-only
    @abstractmethod
    def create_file(self, path: Path, content: str) -> None: pass
    
    # New method for logs/continuous docs
    @abstractmethod
    def append_file(self, path: Path, content: str) -> None: pass

    @abstractmethod
    def list_directory(self, path: Path) -> List[str]: pass

    @abstractmethod
    def search_files(self, directory: Path, pattern: str, allowed_extensions: Set[str]) -> List[str]: pass

    @abstractmethod
    def advanced_search(self, directory: Path, pattern: str, allowed_extensions: Set[str], case_sensitive: bool, context_lines: int) -> List[str]: pass

class IDiffGenerator(ABC):
    @abstractmethod
    def generate_unified_diff(self, file_path: Path, original_lines: List[str], modified_lines: List[str]) -> str: pass

class IPatchCache(ABC):
    @abstractmethod
    def save_patch(self, patch: FilePatch) -> None: pass
    
    @abstractmethod
    def get_patch(self, patch_id: str) -> FilePatch | None: pass

    @abstractmethod
    def delete_patch(self, patch_id: str) -> None: pass

class IGitRepository(ABC):
    @abstractmethod
    def backup_changes(self, message: str) -> None: pass