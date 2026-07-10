"""Safe arithmetic expression calculator tool.

This tool evaluates basic arithmetic expressions using AST parsing for safety.
It explicitly does NOT use eval() or exec() on user input.
"""

import ast
from typing import Any

from ua.tools.base import Tool, ToolResult


class CalculatorTool(Tool):
    """Evaluate a basic arithmetic expression safely.

    Supports: +, -, *, /, **, and parentheses.
    Uses AST parsing to ensure only safe numeric operations are allowed.
    """

    name = "calculator"
    description = (
        "Evaluate a basic arithmetic expression, e.g. '2 + 2 * 3'. "
        "Supports + - * / ** and parentheses."
    )
    parameters = {
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "A basic arithmetic expression to evaluate",
            }
        },
        "required": ["expression"],
    }

    # Mapping of allowed AST operators to their functions
    _OPS = {
        ast.Add: lambda a, b: a + b,
        ast.Sub: lambda a, b: a - b,
        ast.Mult: lambda a, b: a * b,
        ast.Div: lambda a, b: a / b,
        ast.Pow: lambda a, b: a ** b,
    }

    async def run(self, expression: str) -> ToolResult:
        """Evaluate the expression safely using AST parsing.

        Args:
            expression: A string containing a basic arithmetic expression.

        Returns:
            ToolResult with success=True and the numeric result as output,
            or success=False with an error message.
        """
        try:
            # Parse the expression into an AST (mode="eval" for single expressions)
            # This is SAFE - we're only parsing, not evaluating with Python's eval()
            tree = ast.parse(expression, mode="eval")
        except (SyntaxError, ValueError) as e:
            return ToolResult(success=False, output="", error=f"Invalid expression: {e}")

        try:
            # Walk the AST and evaluate only allowed node types
            result = self._eval_node(tree.body)
        except ZeroDivisionError:
            return ToolResult(success=False, output="", error="Division by zero")
        except (TypeError, ValueError) as e:
            return ToolResult(success=False, output="", error=str(e))

        # Format the result: integers as-is, floats with reasonable precision
        if isinstance(result, float):
            # Use repr for floats to avoid unnecessary trailing zeros
            # but strip trailing zeros for cleaner output
            formatted = f"{result:.10g}"
        else:
            formatted = str(result)

        return ToolResult(success=True, output=formatted)

    def _eval_node(self, node: ast.AST) -> Any:
        """Recursively evaluate an AST node, only allowing safe numeric operations.

        Args:
            node: An AST node to evaluate.

        Returns:
            The numeric result of evaluating the node.

        Raises:
            TypeError: If the node type or value is not allowed.
            ZeroDivisionError: If division by zero is attempted.
        """
        # Allow numeric constants only (int, float)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return node.value
            raise TypeError("Only numeric constants are allowed")

        # Handle binary operations: +, -, *, /, **
        if isinstance(node, ast.BinOp):
            left = self._eval_node(node.left)
            right = self._eval_node(node.right)
            op_type = type(node.op)

            if op_type not in self._OPS:
                raise TypeError(f"Operator {op_type.__name__} is not supported")

            return self._OPS[op_type](left, right)

        # Handle unary operations (e.g., -5)
        if isinstance(node, ast.UnaryOp):
            operand = self._eval_node(node.operand)

            if isinstance(node.op, ast.USub):  # Unary minus
                return -operand
            if isinstance(node.op, ast.UAdd):  # Unary plus
                return +operand

            raise TypeError(f"Unary operator {type(node.op).__name__} is not supported")

        # Any other node type is rejected (names, function calls, etc.)
        raise TypeError(
            f"Expression contains disallowed construct: {type(node).__name__}"
        )
