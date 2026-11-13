/** Guard extensions around DSH's existing pi-ai provider and Models editor. */
import { credentialRef } from '@deepseek-ai/dsh-credentials'

export async function guardNativeModels(ctx, config) {
  const provider = 'zai-coding-cn'
  const keyRef = credentialRef('ZAI_CODING_CN_API_KEY')
  const oldRef = credentialRef('QFH_GLM_CODING_CREDENTIAL')
  const old = await ctx.credentials.resolve(oldRef)
  if (old) {
    let value
    try { value = JSON.parse(old.value) } catch {}
    if (!value || value.platform !== 'bigmodel-cn' || value.plan !== 'coding' ||
      value.model !== config.model || typeof value.api_key !== 'string' || !value.api_key.trim()) {
      throw new Error('The saved Coding Plan credential cannot be migrated. Use Settings → Models.')
    }
    // Native credential writes preserve the store's locking and owner-only mode.
    // An existing native value wins. Remove the legacy copy so clearing the native
    // key cannot silently resurrect an earlier credential.
    if (!(await ctx.credentials.resolve(keyRef))) await ctx.credentials.set(keyRef, value.api_key.trim())
    await ctx.credentials.unset(oldRef)
  }
  ctx.on('internal/config', (fiber, next) => {
    const raw = next()
    if (fiber.entry?.options.id !== 'llm-pi-ai') return raw
    const profiles = raw?.providers
    const profile = profiles?.[provider]
    const models = profile?.models
    // Settings may supply a partial user layer. Missing fields inherit the
    // deployment profile; inspect concrete prepared routing again below.
    const changed = (value, expected) => value !== undefined && value !== expected
    const refused = [
      ['providers', !profiles || Object.keys(profiles).some(id => id !== provider) || !profile],
      // Deployment !!js values are deferred until configuration resolution.
      // UI writes are strings; the prepared-call check covers the resolved value.
      ['endpoint', typeof profile?.baseURL === 'string' && profile.baseURL !== config.relayURL],
      ['protocol', changed(profile?.api, 'openai-completions')],
      ['credential reference', changed(profile?.apiKeyEnv, 'ZAI_CODING_CN_API_KEY')],
      ['headers', Object.keys(profile?.headers ?? {}).length > 0],
      ['model overrides', Object.keys(profile?.modelOverrides ?? {}).length > 0],
      ['retries', changed(profile?.retryPolicy?.maxRetries, 0)],
      ['model', models !== undefined && (!Array.isArray(models) || models.length !== 1 ||
        models[0].id !== config.model || models[0].maxTokens > config.maxTokens)],
    ].filter(([, failed]) => failed).map(([field]) => field)
    if (refused.length) {
      throw new Error('Research guard: keep zai-coding-cn, GLM 5.3 Flash and the guarded endpoint. API keys remain editable. Refused fields: ' + refused.join(', '))
    }
    return raw
  })
  ctx.on('llm-pi-ai/request-headers', (request, headers, next) => {
    if (request.provider !== provider || request.model !== config.model ||
      request.baseURL !== config.relayURL || !request.sessionId) {
      throw new Error('Research guard refused an unauthorized provider, model or endpoint.')
    }
    headers.set('x-qfh-relay-key', config.relayCredential)
    headers.set('x-qfh-session-id', request.sessionId)
    return next()
  })
}
