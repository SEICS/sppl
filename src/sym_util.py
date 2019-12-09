# Copyright 2019 MIT Probabilistic Computing Project.
# See LICENSE.txt

import sympy

from .contains import Contains
from .contains import NotContains

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
    assert all(len(s) == len(intersection) for s in sets)

def simplify_nominal_event(event, support):
    if isinstance(event, sympy.Eq):
        a, b = event.args
        value = b if isinstance(a, sympy.Symbol) else a
        return support.intersection({value})
    elif isinstance(event, Contains):
        a, b = event.args
        assert isinstance(a, sympy.Symbol)
        return support.intersection(b)
    elif isinstance(event, NotContains):
        a, b = event.args
        assert isinstance(a, sympy.Symbol)
        return support.difference(b)
    elif isinstance(event, sympy.And):
        sets = [simplify_nominal_event(e, support) for e in event.args]
        return get_intersection(sets)
    elif isinstance(event, sympy.Or):
        sets = [simplify_nominal_event(e, support) for e in event.args]
        return get_union(sets)
    else:
        raise ValueError('Event "%s" does not apply to nominal variable'
            % (event,))