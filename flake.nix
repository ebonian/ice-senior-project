{
  description = "ICE Senior Project";

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

        # Python with required packages
        pythonEnv = pkgs.python3.withPackages (ps:
          with ps; [
            # Data analysis
            pandas
            numpy

            # Visualization
            matplotlib

            # HTTP requests
            requests

            # Jupyter
            jupyter
            notebook
            ipython
            ipykernel

            # Additional useful packages
            jupyter-client
            jupyter-core
            nbconvert
            nbformat
          ]);
      in {
        # Development shell
        devShells.default = pkgs.mkShell {
          buildInputs = [
            pythonEnv
          ];

          shellHook = ''
            echo "🚀 ICE Senior Project development environment"
            echo ""
            echo "Available commands:"
            echo "  jupyter notebook     - Start Jupyter Notebook server"
            echo "  jupyter lab          - Start JupyterLab server"
            echo "  python               - Python interpreter"
            echo ""
            echo "Python version: $(python --version)"
            echo "Jupyter version: $(jupyter --version | head -n 1)"
            echo ""
          '';
        };

        # Apps for easy access
        apps = {
          notebook = {
            type = "app";
            program = "${pythonEnv}/bin/jupyter-notebook";
          };

          lab = {
            type = "app";
            program = "${pythonEnv}/bin/jupyter-lab";
          };

          python = {
            type = "app";
            program = "${pythonEnv}/bin/python";
          };
        };

        # Default app
        apps.default = self.apps.${system}.notebook;
      }
    );
}
