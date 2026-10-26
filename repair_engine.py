"""Observed-failure repairs with syntax units, receipts and validation rollback."""
import ast
import hashlib
import json
import re
import time
from pathlib import Path

from repair_protocol import symbols, compact_test_failure, failure_signature, parse_repair_response, declaration_changes, assertion_coverage


class NoProgressRepair(ValueError):
    """A well-formed response that changes no executable declarations."""


def boundary_focus(failure, originals, table):
    evidence = failure.get("diagnostics") or {}
    if evidence.get("category") not in (None, "answer_round_trip"):
        return None
    path, symbol = evidence.get("path"), evidence.get("symbol")
    if path in originals and symbol in table[path]:
        return {"path": path, "symbol": symbol, "observed": evidence}
    return None


def focused_retry(instruction, failure, originals, table, rejected_units, previous_response=True, basic=False):
    focus = boundary_focus(failure, originals, table)
    if not focus:
        return instruction + ("\nNO-PROGRESS RETRY: the following declarations were executable copies of the existing source: " +
            json.dumps(rejected_units) + ". Trace their inputs and called helpers; repair the first boundary "
            "where the observed value differs from the contract, rather than copying these callers again.")
    path, symbol = focus["path"], focus["symbol"]
    imports = [ast.get_source_segment(originals[path], node) for node in ast.parse(originals[path]).body
               if isinstance(node, (ast.Import, ast.ImportFrom))]
    supporting = {name: info["code"] for name, info in table[path].items()
                  if name != symbol and (name.startswith("_") or name.isupper())}
    requirements = ("Signed integers/fractions/mixed numbers and finite decimals preserve their exact "
        "numeric value as Fraction. Reject malformed/non-finite inputs and zero denominators with ValueError. "
        "Preserve the sign of the entire input, including -0 in a mixed number." if symbol == "parse_answer" else
        "Return bool from the answer checker. Fraction inputs require exact equality; decimal inputs alone "
        "may use an absolute Fraction tolerance of 1e-9. Valid exact values must check true.")
    if basic:
        requirements = ("Support ordinary non-negative fraction answers such as 3/4, 1/2 and 2/3, "
            "equivalent fractions and whole-number answers. Preserve exact Fraction values; no "
            "decimal approximation, precision tolerance or mixed-number requirements. Invalid input "
            "does not score; repeated submissions cannot score again.")
    introduction = ("The previous response made no executable change; repair the observed boundary instead. "
                    if previous_response else "Repair the independently observed failing boundary. ")
    return ("Return ONLY the repairs JSON schema. " + introduction +
        "Do not rewrite the caller "
        "or change correct question answers/tests to hide the failure. Replace the complete function "
        "listed below, retaining its public API and supported input formats. No comments-only fixes.\n" +
        "OBSERVED VALUES AND REQUIRED TARGET:\n" + json.dumps(focus, ensure_ascii=False) +
        "\nREPAIR SCHEMA: {\"repairs\":[{\"path\":\""+path+"\",\"reason\":\"observed root cause\","
        "\"replacements\":[{\"symbol\":\""+symbol+"\",\"code\":\"complete declaration\"}]}]}\n" +
        "CURRENT DECLARATION:\n" + table[path][symbol]["code"] +
        "\nMODULE IMPORTS:\n" + "\n".join(imports) +
        "\nREAD-ONLY SUPPORTING DECLARATIONS:\n" + json.dumps(supporting, ensure_ascii=False) +
        "\nREQUIREMENTS: " + requirements + " No new dependencies. "
        "Do not return a declaration that has the same executable AST as its current source.")


def production_paths(project, manifest):
    known = {f["path"] for f in manifest["files"] if f["path"].endswith(".py")}
    seen, pending = set(), ["main.py"]
    while pending:
        path = pending.pop()
        if path in seen or path not in known:
            continue
        seen.add(path)
        try:
            tree = ast.parse((project / path).read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            imports = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module] if isinstance(node, ast.ImportFrom) and node.module else []
            for name in imports:
                candidate = name.replace(".", "/")+".py"
                if candidate in known:
                    pending.append(candidate)
    return seen


def failure_record(job, error):
    message = str(error)
    product = job.destination(".agent/product-acceptance.json")
    validation = job.destination(".agent/validation.json")
    if "ACCEPTANCE" in message and product.is_file():
        report = json.loads(product.read_text(encoding="utf-8"))
        if report.get("status") == "failed":
            return {"stage": "product", "message": report.get("error", message),
                    "traceback": report.get("traceback", "")[-7000:],
                    "diagnostics": report.get("diagnostics", {})}
    if validation.is_file():
        report = json.loads(validation.read_text(encoding="utf-8"))
        if report.get("failures") and "Tests or Windows build failed" in message:
            return {"stage": "tests", "failures": report["failures"],
                    "groups": compact_test_failure(report)}
    return {"stage": "source", "message": message[-8000:]}


def fingerprint(failure):
    data = failure_signature(failure) if failure["stage"] == "tests" else failure.get("message")
    return hashlib.sha256(json.dumps([failure["stage"], data], sort_keys=True).encode()).hexdigest()


def settle(job, error=None):
    pending = job.state.get("pending_repair")
    if not pending:
        return False
    failure = failure_record(job, error) if error else None
    unchanged = failure is not None and fingerprint(failure) == pending["fingerprint"]
    regression = failure is not None and pending["stage"] == "tests" and failure["stage"] == "product"
    rollback = unchanged or regression
    receipt = job.destination(pending["archive"])
    outcome = "rolled_back_no_progress" if unchanged else "rolled_back_regression" if regression else "validated" if not error else "progress"
    if rollback:
        for change in pending["changes"]:
            target = job.destination(change["path"])
            if hashlib.sha256(target.read_bytes()).hexdigest() != change["after_hash"]:
                raise RuntimeError("A pending repair was edited externally; automatic rollback was stopped.")
        for change in pending["changes"]:
            target = job.destination(change["path"])
            target.write_bytes((receipt / "before" / change["path"]).read_bytes())
            job.state["completed"][change["path"]] = hashlib.sha256(target.read_bytes()).hexdigest()
        rejected = job.state.setdefault("rejected_repairs", {}).setdefault(pending["fingerprint"], [])
        hashes = job.state.setdefault("rejected_repair_hashes", {}).setdefault(pending["fingerprint"], [])
        for change in pending["changes"]:
            rejected.extend(change["units"])
            hashes.append(change["path"]+":"+change["after_hash"])
        job.emit("phase", "Reverted repair: validation did not improve" if unchanged else "Reverted repair: gameplay regressed")
    (receipt / "outcome.json").write_text(json.dumps({"outcome": outcome, "next_failure": failure}, indent=2), encoding="utf-8")
    job.state.pop("pending_repair", None)
    job.state.setdefault("repair_outcomes", []).append({"archive": pending["archive"], "outcome": outcome})
    job.state.pop("source_reviewed", None)
    job.checkpoint()
    return rollback


def repair(job, error, test_guard):
    failure = failure_record(job, error)
    manifest = job.state["manifest"]
    protected = job.state.get("protected_files", {})
    production = production_paths(job.project, manifest)
    if not production:
        production = {f["path"] for f in manifest["files"] if f["path"].endswith(".py") and not f["path"].startswith("tests/")}
    tests = {f["path"] for f in manifest["files"] if f["path"].startswith("tests/") and f["path"].endswith(".py")}
    source_tests = {p for p in tests if p in str(error).replace("\\", "/")} if failure["stage"] == "source" else set()
    editable = (production | (tests if failure["stage"] == "tests" else source_tests)) - set(protected)
    if failure["stage"] == "source" and not any(p in str(error).replace("\\", "/") for p in editable):
        return False  # Missing tools/build infrastructure is not a game-code defect.
    originals = {p: job.destination(p).read_text(encoding="utf-8") for p in sorted(editable)
                 if job.destination(p).is_file() and p in job.state["completed"]}
    table = {p: symbols(source) for p, source in originals.items()}
    failed_names = {n for f in failure.get("failures", []) for n in re.findall(r"::(test\w+)", f["nodeid"])}
    sources = []
    allowed_symbols = {}
    for path, source in originals.items():
        exposed = table[path]
        if path in tests:
            exposed = {name: info for name, info in exposed.items() if "." in name and
                       (path in source_tests or not name.rsplit(".", 1)[-1].startswith("test") or name.rsplit(".", 1)[-1] in failed_names)}
            # Top-level pytest functions also remain editable when they failed.
            exposed.update({name: info for name, info in table[path].items() if name in failed_names})
            source = "\n\n".join(info["code"] for name, info in exposed.items())
        sources.append({"path": path, "symbols": list(exposed), "source": source})
        allowed_symbols[path] = set(exposed)
    # The public close lifecycle is essential evidence for teardown failures.
    framework = job.destination("forge_ui.py")
    lifecycle = symbols(framework.read_text(encoding="utf-8"))["GameShell.close"]["code"] if framework.is_file() else ""
    key = fingerprint(failure)
    blocked = job.state.get("rejected_repairs", {}).get(key, [])
    rejected_hashes = job.state.get("rejected_repair_hashes", {}).get(key, [])
    description = {k: v for k, v in failure.items() if k != "failures"}
    basic = job.contract_version == 3
    test_evidence = {path: assertion_coverage(source) for path, source in originals.items() if path in tests}
    description["test_contract_evidence"] = test_evidence
    focus = boundary_focus(failure, originals, table)
    acceptance = job.destination(".agent/product-acceptance.json")
    passed_evidence = []
    if failure["stage"] == "tests" and acceptance.is_file():
        accepted = json.loads(acceptance.read_text(encoding="utf-8"))
        if accepted.get("status") == "passed":
            passed_evidence = list(dict.fromkeys(e for e in accepted.get("evidence", []) if
                not any(noise in e for noise in ("control", "screen is", "Tkinter callback", "visibly"))))[:100]
    instruction = (
        'Return ONLY JSON {"repairs":[{"path":"file.py","reason":"observed root cause",'
        '"test_contract_error":"","contract_evidence":"",'
        '"replacements":[{"symbol":"Class.method_or_function","code":"complete declaration"}]}]}. '
        "Use at most three files and only the few declarations needed. No old-text snippets, no full files, no code fences. "
        "Copy symbol names from the supplied inventories. Do not add unlisted top-level helpers; use local helpers if needed. Method code starts with def (or its decorator), not class. "
        "The replacement retains its declaration name and public API. It replaces the entire function/method/constant. "
        "Trace the ACTUAL failure phase. A teardown failure after app.close() followed by root.destroy() is a test "
        "fixture bug: close already destroys root. Correct that fixture, not production behavior. "
        + ("Use exact Fraction equality for ordinary fractions and whole numbers only. No decimal precision or mixed-number tests. " if basic else
        "Use exact rational math when judging test expectations: for 5/6, decimal 0.833333333335 is INSIDE the legacy decimal tolerance; 0.833333335 is OUTSIDE. ") +
        "Correct contradictory tests only with test_contract_error and contract_evidence; retain every test name "
        "and assertion coverage, no skips. An invented private API in a test must be replaced with real widgets. "
        "Product acceptance failures may NEVER be fixed by changing a test or protected framework. "
        "Prefer tests/fixtures when product behavior already passed. Never change correct implementation to match "
        "an invalid test. Fix shared causes in one request. Previously unsuccessful symbols are listed below; "
        "revisit the root cause and propose a DIFFERENT implementation, never repeat the rejected source. "
        + ("Fraction and whole-number inputs require EXACT equality. " if basic else
           "Fraction inputs containing '/' require EXACT equality; ONLY decimal input can use 1e-9 tolerance. ") +
        "Session.submit must use check_answer after validating parseability, rather than duplicating its arithmetic. "
        "Keep reasons brief (one sentence); output final JSON only, without reasoning prose. "
        "If no justified repair exists, return an empty repairs array.\nFAILURE:\n" + json.dumps(description, ensure_ascii=False) +
        "\nPREVIOUS NO-PROGRESS SYMBOLS (DO NOT REPEAT THEIR REJECTED IMPLEMENTATIONS):\n" + json.dumps(blocked) +
        "\nREAD-ONLY FRAMEWORK LIFECYCLE:\n" + lifecycle +
        "\nCURRENT EDITABLE SOURCE AND SYMBOL INVENTORIES:\n" + json.dumps(sources, ensure_ascii=False) +
        "\nINDEPENDENT PRODUCT CHECKS ALREADY PASSED:\n" + json.dumps(passed_evidence) +
        "\nFINAL REPAIR RULES: read the failing TEST'S setup and submissions before editing production. "
        "A numeric wrong answer such as '0' is a valid attempt; 'wrong' or 'garbage' is MALFORMED and "
        "must NOT consume an attempt or enable Next. If a score/accuracy test uses a word as its wrong-answer "
        "fixture but expects an attempt, correct the fixture to a valid incorrect number. "
        "A replay/results test must finish ALL fixture questions through Check and Next; one Next cannot "
        "finish a session containing multiple questions. Correct that test's setup/flow, not progression. "
        "Do not change production to contradict the passed checks above. Output the actual corrected "
        "declarations, not copies of the existing functions, and include contract evidence for test corrections." +
        "\nAn assertRaises block containing only pass is impossible and checks no operation. It may be "
        "removed or replaced. Preserve the real operation and all original assertions about object state. "
        "Replacing an impossible exception block with the actual failing operation can consolidate "
        "return-value/message checks into an exception check; that is allowed when the original calls "
        "and state checks are retained. Do not add pointless assertions to satisfy a raw count. "
        "Test repeated-submit prevention by checking score, attempted count and question index stay unchanged. "
        "Do not force production to throw an exception solely because an invalid test demands one. " +
        "\nINDEPENDENTLY OBSERVED FAILING BOUNDARY (when present, fix this boundary before its callers):\n" +
        json.dumps(focus, ensure_ascii=False))
    if focus and failure["stage"] == "product":
        # Objective boundary evidence is more useful than a whole-project dump.
        instruction = focused_retry(instruction, failure, originals, table, [], previous_response=False, basic=basic)
    job.emit("phase", "Repairing observed validation failures")
    for attempt in range(2):
        raw = ""
        ignored = []
        try:
            raw = job.request("Repair validation declarations", instruction,
                              min(job.limit, 16384) if not attempt else job.limit, True)
            record = parse_repair_response(raw)
            if not isinstance(record, dict):
                raise ValueError("Repair response must be a JSON object.")
            repairs = record.get("repairs")
            if repairs == []:
                return False
            if not isinstance(repairs, list) or not 1 <= len(repairs) <= 3:
                raise ValueError("Return one to three repair objects.")
            updates = {}
            seen_paths = set()
            for item in repairs:
                if not isinstance(item, dict):
                    raise ValueError("Each repair must be an object.")
                path = item.get("path")
                if not isinstance(path, str) or path not in originals or path in seen_paths:
                    raise ValueError("Unknown, protected or repeated repair path: " + str(path))
                seen_paths.add(path)
                if path in tests and not (item.get("test_contract_error") and item.get("contract_evidence")):
                    raise ValueError("Test correction requires explicit contract evidence.")
                if not isinstance(item.get("replacements"), list) or not item["replacements"] or not all(isinstance(r, dict) and isinstance(r.get("symbol"), str) for r in item["replacements"]):
                    raise ValueError("Provide nonempty replacement objects with symbol names.")
                for replacement in item["replacements"]:
                    # Some providers repeat the selected path in a qualified
                    # symbol; it is redundant, not a different declaration.
                    name = replacement.get("symbol", "")
                    if name.startswith(path+":"):
                        replacement["symbol"] = name[len(path)+1:]
                units = [path+":"+r.get("symbol", "") for r in item["replacements"]]
                if any(r.get("symbol") not in allowed_symbols[path] for r in item["replacements"]):
                    raise ValueError("Use a declaration from this file's exposed symbol inventory.")
                updated, meaningful = declaration_changes(originals[path], item["replacements"])
                if not meaningful:
                    ignored.extend(units)
                    continue
                units = [path+":"+r["symbol"] for r in meaningful]
                digest = hashlib.sha256(updated.encode("utf-8")).hexdigest()
                if path+":"+digest in rejected_hashes:
                    raise ValueError("This exact source was already rejected for making no validation progress.")
                if path in tests:
                    test_guard(originals[path], updated)
                if updated == originals[path]:
                    raise ValueError("Repair made no source change.")
                updates[path] = (updated, units)
            if not updates:
                raise NoProgressRepair("The response changes no executable declarations: " + ", ".join(ignored))
            break
        except Exception as invalid:
            # Network/auth/budget failures are not formatting retries.
            recoverable = isinstance(invalid, (ValueError, SyntaxError, KeyError, TypeError)) or getattr(invalid, "output_limited", False)
            if not recoverable:
                raise
            rejected = job.destination(".agent/rejected-repairs/"+str(time.time_ns())+".json")
            rejected.parent.mkdir(parents=True, exist_ok=True)
            rejected.write_text(json.dumps({"response": raw, "error": str(invalid),
                "category": "no_progress" if isinstance(invalid, NoProgressRepair) else "invalid_response",
                "failure": failure}), encoding="utf-8")
            if attempt:
                detail = ""
                if focus:
                    observed = focus["observed"]
                    detail = (f" Inspect {focus['path']}:{focus['symbol']}: input {observed.get('input')!r}, "
                              f"expected {observed.get('expected')}, observed {observed.get('parsed', observed.get('parse_exception'))}.")
                raise ValueError("Automatic repair did not produce a valid change; original source preserved. " +
                                 failure.get("message", "Generated tests still fail.") + detail +
                                 " Rejected responses are saved in .agent/rejected-repairs.") from None
            if isinstance(invalid, NoProgressRepair):
                instruction = focused_retry(instruction, failure, originals, table, ignored, basic=basic)
                job.emit("phase", "Repair made no executable change; focusing retry on the failing boundary")
            else:
                instruction += "\nPrevious response was rejected: " + str(invalid) + " Return a smaller valid declaration repair; use the exact inventory names."
                job.emit("phase", "Retrying declaration repair with validation feedback")
    archive = job.destination(".agent/repairs/"+str(time.time_ns()))
    changes = []
    for path, (updated, units) in updates.items():
        for directory, contents in (("before", originals[path]), ("after", updated)):
            saved = archive / directory / path
            saved.parent.mkdir(parents=True, exist_ok=True)
            saved.write_text(contents, encoding="utf-8", newline="\n")
        changes.append({"path": path, "units": units, "after_hash": ""})
    (archive / "repair.json").write_text(json.dumps({"response": record, "failure": failure, "ignored_no_op_units": ignored}, indent=2), encoding="utf-8")
    for change in changes:
        target = job.destination(change["path"])
        target.write_bytes((archive / "after" / change["path"]).read_bytes())
        change["after_hash"] = hashlib.sha256(target.read_bytes()).hexdigest()
        job.state["completed"][change["path"]] = change["after_hash"]
        job.emit("phase", "Applied repair: " + change["path"])
    job.state["pending_repair"] = {"archive": archive.relative_to(job.project).as_posix(),
        "fingerprint": key, "stage": failure["stage"], "changes": changes}
    job.state.pop("source_reviewed", None)
    job.checkpoint()
    return True
