"""Tests for CalculatorTool."""

import pytest

from ua.tools.calculator import CalculatorTool


@pytest.mark.asyncio
async def test_basic_addition_and_precedence():
    """Test basic addition with operator precedence (multiplication before addition)."""
    tool = CalculatorTool()
    result = await tool.run(expression="2 + 2 * 3")
    assert result.success is True
    assert result.output == "8"
    assert result.error is None


@pytest.mark.asyncio
async def test_parentheses_grouping():
    """Test that parentheses override default precedence."""
    tool = CalculatorTool()
    result = await tool.run(expression="(2 + 3) * 4")
    assert result.success is True
    assert result.output == "20"
    assert result.error is None


@pytest.mark.asyncio
async def test_exponentiation():
    """Test exponentiation operator."""
    tool = CalculatorTool()
    result = await tool.run(expression="2 ** 10")
    assert result.success is True
    assert result.output == "1024"
    assert result.error is None


@pytest.mark.asyncio
async def test_unary_minus():
    """Test unary minus (negative numbers)."""
    tool = CalculatorTool()
    result = await tool.run(expression="-5 + 3")
    assert result.success is True
    assert result.output == "-2"
    assert result.error is None


@pytest.mark.asyncio
async def test_division_by_zero_handled_gracefully():
    """Test that division by zero returns a clear error, not an unhandled exception."""
    tool = CalculatorTool()
    result = await tool.run(expression="1 / 0")
    assert result.success is False
    assert "zero" in result.error.lower() or "division" in result.error.lower()


@pytest.mark.asyncio
async def test_malicious_import_expression_rejected_safely():
    """Test that malicious expressions with function calls/names are rejected safely.

    This must NOT execute any code - the expression should be rejected before
    any side effects can occur.
    """
    tool = CalculatorTool()
    result = await tool.run(expression="__import__('os').system('echo pwned')")
    assert result.success is False
    assert result.error is not None
    # Verify it's rejected due to disallowed construct, not just any error
    assert "disallowed" in result.error.lower() or "not supported" in result.error.lower()


@pytest.mark.asyncio
async def test_malformed_expression_syntax_error_handled():
    """Test that malformed expressions return a clear error, not an unhandled SyntaxError."""
    tool = CalculatorTool()
    result = await tool.run(expression="2 +")
    assert result.success is False
    assert result.error is not None
    assert "invalid" in result.error.lower()


@pytest.mark.asyncio
async def test_string_operands_rejected():
    """Test that string operands are rejected - only numeric constants allowed."""
    tool = CalculatorTool()
    result = await tool.run(expression="'a' + 'b'")
    assert result.success is False
    assert result.error is not None
    assert "numeric" in result.error.lower() or "constant" in result.error.lower()


@pytest.mark.asyncio
async def test_float_division_result_formatting():
    """Test float division result formatting.

    Float formatting convention: We use f"{result:.10g}" which provides up to
    10 significant digits, removing trailing zeros for cleaner output.
    For 1/4 = 0.25, the output should be "0.25".
    """
    tool = CalculatorTool()
    result = await tool.run(expression="1 / 4")
    assert result.success is True
    assert result.output == "0.25"
    assert result.error is None


@pytest.mark.asyncio
async def test_name_reference_rejected():
    """Test that bare name references (variables) are rejected.

    Expression like 'x + 1' should fail because 'x' is a Name node,
    not a numeric constant.
    """
    tool = CalculatorTool()
    result = await tool.run(expression="x + 1")
    assert result.success is False
    assert result.error is not None
    assert "disallowed" in result.error.lower() or "name" in result.error.lower()


@pytest.mark.asyncio
async def test_complex_nested_expression():
    """Test a more complex nested expression with multiple operators."""
    tool = CalculatorTool()
    result = await tool.run(expression="(2 + 3) * 4 - 6 / 2")
    assert result.success is True
    assert result.output == "17"  # (5 * 4) - 3 = 20 - 3 = 17


@pytest.mark.asyncio
async def test_negative_exponent():
    """Test negative numbers in exponent expressions."""
    tool = CalculatorTool()
    result = await tool.run(expression="2 ** -1")
    assert result.success is True
    assert result.output == "0.5"


@pytest.mark.asyncio
async def test_unary_plus():
    """Test unary plus operator."""
    tool = CalculatorTool()
    result = await tool.run(expression="+5 + 3")
    assert result.success is True
    assert result.output == "8"
