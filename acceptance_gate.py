"""Independent product acceptance. Never added to the model's editable manifest.

Runs in a separate interpreter from generated tests. The same checks also run
inside the frozen game via a temporary PyInstaller runtime hook.
"""
import json
import ast
import os
import re
import sys
import tempfile
import traceback
from fractions import Fraction
from pathlib import Path


class AcceptanceFailure(AssertionError):
    def __init__(self, message, diagnostics=None):
        super().__init__("ACCEPTANCE: " + message)
        self.diagnostics = diagnostics or {}


def answer_roundtrip_evidence(domain, expected, text, question=None):
    """Observe each public boundary rather than blaming its final caller."""
    evidence = {"category": "answer_round_trip", "input": text,
                "expected": str(expected), "path": "domain.py"}
    if question is not None:
        evidence["question"] = {"id": question.id, "prompt": question.prompt}
    try:
        parsed = domain.parse_answer(text)
        evidence.update(parsed=str(parsed), parsed_type=type(parsed).__name__,
                        parse_matches_expected=parsed == expected)
    except Exception as error:
        evidence.update(parse_exception=type(error).__name__ + ": " + str(error),
                        parse_matches_expected=False)
    if not evidence["parse_matches_expected"]:
        evidence.update(symbol="parse_answer", explanation="The parser changes or rejects the exact submitted value before the checker compares it.")
    else:
        evidence.update(symbol="check_answer", explanation="Parsing preserves the expected value; inspect the checker that rejects it.")
    return evidence


def failure_result(error):
    return {"status": "failed", "error": str(error), "traceback": traceback.format_exc(),
            "diagnostics": getattr(error, "diagnostics", {})}


def arithmetic_value(prompt):
    """Evaluate the COMPLETE numeric expression; never a regex prefix or eval."""
    expression = prompt.split("=", 1)[0].strip().rstrip("?").strip()
    expression = expression.replace("×", "*").replace("÷", "/").replace("−", "-")
    expression = re.sub(r'(?<=\d)\s+[xX]\s+(?=\d)', ' * ', expression)
    expression = re.sub(r"(?i)^(?:what\s+is|solve|calculate|evaluate|simplify)\s*:?\s*", "", expression)
    def mixed(match):
        whole, numerator, denominator = match.groups()
        sign = "-" if whole.startswith("-") else ""
        prefix = expression[:match.start()].rstrip()
        if whole[0] in "+-" and prefix and prefix[-1] not in "+-*/(":
            return f"{whole[0]}({abs(int(whole))}+{numerator}/{denominator})"
        return f"({sign}({abs(int(whole))}+{numerator}/{denominator}))"
    expression = re.sub(r"(?<![\w./])([+-]?\d+)\s+(\d+)\s*/\s*(\d+)", mixed, expression)
    # A displayed a/b is one fraction operand: 1/2 ÷ 1/3 means
    # (1/2)/(1/3), rather than Python's left-associative 1/2/1/3.
    expression = re.sub(r"(?<![\w.])(\d+/\d+)(?![\w.])", r"(\1)", expression)
    tree = ast.parse(expression, mode="eval")
    if len(list(ast.walk(tree))) > 150:
        raise ValueError("Expression too complex")
    operations = set()
    def value(node):
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return Fraction(ast.get_source_segment(expression, node))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            return -value(node.operand) if isinstance(node.op, ast.USub) else value(node.operand)
        if isinstance(node, ast.BinOp):
            a, b = value(node.left), value(node.right)
            if isinstance(node.op, ast.Add):
                operations.add("+"); return a+b
            if isinstance(node.op, ast.Sub):
                operations.add("-"); return a-b
            if isinstance(node.op, ast.Mult):
                operations.add("*"); return a*b
            if isinstance(node.op, ast.Div):
                operations.add("/"); return a/b
        raise ValueError("Only numeric fraction arithmetic is supported")
    return value(tree.body), operations


def project_contract(project):
    configured = globals().get("FORGE_DESKTOP_CONTRACT")
    if configured is not None:
        return configured
    for name in ("run.json", "product-contract.json"):
        path = Path(project) / ".agent" / name
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8")).get("desktop_contract", 2)
    return 2


def check_basic_math(domain, questions, require, results):
    for text, expected in {"0": Fraction(0), "1": Fraction(1), "1/2": Fraction(1, 2),
                           "3/4": Fraction(3, 4), "2/3": Fraction(2, 3), "2/4": Fraction(1, 2)}.items():
        evidence = answer_roundtrip_evidence(domain, expected, text)
        require(evidence["parse_matches_expected"], f"basic fraction parser: {text}; expected={expected}; parsed={evidence.get('parsed')}", evidence)
        require(domain.check_answer(expected, text), "basic fraction answer accepted: " + text)
    require(not domain.check_answer(Fraction(1, 2), "1/3"), "wrong fraction is rejected")
    for invalid in ("", "bad", "1/0", "1//2"):
        try:
            domain.parse_answer(invalid)
        except ValueError:
            continue
        raise AcceptanceFailure("invalid fraction input accepted: " + invalid)
    require(len(questions) >= 20, "at least twenty basic questions")
    require(len({q.id for q in questions}) == len(questions), "unique basic question IDs")
    operators = set()
    for q in questions:
        match = re.fullmatch(r"\s*(\d+)\s*/\s*(\d+)\s*([+\-×÷*/])\s*(\d+)\s*/\s*(\d+)\s*=\s*\?\s*", q.prompt)
        require(match is not None, "basic two-fraction question: " + q.id)
        a, b, operator, c, d = match.groups()
        require(1 <= int(a) <= int(b) <= 12 and 1 <= int(c) <= int(d) <= 12, "small positive fraction operands: " + q.id)
        operators.add(operator.replace("×", "*").replace("÷", "/"))
        expected, _ = arithmetic_value(q.prompt)
        require(expected >= 0 and q.answer == expected, f"basic question arithmetic: {q.id}; expected={expected}; actual={q.answer}")
        evidence = answer_roundtrip_evidence(domain, q.answer, str(q.answer), q)
        require(evidence["parse_matches_expected"], "basic question answer parses exactly: " + q.id, evidence)
        require(domain.check_answer(q.answer, str(q.answer)), "basic question answer checks correctly: " + q.id, evidence)
    require(operators == {"+", "-", "*", "/"}, "basic questions cover four operations")
    probe = domain.Session([domain.Question("repeat-probe", "1/2 + 1/4 = ?", Fraction(3, 4), "Add quarters")])
    require(probe.submit("3/4")[0], "session accepts a correct fraction")
    repeated = probe.submit("1/4")
    require(repeated[0] is False and probe.correct == 1 and probe.attempted == 1, "repeated submission returns False without changing score or attempts")


def check_legacy_math(domain, questions, require, results):
    cases = {"-0 1/2": Fraction(-1, 2), "-1 1/2": Fraction(-3, 2), "-3/4": Fraction(-3, 4), "2/4": Fraction(1, 2),
             "1.234567890123456789": Fraction("1.234567890123456789")}
    for text, expected in cases.items():
        evidence = answer_roundtrip_evidence(domain, expected, text)
        require(evidence["parse_matches_expected"],
                f"exact parser contract: input={text!r}; expected={expected}; parsed={evidence.get('parsed', evidence.get('parse_exception'))}", evidence)
    require(domain.check_answer(Fraction(1, 3), "0.333333333"), "rounded decimal tolerance is accepted")
    require(domain.check_answer(Fraction(1, 3), "0.333333334"), "decimal inside tolerance boundary is accepted")
    require(not domain.check_answer(Fraction(1, 3), "0.333333335"), "decimal outside tolerance boundary is rejected")
    require(not domain.check_answer(Fraction(1, 3), "0.3333"), "decimal outside tolerance is rejected")
    require(not domain.check_answer(Fraction(1, 3), "333333334/1000000000"),
            "fraction input requires exact equality; decimal tolerance is not applied to fractions")
    require(not domain.check_answer(Fraction(1, 3), "1e309"), "large finite input is rejected without float overflow")
    policy_session = domain.Session([domain.Question("policy-probe", "1/3 = ?", Fraction(1, 3), "One third")])
    policy_correct, _ = policy_session.submit("333333334/1000000000")
    require(not policy_correct and policy_session.correct == 0 and policy_session.attempted == 1,
            "Session.submit shares the exact-fraction answer policy and does not score a near fraction")
    for invalid in ("1/0", "NaN", "inf", "bad", "1//2"):
        try:
            domain.parse_answer(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError("ACCEPTANCE: invalid input accepted: " + invalid)
    require(len(questions) >= 20, "at least twenty built-in questions")
    require(len({q.id for q in questions}) == len(questions), "unique question IDs")
    operations = set()
    for q in questions:
        expected, covered = arithmetic_value(q.prompt)
        operations.update(covered)
        require(q.answer == expected, f"question arithmetic independently verified: {q.id}; prompt={q.prompt}; expected={expected}; actual={q.answer}")
        if not domain.check_answer(q.answer, str(q.answer)):
            evidence = answer_roundtrip_evidence(domain, q.answer, str(q.answer), q)
            require(False, f"generated answer round-trip: {q.id}; input={str(q.answer)!r}; expected={q.answer}; parsed={evidence.get('parsed', evidence.get('parse_exception'))}; inspect {evidence['symbol']}", evidence)
        results.append("generated answer round-trip: " + q.id)
    require(operations == {"+", "-", "*", "/"}, "all four operations are covered")


def check_extended_app(root, app, basic=None):
    if basic is None:
        basic = globals().get("FORGE_DESKTOP_CONTRACT", 2) == 3
    results = []
    errors = []
    root.report_callback_exception = lambda kind, value, tb: errors.append("".join(traceback.format_exception(kind, value, tb)))

    def require(ok, message, diagnostics=None):
        if not ok:
            raise AcceptanceFailure(message, diagnostics)
        results.append(message)

    def widget(role):
        require(role in app.widgets, f"{app.screen}: control exists: {role}")
        w = app.widgets[role]
        root.update_idletasks()
        require(bool(w.winfo_exists()) and bool(w.winfo_ismapped()), f"{app.screen}: control visible: {role}")
        parent = w.nametowidget(w.winfo_parent())
        require(w.winfo_y() >= 0 and w.winfo_y()+w.winfo_height() <= parent.winfo_height()+1,
                f"{app.screen}: control is not vertically clipped: {role}")
        return w

    def click(role):
        widget(role).invoke()
        root.update_idletasks()
        require(not errors, "no Tkinter callback errors: " + "\n".join(errors))

    def enter(role, text):
        w = widget(role)
        w.delete(0, "end")
        w.insert(0, text)

    def screen(name):
        require(app.screen == name, f"screen is {name}, got {app.screen}")
        roles = {"menu": ("play", "help", "admin", "quit"),
                 "play": ("question", "progress", "score", "answer", "check", "next", "menu", "feedback"),
                 "results": ("summary", "replay", "menu"), "help": ("instructions", "menu"),
                 "admin": ("questions", "prompt", "correct_answer", "explanation", "add", "save", "delete", "menu", "status")}
        missing = set(roles.get(name, ())) - app.widgets.keys()
        require(not missing, name + ": all required controls exist; missing=" + ",".join(sorted(missing)))
        for role in roles.get(name, ()):
            widget(role)

    root.deiconify()
    root.update()
    if app.screen == "intro":
        click("skip")
    screen("menu")
    click("help")
    screen("help")
    require(len(widget("instructions").cget("text")) > 40, "help instructions are meaningful")
    click("menu")
    click("play")
    screen("play")
    import domain
    import content
    from storage import Store
    questions = content.default_questions()
    if basic:
        check_basic_math(domain, questions, require, results)
    else:
        check_legacy_math(domain, questions, require, results)
    session = app.session
    q = session.current()
    require(q is not None, "session has a current question")
    require(widget("question").cget("text") == q.prompt and len(q.prompt) > 3, "first question actually rendered")
    require(bool(widget("progress").cget("text")), "progress actually rendered")
    require(re.search(r"\b0\s*/\s*" + str(len(session.questions)) + r"\b", widget("score").cget("text")),
            "initial visible score uses correct/total, not zero attempts")
    require(len(app.canvas.find_all()) > 50, "designed Canvas scene is present")
    require(app.canvas.winfo_width() > root.winfo_width() * .9, "scene fills window")
    # Invalid input must not score or consume the question.
    enter("answer", "1/0")
    click("check")
    require(session.attempted == 0 and session.correct == 0, "invalid input does not consume or score")
    enter("answer", str(q.answer) if basic else format(float(q.answer), ".12f"))
    click("check")
    require(session.correct == 1 and session.attempted == 1, "fraction accepted in real UI increments correct and attempted once" if basic else "decimal accepted in real UI increments correct and attempted once")
    require(re.search(r"\b1\s*/\s*" + str(len(session.questions)) + r"\b", widget("score").cget("text")),
            "visible score matches correct count and total")
    require(bool(widget("feedback").cget("text")), "feedback actually rendered")
    # Invoke even a disabled button via Tcl: domain must guard independently.
    widget("check").invoke()
    require(session.correct == 1 and session.attempted == 1, "repeat submit cannot farm score")
    old_index = session.index
    click("next")
    require(session.index == old_index+1, "Next advances exactly once")
    require(widget("question").cget("text") == session.current().prompt, "next question visibly updates")
    # Complete using actual buttons. Answer one question incorrectly.
    made_wrong = False
    for _ in range(len(session.questions)+1):
        if app.screen != "play":
            break
        current = app.session.current()
        require(current is not None, "active question exists during full flow")
        value = str(current.answer + 1000) if not made_wrong else str(current.answer)
        enter("answer", value)
        click("check")
        if not made_wrong:
            f = current.answer
            whole, remainder = divmod(abs(f.numerator), f.denominator)
            mixed = ("-" if f < 0 else "") + f"{whole} {remainder}/{f.denominator}"
            feedback = widget("feedback").cget("text")
            require(str(f) in feedback or mixed in feedback, "incorrect feedback shows the correct numeric answer")
        made_wrong = True
        require(0 <= app.session.accuracy <= 100, "accuracy stays within 0..100")
        click("next")
    screen("results")
    require(bool(widget("summary").cget("text")), "results visibly rendered")
    require(session.correct == len(session.questions)-1, "correct count distinct from points")
    saved = Store(app.data_dir).load_scores()
    require(len(saved) == 1 and bool(saved[0].get("timestamp")), "one timestamped score saved")
    require(saved[0].get("correct") == session.correct and saved[0].get("total") == len(session.questions), "saved correct/total use counts, not weighted points")
    Store(app.data_dir).save_score(saved[0])
    require(len(Store(app.data_dir).load_scores()) == 1, "score saves idempotent")
    click("replay")
    screen("play")
    require(app.session.correct == 0 and app.session.index == 0, "replay resets state")
    require(bool(widget("question").cget("text")), "replay renders question")
    for _ in range(len(app.session.questions)+1):
        if app.screen != "play":
            break
        enter("answer", str(app.session.current().answer))
        click("check")
        click("next")
    screen("results")
    second_scores = Store(app.data_dir).load_scores()
    require(len(second_scores) == 2 and second_scores[0]["id"] != second_scores[1]["id"], "rapid replay saves a distinct session")
    click("menu")
    click("admin")
    screen("admin")
    count = widget("questions").size()
    enter("prompt", "Audit mission: 1/4 + 1/4 = ?")
    enter("correct_answer", "1/2")
    enter("explanation", "Two quarters equal one half.")
    click("add")
    require(widget("questions").size() == count+1, "real Add button adds question")
    items = Store(app.data_dir).load_questions()
    match = next((q for q in items if q.prompt.startswith("Audit mission:")), None)
    require(match is not None and match.answer == Fraction(1, 2), "admin question persists and reloads")
    lb = widget("questions")
    index = next(i for i in range(lb.size()) if "Audit mission:" in str(lb.get(i)))
    lb.selection_clear(0, "end")
    lb.selection_set(index)
    lb.event_generate("<<ListboxSelect>>")
    root.update()
    require(widget("prompt").get().startswith("Audit mission:"), "selection populates editor")
    enter("prompt", "Audit edited mission")
    enter("correct_answer", "3/4" if basic else "-1 1/2")
    click("save")
    require(any(q.prompt == "Audit edited mission" and q.answer == (Fraction(3, 4) if basic else Fraction(-3, 2)) for q in Store(app.data_dir).load_questions()), "real Save updates and persists")
    lb = widget("questions")
    index = next(i for i in range(lb.size()) if "Audit edited mission" in str(lb.get(i)))
    lb.selection_clear(0, "end")
    lb.selection_set(index)
    lb.event_generate("<<ListboxSelect>>")
    root.update()
    click("delete")
    require(widget("questions").size() == count, "real Delete persists removal")
    click("menu")
    click("play")
    require(bool(widget("question").cget("text")), "game reentry has no stale widgets")
    # Invalid storage recovery is tested on an independent store.
    with tempfile.TemporaryDirectory(prefix="forge-corrupt-store-") as directory:
        store = Store(directory)
        store.load_questions()
        store.save_score({"id": "recovery-probe", "correct": 1, "total": 1, "accuracy": 100, "timestamp": "2026-10-24T00:00:00Z"})
        files = list(Path(directory).glob("*.json"))
        require(bool(files), "store uses actual JSON persistence")
        for path in files:
            path.write_text("{broken", encoding="utf-8")
        require(len(Store(directory).load_questions()) >= 20, "corrupt storage recovers built-ins")
        require(Store(directory).load_scores() == [], "corrupt scores recover safely")
    require(not errors, "all callbacks completed without error")
    return {"status": "passed", "checks": len(results), "evidence": results,
            "visual_review": "pending", "python_free_os_verified": False, "math_profile": "basic-fractions" if basic else "legacy"}


def finish_intro(root, app, click):
    if app.screen != 'intro':
        return
    if 'skip' in app.widgets:
        click('skip')
        return
    # A timed intro is also playable; it need not expose a Skip button.
    import time
    deadline = time.monotonic() + 5
    while app.screen == 'intro' and time.monotonic() < deadline:
        root.update()
        time.sleep(.02)


def check_app(root, app, basic=None):
    """Only observable delivery gates; wording and generated unit tests are advisory."""
    errors, passed, warnings = [], [], []
    root.report_callback_exception = lambda kind, value, tb: errors.append(''.join(traceback.format_exception(kind,value,tb)))
    def require(ok, message):
        if not ok:
            raise AcceptanceFailure(message, {'category':'essential_gameplay'})
    def widget(role):
        require(role in app.widgets, 'required control missing: '+role)
        control = app.widgets[role]
        require(bool(control.winfo_exists()) and bool(control.winfo_ismapped()), 'required control unavailable: '+role)
        return control
    def click(role):
        widget(role).invoke()
        root.update_idletasks()
        require(not errors, 'callback failed: '+''.join(errors))
    def enter(role, value):
        control=widget(role);control.delete(0,'end');control.insert(0,value)
    root.deiconify();root.update()
    finish_intro(root, app, click)
    require(app.screen=='menu','intro reaches the menu')
    passed.append('default launch and menu')
    click('play')
    require(app.screen=='play','Play opens a game')
    session=app.session
    require(bool(session.questions),'a game has questions')
    require(bool(widget('question').cget('text')),'a question is displayed')
    q=session.current()
    require(widget('question').cget('text')==q.prompt,'the current question is actually displayed')
    unverified=0
    for question in session.questions:
        try:
            expected,_=arithmetic_value(question.prompt)
        except ZeroDivisionError:
            require(False,'question divides by zero: '+question.id)
        except (ValueError,SyntaxError):
            unverified+=1
            continue
        require(Fraction(question.answer)==expected,'incorrect arithmetic answer: '+question.id)
    if unverified:
        warnings.append(f'Arithmetic could not be independently parsed for {unverified} text questions; wording was accepted.')
    passed.append('basic question arithmetic where parseable')
    before=(session.correct,session.attempted)
    enter('answer','bad');click('check')
    require((session.correct,session.attempted)==before and not session.answered,'invalid input is handled without scoring or crashing')
    answer=Fraction(q.answer)
    enter('answer',f'{answer.numerator*2}/{answer.denominator*2}');click('check')
    require(session.correct==before[0]+1 and session.attempted==before[1]+1,'a correct equivalent fraction scores once')
    click('check')
    require(session.correct==before[0]+1 and session.attempted==before[1]+1,'repeat Check cannot score twice')
    require(bool(widget('feedback').cget('text')) and bool(widget('score').cget('text')),'feedback and score are displayed')
    require(re.search(r'\b'+str(session.correct)+r'\s*/\s*\d+\b',widget('score').cget('text')),'the visible score reflects the correct answer')
    passed.append('answer input, feedback and scoring')
    click('next')
    total=len(session.questions)
    made_wrong=False
    for _ in range(total+1):
        if app.screen=='results':
            break
        require(app.screen=='play','round remains playable until results')
        current=session.current()
        require(current is not None,'an active question exists')
        value=Fraction(current.answer)+(1 if not made_wrong else 0)
        expected=session.correct+(1 if made_wrong else 0)
        enter('answer',str(value));click('check')
        require(session.correct==expected,'correct and incorrect answers update score correctly')
        made_wrong=True
        click('next')
    require(app.screen=='results','Next reaches results after the final question')
    require(session.correct==total-int(made_wrong),'final score matches submitted answers')
    require(bool(widget('summary').cget('text')),'results are displayed')
    passed.append('question progression and final results')
    from storage import Store
    saved=Store(app.data_dir).load_scores()
    if not saved:
        diagnostic = {'category':'score_persistence','path':'storage.py','symbol':'Store.load_scores',
                      'expected':'Read back the completed score written by Store.save_score.'}
        score_path = getattr(app.store, 'scores_path', None)
        if score_path and Path(score_path).is_file() and Path(score_path).resolve().is_relative_to(Path(app.data_dir).resolve()):
            try:
                raw = json.loads(Path(score_path).read_text(encoding='utf-8'))
                diagnostic.update(json_type=type(raw).__name__, json_keys=list(raw) if isinstance(raw,dict) else [],
                                  records_on_disk=len(raw.get('scores',[])) if isinstance(raw,dict) and isinstance(raw.get('scores'),list) else None)
            except (OSError,ValueError):
                pass
        raise AcceptanceFailure('the completed score is saved', diagnostic)
    require(any(r.get('correct')==session.correct and r.get('total')==total for r in saved),'saved score matches the completed round')
    passed.append('score persistence')
    click('replay')
    require(app.screen=='play' and app.session.correct==0 and app.session.index==0,'Replay starts a fresh round')
    passed.append('replay')
    # These secondary controls are inspected once, without blocking a playable
    # executable or causing paid repair rounds when their tests fail.
    try:
        click('menu');click('help')
        require(app.screen=='help' and bool(widget('instructions').cget('text')),'Help displays instructions')
        click('menu');click('admin')
        require(app.screen=='admin','Admin opens')
        original_count=widget('questions').size()
        marker='Delivery check: 1/4 + 1/4?'
        enter('prompt',marker);enter('correct_answer','1/2');enter('explanation','Two quarters make one half.')
        click('add')
        require(widget('questions').size()==original_count+1,'Add inserts a question')
        items=Store(app.data_dir).load_questions()
        require(any(q.prompt==marker and Fraction(q.answer)==Fraction(1,2) for q in items),'new question persists')
        def select(prompt):
            listing=widget('questions')
            index=next((i for i in range(listing.size()) if prompt in str(listing.get(i))),None)
            require(index is not None,'saved question appears in the editor')
            listing.selection_clear(0,'end');listing.selection_set(index);listing.event_generate('<<ListboxSelect>>');root.update()
            require(not errors,'editor selection has no callback errors')
        select(marker)
        edited='Delivery edited question'
        enter('prompt',edited);enter('correct_answer','3/4');click('save')
        require(any(q.prompt==edited and Fraction(q.answer)==Fraction(3,4) for q in Store(app.data_dir).load_questions()),'Save persists the edited answer')
        select(edited);click('delete')
        require(widget('questions').size()==original_count and not any(q.prompt==edited for q in Store(app.data_dir).load_questions()),'Delete persists removal')
        passed.append('optional question editor and persistence')
    except Exception as error:
        warnings.append('Optional help/editor check: '+str(error)[-2000:])
    return {'status':'passed','policy':'essential','checks':len(passed),'evidence':passed,'warnings':warnings,
            'visual_review':'pending','python_free_os_verified':False,
            'math_profile':'basic-fractions' if (basic if basic is not None else globals().get('FORGE_DESKTOP_CONTRACT',2)==3) else 'legacy'}


def run_source(project, report):
    import sys
    import tkinter as tk
    sys.path.insert(0, str(project))
    from main import create_app
    with tempfile.TemporaryDirectory(prefix="forge-acceptance-profile-") as data:
        root = tk.Tk()
        try:
            # Match the executable's real constructor call before the full
            # flow that supplies an explicit temporary storage directory.
            prior = os.environ.get("LOCALAPPDATA")
            try:
                os.environ["LOCALAPPDATA"] = str(Path(data) / "default-launch")
                default_app = create_app(root)
                root.update_idletasks()
            except Exception as error:
                raise AcceptanceFailure("default desktop startup create_app(root) failed: " + str(error),
                    {"category": "default_constructor", "path": "app.py", "symbol": "GameApp.__init__",
                     "expected": "Construct with data_dir=None, passing it to GameShell before reading its fields.",
                     "observed": type(error).__name__ + ": " + str(error)}) from error
            finally:
                if prior is None:
                    os.environ.pop("LOCALAPPDATA", None)
                else:
                    os.environ["LOCALAPPDATA"] = prior
            default_app.close()
            root = tk.Tk()
            app = create_app(root, data_dir=data)
            result = check_app(root, app, basic=project_contract(project) == 3)
        except Exception as error:
            result = failure_result(error)
        finally:
            try:
                root.destroy()
            except tk.TclError:
                pass
    Path(report).write_text(json.dumps(result, indent=2), encoding="utf-8")
    if result["status"] != "passed":
        raise RuntimeError(result["traceback"])


def frozen_hook():
    """This module is copied verbatim as a runtime hook only for a verification run."""
    report = os.environ.pop("FORGE_ACCEPTANCE_REPORT", "")
    if not report:
        return
    import tkinter as tk
    def verify(root, *args, **kwargs):
        try:
            app = root.forge_app
            result = check_app(root, app)
        except Exception as error:
            result = failure_result(error)
        Path(report).write_text(json.dumps(result, indent=2), encoding="utf-8")
        root.destroy()
    tk.Tk.mainloop = verify


if __name__ == "__main__" and not getattr(sys, "frozen", False):
    run_source(Path(sys.argv[1]), Path(sys.argv[2]))
else:
    frozen_hook()
