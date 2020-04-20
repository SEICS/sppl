# Copyright 2020 MIT Probabilistic Computing Project.
# See LICENSE.txt

""""Compiler from SPML to Python 3."""

import ast
import copy
import io
import os

from types import SimpleNamespace
from collections import namedtuple
from collections import OrderedDict
from contextlib import contextmanager

from astunparse import unparse

get_indentation = lambda i: ' ' * i

@contextmanager
def maybe_sequence_block(visitor, value, first=None):
    # Enter
    active = len(value) > 1 or first
    if active:
        idt = get_indentation(visitor.indentation)
        visitor.stream.write('%sSequence(' % (idt,))
        visitor.stream.write('\n')
        visitor.indentation += 4
    # Yield
    yield None
    # Exit
    if active:
        visitor.indentation -= 4
        idt = get_indentation(visitor.indentation)
        visitor.stream.write('%s)' % (idt,))
        if not first:
            visitor.stream.write(',')
            visitor.stream.write('\n')

class SPML_Visitor(ast.NodeVisitor):
    def __init__(self, stream=None):
        self.stream = stream or io.StringIO()
        self.indentation = 0
        self.arrays = OrderedDict()
        self.variables = OrderedDict()
        self.distributions = OrderedDict()
        self.context = ['global']
        self.first = True

    def generic_visit(self, node):
        """Called if no explicit visitor function exists for a node."""
        for field, value in ast.iter_fields(node):
            if isinstance(value, list):
                with maybe_sequence_block(self, value, self.first):
                    self.first = False
                    for item in value:
                        if isinstance(item, ast.AST):
                            self.visit(item)
            elif isinstance(value, ast.AST):
                self.visit(value)

    def visit_Assign(self, node):
        str_node = unparse(node)

        # Analyze node.target.
        assert len(node.targets) == 1
        target = node.targets[0]
        # Target is a location.
        if isinstance(target, ast.Name):
            # Cannot assign variables in for.
            assert 'for' not in self.context, \
            'non-array variable in for %s' % (str_node,)
            # Cannot assign fresh variables in else.
            if 'elif' in self.context:
                assert target.id in self.variables, \
                'unknown variable %s' % (str_node,)
            # Cannot reassign existing variables.
            else:
                assert target.id not in self.variables, \
                'overwriting variable %s' % (str_node,)
                self.variables[target.id] = None
        # Target is a subscript.
        elif isinstance(target, ast.Subscript):
            assert target.value.id in self.arrays,\
            'unknown array %s' % (str_node,)
        else:
            assert False,\
            'unknown sample target %s' % (str_node,)

        # Analyze node.value.
        if isinstance(node.value, ast.Call) and node.value.func.id == 'array':
            assert self.context == ['global']           # must be global
            assert isinstance(target, ast.Name)         # must not be susbcript
            assert node.targets[0] not in self.arrays   # must be fresh
            assert len(node.value.args) == 1            # must be array(n)
            assert isinstance(node.value.args[0], ast.Num) # must be num n
            assert isinstance(node.value.args[0].n, int)   # must be int n
            assert node.value.args[0].n > 0                # must be pos n
            self.arrays[target.id] = node.value.args[0].n
        # Assigning to distribution or transform.
        elif isinstance(node.value, (ast.Call, ast.Dict, ast.expr)):
            value_prime = SPML_Transformer().visit(node.value)
            src_value = unparse(value_prime).replace(os.linesep, '')
            src_targets = unparse(node.targets).replace(os.linesep, '')
            idt = get_indentation(self.indentation)
            self.stream.write('%s%s >> %s,' % (idt, src_targets, src_value))
            self.stream.write('\n')
            if isinstance(node.value, ast.Call):
                self.distributions[node.value.func.id] = None
        else:
            assert False,\
            'unknown sample value %s' % (str_node,)

    def visit_For(self, node):
        assert isinstance(node.target, ast.Name), unparse(node.target)
        assert node.iter.func.id == 'range', unparse(node.iter)
        assert len(node.iter.args) in [1, 2], unparse(node.iter)
        if len(node.iter.args) == 1:
            n0 = 0
            n1 = unparse(node.iter.args[0]).strip()
        if len(node.iter.args) == 2:
            n0 = unparse(node.iter.args[0]).strip()
            n1 = unparse(node.iter.args[1]).strip()
        # Open Repeat.
        self.context.append('for')
        idt = get_indentation(self.indentation)
        idx = unparse(node.target).strip()
        self.stream.write('%sRepeat(%s, %s, lambda %s:' % (idt, n0, n1, idx))
        self.stream.write('\n')
        # Write body.
        self.indentation += 4
        self.generic_visit(ast.Module(node.body))
        self.indentation -= 4
        # Close repeat.
        idt = get_indentation(self.indentation)
        self.stream.write('%s),' % (idt,))
        self.stream.write('\n')
        self.context.pop()

    def visit_If(self, node):
        unrolled = unroll_if(node)
        assert 2 <= len(unrolled), 'if needs elif/else: %s' % (unparse(node))
        idt = get_indentation(self.indentation)
        # Open Cond.
        self.context.append('if')
        self.stream.write('%sCond(' % (idt,))
        self.stream.write('\n')
        # Write branches.
        self.indentation += 4
        for i, (test, body) in enumerate(unrolled):
            # Write the test.
            test_prime = SPML_Transformer().visit(test)
            src_test = unparse(test_prime).strip()
            idt = get_indentation(self.indentation)
            self.stream.write('%s%s,' % (idt, src_test))
            self.stream.write('\n')
            # Write the body.
            if i > 0:
                self.context.append('elif')
            self.indentation += 4
            self.generic_visit(ast.Module(body))
            self.indentation -= 4
            if i > 0:
                self.context.pop()
        self.indentation -= 4
        # Close Cond.
        idt = get_indentation(self.indentation)
        self.stream.write('%s),' % (idt,))
        self.stream.write('\n')
        self.context.pop()

def unroll_if(node, current=None):
    current = [] if current is None else current
    assert isinstance(node, ast.If)
    test = node.test
    body = node.body
    current.append((test, body))
    # Base case, terminating at elif.
    if not node.orelse:
        return current
    # Base case, next statement is not an If.
    if not (isinstance(node.orelse[0], ast.If) and len(node.orelse)== 1):
        current.append((ast.parse('True'), node.orelse))
        return current
    # Recursive case, next statement is elif
    return unroll_if(node.orelse[0], current)

class SPML_Transformer(ast.NodeTransformer):
    def visit_Compare(self, node):
        # TODO: Implement or/and.
        if len(node.ops) > 1:
            return node
        if isinstance(node.ops[0], ast.In):
            return ast.BinOp(
                left=node.left,
                op=ast.LShift(),
                right=node.comparators[0])
        if isinstance(node.ops[0], ast.Eq):
            return ast.BinOp(
                left=node.left,
                op=ast.LShift(),
                right=ast.Set(node.comparators))
        if isinstance(node.ops[0], ast.NotIn):
            node_copy = copy.deepcopy(node)
            node_copy.ops[0] = ast.In()
            return ast.UnaryOp(
                op=ast.Invert(),
                operand=self.visit_Compare(node_copy))
        if isinstance(node.ops[0], ast.NotEq):
            node_copy = copy.deepcopy(node)
            node_copy.ops[0] = ast.Eq()
            return ast.UnaryOp(
                op=ast.Invert(),
                operand=self.visit_Compare(node_copy))
        return node

prog = namedtuple('prog', ('imports', 'variables', 'arrays', 'command'))
class SPML_Compiler():
    def __init__(self, source, modelname='model'):
        self.source = source
        self.modelname = modelname
        self.prog = prog(
            imports=io.StringIO(),
            variables=io.StringIO(),
            arrays=io.StringIO(),
            command=io.StringIO())
        self.compile()
    def preprocess(self):
        source_prime = self.source.replace('~=', '=')
        return source_prime
    def compile(self):
        # Parse and visit.
        source_prime = self.preprocess()
        tree = ast.parse(source_prime)
        visitor = SPML_Visitor()
        visitor.visit(tree)
        # Write the imports.
        self.prog.imports.write("# IMPORT STATEMENTS")
        self.prog.imports.write('\n')
        for c in ['Cond', 'Repeat', 'Sequence', 'Variable', 'VariableArray']:
            self.prog.imports.write('from spn.interpreter import %s' % (c,))
            self.prog.imports.write('\n')
        self.prog.imports.write('from spn.distributions import *')
        # Write the variables.
        if visitor.variables:
            self.prog.variables.write('# VARIABLE DECLARATIONS')
            self.prog.variables.write('\n')
            for v in visitor.variables:
                self.prog.variables.write('%s = Variable(\'%s\')' % (v, v,))
                self.prog.variables.write('\n')
        # Write the arrays.
        if visitor.arrays:
            self.prog.arrays.write('# ARRAY DECLARATIONS')
            self.prog.arrays.write('\n')
            for v, n in visitor.arrays.items():
                self.prog.arrays.write('%s = VariableArray(\'%s\', %d)' % (v, v, n,))
                self.prog.arrays.write('\n')
        # Write the command.
        self.prog.command.write('# MODEL DEFINITION')
        self.prog.command.write('\n')
        command = visitor.stream.getvalue()
        self.prog.command.write('command = %s' % (command,))
        self.prog.command.write('\n')
        # Write the interpret step.
        self.prog.command.write('%s = command.interpret()' % (self.modelname,))
    def render_module(self):
        """Render the source code as a stand alone Python module."""
        program = io.StringIO()
        for stream in self.prog:
            v = stream.getvalue()
            if v:
                program.write(stream.getvalue())
                program.write('\n')
        return program.getvalue()
    def execute_module(self):
        """Execute the source code in a fresh module."""
        code = self.render_module()
        namespace = {}
        exec(code, namespace)
        return SimpleNamespace(**namespace)