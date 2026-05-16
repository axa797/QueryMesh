#!/usr/bin/env node
/** Regenerate public/ and app/favicon.ico from app/icon.svg (requires: npm i -D sharp to-ico). */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import sharp from "sharp";
import toIco from "to-ico";

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const src = path.join(root, "app/icon.svg");

const pngs = await Promise.all(
  [16, 32, 48].map((s) => sharp(src).resize(s, s).png().toBuffer()),
);
const ico = await toIco(pngs);
fs.writeFileSync(path.join(root, "public/favicon.ico"), ico);
fs.writeFileSync(path.join(root, "app/favicon.ico"), ico);
fs.copyFileSync(src, path.join(root, "public/icon.svg"));
await sharp(src).resize(180, 180).png().toFile(path.join(root, "public/apple-touch-icon.png"));
console.log("Generated favicon.ico, icon.svg, apple-touch-icon.png");
