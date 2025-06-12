#!/usr/bin/env bash

if command -v apt-get >/dev/null; then
  apt-get update
  apt-get install -y graphviz
fi

which dot || echo "dot not found"