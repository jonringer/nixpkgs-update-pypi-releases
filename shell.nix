let
  pkgs = import ./.;
in
with pkgs;
mkShell {
  buildInputs = [ interpreter ];
}
