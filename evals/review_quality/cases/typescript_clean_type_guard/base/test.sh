#!/bin/sh
set -eu
# The application is type-checked strictly. Tests use Node's built-in runner;
# transpile their imports without downloading a separate Node typings package.
tsc --noEmit --project tsconfig.json
if [ "$#" -eq 0 ]; then set -- tests/*.test.ts; fi
tsc --noCheck --target ES2022 --module commonjs --esModuleInterop --rootDir . --outDir .test-build "$@"
node --test .test-build/tests/*.test.js
