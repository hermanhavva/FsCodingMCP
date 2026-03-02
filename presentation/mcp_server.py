import os
import sys
import argparse
from pathlib import Path
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

# --- 1. Parse and Validate CLI Arguments ---
parser = argparse.ArgumentParser(description="Secure MCP Workspace Server")
parser.add_argument(
    "workspace_root", 
    type=str, 
    help="Mandatory path to the workspace root directory. The agent cannot escape this sandbox."
)
args = parser.parse_args()

# Resolve to an absolute path immediately
ROOT_DIR = Path(args.workspace_root).resolve()

if not ROOT_DIR.exists() or not ROOT_DIR.is_dir():
    print(f"\nCRITICAL ERROR: The provided workspace root does not exist or is not a directory:\n-> {ROOT_DIR}\n")
    sys.exit(1)

# --- 2. Setup System Paths and Imports ---
# Ensure Python can find the adjacent layers
sys.path.insert(0, str(Path(__file__).parent.parent))

from infrastructure.adapters import LocalFileSystemAdapter, SubprocessGitAdapter, DifflibGenerator, InMemoryPatchCache
from application.use_cases import (
    ReadFileUseCase, ListDirectoryUseCase, SearchFilesUseCase, AdvancedSearchUseCase, GetPwdUseCase,
    CreateFileUseCase, AppendToFileUseCase, ProposeBlockEditUseCase, ApplyEditUseCase
)

# --- 3. Instantiate Adapters ---
fs_adapter = LocalFileSystemAdapter()
git_adapter = SubprocessGitAdapter(ROOT_DIR)
diff_generator = DifflibGenerator()
patch_cache = InMemoryPatchCache()

# --- 4. Inject into Use Cases ---
read_use_case = ReadFileUseCase(fs_adapter, ROOT_DIR)
list_use_case = ListDirectoryUseCase(fs_adapter, ROOT_DIR)
search_use_case = SearchFilesUseCase(fs_adapter, ROOT_DIR)
pwd_use_case = GetPwdUseCase(ROOT_DIR)
advanced_search_use_case = AdvancedSearchUseCase(fs_adapter, ROOT_DIR)
create_use_case = CreateFileUseCase(fs_adapter, git_adapter, ROOT_DIR)
append_use_case = AppendToFileUseCase(fs_adapter, git_adapter, ROOT_DIR)
propose_edit_use_case = ProposeBlockEditUseCase(fs_adapter, diff_generator, patch_cache, ROOT_DIR)
apply_edit_use_case = ApplyEditUseCase(patch_cache, fs_adapter, git_adapter)

# --- 5. Setup FastMCP Server ---
mcp = FastMCP(
    "Secure_Workspace_Server",
    host="0.0.0.0",
    port=8000,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False # Allows ngrok URLs to connect
    )
)


# --- 6. Tools Definition ---
@mcp.tool()
def create_file(path: str, content: str) -> str:
    """
    Creates a brand new file with the specified content. 
    
    IMPLICIT BEHAVIOR: Automatically creates a Git commit of the workspace BEFORE the new file is written to disk as a safety net.
    
    Use this strictly for scaffolding new files (e.g., creating a new C++ header or CMakeLists.txt). 
    This tool will immediately fail with a FileExistsError if the file already exists. To modify an existing file, you MUST use `propose_block_edit`.
    """
    try:
        return create_use_case.execute(path, content)
    except Exception as e:
        return f"Error creating file: {str(e)}"

@mcp.tool()
def append_to_file(path: str, content: str) -> str:
    """
    Appends the provided content to the very end of an existing file.
    
    IMPLICIT BEHAVIOR: Automatically creates a Git commit of the workspace BEFORE appending.
    
    Useful for incrementally adding lines to continuous files like logs, .gitignore, or running documentation without needing to parse the entire file structure.
    """
    try:
        return append_use_case.execute(path, content)
    except Exception as e:
        return f"Error appending to file: {str(e)}"

@mcp.tool()
def propose_block_edit(path: str, start_line: int, end_line: int, new_code: str) -> str:
    """
    PHASE 1 OF EDITING: Proposes a surgical modification to an existing file. 
    
    This tool DOES NOT modify the filesystem. It calculates the change and returns a unified diff and a temporary `patch_id` for review.
    
    Parameters:
    - path: File path relative to the workspace root.
    - start_line: The first line to replace (1-indexed).
    - end_line: The last line to replace. 
      * Note: To INSERT code without deleting anything, set `end_line` to `start_line - 1`.
      * Note: To DELETE code without inserting, provide an empty string "" for `new_code`.
    - new_code: The multi-line string of new code to inject. Do not include line numbers in the string.
    """
    try:
        return propose_edit_use_case.execute(path, start_line, end_line, new_code)
    except Exception as e:
        return f"Error proposing edit: {str(e)}"

@mcp.tool()
def apply_edit(patch_id: str) -> str:
    """
    PHASE 2 OF EDITING: Applies a proposed patch to the file system.
    
    IMPLICIT BEHAVIOR: Automatically creates a Git commit of the workspace BEFORE the patch is applied, allowing for easy reversions if the edit causes compile or runtime errors.
    
    You must provide the exact `patch_id` returned by a previous call to `propose_block_edit`. Once applied, the patch is purged from the memory cache.
    """
    try:
        return apply_edit_use_case.execute(patch_id)
    except Exception as e:
        return f"Error applying edit: {str(e)}"

@mcp.tool()
def read_file(path: str) -> str:
    """
    Reads the complete text content of a file. 
    
    Restricted to safe text extensions only (e.g., .cpp, .py, .txt). Attempting to read binaries or restricted directories will fail. Use this to understand current architectural implementations before proposing edits.
    """
    try:
        return read_use_case.execute(path)
    except Exception as e:
        return f"Error reading file: {str(e)}"

@mcp.tool()
def list_directory(path: str = ".") -> str:
    """
    Lists files and folders in a given directory. 
    
    - Use '.' to query the workspace root.
    - Directories in the output are denoted with a trailing slash (e.g., 'src/').
    - Cannot traverse outside the hardcoded workspace root (passing '../' will throw a sandbox violation error).
    """
    try:
        items = list_use_case.execute(path)
        return "\n".join(items) if items else "Directory is empty."
    except Exception as e:
        return f"Error listing directory: {str(e)}"

@mcp.tool()
def search_codebase(directory: str, pattern: str) -> str:
    """
    Searches for a regex pattern across all allowed files in the specified directory. 
    
    Use '.' for the workspace root. The output is limited to 10,000 characters to prevent context window overflow. If truncated, refine your regex pattern.
    """
    try:
        results = search_use_case.execute(directory, pattern)
        output = "\n".join(results)
        if len(output) > 10000:
            return output[:10000] + "\n... [Output truncated due to length. Please use a more specific regex pattern.]"
        return output if output else "No matches found."
    except Exception as e:
        return f"Error searching files: {str(e)}"
    
@mcp.tool()
def advanced_search_codebase(
    directory: str, 
    pattern: str, 
    extension_filter: list[str] | None = None, 
    case_sensitive: bool = False, 
    context_lines: int = 2
) -> str:
    """
    Highly targeted regex search returning contextual surrounding lines.
    
    Parameters:
    - directory: Directory to search in relative to root (use '.' for root).
    - pattern: The regex pattern to execute.
    - extension_filter: Optional list of extensions to narrow the search (e.g., ['.cpp', '.h', '.cmake']). Reduces search time and noise significantly.
    - case_sensitive: Set to True for exact casing, False for case-insensitive matching.
    - context_lines: Number of lines to show immediately above and below the matched line to provide structural context.
    """
    try:
        results = advanced_search_use_case.execute(directory, pattern, extension_filter, case_sensitive, context_lines)
        output = "\n".join(results)
        if len(output) > 15000:
            return output[:15000] + "\n\n... [Output truncated due to length. Please use a more specific regex or extension filter.]"
        return output if output else "No matches found."
    except Exception as e:
        return f"Error in advanced search: {str(e)}"

@mcp.tool()
def get_pwd() -> str:
    """
    Returns the absolute path of the sandbox workspace root.
    
    You cannot access or modify any files outside this path. All file paths passed to other tools must be relative to this root.
    """
    return f"Workspace Root: {pwd_use_case.execute()}"

if __name__ == "__main__":
    print("Starting Secure MCP Workspace Server on port 8000...")
    mcp.run(transport="sse")