import re
import subprocess
import difflib
from pathlib import Path
from typing import List, Set, Dict

# Updated to include the new interfaces
from domain.interfaces import IFileSystemRepository, IGitRepository, IDiffGenerator, IPatchCache
# Added the missing Value Object
from domain.value_objects import FilePatch

class LocalFileSystemAdapter(IFileSystemRepository):
    def read_file(self, path: Path) -> str:
        return path.read_text(encoding='utf-8')
        
    def create_file(self, path: Path, content: str) -> None:
        # Creates the directories if they don't exist, then writes the file.
        # The Application layer (CreateFileUseCase) already checks if the file exists.
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')

    def append_file(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'a', encoding='utf-8') as f:
            f.write(content)
        
    # def write_file(self, path: Path, content: str) -> None:
    #     path.parent.mkdir(parents=True, exist_ok=True)
    #     path.write_text(content, encoding='utf-8')

    def list_directory(self, path: Path) -> List[str]:
        if not path.is_dir():
            raise NotADirectoryError(f"'{path.name}' is not a directory.")
        
        items = []
        for item in path.iterdir():
            # Append a slash to directories to help the LLM understand the structure
            suffix = "/" if item.is_dir() else ""
            items.append(f"{item.name}{suffix}")
        return sorted(items)

    def search_files(self, directory: Path, pattern: str, allowed_extensions: Set[str]) -> List[str]:
        if not directory.is_dir():
            raise NotADirectoryError(f"'{directory.name}' is not a directory.")

        results = []
        try:
            regex = re.compile(pattern)
        except re.error as e:
            raise ValueError(f"Invalid regex pattern: {e}")

        # Recursively search through the directory
        for file_path in directory.rglob("*"):
            # Only search inside allowed, safe text extensions
            if file_path.is_file() and file_path.suffix.lower() in allowed_extensions:
                try:
                    content = file_path.read_text(encoding='utf-8')
                    for line_num, line in enumerate(content.splitlines(), 1):
                        if regex.search(line):
                            # Format: relative/path/to/file.cpp:42: int main() {
                            rel_path = file_path.relative_to(directory)
                            results.append(f"{rel_path}:{line_num}:{line.strip()}")
                except Exception:
                    # Silently skip files that trigger encoding or permission errors
                    pass
        
        return results
    
    def advanced_search(self, directory: Path, pattern: str, allowed_extensions: Set[str], case_sensitive: bool, context_lines: int) -> List[str]:
        if not directory.is_dir():
            raise NotADirectoryError(f"'{directory.name}' is not a directory.")

        results = []
        # Apply case-insensitivity toggle
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            regex = re.compile(pattern, flags)
        except re.error as e:
            raise ValueError(f"Invalid regex pattern: {e}")

        for file_path in directory.rglob("*"):
            if file_path.is_file() and file_path.suffix.lower() in allowed_extensions:
                try:
                    lines = file_path.read_text(encoding='utf-8').splitlines()
                    match_indices = [i for i, line in enumerate(lines) if regex.search(line)]
                    
                    if match_indices:
                        rel_path = file_path.relative_to(directory)
                        results.append(f"\n--- Matches in {rel_path} ---")
                        
                        last_printed = -1
                        for i in match_indices:
                            start = max(0, i - context_lines)
                            end = min(len(lines), i + context_lines + 1)
                            
                            # Print a separator if there is a gap between context blocks
                            if last_printed != -1 and start > last_printed:
                                results.append("...")
                            
                            actual_start = max(start, last_printed if last_printed != -1 else 0)
                            
                            for j in range(actual_start, end):
                                # Mark the exact matching line with a '>' pointer
                                prefix = ">" if j == i else " "
                                results.append(f"{prefix} {j+1:4d}: {lines[j]}")
                            
                            last_printed = end
                except Exception:
                    pass
        
        return results

class DifflibGenerator(IDiffGenerator):
    def generate_unified_diff(self, file_path: Path, original_lines: List[str], modified_lines: List[str]) -> str:
        # difflib requires line endings to generate a standard patch format accurately
        original_with_newlines = [line + '\n' for line in original_lines]
        modified_with_newlines = [line + '\n' for line in modified_lines]
        
        diff = difflib.unified_diff(
            original_with_newlines, 
            modified_with_newlines, 
            fromfile=f"a/{file_path}", 
            tofile=f"b/{file_path}", 
            n=3 # Number of context lines
        )
        return "".join(diff)

class InMemoryPatchCache(IPatchCache):
    def __init__(self):
        self._cache: Dict[str, FilePatch] = {}

    def save_patch(self, patch: FilePatch) -> None:
        self._cache[patch.patch_id] = patch

    def get_patch(self, patch_id: str) -> FilePatch | None:
        return self._cache.get(patch_id)

    def delete_patch(self, patch_id: str) -> None:
        if patch_id in self._cache:
            del self._cache[patch_id]

class SubprocessGitAdapter(IGitRepository):
    def __init__(self, root_dir: Path):
        self.root_dir = root_dir

    def backup_changes(self, message: str) -> None:
        try:
            # Stage all changes and commit. If there are no changes, subprocess fails silently, which is fine.
            subprocess.run(["git", "add", "."], cwd=self.root_dir, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", message], cwd=self.root_dir, check=True, capture_output=True)
        except subprocess.CalledProcessError:
            pass