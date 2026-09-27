"""A static read of a transform before it runs.

## This is ergonomics, not security

Say it plainly, because a design that claims otherwise will be believed and
then breached. Every check here is trivially bypassable - `pd.read_csv` opens a
file, `pd.read_sql` opens a socket, and neither is an `import`. Anyone trying
to get around this will.

The actual boundary is the container: `--network none`, no credentials, no host
mounts, read-only root, `--cap-drop ALL`. That is what makes exfiltration fail.
This module exists so an *honest mistake* - `import requests` in code pasted
from a notebook - produces a clear sentence in a second rather than a confusing
failure thirty seconds later inside a container with no DNS.

Treat a pass here as "nothing obviously wrong", never as "this code is safe".
"""

from __future__ import annotations

import ast

# What a feature transform plausibly needs. Deliberately short: adding to it
# costs nothing but a line, and a long list invites the belief that the list is
# doing something.
ALLOWED_IMPORTS = frozenset({
    "pandas", "numpy", "np", "pd",
    "math", "statistics", "random", "re", "datetime", "decimal", "fractions",
    "itertools", "functools", "operator", "collections", "typing", "dataclasses",
    "warnings", "enum", "abc", "copy", "string", "textwrap", "unicodedata",
    "sklearn", "scipy",
})

# Names whose presence is a mistake worth naming rather than letting the
# container swallow. Not a security boundary - see the module docstring.
FLAGGED_NAMES = {
    "__import__": "dynamic import",
    "eval": "eval",
    "exec": "exec",
    "compile": "compile",
    "open": "file access",
    "input": "reading stdin, which carries this runner's protocol",
}

ENTRYPOINT = "transform"


class GuardError(Exception):
    """A refusal with a sentence a researcher can act on."""


def check(source: str) -> list[str]:
    """Parse and inspect `source`. Returns warnings; raises `GuardError`.

    The parse itself is the most valuable part: a syntax error caught here
    names a line number, where the same error inside the container arrives as a
    traceback through two layers of JSON.
    """
    try:
        tree = ast.parse(source, filename="transform.py")
    except SyntaxError as e:
        raise GuardError(
            f"line {e.lineno}: {e.msg}"
        ) from None

    _check_entrypoint(tree)
    warnings = _check_imports(tree)
    warnings += _check_names(tree)
    return warnings


def _check_entrypoint(tree: ast.Module) -> None:
    """There must be a top-level `transform(df)`.

    Checked before anything runs, because the alternative is importing the
    module, finding no entrypoint, and reporting it after the researcher has
    already waited for a container start.
    """
    fns = [n for n in tree.body
           if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
           and n.name == ENTRYPOINT]
    if not fns:
        defined = sorted(n.name for n in tree.body
                         if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))
        found = f" Found: {', '.join(defined)}." if defined else ""
        raise GuardError(
            f"No top-level function named `{ENTRYPOINT}`.{found} "
            f"Define `def {ENTRYPOINT}(df):` and return a DataFrame."
        )

    fn = fns[-1]
    if isinstance(fn, ast.AsyncFunctionDef):
        raise GuardError(f"`{ENTRYPOINT}` must be a plain function, not `async def`.")

    args = fn.args
    positional = len(args.posonlyargs) + len(args.args)
    required = positional - len(args.defaults)
    if args.vararg is None and (positional < 1 or required > 1):
        raise GuardError(
            f"`{ENTRYPOINT}` must take exactly one argument, the DataFrame. "
            f"It takes {positional}."
        )


def _check_imports(tree: ast.Module) -> list[str]:
    warnings: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            # A relative import has no module and nothing to resolve to.
            names = [node.module or ""]
        else:
            continue

        for name in names:
            root = name.split(".")[0]
            if root and root not in ALLOWED_IMPORTS:
                raise GuardError(
                    f"line {node.lineno}: `{name}` is not available here. The "
                    "sandbox has no network, no credentials and no host files, "
                    f"so `{root}` would not work even if it were importable. "
                    f"Available: {', '.join(sorted(ALLOWED_IMPORTS))}."
                )
    return warnings


def _check_names(tree: ast.Module) -> list[str]:
    warnings: list[str] = []
    seen = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in FLAGGED_NAMES:
            if node.id in seen:
                continue
            seen.add(node.id)
            raise GuardError(
                f"line {node.lineno}: `{node.id}` ({FLAGGED_NAMES[node.id]}) is "
                "not available here. There are no files to read and no code to "
                "load - everything the transform needs arrives as its argument."
            )
    return warnings
