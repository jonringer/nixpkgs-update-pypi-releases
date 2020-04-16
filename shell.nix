with import <nixpkgs> {};

with python3Packages;

pkgs.mkShell {
  buildInputs = [ packaging requests venvShellHook ];
  venvDir = "venv";
}
