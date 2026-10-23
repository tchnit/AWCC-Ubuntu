# Unmodified offline comparison build — NOT A REPLACEMENT DRIVER

The four source files are unchanged extractions from the verified Ubuntu source
archive; its package diff does not modify them. Build through
`bash tools/build-alienware-offline.sh baseline`, not directly in this directory
(the workspace path contains spaces, which external-module Kbuild rejects).

Build succeeds against `7.0.0-38-generic` headers. The external-build srcversion
is `22697BF46BB665FD2E285BB`, NOT the installed/loaded driver's
`28A4134FBF8432C66D7C668`. This is not a reproducible reconstruction of Ubuntu's
signed binary; the reason for the srcversion difference was not separately
audited. Exact-source provenance is established by the source-package hashes
and diff, not by a claim that this binary matches stock.

Do not install/load this artefact as part of read-only research. The system
continues using the original Ubuntu module. See
`docs/PHASE5B_AWCC_REJECTION_ANALYSIS.md` for installed-binary evidence.
