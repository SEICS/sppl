# Copyright 2020 MIT Probabilistic Computing Project.
# See LICENSE.txt

from math import log

import pytest

from numpy import linspace

from spn.distributions import bernoulli
from spn.distributions import beta
from spn.distributions import randint
from spn.compilers.ast_to_spn import IfElse
from spn.compilers.ast_to_spn import Condition
from spn.compilers.ast_to_spn import Sample
from spn.compilers.ast_to_spn import Sequence
from spn.compilers.ast_to_spn import Id
from spn.math_util import allclose

Y = Id('Y')
X = Id('X')

def test_condition_nominal():
    command = Sequence(
        Sample(Y, {'a':.1, 'b':.1, 'c':.8}),
        Condition(Y << {'a', 'b'}))
    model = command.interpret()
    assert allclose(model.prob(Y << {'a'}), .5)
    assert allclose(model.prob(Y << {'b'}), .5)
    assert allclose(model.prob(Y << {'c'}), 0)

def test_condition_real_discrete_range():
    command = Sequence(
        Sample(Y, randint(low=0, high=4)),
        Condition(Y << {0, 1}))
    model = command.interpret()
    assert allclose(model.prob(Y << {0}), .5)
    assert allclose(model.prob(Y << {1}), .5)

@pytest.mark.xfail(strict=True, reason='https://github.com/probcomp/sum-product-dsl/issues/77')
def test_condition_real_discrete_no_range():
    command = Sequence(
        Sample(Y, randint(low=0, high=4)),
        Condition(Y << {0, 2}))
    model = command.interpret()
    assert allclose(model.prob(Y << {0}), .5)
    assert allclose(model.prob(Y << {1}), .5)

def test_condition_real_continuous():
    command = Sequence(
        Sample(Y, beta(a=1, b=1)),
        Condition(Y < .5))
    model = command.interpret()
    assert allclose(model.prob(Y < .5), 1)
    assert allclose(model.prob(Y > .5), 0)

def test_condition_prob_zero():
    with pytest.raises(Exception):
        Sequence(
            Sample(Y, {'a':.1, 'b':.1, 'c':.8}),
            Condition(Y << {'d'})).interpret()
    with pytest.raises(Exception):
        Sequence(
            Sample(Y, beta(a=1, b=1)),
            Condition(Y > 1)).interpret()