import { afterEach, describe, expect, it } from 'vitest'

import { applyTheme, useThemeStore } from '../theme'

describe('theme contrast contract', () => {
  afterEach(() => {
    applyTheme('dark', 'warm')
    document.documentElement.removeAttribute('data-theme')
    document.documentElement.removeAttribute('data-accent')
  })

  it('uses the soft white palette as the product default', () => {
    expect(useThemeStore.getState().mode).toBe('light')
    expect(useThemeStore.getState().accent).toBe('white')
  })

  it('does not let the accent choice override the selected theme', () => {
    applyTheme('dark', 'white')
    expect(document.documentElement.dataset.theme).toBe('dark')
    expect(document.documentElement.dataset.accent).toBe('white')

    applyTheme('light', 'black')
    expect(document.documentElement.dataset.theme).toBe('light')
    expect(document.documentElement.dataset.accent).toBe('black')
  })
})
