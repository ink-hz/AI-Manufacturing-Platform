"""Private acceptance host. Never exported by the manufacturing package."""

import argparse
from pathlib import Path
from http_fixture import serve

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    serve(parser.parse_args().root.resolve())
