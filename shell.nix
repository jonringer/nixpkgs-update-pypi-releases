with import <nixpkgs> {};

with python3Packages;

pkgs.mkShell {
  buildInputs = [ requests venvShellHook ];
  venvDir = "venv";
}
