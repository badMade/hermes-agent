# nix/web.nix — Hermes Web Dashboard (Vite/React) frontend build
{ pkgs, hermesNpmLib, ... }:
let
  src = ../web;
  npmDeps = pkgs.fetchNpmDeps {
    inherit src;
    hash = "sha256-AM+F+Dnav6erO+ebzGYBkEOv0H0P+t0921l0jpNADZo=";
  };

  npm = hermesNpmLib.mkNpmPassthru { folder = "web"; attr = "web"; pname = "hermes-web"; };

  packageJson = builtins.fromJSON (builtins.readFile (src + "/package.json"));
  version = packageJson.version;
in
pkgs.buildNpmPackage (npm // {
  pname = "hermes-web";
  inherit src npmDeps version;

  doCheck = false;

  buildPhase = ''
    npx tsc -b
    npx vite build --outDir dist
  '';

  installPhase = ''
    runHook preInstall
    cp -r dist $out
    runHook postInstall
  '';
})
