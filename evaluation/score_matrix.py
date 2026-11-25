"""Score eight attested dev experiments against the same annotation file."""

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from evaluation.run_eval import EXPERIMENTS
from evaluation.run_eval import main as score


def main(argv=None):
    """Require a complete matrix and publish results after every case scores."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    if args.output.exists():
        parser.error("Choose a new output directory.")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8-sig"))
    if not isinstance(manifest, dict) or set(manifest) != set(EXPERIMENTS):
        parser.error("The manifest must list all eight experiment names.")
    if any(not isinstance(paths, list) or not paths or
           any(not isinstance(path, str) or not path for path in paths)
           for paths in manifest.values()):
        parser.error("List one or more report paths for each experiment.")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=args.output.parent) as working:
        staging = Path(working) / "scores"
        for experiment in EXPERIMENTS:
            invocation = [
                "--split", "dev", "--experiment", experiment,
                "--annotations", str(args.annotations),
                "--output", str(staging / f"{experiment}.json"),
            ]
            for report in manifest[experiment]:
                invocation.extend(["--report", str(args.manifest.parent / report)])
            score(invocation)
        if args.output.exists():
            parser.error("The output directory already exists.")
        staging.rename(args.output)
    print(args.output)


if __name__ == "__main__":
    main()
