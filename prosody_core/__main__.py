"""Entry point for the packaged core: ``prosody-core.exe``.

With no arguments it runs the line-delimited JSON server on stdio. With a
method name it performs one request and exits, which is what the CLI and the
test-suite use.
"""

from __future__ import annotations

import sys

from prosody_core.server import main

if __name__ == "__main__":
    sys.exit(main())
