{
  inputs,
  workspaceRoot,
}:
let
  inherit (inputs.nixpkgs) lib;

  workspace = inputs.uv2nix.lib.workspace.loadWorkspace { inherit workspaceRoot; };

  pythonOverlay = workspace.mkPyprojectOverlay { sourcePreference = "wheel"; };

  packageOverrides = final: prev: {
    # uv.lock omits build-system metadata required for this sdist build.
    watchdog = prev.watchdog.overrideAttrs (old: {
      nativeBuildInputs =
        old.nativeBuildInputs
        ++ final.resolveBuildSystem {
          setuptools = [ ];
        };
    });
  };

  isCudaWheel =
    name:
    lib.hasPrefix "nvidia-" name
    || builtins.elem name [
      "torch"
      "triton"
    ];

  cudaWheelOverrides =
    _final: prev:
    lib.mapAttrs (
      _name: package:
      package.overrideAttrs {
        # Linux torch depends on CUDA libraries shipped by sibling wheels.
        # autoPatchelf cannot resolve them across separate derivations.
        autoPatchelfIgnoreMissingDeps = true;
      }
    ) (lib.filterAttrs (name: _package: isCudaWheel name) prev);
in
{
  inherit workspace;

  mkPythonSet =
    pkgs:
    let
      overlays = [
        inputs.pyproject-build-systems.overlays.wheel
        pythonOverlay
        packageOverrides
      ]
      ++ lib.optionals pkgs.stdenv.hostPlatform.isLinux [
        cudaWheelOverrides
      ];
    in
    (pkgs.callPackage inputs.pyproject-nix.build.packages {
      python = pkgs.python314;
    }).overrideScope
      (lib.composeManyExtensions overlays);
}
