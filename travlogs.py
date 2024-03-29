#!/usr/bin/env python3
# Copyright (c) 2019 Leedehai. All rights reserved.
# Licensed under the MIT License.
#
# File: travlogs.py
# ---------------------------
# This package converts the compilation log, into a graph, and handles
# queries on the graph.
# This script cannot handle huge graphs, because all data is loaded in
# memory at once; there's no such demand in my projects.
# For details, see the README.md file.
#
# NOTE on serializing/deserializing: do not use the 'pickle' package
#      because 1) it makes the cache file unreadable (bad to debug)
#      and 2) it results in a larger cache file than the current implementation

import os, sys
import json
import hashlib
import argparse
from collections import deque

# written under the build output directory
BUILD_GRAPH_CACHE_BASENAME = "graph.cache"

# this script content's hash string, representing its own version
with open(__file__, 'rb') as script_f: # read as bytes
    script_h = hashlib.sha1()
    script_h.update(script_f.read())
SCRIPT_HASH = script_h.hexdigest()[:5]

def debug(s):
    print(s)

def parse_repr_line_(line, sigil, sep):
    return line[len(sigil):].split(sep)

class NameIdBidirectionalMap: # ever-growing, value immutable
    REPR_SIGIL, REPR_SEP = "id", "^"
    def __init__(self, name2id = None, id2name = None):
        # NOTE do not assign default value {} to args 'name2id' and 'id2name'
        #      see: https://stackoverflow.com/questions/1132941/least-astonishment-and-the-mutable-default-argument
        self.name2id = name2id if name2id != None else {} # key: node name (str), val: id (int)
        self.id2name = id2name if id2name != None else {} # key: id (int), val: node name (str)
        self.counter = len(name2id) if name2id != None else 0
    # serialize: do not use 'pickle'
    def __repr__(self):
        return '\n'.join([
            "{sigil} {node_id} {sep} {node_name}".format(
                sigil = self.REPR_SIGIL, sep = self.REPR_SEP,
                node_id = node_id, node_name = self.id2name[node_id]
            )
            for node_id in sorted(self.id2name)
        ])
    # deserialize: do not use 'pickle'
    @classmethod
    def from_repr(cls, repr_str):
        name2id, id2name = {}, {}
        filtered_line_generator = (
            l for l in repr_str.split('\n')
            if len(l.strip()) and l.startswith(cls.REPR_SIGIL)
        )
        for line in filtered_line_generator:
            node_id_str, node_name_str = parse_repr_line_(
                line = line, sigil = cls.REPR_SIGIL, sep = cls.REPR_SEP)
            name2id[node_name_str.strip()] = int(node_id_str)
            id2name[int(node_id_str)] = node_name_str.strip()
        return NameIdBidirectionalMap(name2id, id2name)
    def size():
        return len(self.name2id)
    # return id, but insertion only takes place if not existing
    def insert(self, name):
        if name in self.name2id:
            return self.name2id[name]
        self.name2id[name] = node_id = self.counter
        self.id2name[node_id] = name
        self.counter += 1
        return node_id
    # return id if found, None otherwise
    def get_id_from_name(self, name):
        return self.name2id.get(name, None)
    # return name if found, None otherwise
    def get_name_from_id(self, nid): # avoid "id": is a keyword
        return self.id2name.get(nid, None)

class DAGNodeRec:
    def __init__(self, prevs = None, nexts = None):
        # NOTE do not assign default value set() to args 'prevs' and 'nexts'
        #      see: https://stackoverflow.com/questions/1132941/least-astonishment-and-the-mutable-default-argument
        # store both parents and children for faster searching
        self.prevs = prevs if prevs != None else set() # id of parent nodes
        self.nexts = nexts if nexts != None else set() # id of child nodes

class DAG: # directional acyclic graph, ever growing
    REPR_SIGIL, REPR_SEP = "io", "^"
    def __init__(self, other=None):
        # NOTE do not assign default value {} to arg 'other'
        #      see: https://stackoverflow.com/questions/1132941/least-astonishment-and-the-mutable-default-argument
        self.nodes = other if other != None else {} # key: node id, val: DAGNodeRec
        self.num_edge = 0
    # serialize: do not use 'pickle'
    def __repr__(self):
        return '\n'.join([
            "{sigil} {node_id} {sep} {prevs} {sep} {nexts}".format(
                sigil = self.REPR_SIGIL, sep = self.REPR_SEP,
                node_id = node_id,
                prevs = repr(self.nodes[node_id].prevs),
                nexts = repr(self.nodes[node_id].nexts)
            )
            for node_id in self.nodes
        ])
    # deserialize: do not use 'pickle'
    @classmethod
    def from_repr(cls, repr_str):
        dag = {}
        filtered_line_generator = (
            l for l in repr_str.split('\n')
            if len(l.strip()) and l.startswith(cls.REPR_SIGIL)
        )
        for line in filtered_line_generator:
            node_id_str, prevs_str, nexts_str = parse_repr_line_(
                line = line, sigil = cls.REPR_SIGIL, sep = cls.REPR_SEP)
            dag[int(node_id_str)] = DAGNodeRec(eval(prevs_str), eval(nexts_str))
        return DAG(dag)
    def node_num(self):
        return len(self.nodes)
    def edge_num(self):
        return self.num_edge
    def add_edge(self, from_id, to_id):
        assert(type(from_id) == int and type(to_id) == int)
        assert(from_id != to_id)
        self.num_edge += 1
        self.nodes.setdefault(from_id, DAGNodeRec()).nexts.add(to_id)
        self.nodes.setdefault(to_id, DAGNodeRec()).prevs.add(from_id)
    def get_nexts_from_id(self, nid):
        node_rec = self.nodes.get(nid, None)
        if node_rec == None:
            return None
        return node_rec.nexts # set of node ids
    def get_prevs_from_id(self, nid):
        node_rec = self.nodes.get(nid, None)
        if node_rec == None:
            return None
        return node_rec.prevs # set of node ids

def construct_build_graph_(data, record_filter=None):
    name_id_bimap, graph = NameIdBidirectionalMap(), DAG()
    for i, record in enumerate(data): # for each compilation object (dict)
        if record_filter != None and record_filter(record) == False:
            continue
        # node names
        in_nodes_arr, out_node = record.get("inputs", None), record.get("output", None)
        if in_nodes_arr == None or out_node == None:
            raise ValueError(
                "missing key 'inputs' or 'output' in compilation object #%d" % (i + 1))
        in_nodes = set(in_nodes_arr)
        for header in record.get("headers", []):
            in_nodes.add(header)
        # node id
        in_node_id_generator = (name_id_bimap.insert(name) for name in in_nodes)
        out_node_id = name_id_bimap.insert(out_node)
        # add edge: do not use map() or list comprehension for side effects
        for in_node_id in in_node_id_generator:
            graph.add_edge(in_node_id, out_node_id)
    return graph, name_id_bimap

# read from graph cache or construct graph anew
# record_filter: a predicate - ignore a compilation object if the result is False
def load_build_graph_impl_(
    data, data_hash, graph_cache_filename=None, record_filter=None):
    if graph_cache_filename and os.path.isfile(graph_cache_filename):
        with open(graph_cache_filename, 'r') as f:
            hash_str = f.readline().strip("#").strip()
            if hash_str == "%s:%s" % (SCRIPT_HASH, data_hash): # use the cache
                data_serialized = f.read() # read the remainder
                return (
                    DAG.from_repr(data_serialized), # graph
                    NameIdBidirectionalMap.from_repr(data_serialized) # name_id_bimap
                )
        # reaching here: graph cache is outdated, bust the cache
        os.remove(graph_cache_filename)
    # build graph from data
    graph, name_id_bimap = construct_build_graph_(data, record_filter)
    # serialize the data, write cahce
    if graph_cache_filename:
        with open(graph_cache_filename, 'w') as f:
            f.write("# %s:%s\n" % (SCRIPT_HASH, data_hash))
            f.write("\n# N: %d E: %d\n\n" % (graph.node_num(), graph.edge_num()))
            f.write("# id prevs nexts\n" + repr(graph) + "\n\n")
            f.write("# id name\n" + repr(name_id_bimap) + "\n")
    return graph, name_id_bimap

INTERESTED_EDGE_TYPES = { "cc", "cxx", "link", "solink", "alink" }
def load_build_graph_(root_dir, log_basename, cache_aware=True):
    logfile_path = os.path.join(root_dir, log_basename)
    with open(logfile_path, 'rb') as f: # read as bytes
        log_data = f.read()
    h = hashlib.sha256()
    h.update(log_data)
    if cache_aware:
        cache_name = os.path.join(root_dir, BUILD_GRAPH_CACHE_BASENAME)
    else:
        cache_name = None
    return load_build_graph_impl_(
        data = json.loads(log_data.decode()), data_hash = h.hexdigest(),
        graph_cache_filename = cache_name,
        record_filter = lambda e: e["rule"] in INTERESTED_EDGE_TYPES
    )

def bfs_find_ends_(
    input_ids, graph, name_id_bimap, node_name_filter,
    get_gotos, exclude_order_only=True):
    def filter_goto_(node_id):
        node_name = name_id_bimap.get_name_from_id(node_id)
        if exclude_order_only and node_name.startswith("||"):
            return False
        return node_name_filter(node_name) if node_name_filter != None else True
    q = deque(input_ids)
    visited, result = set(), set()
    while len(q) != 0:
        nid = q.popleft()
        visited.add(nid)
        arrived_at_sink = True
        for goto_id in (gid for gid in get_gotos(graph, nid) if filter_goto_(gid)):
            arrived_at_sink = False
            if goto_id not in visited:
                q.append(goto_id)
        if arrived_at_sink:
            result.add(nid)
    return result # set of id

def bfs_find_paths_(
    input_ids, graph, name_id_bimap, node_name_filter,
    get_gotos, exclude_order_only=True):
    def filter_goto_(node_id):
        node_name = name_id_bimap.get_name_from_id(node_id)
        if exclude_order_only and node_name.startswith("||"):
            return False
        return node_name_filter(node_name) if node_name_filter != None else True
    q = deque([ nid ] for nid in input_ids)
    result = []
    while len(q) != 0:
        path = q.popleft()
        nid = path[-1] # path's current end
        arrived_at_sink = True
        for goto_id in (gid for gid in get_gotos(graph, nid) if filter_goto_(gid)):
            arrived_at_sink = False
            q.append(path + [ goto_id ])
        if arrived_at_sink:
            result.append(path)
    return result # list of list of id

# export
class NodeNamesNotInGraphError(ValueError):
    def __init__(self, not_found_names):
        self.not_found = not_found_names
    def __str__(self):
        return "node names not found in graph: " + ', '.join(self.not_found)

# traverse DAG
def traverse_(
    graph, name_id_bimap, starts, traverse_func, get_goto_func, node_name_filter=None):
    input_ids = [ name_id_bimap.get_id_from_name(start) for start in starts ]
    not_found_names = [
        starts[i] for i, input_id in enumerate(input_ids) if input_id == None
    ]
    if len(not_found_names):
        raise NodeNamesNotInGraphError(not_found_names)
    intermediate_res = traverse_func(
        input_ids, graph, name_id_bimap, node_name_filter, get_goto_func)
    return intermediate_res

# export
# Given a list of target names, find the source names
# NOTE "sources" are nodes which do not have parents (source nodes),
#       but "targets" has no restriction
# NOTE if a node's name doesn't pass node_name_filter, it is ignored as if pruned
# @param root_dir: str - the directory where the log is in and
#                        the base path of path strings in logs
# @param log_basename: str - compilation log relative to root_dir
# @param targets: list of str - names in the log
# @param node_name_filter: predicate of node name - node is ignored if the result is False
# @param cache_aware: boolean - if True, use/write cache
# @return list of str - source names in the log
# @throws NodeNamesNotInGraph
def find_sources_from_targets(
    root_dir, log_basename, targets, node_name_filter=None, cache_aware=True):
    graph, name_id_bimap = load_build_graph_(root_dir, log_basename, cache_aware)
    source_nodes = traverse_(
        graph, name_id_bimap, targets,
        bfs_find_ends_, DAG.get_prevs_from_id,
        node_name_filter
    )
    return [ name_id_bimap.get_name_from_id(sid) for sid in source_nodes ]

# export
# similar to above, but return paths along the way, not just the arrived nodes
def find_paths_from_targets(
    root_dir, log_basename, targets, node_name_filter=None, cache_aware=True):
    graph, name_id_bimap = load_build_graph_(root_dir, log_basename, cache_aware)
    paths_to_sources = traverse_(
        graph, name_id_bimap, targets,
        bfs_find_paths_, DAG.get_prevs_from_id,
        node_name_filter
    )
    return [
        [ name_id_bimap.get_name_from_id(nid) for nid in path ]
        for path in paths_to_sources
    ]

# export
# Given a list of source names, find the target names
# NOTE "targets" are nodes which do not have children (sink nodes),
#       but "sources" has no restriction
# NOTE if a node's name doesn't pass node_name_filter, it is ignored as if pruned
# @param root_dir: str - the directory where the log is in and
#                        the base path of path strings in logs
# @param log_basename: str - compilation log relative to root_dir
# @param sources: list of str - names in the log
# @param node_name_filter: predicate of node name - node is ignored if the result is False
# @param cache_aware: boolean - if True, use/write cache
# @return list of str - target names in the log
def find_targets_from_sources(
    root_dir, log_basename, sources, node_name_filter=None, cache_aware=True):
    graph, name_id_bimap = load_build_graph_(root_dir, log_basename, cache_aware)
    target_nodes = traverse_(
        graph, name_id_bimap, sources,
        bfs_find_ends_, DAG.get_nexts_from_id,
        node_name_filter
    )
    return [ name_id_bimap.get_name_from_id(tid) for tid in target_nodes ]

# export
# similar to above, but return paths along the way, not just the arrived nodes
def find_paths_from_sources(
    root_dir, log_basename, sources, node_name_filter=None, cache_aware=True):
    graph, name_id_bimap = load_build_graph_(root_dir, log_basename, cache_aware)
    paths_to_targets = traverse_(
        graph, name_id_bimap, sources,
        bfs_find_paths_, DAG.get_nexts_from_id,
        node_name_filter
    )
    return [
        [ name_id_bimap.get_name_from_id(nid) for nid in path ]
        for path in paths_to_targets
    ]

# not a comprehensive test
def sanity_check():
    cache_filename = os.path.join(".", BUILD_GRAPH_CACHE_BASENAME)
    if os.path.isfile(cache_filename):
        os.remove(os.path.join(".", BUILD_GRAPH_CACHE_BASENAME))

    print("\x1b[33mfind_sources_from_targets(): case 1\x1b[0m")
    from_targets = [
        "utests/base/c-style-fstring-test",
        "utests/base/llvm-style-rtti-test"
    ]
    found_sources = find_sources_from_targets(
        ".", "build_log.json",
        from_targets,
        lambda name: "googletest" not in name
    )
    print("targets:\n\t" + "\n\t".join(from_targets)
        + "\n=> sources:\n" + '\n'.join(sorted(found_sources)))

    print("\n\x1b[33mfind_sources_from_targets(): case 2\x1b[0m")
    from_targets = [
        "../../unit-tests/ADT/c-style-fstring-test.cc",
    ]
    found_sources = find_sources_from_targets(
        ".", "build_log.json",
        from_targets,
        lambda name: "googletest" not in name
    )
    print("targets:\n\t" + "\n\t".join(from_targets)
        + "\n=> sources:\n" + '\n'.join(sorted(found_sources)))

    print("\n\x1b[33mfind_targets_from_sources(): case 1\x1b[0m")
    from_sources = [
        "../../src/ADT/string-ref.cc",
        "../../unit-tests/ADT/c-style-fstring-test.cc"
    ]
    found_targets = find_targets_from_sources(
        ".", "build_log.json",
        from_sources,
    )
    print("sources:\n\t" + "\n\t".join(from_sources)
        + "\n=> targets:\n" + '\n'.join(sorted(found_targets)))

    print("\n\x1b[33mfind_targets_from_sources(): case 2\x1b[0m")
    from_sources = [
        "../../include/ADT/string-ref.h",
    ]
    found_targets = find_targets_from_sources(
        ".", "build_log.json",
        from_sources,
    )
    print("sources:\n\t" + "\n\t".join(from_sources)
        + "\n=> targets:\n" + '\n'.join(sorted(found_targets)))

    print("\n\x1b[33mfind_paths_from_targets():\x1b[0m")
    from_targets = [
        "utests/base/c-style-fstring-test",
    ]
    paths_to_sources = [
        "\n  > ".join(path)
        for path in find_paths_from_targets(
            ".", "build_log.json",
            from_targets,
            lambda name: "googletest" not in name
        )
    ]
    print("targets:\n\t" + "\n\t".join(from_targets)
        + "\n=> paths:\n" + '\n'.join(sorted(paths_to_sources)))

    print("\n\x1b[33mfind_paths_from_sources():\x1b[0m")
    from_sources = [
        "../../include/ADT/string-ref.h",
    ]
    paths_to_targets = [
        "\n  > ".join(path)
        for path in find_paths_from_sources(
            ".", "build_log.json",
            from_sources
        )
    ]
    print("sources:\n\t" + "\n\t".join(from_sources)
        + "\n=> paths:\n" + '\n'.join(sorted(paths_to_targets)))

# as commandline utility
USAGE = """travlogs.py [-h] [--check]
                   OUT_PATH [--db]
                   [-t|--src-from-targets T [T ...]]
                   [-s|--targets-from-src S [S ...]]
                   [-T|--paths-from-targets T [T ...]]
                   [-S|--paths-from-src S [S ...]]"""
def cli_main():
    argparser = argparse.ArgumentParser(
        description="Traverse a Clang(-like) compilation database for a C/C++ project.",
        epilog="For usage as a library, see README.md",
        usage=USAGE)
    argparser.add_argument("outdir", metavar="OUT_PATH", nargs='?', default=".",
                           help="build output directory, defualt: .")
    argparser.add_argument("--check", action="store_true",
                           help="(dev) run a sanity test of this utility")
    argparser.add_argument("--db", metavar="FILE", default="build_log.json",
                           help="compilation database file path relative to OUT_PATH, default: build_log.json")
    argparser.add_argument("-t", "--src-from-targets", metavar="T", nargs='+', type=str, default=[],
                           help="find sources from targets")
    argparser.add_argument("-s", "--targets-from-src", metavar="S", nargs='+', type=str, default=[],
                           help="find targets from sources")
    argparser.add_argument("-T", "--paths-from-targets", metavar="T", nargs='+', type=str, default=[],
                           help="find paths from targets")
    argparser.add_argument("-S", "--paths-from-src", metavar="S", nargs='+', type=str, default=[],
                           help="find paths from sources")
    args = argparser.parse_args()

    action_count = sum([
        args.check == True,
        len(args.src_from_targets) != 0,
        len(args.targets_from_src) != 0,
        len(args.paths_from_targets) != 0,
        len(args.paths_from_src) != 0,
    ])
    if not os.path.isdir(args.outdir):
        sys.exit("[Error] directory not found: %s" % args.log)
    db_norm_path = os.path.normpath(os.path.join(args.outdir, args.db))
    if not os.path.isfile(db_norm_path):
        sys.exit("[Error] file not found: %s" % db_norm_path)
    if action_count != 1:
        sys.exit("[Error] require exactly 1 action, but %d given." % action_count)

    NODE_NAME_PASSTHROUGH = lambda name : True
    rebase_filename_to_outdir = lambda p: os.path.relpath(p, args.outdir)
    rebase_filename_to_curdir = lambda p: os.path.normpath(os.path.join(args.outdir, p))
    if args.check:
        return sanity_check()
    if len(args.src_from_targets):
        try:
            found_sources = find_sources_from_targets(
                args.outdir, args.db,
                [ rebase_filename_to_outdir(p) for p in args.src_from_targets ],
                node_name_filter = NODE_NAME_PASSTHROUGH,
                cache_aware = False
            )
        except NodeNamesNotInGraphError as e:
            print(e)
            return 1
        print('\n'.join([ rebase_filename_to_curdir(p) for p in found_sources ]))
        return 0
    if len(args.targets_from_src):
        try:
            found_targets = find_targets_from_sources(
                args.outdir, args.db,
                [ rebase_filename_to_outdir(p) for p in args.targets_from_src ],
                node_name_filter = NODE_NAME_PASSTHROUGH,
                cache_aware = False
            )
        except NodeNamesNotInGraphError as e:
            print(e)
            return 1
        print('\n'.join([ rebase_filename_to_curdir(p) for p in found_targets ]))
        return 0
    if len(args.paths_from_targets):
        try:
            paths_to_sources = [
                "\n  > ".join([ rebase_filename_to_curdir(node) for node in path ])
                for path in find_paths_from_targets(
                    args.outdir, args.db,
                    [ rebase_filename_to_outdir(p) for p in args.paths_from_targets ],
                    node_name_filter = NODE_NAME_PASSTHROUGH,
                    cache_aware = False
                )
            ]
        except NodeNamesNotInGraphError as e:
            print(e)
            return 1
        print('\n'.join(sorted(paths_to_sources)))
        return 0
    if len(args.paths_from_src):
        try:
            paths_to_targets = [
                "\n  > ".join([ rebase_filename_to_curdir(node) for node in path ])
                for path in find_paths_from_sources(
                    args.outdir, args.db,
                    [ rebase_filename_to_outdir(p) for p in args.paths_from_src ],
                    node_name_filter = NODE_NAME_PASSTHROUGH,
                    cache_aware = False
                )
            ]
        except NodeNamesNotInGraphError as e:
            print(e)
            return 1
        print('\n'.join(sorted(paths_to_targets)))
        return 0

if __name__ == "__main__":
    sys.exit(cli_main())
