# Copyright 2019 MIT Probabilistic Computing Project.
# See LICENSE.txt

from math import isinf

import sympy

from sympy import oo
from sympy import sympify
from sympy.abc import X as symX
from sympy.core.relational import Relational

from sympy.calculus.util import function_range
from sympy.calculus.util import limit

from .poly import solve_poly_equality
from .poly import solve_poly_inequality

from .sym_util import get_symbols
from .sym_util import EmptySet
from .sym_util import Reals
from .sym_util import ExtReals
from .sym_util import ExtRealsPos

# ==============================================================================
# Utilities.

def transform_interval(interval, a, b):
    return sympy.Interval(a, b, interval.left_open, interval.right_open)

def make_sympy_polynomial(coeffs):
    terms = [c*symX**i for (i,c) in enumerate(coeffs)]
    return sympy.Add(*terms)

def make_subexpr(subexpr):
    if isinstance(subexpr, Transform):
        return subexpr
    assert False, 'Invalid subexpr: %s' % (subexpr,)

def solveset_bounds(sympy_expr, b, strict):
    if not isinf(b):
        expr = (sympy_expr < b) if strict else (sympy_expr <= b)
        return sympy.solveset(expr, domain=Reals)
    if b < oo:
        return EmptySet
    return Reals

def listify_interval(interval):
    if interval == EmptySet:
        return [EmptySet]
    if isinstance(interval, sympy.Interval):
        return [interval]
    if isinstance(interval, sympy.Union):
        intervals = interval.args
        assert all(isinstance(intv, sympy.Interval) for intv in intervals)
        return intervals
    assert False, 'Unknown interval: %s' % (interval,)

def sympify_number(x):
    error = NotImplementedError('Expected a numeric term, not %s' % (x,))
    try:
        sym = sympify(x)
        if not sym.is_number:
            raise error
        return sym
    except sympy.SympifyError:
        raise error

def polyify(expr):
    if isinstance(expr, Poly):
        return expr
    return Poly(expr, (0, 1))

def add_coeffs(a, b):
    length = max(len(a), len(b))
    a_prime = a + (0,) * (length - len(a))
    b_prime = b + (0,) * (length - len(b))
    assert len(a_prime) == len(b_prime)
    return [xa + xb for (xa, xb) in zip(a_prime, b_prime)]

def poly_add(poly_a, poly_b):
    assert poly_a.subexpr == poly_b.subexpr
    # Alternative implementation.
    # sym_poly_a = sympy.Poly(poly_a.symexpr)
    # sym_poly_b = sympy.Poly(poly_b.symexpr)
    # sym_poly_c = sym_poly_a + sym_poly_b
    # assert sym_poly_c.all_coeffs()[::-1] == coeffs
    coeffs = add_coeffs(poly_a.coeffs, poly_b.coeffs)
    return Poly(poly_a.subexpr, coeffs)

def poly_mul(poly_a, poly_b):
    assert poly_a.subexpr == poly_b.subexpr
    sym_poly_a = sympy.Poly(poly_a.symexpr, symX)
    sym_poly_b = sympy.Poly(poly_b.symexpr, symX)
    sym_poly_c = sym_poly_a * sym_poly_b
    coeffs = sym_poly_c.all_coeffs()[::-1]
    return Poly(poly_a.subexpr, coeffs)

# ==============================================================================
# Custom invertible function language.

class Transform(object):
    def symbol(self):
        raise NotImplementedError()
    def domain(self):
        raise NotImplementedError()
    def range(self):
        raise NotImplementedError()
    def ffwd(self, x):
        raise NotImplementedError()
    def finv(self, x):
        raise NotImplementedError()
    def evaluate(self, x):
        # pylint: disable=no-member
        y = self.subexpr.evaluate(x)
        return self.ffwd(y)
    def invert(self, x):
        if x is EmptySet:
            return EmptySet
        if isinstance(x, sympy.FiniteSet):
            return self.invert_finite(x)
        if isinstance(x, sympy.Interval):
            return self.invert_interval(x)
        if isinstance(x, sympy.Union):
            intervals = [self.invert(y) for y in x.args]
            return sympy.Union(*intervals)

    def invert_finite(self, values):
        raise NotImplementedError()
    def invert_interval(self, interval):
        raise NotImplementedError()

    # Multiplication.
    def __mul__(self, x):
        poly_self = polyify(self)
        # Is x a constant?
        try:
            x_val = sympify_number(x)
            coeffs = [x_val*c for c in poly_self.coeffs]
            return Poly(poly_self.subexpr, coeffs)
        except NotImplementedError:
            pass
        # Multiply polynomial terms only if subexpressions match.
        poly_x = polyify(x)
        if poly_x.subexpr != poly_self.subexpr:
            raise NotImplementedError('Invalid addition %s + %s' % (self, x))
        return poly_mul(poly_self, poly_x)
    def __rmul__(self, x):
        return self * x
    def __neg__(self):
        return -1 * self

    # Exponentiation.
    def __pow__(self, x):
        x_val = sympify_number(x)
        if isinstance(x_val, sympy.Integer):
            return Pow(self, x_val)
        if isinstance(x_val, sympy.Rational):
            (numer, denom) = x_val.as_numer_denom()
            if numer != 1:
                raise NotImplementedError(
                    'Rational powers must be 1/n, not %s' % (x,))
            return Radical(self, denom)
        raise NotImplementedError(
            'Power must be rational or integer, not %s' % (x))

    # Addition.
    def __add__(self, x):
        poly_self = polyify(self)
        # Is x a constant?
        try:
            x_val = sympify_number(x)
            coeffs_new = list(poly_self.coeffs)
            coeffs_new[0] += x_val
            return Poly(poly_self.subexpr, coeffs_new)
        except NotImplementedError:
            pass
        # Add polynomial terms only if subexpressions match.
        poly_x = polyify(x)
        if poly_x.subexpr != poly_self.subexpr:
            raise NotImplementedError('Invalid addition %s + %s' % (self, x))
        return poly_add(poly_self, poly_x)
    def __radd__(self, x):
        return self + x

    # Subtraction.
    def __sub__(self, x):
        return self + (-1 * x)
    def __rsub__(self, x):
        return self - x

    # Comparison.
    def __le__(self, x):
        # self <= x
        x_val = sympify_number(x)
        interval = sympy.Interval(-oo, x_val)
        return EventInterval(self, interval)
    def __lt__(self, x):
        # self < x
        x_val = sympify_number(x)
        interval = sympy.Interval(-oo, x_val, right_open=True)
        return EventInterval(self, interval)
    def __ge__(self, x):
        # self >= x
        x_val = sympify_number(x)
        interval = sympy.Interval(x_val, oo)
        return EventInterval(self, interval)
    def __gt__(self, x):
        # self > x
        x_val = sympify_number(x)
        interval = sympy.Interval(x_val, oo, left_open=True)
        return EventInterval(self, interval)

class Injective(Transform):
    # Injective (one-to-one) transforms.
    def invert_finite(self, values):
        # pylint: disable=no-member
        values_prime = [self.finv(x) for x in values]
        return self.subexpr.invert(values_prime)
    def invert_interval(self, interval):
        # pylint: disable=no-member
        intersection = sympy.Intersection(self.range(), interval)
        if intersection == EmptySet:
            return EmptySet
        (a, b) = (intersection.left, intersection.right)
        a_prime = self.finv(a)
        b_prime = self.finv(b)
        interval_prime = transform_interval(intersection, a_prime, b_prime)
        return self.subexpr.invert(interval_prime)

class Identity(Injective):
    def __init__(self, symbol):
        assert isinstance(symbol, str)
        self.symb = symbol
    def symbol(self):
        return self.symb
    def domain(self):
        return ExtReals
    def range(self):
        return ExtReals
    def ffwd(self, x):
        assert x in self.domain()
        return x
    def finv(self, x):
        assert x in self.range()
        return x
    def evaluate(self, x):
        assert x in self.domain()
        return x
    def invert_finite(self, values):
        return values
    def invert_interval(self, interval):
        return interval
    def __eq__(self, x):
        return isinstance(x, Identity) and self.symb == x.symb
    def __repr__(self):
        return 'Identity(%s)' % (repr(self.symb),)

class Abs(Transform):
    def __init__(self, subexpr):
        self.subexpr = make_subexpr(subexpr)
    def symbol(self):
        return self.subexpr.symbol
    def domain(self):
        return ExtReals
    def range(self):
        return ExtRealsPos
    def ffwd(self, x):
        assert x in self.domain()
        return x if x > 0 else -x
    def finv(self, x):
        assert x in self.range()
        return (x, -x)
    def invert_interval(self, interval):
        intersection = sympy.Intersection(self.range(), interval)
        if intersection == EmptySet:
            return EmptySet
        (a, b) = (intersection.left, intersection.right)
        # Positive solution.
        (a_pos, b_pos) = (a, b)
        interval_pos = transform_interval(intersection, a_pos, b_pos)
        xvals_pos = self.subexpr.invert(interval_pos)
        # Negative solution.
        (a_neg, b_neg) = (-b, -a)
        interval_neg = transform_interval(intersection, a_neg, b_neg)
        xvals_neg = self.subexpr.invert(interval_neg)
        # Return the union.
        return sympy.Union(xvals_pos, xvals_neg)
    def __eq__(self, x):
        return isinstance(x, Abs) and self.subexpr == x.subexpr
    def __repr__(self):
        return 'Abs(%s)' % (repr(self.subexpr))

class Radical(Injective):
    def __init__(self, subexpr, degree):
        assert degree != 0
        self.subexpr = make_subexpr(subexpr)
        self.degree = degree
    def symbol(self):
        return self.subexpr.symbol
    def domain(self):
        return ExtRealsPos
    def range(self):
        return ExtRealsPos
    def ffwd(self, x):
        assert x in self.domain()
        return sympy.Pow(x, sympy.Rational(1, self.degree))
    def finv(self, x):
        return sympy.Pow(x, sympy.Rational(self.degree, 1))
    def __eq__(self, x):
        return isinstance(x, Radical) \
            and self.subexpr == x.subexpr \
            and self.degree == x.degree
    def __repr__(self):
        return 'Radical(degree=%s, %s)' \
            % (repr(self.degree), repr(self.subexpr))

class Exp(Injective):
    def __init__(self, subexpr, base):
        assert base > 0
        self.subexpr = make_subexpr(subexpr)
        self.base = base
    def symbol(self):
        return self.subexpr.symbol
    def domain(self):
        return ExtReals
    def range(self):
        return ExtRealsPos
    def ffwd(self, x):
        assert x in self.domain()
        return sympy.Pow(self.base, x)
    def finv(self, x):
        assert x in self.range()
        return sympy.log(x, self.base) if x > 0 else -oo
    def __eq__(self, x):
        return isinstance(x, Exp) \
            and self.subexpr == x.subexpr \
            and self.base == x.base
    def __repr__(self):
        if self.base == sympy.exp(1):
            return 'ExpNat(%s)' % (repr(self.subexpr),)
        return 'Exp(base=%s, %s)' \
            % (repr(self.base), repr(self.subexpr))

class Log(Injective):
    def __init__(self, subexpr, base):
        assert base > 1
        self.subexpr = make_subexpr(subexpr)
        self.base = base
    def symbol(self):
        return self.subexpr.symbol
    def domain(self):
        return ExtRealsPos
    def range(self):
        return ExtReals
    def ffwd(self, x):
        assert x in self.domain()
        return sympy.log(x, self.base) if x > 0 else -oo
    def finv(self, x):
        assert x in self.range()
        return sympy.Pow(self.base, x)
    def __eq__(self, x):
        return isinstance(x, Log) \
            and self.subexpr == x.subexpr \
            and self.base == x.base
    def __repr__(self):
        if self.base == sympy.exp(1):
            return 'LogNat(%s)' % (repr(self.subexpr),)
        return 'Log(base=%s, %s)' \
            % (repr(self.base), repr(self.subexpr))

class Poly(Transform):
    def __init__(self, subexpr, coeffs):
        assert len(coeffs) > 1
        self.subexpr = make_subexpr(subexpr)
        self.coeffs = tuple(coeffs)
        self.degree = len(coeffs) - 1
        self.symexpr = make_sympy_polynomial(coeffs)
    def symbol(self):
        return self.subexpr.symbol
    def domain(self):
        return ExtReals
    def range(self):
        result = function_range(self.symexpr, symX, Reals)
        pos_inf = sympy.FiniteSet(oo) if result.right == oo else EmptySet
        neg_inf = sympy.FiniteSet(-oo) if result.left == -oo else EmptySet
        return sympy.Union(result, pos_inf, neg_inf)
    def ffwd(self, x):
        assert x in self.domain()
        return self.symexpr.subs(symX, x) \
            if not isinf(x) else limit(self.symexpr, symX, x)
    def finv(self, x):
        assert x in self.range()
        return solve_poly_equality(self.symexpr, x)
    def invert_interval(self, interval):
        (a, b) = (interval.left, interval.right)
        (lo, ro) = (not interval.left_open, interval.right_open)
        xvals_a = solve_poly_inequality(self.symexpr, a, lo, extended=False)
        xvals_b = solve_poly_inequality(self.symexpr, b, ro, extended=False)
        xvals = xvals_a.complement(xvals_b)
        return self.subexpr.invert(xvals)
    def __eq__(self, x):
        return isinstance(x, Poly) \
            and self.subexpr == x.subexpr \
            and self.coeffs == x.coeffs
    def __neg__(self):
        return Poly(self.subexpr, [-c for c in self.coeffs])
    def __repr__(self):
        return 'Poly(coeffs=%s, %s)' \
            % (repr(self.coeffs), repr(self.subexpr))

# Some useful constructors.
def ExpNat(subexpr):
    return Exp(subexpr, sympy.exp(1))
def LogNat(subexpr):
    return Log(subexpr, sympy.exp(1))
def Sqrt(subexpr):
    return Radical(subexpr, 2)
def Pow(subexpr, n):
    assert 0 <= n
    coeffs = [0]*n + [1]
    return Poly(subexpr, coeffs)

# ==============================================================================
# Custom event language.

class Event(object):
    def __and__(self, event):
        assert isinstance(event, Event)
        return EventAnd([self, event])
    def __or__(self, event):
        assert isinstance(event, Event)
        return EventOr([self, event])
    def __invert__(self):
        return EventNot(self)

class EventInterval(Event):
    def __init__(self, expr, interval):
        self.interval = interval
        self.expr = make_subexpr(expr)
    def solve(self):
        return self.expr.invert(self.interval)
    def __eq__(self, event):
        return (self.interval == event.interval) and (self.expr == event.expr)
    def __repr__(self):
        return 'EventInterval(%s, %s)' \
            % (repr(self.expr), repr(self.interval))

class EventOr(Event):
    def __init__(self, events):
        self.events = events
    def solve(self):
        intervals = [event.solve() for event in self.events]
        return sympy.Union(*intervals)
    def __eq__(self, event):
        return self.events == event.events
    def __repr__(self):
        return 'EventOr(%s)' % (repr(self.events,))

class EventAnd(Event):
    def __init__(self, events):
        self.events = events
    def solve(self):
        intervals = [event.solve() for event in self.events]
        return sympy.Intersection(*intervals)
    def __eq__(self, event):
        return self.events == event.events
    def __repr__(self):
        return 'EventAnd(%s)' % (repr(self.events,))

class EventNot(Event):
    def __init__(self, event):
        self.event = event
    def solve(self):
        # TODO Should complement range not Reals.
        interval = self.event.solve()
        return interval.complement(Reals)
    def __invert__(self):
        return self.event
    def __eq__(self, event):
        return event == self.event
    def __repr__(self):
        return 'EventNot(%s)' % (repr(self.event,))

# ==============================================================================
# SymPy solver.

def solver(expr):
    symbols = get_symbols(expr)
    if len(symbols) != 1:
        raise ValueError('Expression "%s" needs exactly one symbol.' % (expr,))

    if isinstance(expr, Relational):
        result = sympy.solveset(expr, domain=Reals)
    elif isinstance(expr, sympy.Or):
        subexprs = expr.args
        intervals = [solver(e) for e in subexprs]
        result = sympy.Union(*intervals)
    elif isinstance(expr, sympy.And):
        subexprs = expr.args
        intervals = [solver(e) for e in subexprs]
        result = sympy.Intersection(*intervals)
    elif isinstance(expr, sympy.Not):
        (notexpr,) = expr.args
        interval = solver(notexpr)
        result = interval.complement(Reals)
    else:
        raise ValueError('Expression "%s" has unknown type.' % (expr,))

    if isinstance(result, sympy.ConditionSet):
        raise ValueError('Expression "%s" is not invertible.' % (expr,))

    return result
