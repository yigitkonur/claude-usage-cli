import { execSync } from 'child_process';

/**
 * @returns {{ uv: boolean, uvVersion: string|null, uvPath: string|null, python312: boolean }}
 */
export function checkPrereqs() {
  const result = { uv: false, uvVersion: null, uvPath: null, python312: false };

  try {
    const out = execSync('uv --version', { encoding: 'utf8', stdio: 'pipe' }).trim();
    result.uv = true;
    result.uvVersion = out.replace(/^uv\s+/, '');
    result.uvPath = execSync('which uv', { encoding: 'utf8', stdio: 'pipe' }).trim();
  } catch {
    return result;
  }

  try {
    execSync('uv python find 3.12', { encoding: 'utf8', stdio: 'pipe' });
    result.python312 = true;
  } catch {
    result.python312 = false;
  }

  return result;
}
