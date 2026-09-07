import { readFile, writeFile, chmod } from 'node:fs/promises'
import { homedir } from 'node:os'
import { join } from 'node:path'

// 只读取指定插件行，保留 YAML 引号和环境变量表达式，不执行配置代码。
function tokenLine(text, id) {
  const lines = text.split(/\r?\n/)
  const start = lines.findIndex((line) => line.trim() === `- id: ${id}`)
  if (start < 0) throw new Error(`未找到 ${id} 插件行`)
  for (let index = start + 1; index < lines.length; index += 1) {
    if (/^-\s/.test(lines[index])) break
    const match = lines[index].match(/^(\s+)token:[ \t]*(\S.*)$/)
    if (match) return { lines, index, indent: match[1], value: match[2] }
  }
  throw new Error(`未在 ${id} 插件中找到 token 配置`)
}

const dshHome = process.env.DSH_HOME ?? join(homedir(), '.dsh')
const profileName = process.env.DSH_PROFILE ?? 'web'
const profilePatch = join(dshHome, 'profiles', profileName, 'cordis.patch.yml')
const presetFile = join(dshHome, '.agent-presets/nai-author/agent.cordis.yml')
const source = tokenLine(await readFile(profilePatch, 'utf8'), 'nai-ui')
const target = tokenLine(await readFile(presetFile, 'utf8'), 'nai')
target.lines[target.index] = `${target.indent}token: ${source.value}`

// 先收紧已有文件权限，再写入凭据；重复运行也应成功。
await chmod(presetFile, 0o600)
await writeFile(presetFile, target.lines.join('\n'), { encoding: 'utf8', mode: 0o600 })
console.log(`已同步本地 preset token：${presetFile}`)
