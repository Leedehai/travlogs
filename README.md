# travlogs

Traverse a Clang(-like) compilation database for a C/C++ project.

This package converts the JSON log into a graph, then handles some queries on the graph (*yeah! This is **the** CS*).

> Each record in the complication log essentially consists of edges into one node (which files, through what operation, produce what). Graph building converts these records into a set of nodes. The graph is directional acyclic (DAG).

The graph is also cached to save runtime. As long as the [script itself](./travlogs.py) and the compilation log do not mutate, the cached graph will be used to handle queries.

The compilation log has the same format of [Clang's compilation database](https://clang.llvm.org/docs/JSONCompilationDatabase.html) with these augmentations:
- (mandatory field) replace the `file` field, which only stores the first input file for each compilation command, with a `inputs` field, which stores all input files,
- (mendatory field): add a `rule` field to document the category of the compilation command: `cc`, `cxx`, `solink`, `alink`, `link`, `stamp`, etc (see [GN's tool types](https://gn.googlesource.com/gn/+/master/docs/reference.md#tool-types)),
- (optional field) add a `headers` field to store all headers reported by the compiler,
- other additional fields, optional.

## Prerequisites

- Python 2.7 or Python 3.5+
- Linux, macOS, or Windows

## API

This package has two APIs, look at the [source code](./travlogs.py) for usage
- `find_sources_from_targets`: given targets, find which header/source files are involved
- `find_targets_from_sources`: given header/source files, find which targets are affected

## Testing

TODO

## Examples

TODO: backburner-ed

## Why don't you give more docs?
I might, but this is a package merely for my own projects. I intend to use it for my build automation scripts.

###### EOF