import { constants } from "node:fs";
import { access, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { createInterface } from "node:readline/promises";

const rootDirectory = process.cwd();
const examplePath = path.join(rootDirectory, ".env.example");
const environmentPath = path.join(rootDirectory, ".env");
const keys = [
  "DB_HOST",
  "DB_PORT",
  "DB_USER",
  "DB_PASSWORD",
  "DB_NAME",
  "SESSION_IDLE_TIMEOUT_MINUTES",
  "SESSION_COOKIE_MAX_AGE_DAYS",
];

async function exists(filePath) {
  try {
    await access(filePath, constants.F_OK);
    return true;
  } catch {
    return false;
  }
}

function parseEnvironment(content) {
  return Object.fromEntries(
    content
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter((line) => line && !line.startsWith("#"))
      .map((line) => {
        const separatorIndex = line.indexOf("=");

        if (separatorIndex === -1) {
          return [line, ""];
        }

        return [
          line.slice(0, separatorIndex).trim(),
          line.slice(separatorIndex + 1).trim(),
        ];
      }),
  );
}

async function main() {
  if (!(await exists(examplePath))) {
    throw new Error(`Missing environment template: ${examplePath}`);
  }

  const defaults = parseEnvironment(await readFile(examplePath, "utf8"));
  const missingKeys = keys.filter((key) => !(key in defaults));

  if (missingKeys.length > 0) {
    throw new Error(
      `.env.example is missing required keys: ${missingKeys.join(", ")}`,
    );
  }

  const prompts = createInterface({
    input: process.stdin,
    output: process.stdout,
  });

  try {
    if (await exists(environmentPath)) {
      const replaceAnswer = await prompts.question(
        ".env already exists. Replace it? [y/N]: ",
      );

      if (!["y", "yes"].includes(replaceAnswer.trim().toLowerCase())) {
        console.log("Configuration cancelled. Existing .env was preserved.");
        return;
      }
    }

    const values = {};

    for (const key of keys) {
      const answer = await prompts.question(`${key} [${defaults[key]}]: `);
      values[key] = answer.trim() || defaults[key];
    }

    const content = `${keys.map((key) => `${key}=${values[key]}`).join("\n")}\n`;
    await writeFile(environmentPath, content, "utf8");
    console.log(`Created ${environmentPath}`);
  } finally {
    prompts.close();
  }
}

main().catch((error) => {
  console.error(`Configuration failed: ${error.message}`);
  process.exitCode = 1;
});
