#!/usr/bin/env python3
"""소스에서 바로 실행할 때 쓰는 진입 스크립트."""
import sys

from choflix.app import main

if __name__ == "__main__":
    sys.exit(main())
