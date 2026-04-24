import zh from './zh'

type Dict = typeof zh

const dict: Dict = zh

export function t(path: string): string {
  const parts = path.split('.')
  let cur: any = dict
  for (const p of parts) {
    cur = cur?.[p]
    if (cur == null) return path
  }
  return typeof cur === 'string' ? cur : path
}

export { zh }
