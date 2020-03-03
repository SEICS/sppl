# Copyright 2020 MIT Probabilistic Computing Project.
# See LICENSE.txt

from itertools import chain
from itertools import combinations
from math import isinf

import sympy

from sympy.core import Atom
from sympy.core.relational import Relational

UniversalSet = sympy.UniversalSet

EmptySet = sympy.S.EmptySet
Infinities = sympy.FiniteSet(-sympy.oo, sympy.oo)

Integers = sympy.S.Integers
IntegersPos = sympy.S.Naturals
IntegersNeg = sympy.Range(-sympy.oo, 0, 1)

IntegersPos0 = sympy.S.Naturals0
IntegersNeg0 = sympy.Range(-sympy.oo, 1, 1)

Reals = sympy.S.Reals
RealsPos = sympy.Interval(0, sympy.oo)
RealsNeg = sympy.Interval(-sympy.oo, 0)

ExtReals = Reals + Infinities
ExtRealsPos = RealsPos + sympy.FiniteSet(sympy.oo)
ExtRealsNeg = RealsNeg + sympy.FiniteSet(-sympy.oo)

UnitInterval = sympy.Interval(0, 1)

ContainersFinite = (
    sympy.FiniteSet, sympy.EmptySet, sympy.Tuple,
    frozenset, set, list, tuple)

def get_symbols(expr):
    atoms = expr.atoms()
    return [a for a in atoms if isinstance(a, sympy.Symbol)]

def get_union(sets):
    return sets[0].union(*sets[1:])

def get_intersection(sets):
    return sets[0].intersection(*sets[1:])

def are_disjoint(sets):
    union = get_union(sets)
    return len(union) == sum(len(s) for s in sets)

def are_identical(sets):
    intersection = get_intersection(sets)
    return all(len(s) == len(intersection) for s in sets)

def powerset(values, start=0):
    s = list(values)
    subsets = [combinations(s, k) for k in range(start, len(s) + 1)]
    return chain.from_iterable(subsets)

def sympify_number(x):
    msg = 'Expected a numeric term, not %s' % (x,)
    try:
        sym = sympy.sympify(x)
        if not sym.is_number:
            raise TypeError(msg)
        return sym
    except (sympy.SympifyError, AttributeError, TypeError):
        raise TypeError(msg)

def sympify_nominal(x):
    if isinstance(x, NominalValue):
        return x
    if isinstance(x, str):
        return NominalValue(x)
    raise TypeError('Expected a nominal term, not %s' % (x,))

def sym_log(x):
    assert 0 <= x
    if x == 0:
        return -float('inf')
    if isinf(x):
        return float('inf')
    return sympy.log(x)

def is_number(x):
    if isinstance(x, str):
        return False
    try:
        sympify_number(x)
        return True
    except TypeError:
        return False

def is_nominal(x):
    return isinstance(x, (str, NominalValue))

def complement_nominal_set(values, universe=None):
    if universe is None:
        universe = UniversalSet
    if values is EmptySet:
        return universe
    if values is universe:
        return EmptySet
    if isinstance(values, sympy.FiniteSet):
        return sympy.Complement(universe, values)
    if isinstance(values, sympy.Complement):
        values_not = values.args[1]
        assert is_nominal_set(values_not)
        return values_not
    assert False, 'Invalid values to complement symbolic: %s' % (str(values),)

def sympy_solver(expr):
    # Sympy is buggy and slow.  Use Transforms.
    symbols = get_symbols(expr)
    if len(symbols) != 1:
        raise ValueError('Expression "%s" needs exactly one symbol.' % (expr,))

    if isinstance(expr, Relational):
        result = sympy.solveset(expr, domain=Reals)
    elif isinstance(expr, sympy.Or):
        subexprs = expr.args
        intervals = [sympy_solver(e) for e in subexprs]
        result = sympy.Union(*intervals)
    elif isinstance(expr, sympy.And):
        subexprs = expr.args
        intervals = [sympy_solver(e) for e in subexprs]
        result = sympy.Intersection(*intervals)
    elif isinstance(expr, sympy.Not):
        (notexpr,) = expr.args
        interval = sympy_solver(notexpr)
        result = interval.complement(Reals)
    else:
        raise ValueError('Expression "%s" has unknown type.' % (expr,))

    if isinstance(result, sympy.ConditionSet):
        raise ValueError('Expression "%s" is not invertible.' % (expr,))

    return result

class NominalValue(Atom):
    # Prevent sympy from converting a FinteSet of strings into
    # a FiniteSet of symbols, which corrupts set operations
    # combining symbolic and numeric values.
    def __eq__(self, x):
        if isinstance(x, NominalValue):
            return x.args == self.args
        if isinstance(x, str):
            return (x,) == self.args
        return False
    def __hash__(self):
        return hash(self.args[0])
    def __str__(self):
        return self.args[0]
    def __repr__(self):
        return self.args[0]
    def _eval_Eq(self, x):
        if isinstance(x, NominalValue) and x.args == self.args:
            return sympy.true
        return sympy.false

def NominalSet(*values):
    return sympy.FiniteSet(*[sympify_nominal(v) for v in values])

def is_nominal_set(x):
    if not isinstance(x, sympy.FiniteSet):
        return False
    return all(isinstance(y, NominalValue) for y in x)

def is_numeric_set(x):
    if not isinstance(x, sympy.FiniteSet):
        return False
    return all(y.is_number for y in x)
