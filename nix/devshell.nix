{
  pkgs,
  pythonSet,
  workspace,
}:
let
  inherit (pkgs) lib;

  virtualenv = pythonSet.mkVirtualEnv "cocobee-dev" workspace.deps.all;

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
      UV_CONCURRENT_DOWNLOADS = "4";
      UV_HTTP_TIMEOUT = "600";
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

  driverLibs = lib.optionalString pkgs.stdenv.hostPlatform.isLinux "${pkgs.addDriverRunpath.driverLink}/lib";

  uv2nix = mkDevShell {
    packages = [ virtualenv ];
    env = {
      UV_NO_SYNC = "1";
    }
    // lib.optionalAttrs pkgs.stdenv.hostPlatform.isLinux {
      LD_LIBRARY_PATH = driverLibs;
    };
  };

  impure = mkDevShell {
    packages = [ pythonSet.python ];
    env = lib.optionalAttrs pkgs.stdenv.hostPlatform.isLinux {
      LD_LIBRARY_PATH = lib.makeLibraryPath [ pkgs.stdenv.cc.cc.lib ] + ":" + driverLibs;
    };
    shellHook = ''
      if [ ! -x .venv/bin/python ] || [ uv.lock -nt .venv/pyvenv.cfg ]; then
        uv sync --frozen
      fi
      . .venv/bin/activate
    '';
  };
in
{
  inherit impure uv2nix;
  default = uv2nix;
}
