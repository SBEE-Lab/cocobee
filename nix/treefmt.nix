{
  projectRootFile = "flake.nix";
  programs = {
    deadnix.enable = true;
    nixfmt.enable = true;
    statix.enable = true;
    ruff-check.enable = true;
    ruff-format.enable = true;
  };
}
