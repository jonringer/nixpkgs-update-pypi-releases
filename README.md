# Nixpkgs-update-pypi-releases

This is meant to create a compilation of packages to be updated for nixpkgs-update.

## Usage

```
  # collect updates for python-modules
  ./main.py pkgs/development/python-modules/*/default.nix > $XDG_CONFIG_HOME/package-to-update.txt
```
or
```
  # update all non-frozen packages that use buildPython{Application,Package}
  grep -rl ./nixpkgs -e buildPython | grep default | ./main.py > $XDG_CONFIG_HOME/package-to-update.txt
```

## Thanks

Thanks to @fridh who created the original script located: https://github.com/NixOS/nixpkgs/blob/master/pkgs/development/interpreters/python/update-python-libraries/update-python-libraries.py

