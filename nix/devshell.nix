{
  pkgs,
  pythonSet,
  workspace,
}:
let
  inherit (pkgs) lib;

  virtualenv = pythonSet.mkVirtualEnv "cocoindex-playground-dev" workspace.deps.all;

  base = {
    packages = with pkgs; [
      git
      lmdb
      ruff
      sops
      uv
    ];
    env = {
      UV_PYTHON = pythonSet.python.interpreter;
      UV_PYTHON_DOWNLOADS = "never";
    };
    shellHook = ''
      unset PYTHONPATH
      export REPO_ROOT=$(git rev-parse --show-toplevel)
    '';
  };

  mkDevShell =
    args:
    pkgs.mkShell (
      base
      // args
      // {
        packages = (args.packages or [ ]) ++ base.packages;
        env = base.env // (args.env or { });
        shellHook = base.shellHook + (args.shellHook or "");
      }
    );

  uv2nix = mkDevShell {
    packages = [ virtualenv ];
    env.UV_NO_SYNC = "1";
  };

  impure = mkDevShell {
    packages = [ pythonSet.python ];
    env = lib.optionalAttrs pkgs.stdenv.hostPlatform.isLinux {
      LD_LIBRARY_PATH = lib.makeLibraryPath [ pkgs.stdenv.cc.cc.lib ];
    };
    shellHook = ''
      uv sync
      . .venv/bin/activate
    '';
  };
in
{
  inherit impure uv2nix;
  default = impure;
}
