"""Untrusted execution entrypoint. Installed only in disposable job images."""
import contextlib
import io
import json
import sys


class BoundedLog(io.TextIOBase):
    def __init__(self):
        self.size = 0

    def write(self, value):
        self.size += len(value.encode())
        if self.size > 16384:
            raise RuntimeError("PYTHON_LOG_LIMIT")
        return len(value)


def main():
    request = json.loads(sys.stdin.buffer.read(1200000))
    namespace = {"__name__": "tierx_user_tool", "AlertContext": dict, "ClusterContext": dict}
    # This is not a Python-language sandbox: the container is the security boundary.
    with contextlib.redirect_stdout(BoundedLog()), contextlib.redirect_stderr(BoundedLog()):
        exec(compile(request["source"], "<python-tool>", "exec"), namespace)
        result = namespace["run"](request["input"]["alert"], request["input"]["cluster"])
    encoded = json.dumps({"result": result}, allow_nan=False, ensure_ascii=False, separators=(",", ":")).encode()
    if len(encoded) > 70000:
        raise RuntimeError("PYTHON_OUTPUT_LIMIT")
    sys.stdout.buffer.write(encoded)


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        # Source lines and exception values can contain evidence; do not expose them.
        sys.stdout.write('{"error":"PYTHON_EXECUTION_FAILED"}')
        sys.exit(1)
