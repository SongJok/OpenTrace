import { readFileSync, statSync } from 'node:fs'
import { resolve } from 'node:path'
import { gzipSync } from 'node:zlib'

const frontendRoot = resolve(import.meta.dirname, '..')
const distRoot = resolve(frontendRoot, 'dist')
const htmlPath = resolve(distRoot, 'index.html')
const html = readFileSync(htmlPath, 'utf8')

const assetRefs = [
  ...html.matchAll(/(?:src|href)="([^"]+)"/g),
]
  .map((match) => match[1])
  .filter((value) => value.startsWith('/assets/'))

const initialFiles = [...new Set([htmlPath, ...assetRefs.map((value) => resolve(distRoot, `.${value}`))])]
const externalRefs = [...html.matchAll(/(?:src|href)="(https?:\/\/[^"']+)"/g)].map(
  (match) => match[1],
)

let rawBytes = 0
let gzipBytes = 0
for (const file of initialFiles) {
  const content = readFileSync(file)
  rawBytes += statSync(file).size
  gzipBytes += gzipSync(content).length

  if (file.endsWith('.css')) {
    const css = content.toString('utf8')
    if (/\@import\s+(?:url\()?['"]?https?:\/\//i.test(css)) {
      throw new Error(`首屏 CSS 不能依赖远程 @import：${file}`)
    }
  }
}

const MAX_INITIAL_RAW_BYTES = 400 * 1024
const MAX_INITIAL_GZIP_BYTES = 120 * 1024

if (externalRefs.length > 0) {
  throw new Error(`首屏不能依赖外部资源：${externalRefs.join(', ')}`)
}
if (rawBytes > MAX_INITIAL_RAW_BYTES) {
  throw new Error(`首屏原始体积超标：${Math.ceil(rawBytes / 1024)} KiB`)
}
if (gzipBytes > MAX_INITIAL_GZIP_BYTES) {
  throw new Error(`首屏压缩体积超标：${Math.ceil(gzipBytes / 1024)} KiB`)
}

console.log(
  `First-load budget OK: ${initialFiles.length} files, ` +
    `${(rawBytes / 1024).toFixed(1)} KiB raw, ${(gzipBytes / 1024).toFixed(1)} KiB gzip`,
)
