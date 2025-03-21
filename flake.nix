{
  description = "Python";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; };
        python = pkgs.python3;
        pythonPackages = python.pkgs;
      in {
        devShells.default = pkgs.mkShell {
          buildInputs = [
            python
            pythonPackages.pip
            pythonPackages.setuptools
            pythonPackages.wheel
          ];
          shellHook = ''
            python -m venv .venv
            source .venv/bin/activate
            pip install ossapi
            pip install dotenv

            #if [ -f requirements.txt ]; then
            #  pip install -r requirements.txt
            #fi
          '';
        };
      });
}

