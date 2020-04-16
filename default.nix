let
  pkgs = import <nixpkgs> { };
in {
  inherit pkgs;
  interpreter = pkgs.python3.withPackages(ps: with ps; [
    requests packaging
  ]);
}

