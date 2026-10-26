"""Small, syntax-aware repair units. No model-provided search strings are used."""
import ast
import json
import textwrap


def parse_repair_response(raw):
    """Accept a complete final object after an explicit provider boundary only."""
    text = raw.strip()
    if text.startswith("```") and text.endswith("```"):
        text = "\n".join(text.splitlines()[1:-1])
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        for marker in ("<｜end▁of▁thinking｜>", "</think>"):
            if marker in text:
                return json.loads(text.rsplit(marker, 1)[1].strip())
        raise


def symbols(source):
    tree = ast.parse(source)
    result = {}
    lines = source.splitlines(keepends=True)

    def walk(body, prefix=""):
        for node in body:
            name = None
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                name = node.name
            elif not prefix and isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if len(targets) == 1 and isinstance(targets[0], ast.Name):
                    name = targets[0].id
            if name:
                key = prefix + name
                start = min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])])-1
                if key in result:
                    raise ValueError("Duplicate Python symbol: " + key)
                result[key] = {"start": start, "end": node.end_lineno,
                    "indent": node.col_offset, "code": "".join(lines[start:node.end_lineno])}
                if isinstance(node, ast.ClassDef):
                    walk(node.body, key + ".")
    walk(tree.body)
    return result


def replace_symbols(source, replacements):
    if not isinstance(replacements, list) or not replacements:
        raise ValueError("Provide a nonempty replacements array.")
    table = symbols(source)
    changes = []
    seen = set()
    for replacement in replacements:
        key, code = replacement.get("symbol"), replacement.get("code")
        if key not in table or key in seen or not isinstance(code, str) or not code.strip():
            raise ValueError("Unknown/repeated symbol. Available: " + ", ".join(table))
        seen.add(key)
        old = table[key]
        clean = textwrap.dedent(code).strip()+"\n"
        tree = ast.parse(clean)
        # One complete declaration, retaining its public name/type.
        declaration = tree.body[0] if len(tree.body) == 1 else None
        expected = key.rsplit(".", 1)[-1]
        targets = declaration.targets if isinstance(declaration, ast.Assign) else [declaration.target] if isinstance(declaration, ast.AnnAssign) else []
        names = [n.id for n in targets if isinstance(n, ast.Name)]
        if not declaration or (getattr(declaration, "name", None) != expected and
                not (isinstance(declaration, (ast.Assign, ast.AnnAssign)) and expected in names)):
            raise ValueError("Replacement must be one complete declaration named " + expected)
        changes.append((old["start"], old["end"], textwrap.indent(clean, " "*old["indent"])))
    changes.sort()
    if any(changes[i][1] > changes[i+1][0] for i in range(len(changes)-1)):
        raise ValueError("Overlapping class/method replacements; choose one level.")
    lines = source.splitlines(keepends=True)
    for start, end, code in reversed(changes):
        lines[start:end] = [code]
    updated = "".join(lines)
    ast.parse(updated)
    return updated


def compact_test_failure(report):
    """Group identical teardown failures instead of sending pages of duplicates."""
    groups = {}
    for failure in report.get("failures", []):
        key = (failure.get("when"), failure.get("message"))
        group = groups.setdefault(key, {"when": key[0], "message": key[1], "tests": [],
                                       "traceback": failure.get("traceback", "")[-5000:]})
        group["tests"].append(failure.get("nodeid"))
    return list(groups.values())


def failure_signature(report):
    return sorted({(f.get("nodeid", ""), f.get("when", ""), f.get("message", ""))
                   for f in report.get("failures", [])})


def declaration_changes(original, replacements):
    """Validate a complete proposal, retaining only executable AST changes."""
    updated = replace_symbols(original, replacements)
    # Compare bodies without docstrings: a new comment/docstring is not a fix.
    def executable(source):
        tree = ast.parse(source)
        for node in ast.walk(tree):
            body = getattr(node, "body", None)
            if isinstance(body, list) and body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
                node.body = body[1:]
        return ast.dump(tree)
    if executable(original) == executable(updated):
        return original, []
    table = symbols(original)
    changed = [replacement for replacement in replacements if executable(
        textwrap.dedent(table[replacement["symbol"]]["code"])) != executable(textwrap.dedent(replacement["code"]))]
    return replace_symbols(original, changed), changed


def assertion_coverage(source):
    """Count real checks per test; empty exception contexts check no behavior."""
    tree = ast.parse(source)
    tests, empty = {}, []
    def walk(body, prefix=""):
        for node in body:
            if isinstance(node, ast.ClassDef):
                walk(node.body, prefix+node.name+".")
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
                name = prefix+node.name
                ignored = set()
                for context in ast.walk(node):
                    if not isinstance(context, (ast.With, ast.AsyncWith)) or len(context.items) != 1:
                        continue
                    call = context.items[0].context_expr
                    fn = call.func if isinstance(call, ast.Call) else None
                    raises = isinstance(fn, ast.Attribute) and (fn.attr in {"assertRaises", "assertRaisesRegex"} or
                        fn.attr == "raises" and isinstance(fn.value, ast.Name) and fn.value.id == "pytest")
                    passive = all(isinstance(s, ast.Pass) or isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant) for s in context.body)
                    if raises and passive:
                        ignored.add(id(call))
                        empty.append({"test": name, "line": context.lineno,
                                      "reason": "An exception assertion around an empty/pass body cannot test an operation."})
                tests[name] = sum(isinstance(n, ast.Assert) or isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and
                                 (n.func.attr.startswith("assert") or n.func.attr == "raises" and
                                  isinstance(n.func.value, ast.Name) and n.func.value.id == "pytest") and
                                 id(n) not in ignored for n in ast.walk(node))
    walk(tree.body)
    skips = sum(isinstance(n, ast.Attribute) and n.attr in
                {"skip", "skipIf", "skipUnless", "skipTest", "xfail", "importorskip"} for n in ast.walk(tree))
    return {"tests": tests, "empty_exception_contexts": empty, "skips": skips}


def recovers_empty_exception_test(before, after, name):
    """Permit replacing an impossible context with a real operation and state checks."""
    if name not in {e['test'] for e in assertion_coverage(before)['empty_exception_contexts']}:
        return False
    old_table, new_table = symbols(before), symbols(after)
    if name not in old_table or name not in new_table:
        return False
    old = ast.parse(textwrap.dedent(old_table[name]['code']))
    new = ast.parse(textwrap.dedent(new_table[name]['code']))
    def assertions(tree):
        return [n for n in ast.walk(tree) if isinstance(n, ast.Assert) or isinstance(n, ast.Call) and
                isinstance(n.func, ast.Attribute) and n.func.attr.startswith('assert')]
    def state_assertions(tree):
        found = set()
        for node in assertions(tree):
            arguments = node.args if isinstance(node, ast.Call) else [node.test]
            if any(isinstance(child, ast.Attribute) for arg in arguments for child in ast.walk(arg)):
                found.add(ast.dump(node))
        return found
    def operations(tree):
        return {ast.dump(n) for n in ast.walk(tree) if isinstance(n, ast.Call) and
                not (isinstance(n.func, ast.Attribute) and n.func.attr.startswith('assert'))}
    has_real_context = any(isinstance(n, ast.With) and any(
        isinstance(i.context_expr, ast.Call) and isinstance(i.context_expr.func, ast.Attribute) and
        i.context_expr.func.attr in {'assertRaises','assertRaisesRegex'} for i in n.items) and
        operations(n) for n in ast.walk(new))
    return bool(has_real_context and operations(old) <= operations(new) and
                state_assertions(old) <= state_assertions(new) and assertions(new))
