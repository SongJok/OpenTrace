import zh from './zh'

type Dict = typeof zh

const dict: Dict = zh

export function t(path: string, replacements?: Record<string, string>): string {
  const parts = path.split('.')
  let cur: any = dict
  for (const p of parts) {
    cur = cur?.[p]
    if (cur == null) return path
  }
  let result = typeof cur === 'string' ? cur : path
  if (replacements) {
    for (const [key, value] of Object.entries(replacements)) {
      result = result.replace(`{${key}}`, value)
    }
  }
  return result
}

export { zh }
