{
  inputs,
  workspaceRoot,
}:
let
  inherit (inputs.nixpkgs) lib;

  workspace = inputs.uv2nix.lib.workspace.loadWorkspace { inherit workspaceRoot; };

  pythonOverlay = workspace.mkPyprojectOverlay { sourcePreference = "wheel"; };

  # sdist-only deps that build with setuptools but omit it from
  # build-system.requires, so uv2nix has nothing to bootstrap them with.
  needsSetuptools = [
    "watchdog"
  ];

  pythonOverrides =
    final: prev:
    lib.genAttrs needsSetuptools (
      name:
      prev.${name}.overrideAttrs (old: {
        nativeBuildInputs = (old.nativeBuildInputs or [ ]) ++ [ final.setuptools ];
      })
    );
in
{
  inherit workspace;

  mkPythonSet =
    pkgs:
    (pkgs.callPackage inputs.pyproject-nix.build.packages {
      python = pkgs.python314;
    }).overrideScope
      (
        lib.composeManyExtensions [
          inputs.pyproject-build-systems.overlays.wheel
          pythonOverlay
          pythonOverrides
        ]
      );
}
