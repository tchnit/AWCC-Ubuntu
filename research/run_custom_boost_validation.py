#!/usr/bin/python3
"""Normal-user transcript capture for the explicitly approved root experiment."""
import os
from pathlib import Path
import subprocess
import sys

from custom_boost_validation import CONFIRM, approved_channel


def main(argv=None):
    channel=approved_channel(sys.argv[1:] if argv is None else argv)
    if channel is None or os.geteuid()==0:
        return 64
    root=Path(__file__).resolve().parent
    # Exclusive creation preserves every previous run, including aborted ones.
    result=root/f"results/hardware-test-custom-boost-2026-10-15-fan{channel}.jsonl"
    with result.open("x",encoding="utf-8") as transcript:
        with subprocess.Popen(["pkexec","/usr/bin/python3","-I","-B",str(root/"custom_boost_validation.py"),CONFIRM,"--channel",str(channel)],
                              stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1) as child:
            for line in child.stdout:
                transcript.write(line)
                transcript.flush()
                print(line,end="",flush=True)
            return child.wait()


if __name__=="__main__":
    raise SystemExit(main())
