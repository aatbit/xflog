import os
from http.client import HTTPConnection, HTTPException
from urllib.parse import urlsplit


def main():
    connection = HTTPConnection("127.0.0.1", int(os.getenv("XFLOG_PORT", "7860")), timeout=5)
    try:
        origin = os.getenv("XFLOG_ORIGIN", "http://127.0.0.1:7860")
        connection.request("GET", "/healthz", headers={"Host": urlsplit(origin).netloc})
        if connection.getresponse().status != 200:
            raise SystemExit(1)
    except (OSError, HTTPException):
        raise SystemExit(1) from None
    finally:
        connection.close()


if __name__ == "__main__":
    main()
