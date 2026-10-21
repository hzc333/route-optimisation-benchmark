"""Build the two shareable walkthrough pages from their sources.

    docs/viz/src/page_zh.html       Chinese page: text, styles and chart script
    docs/viz/src/page_en_text.html  English page text and styles
    docs/viz/src/viz_data.json      chart data (python -m experiments.export_viz)

        -> docs/viz/walkthrough_zh.html
        -> docs/viz/walkthrough_en.html  (chart script translated by
                                          experiments.translate_viz)

Each output is one self-contained file with the data inlined: it opens offline
and publishes as a single artifact.

    python -m experiments.build_viz
"""

from pathlib import Path

from experiments.translate_viz import english_page

VIZ = Path(__file__).resolve().parents[1] / "docs" / "viz"
SRC = VIZ / "src"
MARKER = '<script type="application/json" id="viz-data"></script>'


def main() -> None:
    data = (SRC / "viz_data.json").read_text(encoding="utf-8").replace("</", r"<\/")
    pages = {"walkthrough_zh.html": (SRC / "page_zh.html").read_text(encoding="utf-8"),
             "walkthrough_en.html": english_page()}
    for name, page in pages.items():
        assert MARKER in page, name
        out = VIZ / name
        out.write_text(page.replace(MARKER, MARKER.replace("></script>", f">{data}</script>")),
                       encoding="utf-8")
        print(f"wrote {out} ({out.stat().st_size / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
