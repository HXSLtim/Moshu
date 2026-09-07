import { spawnSync } from 'node:child_process'
import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const packageDir = fileURLToPath(new URL('..', import.meta.url))
const profileName = process.env.DSH_PROFILE ?? 'web'
const dshHome = process.env.DSH_HOME ?? join(homedir(), '.dsh')
const profileDir = join(dshHome, 'profiles', profileName)

function run(command, args, cwd) {
  const result = spawnSync(command, args, { cwd, stdio: 'inherit', env: process.env })
  if (result.error) throw result.error
  if (result.status !== 0) process.exit(result.status ?? 1)
}

// 安装失败即退出，包括依赖构建审批失败；不能继续修改 profile 并报告成功。
run('dsh', ['plugin', '--profile', profileName, 'add', packageDir])
// Cordis 从 profile 根解析插件实现，因此同时显式安装底层包。
run('pnpm', ['add', 'dsh-tdai-memory@0.2.7'], profileDir)

const profileManifestFile = join(profileDir, 'package.json')
if (existsSync(profileManifestFile)) {
  const manifest = JSON.parse(readFileSync(profileManifestFile, 'utf8'))
  const bundles = manifest.dsh?.profile?.bundles ?? []
  const nextBundles = bundles.filter((name) => name !== 'dsh-nai')
  if (nextBundles.length !== bundles.length) {
    manifest.dsh.profile.bundles = nextBundles
    writeFileSync(profileManifestFile, `${JSON.stringify(manifest, null, 2)}\n`)
  }
}
console.log(`已安装 dsh-nai-memory 与 dsh-tdai-memory 到 ${profileDir}`)
