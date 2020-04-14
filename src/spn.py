# Copyright 2020 MIT Probabilistic Computing Project.
# See LICENSE.txt

from collections import ChainMap
from collections import Counter
from collections import namedtuple
from fractions import Fraction
from functools import reduce
from inspect import getfullargspec
from itertools import chain
from math import exp
from math import isfinite
from math import log

from sympy import Complement
from sympy import Intersection
from sympy import Interval
from sympy import Range
from sympy import Union

from .dnf import dnf_factor
from .dnf import dnf_normalize
from .dnf import dnf_to_disjoint_union

from .math_util import allclose
from .math_util import flip
from .math_util import isinf_neg
from .math_util import logdiffexp
from .math_util import logflip
from .math_util import lognorm
from .math_util import logsumexp

from .sym_util import ContainersFinite
from .sym_util import EmptySet
from .sym_util import NominalSet
from .sym_util import NominalValue
from .sym_util import are_disjoint
from .sym_util import are_identical
from .sym_util import get_union
from .sym_util import partition_list_blocks
from .sym_util import powerset
from .sym_util import sympify_number

from .transforms import Event
from .transforms import EventBasic
from .transforms import EventCompound
from .transforms import EventOr
from .transforms import Identity

inf = float('inf')
Memo = namedtuple('Memo', ['logprob', 'condition'])

# ==============================================================================
# SPN (base class).

class SPN(object):
    def __init__(self):
        raise NotImplementedError()
    def sample(self, N, rng):
        raise NotImplementedError()
    def sample_subset(self, symbols, N, rng):
        raise NotImplementedError()
    def sample_func(self, func, N, rng):
        raise NotImplementedError()
    def logprob(self, event, memo=None):
        raise NotImplementedError()
    def prob(self, event):
        lp = self.logprob(event)
        return exp(lp)
    def condition(self, event, memo=None):
        raise NotImplementedError()
    def mutual_information(self, A, B):
        # p11 = self.logprob(A & B)
        # p10 = self.logprob(A & ~B)
        # p01 = self.logprob(~A & B)
        # p00 = self.logprob(~A & ~B)
        lpA1 = self.logprob(A)
        lpB1 = self.logprob(B)
        lpA0 = logdiffexp(0, lpA1)
        lpB0 = logdiffexp(0, lpB1)
        lp00 = self.logprob(~A & ~B)
        lp01 = self.logprob(~A & B)
        lp10 = self.logprob(A & ~B)
        lp11 = self.logprob(A & B)
        m00 = exp(lp00) * (lp00 - (lpA0 + lpB0)) if not isinf_neg(lp00) else 0
        m01 = exp(lp01) * (lp01 - (lpA0 + lpB1)) if not isinf_neg(lp01) else 0
        m10 = exp(lp10) * (lp10 - (lpA1 + lpB0)) if not isinf_neg(lp10) else 0
        m11 = exp(lp11) * (lp11 - (lpA1 + lpB1)) if not isinf_neg(lp11) else 0
        return m00 + m01 + m10 + m11

    def __rmul__number(self, x):
        x_val = sympify_number(x)
        if not 0 < x < 1:
            raise ValueError('Weight %s must be in (0, 1)' % (str(x),))
        return PartialSumSPN([self], [x_val])
    def __rmul__(self, x):
        # Try to multiply x as a number.
        try:
            return self.__rmul__number(x)
        except TypeError:
            pass
        # Failed.
        return NotImplemented
    def __mul__(self, x):
        return x * self

    def __and__spn(self, x):
        if isinstance(x, PartialSumSPN):
            raise TypeError()
        if not isinstance(x, SPN):
            raise TypeError()
        return ProductSPN([self, x])
    def __and__(self, x):
        # Try to & x as a SPN.
        try:
            return self.__and__spn(x)
        except TypeError:
            pass
        # Failed.
        return NotImplemented

    def get_memo_key(self, e):
        if isinstance(e, (list, tuple)):
            x = id(self)
            y = tuple(tuple(conjunction.items()) for conjunction in e)
            return (x, y)
        if isinstance(e, Event):
            x = id(self)
            y = hash(e)
            return (x, y)
        assert False, 'Unknown event type: %s' % (e,)

# ==============================================================================
# Branch SPN.

class BranchSPN(SPN):
    symbols = None
    children = None
    def get_symbols(self):
        return self.symbols
    def logprob(self, event, memo=None):
        if memo is None:
            memo = Memo({}, {})
        # Check memo table.
        key = self.get_memo_key(event)
        if key in memo.logprob:
            return memo.logprob[key]
        # Compute and memoize.
        event_dnf = dnf_normalize(event)
        event_dnf_pruned = self.prune_events(event_dnf, memo)
        if event_dnf_pruned is None:
            return -inf
        event_factor = dnf_factor(event_dnf_pruned)
        memo.logprob[key] = self.logprob_factored(event_factor, memo)
        return memo.logprob[key]
    def condition(self, event, memo=None):
        if memo is None:
            memo = Memo({}, {})
        # Check memo table.
        key = self.get_memo_key(event)
        if key in memo.condition:
            return memo.condition[key]
        # Compute and memoize.
        event_dnf = dnf_normalize(event)
        event_dnf_pruned = self.prune_events(event_dnf, memo)
        if event_dnf_pruned is None:
            raise ValueError('Zero probability event: %s' % (event,))
        event_disjoint = dnf_to_disjoint_union(event_dnf_pruned)
        event_factor = dnf_factor(event_disjoint)
        memo.condition[key] = self.condition_factored(event_factor, memo)
        return memo.condition[key]
    def logprob_factored(self, event_factor, memo):
        raise NotImplementedError()
    def condition_factored(self, event_factor, memo):
        raise NotImplementedError()
    def prune_events(self, event_dnf, memo):
        if not isinstance(event_dnf, EventOr):
            return event_dnf
        conjunctions = [dnf_factor(e) for e in event_dnf.subexprs]
        logps = [self.logprob_factored(c, memo) for c in conjunctions]
        indexes = [i for i, lp in enumerate(logps) if not isinf_neg(lp)]
        if not indexes:
            return None
        return EventOr([event_dnf.subexprs[i] for i in indexes])

# ==============================================================================
# Sum SPN.

class SumSPN(BranchSPN):
    """Weighted mixture of SPNs."""

    def __init__(self, children, weights):
        self.children = tuple(chain.from_iterable([
            spn.children
                if isinstance(spn, type(self)) else [spn]
            for spn in children
        ]))
        self.weights = tuple(chain.from_iterable([
            [weight + w for w in spn.weights]
                if isinstance(spn, type(self)) else [weight]
            for spn, weight in zip(children, weights)
        ]))
        # Derived attributes.
        self.indexes = tuple(range(len(self.weights)))
        assert allclose(float(logsumexp(weights)),  0)

        symbols = [spn.get_symbols() for spn in self.children]
        if not are_identical(symbols):
            raise ValueError('Mixture must have identical symbols.')
        self.symbols = self.children[0].get_symbols()

    def sample(self, N, rng):
        f_sample = lambda i, n: self.children[i].sample(n, rng)
        return self.sample_many(f_sample, N, rng)

    def sample_subset(self, symbols, N, rng):
        f_sample = lambda i, n : \
            self.children[i].sample_subset(symbols, n, rng)
        return self.sample_many(f_sample, N, rng)

    def sample_func(self, func, N, rng):
        f_sample = lambda i, n : self.children[i].sample_func(func, n, rng)
        return self.sample_many(f_sample, N, rng)

    def sample_many(self, func, N, rng):
        selections = logflip(self.weights, self.indexes, N, rng)
        counts = Counter(selections)
        samples = [func(i, counts[i]) for i in counts]
        rng.shuffle(samples)
        return list(chain.from_iterable(samples))

    def logprob_factored(self, event_factor, memo):
        # Check memo table.
        key = self.get_memo_key(event_factor)
        if key in memo.logprob:
            return memo.logprob[key]
        # Compute and memoize.
        logps = [spn.logprob_factored(event_factor, memo) for spn in self.children]
        logp = logsumexp([p + w for (p, w) in zip(logps, self.weights)])
        memo.logprob[key] = logp
        return logp

    def condition_factored(self, event_factor, memo):
        # Check memo table.
        key = self.get_memo_key(event_factor)
        if key in memo.condition:
            return memo.condition[key]
        # Compute and memoize.
        logps_condt = [spn.logprob_factored(event_factor, memo) for spn in self.children]
        indexes = [i for i, lp in enumerate(logps_condt) if not isinf_neg(lp)]
        logps_joint = [logps_condt[i] + self.weights[i] for i in indexes]
        children = [self.children[i].condition_factored(event_factor, memo) for i in indexes]
        weights = lognorm(logps_joint)
        spn = SumSPN(children, weights) if len(indexes) > 1 else children[0]
        memo.condition[key] = spn
        return spn

    def __eq__(self, x):
        return isinstance(x, type(self)) \
            and self.children == x.children \
            and self.weights == x.weights
    def __hash__(self):
        x = (self.__class__, self.children, self.weights)
        return hash(x)

class ExposedSumSPN(SumSPN):
    def __init__(self, children, spn_weights):
        """Weighted mixture of SPNs with exposed internal choice."""
        assert isinstance(spn_weights, NominalDistribution)
        weights = [
            spn_weights.logprob(spn_weights.symbol << {n})
            for n in spn_weights.support
        ]
        children = [
            ProductSPN([
                NominalDistribution(spn_weights.symbol, {str(n): 1}),
                children[n]
            ]) for n in spn_weights.support
        ]
        super().__init__(children, weights)

class PartialSumSPN(SPN):
    """Weighted mixture of SPNs that do not yet sum to unity."""
    def __init__(self, children, weights):
        self.children = children
        self.weights = weights
        self.indexes = list(range(len(self.weights)))
        assert sum(weights) <  1

        symbols = [spn.get_symbols() for spn in children]
        if not are_identical(symbols):
            raise ValueError('Mixture must have identical symbols.')
        self.symbols = self.children[0].get_symbols()

    def __and__(self, x):
        raise TypeError('Weights do not sum to one.')
    def __rand__(self, x):
        raise TypeError('Weights do not sum to one.')
    def __mul__(self, x):
        raise TypeError('Cannot multiply PartialSumSPN by constant.')
    def __rmul__(self, x):
        raise TypeError('Cannot multiply PartialSumSPN by constant.')

    def __or__partialsum(self, x):
        if not isinstance(x, PartialSumSPN):
            raise TypeError()
        weights = self.weights + x.weights
        cumsum = float(sum(weights))
        if allclose(cumsum, 1):
            weights = [log(w) for w in weights]
            children = self.children + x.children
            return SumSPN(children, weights)
        if cumsum < 1:
            children = self.children + x.children
            return PartialSumSPN(children, weights)
        raise ValueError('Weights sum to more than one.')
    def __or__(self, x):
        # Try to | x as a PartialSumSPN
        try:
            return self.__or__partialsum(x)
        except TypeError:
            pass
        # Failed.
        return NotImplemented

def spn_simplify_sum(spn):
    if isinstance(spn.children[0], LeafSPN):
        return spn_simplify_sum_leaf(spn)
    if isinstance(spn.children[0], ProductSPN):
        return spn_simplify_sum_product(spn)
    assert False, 'Invalid children of SumSPN: %s' % (spn.children,)

def spn_simplify_sum_leaf(spn):
    assert all(isinstance(c, LeafSPN) for c in spn.children)
    partition = partition_list_blocks(spn.children)
    if len(partition) == len(spn.children):
        return spn
    if len(partition) == 1:
        return spn.children[0]
    children = [spn.children[block[0]] for block in partition]
    weights = [logsumexp([spn.weights[i] for i in block]) for block in partition]
    return SumSPN(children, weights)

def spn_simplify_sum_product(spn):
    assert all(isinstance(c, ProductSPN) for c in spn.children)
    children_list = [c.children for c in spn.children]
    children_simplified, weight_simplified = reduce(
        lambda state, cw: spn_simplify_sum_product_helper(state, cw[0], cw[1]),
        zip(children_list[1:], spn.weights[1:]),
        (children_list[0], spn.weights[0]),
    )
    assert allclose(logsumexp(weight_simplified), 0)
    return spn_list_to_product(children_simplified)

def spn_simplify_sum_product_helper(state, children_b, w_b):
    (children_a, w_a) = state
    weights_sum = lognorm([w_a, w_b])
    weight_overall = logsumexp([w_a, w_b])
    overlap = [(i, j)
        for j, cb in enumerate(children_b)
        for i, ca in enumerate(children_a)
        if ca == cb
    ]
    if len(overlap) == 0:
        product_a = spn_list_to_product(children_a)
        product_b = spn_list_to_product(children_b)
        children_simplified = [SumSPN([product_a, product_b], weights_sum)]
    elif len(overlap) == len(children_a):
        children_simplified = children_a
    else:
        dup_b = set([p[1] for p in overlap])
        dup_a = set([p[0] for p in overlap])
        uniq_children_b = [c for j, c in enumerate(children_b) if j not in dup_b]
        uniq_children_a = [c for i, c in enumerate(children_a) if i not in dup_a]
        dup_children = [c for i, c in enumerate(children_a) if i in dup_a]
        product_a = spn_list_to_product(uniq_children_a)
        product_b = spn_list_to_product(uniq_children_b)
        sum_a_b = SumSPN([product_a, product_b], weights_sum)
        children_simplified = [sum_a_b] + dup_children
    return (children_simplified, weight_overall)

# ==============================================================================
# Product base class.

class ProductSPN(BranchSPN):
    """List of independent SPNs."""

    def __init__(self, children):
        self.children = tuple(chain.from_iterable([
            (spn.children if isinstance(spn, type(self)) else [spn])
            for spn in children
        ]))
        # Derived attributes.
        symbols = [spn.get_symbols() for spn in self.children]
        if not are_disjoint(symbols):
            raise ValueError('Product must have disjoint symbols')
        self.lookup = {s:i for i, syms in enumerate(symbols) for s in syms}
        self.symbols = frozenset(get_union(symbols))

    def sample(self, N, rng):
        samples = [spn.sample(N, rng) for spn in self.children]
        return merge_samples(samples)

    def sample_subset(self, symbols, N, rng):
        # Partition symbols by lookup.
        index_to_symbols = {}
        for symbol in symbols:
            key = self.lookup[symbol]
            if key not in index_to_symbols:
                index_to_symbols[key] = []
            index_to_symbols[key].append(symbol)
        # Obtain the samples.
        samples = [
            self.children[i].sample_subset(symbols_i, N, rng)
            for i, symbols_i in index_to_symbols.items()
        ]
        # Merge the samples.
        return merge_samples(samples)

    def sample_func(self, func, N, rng):
        symbols = func_symbols(self, func)
        samples = self.sample_subset(symbols, N, rng)
        return func_evaluate(self, func, samples)

    def logprob_factored(self, event_factor, memo):
        key = self.get_memo_key(event_factor)
        # Check memo table.
        if key in memo.logprob:
            return memo.logprob[key]
        # Compute and memoize.
        # Adopting Inclusion--Exclusion principle for DNF event:
        # https://cp-algorithms.com/combinatorics/inclusion-exclusion.html#toc-tgt-4
        indexes = range(len(event_factor))
        subsets = list(powerset(indexes, start=1))
        # Compute probabilities of all the conjunctions.
        (logps_pos, logps_neg) = ([], [])
        for J in subsets:
            # Compute probability of this conjunction.
            logprob = self.logprob_conjunction(event_factor, J, memo)
            # Add probability to either positive or negative sums.
            prefactor = (-1)**(len(J) - 1)
            x = logps_pos if prefactor > 0 else logps_neg
            x.append(logprob)
        # Aggregate positive term.
        logp_pos = logsumexp(logps_pos)
        if isinf_neg(logp_pos) or not logps_neg:
            return logp_pos
        # Aggregate negative terms and return the difference.
        logp_neg = logsumexp(logps_neg) if logps_neg else -inf
        logp = logdiffexp(logp_pos, logp_neg)
        memo.logprob[key] = logp
        return logp

    def condition_factored(self, event_factor, memo):
        # Check memo table.
        key = self.get_memo_key(event_factor)
        if key in memo.condition:
            return memo.condition[key]
        # Compute and memoize.
        logps = [self.logprob_conjunction([c], [0], memo) for c in event_factor]
        assert allclose(logsumexp(logps), self.logprob_factored(event_factor, memo))
        indexes = [i for (i, lp) in enumerate(logps) if not isinf_neg(lp)]
        if not indexes:
            raise ValueError('Conditioning event "%s" has probability zero'
                % (str(event_factor),))
        weights = lognorm([logps[i] for i in indexes])
        childrens = [self.condition_clause(event_factor[i], memo) for i in indexes]
        products = [ProductSPN(children) for children in childrens]
        if len(indexes) == 1:
            spn = products[0]
        else:
            spn_sum = SumSPN(products, weights)
            spn = spn_simplify_sum(spn_sum)
        memo.condition[key] = spn
        return memo.condition[key]

    def logprob_conjunction(self, event_factor, J, memo):
        # Return probability of conjunction of |J| conjunctions.
        keys = set([self.lookup[s] for j in J for s in event_factor[j]])
        return sum([
            self.logprob_conjunction_key(event_factor, J, key, memo)
            for key in keys
        ])

    def logprob_conjunction_key(self, event_factor, J, key, memo):
        # Return probability of conjunction of |J| conjunction, for given key.
        clause = {}
        for j in J:
            for symbol, event in event_factor[j].items():
                if self.lookup[symbol] == key:
                    if symbol not in clause:
                        clause[symbol] = event
                    else:
                        clause[symbol] &= event
        if not clause:
            return -inf
        return self.children[key].logprob_factored((clause,), memo)

    def condition_clause(self, clause, memo):
        # Return children conditioned on a clause (one conjunction).
        children = []
        for spn in self.children:
            spn_condition = spn
            symbols = spn.get_symbols().intersection(clause)
            if symbols:
                spn_clause = ({symbol: clause[symbol] for symbol in symbols},)
                spn_condition = spn.condition_factored(spn_clause, memo)
            children.append(spn_condition)
        return children

    def __eq__(self, x):
        return isinstance(x, type(self)) \
            and self.children == x.children
    def __hash__(self):
        x = (self.__class__, self.children)
        return hash(x)

def spn_list_to_product(children):
    return children[0] if len(children) == 1 else ProductSPN(children)

# ==============================================================================
# Basic Distribution base class.

class LeafSPN(SPN):
    symbol = None
    def get_symbols(self):
        return frozenset({self.symbol})
    def sample(self, N, rng):
        raise NotImplementedError()
    def sample_subset(self, symbols, N, rng):
        return self.sample(N, rng) if self.symbol in symbols else None
    def sample_func(self, func, N, rng):
        samples = self.sample(N, rng)
        return func_evaluate(self, func, samples)
    def logpdf(self, x):
        raise NotImplementedError()
    def logprob(self, event, memo=None):
        if memo is None:
            return self.logprob__(event)
        key = self.get_memo_key(({self.symbol: event},))
        if key not in memo.logprob:
            memo.logprob[key] = self.logprob__(event)
        return memo.logprob[key]
    def condition(self, event, memo=None):
        if memo is None:
            return self.condition__(event)
        key = self.get_memo_key(({self.symbol: event},))
        if key not in memo.condition:
            memo.condition[key] = self.condition__(event)
        return memo.condition[key]
    def logprob_factored(self, event_factor, memo):
        # Check memo table.
        key = self.get_memo_key(event_factor)
        if key in memo.logprob:
            return memo.logprob[key]
        # Compute and memoize.
        event = event_unfactor(self.symbol, event_factor)
        lp = self.logprob(event)
        memo.logprob[key] = lp
        return lp
    def condition_factored(self, event_factor, memo):
        # Check memo table.
        key = self.get_memo_key(event_factor)
        if key in memo.condition:
            return memo.condition[key]
        # Compute and memoize.
        event = event_unfactor(self.symbol, event_factor)
        spn = self.condition(event)
        memo.condition[key] = spn
        return spn
    def logprob__(self, event):
        raise NotImplementedError()
    def condition__(self, event):
        raise NotImplementedError()

# ==============================================================================
# RealDistribution base class.

class RealDistribution(LeafSPN):
    """Base class for distribution with a cumulative distribution function."""

    def __init__(self, symbol, dist, support, conditioned=None):
        assert isinstance(symbol, Identity)
        self.symbol = symbol
        self.dist = dist
        self.support = support
        self.conditioned = conditioned
        # Derived attributes.
        self.xl = float(support.inf)
        self.xu = float(support.sup)
        # Attributes to be populated by child classes.
        self.Fl = None
        self.Fu = None
        self.logFl = None
        self.logFu = None
        self.logZ = None

    def sample(self, N, rng):
        if self.conditioned:
            # XXX Method not guaranteed to be numerically stable, see e.g,.
            # https://www.iro.umontreal.ca/~lecuyer/myftp/papers/truncated-normal-book-chapter.pdf
            # Also consider using CDF for left tail and SF for right tail.
            # Example: X ~ N(0,1) can sample X | (X < -10) but not X | (X > 10).
            u = rng.uniform(size=N)
            u_interval = u*self.Fl + (1-u) * self.Fu
            xs = self.dist.ppf(u_interval)
        else:
            # Simulation by vanilla inversion sampling.
            xs = self.dist.rvs(size=N, random_state=rng)
        # Wrap result in a dictionary.
        return [{self.symbol : x} for x in xs]

    def logcdf(self, x):
        if not self.conditioned:
            return self.dist.logcdf(x)
        if self.xu < x:
            return 0
        elif x < self.xl:
            return -inf
        p = logdiffexp(self.dist.logcdf(x), self.logFl)
        return p - self.logZ

    def logprob__(self, event):
        interval = event.solve()
        values = get_intersection_safe(self.support, interval)
        return self.logprob_values__(values)

    def logprob_values__(self, values):
        if values is EmptySet:
            return -inf
        if isinstance(values, ContainersFinite):
            return self.logprob_finite__(values)
        if isinstance(values, Range):
            return self.logprob_range__(values)
        if isinstance(values, Interval):
            return self.logprob_interval__(values)
        if isinstance(values, Union):
            logps = [self.logprob_values__(v) for v in values.args]
            return logsumexp(logps)
        assert False, 'Unknown set type: %s' % (values,)

    def logprob_finite__(self, values):
        raise NotImplementedError()
    def logprob_range__(self, values):
        raise NotImplementedError()
    def logprob_interval__(self, values):
        raise NotImplementedError()

    def condition__(self, event):
        interval = event.solve()
        values = get_intersection_safe(self.support, interval)
        weight = self.logprob_values__(values)

        # Probability zero event.
        if isinf_neg(weight):
            raise ValueError('Conditioning event "%s" has probability zero'
                % (str(event)))

        # Condition on support.
        if values == self.support:
            return self

        # Condition on one set.
        if isinstance(values, (ContainersFinite, Range, Interval)):
            return (type(self))(self.symbol, self.dist, values, True)

        # Condition on union of sets.
        if isinstance(values, Union):
            weights_unorm = [self.logprob_values__(v) for v in values.args]
            indexes = [i for i, w in enumerate(weights_unorm) if not isinf_neg(w)]
            if not indexes:
                raise ValueError('Conditioning event "%s" has probability zero'
                    % (str(event),))
            # TODO: Normalize the weights with greater precision, e.g.,
            # https://stats.stackexchange.com/questions/66616/converting-normalizing-very-small-likelihood-values-to-probability
            weights = lognorm([weights_unorm[i] for i in indexes])
            children = [
                (type(self))(self.symbol, self.dist, values.args[i], True)
                for i in indexes
            ]
            return SumSPN(children, weights) if 1 < len(indexes) else children[0]

        # Unknown set.
        assert False, 'Unknown set type: %s' % (values,)

    def __hash__(self):
        d = (self.dist.dist.name, self.dist.args, tuple(self.dist.kwds.items()))
        x = (self.__class__, self.symbol, d, self.support, self.conditioned)
        return hash(x)
    def __eq__(self, x):
        return isinstance(x, type(self)) \
            and self.symbol == x.symbol \
            and self.dist.dist.name == x.dist.dist.name \
            and self.dist.args == x.dist.args \
            and self.dist.kwds == x.dist.kwds \
            and self.support == x.support \
            and self.conditioned == x.conditioned

# ==============================================================================
# Continuous RealDistribution.

class ContinuousReal(RealDistribution):
    """Non-atomic distribution with a cumulative distribution function."""
    def __init__(self, symbol, dist, support, conditioned=None):
        super().__init__(symbol, dist, support, conditioned)
        if conditioned:
            self.Fl = self.dist.cdf(self.xl)
            self.Fu = self.dist.cdf(self.xu)
            self.logFl = self.dist.logcdf(self.xl)
            self.logFu = self.dist.logcdf(self.xu)
            self.logZ = logdiffexp(self.logFu, self.logFl)
        else:
            self.logFl = -inf
            self.logFu = 0
            self.Fl = 0
            self.Fu = 1
            self.logZ = 1

    def logpdf(self, x):
        if not self.conditioned:
            return self.dist.logpdf(x)
        if x not in self.support:
            return -inf
        return self.dist.logpdf(x) - self.logZ

    def logprob_finite__(self, values):
        return -inf

    def logprob_range__(self, values):
        return -inf

    def logprob_interval__(self, values):
        xl = float(values.start)
        xu = float(values.end)
        logFl = self.logcdf(xl)
        logFu = self.logcdf(xu)
        return logdiffexp(logFu, logFl)

# ==============================================================================
# Discrete RealDistribution.

class DiscreteReal(RealDistribution):
    """Atomic distribution with a cumulative distribution function."""

    def __init__(self, symbol, dist, support, conditioned=None):
        super().__init__(symbol, dist, support, conditioned)
        if conditioned:
            self.Fl = self.dist.cdf(self.xl - 1)
            self.Fu = self.dist.cdf(self.xu)
            self.logFl = self.dist.logcdf(self.xl - 1)
            self.logFu = self.dist.logcdf(self.xu)
            self.logZ = logdiffexp(self.logFu, self.logFl)
        else:
            self.logFl = -inf
            self.logFu = 0
            self.Fl = 0
            self.Fu = 1
            self.logZ = 1

    def logpdf(self, x):
        if not self.conditioned:
            return self.dist.logpmf(x)
        if (x < self.xl) or (self.xu < x):
            return -inf
        return self.dist.logpmf(x) - self.logZ

    def logprob_finite__(self, values):
        logps = [self.logpdf(float(x)) for x in values]
        return logsumexp(logps)
    def logprob_range__(self, values):
        if values.stop <= values.start:
            return -inf
        if values.step == 1:
            xl = float(values.inf)
            xu = float(values.sup)
            logFl = self.logcdf(xl - 1)
            logFu = self.logcdf(xu)
            return logdiffexp(logFu, logFl)
        if isfinite(values.start) and isfinite(values.stop):
            xs = list(values)
            return self.logprob_finite__(xs)
        raise ValueError('Cannot enumerate infinite set: %s' % (values,))
    def logprob_interval__(self, values):
        assert False, 'Atomic distribution cannot intersect an interval!'

# ==============================================================================
# Nominal distribution.

class NominalDistribution(LeafSPN):
    """Atomic distribution, no cumulative distribution function."""

    def __init__(self, symbol, dist):
        assert isinstance(symbol, Identity)
        assert all(isinstance(x, str) for x in dist)
        self.symbol = symbol
        self.dist = {NominalValue(x): Fraction(w) for x, w in dist.items()}
        # Derived attributes.
        self.support = NominalSet(*dist.keys())
        self.outcomes = list(self.dist.keys())
        self.weights = list(self.dist.values())
        assert allclose(float(sum(self.weights)),  1)

    def logpdf(self, x):
        if x not in self.dist:
            return -inf
        w = self.dist[x]
        return log(w[0]) - log(w[1])

    def sample(self, N, rng):
        # TODO: Replace with FLDR.
        xs = flip(self.weights, self.outcomes, N, rng)
        return [{self.symbol: x} for x in xs]

    def logprob__(self, event):
        # TODO: Consider using 1 - Pr[Event] for negation to avoid
        # iterating over domain.
        # if is_event_transformed(event):
        #     raise ValueError('Cannot apply transform to Nominal variable: %s'
        #         % (str(event),))
        solution = event.solve()
        values = Intersection(self.support, solution)
        p_event = sum(self.dist[x] for x in values)
        return log(p_event) if p_event != 0 else -inf

    def condition__(self, event):
        # if is_event_transformed(event):
        #     raise ValueError('Cannot apply transform to Nominal variable: %s'
        #         % (str(event),))
        solution = event.solve()
        values = Intersection(self.support, solution)
        p_event = sum([self.dist[x] for x in values])
        if p_event == 0:
            raise ValueError('Conditioning event "%s" has probability zero' %
                (str(event),))
        if p_event == 1:
            return self
        dist = {
            str(x) : (self.dist[x] / p_event) if x in values else 0
            for x in self.support
        }
        return NominalDistribution(self.symbol, dist)

    def __hash__(self):
        x = (self.__class__, self.symbol, tuple(self.dist.items()))
        return hash(x)
    def __eq__(self, x):
        return isinstance(x, type(self)) \
            and self.symbol == x.symbol \
            and self.dist == x.dist

# ==============================================================================
# Utilities.

def spn_cache_duplicate_subtrees(spn, memo):
    if isinstance(spn, LeafSPN):
        if spn not in memo:
            memo[spn] = spn
        return memo[spn]
    if isinstance(spn, BranchSPN):
        if spn not in memo:
            memo[spn] = spn
            spn.children = list(spn.children)
            for i, c in enumerate(spn.children):
                spn.children[i] = spn_cache_duplicate_subtrees(c, memo)
            spn.children = tuple(spn.children)
        return memo[spn]
    assert False, '%s is not an spn' % (spn,)

def event_unfactor(symbol, dnf_factor):
    if len(dnf_factor) == 1:
        return dnf_factor[0][symbol]
    return EventOr([conjunction[symbol] for conjunction in dnf_factor])

def get_intersection_safe(a, b):
    assert not isinstance(a, Union)
    if isinstance(b, Union):
        intersections = [get_intersection_safe(a, x) for x in b.args]
        return Union(*intersections)
    intersection = Intersection(a, b)
    if isinstance(intersection, Complement):
        (A, B) = intersection.args
        return A - Intersection(A, B)
    return intersection

def is_event_transformed(event):
    if isinstance(event, EventBasic):
        return not isinstance(event.subexpr, Identity)
    if isinstance(event, EventCompound):
        return any(map(is_event_transformed, event.subexprs))
    assert False, 'Unknown event: %s' % (event,)

def func_evaluate(spn, func, samples):
    args = func_symbols(spn, func)
    sample_kwargs = [{X.token: s[X] for X in args} for s in samples]
    return [func(**kwargs) for kwargs in sample_kwargs]

def func_symbols(spn, func):
    symbols = spn.get_symbols()
    args = [Identity(a) for a in getfullargspec(func).args]
    unknown = [a for a in args if a not in symbols]
    if unknown:
        raise ValueError('Unknown function arguments "%s" (allowed %s)'
            % (unknown, symbols))
    return args

def merge_samples(samples):
    # input [[{X:1, Y:2}, {X:0, Y:1}], [{Z:0}, {Z:1}]] (N=2)
    # output [{X:1, Y:2, Z:0}, {X:0, Y:1, Z:1}]
    return [dict(ChainMap(*sample_list)) for sample_list in zip(*samples)]
