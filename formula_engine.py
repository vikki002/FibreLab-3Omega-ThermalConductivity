# -*- coding: utf-8 -*-
"""Spreadsheet formula engine — address parsing, tokenizer, recursive-descent
parser, AST evaluator, dependency graph and full-sheet recalculation, plus a
function registry (math/trig, aggregate/statistics, regression, logical,
text). Pure Python — no Qt, no pyvisa — independently usable/testable.

Never uses eval()/exec() on formula text: formulas are parsed into a custom
AST by a hand-written tokenizer + parser, then walked by a small evaluator.

Grammar (precedence high -> low, as written top-down):
    comparison := concat ( ('='|'<>'|'<'|'<='|'>'|'>=') concat )*
    concat     := additive ( '&' additive )*
    additive   := term ( ('+'|'-') term )*
    term       := unary ( ('*'|'/') unary )*
    unary      := ('-'|'+') unary | power
    power      := postfix ( '^' unary )*        # right-assoc
    postfix    := primary ( '%' )*               # 50% -> 0.5
    primary    := NUMBER | STRING | TRUE | FALSE | '(' expr ')'
                | REF_SHAPED [ ':' REF_SHAPED ]
                | IDENT '(' (expr (',' expr)*)? ')'
                | IDENT

Note: unary minus binds tighter than '^' here (-2^2 == -4, standard math),
which differs from real Excel (-2^2 == 4 there). Deliberate — see plan notes.
"""

import math
import re
import datetime
import random


# ============================================================================
# Cell addresses
# ============================================================================

MAX_ROWS = 10000
MAX_COLS = 702  # 'A'..'ZZ'

_ADDR_RE = re.compile(r'^\$?([A-Za-z]{1,3})\$?([0-9]{1,7})$')


def col_to_index(col_str):
    """'A' -> 0, 'Z' -> 25, 'AA' -> 26."""
    idx = 0
    for ch in col_str.upper():
        idx = idx * 26 + (ord(ch) - ord('A') + 1)
    return idx - 1


def index_to_col(idx):
    """0 -> 'A', 26 -> 'AA'."""
    idx += 1
    s = ''
    while idx > 0:
        idx, rem = divmod(idx - 1, 26)
        s = chr(ord('A') + rem) + s
    return s


def parse_address(addr):
    m = _ADDR_RE.match(addr.strip())
    if not m:
        raise ValueError("Bad cell address: %r" % addr)
    col_str, row_str = m.groups()
    return int(row_str) - 1, col_to_index(col_str)


def format_address(row, col):
    return "%s%d" % (index_to_col(col), row + 1)


_ADDR_DOLLAR_RE = re.compile(r'^(\$?)([A-Za-z]{1,3})(\$?)([0-9]{1,7})$')


def _translate_ref_token(tok_text, row_delta, col_delta):
    """Shift one REF_SHAPED token (e.g. 'B1', '$B1', 'B$1', '$B$1') by
    (row_delta, col_delta), leaving any $-anchored axis unchanged --
    Excel's relative/absolute reference rule for fill/copy. A reference
    pushed out of the addressable grid is clamped to the nearest valid
    row/column rather than erroring (dragging a fill handle toward the
    sheet's own edge is a rare, low-stakes edge case not worth a
    dedicated #REF!-in-formula-text grammar extension)."""
    m = _ADDR_DOLLAR_RE.match(tok_text)
    if not m:
        return tok_text
    col_dollar, col_str, row_dollar, row_str = m.groups()
    col_idx = col_to_index(col_str)
    row_idx = int(row_str) - 1
    if not col_dollar:
        col_idx = min(max(col_idx + col_delta, 0), MAX_COLS - 1)
    if not row_dollar:
        row_idx = min(max(row_idx + row_delta, 0), MAX_ROWS - 1)
    return "%s%s%s%d" % (col_dollar, index_to_col(col_idx), row_dollar, row_idx + 1)


def translate_formula(raw_text, row_delta, col_delta):
    """Return `raw_text` with every cell/range reference shifted by
    (row_delta, col_delta) -- the relative-reference adjustment Excel
    applies when a formula is copied or dragged via the fill handle.
    $-anchored rows/columns are left unchanged on that axis. A
    non-formula value (no leading '=') is returned unchanged. Operates
    at the token level (reusing the tokenizer's REF_SHAPED token, which
    already preserves '$' verbatim) rather than the AST, so it never
    touches text inside string literals or anything else that merely
    looks like a reference. Raises FormulaSyntaxError if `raw_text`
    doesn't tokenize (mirrors set_cell_raw's own validation)."""
    if not raw_text.startswith("="):
        return raw_text
    tokens = tokenize(raw_text[1:])
    parts = []
    for tok in tokens:
        if tok.type == "EOF":
            break
        if tok.type == "REF_SHAPED":
            parts.append(_translate_ref_token(tok.text, row_delta, col_delta))
        else:
            parts.append(tok.text)
    return "=" + "".join(parts)


# ============================================================================
# Error values
# ============================================================================

class ErrorValue(object):
    __slots__ = ("token",)

    def __init__(self, token):
        self.token = token

    def __repr__(self):
        return self.token

    def __eq__(self, other):
        return isinstance(other, ErrorValue) and self.token == other.token

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(("ErrorValue", self.token))


DIV0 = ErrorValue("#DIV/0!")
NAME = ErrorValue("#NAME?")
REF = ErrorValue("#REF!")
VALUE = ErrorValue("#VALUE!")
NUM = ErrorValue("#NUM!")
CIRCULAR = ErrorValue("#CIRCULAR!")
NA = ErrorValue("#N/A")
GENERIC_ERROR = ErrorValue("#ERROR!")


class FormulaSyntaxError(Exception):
    """Raised while parsing formula text. Caller should reject the edit and
    keep the cell's previous value — never store an unparseable formula."""
    pass


class FormulaEvalError(Exception):
    """Raised during evaluation; carries the ErrorValue to display."""
    def __init__(self, error_value):
        super(FormulaEvalError, self).__init__(error_value.token)
        self.error_value = error_value


# ============================================================================
# Coercion helpers — also the re-raise chokepoints for error propagation
# ============================================================================

def to_number(v):
    if v is None:
        return 0.0
    if isinstance(v, ErrorValue):
        raise FormulaEvalError(v)
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.strip())
        except ValueError:
            raise FormulaEvalError(VALUE)
    raise FormulaEvalError(VALUE)


def to_text(v):
    if v is None:
        return ""
    if isinstance(v, ErrorValue):
        raise FormulaEvalError(v)
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, float):
        return "%.10g" % v
    return str(v)


def to_bool(v):
    if v is None:
        return False
    if isinstance(v, ErrorValue):
        raise FormulaEvalError(v)
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    if isinstance(v, str) and v.strip().upper() in ("TRUE", "FALSE"):
        return v.strip().upper() == "TRUE"
    raise FormulaEvalError(VALUE)


def _guard_finite(v):
    """Convert nan/inf results from math ops into #NUM! rather than letting
    them flow into the grid as confusing text."""
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        raise FormulaEvalError(NUM)
    return v


# ============================================================================
# Tokenizer
# ============================================================================

_TOKEN_SPEC = [
    ("NUMBER", r"\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?"),
    ("STRING", r'"(?:[^"]|"")*"'),
    # REF_SHAPED must be tried before WORD: a $ can sit before the column
    # letters, before the row digits, both, or neither (A1 / $A1 / A$1 /
    # $A$1), and only this dedicated pattern correctly consumes a
    # middle-placed $ (e.g. "A$1") as ONE token -- the plain WORD pattern
    # can't, since $ isn't a word character, so "A$1" would otherwise
    # split into "A$" + the separate number "1", silently breaking any
    # row-absolute/column-relative (or column-absolute/row-relative)
    # reference typed in a real formula, not just fill/copy translation.
    ("REF_SHAPED", r"\$?[A-Za-z]{1,3}\$?[0-9]{1,7}"),
    ("WORD", r"[A-Za-z_][A-Za-z0-9_]*"),
    ("NE", r"<>"), ("LE", r"<="), ("GE", r">="),
    ("LPAREN", r"\("), ("RPAREN", r"\)"), ("COMMA", r","), ("COLON", r":"),
    ("PLUS", r"\+"), ("MINUS", r"-"), ("STAR", r"\*"), ("SLASH", r"/"),
    ("CARET", r"\^"), ("AMP", r"&"), ("PERCENT", r"%"),
    ("EQ", r"="), ("LT", r"<"), ("GT", r">"),
    ("WS", r"[ \t]+"),
]
_MASTER_RE = re.compile("|".join("(?P<%s>%s)" % (n, p) for n, p in _TOKEN_SPEC))


class Token(object):
    __slots__ = ("type", "text")

    def __init__(self, type_, text):
        self.type = type_
        self.text = text

    def __repr__(self):
        return "Token(%s,%r)" % (self.type, self.text)


def tokenize(text):
    tokens = []
    pos = 0
    n = len(text)
    while pos < n:
        m = _MASTER_RE.match(text, pos)
        if not m:
            raise FormulaSyntaxError("Unexpected character %r at position %d" % (text[pos], pos))
        kind = m.lastgroup
        tok_text = m.group()
        pos = m.end()
        if kind == "WS":
            continue
        if kind == "WORD":
            tokens.append(Token("IDENT", tok_text.upper()))
            continue
        tokens.append(Token(kind, tok_text))
    tokens.append(Token("EOF", ""))
    return tokens


# ============================================================================
# AST nodes
# ============================================================================

class Node(object):
    def eval(self, ctx):
        raise NotImplementedError

    def precedents(self, out):
        pass


class NumberLit(Node):
    def __init__(self, value):
        self.value = value

    def eval(self, ctx):
        return self.value


class StringLit(Node):
    def __init__(self, value):
        self.value = value

    def eval(self, ctx):
        return self.value


class BoolLit(Node):
    def __init__(self, value):
        self.value = value

    def eval(self, ctx):
        return self.value


class CellRef(Node):
    def __init__(self, row, col):
        self.row = row
        self.col = col

    @classmethod
    def parse(cls, text):
        row, col = parse_address(text.replace("$", ""))
        return cls(row, col)

    def eval(self, ctx):
        return ctx.resolve_cell(self.row, self.col)

    def precedents(self, out):
        out.add((self.row, self.col))


class RangeRef(Node):
    def __init__(self, start, end):
        self.start = start
        self.end = end

    def cells(self):
        r0, r1 = sorted((self.start.row, self.end.row))
        c0, c1 = sorted((self.start.col, self.end.col))
        for r in range(r0, r1 + 1):
            for c in range(c0, c1 + 1):
                yield (r, c)

    def eval(self, ctx):
        """A bare range used where a scalar is expected (e.g. the '+' in
        '=B1:B200+G1:G200') doesn't error outright -- it uses Excel's
        classic "implicit intersection": a single-column range resolves
        to the entry in the row the FORMULA ITSELF is in (so the same
        formula, filled down a column, naturally does row-by-row
        arithmetic between the two source columns); a single-row range
        resolves by column the same way. This is the older, non-spilling
        Excel behavior (no dynamic-array/#SPILL! support here) -- a
        genuinely 2-D range, or one that doesn't intersect the formula's
        own row/column, still raises #VALUE!, matching Excel too."""
        r0, r1 = sorted((self.start.row, self.end.row))
        c0, c1 = sorted((self.start.col, self.end.col))
        if r0 == r1 and c0 == c1:
            return ctx.resolve_cell(r0, c0)
        if c0 == c1 and r0 != r1:
            if ctx.current_row is not None and r0 <= ctx.current_row <= r1:
                return ctx.resolve_cell(ctx.current_row, c0)
            raise FormulaEvalError(VALUE)
        if r0 == r1 and c0 != c1:
            if ctx.current_col is not None and c0 <= ctx.current_col <= c1:
                return ctx.resolve_cell(r0, ctx.current_col)
            raise FormulaEvalError(VALUE)
        raise FormulaEvalError(VALUE)  # a genuine 2-D range -- no scalar to intersect

    def precedents(self, out):
        out.update(self.cells())


class NameRef(Node):
    """A bare identifier that isn't TRUE/FALSE and isn't a function call.
    v1 has no named ranges, so this always evaluates to #NAME?."""
    def __init__(self, name):
        self.name = name

    def eval(self, ctx):
        raise FormulaEvalError(NAME)


class UnaryOp(Node):
    def __init__(self, op, operand):
        self.op = op
        self.operand = operand

    def eval(self, ctx):
        v = to_number(self.operand.eval(ctx))
        if self.op == "MINUS":
            return -v
        if self.op == "PLUS":
            return v
        if self.op == "PCT":
            return v / 100.0
        raise FormulaEvalError(VALUE)

    def precedents(self, out):
        self.operand.precedents(out)


_CMP_OPS = {
    "EQ": lambda a, b: a == b, "NE": lambda a, b: a != b,
    "LT": lambda a, b: a < b, "LE": lambda a, b: a <= b,
    "GT": lambda a, b: a > b, "GE": lambda a, b: a >= b,
}


def _compare(op, lv, rv):
    if isinstance(lv, ErrorValue):
        raise FormulaEvalError(lv)
    if isinstance(rv, ErrorValue):
        raise FormulaEvalError(rv)
    # Mixed-type comparisons: fall back to text comparison if either side
    # isn't numeric, matching a permissive (not strict-Excel) convention.
    try:
        a, b = to_number(lv), to_number(rv)
    except FormulaEvalError:
        a, b = to_text(lv), to_text(rv)
    return _CMP_OPS[op](a, b)


class BinOp(Node):
    def __init__(self, op, left, right):
        self.op = op
        self.left = left
        self.right = right

    def eval(self, ctx):
        if self.op == "AMP":
            return to_text(self.left.eval(ctx)) + to_text(self.right.eval(ctx))
        if self.op in _CMP_OPS:
            return _compare(self.op, self.left.eval(ctx), self.right.eval(ctx))
        lv, rv = to_number(self.left.eval(ctx)), to_number(self.right.eval(ctx))
        if self.op == "PLUS":
            return lv + rv
        if self.op == "MINUS":
            return lv - rv
        if self.op == "STAR":
            return lv * rv
        if self.op == "SLASH":
            if rv == 0:
                raise FormulaEvalError(DIV0)
            return lv / rv
        if self.op == "CARET":
            return _safe_pow(lv, rv)
        raise FormulaEvalError(VALUE)

    def precedents(self, out):
        self.left.precedents(out)
        self.right.precedents(out)


def _safe_pow(base, exp):
    try:
        result = base ** exp
    except (ValueError, OverflowError, ZeroDivisionError):
        raise FormulaEvalError(NUM)
    if isinstance(result, complex):
        raise FormulaEvalError(NUM)
    return _guard_finite(float(result))


class FunctionCall(Node):
    def __init__(self, name, args):
        self.name = name
        self.args = args

    def eval(self, ctx):
        fn = ctx.functions.get(self.name)
        if fn is None:
            raise FormulaEvalError(NAME)
        return fn(self.args, ctx)

    def precedents(self, out):
        for a in self.args:
            a.precedents(out)


# ============================================================================
# Parser
# ============================================================================

class Parser(object):
    def __init__(self, tokens):
        self.tokens = tokens
        self.i = 0

    def peek(self):
        return self.tokens[self.i]

    def advance(self):
        t = self.tokens[self.i]
        self.i += 1
        return t

    def expect(self, type_):
        t = self.peek()
        if t.type != type_:
            raise FormulaSyntaxError("Expected %s, found %r" % (type_, t.text))
        return self.advance()

    def parse(self):
        if self.peek().type == "EOF":
            raise FormulaSyntaxError("Empty formula")
        node = self.expr()
        self.expect("EOF")
        return node

    def expr(self):
        return self.comparison()

    def comparison(self):
        node = self.concat()
        while self.peek().type in ("EQ", "NE", "LT", "LE", "GT", "GE"):
            op = self.advance().type
            node = BinOp(op, node, self.concat())
        return node

    def concat(self):
        node = self.additive()
        while self.peek().type == "AMP":
            self.advance()
            node = BinOp("AMP", node, self.additive())
        return node

    def additive(self):
        node = self.term()
        while self.peek().type in ("PLUS", "MINUS"):
            op = self.advance().type
            node = BinOp(op, node, self.term())
        return node

    def term(self):
        node = self.unary()
        while self.peek().type in ("STAR", "SLASH"):
            op = self.advance().type
            node = BinOp(op, node, self.unary())
        return node

    def unary(self):
        if self.peek().type in ("MINUS", "PLUS"):
            op = self.advance().type
            return UnaryOp(op, self.unary())
        return self.power()

    def power(self):
        node = self.postfix()
        if self.peek().type == "CARET":
            self.advance()
            return BinOp("CARET", node, self.unary())  # right-assoc via recursing to unary
        return node

    def postfix(self):
        node = self.primary()
        while self.peek().type == "PERCENT":
            self.advance()
            node = UnaryOp("PCT", node)
        return node

    def primary(self):
        tok = self.peek()
        if tok.type == "NUMBER":
            self.advance()
            return NumberLit(float(tok.text))
        if tok.type == "STRING":
            self.advance()
            return StringLit(tok.text[1:-1].replace('""', '"'))
        if tok.type == "LPAREN":
            self.advance()
            n = self.expr()
            self.expect("RPAREN")
            return n
        if tok.type == "REF_SHAPED":
            self.advance()
            if self.peek().type == "LPAREN":
                return self._finish_call(tok.text)
            if self.peek().type == "COLON":
                self.advance()
                end = self.expect("REF_SHAPED")
                return RangeRef(CellRef.parse(tok.text), CellRef.parse(end.text))
            return CellRef.parse(tok.text)
        if tok.type == "IDENT":
            self.advance()
            if self.peek().type == "LPAREN":
                return self._finish_call(tok.text)
            if tok.text == "TRUE":
                return BoolLit(True)
            if tok.text == "FALSE":
                return BoolLit(False)
            return NameRef(tok.text)
        raise FormulaSyntaxError("Unexpected token %r" % tok.text)

    def _finish_call(self, name):
        self.expect("LPAREN")
        args = []
        if self.peek().type != "RPAREN":
            args.append(self.expr())
            while self.peek().type == "COMMA":
                self.advance()
                args.append(self.expr())
        self.expect("RPAREN")
        return FunctionCall(name.upper().replace("$", ""), args)


def parse_formula(text):
    """Parse formula text (WITHOUT the leading '='). Raises FormulaSyntaxError."""
    return Parser(tokenize(text)).parse()


# ============================================================================
# Evaluation context
# ============================================================================

class EvalContext(object):
    def __init__(self, sheet=None, functions=None):
        self.sheet = sheet
        self.functions = functions if functions is not None else FUNCTIONS
        # Set by evaluate_cell to the cell currently being computed, so
        # argument-less ROW()/COLUMN() can report the formula's own
        # location, matching Excel.
        self.current_row = None
        self.current_col = None

    def resolve_cell(self, row, col):
        if row < 0 or row >= MAX_ROWS or col < 0 or col >= MAX_COLS:
            raise FormulaEvalError(REF)
        if self.sheet is None:
            raise FormulaEvalError(REF)
        cell = self.sheet.get_cell(row, col)
        if cell is None or cell.kind == CellKind.EMPTY:
            return None
        if isinstance(cell.value, ErrorValue):
            raise FormulaEvalError(cell.value)
        return cell.value


def eval_formula(ast, sheet=None, functions=None):
    """Convenience one-shot evaluator (used by the calculator, and available
    for ad-hoc use). Returns the value, or an ErrorValue on failure."""
    ctx = EvalContext(sheet=sheet, functions=functions)
    try:
        return ast.eval(ctx)
    except FormulaEvalError as e:
        return e.error_value
    except ZeroDivisionError:
        return DIV0
    except RecursionError:
        return GENERIC_ERROR
    except (TypeError, ValueError):
        return VALUE


# ============================================================================
# Value iteration helpers for aggregate / ordered-pair functions
# ============================================================================

def iter_values(arg_nodes, ctx, skip_range_bool=False):
    """Flatten args into a scalar stream. Blanks are always skipped.

    Text values coming from a RangeRef are always silently skipped,
    matching Excel: text cells inside a *range* argument to
    SUM/AVERAGE/COUNT/AND/OR/etc. are ignored, not coerced or errored --
    e.g. SUM(F1:F200) where F1 holds a text header label like "Voltage"
    must still sum the numeric cells below it.

    skip_range_bool additionally skips logical (bool) values from a
    RangeRef -- needed for math aggregates (SUM/AVERAGE/STDEV/...), where
    Excel also ignores logicals found in a range. AND/OR must NOT set
    this: combining logical values pulled from a range is their entire
    purpose, so their bools must pass through.

    A literal (non-range) argument is always yielded as-is for normal
    coercion by the caller, e.g. SUM("5", 3) or AND(TRUE, 1=1) should
    still work like Excel does -- Excel only ignores text/logical when it
    comes from a range, not a literal. (An error-valued range cell
    already raises inside ctx.resolve_cell, before reaching here.)
    """
    for node in arg_nodes:
        if isinstance(node, RangeRef):
            for (r, c) in node.cells():
                v = ctx.resolve_cell(r, c)
                if v is None or isinstance(v, str):
                    continue
                if skip_range_bool and isinstance(v, bool):
                    continue
                yield v
        else:
            v = node.eval(ctx)
            if v is not None:
                yield v


def range_to_array(node, ctx):
    """Order-preserving unpack (for paired x/y functions like SLOPE)."""
    if isinstance(node, RangeRef):
        return [ctx.resolve_cell(r, c) for (r, c) in node.cells()]
    return [node.eval(ctx)]


# ============================================================================
# Function library
# ============================================================================

def _num_args(args, ctx):
    return [to_number(v) for v in iter_values(args, ctx, skip_range_bool=True)]


# ---- Math / trig ----------------------------------------------------------

def fn_sum(args, ctx):
    return sum(_num_args(args, ctx))


def fn_product(args, ctx):
    result = 1.0
    for v in _num_args(args, ctx):
        result *= v
    return result


def fn_abs(args, ctx):
    if len(args) != 1:
        raise FormulaEvalError(VALUE)
    return abs(to_number(args[0].eval(ctx)))


def fn_sqrt(args, ctx):
    if len(args) != 1:
        raise FormulaEvalError(VALUE)
    v = to_number(args[0].eval(ctx))
    if v < 0:
        raise FormulaEvalError(NUM)
    return math.sqrt(v)


def fn_exp(args, ctx):
    if len(args) != 1:
        raise FormulaEvalError(VALUE)
    return _guard_finite(math.exp(to_number(args[0].eval(ctx))))


def fn_ln(args, ctx):
    if len(args) != 1:
        raise FormulaEvalError(VALUE)
    v = to_number(args[0].eval(ctx))
    if v <= 0:
        raise FormulaEvalError(NUM)
    return math.log(v)


def fn_log(args, ctx):
    if len(args) not in (1, 2):
        raise FormulaEvalError(VALUE)
    v = to_number(args[0].eval(ctx))
    base = to_number(args[1].eval(ctx)) if len(args) == 2 else 10.0
    if v <= 0 or base <= 0 or base == 1:
        raise FormulaEvalError(NUM)
    return math.log(v, base)


def fn_log10(args, ctx):
    if len(args) != 1:
        raise FormulaEvalError(VALUE)
    v = to_number(args[0].eval(ctx))
    if v <= 0:
        raise FormulaEvalError(NUM)
    return math.log10(v)


def fn_power(args, ctx):
    if len(args) != 2:
        raise FormulaEvalError(VALUE)
    return _safe_pow(to_number(args[0].eval(ctx)), to_number(args[1].eval(ctx)))


def fn_mod(args, ctx):
    if len(args) != 2:
        raise FormulaEvalError(VALUE)
    a, b = to_number(args[0].eval(ctx)), to_number(args[1].eval(ctx))
    if b == 0:
        raise FormulaEvalError(DIV0)
    return a % b  # Python's % follows the divisor's sign, matching Excel's MOD


def _excel_round(v, n, mode):
    factor = 10.0 ** n
    scaled = v * factor
    sign = 1.0 if scaled >= 0 else -1.0
    mag = abs(scaled)
    if mode == "nearest":
        result = math.floor(mag + 0.5)
    elif mode == "up":  # away from zero
        result = math.ceil(mag - 1e-9)
    else:  # "down" -- toward zero
        result = math.floor(mag + 1e-9)
    return sign * result / factor


def fn_round(args, ctx):
    if len(args) != 2:
        raise FormulaEvalError(VALUE)
    return _excel_round(to_number(args[0].eval(ctx)), int(to_number(args[1].eval(ctx))), "nearest")


def fn_roundup(args, ctx):
    if len(args) != 2:
        raise FormulaEvalError(VALUE)
    return _excel_round(to_number(args[0].eval(ctx)), int(to_number(args[1].eval(ctx))), "up")


def fn_rounddown(args, ctx):
    if len(args) != 2:
        raise FormulaEvalError(VALUE)
    return _excel_round(to_number(args[0].eval(ctx)), int(to_number(args[1].eval(ctx))), "down")


def fn_int(args, ctx):
    if len(args) != 1:
        raise FormulaEvalError(VALUE)
    return float(math.floor(to_number(args[0].eval(ctx)))) # Excel INT floors (not truncates)


def fn_sign(args, ctx):
    if len(args) != 1:
        raise FormulaEvalError(VALUE)
    v = to_number(args[0].eval(ctx))
    return float((v > 0) - (v < 0))


def fn_pi(args, ctx):
    if args:
        raise FormulaEvalError(VALUE)
    return math.pi


def fn_e(args, ctx):
    if args:
        raise FormulaEvalError(VALUE)
    return math.e


def _trig1(pyfunc, domain_check=None):
    def _fn(args, ctx):
        if len(args) != 1:
            raise FormulaEvalError(VALUE)
        v = to_number(args[0].eval(ctx))
        if domain_check is not None and not domain_check(v):
            raise FormulaEvalError(NUM)
        return _guard_finite(pyfunc(v))
    return _fn


fn_sin = _trig1(math.sin)
fn_cos = _trig1(math.cos)
fn_tan = _trig1(math.tan)
fn_asin = _trig1(math.asin, lambda v: -1.0 <= v <= 1.0)
fn_acos = _trig1(math.acos, lambda v: -1.0 <= v <= 1.0)
fn_atan = _trig1(math.atan)


def fn_atan2(args, ctx):
    if len(args) != 2:
        raise FormulaEvalError(VALUE)
    y, x = to_number(args[0].eval(ctx)), to_number(args[1].eval(ctx))
    return math.atan2(y, x)


# ---- Aggregate / statistical ----------------------------------------------

def fn_count(args, ctx):
    n = 0
    for node in args:
        if isinstance(node, RangeRef):
            for (r, c) in node.cells():
                v = ctx.resolve_cell(r, c)
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    n += 1
        else:
            v = node.eval(ctx)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                n += 1
    return float(n)


def fn_counta(args, ctx):
    n = 0
    for node in args:
        if isinstance(node, RangeRef):
            for (r, c) in node.cells():
                if ctx.resolve_cell(r, c) is not None:
                    n += 1
        else:
            if node.eval(ctx) is not None:
                n += 1
    return float(n)


def fn_countblank(args, ctx):
    n = 0
    for node in args:
        if isinstance(node, RangeRef):
            for (r, c) in node.cells():
                if ctx.resolve_cell(r, c) is None:
                    n += 1
    return float(n)


def fn_average(args, ctx):
    vals = _num_args(args, ctx)
    if not vals:
        raise FormulaEvalError(DIV0)
    return sum(vals) / len(vals)


def fn_median(args, ctx):
    vals = sorted(_num_args(args, ctx))
    if not vals:
        raise FormulaEvalError(NUM)
    n = len(vals)
    mid = n // 2
    if n % 2:
        return vals[mid]
    return (vals[mid - 1] + vals[mid]) / 2.0


def fn_min(args, ctx):
    vals = _num_args(args, ctx)
    return min(vals) if vals else 0.0


def fn_max(args, ctx):
    vals = _num_args(args, ctx)
    return max(vals) if vals else 0.0


def _variance(vals, ddof):
    n = len(vals)
    if n <= ddof:
        raise FormulaEvalError(DIV0)
    mean = sum(vals) / n
    return sum((v - mean) ** 2 for v in vals) / (n - ddof)


def fn_stdev(args, ctx):
    return math.sqrt(_variance(_num_args(args, ctx), 1))


def fn_stdevp(args, ctx):
    return math.sqrt(_variance(_num_args(args, ctx), 0))


def fn_var(args, ctx):
    return _variance(_num_args(args, ctx), 1)


def fn_varp(args, ctx):
    return _variance(_num_args(args, ctx), 0)


# ---- Regression (numpy.polyfit convention, matching this codebase) -------

def _try_number(v):
    """Like to_number, but never raises for a value Excel's regression
    functions treat as 'exclude this pair' -- blank, non-numeric text, or
    a logical value -- returning None instead (an upstream error still
    propagates, matching resolve_cell's own re-raise). This mirrors the
    range-argument leniency in iter_values: a whole-column reference
    (e.g. from clicking a column header) commonly includes a text header
    label above the numeric data, which must not break the whole fit."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, ErrorValue):
        raise FormulaEvalError(v)
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.strip())
        except ValueError:
            return None
    return None


def _xy_pairs(args, ctx):
    """Excel order: known_y's first, known_x's second. Pairs are matched
    by position; a pair is excluded if either side is blank/text/logical
    (see _try_number) -- matching Excel's own SLOPE/TREND/etc. semantics."""
    if len(args) != 2:
        raise FormulaEvalError(VALUE)
    y_raw = range_to_array(args[0], ctx)
    x_raw = range_to_array(args[1], ctx)
    xs, ys = [], []
    for x, y in zip(x_raw, y_raw):
        xn, yn = _try_number(x), _try_number(y)
        if xn is not None and yn is not None:
            xs.append(xn)
            ys.append(yn)
    if len(xs) < 2:
        raise FormulaEvalError(DIV0)
    return (xs, ys)


def fn_slope(args, ctx):
    import numpy as np
    x, y = _xy_pairs(args, ctx)
    coeffs = np.polyfit(np.array(x), np.array(y), 1)
    return float(coeffs[0])


def fn_intercept(args, ctx):
    import numpy as np
    x, y = _xy_pairs(args, ctx)
    coeffs = np.polyfit(np.array(x), np.array(y), 1)
    return float(coeffs[1])


def fn_rsq(args, ctx):
    import numpy as np
    x, y = _xy_pairs(args, ctx)
    x_arr, y_arr = np.array(x), np.array(y)
    coeffs = np.polyfit(x_arr, y_arr, 1)
    fitted = np.polyval(coeffs, x_arr)
    ss_res = float(np.sum((y_arr - fitted) ** 2))
    ss_tot = float(np.sum((y_arr - np.mean(y_arr)) ** 2))
    if ss_tot == 0:
        raise FormulaEvalError(DIV0)
    return 1.0 - ss_res / ss_tot


def fn_trend(args, ctx):
    import numpy as np
    if len(args) not in (2, 3):
        raise FormulaEvalError(VALUE)
    x, y = _xy_pairs(args[:2], ctx)
    coeffs = np.polyfit(np.array(x), np.array(y), 1)
    if len(args) == 3:
        new_x = to_number(args[2].eval(ctx))
    else:
        new_x = x[-1]
    return float(np.polyval(coeffs, new_x))


def fn_forecast(args, ctx):
    import numpy as np
    if len(args) != 3:
        raise FormulaEvalError(VALUE)
    new_x = to_number(args[0].eval(ctx))
    x, y = _xy_pairs(args[1:], ctx)
    coeffs = np.polyfit(np.array(x), np.array(y), 1)
    return float(np.polyval(coeffs, new_x))


# ---- Logical ---------------------------------------------------------------

def fn_if(args, ctx):
    if len(args) not in (2, 3):
        raise FormulaEvalError(VALUE)
    if to_bool(args[0].eval(ctx)):
        return args[1].eval(ctx)
    return args[2].eval(ctx) if len(args) == 3 else False


def fn_and(args, ctx):
    if not args:
        raise FormulaEvalError(VALUE)
    return all(to_bool(v) for v in iter_values(args, ctx))


def fn_or(args, ctx):
    if not args:
        raise FormulaEvalError(VALUE)
    return any(to_bool(v) for v in iter_values(args, ctx))


def fn_not(args, ctx):
    if len(args) != 1:
        raise FormulaEvalError(VALUE)
    return not to_bool(args[0].eval(ctx))


def fn_iferror(args, ctx):
    if len(args) != 2:
        raise FormulaEvalError(VALUE)
    try:
        result = args[0].eval(ctx)
    except FormulaEvalError:
        return args[1].eval(ctx)
    return args[1].eval(ctx) if isinstance(result, ErrorValue) else result


def fn_iserror(args, ctx):
    if len(args) != 1:
        raise FormulaEvalError(VALUE)
    try:
        result = args[0].eval(ctx)
    except FormulaEvalError:
        return True
    return isinstance(result, ErrorValue)


def fn_isblank(args, ctx):
    if len(args) != 1:
        raise FormulaEvalError(VALUE)
    node = args[0]
    if isinstance(node, CellRef):
        return ctx.resolve_cell(node.row, node.col) is None
    return node.eval(ctx) is None


def fn_isnumber(args, ctx):
    if len(args) != 1:
        raise FormulaEvalError(VALUE)
    try:
        v = args[0].eval(ctx)
    except FormulaEvalError:
        return False
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def fn_istext(args, ctx):
    if len(args) != 1:
        raise FormulaEvalError(VALUE)
    try:
        v = args[0].eval(ctx)
    except FormulaEvalError:
        return False
    return isinstance(v, str)


def fn_islogical(args, ctx):
    if len(args) != 1:
        raise FormulaEvalError(VALUE)
    try:
        v = args[0].eval(ctx)
    except FormulaEvalError:
        return False
    return isinstance(v, bool)


def fn_isna(args, ctx):
    if len(args) != 1:
        raise FormulaEvalError(VALUE)
    try:
        v = args[0].eval(ctx)
    except FormulaEvalError as e:
        return e.error_value is NA
    return False


def fn_na(args, ctx):
    if len(args) != 0:
        raise FormulaEvalError(VALUE)
    raise FormulaEvalError(NA)


def fn_ifs(args, ctx):
    """IFS(cond1, val1, cond2, val2, ...) -- first TRUE condition wins,
    lazily (later conditions/values are never evaluated), matching Excel.
    #N/A if none match, matching Excel's own behavior."""
    if len(args) < 2 or len(args) % 2 != 0:
        raise FormulaEvalError(VALUE)
    for i in range(0, len(args), 2):
        if to_bool(args[i].eval(ctx)):
            return args[i + 1].eval(ctx)
    raise FormulaEvalError(NA)


def fn_switch(args, ctx):
    """SWITCH(expr, val1, res1, [val2, res2, ...], [default]) -- lazy:
    only the matching (or default) branch is evaluated."""
    if len(args) < 3:
        raise FormulaEvalError(VALUE)
    target = args[0].eval(ctx)
    i = 1
    while i + 1 < len(args):
        if args[i].eval(ctx) == target:
            return args[i + 1].eval(ctx)
        i += 2
    if i < len(args):  # trailing default value, no matching pair
        return args[i].eval(ctx)
    raise FormulaEvalError(NA)


def fn_xor(args, ctx):
    n_true = sum(1 for v in iter_values(args, ctx) if to_bool(v))
    return (n_true % 2) == 1


# ---- Text -------------------------------------------------------------------

def fn_concatenate(args, ctx):
    return "".join(to_text(v) for v in (a.eval(ctx) for a in args))


def fn_len(args, ctx):
    if len(args) != 1:
        raise FormulaEvalError(VALUE)
    return float(len(to_text(args[0].eval(ctx))))


def fn_upper(args, ctx):
    if len(args) != 1:
        raise FormulaEvalError(VALUE)
    return to_text(args[0].eval(ctx)).upper()


def fn_lower(args, ctx):
    if len(args) != 1:
        raise FormulaEvalError(VALUE)
    return to_text(args[0].eval(ctx)).lower()


def fn_trim(args, ctx):
    if len(args) != 1:
        raise FormulaEvalError(VALUE)
    return " ".join(to_text(args[0].eval(ctx)).split())


def fn_left(args, ctx):
    if len(args) not in (1, 2):
        raise FormulaEvalError(VALUE)
    s = to_text(args[0].eval(ctx))
    n = int(to_number(args[1].eval(ctx))) if len(args) == 2 else 1
    return s[:max(n, 0)]


def fn_right(args, ctx):
    if len(args) not in (1, 2):
        raise FormulaEvalError(VALUE)
    s = to_text(args[0].eval(ctx))
    n = int(to_number(args[1].eval(ctx))) if len(args) == 2 else 1
    return s[-n:] if n > 0 else ""


def fn_mid(args, ctx):
    if len(args) != 3:
        raise FormulaEvalError(VALUE)
    s = to_text(args[0].eval(ctx))
    start = int(to_number(args[1].eval(ctx)))
    n = int(to_number(args[2].eval(ctx)))
    if start < 1 or n < 0:
        raise FormulaEvalError(VALUE)
    return s[start - 1: start - 1 + n]


def fn_find(args, ctx):
    """Case-sensitive substring search; 1-based position, #VALUE! if absent."""
    if len(args) not in (2, 3):
        raise FormulaEvalError(VALUE)
    needle = to_text(args[0].eval(ctx))
    hay = to_text(args[1].eval(ctx))
    start = int(to_number(args[2].eval(ctx))) if len(args) == 3 else 1
    if start < 1:
        raise FormulaEvalError(VALUE)
    idx = hay.find(needle, start - 1)
    if idx < 0:
        raise FormulaEvalError(VALUE)
    return float(idx + 1)


def fn_search(args, ctx):
    """Case-insensitive substring search (wildcards not supported)."""
    if len(args) not in (2, 3):
        raise FormulaEvalError(VALUE)
    needle = to_text(args[0].eval(ctx)).lower()
    hay = to_text(args[1].eval(ctx)).lower()
    start = int(to_number(args[2].eval(ctx))) if len(args) == 3 else 1
    if start < 1:
        raise FormulaEvalError(VALUE)
    idx = hay.find(needle, start - 1)
    if idx < 0:
        raise FormulaEvalError(VALUE)
    return float(idx + 1)


def fn_substitute(args, ctx):
    if len(args) not in (3, 4):
        raise FormulaEvalError(VALUE)
    text = to_text(args[0].eval(ctx))
    old = to_text(args[1].eval(ctx))
    new = to_text(args[2].eval(ctx))
    if len(args) == 3 or not old:
        return text.replace(old, new) if old else text
    instance = int(to_number(args[3].eval(ctx)))
    if instance < 1:
        raise FormulaEvalError(VALUE)
    parts = text.split(old)
    if instance >= len(parts):
        return text
    return old.join(parts[:instance]) + new + old.join(parts[instance:])


def fn_replace(args, ctx):
    if len(args) != 4:
        raise FormulaEvalError(VALUE)
    text = to_text(args[0].eval(ctx))
    start = int(to_number(args[1].eval(ctx)))
    n = int(to_number(args[2].eval(ctx)))
    new = to_text(args[3].eval(ctx))
    if start < 1 or n < 0:
        raise FormulaEvalError(VALUE)
    return text[:start - 1] + new + text[start - 1 + n:]


def fn_proper(args, ctx):
    if len(args) != 1:
        raise FormulaEvalError(VALUE)
    return to_text(args[0].eval(ctx)).title()


def fn_rept(args, ctx):
    if len(args) != 2:
        raise FormulaEvalError(VALUE)
    text = to_text(args[0].eval(ctx))
    n = int(to_number(args[1].eval(ctx)))
    if n < 0:
        raise FormulaEvalError(VALUE)
    return text * n


def fn_exact(args, ctx):
    if len(args) != 2:
        raise FormulaEvalError(VALUE)
    return to_text(args[0].eval(ctx)) == to_text(args[1].eval(ctx))


def fn_value(args, ctx):
    if len(args) != 1:
        raise FormulaEvalError(VALUE)
    return to_number(args[0].eval(ctx))


def fn_char(args, ctx):
    if len(args) != 1:
        raise FormulaEvalError(VALUE)
    n = int(to_number(args[0].eval(ctx)))
    if not (1 <= n <= 0x10FFFF):
        raise FormulaEvalError(VALUE)
    return chr(n)


def fn_code(args, ctx):
    if len(args) != 1:
        raise FormulaEvalError(VALUE)
    s = to_text(args[0].eval(ctx))
    if not s:
        raise FormulaEvalError(VALUE)
    return float(ord(s[0]))


def fn_concat(args, ctx):
    """Like CONCATENATE, but also flattens range arguments (Excel's newer
    CONCAT function does this; CONCATENATE never accepted ranges)."""
    parts = []
    for node in args:
        if isinstance(node, RangeRef):
            for (r, c) in node.cells():
                v = ctx.resolve_cell(r, c)
                if v is not None:
                    parts.append(to_text(v))
        else:
            parts.append(to_text(node.eval(ctx)))
    return "".join(parts)


def fn_textjoin(args, ctx):
    if len(args) < 3:
        raise FormulaEvalError(VALUE)
    delim = to_text(args[0].eval(ctx))
    ignore_empty = to_bool(args[1].eval(ctx))
    parts = []
    for node in args[2:]:
        if isinstance(node, RangeRef):
            for (r, c) in node.cells():
                v = ctx.resolve_cell(r, c)
                text = to_text(v) if v is not None else ""
                if ignore_empty and text == "":
                    continue
                parts.append(text)
        else:
            text = to_text(node.eval(ctx))
            if ignore_empty and text == "":
                continue
            parts.append(text)
    return delim.join(parts)


def fn_text(args, ctx):
    """Reduced-scope TEXT(): supports a decimal-place count via a format like
    '0.00'; anything else falls back to a plain string conversion."""
    if len(args) != 2:
        raise FormulaEvalError(VALUE)
    v = args[0].eval(ctx)
    fmt = to_text(args[1].eval(ctx))
    m = re.match(r'^0(?:\.(0+))?$', fmt.strip())
    if m and isinstance(v, (int, float)) and not isinstance(v, bool):
        decimals = len(m.group(1)) if m.group(1) else 0
        return "%.*f" % (decimals, float(v))
    return to_text(v)


# ---- Date / Time (Excel serial-number convention: days since 1899-12-30) --

_EXCEL_EPOCH = datetime.date(1899, 12, 30)


def _date_to_serial(d):
    return float((d - _EXCEL_EPOCH).days)


def _serial_to_date(serial):
    return _EXCEL_EPOCH + datetime.timedelta(days=int(serial))


def _serial_to_datetime(serial):
    days = int(serial)
    frac = serial - days
    base = datetime.datetime.combine(_EXCEL_EPOCH, datetime.time())
    return base + datetime.timedelta(days=days, seconds=round(frac * 86400))


def fn_today(args, ctx):
    if len(args) != 0:
        raise FormulaEvalError(VALUE)
    return _date_to_serial(datetime.date.today())


def fn_now(args, ctx):
    if len(args) != 0:
        raise FormulaEvalError(VALUE)
    now = datetime.datetime.now()
    return _date_to_serial(now.date()) + (now - datetime.datetime.combine(now.date(), datetime.time())).total_seconds() / 86400.0


def fn_date(args, ctx):
    if len(args) != 3:
        raise FormulaEvalError(VALUE)
    y = int(to_number(args[0].eval(ctx)))
    m = int(to_number(args[1].eval(ctx)))
    d = int(to_number(args[2].eval(ctx)))
    try:
        # Excel allows month/day overflow (e.g. month=13 -> next January);
        # emulate by building the 1st of (y, m) via divmod then adding days.
        y_adj, m_adj = divmod(m - 1, 12)
        base = datetime.date(y + y_adj, m_adj + 1, 1)
        result = base + datetime.timedelta(days=d - 1)
    except (ValueError, OverflowError):
        raise FormulaEvalError(NUM)
    return _date_to_serial(result)


def fn_year(args, ctx):
    if len(args) != 1:
        raise FormulaEvalError(VALUE)
    return float(_serial_to_date(to_number(args[0].eval(ctx))).year)


def fn_month(args, ctx):
    if len(args) != 1:
        raise FormulaEvalError(VALUE)
    return float(_serial_to_date(to_number(args[0].eval(ctx))).month)


def fn_day(args, ctx):
    if len(args) != 1:
        raise FormulaEvalError(VALUE)
    return float(_serial_to_date(to_number(args[0].eval(ctx))).day)


def fn_weekday(args, ctx):
    if len(args) not in (1, 2):
        raise FormulaEvalError(VALUE)
    d = _serial_to_date(to_number(args[0].eval(ctx)))
    ret_type = int(to_number(args[1].eval(ctx))) if len(args) == 2 else 1
    py_wd = d.weekday()  # Monday=0 .. Sunday=6
    if ret_type == 1:
        return float((py_wd + 1) % 7 + 1)  # Sunday=1 .. Saturday=7
    if ret_type == 2:
        return float(py_wd + 1)  # Monday=1 .. Sunday=7
    if ret_type == 3:
        return float(py_wd)  # Monday=0 .. Sunday=6
    raise FormulaEvalError(NUM)


def fn_hour(args, ctx):
    if len(args) != 1:
        raise FormulaEvalError(VALUE)
    return float(_serial_to_datetime(to_number(args[0].eval(ctx))).hour)


def fn_minute(args, ctx):
    if len(args) != 1:
        raise FormulaEvalError(VALUE)
    return float(_serial_to_datetime(to_number(args[0].eval(ctx))).minute)


def fn_second(args, ctx):
    if len(args) != 1:
        raise FormulaEvalError(VALUE)
    return float(_serial_to_datetime(to_number(args[0].eval(ctx))).second)


def fn_days(args, ctx):
    if len(args) != 2:
        raise FormulaEvalError(VALUE)
    end = to_number(args[0].eval(ctx))
    start = to_number(args[1].eval(ctx))
    return end - start


def _add_months(d, months):
    total = (d.year * 12 + (d.month - 1)) + months
    y, m = divmod(total, 12)
    return y, m + 1


def fn_edate(args, ctx):
    if len(args) != 2:
        raise FormulaEvalError(VALUE)
    d = _serial_to_date(to_number(args[0].eval(ctx)))
    months = int(to_number(args[1].eval(ctx)))
    y, m = _add_months(d, months)
    last_day = _days_in_month(y, m)
    try:
        result = datetime.date(y, m, min(d.day, last_day))
    except (ValueError, OverflowError):
        raise FormulaEvalError(NUM)
    return _date_to_serial(result)


def _days_in_month(y, m):
    y2, m2 = (y, m + 1) if m < 12 else (y + 1, 1)
    return (datetime.date(y2, m2, 1) - datetime.date(y, m, 1)).days


def fn_eomonth(args, ctx):
    if len(args) != 2:
        raise FormulaEvalError(VALUE)
    d = _serial_to_date(to_number(args[0].eval(ctx)))
    months = int(to_number(args[1].eval(ctx)))
    y, m = _add_months(d, months)
    try:
        result = datetime.date(y, m, _days_in_month(y, m))
    except (ValueError, OverflowError):
        raise FormulaEvalError(NUM)
    return _date_to_serial(result)


def fn_datedif(args, ctx):
    if len(args) != 3:
        raise FormulaEvalError(VALUE)
    start = _serial_to_date(to_number(args[0].eval(ctx)))
    end = _serial_to_date(to_number(args[1].eval(ctx)))
    unit = to_text(args[2].eval(ctx)).strip().upper()
    if end < start:
        raise FormulaEvalError(NUM)
    if unit == "D":
        return float((end - start).days)
    if unit == "M":
        months = (end.year - start.year) * 12 + (end.month - start.month)
        if end.day < start.day:
            months -= 1
        return float(max(months, 0))
    if unit == "Y":
        years = end.year - start.year
        if (end.month, end.day) < (start.month, start.day):
            years -= 1
        return float(max(years, 0))
    if unit == "MD":
        days = end.day - start.day
        if days < 0:
            prev_month_days = _days_in_month(*((end.year, end.month - 1) if end.month > 1 else (end.year - 1, 12)))
            days += prev_month_days
        return float(days)
    if unit == "YM":
        months = end.month - start.month
        if end.day < start.day:
            months -= 1
        return float(months % 12)
    if unit == "YD":
        anniversary = datetime.date(end.year, start.month, start.day) if (start.month, start.day) != (2, 29) or _is_leap(end.year) else datetime.date(end.year, 2, 28)
        if anniversary > end:
            anniversary = datetime.date(anniversary.year - 1, anniversary.month, anniversary.day)
        return float((end - anniversary).days)
    raise FormulaEvalError(NUM)


def _is_leap(y):
    return y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)


# ---- Lookup / Reference -----------------------------------------------------

def fn_row(args, ctx):
    if len(args) == 0:
        if ctx.current_row is None:
            raise FormulaEvalError(VALUE)
        return float(ctx.current_row + 1)
    if len(args) != 1:
        raise FormulaEvalError(VALUE)
    node = args[0]
    if isinstance(node, CellRef):
        return float(node.row + 1)
    if isinstance(node, RangeRef):
        return float(min(node.start.row, node.end.row) + 1)
    raise FormulaEvalError(VALUE)


def fn_column(args, ctx):
    if len(args) == 0:
        if ctx.current_col is None:
            raise FormulaEvalError(VALUE)
        return float(ctx.current_col + 1)
    if len(args) != 1:
        raise FormulaEvalError(VALUE)
    node = args[0]
    if isinstance(node, CellRef):
        return float(node.col + 1)
    if isinstance(node, RangeRef):
        return float(min(node.start.col, node.end.col) + 1)
    raise FormulaEvalError(VALUE)


def fn_rows(args, ctx):
    if len(args) != 1 or not isinstance(args[0], RangeRef):
        raise FormulaEvalError(VALUE)
    node = args[0]
    return float(abs(node.end.row - node.start.row) + 1)


def fn_columns(args, ctx):
    if len(args) != 1 or not isinstance(args[0], RangeRef):
        raise FormulaEvalError(VALUE)
    node = args[0]
    return float(abs(node.end.col - node.start.col) + 1)


def fn_choose(args, ctx):
    if len(args) < 2:
        raise FormulaEvalError(VALUE)
    idx = int(to_number(args[0].eval(ctx)))
    if idx < 1 or idx >= len(args):
        raise FormulaEvalError(VALUE)
    return args[idx].eval(ctx)


def _range_bounds(node):
    if not isinstance(node, RangeRef):
        raise FormulaEvalError(VALUE)
    r0, r1 = sorted((node.start.row, node.end.row))
    c0, c1 = sorted((node.start.col, node.end.col))
    return r0, r1, c0, c1


def fn_index(args, ctx):
    if len(args) not in (2, 3):
        raise FormulaEvalError(VALUE)
    r0, r1, c0, c1 = _range_bounds(args[0])
    n_rows, n_cols = r1 - r0 + 1, c1 - c0 + 1
    row_num = int(to_number(args[1].eval(ctx)))
    col_num = int(to_number(args[2].eval(ctx))) if len(args) == 3 else None
    if col_num is None:
        # 1-D range: a single number addresses along whichever dimension
        # isn't 1, matching Excel's INDEX(range, n) dual convention.
        if n_cols == 1 and n_rows != 1:
            col_num = 1
        elif n_rows == 1 and n_cols != 1:
            col_num, row_num = row_num, 1
        else:
            col_num = 1
    if row_num < 1 or row_num > n_rows or col_num < 1 or col_num > n_cols:
        raise FormulaEvalError(REF)
    return ctx.resolve_cell(r0 + row_num - 1, c0 + col_num - 1)


def fn_match(args, ctx):
    if len(args) not in (2, 3):
        raise FormulaEvalError(VALUE)
    target = args[0].eval(ctx)
    array = range_to_array(args[1], ctx)
    match_type = int(to_number(args[2].eval(ctx))) if len(args) == 3 else 1
    if match_type == 0:
        for i, v in enumerate(array):
            if v == target or (_comparable_eq(v, target)):
                return float(i + 1)
        raise FormulaEvalError(NA)
    if match_type == 1:
        best = None
        for i, v in enumerate(array):
            if v is None or isinstance(v, (str, bool)):
                continue
            if v <= target:
                best = i
            else:
                break
        if best is None:
            raise FormulaEvalError(NA)
        return float(best + 1)
    if match_type == -1:
        best = None
        for i, v in enumerate(array):
            if v is None or isinstance(v, (str, bool)):
                continue
            if v >= target:
                best = i
            else:
                break
        if best is None:
            raise FormulaEvalError(NA)
        return float(best + 1)
    raise FormulaEvalError(VALUE)


def _comparable_eq(a, b):
    try:
        return to_number(a) == to_number(b)
    except FormulaEvalError:
        return to_text(a).lower() == to_text(b).lower()


def fn_vlookup(args, ctx):
    if len(args) not in (3, 4):
        raise FormulaEvalError(VALUE)
    target = args[0].eval(ctx)
    r0, r1, c0, c1 = _range_bounds(args[1])
    col_index = int(to_number(args[2].eval(ctx)))
    if col_index < 1 or c0 + col_index - 1 > c1:
        raise FormulaEvalError(REF)
    approximate = to_bool(args[3].eval(ctx)) if len(args) == 4 else True
    best_row = None
    for r in range(r0, r1 + 1):
        v = ctx.resolve_cell(r, c0)
        if approximate:
            if v is None or isinstance(v, (str, bool)):
                continue
            if v <= target:
                best_row = r
            else:
                break
        else:
            if v == target or _comparable_eq(v, target):
                best_row = r
                break
    if best_row is None:
        raise FormulaEvalError(NA)
    return ctx.resolve_cell(best_row, c0 + col_index - 1)


def fn_hlookup(args, ctx):
    if len(args) not in (3, 4):
        raise FormulaEvalError(VALUE)
    target = args[0].eval(ctx)
    r0, r1, c0, c1 = _range_bounds(args[1])
    row_index = int(to_number(args[2].eval(ctx)))
    if row_index < 1 or r0 + row_index - 1 > r1:
        raise FormulaEvalError(REF)
    approximate = to_bool(args[3].eval(ctx)) if len(args) == 4 else True
    best_col = None
    for c in range(c0, c1 + 1):
        v = ctx.resolve_cell(r0, c)
        if approximate:
            if v is None or isinstance(v, (str, bool)):
                continue
            if v <= target:
                best_col = c
            else:
                break
        else:
            if v == target or _comparable_eq(v, target):
                best_col = c
                break
    if best_col is None:
        raise FormulaEvalError(NA)
    return ctx.resolve_cell(r0 + row_index - 1, best_col)


# ---- More math --------------------------------------------------------------

def fn_ceiling(args, ctx):
    if len(args) != 2:
        raise FormulaEvalError(VALUE)
    v = to_number(args[0].eval(ctx))
    sig = to_number(args[1].eval(ctx))
    if sig == 0:
        return 0.0
    return math.ceil(v / sig) * sig


def fn_floor(args, ctx):
    if len(args) != 2:
        raise FormulaEvalError(VALUE)
    v = to_number(args[0].eval(ctx))
    sig = to_number(args[1].eval(ctx))
    if sig == 0:
        return 0.0
    return math.floor(v / sig) * sig


def fn_trunc(args, ctx):
    if len(args) not in (1, 2):
        raise FormulaEvalError(VALUE)
    v = to_number(args[0].eval(ctx))
    digits = int(to_number(args[1].eval(ctx))) if len(args) == 2 else 0
    factor = 10.0 ** digits
    return math.trunc(v * factor) / factor


def fn_gcd(args, ctx):
    vals = [int(v) for v in _num_args(args, ctx)]
    if not vals:
        raise FormulaEvalError(VALUE)
    result = abs(vals[0])
    for v in vals[1:]:
        result = math.gcd(result, abs(v))
    return float(result)


def fn_lcm(args, ctx):
    vals = [int(v) for v in _num_args(args, ctx)]
    if not vals:
        raise FormulaEvalError(VALUE)
    result = abs(vals[0])
    for v in vals[1:]:
        v = abs(v)
        if result == 0 or v == 0:
            result = 0
        else:
            result = result * v // math.gcd(result, v)
    return float(result)


def fn_combin(args, ctx):
    if len(args) != 2:
        raise FormulaEvalError(VALUE)
    n = int(to_number(args[0].eval(ctx)))
    k = int(to_number(args[1].eval(ctx)))
    if n < 0 or k < 0 or k > n:
        raise FormulaEvalError(NUM)
    return float(math.comb(n, k))


def fn_permut(args, ctx):
    if len(args) != 2:
        raise FormulaEvalError(VALUE)
    n = int(to_number(args[0].eval(ctx)))
    k = int(to_number(args[1].eval(ctx)))
    if n < 0 or k < 0 or k > n:
        raise FormulaEvalError(NUM)
    return float(math.perm(n, k))


def fn_sumproduct(args, ctx):
    if not args:
        raise FormulaEvalError(VALUE)
    arrays = [range_to_array(a, ctx) for a in args]
    n = len(arrays[0])
    if any(len(a) != n for a in arrays):
        raise FormulaEvalError(VALUE)
    total = 0.0
    for i in range(n):
        product = 1.0
        for arr in arrays:
            v = arr[i]
            product *= to_number(v) if not isinstance(v, str) else 0.0
        total += product
    return total


def fn_rand(args, ctx):
    if len(args) != 0:
        raise FormulaEvalError(VALUE)
    return random.random()


def fn_randbetween(args, ctx):
    if len(args) != 2:
        raise FormulaEvalError(VALUE)
    lo = int(to_number(args[0].eval(ctx)))
    hi = int(to_number(args[1].eval(ctx)))
    if lo > hi:
        raise FormulaEvalError(NUM)
    return float(random.randint(lo, hi))


# ---- Conditional aggregates (COUNTIF/SUMIF family) --------------------------

def _stringify(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, float):
        return "%.10g" % v
    return str(v)


def _wildcard_match(value_text, pattern):
    regex = "^" + re.escape(pattern).replace(r"\*", ".*").replace(r"\?", ".") + "$"
    return re.match(regex, value_text, re.IGNORECASE) is not None


def _criteria_match(value, criteria):
    """Excel-style criteria matching for COUNTIF/SUMIF/etc: a bare number
    or bool means direct equality; text may start with a comparison
    operator (>, <, >=, <=, <>, =) or contain wildcards (* / ?)."""
    if isinstance(criteria, bool):
        return isinstance(value, bool) and value == criteria
    if isinstance(criteria, (int, float)):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and value == criteria
    if criteria is None:
        return value is None
    text = str(criteria).strip()
    m = re.match(r'^(<=|>=|<>|=|<|>)(.*)$', text)
    if m:
        op, rhs = m.group(1), m.group(2).strip()
        try:
            rhs_num = float(rhs)
        except ValueError:
            rhs_num = None
        is_num_val = isinstance(value, (int, float)) and not isinstance(value, bool)
        if op == "=":
            if rhs_num is not None:
                return is_num_val and value == rhs_num
            return _wildcard_match(_stringify(value), rhs)
        if op == "<>":
            if rhs_num is not None:
                return not (is_num_val and value == rhs_num)
            return not _wildcard_match(_stringify(value), rhs)
        if rhs_num is None or not is_num_val:
            return False
        if op == "<":
            return value < rhs_num
        if op == ">":
            return value > rhs_num
        if op == "<=":
            return value <= rhs_num
        if op == ">=":
            return value >= rhs_num
    try:
        crit_num = float(text)
        return isinstance(value, (int, float)) and not isinstance(value, bool) and float(value) == crit_num
    except ValueError:
        return _wildcard_match(_stringify(value), text)


def fn_countif(args, ctx):
    if len(args) != 2 or not isinstance(args[0], RangeRef):
        raise FormulaEvalError(VALUE)
    criteria = args[1].eval(ctx)
    n = 0
    for (r, c) in args[0].cells():
        if _criteria_match(ctx.resolve_cell(r, c), criteria):
            n += 1
    return float(n)


def _multi_criteria_mask(pairs, ctx):
    ranges = []
    for range_node, _ in pairs:
        if not isinstance(range_node, RangeRef):
            raise FormulaEvalError(VALUE)
        ranges.append(list(range_node.cells()))
    n = len(ranges[0])
    if any(len(cells) != n for cells in ranges):
        raise FormulaEvalError(VALUE)
    mask = [True] * n
    for (_, crit_node), cells in zip(pairs, ranges):
        criteria = crit_node.eval(ctx)
        for i, (r, c) in enumerate(cells):
            if mask[i] and not _criteria_match(ctx.resolve_cell(r, c), criteria):
                mask[i] = False
    return ranges[0], mask


def fn_countifs(args, ctx):
    if len(args) < 2 or len(args) % 2 != 0:
        raise FormulaEvalError(VALUE)
    pairs = [(args[i], args[i + 1]) for i in range(0, len(args), 2)]
    _, mask = _multi_criteria_mask(pairs, ctx)
    return float(sum(1 for m in mask if m))


def fn_sumif(args, ctx):
    if len(args) not in (2, 3) or not isinstance(args[0], RangeRef):
        raise FormulaEvalError(VALUE)
    criteria = args[1].eval(ctx)
    sum_node = args[2] if len(args) == 3 else args[0]
    if not isinstance(sum_node, RangeRef):
        raise FormulaEvalError(VALUE)
    crit_cells = list(args[0].cells())
    sum_cells = list(sum_node.cells())
    if len(crit_cells) != len(sum_cells):
        raise FormulaEvalError(VALUE)
    total = 0.0
    for (cr, cc), (sr, sc) in zip(crit_cells, sum_cells):
        if _criteria_match(ctx.resolve_cell(cr, cc), criteria):
            sv = ctx.resolve_cell(sr, sc)
            if sv is not None and not isinstance(sv, (str, bool)):
                total += sv
    return total


def fn_sumifs(args, ctx):
    if len(args) < 3 or len(args) % 2 != 1 or not isinstance(args[0], RangeRef):
        raise FormulaEvalError(VALUE)
    pairs = [(args[i], args[i + 1]) for i in range(1, len(args), 2)]
    _, mask = _multi_criteria_mask(pairs, ctx)
    sum_cells = list(args[0].cells())
    if len(sum_cells) != len(mask):
        raise FormulaEvalError(VALUE)
    total = 0.0
    for keep, (sr, sc) in zip(mask, sum_cells):
        if keep:
            sv = ctx.resolve_cell(sr, sc)
            if sv is not None and not isinstance(sv, (str, bool)):
                total += sv
    return total


def fn_averageif(args, ctx):
    if len(args) not in (2, 3) or not isinstance(args[0], RangeRef):
        raise FormulaEvalError(VALUE)
    criteria = args[1].eval(ctx)
    avg_node = args[2] if len(args) == 3 else args[0]
    if not isinstance(avg_node, RangeRef):
        raise FormulaEvalError(VALUE)
    crit_cells = list(args[0].cells())
    avg_cells = list(avg_node.cells())
    if len(crit_cells) != len(avg_cells):
        raise FormulaEvalError(VALUE)
    vals = []
    for (cr, cc), (ar, ac) in zip(crit_cells, avg_cells):
        if _criteria_match(ctx.resolve_cell(cr, cc), criteria):
            av = ctx.resolve_cell(ar, ac)
            if av is not None and not isinstance(av, (str, bool)):
                vals.append(av)
    if not vals:
        raise FormulaEvalError(DIV0)
    return sum(vals) / len(vals)


def fn_averageifs(args, ctx):
    if len(args) < 3 or len(args) % 2 != 1 or not isinstance(args[0], RangeRef):
        raise FormulaEvalError(VALUE)
    pairs = [(args[i], args[i + 1]) for i in range(1, len(args), 2)]
    _, mask = _multi_criteria_mask(pairs, ctx)
    avg_cells = list(args[0].cells())
    vals = []
    for keep, (ar, ac) in zip(mask, avg_cells):
        if keep:
            av = ctx.resolve_cell(ar, ac)
            if av is not None and not isinstance(av, (str, bool)):
                vals.append(av)
    if not vals:
        raise FormulaEvalError(DIV0)
    return sum(vals) / len(vals)


def _minmax_ifs(args, ctx, pick):
    if len(args) < 3 or len(args) % 2 != 1 or not isinstance(args[0], RangeRef):
        raise FormulaEvalError(VALUE)
    pairs = [(args[i], args[i + 1]) for i in range(1, len(args), 2)]
    _, mask = _multi_criteria_mask(pairs, ctx)
    target_cells = list(args[0].cells())
    vals = []
    for keep, (r, c) in zip(mask, target_cells):
        if keep:
            v = ctx.resolve_cell(r, c)
            if v is not None and not isinstance(v, (str, bool)):
                vals.append(v)
    return pick(vals) if vals else 0.0


def fn_maxifs(args, ctx):
    return _minmax_ifs(args, ctx, max)


def fn_minifs(args, ctx):
    return _minmax_ifs(args, ctx, min)


# ---- More statistics ---------------------------------------------------------

def fn_rank(args, ctx):
    if len(args) not in (2, 3):
        raise FormulaEvalError(VALUE)
    target = to_number(args[0].eval(ctx))
    vals = _num_args([args[1]], ctx)
    order = int(to_number(args[2].eval(ctx))) if len(args) == 3 else 0
    if target not in vals:
        raise FormulaEvalError(NA)
    if order == 0:
        rank = sum(1 for v in vals if v > target) + 1
    else:
        rank = sum(1 for v in vals if v < target) + 1
    return float(rank)


def fn_large(args, ctx):
    if len(args) != 2:
        raise FormulaEvalError(VALUE)
    vals = sorted(_num_args([args[0]], ctx), reverse=True)
    k = int(to_number(args[1].eval(ctx)))
    if k < 1 or k > len(vals):
        raise FormulaEvalError(NUM)
    return vals[k - 1]


def fn_small(args, ctx):
    if len(args) != 2:
        raise FormulaEvalError(VALUE)
    vals = sorted(_num_args([args[0]], ctx))
    k = int(to_number(args[1].eval(ctx)))
    if k < 1 or k > len(vals):
        raise FormulaEvalError(NUM)
    return vals[k - 1]


def fn_mode(args, ctx):
    vals = _num_args(args, ctx)
    if not vals:
        raise FormulaEvalError(NA)
    counts = {}
    for v in vals:
        counts[v] = counts.get(v, 0) + 1
    best = max(counts.values())
    if best == 1:
        raise FormulaEvalError(NA)
    for v in vals:
        if counts[v] == best:
            return v
    raise FormulaEvalError(NA)


def _percentile(vals, p):
    if not vals:
        raise FormulaEvalError(NUM)
    if not (0.0 <= p <= 1.0):
        raise FormulaEvalError(NUM)
    s = sorted(vals)
    if len(s) == 1:
        return s[0]
    rank = p * (len(s) - 1)
    lo = int(math.floor(rank))
    hi = int(math.ceil(rank))
    if lo == hi:
        return s[lo]
    frac = rank - lo
    return s[lo] + (s[hi] - s[lo]) * frac


def fn_percentile(args, ctx):
    if len(args) != 2:
        raise FormulaEvalError(VALUE)
    vals = _num_args([args[0]], ctx)
    p = to_number(args[1].eval(ctx))
    return _percentile(vals, p)


def fn_quartile(args, ctx):
    if len(args) != 2:
        raise FormulaEvalError(VALUE)
    vals = _num_args([args[0]], ctx)
    q = int(to_number(args[1].eval(ctx)))
    if q not in (0, 1, 2, 3, 4):
        raise FormulaEvalError(NUM)
    return _percentile(vals, q / 4.0)


FUNCTIONS = {
    "SUM": fn_sum, "PRODUCT": fn_product, "ABS": fn_abs, "SQRT": fn_sqrt,
    "EXP": fn_exp, "LN": fn_ln, "LOG": fn_log, "LOG10": fn_log10,
    "POWER": fn_power, "MOD": fn_mod, "ROUND": fn_round, "ROUNDUP": fn_roundup,
    "ROUNDDOWN": fn_rounddown, "INT": fn_int, "SIGN": fn_sign, "PI": fn_pi,
    "E": fn_e, "SIN": fn_sin, "COS": fn_cos, "TAN": fn_tan, "ASIN": fn_asin,
    "ACOS": fn_acos, "ATAN": fn_atan, "ATAN2": fn_atan2,
    "CEILING": fn_ceiling, "FLOOR": fn_floor, "TRUNC": fn_trunc,
    "GCD": fn_gcd, "LCM": fn_lcm, "COMBIN": fn_combin, "PERMUT": fn_permut,
    "SUMPRODUCT": fn_sumproduct, "RAND": fn_rand, "RANDBETWEEN": fn_randbetween,

    "COUNT": fn_count, "COUNTA": fn_counta, "COUNTBLANK": fn_countblank,
    "AVERAGE": fn_average, "MEDIAN": fn_median, "MIN": fn_min, "MAX": fn_max,
    "STDEV": fn_stdev, "STDEVP": fn_stdevp, "VAR": fn_var, "VARP": fn_varp,
    "COUNTIF": fn_countif, "COUNTIFS": fn_countifs, "SUMIF": fn_sumif,
    "SUMIFS": fn_sumifs, "AVERAGEIF": fn_averageif, "AVERAGEIFS": fn_averageifs,
    "MAXIFS": fn_maxifs, "MINIFS": fn_minifs, "RANK": fn_rank,
    "LARGE": fn_large, "SMALL": fn_small, "MODE": fn_mode,
    "PERCENTILE": fn_percentile, "QUARTILE": fn_quartile,

    "SLOPE": fn_slope, "INTERCEPT": fn_intercept, "RSQ": fn_rsq,
    "TREND": fn_trend, "FORECAST": fn_forecast,

    "IF": fn_if, "AND": fn_and, "OR": fn_or, "NOT": fn_not, "XOR": fn_xor,
    "IFERROR": fn_iferror, "ISERROR": fn_iserror, "ISBLANK": fn_isblank,
    "ISNUMBER": fn_isnumber, "ISTEXT": fn_istext, "ISLOGICAL": fn_islogical,
    "ISNA": fn_isna, "NA": fn_na, "IFS": fn_ifs, "SWITCH": fn_switch,

    "CONCATENATE": fn_concatenate, "CONCAT": fn_concat, "LEN": fn_len,
    "UPPER": fn_upper, "LOWER": fn_lower, "TRIM": fn_trim, "LEFT": fn_left,
    "RIGHT": fn_right, "MID": fn_mid, "TEXT": fn_text, "FIND": fn_find,
    "SEARCH": fn_search, "SUBSTITUTE": fn_substitute, "REPLACE": fn_replace,
    "PROPER": fn_proper, "REPT": fn_rept, "EXACT": fn_exact, "VALUE": fn_value,
    "CHAR": fn_char, "CODE": fn_code, "TEXTJOIN": fn_textjoin,

    "TODAY": fn_today, "NOW": fn_now, "DATE": fn_date, "YEAR": fn_year,
    "MONTH": fn_month, "DAY": fn_day, "WEEKDAY": fn_weekday, "HOUR": fn_hour,
    "MINUTE": fn_minute, "SECOND": fn_second, "DAYS": fn_days,
    "EDATE": fn_edate, "EOMONTH": fn_eomonth, "DATEDIF": fn_datedif,

    "ROW": fn_row, "COLUMN": fn_column, "ROWS": fn_rows, "COLUMNS": fn_columns,
    "CHOOSE": fn_choose, "INDEX": fn_index, "MATCH": fn_match,
    "VLOOKUP": fn_vlookup, "HLOOKUP": fn_hlookup,
}


def make_calculator_functions(angle_mode_getter):
    """A function registry for the calculator tab: identical to FUNCTIONS
    except SIN/COS/TAN/ASIN/ACOS/ATAN respect a live Deg/Rad toggle
    (angle_mode_getter() returns 'deg' or 'rad'). Spreadsheet formulas always
    use radians (Excel convention) via the plain FUNCTIONS dict above."""
    funcs = dict(FUNCTIONS)

    def _to_rad(v):
        return math.radians(v) if angle_mode_getter() == "deg" else v

    def _from_rad(v):
        return math.degrees(v) if angle_mode_getter() == "deg" else v

    def _calc_sin(args, ctx):
        if len(args) != 1:
            raise FormulaEvalError(VALUE)
        return _guard_finite(math.sin(_to_rad(to_number(args[0].eval(ctx)))))

    def _calc_cos(args, ctx):
        if len(args) != 1:
            raise FormulaEvalError(VALUE)
        return _guard_finite(math.cos(_to_rad(to_number(args[0].eval(ctx)))))

    def _calc_tan(args, ctx):
        if len(args) != 1:
            raise FormulaEvalError(VALUE)
        return _guard_finite(math.tan(_to_rad(to_number(args[0].eval(ctx)))))

    def _calc_asin(args, ctx):
        if len(args) != 1:
            raise FormulaEvalError(VALUE)
        v = to_number(args[0].eval(ctx))
        if not (-1.0 <= v <= 1.0):
            raise FormulaEvalError(NUM)
        return _from_rad(math.asin(v))

    def _calc_acos(args, ctx):
        if len(args) != 1:
            raise FormulaEvalError(VALUE)
        v = to_number(args[0].eval(ctx))
        if not (-1.0 <= v <= 1.0):
            raise FormulaEvalError(NUM)
        return _from_rad(math.acos(v))

    def _calc_atan(args, ctx):
        if len(args) != 1:
            raise FormulaEvalError(VALUE)
        return _from_rad(math.atan(to_number(args[0].eval(ctx))))

    def _fact(args, ctx):
        if len(args) != 1:
            raise FormulaEvalError(VALUE)
        v = to_number(args[0].eval(ctx))
        n = int(round(v))
        if n < 0 or abs(v - n) > 1e-9 or n > 170:
            raise FormulaEvalError(NUM)
        return float(math.factorial(n))

    funcs["SIN"] = _calc_sin
    funcs["COS"] = _calc_cos
    funcs["TAN"] = _calc_tan
    funcs["ASIN"] = _calc_asin
    funcs["ACOS"] = _calc_acos
    funcs["ATAN"] = _calc_atan
    funcs["FACT"] = _fact
    return funcs


# ============================================================================
# Cell / Sheet data model
# ============================================================================

class CellKind(object):
    EMPTY = "empty"
    NUMBER = "number"
    TEXT = "text"
    BOOLEAN = "boolean"
    FORMULA = "formula"


class Cell(object):
    __slots__ = ("row", "col", "raw", "kind", "ast", "value", "dirty")

    def __init__(self, row, col):
        self.row = row
        self.col = col
        self.raw = ""
        self.kind = CellKind.EMPTY
        self.ast = None
        self.value = None
        self.dirty = True

    @property
    def address(self):
        return format_address(self.row, self.col)

    @property
    def is_error(self):
        return isinstance(self.value, ErrorValue)

    @property
    def display(self):
        if self.kind == CellKind.EMPTY:
            return ""
        if self.is_error:
            return self.value.token
        if isinstance(self.value, bool):
            return "TRUE" if self.value else "FALSE"
        if isinstance(self.value, float):
            return "%.10g" % self.value
        return "" if self.value is None else str(self.value)


def _classify_literal(text):
    text = text.strip()
    if text == "":
        return CellKind.EMPTY, None
    try:
        return CellKind.NUMBER, float(text)
    except ValueError:
        pass
    if text.upper() in ("TRUE", "FALSE"):
        return CellKind.BOOLEAN, text.upper() == "TRUE"
    return CellKind.TEXT, text


class Sheet(object):
    def __init__(self, name="Sheet1"):
        self.name = name
        self.cells = {}       # (row,col) -> Cell
        self.precedents = {}  # (row,col) -> set of (row,col) this cell's formula reads
        self.dependents = {}  # (row,col) -> set of (row,col) that read this cell

    def get_cell(self, row, col):
        return self.cells.get((row, col))

    def get_or_create(self, row, col):
        key = (row, col)
        cell = self.cells.get(key)
        if cell is None:
            cell = Cell(row, col)
            self.cells[key] = cell
        return cell


def set_cell_raw(sheet, row, col, raw_text):
    """Update ONE cell's stored formula/value and its precedent edges.
    Does NOT recalculate — call sheet-wide recalculate() once after a batch
    of edits (critical for bulk file import: one recalculate() per import,
    not one per cell). Raises FormulaSyntaxError on a malformed formula —
    caller should reject the edit and keep the cell's previous value."""
    cell = sheet.get_or_create(row, col)
    raw_text = raw_text or ""
    old_precedents = sheet.precedents.get((row, col), frozenset())

    if raw_text.startswith("="):
        new_ast = parse_formula(raw_text[1:])  # may raise FormulaSyntaxError
        cell.raw = raw_text
        cell.ast = new_ast
        cell.kind = CellKind.FORMULA
        cell.value = None
    else:
        cell.raw = raw_text
        cell.ast = None
        cell.kind, cell.value = _classify_literal(raw_text)

    new_precedents = set()
    if cell.ast is not None:
        cell.ast.precedents(new_precedents)
    for p in old_precedents - new_precedents:
        sheet.dependents.get(p, set()).discard((row, col))
    for p in new_precedents - old_precedents:
        sheet.dependents.setdefault(p, set()).add((row, col))
    sheet.precedents[(row, col)] = new_precedents
    cell.dirty = True
    return cell


def clear_cell(sheet, row, col):
    set_cell_raw(sheet, row, col, "")


# ============================================================================
# Recalculation (full-sheet topological order, Kahn's algorithm)
# ============================================================================

def evaluate_cell(cell, ctx):
    if cell.kind != CellKind.FORMULA:
        return
    ctx.current_row, ctx.current_col = cell.row, cell.col
    try:
        cell.value = _guard_finite(cell.ast.eval(ctx))
    except FormulaEvalError as e:
        cell.value = e.error_value
    except ZeroDivisionError:
        cell.value = DIV0
    except RecursionError:
        cell.value = GENERIC_ERROR
    except (TypeError, ValueError):
        cell.value = VALUE
    cell.dirty = False


def _topological_order(sheet, formula_keys):
    formula_set = set(formula_keys)
    indegree = dict((k, 0) for k in formula_keys)
    adj = dict((k, []) for k in formula_keys)
    for k in formula_keys:
        for p in sheet.precedents.get(k, ()):
            if p in formula_set:
                adj[p].append(k)
                indegree[k] += 1

    from collections import deque
    queue = deque(k for k in formula_keys if indegree[k] == 0)
    order = []
    while queue:
        k = queue.popleft()
        order.append(k)
        for nxt in adj[k]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)

    if len(order) == len(formula_keys):
        return order, []
    ordered_set = set(order)
    return order, [k for k in formula_keys if k not in ordered_set]


def recalculate(sheet):
    """Full-sheet recalculation. Call exactly once after a batch of edits."""
    formula_keys = [k for k, c in sheet.cells.items() if c.kind == CellKind.FORMULA]
    order, cyclic = _topological_order(sheet, formula_keys)

    ctx = EvalContext(sheet=sheet)
    for key in order:
        evaluate_cell(sheet.cells[key], ctx)
    for key in cyclic:
        cell = sheet.cells[key]
        cell.value = CIRCULAR
        cell.dirty = False
