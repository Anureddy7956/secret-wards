"""A private 0700 temp dir under TMPDIR, always wiped in finally. Only encrypted blobs go inside."""
from __future__ import annotations

import os
import shutil
import tempfile
from contextlib import contextmanager


@contextmanager
def private_tempdir():
    path = tempfile.mkdtemp(prefix="rk-")
    os.chmod(path, 0o700)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
