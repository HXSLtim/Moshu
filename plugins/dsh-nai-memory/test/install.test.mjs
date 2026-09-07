import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const script = fileURLToPath(new URL('../scripts/install-profile.mjs', import.meta.url))
for (const [label, firstExit, secondExit] of [['首步失败', 7, 0], ['次步失败', 0, 8], ['安装成功', 0, 0]]) {
  test(`记忆插件安装：${label}`, () => {
    const root = mkdtempSync(join(tmpdir(), 'nai-install-test-'))
    try {
      const bin = join(root, 'bin')
      const profile = join(root, 'profiles/web')
      mkdirSync(bin)
      mkdirSync(profile, { recursive: true })
      for (const [command, code] of [['dsh', firstExit], ['pnpm', secondExit]]) {
        writeFileSync(join(bin, command), `#!/bin/sh\nexit ${code}\n`, { mode: 0o755 })
      }
      const manifestFile = join(profile, 'package.json')
      const manifest = { dsh: { profile: { bundles: ['dsh-nai', 'dsh-nai-ui', 'dsh-nai-memory'] } } }
      writeFileSync(manifestFile, JSON.stringify(manifest))
      const result = spawnSync(process.execPath, [script], {
        env: { ...process.env, DSH_HOME: root, DSH_PROFILE: 'web', PATH: `${bin}:${process.env.PATH}` }, encoding: 'utf8',
      })
      assert.equal(result.status, firstExit || secondExit, result.stderr)
      const bundles = JSON.parse(readFileSync(manifestFile, 'utf8')).dsh.profile.bundles
      if (firstExit || secondExit) {
        assert.deepEqual(bundles, manifest.dsh.profile.bundles)
        assert.ok(!result.stdout.includes('已安装'))
      } else {
        assert.deepEqual(bundles, ['dsh-nai-ui', 'dsh-nai-memory'])
      }
    } finally {
      rmSync(root, { recursive: true, force: true })
    }
  })
}
