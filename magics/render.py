# Copyright 2020 MIT Probabilistic Computing Project.
# See LICENSE.txt

import os
import tempfile
import time

from math import exp

import graphviz
import networkx as nx

from spn.spn import NominalLeaf
from spn.spn import ProductSPN
from spn.spn import RealLeaf
from spn.spn import SumSPN

def render_networkx_graph(spn):
    if isinstance(spn, NominalLeaf):
        G = nx.DiGraph()
        root = str(time.time())
        G.add_node(root, label='%s\n%s' % (spn.symbol.token, 'Nominal'))
        return G
    if isinstance(spn, RealLeaf):
        G = nx.DiGraph()
        root = str(time.time())
        G.add_node(root, label='%s\n%s' % (spn.symbol.token, spn.dist.dist.name))
        return G
    if isinstance(spn, SumSPN):
        G = nx.DiGraph()
        root = str(time.time())
        G.add_node(root, label='+')
        # Add nodes and edges from children.
        G_children = [render_networkx_graph(c) for c in spn.children]
        for i, x in enumerate(G_children):
            G.add_nodes_from(x.nodes.data())
            G.add_edges_from(x.edges.data())
            subroot = list(nx.topological_sort(x))[0]
            G.add_edge(root, subroot, label='%1.3f' % (exp(spn.weights[i]),))
        return G
    if isinstance(spn, ProductSPN):
        G = nx.DiGraph()
        root = str(time.time())
        G.add_node(root, label='*')
        # Add nodes and edges from children.
        G_children = [render_networkx_graph(c) for c in spn.children]
        for x in G_children:
            G.add_nodes_from(x.nodes.data())
            G.add_edges_from(x.edges.data())
            subroot = list(nx.topological_sort(x))[0]
            G.add_edge(root, subroot)
        return G
    assert False, 'Unknown SPN type: %s' % (spn,)

def render_graphviz(spn, filename=None, ext=None, show=None):
    fname = filename
    if filename is None:
        f = tempfile.NamedTemporaryFile(delete=False)
        fname = f.name
    G = render_networkx_graph(spn)
    ext = ext or 'png'
    assert ext in ['png', 'pdf'], 'Extension must be .pdf or .png'
    fname_dot = '%s.dot' % (fname,)
    # nx.set_edge_attributes(G, 'serif', 'fontname')
    # nx.set_node_attributes(G, 'serif', 'fontname')
    nx.nx_agraph.write_dot(G, fname_dot)
    source = graphviz.Source.from_file(fname_dot, format=ext)
    source.render(filename=fname, view=show)
    os.unlink(fname)
    return source