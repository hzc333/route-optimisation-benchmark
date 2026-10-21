"""Inline docs/viz/viz_data.json into the explainer page -> docs/viz/index.html
(one self-contained file: opens offline and publishes as a single artifact).

    python -m experiments.build_viz
"""

from pathlib import Path

VIZ = Path(__file__).resolve().parents[1] / "docs" / "viz"


def main() -> None:
    page = (VIZ / "explainer.html").read_text(encoding="utf-8")
    data = (VIZ / "viz_data.json").read_text(encoding="utf-8").replace("</", r"<\/")
    marker = '<script type="application/json" id="viz-data"></script>'
    assert marker in page
    out = VIZ / "index.html"
    out.write_text(page.replace(marker, marker.replace("></script>", f">{data}</script>")),
                   encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
