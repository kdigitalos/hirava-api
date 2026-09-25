"""Bounded decimal expression evaluator. No Python eval or executable formulas."""
import ast
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING, ROUND_FLOOR, localcontext


class CalculationError(ValueError):
    pass


def formula(expression: str, values: dict[str, Decimal]) -> Decimal:
    try:
        tree = ast.parse(expression, mode="eval")
    except (SyntaxError, RecursionError) as exc:
        raise CalculationError("Invalid formula syntax") from exc
    if len(list(ast.walk(tree))) > 100:
        raise CalculationError("Formula is too complex")

    def visit(node):
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return Decimal(ast.get_source_segment(expression, node))
        if isinstance(node, ast.Name):
            if node.id not in values:
                raise CalculationError(f"Unknown or forward reference: {node.id}")
            return values[node.id]
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = visit(node.operand)
            return -value if isinstance(node.op, ast.USub) else value
        if isinstance(node, ast.BinOp):
            a, b = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Add):
                return a + b
            if isinstance(node.op, ast.Sub):
                return a - b
            if isinstance(node.op, ast.Mult):
                return a * b
            if isinstance(node.op, ast.Div):
                if not b:
                    raise CalculationError("Division by zero")
                return a / b
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
            args = [visit(arg) for arg in node.args]
            if node.func.id in {"MIN", "MAX"} and 1 <= len(args) <= 10:
                return (min if node.func.id == "MIN" else max)(args)
            if node.func.id in {"ROUND", "CEILING", "FLOOR"} and len(args) == 1:
                mode = {"ROUND": ROUND_HALF_UP, "CEILING": ROUND_CEILING, "FLOOR": ROUND_FLOOR}[node.func.id]
                return args[0].quantize(Decimal("1"), rounding=mode)
        raise CalculationError("Use numbers, references, + - * /, MIN, MAX, ROUND, CEILING or FLOOR")

    try:
        with localcontext() as context:
            context.prec = 28
            result = visit(tree)
            if not result.is_finite() or abs(result) > Decimal("999999999999.99"):
                raise CalculationError("Calculated amount is outside the supported range")
            return result
    except ArithmeticError as exc:
        raise CalculationError("Invalid arithmetic in formula") from exc


def calculate(components, monthly_gross):
    gross = Decimal(str(monthly_gross))
    values = {"GROSS": gross}
    totals = {"earning": Decimal(0), "deduction": Decimal(0), "employer": Decimal(0)}
    lines = []
    for component in components:
        try:
            amount = formula(component["formula"], values).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        except CalculationError as exc:
            raise CalculationError(f"{component['code']}: {exc}") from exc
        if amount < 0:
            raise CalculationError(f"{component['code']}: negative amounts are not allowed")
        values[component["code"]] = amount
        totals[component["kind"]] += amount
        lines.append({**component, "amount": format(amount, ".2f")})
    if totals["earning"] != gross:
        raise CalculationError("Earnings must equal monthly gross; use a balancing earnings component")
    if totals["deduction"] > gross:
        raise CalculationError("Deductions cannot exceed gross earnings")
    return {"lines": lines, "gross": format(gross, ".2f"),
            "deductions": format(totals["deduction"], ".2f"),
            "net_before_unconfigured_deductions": format(gross - totals["deduction"], ".2f"),
            "employer_contributions": format(totals["employer"], ".2f"),
            "monthly_employer_cost": format(gross + totals["employer"], ".2f"),
            "currency": "INR", "status": "structure_preview",
            "notice": "Structure preview only. Statutory eligibility, taxes, attendance and payment approval are not calculated."}
