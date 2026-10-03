"""Public-copy path substitution only; raw local originals remain immutable."""
def sanitize(data: bytes, workspace_root: str) -> bytes:
    return data.replace(workspace_root.encode("utf-8"), b"/workspace/Entrotter")
