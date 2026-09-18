#!/usr/bin/env bash
set -euo pipefail

st_file="${1:?Structured Text source path is required}"
work_dir="$(mktemp -d /tmp/plc_agent_compile_XXXXXX)"
cd "$work_dir"
cp "$st_file" program.st
ln -s /usr/local/share/matiec/lib lib

if ! iec2c -f -p -i -l program.st >iec2c.log 2>&1; then
    cat iec2c.log >&2
    exit 1
fi
cat iec2c.log >&2

for file in Config0.c Config0.h Res0.c POUS.c POUS.h LOCATED_VARIABLES.h VARIABLES.csv; do
    if [ ! -f "$file" ]; then
        echo "MatIEC did not generate required runtime artifact: $file" >&2
        exit 4
    fi
done

if ! xml2st --generate-debug program.st VARIABLES.csv >/dev/null 2>&1; then
    echo "xml2st failed to generate debug.c" >&2
    exit 2
fi
if ! xml2st --generate-gluevars LOCATED_VARIABLES.h >/dev/null 2>&1; then
    echo "xml2st failed to generate glueVars.c" >&2
    exit 3
fi

cat >c_blocks_code.cpp <<'EOF'
extern "C" {}
EOF
cat >c_blocks.h <<'EOF'
#ifndef C_BLOCKS_H
#define C_BLOCKS_H
#endif
EOF

rm lib
cp -r /usr/local/share/matiec/lib ./lib
package="$work_dir/program.zip"
zip -qr "$package" \
    Config0.c Config0.h Res0.c POUS.c POUS.h LOCATED_VARIABLES.h \
    VARIABLES.csv debug.c glueVars.c c_blocks_code.cpp c_blocks.h lib/
printf '%s\n' "$package"
