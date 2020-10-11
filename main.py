#!/usr/bin/env nix-shell
#!nix-shell -i python3 -p nix -p "python3.withPackages(ps: with ps; [ requests ])

"""
This is used to create a manifest of updated python packages to be used by nixpkgs-updates

Example Usage:
```
  # collect updates for python-modules
  ./main.py pkgs/development/python-modules/*/default.nix > $XDG_CONFIG_HOME/package-to-update.txt
```
or
```
  # update all non-frozen packages that use buildPython{Application,Package}
  grep -rl ./nixpkgs -e buildPython | grep default | ./main.py > $XDG_CONFIG_HOME/package-to-update.txt
"""

import argparse
import collections
import logging
import os
import re
import requests
import shlex
import subprocess
import sys

from concurrent.futures import ThreadPoolExecutor as Pool
from packaging.version import Version as _Version
from packaging.version import InvalidVersion
from packaging.specifiers import SpecifierSet


INDEX = "https://pypi.io/pypi"
"""url of PyPI"""

PYPI_PACKAGE_URL = "https://pypi.org/project"
"""default url of a package on PyPI"""

EXTENSIONS = ['tar.gz', 'tar.bz2', 'tar', 'zip', '.whl']
"""Permitted file extensions. These are evaluated from left to right and the first occurance is returned."""

PRERELEASES = False
CACHE_HOME = os.environ.get("XDG_CACHE_HOME", os.environ.get("HOME", "."))

logging.basicConfig(level=logging.INFO, stream=sys.stderr)


class Version(_Version, collections.abc.Sequence):

    def __init__(self, version):
        super().__init__(version)
        # We cannot use `str(Version(0.04.21))` because that becomes `0.4.21`
        # https://github.com/avian2/unidecode/issues/13#issuecomment-354538882
        self.raw_version = version

    def __getitem__(self, i):
        return self._version.release[i]

    def __len__(self):
        return len(self._version.release)

    def __iter__(self):
        yield from self._version.release


def _get_values(attribute, text):
    """Match attribute in text and return all matches.

    :returns: List of matches.
    """
    regex = '{}\s+=\s+"(.*)";'.format(attribute)
    regex = re.compile(regex)
    values = regex.findall(text)
    return values


def _get_unique_value(attribute, text):
    """Match attribute in text and return unique match.

    :returns: Single match.
    """
    values = _get_values(attribute, text)
    n = len(values)
    if n > 1:
        raise ValueError("found too many values for {}".format(attribute))
    elif n == 1:
        return values[0]
    else:
        raise ValueError("no value found for {}".format(attribute))


def _get_line_and_value(attribute, text):
    """Match attribute in text. Return the line and the value of the attribute."""
    regex = '({}\s+=\s+"(.*)";)'.format(attribute)
    regex = re.compile(regex)
    value = regex.findall(text)
    n = len(value)
    if n > 1:
        raise ValueError("found too many values for {}".format(attribute))
    elif n == 1:
        return value[0]
    else:
        raise ValueError("no value found for {}".format(attribute))


def _fetch_page(url):
    r = requests.get(url)
    if r.status_code == requests.codes.ok:
        return r.json()
    else:
        raise ValueError("request for {} failed".format(url))


SEMVER = {
    'major': 0,
    'minor': 1,
    'patch': 2,
}


def _determine_latest_version(current_version, target, versions):
    """Determine latest version, given `target`.
    """
    current_version = Version(current_version)

    def _parse_versions(versions):
        for v in versions:
            try:
                yield Version(v)
            except InvalidVersion:
                pass

    versions = _parse_versions(versions)

    index = SEMVER[target]

    ceiling = list(current_version[0:index])
    if len(ceiling) == 0:
        ceiling = None
    else:
        ceiling[-1] += 1
        ceiling = Version(".".join(map(str, ceiling)))

    # We do not want prereleases
    versions = SpecifierSet(prereleases=PRERELEASES).filter(versions)

    if ceiling is not None:
        versions = SpecifierSet(f"<{ceiling}").filter(versions)

    return (max(sorted(versions))).raw_version


def _check_pypi(package, current_version, target):
    """Get latest version and hash from PyPI."""
    json_url = "{}/{}/json".format(INDEX, package)
    json = _fetch_page(json_url)

    versions = json['releases'].keys()
    version = _determine_latest_version(current_version, target, versions)

    try:
        releases = json['releases'][version]
    except KeyError as e:
        raise KeyError('Could not find version {} for {}'.format(version, package)) from e
    return version


def _print_new_version(path, target, drv_name_path):
    # Read the expression
    with open(path, 'r') as f:
        text = f.read()

    # Determine pname.
    pname = _get_unique_value('pname', text)

    # Determine version.
    version = _get_unique_value('version', text)

    new_version = _check_pypi(pname, version, target)

    package_url = "{}/{}/".format(PYPI_PACKAGE_URL, pname)

    if new_version == version:
        logging.info("Path {}: already at latest version for: {}.".format(path, pname))
        return False
    elif Version(new_version) <= Version(version):
        raise ValueError("downgrade for {}.".format(pname))

    # to get cat and the pipes to work, I had to do shell=True
    cmd = f"cat -- {drv_name_path} | grep {pname}-{version} | grep -v python2 | head -1"
    drv_name_bytes = subprocess.check_output(cmd, shell=True)

    # b"friture-0.37\n" -> "friture-0.37"
    drv_name = drv_name_bytes.decode('utf-8').rstrip()

    # "azure-mgmt-storge-0.37" -> "azure-mgmt-storge"
    drv_name = "-".join(drv_name.split("-")[:-1])

    if len(drv_name) == 0:
        return False

    print(f"{drv_name} {version} {new_version} {package_url}")


def _update(path, target, drv_name_path):
    # We need to read and modify a Nix expression.
    if os.path.isdir(path):
        path = os.path.join(path, 'default.nix')

    # If a default.nix does not exist, we quit.
    if not os.path.isfile(path):
        logging.info("Path {}: does not exist.".format(path))
        return False

    # If file is not a Nix expression, we quit.
    if not path.endswith(".nix"):
        logging.info("Path {}: does not end with `.nix`.".format(path))
        return False

    try:
        _print_new_version(path, target, drv_name_path)
        return True
    except ValueError as e:
        logging.warning("Path {}: {}".format(path, e))
        return False


def create_package_list(initial_packages: list):
    logging.info("Creating pypi package list")
    packages = initial_packages.copy()
    # also read packages from stdin
    if not sys.stdin.isatty():
        logging.info("Reading package paths from stdin")
        packages.extend(sys.stdin.read().split())

    assert len(packages) > 0, \
        "You must specify more than one package. Please list package paths as arguments or through stdin"

    return list(map(os.path.abspath, packages))


def generate_drv_name_file(nixpkgs: str, path: str):
    logging.info(f"Creating drv name file at {path}")
    nixpkgs_arg = ''
    if nixpkgs != '':
        nixpkgs_arg = f"-f {nixpkgs} "
    cmd=f"nix-env {nixpkgs_arg}-qa"
    logging.info(f"Executing: {cmd}")
    file_contents = subprocess.check_output(shlex.split(cmd))
    with open(path, 'w+') as f:
        f.write(file_contents.decode('utf-8'))


def main():
    logging.info("########## BEGINNING OF NIXPKGS_UPDATE_PYPI_RELEASES ##########")

    parser = argparse.ArgumentParser()
    parser.add_argument('package', type=str, nargs='*', default=[])
    parser.add_argument('--nixpkgs', type=str, default='')
    parser.add_argument('--target', type=str, choices=SEMVER.keys(), default='major')
    parser.add_argument('--drv-name-path', type=str, default=os.path.join(CACHE_HOME, "drv_names.txt"))
    args = parser.parse_args()

    generate_drv_name_file(args.nixpkgs, args.drv_name_path)
    packages = create_package_list(args.package)

    logging.info("Updating packages...")

    def update_func(pkg):
        return _update(pkg, target=args.target, drv_name_path=args.drv_name_path)

    # Use threads to update packages concurrently
    # list is used to force evaluation of the generator
    with Pool() as p:
        results = list(p.map(update_func, packages))

    logging.info("Finished updating packages.")

    count = sum(filter(bool, results))
    logging.info("Checked {} packages, {} updated".format(len(results), count))
    logging.info("########## END OF NIXPKGS_UPDATE_PYPI_RELEASES ##########")


if __name__ == '__main__':
    main()
