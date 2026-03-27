import { build } from "esbuild";

export async function setup() {
    await build({
        entryPoints: ["./index.ts"],
        bundle: true,
        outfile: "./dist/index.mjs",
        format: "esm",
        target: "esnext",
        minify: false,
        external: [],
    });
}
