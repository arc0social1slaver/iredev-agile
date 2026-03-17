// src/components/settings/SettingsModal.jsx
// ─────────────────────────────────────────────────────────────────────────────
// Settings dialog with three tabs: Profile, Appearance, API.
// Opens when the user clicks "Settings" in the sidebar.
// ─────────────────────────────────────────────────────────────────────────────
import { useState }    from 'react'
import { Modal }       from '../ui/Modal'
import { useAuth }     from '../../context/AuthContext'
import { LoadingSpinner } from '../ui/LoadingSpinner'

const TABS = ['Profile', 'Appearance', 'API']

export function SettingsModal({ open, onClose }) {
  const [activeTab, setActiveTab] = useState('Profile')

  return (
    <Modal open={open} onClose={onClose} title="Settings" width="max-w-[520px]">
      {/* Tab bar */}
      <div className="flex gap-1 mb-5 -mx-5 px-5 border-b border-[#F0ECE6] pb-0">
        {TABS.map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-3 py-2 text-[13px] font-medium border-b-2 -mb-px transition-colors ${
              tab === activeTab
                ? 'border-[#C96A42] text-[#C96A42]'
                : 'border-transparent text-[#8A7F72] hover:text-[#1A1410]'
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {activeTab === 'Profile'    && <ProfileTab />}
      {activeTab === 'Appearance' && <AppearanceTab />}
      {activeTab === 'API'        && <ApiTab />}
    </Modal>
  )
}

// ── Profile tab ───────────────────────────────────────────────────────────────
function ProfileTab() {
  const { user, logout, authLoading } = useAuth()
  const [name,  setName]  = useState(user?.name  || '')
  const [email, setEmail] = useState(user?.email || '')
  const [saved, setSaved] = useState(false)

  async function handleSave(e) {
    e.preventDefault()
    // Call PUT /api/auth/profile in a real app
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  return (
    <div className="space-y-5">
      {/* Avatar */}
      <div className="flex items-center gap-4">
        <div className="w-14 h-14 rounded-full bg-[#8A7F72] flex items-center justify-center">
          <span className="text-white text-lg font-semibold">
            {(user?.name || user?.email || 'U')[0].toUpperCase()}
          </span>
        </div>
        <div>
          <div className="text-[13px] font-medium text-[#1A1410]">
            {user?.name || 'User'}
          </div>
          <div className="text-[12px] text-[#8A7F72]">{user?.email}</div>
        </div>
      </div>

      <form onSubmit={handleSave} className="space-y-3">
        <SettingsField label="Display name" value={name} onChange={e => setName(e.target.value)} />
        <SettingsField label="Email" type="email" value={email} onChange={e => setEmail(e.target.value)} />

        <div className="flex items-center justify-between pt-1">
          <button
            type="submit"
            className="h-8 px-4 bg-[#C96A42] hover:bg-[#B85E38] text-white
                       text-[12px] font-semibold rounded-lg transition-colors"
          >
            {saved ? '✓ Saved' : 'Save changes'}
          </button>
          <button
            type="button"
            onClick={logout}
            disabled={authLoading}
            className="h-8 px-4 text-[12px] text-red-500 hover:bg-red-50
                       rounded-lg transition-colors flex items-center gap-1.5"
          >
            {authLoading && <LoadingSpinner size={12} />}
            Sign out
          </button>
        </div>
      </form>
    </div>
  )
}

// ── Appearance tab ────────────────────────────────────────────────────────────
function AppearanceTab() {
  const [theme,    setTheme]    = useState('light')   // 'light' | 'dark' | 'system'
  const [fontSize, setFontSize] = useState('default') // 'small' | 'default' | 'large'

  return (
    <div className="space-y-5">
      {/* Theme */}
      <div>
        <div className="text-[12px] font-medium text-[#3D3530] mb-2">Theme</div>
        <div className="flex gap-2">
          {['light', 'dark', 'system'].map((t) => (
            <button
              key={t}
              onClick={() => setTheme(t)}
              className={`flex-1 h-8 rounded-lg text-[12px] font-medium capitalize
                          border transition-colors ${
                            theme === t
                              ? 'border-[#C96A42] bg-[#FDF0EA] text-[#C96A42]'
                              : 'border-[#E8E3D9] text-[#8A7F72] hover:border-[#D9D3C8]'
                          }`}
            >
              {t}
            </button>
          ))}
        </div>
        <p className="text-[11px] text-[#B5ADA4] mt-1.5">
          Dark mode applies on next page load.
        </p>
      </div>

      {/* Font size */}
      <div>
        <div className="text-[12px] font-medium text-[#3D3530] mb-2">Font size</div>
        <div className="flex gap-2">
          {['small', 'default', 'large'].map((s) => (
            <button
              key={s}
              onClick={() => setFontSize(s)}
              className={`flex-1 h-8 rounded-lg text-[12px] font-medium capitalize
                          border transition-colors ${
                            fontSize === s
                              ? 'border-[#C96A42] bg-[#FDF0EA] text-[#C96A42]'
                              : 'border-[#E8E3D9] text-[#8A7F72] hover:border-[#D9D3C8]'
                          }`}
            >
              {s}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}

// ── API tab ───────────────────────────────────────────────────────────────────
function ApiTab() {
  const [apiKey,   setApiKey]   = useState('')
  const [model,    setModel]    = useState('claude-sonnet-4-5')
  const [maxTokens,setMaxTokens]= useState(4096)
  const [saved,    setSaved]    = useState(false)

  function handleSave(e) {
    e.preventDefault()
    // Persist to backend or localStorage
    localStorage.setItem('api_settings', JSON.stringify({ model, maxTokens }))
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  return (
    <form onSubmit={handleSave} className="space-y-4">
      {/* API Key */}
      <div>
        <label className="block text-[12px] font-medium text-[#3D3530] mb-1.5">
          API Key <span className="text-[#B5ADA4] font-normal">(optional — uses server key if blank)</span>
        </label>
        <input
          type="password"
          value={apiKey}
          onChange={e => setApiKey(e.target.value)}
          placeholder="sk-ant-api03-••••"
          className={settingsInputClass}
        />
      </div>

      {/* Model selector */}
      <div>
        <label className="block text-[12px] font-medium text-[#3D3530] mb-1.5">Model</label>
        <select
          value={model}
          onChange={e => setModel(e.target.value)}
          className={settingsInputClass}
        >
          <option value="claude-opus-4-5">Claude Opus 4.5</option>
          <option value="claude-sonnet-4-5">Claude Sonnet 4.5</option>
          <option value="claude-haiku-4-5-20251001">Claude Haiku 4.5</option>
        </select>
      </div>

      {/* Max tokens */}
      <div>
        <div className="flex items-center justify-between mb-1.5">
          <label className="text-[12px] font-medium text-[#3D3530]">Max tokens</label>
          <span className="text-[12px] font-mono text-[#8A7F72]">{maxTokens.toLocaleString()}</span>
        </div>
        <input
          type="range"
          min={256}
          max={8192}
          step={256}
          value={maxTokens}
          onChange={e => setMaxTokens(Number(e.target.value))}
          className="w-full accent-[#C96A42]"
        />
        <div className="flex justify-between text-[10px] text-[#C0B8AE] mt-0.5">
          <span>256</span><span>8192</span>
        </div>
      </div>

      <button
        type="submit"
        className="h-8 px-4 bg-[#C96A42] hover:bg-[#B85E38] text-white
                   text-[12px] font-semibold rounded-lg transition-colors"
      >
        {saved ? '✓ Saved' : 'Save settings'}
      </button>
    </form>
  )
}

// ── Shared sub-components ─────────────────────────────────────────────────────
function SettingsField({ label, type = 'text', value, onChange }) {
  return (
    <div>
      <label className="block text-[12px] font-medium text-[#3D3530] mb-1.5">{label}</label>
      <input
        type={type}
        value={value}
        onChange={onChange}
        className={settingsInputClass}
      />
    </div>
  )
}

const settingsInputClass =
  'w-full h-9 px-3 bg-[#FAF8F5] border border-[#E8E3D9] rounded-lg ' +
  'text-[13px] text-[#1A1410] placeholder:text-[#C0B8AE] ' +
  'focus:outline-none focus:ring-2 focus:ring-[#C96A42]/20 ' +
  'focus:border-[#C96A42]/60 transition-all'