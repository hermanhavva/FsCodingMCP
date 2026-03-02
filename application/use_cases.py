from pathlib import Path
from domain.value_objects import WorkspacePath, FileExtension, FilePatch
from domain.interfaces import IFileSystemRepository, IGitRepository, IDiffGenerator, IPatchCache

class ReadFileUseCase:
    def __init__(self, fs_repo: IFileSystemRepository, root_dir: Path):
        self.fs_repo = fs_repo
        self.root_dir = root_dir

    def execute(self, raw_path: str) -> str:
        workspace_path = WorkspacePath(raw_path, self.root_dir)
        FileExtension(workspace_path.full_path) 
        return self.fs_repo.read_file(workspace_path.full_path)

# class WriteFileUseCase:
#     def __init__(self, fs_repo: IFileSystemRepository, git_repo: IGitRepository, root_dir: Path):
#         self.fs_repo = fs_repo
#         self.git_repo = git_repo
#         self.root_dir = root_dir

#     def execute(self, raw_path: str, content: str) -> str:
#         workspace_path = WorkspacePath(raw_path, self.root_dir)
#         FileExtension(workspace_path.full_path)
        
#         # The safety net is enforced here, completely agnostic of the actual OS
#         self.git_repo.backup_changes(f"Auto-backup before agent edit of {raw_path}")
#         self.fs_repo.write_file(workspace_path.full_path, content)
        
#         return f"Successfully wrote to {raw_path}"
    
class ListDirectoryUseCase:
    def __init__(self, fs_repo: IFileSystemRepository, root_dir: Path):
        self.fs_repo = fs_repo
        self.root_dir = root_dir

    def execute(self, raw_path: str) -> list[str]:
        # WorkspacePath naturally prevents escaping the sandbox (e.g., passing "../../")
        workspace_path = WorkspacePath(raw_path, self.root_dir)
        return self.fs_repo.list_directory(workspace_path.full_path)

class SearchFilesUseCase:
    def __init__(self, fs_repo: IFileSystemRepository, root_dir: Path):
        self.fs_repo = fs_repo
        self.root_dir = root_dir

    def execute(self, raw_dir: str, pattern: str) -> list[str]:
        # Validate the search root is within the sandbox
        workspace_path = WorkspacePath(raw_dir, self.root_dir)
        
        # We pass the domain's ALLOWED extensions to the infrastructure
        # so it knows which files are safe to grep through
        allowed_exts = FileExtension.ALLOWED
        return self.fs_repo.search_files(workspace_path.full_path, pattern, allowed_exts)

class GetPwdUseCase:
    def __init__(self, root_dir: Path):
        self.root_dir = root_dir

    def execute(self) -> str:
        # Returns the absolute path of the sandbox root so the LLM knows its boundaries
        return str(self.root_dir.resolve())
    
class AdvancedSearchUseCase:
    def __init__(self, fs_repo: IFileSystemRepository, root_dir: Path):
        self.fs_repo = fs_repo
        self.root_dir = root_dir

    def execute(self, raw_dir: str, pattern: str, extension_filter: list[str] | None = None, case_sensitive: bool = False, context_lines: int = 2) -> list[str]:
        workspace_path = WorkspacePath(raw_dir, self.root_dir)
        
        # 1. Start with the globally allowed safe extensions
        safe_extensions = FileExtension.ALLOWED
        
        # 2. If the LLM requested specific extensions, filter down to them
        if extension_filter:
            # Normalize extensions (e.g., 'cpp' -> '.cpp')
            requested_exts = {ext.lower() if ext.startswith('.') else f".{ext.lower()}" for ext in extension_filter}
            # Intersect to guarantee we never search unsafe files, even if requested
            search_extensions = safe_extensions.intersection(requested_exts)
            
            if not search_extensions:
                return ["Error: None of the requested extensions are in the allowed sandbox whitelist."]
        else:
            search_extensions = safe_extensions

        return self.fs_repo.advanced_search(
            workspace_path.full_path, 
            pattern, 
            search_extensions, 
            case_sensitive, 
            context_lines
        )
    
class CreateFileUseCase:
    def __init__(self, fs_repo: IFileSystemRepository, git_repo: IGitRepository, root_dir: Path):
        self.fs_repo = fs_repo
        self.git_repo = git_repo
        self.root_dir = root_dir

    def execute(self, raw_path: str, content: str) -> str:
        workspace_path = WorkspacePath(raw_path, self.root_dir)
        FileExtension(workspace_path.full_path)
        
        # Guardrail: Prevent overwriting existing files
        if workspace_path.full_path.exists():
            raise FileExistsError(f"File '{raw_path}' already exists. Use 'propose_block_edit' to modify it.")
            
        self.git_repo.backup_changes(f"Auto-backup before agent created {raw_path}")
        self.fs_repo.create_file(workspace_path.full_path, content)
        return f"Successfully created new file at {raw_path}"

class AppendToFileUseCase:
    def __init__(self, fs_repo: IFileSystemRepository, git_repo: IGitRepository, root_dir: Path):
        self.fs_repo = fs_repo
        self.git_repo = git_repo
        self.root_dir = root_dir

    def execute(self, raw_path: str, content: str) -> str:
        workspace_path = WorkspacePath(raw_path, self.root_dir)
        FileExtension(workspace_path.full_path)
        
        self.git_repo.backup_changes(f"Auto-backup before agent appended to {raw_path}")
        self.fs_repo.append_file(workspace_path.full_path, content)
        return f"Successfully appended content to {raw_path}"

class ProposeBlockEditUseCase:
    def __init__(self, fs_repo: IFileSystemRepository, diff_gen: IDiffGenerator, patch_cache: IPatchCache, root_dir: Path):
        self.fs_repo = fs_repo
        self.diff_gen = diff_gen
        self.patch_cache = patch_cache
        self.root_dir = root_dir

    def execute(self, raw_path: str, start_line: int, end_line: int, new_code: str) -> str:
        workspace_path = WorkspacePath(raw_path, self.root_dir)
        FileExtension(workspace_path.full_path)

        if not workspace_path.full_path.exists():
            raise FileNotFoundError(f"File '{raw_path}' does not exist. Use 'create_file' instead.")

        # 1. Read the original content
        original_content = self.fs_repo.read_file(workspace_path.full_path)
        original_lines = original_content.splitlines()

        # 2. Slice and inject the new lines (1-indexed to 0-indexed)
        start_idx = max(0, start_line - 1)
        end_idx = min(len(original_lines), end_line)
        
        new_lines = new_code.splitlines()
        modified_lines = original_lines[:start_idx] + new_lines + original_lines[end_idx:]
        modified_content = "\n".join(modified_lines) + "\n"

        # 3. Generate the Diff
        diff_str = self.diff_gen.generate_unified_diff(
            workspace_path.full_path.relative_to(self.root_dir), 
            original_lines, 
            modified_lines
        )

        if not diff_str.strip():
            return "No changes detected. The new code is identical to the existing code."

        # 4. Save to Cache
        patch = FilePatch(
            file_path=workspace_path.full_path,
            original_content=original_content,
            modified_content=modified_content,
            unified_diff=diff_str
        )
        self.patch_cache.save_patch(patch)

        return (
            f"Review the proposed changes below. If correct, use the 'apply_edit' tool with patch_id: {patch.patch_id}\n\n"
            f"```diff\n{diff_str}\n```"
        )

class ApplyEditUseCase:
    def __init__(self, patch_cache: IPatchCache, fs_repo: IFileSystemRepository, git_repo: IGitRepository):
        self.patch_cache = patch_cache
        self.fs_repo = fs_repo
        self.git_repo = git_repo

    def execute(self, patch_id: str) -> str:
        patch = self.patch_cache.get_patch(patch_id)
        if not patch:
            raise ValueError(f"Patch ID '{patch_id}' not found or has expired.")

        # The guardrails (extensions, root bounds) were already checked during the propose phase
        self.git_repo.backup_changes(f"Auto-backup before agent applied patch {patch_id}")
        
        # We reuse create_file logic (or add a specific overwrite_file) to write the exact modified content
        # For simplicity, we can use the same pathlib write_text underlying implementation.
        # Let's assume LocalFileSystemAdapter's create_file overwrites. 
        self.fs_repo.create_file(patch.file_path, patch.modified_content)
        
        self.patch_cache.delete_patch(patch_id)
        return f"Successfully applied patch {patch_id} to {patch.file_path.name}"