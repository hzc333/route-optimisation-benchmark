"""Inline docs/viz/viz_data.json into the explainer pages, one self-contained
file per language (opens offline and publishes as a single artifact):

    docs/viz/explainer.html    -> docs/viz/index.html      (Chinese)
    docs/viz/explainer_en.html -> docs/viz/index_en.html   (English, made by
                                  experiments.translate_viz)

    python -m experiments.build_viz
"""

from pathlib import Path

VIZ = Path(__file__).resolve().parents[1] / "docs" / "viz"
PAGES = {"explainer.html": "index.html", "explainer_en.html": "index_en.html"}
MARKER = '<script type="application/json" id="viz-data"></script>'


def main() -> None:
    data = (VIZ / "viz_data.json").read_text(encoding="utf-8").replace("</", r"<\/")
    for src, dst in PAGES.items():
        if not (VIZ / src).exists():
            continue
        page = (VIZ / src).read_text(encoding="utf-8")
        assert MARKER in page, src
        out = VIZ / dst
        out.write_text(page.replace(MARKER, MARKER.replace("></script>", f">{data}</script>")),
                       encoding="utf-8")
        print(f"wrote {out} ({out.stat().st_size / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
