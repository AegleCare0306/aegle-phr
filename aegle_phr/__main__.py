"""
`python -m aegle_phr` -- standalone dev server on port 8001.

8001, not 8000: the existing ABDM backend owns 8000, and both will run at
once during development. This entry point is for solo development only;
production mounts the router into that backend's process instead.
"""

import uvicorn

from aegle_phr.app import create_app

# Kept as module-level constants rather than argparse: this is a
# development convenience, and anything configurable belongs in .env.
HOST = "127.0.0.1"
PORT = 8001


def main() -> None:
    # The app is built here, inside main() -- not at module scope -- so
    # that importing aegle_phr.__main__ stays free of side effects like
    # every other module in this package.
    uvicorn.run(create_app(), host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    main()
