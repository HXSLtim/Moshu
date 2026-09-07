import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, statSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const script = fileURLToPath(new URL('../scripts/configure-local-token.mjs', import.meta.url))
for (const value of ['"test.header.signature"', "!!js process.env.NAI_TOKEN ?? ''"]) {
  test(`令牌同步限定插件并保留 YAML 值：${value.startsWith('!!') ? '环境变量' : '引号'}`, () => {
    const dshHome = mkdtempSync(join(tmpdir(), 'nai-config-test-'))
    try {
      const profile = join(dshHome, 'profiles/web')
      const preset = join(dshHome, '.agent-presets/nai-author')
      mkdirSync(profile, { recursive: true })
      mkdirSync(preset, { recursive: true })
      writeFileSync(join(profile, 'cordis.patch.yml'), `- id: other\n  config:\n    token: wrong\n- id: nai-ui\n  config:\n    token: ${value}\n`)
      const target = join(preset, 'agent.cordis.yml')
      writeFileSync(target, '- id: other\n  config:\n    token: unchanged\n- id: nai\n  config:\n    token: old\n')
      for (let attempt = 0; attempt < 2; attempt += 1) {
        const result = spawnSync(process.execPath, [script], { env: { ...process.env, DSH_HOME: dshHome, DSH_PROFILE: 'web' }, encoding: 'utf8' })
        assert.equal(result.status, 0, result.stderr)
        assert.ok(!result.stdout.includes('test.header.signature'))
      }
      const text = readFileSync(target, 'utf8')
      assert.ok(text.includes(`    token: ${value}`))
      assert.ok(text.includes('    token: unchanged'))
      assert.equal(statSync(target).mode & 0o777, 0o600)
    } finally {
      rmSync(dshHome, { recursive: true, force: true })
    }
  })
}
