import { useState, FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { apiRegister } from '../api/client'
import { t } from '../i18n'

const ALLOWED_DOMAIN = (import.meta as any).env?.VITE_REGISTRATION_ALLOWED_DOMAIN as string | undefined

export default function RegisterPage() {
  const [email, setEmail] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError('')
    setSuccess('')
    setLoading(true)
    try {
      const data = await apiRegister(email, displayName || undefined)
      setSuccess(data.message)
    } catch (err: any) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  if (success) {
    return (
      <div className="min-h-screen bg-[#212121] flex items-center justify-center px-4">
        <div className="w-full max-w-[340px] animate-fade-in text-center">
          <div className="w-10 h-10 mb-5 mx-auto rounded-full bg-[#10a37f] flex items-center justify-center">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5">
              <polyline points="20 6 9 17 4 12" />
            </svg>
          </div>
          <h1 className="text-xl font-semibold text-white mb-3">{t('register.success')}</h1>
          <button
            onClick={() => navigate('/login')}
            className="text-sm text-[#10a37f] hover:underline transition-colors mt-4"
          >
            {t('register.hasAccount')}
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-[#212121] flex items-center justify-center px-4">
      <div className="w-full max-w-[340px] animate-fade-in">
        <div className="flex flex-col items-center mb-8">
          <div className="w-10 h-10 mb-5 rounded-full bg-white flex items-center justify-center">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="black">
              <path d="M22.282 9.821a5.985 5.985 0 0 0-.516-4.91 6.046 6.046 0 0 0-6.51-2.9A6.065 6.065 0 0 0 4.981 4.18a5.985 5.985 0 0 0-3.998 2.9 6.046 6.046 0 0 0 .743 7.097 5.98 5.98 0 0 0 .51 4.911 6.051 6.051 0 0 0 6.515 2.9A5.985 5.985 0 0 0 13.26 24a6.056 6.056 0 0 0 5.772-4.206 5.99 5.99 0 0 0 3.997-2.9 6.056 6.056 0 0 0-.747-7.073zM13.26 22.43a4.476 4.476 0 0 1-2.876-1.04l.141-.081 4.779-2.758a.795.795 0 0 0 .392-.681v-6.737l2.02 1.168a.071.071 0 0 1 .038.052v5.583a4.504 4.504 0 0 1-4.494 4.494zM3.6 18.304a4.47 4.47 0 0 1-.535-3.014l.142.085 4.783 2.759a.771.771 0 0 0 .78 0l5.843-3.369v2.332a.08.08 0 0 1-.033.062L9.74 19.95a4.5 4.5 0 0 1-6.14-1.646zM2.34 7.896a4.485 4.485 0 0 1 2.366-1.973V11.6a.766.766 0 0 0 .388.676l5.815 3.355-2.02 1.168a.076.076 0 0 1-.071 0l-4.83-2.786A4.504 4.504 0 0 1 2.34 7.872zm16.597 3.855-5.833-3.387L15.119 7.2a.076.076 0 0 1 .071 0l4.83 2.791a4.494 4.494 0 0 1-.676 8.105v-5.678a.79.79 0 0 0-.407-.667zm2.01-3.023-.141-.085-4.774-2.782a.776.776 0 0 0-.785 0L9.409 9.23V6.897a.066.066 0 0 1 .028-.061l4.83-2.787a4.5 4.5 0 0 1 6.68 4.66zm-12.64 4.135-2.02-1.164a.08.08 0 0 1-.038-.057V6.075a4.5 4.5 0 0 1 7.375-3.453l-.142.08L8.704 5.46a.795.795 0 0 0-.393.681zm1.097-2.365 2.602-1.5 2.607 1.5v2.999l-2.597 1.5-2.607-1.5z"/>
            </svg>
          </div>
          <h1 className="text-2xl font-semibold text-white">{t('register.title')}</h1>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col gap-3">
          <input
            type="email"
            placeholder={t('register.email')}
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            className="w-full bg-[#2f2f2f] border border-[#3d3d3d] rounded-xl px-4 py-3 text-sm text-white placeholder-[#8e8ea0] focus:outline-none focus:border-[#10a37f] transition-colors"
          />
          <input
            type="text"
            placeholder={t('register.displayName')}
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            className="w-full bg-[#2f2f2f] border border-[#3d3d3d] rounded-xl px-4 py-3 text-sm text-white placeholder-[#8e8ea0] focus:outline-none focus:border-[#10a37f] transition-colors"
          />
          <p className="text-xs text-[#8e8ea0]">{ALLOWED_DOMAIN ? t('register.emailDomainHint', { domain: ALLOWED_DOMAIN }) : ''}</p>

          {error && (
            <p className="text-red-400 text-xs text-center">{error}</p>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full bg-white hover:bg-gray-100 text-black font-medium rounded-xl py-3 text-sm transition-colors disabled:opacity-50 mt-1"
          >
            {loading ? t('register.submitting') : t('register.submit')}
          </button>
        </form>

        <p className="text-center mt-5">
          <button
            onClick={() => navigate('/login')}
            className="text-sm text-[#8e8ea0] hover:text-[#10a37f] transition-colors"
          >
            {t('register.hasAccount')}
          </button>
        </p>
      </div>
    </div>
  )
}
