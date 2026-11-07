"""A book that carries its series only as EPUB 3 collection metadata."""
import zipfile

from epubkit.tools import scan_epubs as S

OPF = """<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
<dc:title>Book Six</dc:title><dc:creator>A. Writer</dc:creator>
%s
</metadata>
<manifest><item id="c" href="c.xhtml" media-type="application/xhtml+xml"/></manifest>
<spine><itemref idref="c"/></spine>
</package>"""


def book(tmp_path, meta):
    p = tmp_path / "b.epub"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml",
                   '<container><rootfiles><rootfile full-path="o.opf"/></rootfiles></container>')
        z.writestr("o.opf", OPF % meta)
        z.writestr("c.xhtml", "<html/>")
    return str(p)


def test_series_from_belongs_to_collection(tmp_path):
    got = S.read(book(tmp_path, '<meta property="belongs-to-collection" id="s">Long Saga</meta>'
                                '<meta refines="#s" property="collection-type">series</meta>'
                                '<meta refines="#s" property="group-position">6</meta>'))
    assert (got["series"], got["series_index"]) == ("Long Saga", "6")


def test_calibre_series_still_wins_and_a_set_is_not_a_series(tmp_path):
    got = S.read(book(tmp_path, '<meta name="calibre:series" content="Saga"/>'
                                '<meta property="belongs-to-collection" id="s">Other</meta>'))
    assert got["series"] == "Saga"
    got = S.read(book(tmp_path, '<meta property="belongs-to-collection" id="s">Box</meta>'
                                '<meta refines="#s" property="collection-type">set</meta>'))
    assert got["series"] is None
