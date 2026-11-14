# PyInstaller entry script: runs the package the same way `python -m shellac` does.
import sys

from shellac.app import main

sys.exit(main())
