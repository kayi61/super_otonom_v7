"""One-shot: test_5000_phase*.py içinde bulk_check.check / bc → assert (AST)."""

from __future__ import annotations

import ast
import sys
from pathlib import Path


def _strip_bulk_check_arg(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
    args = fn.args
    names = [a.arg for a in args.args]
    if "bulk_check" not in names:
        return
    i = names.index("bulk_check")
    new_args = args.args[:i] + args.args[i + 1 :]
    na = len(args.args)
    nd = len(args.defaults)
    if nd == 0:
        new_defaults: list[ast.expr] = []
    else:
        fm = na - nd
        if i < fm:
            new_defaults = list(args.defaults)
        else:
            di = i - fm
            new_defaults = list(args.defaults[:di]) + list(args.defaults[di + 1 :])
    args.args = new_args
    args.defaults = new_defaults


def _filter_bc_assign(body: list[ast.stmt]) -> list[ast.stmt]:
    out: list[ast.stmt] = []
    for stmt in body:
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
            t = stmt.targets[0]
            if isinstance(t, ast.Name) and t.id == "bc":
                v = stmt.value
                if isinstance(v, ast.Attribute) and v.attr == "check":
                    if isinstance(v.value, ast.Name) and v.value.id == "bulk_check":
                        continue
        out.append(stmt)
    return out


class _ConvertCalls(ast.NodeTransformer):
    def visit_Call(self, node: ast.Call) -> ast.AST:
        self.generic_visit(node)
        is_bulk = (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "check"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "bulk_check"
        )
        is_bc = isinstance(node.func, ast.Name) and node.func.id == "bc"
        if not (is_bulk or is_bc):
            return node
        if len(node.args) < 2 or len(node.args) > 3 or node.keywords:
            return node
        label, ok = node.args[0], node.args[1]
        if len(node.args) == 2:
            msg: ast.expr = label
        else:
            detail = node.args[2]
            msg = ast.BinOp(
                left=ast.BinOp(left=label, op=ast.Add(), right=ast.Constant(value=" | ")),
                op=ast.Add(),
                right=detail,
            )
        new = ast.Assert(test=ok, msg=msg)
        return ast.copy_location(new, node)


class _ProcessFunctions(ast.NodeTransformer):
    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.FunctionDef:
        _strip_bulk_check_arg(node)
        node.body = _filter_bc_assign(node.body)
        self.generic_visit(node)
        return node

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AsyncFunctionDef:
        _strip_bulk_check_arg(node)
        node.body = _filter_bc_assign(node.body)
        self.generic_visit(node)
        return node


def convert_file(path: Path) -> bool:
    src = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        print(f"SKIP parse {path}: {e}", file=sys.stderr)
        return False
    tree = _ConvertCalls().visit(tree)
    ast.fix_missing_locations(tree)
    tree = _ProcessFunctions().visit(tree)
    ast.fix_missing_locations(tree)
    try:
        out = ast.unparse(tree)
    except AttributeError:
        print("ast.unparse requires Python 3.9+", file=sys.stderr)
        return False
    if not out.endswith("\n"):
        out += "\n"
    path.write_text(out, encoding="utf-8")
    return True


def main() -> None:
    root = Path(__file__).resolve().parents[1] / "tests"
    paths = sorted(root.glob("test_5000_phase*.py"))
    if not paths:
        print("no test_5000_phase*.py", file=sys.stderr)
        sys.exit(1)
    for p in paths:
        convert_file(p)
        print(p.name)


if __name__ == "__main__":
    main()
