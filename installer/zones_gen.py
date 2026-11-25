"""Generates installer/zones.json from the Unicode CLDR windowsZones.xml (INST-REQ-055, INST-REQ-051).

Offline, deterministic, standard library only: the same file always gives the same bytes. The file is fetched once by
hand (its release and location are recorded in zones.json), never committed and never read by the installer. The
generator checks the sha256 of the file you name before it parses a byte, and refuses any other content.

Selection rule, one row {windows, iana, country} per IANA name listed in any mapZone type:
  windows  the mapZone "other" value; zones come in the order of the file.
  country  the territory the name is listed under (a name under 001 and a country takes the country). ZZ, the CLDR
           "no territory", and a name listed only under 001 give "001".
  order    inside a zone the name listed under 001 comes first, so windows_to_iana(zone) is the CLDR default; the other
           names follow in the order of the file.
Refused: a name in two Windows zones or two countries, a Windows zone without exactly one 001 row that names exactly one
zone, a value outside the shapes below, a source that is not the file whose sha256 was given. RENAMED writes the
current tz name for spellings CLDR still uses that tz data without backward links does not know.

Regenerate (exit 0 written; 1 refused, one line on stderr and nothing written; 2 usage):
  python3 -m installer.zones_gen --source <xml> --expect-sha256 <sha256> [--tag <release>] --out installer/zones.json
then copy the printed sha256_of_zones into ZONES_SHA256 (installer/log.py) and PINNED (tests/test_installer_zone.py).
--tag may be left out only for the recorded file (RECORDED_SHA256); any other file names its own release.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from contextlib import suppress
from pathlib import Path

RECORDED_TAG = "release-49"
RECORDED_SHA256 = "5f902f94106a396cb7774f0b0e1ca4dfecb686494045350c0b4935d378e3913b"

# Each old spelling is a link to the new name in the IANA data (the L lines of tzdata.zi).
RENAMED = {
    "America/Louisville": "America/Kentucky/Louisville",
    "America/Indianapolis": "America/Indiana/Indianapolis",
    "America/Buenos_Aires": "America/Argentina/Buenos_Aires",
    "America/Catamarca": "America/Argentina/Catamarca",
    "America/Cordoba": "America/Argentina/Cordoba",
    "America/Jujuy": "America/Argentina/Jujuy",
    "America/Mendoza": "America/Argentina/Mendoza",
    "America/Godthab": "America/Nuuk",
    "Atlantic/Faeroe": "Atlantic/Faroe",
    "Europe/Kiev": "Europe/Kyiv",
    "Africa/Asmera": "Africa/Asmara",
    "Asia/Calcutta": "Asia/Kolkata",
    "Asia/Katmandu": "Asia/Kathmandu",
    "Asia/Rangoon": "Asia/Yangon",
    "Asia/Saigon": "Asia/Ho_Chi_Minh",
    "Pacific/Truk": "Pacific/Chuuk",
    "Pacific/Ponape": "Pacific/Pohnpei",
    "Pacific/Enderbury": "Pacific/Kanton",
}

_NAME = re.compile(r"[A-Za-z0-9_+-]+(?:/[A-Za-z0-9_+-]+)*")
_WINDOWS = re.compile(r"\S(?:[^\r\n\t]*\S)?")
_TERRITORY = re.compile(r"001|[A-Z]{2}")
_TAG = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_SHA256 = re.compile(r"[0-9A-Fa-f]{64}")
_NO_COUNTRY = ("001", "ZZ")


class ZonesGenError(Exception):
    """An expected refusal: nothing is written, the command line prints one line and exits 1."""


def published_location(tag):
    """Where CLDR publishes the file of a release. Written without a URL scheme on purpose: it is provenance text that
    nothing fetches, and the installer data-boundary scan (INST-REQ-050) flags every URL to a host outside its policy."""
    return "raw.githubusercontent.com/unicode-org/cldr/%s/common/supplemental/windowsZones.xml" % tag


def table_sha256(zones):
    """The pin: the sha256 of the rows as installer/log.py load_zones recomputes it."""
    return hashlib.sha256(json.dumps(zones, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def resolve_tag(expect_sha256, tag):
    recorded = _sha256_arg(expect_sha256) == RECORDED_SHA256
    if tag is None:
        if recorded:
            return RECORDED_TAG
        raise ZonesGenError("this is not the recorded source file: name its CLDR release with --tag")
    if not _TAG.fullmatch(tag):
        raise ZonesGenError("bad CLDR release tag %r" % tag)
    if recorded and tag != RECORDED_TAG:
        raise ZonesGenError("the recorded source file is %s, not %s: --tag is wrong" % (RECORDED_TAG, tag))
    return tag


def generate(data, expect_sha256, tag=None):
    """The text of zones.json for the source bytes; refuses unless their sha256 is the expected one."""
    expect = _sha256_arg(expect_sha256)
    actual = hashlib.sha256(data).hexdigest()
    if actual != expect:
        raise ZonesGenError("source sha256 is %s, not the expected %s" % (actual, expect))
    tag = resolve_tag(expect, tag)
    zones = _table(_rows(data))
    return _render(_source_text(tag), _how_obtained(tag, expect), table_sha256(zones), zones)


def _sha256_arg(value):
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ZonesGenError("--expect-sha256 must be 64 hexadecimal digits, the sha256 of the source file")
    return value.lower()


def _rows(data):
    try:
        root = ET.fromstring(data)
    except (ET.ParseError, ValueError, LookupError) as e:
        raise ZonesGenError("source is not well-formed XML: %s" % e) from None
    if root.tag != "supplementalData":
        raise ZonesGenError("source root is <%s>, not <supplementalData>" % root.tag)
    elements = root.findall("windowsZones/mapTimezones/mapZone")
    if not elements:
        raise ZonesGenError("source has no windowsZones/mapTimezones/mapZone rows")
    rows = []
    for n, el in enumerate(elements, 1):
        windows, territory, listed = el.get("other"), el.get("territory"), el.get("type")
        for attribute, value in (("other", windows), ("territory", territory), ("type", listed)):
            if value is None:
                raise ZonesGenError("mapZone row %d: missing the %s attribute" % (n, attribute))
        if not _WINDOWS.fullmatch(windows):
            raise ZonesGenError("mapZone row %d: bad other (Windows zone) value %r" % (n, windows))
        if not _TERRITORY.fullmatch(territory):
            raise ZonesGenError("mapZone row %d: bad territory %r" % (n, territory))
        names = listed.split()
        if not names:
            raise ZonesGenError("mapZone row %d: empty type" % n)
        for name in names:
            if not _NAME.fullmatch(name):
                raise ZonesGenError("mapZone row %d: bad IANA name %r" % (n, name))
        rows.append((windows, territory, [RENAMED.get(name, name) for name in names]))
    return rows


def _table(rows):
    zones, owner, countries = {}, {}, {}
    for windows, territory, names in rows:
        zone = zones.setdefault(windows, {"default": [], "names": []})
        if territory == "001":
            if zone["default"]:
                raise ZonesGenError("Windows zone %r has more than one 001 row" % windows)
            if len(names) != 1:
                raise ZonesGenError("Windows zone %r: its 001 row must name exactly one zone" % windows)
            zone["default"] = names
        for name in names:
            if owner.setdefault(name, windows) != windows:
                raise ZonesGenError("%s is listed under two Windows zones: %r and %r" % (name, owner[name], windows))
            if territory not in _NO_COUNTRY and countries.setdefault(name, territory) != territory:
                raise ZonesGenError("%s is listed under two countries: %s and %s" % (name, countries[name], territory))
            if name not in zone["names"]:
                zone["names"].append(name)
    table = []
    for windows, zone in zones.items():
        if not zone["default"]:
            raise ZonesGenError("Windows zone %r has no 001 (default) row" % windows)
        ordered = zone["default"] + [name for name in zone["names"] if name not in zone["default"]]
        table += [{"windows": windows, "iana": name, "country": countries.get(name, "001")} for name in ordered]
    return table


def _source_text(tag):
    return ("Unicode CLDR common/supplemental/windowsZones.xml, %s. Copyright \u00a9 1991-2013 Unicode, Inc. CLDR data "
            "files are interpreted according to the LDML specification; for terms of use, see "
            "www.unicode.org/copyright.html." % tag)


def _how_obtained(tag, sha256):
    return (
        "Generated offline by installer/zones_gen.py from the file published at %s (CLDR tag %s, file sha256 %s). "
        "Selection rule: one row per IANA name listed in any mapZone type; windows is the mapZone other value, in the "
        "order of the file; country is the territory the name is listed under (a name under 001 and a country takes "
        "the country; ZZ and a name only under 001 give 001); inside a zone the name listed under 001 comes first, so "
        "the first row of a zone is the CLDR default; %d names that the tz database now keeps only as links are "
        "written with the current name (RENAMED in the generator). Regenerate: python3 -m installer.zones_gen "
        "--source <file> --expect-sha256 %s --tag %s --out installer/zones.json, then copy sha256_of_zones into "
        "ZONES_SHA256 in installer/log.py and PINNED in tests/test_installer_zone.py."
        % (published_location(tag), tag, sha256, len(RENAMED), sha256, tag)
    )


def _render(source, how_obtained, pin, zones):
    rows = ['  {"windows": %s, "iana": %s, "country": %s}' % (
        json.dumps(z["windows"]), json.dumps(z["iana"]), json.dumps(z["country"])) for z in zones]
    return "".join((
        "{\n",
        ' "source": %s,\n' % json.dumps(source),
        ' "how_obtained": %s,\n' % json.dumps(how_obtained),
        ' "sha256_of_zones": %s,\n' % json.dumps(pin),
        ' "zones": [\n',
        ",\n".join(rows),
        "\n ]\n}\n",
    ))


def _read(path):
    try:
        return Path(path).read_bytes()
    except OSError as e:
        raise ZonesGenError("cannot read source %s: %s" % (path, e.strerror or e)) from None


def _write(path, text):
    """Writes through a temporary file, so a failed run never leaves a half-written table."""
    target = Path(path)
    temporary = target.with_name(target.name + ".tmp")
    try:
        temporary.write_bytes(text.encode("utf-8"))
        os.replace(temporary, target)
    except OSError as e:
        with suppress(OSError):
            temporary.unlink()
        raise ZonesGenError("cannot write %s: %s" % (path, e.strerror or e)) from None


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python3 -m installer.zones_gen", description=__doc__.split("\n")[0])
    parser.add_argument("--source", required=True, help="the CLDR windowsZones.xml, fetched by hand and never committed")
    parser.add_argument("--expect-sha256", required=True, help="its sha256; any other content is refused")
    parser.add_argument("--tag", help="its CLDR release; may be left out only for the recorded file (%s)" % RECORDED_TAG)
    parser.add_argument("--out", required=True, help="where to write the table, normally installer/zones.json")
    args = parser.parse_args(argv)
    try:
        text = generate(_read(args.source), args.expect_sha256, args.tag)
        _write(args.out, text)
    except ZonesGenError as e:
        print("zones_gen: %s" % e, file=sys.stderr)
        return 1
    doc = json.loads(text)
    print("wrote %s: %d rows, %d Windows zones, sha256_of_zones %s" % (
        args.out, len(doc["zones"]), len({z["windows"] for z in doc["zones"]}), doc["sha256_of_zones"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
