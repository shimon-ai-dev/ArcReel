"""Only allowlisted references under a selected library can be packaged."""

import hashlib
from pathlib import Path

import pytest

from lib.library_bundle.safe_io import LibraryReader, LibraryReadError, new_output_directory, relative_path


def test_in_root_product_symlink_keeps_source_and_copies_bytes(tmp_path: Path):
    root = tmp_path / "library"
    archive = root / "archive" / "image.png"
    archive.parent.mkdir(parents=True)
    archive.write_bytes(b"synthetic-media")
    product = root / "product.png"
    product.symlink_to(archive)
    reader = LibraryReader(root)

    content = reader.inspect("product.png", expected_sha256=hashlib.sha256(b"synthetic-media").hexdigest())
    output = new_output_directory(reader.root, tmp_path / "output")
    reader.copy(content, output / content.filename)

    assert (output / content.filename).read_bytes() == b"synthetic-media"
    assert content.source == "product.png"
    assert product.is_symlink()
    assert archive.read_bytes() == b"synthetic-media"


def test_product_only_root_cannot_follow_external_archive(tmp_path: Path):
    products = tmp_path / "products"
    products.mkdir()
    archive = tmp_path / "private.png"
    archive.write_bytes(b"do not copy")
    (products / "image.png").symlink_to(archive)

    with pytest.raises(LibraryReadError, match="complete library"):
        LibraryReader(products).inspect("image.png")


def test_hash_mismatch_stops_packaging(tmp_path: Path):
    (tmp_path / "image.png").write_bytes(b"synthetic-media")
    with pytest.raises(LibraryReadError, match="SHA-256"):
        LibraryReader(tmp_path).inspect("image.png", expected_sha256="0" * 64)


def test_changed_media_is_not_exported_as_verified_content(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    media = source / "image.png"
    media.write_bytes(b"first version")
    reader = LibraryReader(source)
    content = reader.inspect("image.png")
    media.write_bytes(b"second version")

    with pytest.raises(LibraryReadError, match="changed after preview"):
        reader.copy(content, tmp_path / content.filename)


@pytest.mark.parametrize("value", ["../secret.png", "/private.png", "C:/private.png", "a\\b.png", "a/./b.png"])
def test_nonportable_or_escaping_path_is_rejected(value: str):
    with pytest.raises(LibraryReadError, match="relative path"):
        relative_path(value)


def test_output_cannot_modify_the_source_or_existing_output(tmp_path: Path):
    root = tmp_path / "source"
    root.mkdir()
    with pytest.raises(LibraryReadError, match="outside"):
        new_output_directory(root, root / "output")
    output = tmp_path / "output"
    output.mkdir()
    marker = output / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    with pytest.raises(LibraryReadError, match="already exists"):
        new_output_directory(root, output)
    assert marker.read_text(encoding="utf-8") == "keep"


def test_unrelated_nonmedia_file_is_never_copied(tmp_path: Path):
    (tmp_path / ".env").write_text("SECRET=synthetic", encoding="utf-8")
    with pytest.raises(LibraryReadError, match="supported images and audio"):
        LibraryReader(tmp_path).inspect(".env")
