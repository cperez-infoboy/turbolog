#!/usr/bin/env python3
"""Additive-migration guard (CI gate).

Scans Alembic migration files NEWER than the pinned baseline revision and
FAILS the build if any ``upgrade()`` body contains a non-additive op.

Grandfathering
--------------
Every revision up to and INCLUDING the baseline (default
``c1d2e3f4a5b6`` — the current production head) is EXCLUDED. The existing
chain uses ``op.drop_table`` in ``upgrade()`` (e.g. ``68c029c4286e`` drops
``jira_connections``) and ``op.drop_*`` in EVERY ``downgrade()``, so a
blanket scan would block every deploy. Only ``upgrade()`` bodies are ever
scanned — never ``downgrade()``.

Rejected operations (non-additive)
----------------------------------
- ``op.drop_table`` / ``op.drop_column`` / ``op.drop_index``
- ``op.alter_column(..., nullable=False)``  (nullable -> NOT NULL)
- ``op.create_primary_key`` / ``op.drop_constraint(type_ in {primary, pk})``
- ``op.alter_column(..., type_=...)``       (column type change)

Type changes (possible narrows)
-------------------------------
A static AST scan cannot reliably distinguish a narrow (``String(255)`` ->
``String(50)``) from a widen, so by default ANY ``alter_column`` with a
``type_=`` kwarg is REJECTED. A genuinely safe, additive type change can be
explicitly allow-listed by the author with the inline comment marker on the
SAME source line as the ``alter_column`` call::

    op.alter_column("t", "c", type_=sa.String(255))  # additive: allow-type-change

This keeps the gate spec-compliant (narrows fail) while avoiding
false-positive blocking of safe widens via a reviewer-visible justification.

The upgrade->downgrade->upgrade round-trip run separately by CI (seeded with
NULL rows) is defense-in-depth; this op-scan is the AUTHORITY for additivity
(it catches nullable->non-null that an empty-DB round-trip misses).

Exit codes: 0 = additive, 1 = non-additive op found, 2 = config error.
"""
from __future__ import annotations

import argparse
import ast
import pathlib
import sys

BASELINE_DEFAULT = "c1d2e3f4a5b6"

# ops that are always destructive in upgrade()
DROP_OPS = {"drop_table", "drop_column", "drop_index"}
# PK-altering ops
PK_CREATE = {"create_primary_key"}
PK_CONSTRAINT_TYPES = {"primary", "pk", "primary_key"}

# Inline marker that allow-lists a type change as additive (a widen).
TYPE_CHANGE_ALLOW_MARKER = "additive: allow-type-change"


def _assignments(tree: ast.AST):
    """Yield (target_name, value_node) for top-level Assign and AnnAssign nodes."""
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    yield target.id, node.value
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.value is not None:
                yield node.target.id, node.value


def _extract_revision_data(
    tree: ast.AST,
) -> tuple[str | None, object, ast.FunctionDef | None]:
    """Return (revision, down_revision, upgrade_funcdef).

    ``down_revision`` is the raw literal value (str, None, or tuple) or the
    sentinel object ``_UNSET`` when the module does not define it.
    """
    _UNSET = object()
    revision: str | None = None
    down_revision: object = _UNSET
    upgrade_fn: ast.FunctionDef | None = None
    for name, value in _assignments(tree):
        if name == "revision":
            try:
                revision = ast.literal_eval(value)
            except ValueError:
                revision = None
        elif name == "down_revision":
            try:
                down_revision = ast.literal_eval(value)
            except ValueError:
                down_revision = _UNSET
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "upgrade":
            upgrade_fn = node
            break
    return revision, down_revision, upgrade_fn


def _op_attr(call: ast.Call) -> str | None:
    """Return the attribute name for an ``op.<attr>(...)`` call, else None."""
    func = call.func
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "op":
        return func.attr
    return None


def _kwarg_value(call: ast.Call, name: str) -> ast.AST | None:
    for kw in call.keywords:
        if kw.arg == name:
            return kw.value
    return None


def _literal(node: ast.AST | None):
    """Best-effort literal evaluation; returns None if not a literal."""
    if node is None:
        return None
    try:
        return ast.literal_eval(node)
    except ValueError:
        return None


def scan_upgrade(upgrade_fn: ast.FunctionDef, source_lines: list[str], path: pathlib.Path) -> list[str]:
    """Return a list of violation messages for one ``upgrade()`` body."""
    violations: list[str] = []
    for node in ast.walk(upgrade_fn):
        if not isinstance(node, ast.Call):
            continue
        attr = _op_attr(node)
        if attr is None:
            continue
        lineno = getattr(node, "lineno", "?")

        if attr in DROP_OPS:
            violations.append(f"{path.name}:{lineno}: non-additive op op.{attr}() in upgrade()")
            continue

        if attr in PK_CREATE:
            violations.append(f"{path.name}:{lineno}: primary-key change op.{attr}() in upgrade()")
            continue

        if attr == "drop_constraint":
            t = _literal(_kwarg_value(node, "type_"))
            if isinstance(t, str) and t.lower() in PK_CONSTRAINT_TYPES:
                violations.append(
                    f"{path.name}:{lineno}: PK constraint drop op.drop_constraint(type_={t!r}) in upgrade()"
                )
            continue

        if attr == "alter_column":
            nullable_val = _literal(_kwarg_value(node, "nullable"))
            if nullable_val is False:
                violations.append(
                    f"{path.name}:{lineno}: op.alter_column(..., nullable=False) tightens a column in upgrade()"
                )
            if _kwarg_value(node, "type_") is not None:
                # Type change: reject unless the author allow-listed this line.
                line = source_lines[lineno - 1] if 1 <= lineno <= len(source_lines) else ""
                if TYPE_CHANGE_ALLOW_MARKER not in line:
                    violations.append(
                        f"{path.name}:{lineno}: op.alter_column(..., type_=...) changes a column type "
                        f"in upgrade() (additive widens may be marked with "
                        f"'# {TYPE_CHANGE_ALLOW_MARKER}')"
                    )
            continue

    return violations


def parse_versions(versions_dir: pathlib.Path):
    """Yield (revision, down_revision_raw, upgrade_fn, path) per migration file.

    Skips files that fail to parse or lack a revision id.
    """
    for path in sorted(versions_dir.glob("*.py")):
        if path.name.startswith("__"):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            print(f"error: cannot parse {path.name}: {exc}", file=sys.stderr)
            continue
        rev, down, upgrade_fn = _extract_revision_data(tree)
        if rev is None:
            continue
        yield rev, down, upgrade_fn, path


def _is_descendant(rev: str, parent_map: dict[str, object], baseline: str) -> bool:
    """True if ``baseline`` is a proper ancestor of ``rev``.

    Handles tuple ``down_revision`` values (merge migrations) by walking all
    ancestor branches.
    """
    if rev == baseline:
        return False
    frontier: list[str] = []
    p = parent_map.get(rev)
    if isinstance(p, tuple):
        frontier.extend(x for x in p if isinstance(x, str))
    elif isinstance(p, str):
        frontier.append(p)
    seen: set[str] = set()
    while frontier:
        cur = frontier.pop()
        if cur in seen:
            continue
        seen.add(cur)
        if cur == baseline:
            return True
        np = parent_map.get(cur)
        if isinstance(np, tuple):
            frontier.extend(x for x in np if isinstance(x, str))
        elif isinstance(np, str):
            frontier.append(np)
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Additive-migration guard (CI gate).")
    parser.add_argument("--versions-dir", default="backend/alembic/versions")
    parser.add_argument("--baseline", default=BASELINE_DEFAULT)
    args = parser.parse_args()

    versions_dir = pathlib.Path(args.versions_dir)
    if not versions_dir.is_dir():
        print(f"error: versions dir not found: {versions_dir}", file=sys.stderr)
        return 2

    parsed = list(parse_versions(versions_dir))
    parent_map: dict[str, object] = {rev: down for rev, down, _, _ in parsed}

    if args.baseline not in parent_map:
        print(
            f"error: baseline revision {args.baseline} not found in {versions_dir}",
            file=sys.stderr,
        )
        return 2

    descendants = sorted(
        rev for rev, _, _, _ in parsed if _is_descendant(rev, parent_map, args.baseline)
    )

    if not descendants:
        print(f"ok: no migrations newer than baseline {args.baseline}; nothing to scan.")
        return 0

    print(f"scanning {len(descendants)} migration(s) newer than baseline {args.baseline}:")
    print("  - " + "\n  - ".join(descendants))

    parsed_by_rev = {rev: (upgrade_fn, path) for rev, _, upgrade_fn, path in parsed}
    all_violations: list[str] = []
    for rev in descendants:
        upgrade_fn, path = parsed_by_rev[rev]
        if upgrade_fn is None:
            print(f"warn: {rev} ({path.name}) has no upgrade() function; skipping.", file=sys.stderr)
            continue
        source_lines = path.read_text(encoding="utf-8").splitlines()
        all_violations.extend(scan_upgrade(upgrade_fn, source_lines, path))

    if all_violations:
        print("\nNON-ADDITIVE MIGRATION(S) DETECTED — deploy blocked:", file=sys.stderr)
        for msg in all_violations:
            print(f"  - {msg}", file=sys.stderr)
        print(
            "\nMigrations MUST be backward-compatible (additive). Destructive changes "
            "require a manual migrate-first ops procedure.",
            file=sys.stderr,
        )
        return 1

    print(f"ok: all {len(descendants)} new migration(s) are additive.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
