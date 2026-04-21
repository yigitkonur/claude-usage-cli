import { readdirSync, readFileSync, existsSync } from 'fs';
import { join } from 'path';
import os from 'os';

const CANDIDATE_DIRS = [
  '~/scripts',
  '~/Scripts',
  '~/Documents/Raycast Scripts',
  '~/Documents/raycast-scripts',
  '~/Documents/scripts',
  '~/Desktop/Raycast Scripts',
  '~/.local/scripts',
  '~/bin',
];

/**
 * Scan well-known locations for directories that look like Raycast script folders.
 * Returns array sorted by confidence (highest first).
 *
 * @returns {Array<{ path: string, score: number, hint: string }>}
 */
export function detectRaycastDirs() {
  const home = os.homedir();
  const seen = new Set();
  const results = [];

  for (const raw of CANDIDATE_DIRS) {
    const dir = raw.replace('~', home);
    if (seen.has(dir) || !existsSync(dir)) continue;
    seen.add(dir);

    const { score, hint } = scoreDir(dir);
    results.push({ path: dir, score, hint });
  }

  return results.sort((a, b) => b.score - a.score);
}

/**
 * Score a directory by how likely it is to be a Raycast scripts folder.
 */
export function scoreDir(dir) {
  let score = 1;
  let hint = 'directory exists';

  try {
    const entries = readdirSync(dir);
    const scriptFiles = entries.filter(f => /\.(py|sh|swift|rb|js)$/.test(f));

    // Existing claude-usage installation is the strongest signal
    if (entries.includes('claude-usage.py')) {
      score += 30;
      hint = 'existing claude-usage installation';
      return { score, hint };
    }

    for (const f of scriptFiles) {
      try {
        const content = readFileSync(join(dir, f), 'utf8');
        if (content.includes('@raycast.schemaVersion')) {
          score += 15;
          hint = `contains Raycast scripts (${scriptFiles.length} file${scriptFiles.length !== 1 ? 's' : ''})`;
          break;
        }
      } catch {
        // unreadable file — skip
      }
    }

    if (scriptFiles.length > 0 && score === 1) {
      score += 3;
      hint = `contains ${scriptFiles.length} script file${scriptFiles.length !== 1 ? 's' : ''}`;
    }
  } catch {
    // unreadable dir
  }

  return { score, hint };
}
