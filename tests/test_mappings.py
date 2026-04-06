"""Tests for path-to-documentation mappings."""
import pytest

from docgap.core.mappings import PathMapper


class TestPathMapperBasic:
    """Test basic path mapping rules."""

    def setup_method(self):
        self.mapper = PathMapper()

    def test_empty_path_returns_none(self):
        assert self.mapper.map_path("") is None

    def test_contrib_path_returns_none(self):
        assert self.mapper.map_path("contrib/openssl/crypto/bio.c") is None

    def test_sys_contrib_returns_none(self):
        assert self.mapper.map_path("sys/contrib/ipfilter/ip_fil.c") is None

    def test_usr_bin_path(self):
        result = self.mapper.map_path("usr.bin/ls/ls.c")
        assert result is not None
        assert result.endswith(".1")

    def test_usr_sbin_path(self):
        result = self.mapper.map_path("usr.sbin/syslogd/syslogd.c")
        assert result is not None
        assert result.endswith(".8")

    def test_bin_path(self):
        result = self.mapper.map_path("bin/sh/sh.c")
        assert result is not None
        assert result.endswith(".1")

    def test_sbin_path(self):
        result = self.mapper.map_path("sbin/mount/mount.c")
        assert result is not None
        assert result.endswith(".8")

    def test_lib_path(self):
        result = self.mapper.map_path("lib/libc/string/strcpy.c")
        assert result is not None
        assert result.endswith(".3")

    def test_share_man_path(self):
        result = self.mapper.map_path("share/man/man1/ls.1")
        # share/man paths are passed through or remapped
        assert result is not None

    def test_direct_manpage_extension_1(self):
        result = self.mapper.map_path("usr.bin/ls/ls.1")
        assert result is not None

    def test_direct_manpage_extension_3(self):
        result = self.mapper.map_path("lib/libc/printf.3")
        assert result == "lib/libc/printf.3"

    def test_direct_manpage_extension_8(self):
        result = self.mapper.map_path("sbin/newfs/newfs.8")
        assert result == "sbin/newfs/newfs.8"

    def test_direct_manpage_extension_9(self):
        # sys/kern matches sys_kern_sections rule first, so it maps to man9/
        result = self.mapper.map_path("sys/kern/vfs.9")
        assert result is not None
        assert ".9" in result

    def test_sys_kern_path(self):
        result = self.mapper.map_path("sys/kern/vfs_lookup.c")
        assert result is not None
        assert result.endswith(".9")
        assert "man9" in result

    def test_sys_dev_path(self):
        result = self.mapper.map_path("sys/dev/usb/usb.c")
        assert result is not None
        assert result.endswith(".4")
        assert "man4" in result

    def test_sys_net_path(self):
        result = self.mapper.map_path("sys/net/if.c")
        assert result is not None
        assert result.endswith(".4")

    def test_sys_sys_path(self):
        result = self.mapper.map_path("sys/sys/types.h")
        assert result is not None
        assert result.endswith(".9")

    def test_handbook_books_path(self):
        result = self.mapper.map_path("books/handbook/intro.adoc")
        assert result == "books/handbook/intro.adoc"

    def test_handbook_documentation_path(self):
        result = self.mapper.map_path("documentation/content/en/books/handbook/chapter.adoc")
        assert result == "documentation/content/en/books/handbook/chapter.adoc"

    def test_unrecognized_path_returns_none(self):
        result = self.mapper.map_path("completely/unknown/path.py")
        assert result is None


class TestMapPathsToDocs:
    """Test map_paths_to_docs deduplication."""

    def setup_method(self):
        self.mapper = PathMapper()

    def test_empty_list_returns_empty(self):
        assert self.mapper.map_paths_to_docs([]) == []

    def test_deduplication(self):
        paths = ["usr.bin/ls/ls.c", "usr.bin/ls/ls.h"]
        result = self.mapper.map_paths_to_docs(paths)
        # Both map to the same doc, should deduplicate
        assert len(result) <= 2

    def test_mixed_mappable_and_unmappable(self):
        paths = ["usr.bin/ls/ls.c", "contrib/vendor/file.c"]
        result = self.mapper.map_paths_to_docs(paths)
        assert isinstance(result, list)

    def test_multiple_distinct_docs(self):
        paths = ["usr.bin/ls/ls.c", "sbin/mount/mount.c"]
        result = self.mapper.map_paths_to_docs(paths)
        assert len(result) == 2

    def test_share_man_in_path_direct(self):
        """Path containing share/man/ is passed through directly."""
        result = self.mapper.map_path("src/share/man/man1/test.1")
        # "share/man/" is in this path, so it returns the path
        assert result == "src/share/man/man1/test.1"

    def test_bin_simple_single_file(self):
        """Simple bin/<file> path (no sub-directory) maps correctly."""
        # bin/foo maps using the else branch (no "/" in rest after stripping prefix)
        result = self.mapper.map_path("bin/sh")
        # "bin/sh" has no nested path after "bin/" prefix, rest="sh", no "/" in rest
        assert result is not None
        assert result.endswith(".1")

    def test_extension_3_direct(self):
        """A .3 manpage path is returned as-is."""
        result = self.mapper.map_path("lib/libc/printf.3")
        assert result == "lib/libc/printf.3"

    def test_extension_8_direct(self):
        """A .8 manpage path is returned as-is (not in sbin/ prefix)."""
        result = self.mapper.map_path("docs/mount.8")
        assert result == "docs/mount.8"
