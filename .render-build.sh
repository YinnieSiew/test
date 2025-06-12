#!/usr/bin/env bash

mkdir -p .graphviz/bin
curl -L https://gitlab.com/api/v4/projects/4207231/packages/generic/graphviz-releases/12.2.1/graphviz-12.2.1-linux-amd64.tar.gz | tar -xz -C .graphviz

echo "export PATH=\"$PWD/.graphviz/bin:\$PATH\"" >> ~/.bashrc