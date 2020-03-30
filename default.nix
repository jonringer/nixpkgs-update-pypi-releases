let
  pkgs = import <nixpkgs> { };
in {
  inherit (pkgs) mkShell;
  interpreter = pkgs.python3.withPackages(ps: with ps; [
    toolz requests
  ]);
}

