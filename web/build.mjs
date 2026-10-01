// Bundle the UI into the Python package so `sentinel serve` can serve it directly.
import { build, context } from "esbuild";
import { copyFileSync, mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const outdir = resolve(here, "../src/sentinel/apps/api/static");
const watch = process.argv.includes("--watch");

mkdirSync(resolve(outdir, "assets"), { recursive: true });
copyFileSync(resolve(here, "index.html"), resolve(outdir, "index.html"));
writeFileSync(
  resolve(outdir, "assets/favicon.svg"),
  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path fill="#0f6e6a" d="M12 2.5 20 6v6.2c0 4.6-3.3 8.3-8 9.3-4.7-1-8-4.7-8-9.3V6l8-3.5Z"/><path fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" d="m8.3 12.2 2.5 2.5 4.9-5.2"/></svg>`,
);

const options = {
  entryPoints: { app: resolve(here, "src/main.tsx") },
  bundle: true,
  format: "esm",
  target: ["es2022"],
  outdir: resolve(outdir, "assets"),
  minify: !watch,
  sourcemap: watch ? "inline" : false,
  jsx: "automatic",
  define: { "process.env.NODE_ENV": JSON.stringify(watch ? "development" : "production") },
  logLevel: "info",
  legalComments: "none",
};

if (watch) {
  const ctx = await context(options);
  await ctx.watch();
} else {
  await build(options);
}
