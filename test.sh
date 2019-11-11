#!/usr/bin/env bash

has_error=0

rm -f ./graph.cache

# without cache
./travlogs.py > log1
diff log1 out.gold # exit is non-zero if files differ
if [ $? -ne 0 ]; then
    has_error=1
    echo "error found: run without cache"
fi

# cache exists, run again
./travlogs.py > log2
diff log2 out.gold # exit is non-zero if files differ
if [ $? -ne 0 ]; then
    has_error=1
    echo "error found: run with cache"
fi

if [ $has_error -eq 0 ]; then
    printf "\033[32mok.\033[0m\n"
fi
exit $has_error
