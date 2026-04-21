#!/usr/bin/env node
import { fileURLToPath } from 'url';
import { dirname, join, resolve } from 'path';
import {
  readFileSync, existsSync, copyFileSync, chmodSync, mkdirSync, accessSync, constants,
} from 'fs';
import { spawnSync } from 'child_process';
import os from 'os';

import {
  intro, outro, text, password, select, confirm,
  spinner, note, cancel, isCancel, log,
} from '@clack/prompts';
import pc from 'picocolors';

import { checkPrereqs } from '../src/prereqs.js';
import { detectRaycastDirs } from '../src/raycast.js';

// ── Paths ──────────────────────────────────────────────────────────────────────
const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const ROOT = join(__dirname, '..');
const pkg = JSON.parse(readFileSync(join(ROOT, 'package.json'), 'utf8'));
const SCRIPT_ASSET = join(ROOT, 'assets', 'claude-usage.py');
const STATE_FILE = join(os.homedir(), '.config', 'claude-usage', 'state.json');
const PLIST_FILE = join(
  os.homedir(), 'Library', 'LaunchAgents', 'com.yigitkonur.claude-usage.plist',
);

// ── Entry ──────────────────────────────────────────────────────────────────────
async function main() {
  const [cmd] = process.argv.slice(2);

  console.log();
  intro(
    `${pc.bold('claude-usage')}  ${pc.dim(`v${pkg.version}`)}  ` +
    pc.dim('Claude.ai usage tracker for Raycast'),
  );

  switch (cmd) {
    case 'update':
    case '--update':
      await cmdUpdate();
      break;
    case 'help':
    case '--help':
    case '-h':
      cmdHelp();
      break;
    default:
      await cmdInstall();
  }
}

// ── Install ────────────────────────────────────────────────────────────────────
async function cmdInstall() {
  // ── Step 1: Prerequisites ──
  const s = spinner();
  s.start('Checking prerequisites');
  const prereqs = checkPrereqs();

  if (!prereqs.uv) {
    s.stop(pc.red('✗  uv not found'));
    note(
      [
        'uv is required to run the Python script.',
        '',
        `${pc.bold('Install it:')}`,
        pc.cyan('  curl -LsSf https://astral.sh/uv/install.sh | sh'),
        pc.dim('  (or: brew install uv)'),
        '',
        'Then re-run this installer.',
      ].join('\n'),
      'Missing prerequisite',
    );
    process.exit(1);
  }

  if (!prereqs.python312) {
    s.stop(`${pc.green('✓')}  uv ${prereqs.uvVersion}   ${pc.yellow('⚠  Python 3.12 not installed')}`);
    const go = await confirm({ message: 'Install Python 3.12 via uv?' });
    if (isCancel(go) || !go) { cancel('Aborted.'); process.exit(1); }

    const ps = spinner();
    ps.start('Installing Python 3.12 (first run may take ~30 s)');
    const res = spawnSync('uv', ['python', 'install', '3.12'], { encoding: 'utf8', timeout: 120_000 });
    if (res.status !== 0) {
      ps.stop(pc.red(`Failed: ${(res.stderr || '').split('\n')[0]}`));
      process.exit(1);
    }
    ps.stop(`${pc.green('✓')}  Python 3.12 installed`);
  } else {
    s.stop(
      `${pc.green('✓')}  uv ${prereqs.uvVersion}   ${pc.green('✓')}  Python 3.12`,
    );
  }

  // ── Step 2: Raycast scripts folder ──
  const candidates = detectRaycastDirs();
  let scriptDir;

  if (candidates.length > 0) {
    const options = [
      ...candidates.map(d => ({
        value: d.path,
        label: d.path.replace(os.homedir(), '~'),
        hint: d.hint,
      })),
      { value: '__custom', label: 'Enter a custom path…' },
    ];

    const chosen = await select({
      message: 'Where is your Raycast scripts folder?',
      options,
    });
    if (isCancel(chosen)) { cancel(); process.exit(0); }

    scriptDir = chosen === '__custom' ? await promptCustomDir() : chosen;
  } else {
    note(
      [
        "Couldn't auto-detect your Raycast scripts folder.",
        '',
        pc.bold('Find it:'),
        '  Raycast → Settings (⌘,) → Extensions → Script Commands',
        '  → the folder icon next to any script directory',
      ].join('\n'),
      'Manual setup',
    );
    scriptDir = await promptCustomDir();
  }

  if (!scriptDir) { cancel(); process.exit(0); }

  // ── Step 3: Install / update script ──
  const dest = join(scriptDir, 'claude-usage.py');
  const isUpdate = existsSync(dest);
  const is = spinner();
  is.start(isUpdate ? 'Updating claude-usage.py' : 'Installing claude-usage.py');

  try {
    mkdirSync(scriptDir, { recursive: true });
    copyFileSync(SCRIPT_ASSET, dest);
    chmodSync(dest, 0o755);
    is.stop(
      `${pc.green('✓')}  ${isUpdate ? 'Updated' : 'Installed'}  →  ` +
      pc.cyan(dest.replace(os.homedir(), '~')),
    );
  } catch (err) {
    is.stop(pc.red(`Install failed: ${err.message}`));
    process.exit(1);
  }

  // ── Step 4: Accounts ──
  const isFirstInstall = !existsSync(STATE_FILE);

  if (isFirstInstall) {
    note(
      [
        'Add your first Claude account.',
        '',
        pc.bold('How to get a session key:'),
        `  1. Open ${pc.cyan('claude.ai')} in Chrome · sign in`,
        '  2. Open DevTools  ⌘ + Option + I',
        '  3. Application tab  →  Storage  →  Cookies  →  https://claude.ai',
        `  4. Find ${pc.bold('sessionKey')}  →  copy the value`,
        pc.dim(`     (it starts with sk-ant-sid02-)`),
      ].join('\n'),
      'Account setup',
    );
    await addAccountLoop(dest, prereqs.uvPath);
  } else {
    const addNow = await confirm({ message: 'Add or update a Claude account now?' });
    if (!isCancel(addNow) && addNow) {
      await addAccountLoop(dest, prereqs.uvPath);
    } else {
      log.info(
        'Run later:  ' +
        pc.cyan(`uv run --python 3.12 --script ${dest.replace(os.homedir(), '~')} add <label> <key>`),
      );
    }
  }

  // ── Step 5: LaunchAgent ──
  await installAgentStep(dest, prereqs.uvPath);

  doOutro(dest);
}

// ── Update ─────────────────────────────────────────────────────────────────────
async function cmdUpdate() {
  const s = spinner();
  s.start('Locating existing installations');

  const found = detectRaycastDirs()
    .map(d => join(d.path, 'claude-usage.py'))
    .filter(p => existsSync(p));

  s.stop(found.length ? `Found ${found.length} installation(s)` : 'No existing installations found');

  if (found.length === 0) {
    const run = await confirm({ message: 'Run full installer instead?' });
    if (!isCancel(run) && run) await cmdInstall();
    else cancel('Nothing to update.');
    return;
  }

  for (const dest of found) {
    try {
      copyFileSync(SCRIPT_ASSET, dest);
      chmodSync(dest, 0o755);
      log.success('Updated  ' + pc.cyan(dest.replace(os.homedir(), '~')));
    } catch (err) {
      log.error(`Failed to update ${dest}: ${err.message}`);
    }
  }

  outro(`${pc.green('✓')}  Script updated. Your accounts and config at ${pc.dim('~/.config/claude-usage/')} are untouched.`);
}

// ── Help ───────────────────────────────────────────────────────────────────────
function cmdHelp() {
  outro(
    [
      '',
      `  ${pc.bold('npx claude-usage')}          Interactive installer`,
      `  ${pc.bold('npx claude-usage update')}   Update script in place`,
      `  ${pc.bold('npx claude-usage help')}     Show this help`,
      '',
      `  ${pc.dim('After installing, manage accounts with the Python script directly:')}`,
      `  ${pc.cyan(`uv run --python 3.12 --script ~/scripts/claude-usage.py --help`)}`,
    ].join('\n'),
  );
}

// ── Shared helpers ─────────────────────────────────────────────────────────────
async function promptCustomDir() {
  const val = await text({
    message: 'Raycast scripts folder path',
    placeholder: `${os.homedir()}/scripts`,
    validate: (v) => {
      if (!v.trim()) return 'Path is required';
      const p = resolve(v.replace(/^~/, os.homedir()));
      if (!existsSync(p)) return `Not found: ${p}`;
      try { accessSync(p, constants.W_OK); } catch { return `No write permission: ${p}`; }
    },
  });
  if (isCancel(val)) return null;
  return resolve(val.replace(/^~/, os.homedir()));
}

async function addAccountLoop(dest, uvPath) {
  let adding = true;
  while (adding) {
    const label = await text({
      message: 'Account label  (e.g. work, personal)',
      validate: (v) => (!v.trim() ? 'Required' : undefined),
    });
    if (isCancel(label)) break;

    const key = await password({
      message: 'Session key  (sk-ant-sid02-…)',
      mask: '•',
      validate: (v) => {
        if (!v.trim()) return 'Required';
        if (!v.trim().startsWith('sk-ant-')) return 'Must start with sk-ant-';
      },
    });
    if (isCancel(key)) break;

    const as = spinner();
    as.start(`Verifying "${label.trim()}"…`);

    const res = spawnSync(
      uvPath,
      ['run', '--python', '3.12', '--script', dest, 'add', label.trim(), key.trim()],
      { encoding: 'utf8', timeout: 30_000 },
    );

    if (res.status === 0) {
      as.stop(`${pc.green('✓')}  ${(res.stdout || '').trim()}`);
    } else {
      const msg = ((res.stdout || '') + (res.stderr || '')).trim();
      as.stop(`${pc.red('✗')}  ${msg || 'Unknown error'}`);
    }

    const more = await confirm({ message: 'Add another account?' });
    adding = !isCancel(more) && more;
  }
}

async function installAgentStep(dest, uvPath) {
  const go = await confirm({
    message: 'Install background auto-refresh agent?',
    initialValue: true,
  });
  if (isCancel(go) || !go) return;

  const as = spinner();
  as.start('Installing LaunchAgent');

  const res = spawnSync(
    uvPath,
    ['run', '--python', '3.12', '--script', dest, 'agent', 'install'],
    { encoding: 'utf8' },
  );

  if (res.status === 0) {
    as.stop(`${pc.green('✓')}  LaunchAgent installed  (refreshes every 60 s)`);
    spawnSync('launchctl', ['unload', PLIST_FILE], { stdio: 'ignore' });
    const loadRes = spawnSync('launchctl', ['load', PLIST_FILE], { encoding: 'utf8' });
    if (loadRes.status !== 0) {
      log.warn(`launchctl load failed: ${(loadRes.stderr || '').trim() || 'unknown error'}`);
      log.info(`Start manually: launchctl load ${PLIST_FILE}`);
    }
  } else {
    as.stop(
      `${pc.yellow('⚠')}  Could not install agent automatically.  ` +
      `Run manually: ${pc.dim(dest.replace(os.homedir(), '~') + ' agent install')}`,
    );
  }
}

function doOutro(dest) {
  const short = dest.replace(os.homedir(), '~');
  outro(
    [
      pc.bold(pc.green('All done!')),
      '',
      `  ${pc.bold('Raycast')}    Open Raycast  →  search ${pc.bold('"CC"')}`,
      `  ${pc.bold('Dashboard')}  Script opens the HTML dashboard on every refresh`,
      `  ${pc.bold('Update')}     ${pc.dim('npx claude-usage update')}`,
      '',
      pc.dim(`  Script at: ${short}`),
    ].join('\n'),
  );
}

main().catch((err) => {
  console.error(pc.red(`\n  Error: ${err.message}`));
  process.exit(1);
});
