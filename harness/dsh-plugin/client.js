/* DSH's documented lazy client-module factory; no build-time runtime copy. */
globalThis.__ModuleLoader__.load({
  id: '@qfh/dsh-data',
  factory(require) {
    const React = require('react')
    const { createElement: h, useEffect, useState, useCallback } = React
    const refs = ['QFH_IFIND_CREDENTIAL', 'QFH_RQDATA_LICENSE']
    const fieldStyle = { width: '100%', border: '1px solid #aaa', borderRadius: 6,
      padding: '9px 12px', background: 'transparent', color: 'inherit', boxSizing: 'border-box' }
    // Native option popups do not consistently inherit the page's dark background.
    // Pair system foreground/background colors on both the control and its options.
    const selectStyle = { ...fieldStyle, colorScheme: 'light dark', background: 'Canvas', color: 'CanvasText' }
    const optionStyle = { background: 'Canvas', color: 'CanvasText', colorScheme: 'light dark' }
    const buttonStyle = { ...fieldStyle, width: 'auto', cursor: 'pointer' }

    function CredentialForm({ provider, configured, operations, refresh }) {
      const [value, setValue] = useState('')
      const [method, setMethod] = useState('refresh_token')
      const [busy, setBusy] = useState(false)
      const [message, setMessage] = useState('')
      const ref = provider === 'ifind' ? refs[0] : refs[1]
      const label = provider === 'ifind' ? 'iFind' : 'RQData'
      async function save(event) {
        event.preventDefault()
        if (!value.trim() || busy) return
        setBusy(true); setMessage('')
        try {
          await operations.save(ref, provider === 'ifind' ? JSON.stringify({ [method]: value.trim() }) : value.trim())
          setValue('')
          await refresh()
          setMessage('Saved locally. No provider request was sent.')
        } catch { setMessage('Could not save. Check the local DSH connection and try again.') }
        finally { setBusy(false) }
      }
      async function remove() {
        setBusy(true); setMessage(''); setValue('')
        try { await operations.remove(ref); await refresh(); setMessage('Credential removed locally.') }
        catch { setMessage('Could not remove the credential. Please retry.') }
        finally { setBusy(false) }
      }
      return h('form', { onSubmit: save, 'aria-label': label + ' credentials',
        style: { display: 'grid', gap: 12, border: '1px solid #bbb', borderRadius: 10, padding: 20 } },
        h('h3', { style: { margin: 0 } }, label + ' credentials'),
        h('p', { role: 'status', style: { margin: 0 } }, configured ? 'Configured' : 'Not configured'),
        provider === 'ifind' ? h('label', null, 'Token type',
          h('select', { 'aria-label': 'iFind token type', value: method, disabled: busy,
            onChange: event => setMethod(event.target.value), style: selectStyle },
            h('option', { value: 'refresh_token', style: optionStyle }, 'Refresh token'),
            h('option', { value: 'access_token', style: optionStyle }, 'Access token'))) : null,
        h('label', null, label + (provider === 'ifind' ? ' token' : ' license'),
          h('input', { type: 'password', 'aria-label': label + ' credential', value,
            autoComplete: 'off', spellCheck: false, disabled: busy, style: fieldStyle,
            onChange: event => setValue(event.target.value) })),
        h('div', { style: { display: 'flex', gap: 10, flexWrap: 'wrap' } },
          h('button', { type: 'submit', disabled: busy || !value.trim(),
            style: buttonStyle }, 'Save ' + label),
          h('button', { type: 'button', onClick: remove, disabled: busy || !configured,
            style: buttonStyle }, 'Remove ' + label)),
        message ? h('p', { role: 'status', style: { margin: 0 } }, message) : null)
    }

    function DataSettings({ operations }) {
      const [state, setState] = useState(null)
      const [error, setError] = useState('')
      const [busy, setBusy] = useState(false)
      const refresh = useCallback(async () => {
        const next = await operations.read()
        setState(next)
        setError('')
      }, [operations])
      useEffect(() => {
        let active = true
        operations.read().then(next => { if (active) setState(next) })
          .catch(() => { if (active) setError('Could not load data settings.') })
        return () => { active = false }
      }, [operations])
      async function select(provider) {
        if (!state || busy) return
        setBusy(true)
        try { await operations.select(provider, state.revision); await refresh() }
        catch { setError('Could not change source. Refresh settings before retrying.') }
        finally { setBusy(false) }
      }
      return h('section', { 'aria-label': 'Research data settings',
        style: { display: 'grid', gap: 20, maxWidth: 640, minWidth: 0, padding: '0 4px' } },
        h('h2', { style: { margin: 0 } }, 'Research data'),
        h('p', { style: { margin: 0 } },
          'Daily China A shares. Each research session uses one data source. Saving credentials makes no provider request.'),
        error ? h('p', { role: 'alert' }, error) : null,
        !state ? h('p', null, 'Loading settings…') : h(React.Fragment, null,
          h('label', null, 'Active data source',
            h('select', { 'aria-label': 'Active data source', value: state.provider, disabled: busy || state.researchMode,
              onChange: event => { void select(event.target.value) }, style: selectStyle },
              h('option', { value: 'baostock', style: optionStyle }, 'BaoStock — free testing'),
              h('option', { value: 'ifind', style: optionStyle }, 'iFind'),
              h('option', { value: 'rqdata', style: optionStyle }, 'RiceQuant RQData'))),
          h('p', { style: { margin: 0, fontSize: 13 } },
            state.researchMode
              ? 'Interactive trial: BaoStock is pinned. Start a new chat, describe a research idea, and keep Use Agent Teams enabled. One supervisor and two workers will produce a cited draft.'
              : 'Change source before starting a new session. An existing session refuses source changes.'),
          h('div', { style: { border: '1px solid #bbb', borderRadius: 10, padding: 20 } },
            h('h3', { style: { margin: '0 0 8px' } }, 'BaoStock free testing'),
            h('p', { style: { margin: 0 } },
              'Ready without an account or token. Daily close prices only. Reports and news are unavailable from this adapter.')),
          h(CredentialForm, { provider: 'ifind', configured: state.credentials[refs[0]]?.configured,
            operations, refresh }),
          h(CredentialForm, { provider: 'rqdata', configured: state.credentials[refs[1]]?.configured,
            operations, refresh }),
          h('p', { style: { margin: 0, fontSize: 13 } },
            state.researchMode
              ? (globalThis.__QFH_RESEARCH_PROFILE__?.sampleDescription || 'The research scope tool identifies this session’s frozen sample.') + (globalThis.__QFH_RESEARCH_PROFILE__?.modelProvider === 'glm_coding'
                ? ' Current trials use GLM 5.3 Flash through Coding Plan Pro until 18:00 Beijing on 13 November. Subscription quota is bounded and recorded separately; the original 200 CNY cash cap is retained.'
                : ' DeepSeek runs only 12:00–14:00 and 18:00–24:00 Beijing, within the original shared 200 CNY cap.') + ' No backtest or publication is included.'
              : 'Initial scope: one symbol, up to three calendar days, close price only. iFind and RQData each allow one data query and one authentication request. BaoStock allows three attempts, including two retained failed attempts. Exact repeats reuse saved results.'),
          h('p', { style: { margin: 0, fontSize: 13 } },
            'Credentials stay in the local DSH credential store. iFind uses the current access token and never rotates it automatically.')))
    }

    function ModelSettings() {
      return h('section', { 'aria-label': 'Research guard',
        style: { display: 'grid', gap: 12, maxWidth: 640, minWidth: 0, padding: '12px 4px' } },
        h('h3', { style: { margin: 0 } }, 'Research guard'),
        h('p', { style: { margin: 0 } },
          'Use the zai-coding-cn provider above to save your Coding Plan Pro API key. Saving makes no provider request.'),
        h('p', { style: { margin: 0 } },
          'GLM 5.3 Flash is pinned for the supervisor and both native Agent Teams workers. Model and endpoint changes are checked by the host.'),
        h('p', { style: { margin: 0 } },
          'GLM admission ends at 18:00 Beijing on 13 November. The original 200 CNY total cap and a separate subscription quota limit apply to every request. Failed requests stay in the ledger.'),
        h('p', { style: { margin: 0, fontSize: 13 } },
          'Different models per role remain planned. GLM 5.3 requires recorded evidence that Flash is insufficient.'))
    }

    return {
      inject: ['slots', 'remote', 'remote.credentials', 'remote.settings'],
      apply(ctx) {
        const checked = response => {
          if (!response.ok) throw new Error('DSH settings operation failed')
          return response.value
        }
        const operations = {
          async read() {
            const [credentials, settings] = await Promise.all([
              ctx.remote.credentials.describe(refs), ctx.remote.settings.describe(),
            ])
            const form = checked(settings).namespaces.find(x => x.ns === 'qfh-data')
            if (!form) throw new Error('QFH settings are unavailable')
            return { provider: form.value.activeProvider, revision: form.revision,
              researchMode: globalThis.__QFH_RESEARCH_PROFILE__?.enabled === true,
              credentials: checked(credentials) }
          },
          async save(ref, value) { checked(await ctx.remote.credentials.set(ref, value)) },
          async remove(ref) { checked(await ctx.remote.credentials.unset(ref)) },
          async select(provider, revision) {
            checked(await ctx.remote.settings.update('qfh-data', { activeProvider: provider }, revision))
          },
        }
        ctx.slots.inject('settings.section', () => ctx.slots.register({
          name: 'settings.section', id: 'qfh-data', label: () => 'Research data', order: 15,
          inject: () => ({ operations }),
        }, DataSettings))
        ctx.slots.inject('settings.models.footer', () => ctx.slots.register({
          name: 'settings.models.footer', id: 'qfh-models', order: 10,
          inject: () => ({ operations }),
        }, ModelSettings))
      },
    }
  },
})
