{
  description = "Python environment for Jupyter notebooks";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = {
    self,
    nixpkgs,
    flake-utils,
  }:
    flake-utils.lib.eachDefaultSystem (
      system: let
        pkgs = nixpkgs.legacyPackages.${system};
        python = pkgs.python311;
        pythonPackages = python.pkgs;
      in {
        devShells.default = pkgs.mkShell {
          buildInputs = [
            python
            pythonPackages.pandas
            pythonPackages.numpy
            pythonPackages.matplotlib
            pythonPackages.jupyter
            pythonPackages.ipython
            pythonPackages.notebook
          ];

          shellHook = ''
            # Create a stable Python symlink for VSCode
            mkdir -p .direnv/python-default/bin
            ln -sf ${python}/bin/python .direnv/python-default/bin/python
            ln -sf ${python}/bin/python3 .direnv/python-default/bin/python3

            echo "Python environment ready!"
            echo "Run 'jupyter notebook' to start the Jupyter server"
            echo "Or 'jupyter lab' for JupyterLab"
          '';
        };
      }
    );
}
