#!/usr/bin/env bash
# setup_dirs.sh — create the expected input/output directory tree
# Usage: ./setup_dirs.sh <prefix>

set -euo pipefail
PREFIX="${1:?Usage: $0 <prefix>}"

echo "Creating directory structure under: $PREFIX"

# Step 1: addr2function
mkdir -p "$PREFIX/addr2function/input/selftests-kvm-rawcover"
mkdir -p "$PREFIX/addr2function/output/selftests-kvm-functions"

# Step 2: sum
mkdir -p "$PREFIX/sum/input"
mkdir -p "$PREFIX/sum/output"

# Step 3: coverage
mkdir -p "$PREFIX/coverage/output"

# Step 4: analyze
mkdir -p "$PREFIX/analyze/output"

echo ""
echo "Done. Place your files as follows:"
echo ""
echo "  $PREFIX/addr2function/input/fuzz-old-rawcover.txt"
echo "  $PREFIX/addr2function/input/fuzz-new-rawcover.txt"
echo "  $PREFIX/addr2function/input/selftests-kvm-rawcover/<test>_rawcover.txt  (one per test)"
echo "  $PREFIX/addr2function/input/fuzz-old-vmlinux"
echo "  $PREFIX/addr2function/input/fuzz-new-vmlinux"
echo "  $PREFIX/addr2function/input/selftests-kvm-vmlinux"
echo ""
echo "  $PREFIX/sum/input/fuzz-old-vmlinux      (symlink or copy)"
echo "  $PREFIX/sum/input/fuzz-new-vmlinux"
echo "  $PREFIX/sum/input/selftests-kvm-vmlinux"
echo ""
echo "Tip: symlink the vmlinux files to avoid duplication:"
echo "  ln -s \$PREFIX/addr2function/input/fuzz-old-vmlinux \$PREFIX/sum/input/fuzz-old-vmlinux"
