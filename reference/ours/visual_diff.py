"""Create pixel difference images for directly paired 1440×900 captures."""

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parent
REFERENCE = ROOT.parent / "cortexide"
STATES = ["01-main-shell", "02-sidebar", "03-editor", "04-agent-empty", "05-agent-typing", "09-bottom-panel", "10-sidebar-collapsed"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("pass_name")
    args = parser.parse_args()
    source = ROOT / args.pass_name
    output = ROOT / f"diff-{args.pass_name}"
    output.mkdir(exist_ok=True)
    metrics = {}
    for name in STATES:
        reference = np.asarray(Image.open(REFERENCE / f"{name}.png").convert("RGB"), dtype=np.int16)
        ours = np.asarray(Image.open(source / f"{name}.png").convert("RGB"), dtype=np.int16)
        assert reference.shape == ours.shape == (900, 1440, 3)
        difference = np.abs(reference - ours)
        mask = np.max(difference, axis=2) > 20
        Image.fromarray(np.clip(difference * 4, 0, 255).astype(np.uint8)).save(output / f"{name}.png")
        metrics[name] = {
            "rawMismatchPercentThreshold20": round(100 * float(mask.mean()), 2),
            "meanAbsoluteChannelDifference": round(float(difference.mean()), 2),
        }
        if name == "01-main-shell":
            blank = difference[90:870, 350:1138]
            metrics[name]["editorBlankMismatchPercentThreshold20"] = round(100 * float((np.max(blank, axis=2) > 20).mean()), 2)
    (output / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
