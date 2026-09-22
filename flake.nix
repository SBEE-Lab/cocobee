{
  description = "cocoindex-playground";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    pyproject-nix = {
      url = "github:pyproject-nix/pyproject.nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    uv2nix = {
      url = "github:pyproject-nix/uv2nix";
      inputs.nixpkgs.follows = "nixpkgs";
      inputs.pyproject-nix.follows = "pyproject-nix";
    };
    pyproject-build-systems = {
      url = "github:pyproject-nix/build-system-pkgs";
      inputs.nixpkgs.follows = "nixpkgs";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.uv2nix.follows = "uv2nix";
    };
    treefmt-nix = {
      url = "github:numtide/treefmt-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    inputs:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "aarch64-darwin"
      ];

      eachSystem =
        f:
        inputs.nixpkgs.lib.genAttrs systems (
          system:
          f {
            inherit system;
            pkgs = inputs.nixpkgs.legacyPackages.${system};
          }
        );

      workspace = inputs.uv2nix.lib.workspace.loadWorkspace { workspaceRoot = ./.; };
      pythonOverlay = workspace.mkPyprojectOverlay { sourcePreference = "wheel"; };
      pythonOverrides = final: prev: {
        watchdog = prev.watchdog.overrideAttrs (old: {
          nativeBuildInputs = (old.nativeBuildInputs or [ ]) ++ [ final.setuptools ];
        });
      };

      pythonSets = eachSystem (
        { pkgs, ... }:
        (pkgs.callPackage inputs.pyproject-nix.build.packages {
          python = pkgs.python314;
        }).overrideScope
          (
            inputs.nixpkgs.lib.composeManyExtensions [
              inputs.pyproject-build-systems.overlays.wheel
              pythonOverlay
              pythonOverrides
            ]
          )
      );

      treefmtEval = eachSystem (
        { pkgs, ... }:
        inputs.treefmt-nix.lib.evalModule pkgs {
          projectRootFile = "flake.nix";
          programs = {
            deadnix.enable = true;
            nixfmt.enable = true;
            statix.enable = true;
          };
        }
      );
    in
    {
      checks = eachSystem (
        { system, ... }:
        {
          formatting = treefmtEval.${system}.config.build.check inputs.self;
        }
      );

      formatter = eachSystem ({ system, ... }: treefmtEval.${system}.config.build.wrapper);

      devShells = eachSystem (
        { pkgs, system, ... }:
        let
          virtualenv = pythonSets.${system}.mkVirtualEnv "cocoindex-playground-dev" workspace.deps.all;

          uv2nix = pkgs.mkShell {
            packages = [
              virtualenv
              pkgs.uv
            ];

            env = {
              UV_NO_SYNC = "1";
              UV_PYTHON = pythonSets.${system}.python.interpreter;
              UV_PYTHON_DOWNLOADS = "never";
            };

            shellHook = ''
              unset PYTHONPATH
            '';
          };

          impure = pkgs.mkShell {
            packages = [
              pkgs.python314
              pkgs.uv
            ];

            env = {
              UV_PYTHON = pkgs.python314.interpreter;
              UV_PYTHON_DOWNLOADS = "never";
            }
            // inputs.nixpkgs.lib.optionalAttrs pkgs.stdenv.hostPlatform.isLinux {
              LD_LIBRARY_PATH = inputs.nixpkgs.lib.makeLibraryPath [
                pkgs.stdenv.cc.cc.lib
              ];
            };

            shellHook = ''
              unset PYTHONPATH
              uv sync
              . .venv/bin/activate
            '';
          };
        in
        {
          inherit impure uv2nix;
          default = impure;
        }
      );

      packages = eachSystem (
        { system, ... }:
        {
          default = pythonSets.${system}.mkVirtualEnv "cocoindex-playground" workspace.deps.default;
        }
      );
    };
}
