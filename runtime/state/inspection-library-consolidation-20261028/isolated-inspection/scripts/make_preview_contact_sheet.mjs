import sharp from "sharp";

const [, , outputPath, ...inputPaths] = process.argv;
if (!outputPath || inputPaths.length !== 4) throw new Error("usage: make_preview_contact_sheet.mjs <output.png> <four-input-pngs>");

const images = await Promise.all(inputPaths.map((input) => sharp(input).resize({ width: 900 }).png().toBuffer({ resolveWithObject: true })));
const cellHeight = Math.max(...images.map(({ info }) => info.height));
await sharp({ create: { width: 1800, height: cellHeight * 2, channels: 4, background: "#FFFFFF" } })
  .composite(images.map(({ data }, index) => ({ input: data, left: (index % 2) * 900, top: Math.floor(index / 2) * cellHeight })))
  .png()
  .toFile(outputPath);

console.log(JSON.stringify({ outputPath, inputs: inputPaths.length, width: 1800, height: cellHeight * 2 }));
