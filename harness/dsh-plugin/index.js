/** DSH-native credentials UI and a small, read-only research data tool surface. */
import { spawn } from 'node:child_process'
import { isAbsolute } from 'node:path'
import Schema from '@deepseek-ai/schemastery'
import { credentialRef } from '@deepseek-ai/dsh-credentials'
import { defineTool } from '@deepseek-ai/dsh-tools'

export const name = 'qfh-data'
export const inject = ['credentials', 'tools']
export const Config = Schema.object({
  activeProvider: Schema.union(['baostock', 'ifind', 'rqdata']).default('baostock').volatile()
    .description('Data source for new research sessions. Existing sessions retain their source.'),
  python: Schema.string().required(),
  sourceRoot: Schema.string().required(),
  policyPath: Schema.string().required(),
  privateRoot: Schema.string().required(),
  researchConfig: Schema.string().default(''),
  researchPrivateRoot: Schema.string().default(''),
  researchSampleDescription: Schema.string().default(''),
  researchModelProvider: Schema.union(['deepseek', 'glm_coding']).default('deepseek'),
  enabledKinds: Schema.array(Schema.string()).default(['bars', 'report_summaries', 'announcements', 'news']),
  requestTimeoutMs: Schema.number().min(1000).max(180000).default(90000),
})

export function runBackend(config, request, signal) {
  return runPython(config, ['-m', 'qfh.data_gateway', '--policy', config.policyPath,
    '--root', config.privateRoot], request, signal)
}

export function runResearch(config, request, signal) {
  return runPython(config, ['-m', 'qfh.research', '--config', config.researchConfig,
    '--private', config.researchPrivateRoot], request, signal)
}

function runPython(config, args, request, signal) {
  return new Promise((resolve, reject) => {
    const child = spawn(config.python, args, {
      env: { PATH: process.env.PATH ?? '', PYTHONPATH: config.sourceRoot },
      stdio: ['pipe', 'pipe', 'ignore'], signal,
    })
    let output = ''
    const timer = setTimeout(() => { child.kill('SIGTERM') }, config.requestTimeoutMs)
    child.stdout.on('data', chunk => {
      output += chunk.toString('utf8')
      if (Buffer.byteLength(output) > 262144) child.kill('SIGTERM')
    })
    child.once('error', () => { clearTimeout(timer); reject(new Error('Data adapter could not start')) })
    child.once('close', code => {
      clearTimeout(timer)
      if (code !== 0) return reject(new Error('Data adapter stopped; inspect data usage before retrying'))
      try {
        const result = JSON.parse(output)
        if (!result.ok) return reject(new Error(result.error))
        resolve(result.result)
      } catch { reject(new Error('Data adapter returned an invalid response')) }
    })
    child.stdin.on('error', () => { /* Process close reports the failed attempt. */ })
    child.stdin.end(JSON.stringify(request) + '\n')
  })
}

export function apply(ctx, config) {
  for (const key of ['python', 'sourceRoot', 'policyPath', 'privateRoot']) {
    if (!isAbsolute(config[key])) throw new Error(`qfh-data ${key} must be an absolute path`)
  }
  // Static configuration is intentionally absent from editable settings forms.
  // Publish only this non-secret UI fact through DSH's native page bootstrap.
  ctx.on('webserver/index-inject', table => {
    table.push({ kind: 'global', name: '__QFH_RESEARCH_PROFILE__',
      value: { enabled: !!config.researchConfig, sampleDescription: config.researchSampleDescription,
        modelProvider: config.researchModelProvider } })
  })
  for (const [toolName, kind, description] of [
    ['market_daily_bars', 'bars', 'Fetch daily stock data from the selected data source within the operator quota.'],
    ['research_reports', 'report_summaries', 'Read broker report summaries where supported and enabled.'],
    ['company_announcements', 'announcements', 'Read company disclosure metadata and original document links where enabled.'],
    ['research_news', 'news', 'Read news titles, source links and publication times where supported and enabled.'],
  ]) {
    if (!config.enabledKinds.includes(kind)) continue
    ctx.effect(() => ctx.tools.register(defineTool({
      name: toolName,
      description: config.researchConfig && kind === 'bars'
        ? 'Required first evidence step for EACH worker: call with the exact scope.query and await success. Grants this session access to the permitted sample. Composed samples reuse frozen cache with no new vendor query. An evidence ID from another agent is not an access grant.'
        : description,
      parameters: {
        symbols: { type: 'array', required: true, items: { type: 'string' },
          description: 'Canonical identifiers, e.g. 000001.XSHE; converted for the selected source.' },
        start: { type: 'string', required: true, description: 'First date, YYYY-MM-DD' },
        end: { type: 'string', required: true, description: 'Last date, YYYY-MM-DD' },
        fiscal_year: { type: 'string', description: 'Required for broker report summaries' },
      },
      output: { schema: { type: 'json' }, render: (_args, value) => [{ type: 'text', text: JSON.stringify(value) }] },
      async execute(args, exec) {
        if (!exec.agent) throw new Error('Research data requires an owning session')
        const provider = config.activeProvider.get()
        if (config.researchConfig) return runResearch(config, { op: 'data',
          session_id: exec.agent.session.id, selected_provider: provider,
          args: { kind, query: { symbols: args.symbols, start: args.start, end: args.end } } }, exec.signal)
        let payload = {}
        if (provider !== 'baostock') {
          const credential = await ctx.credentials.resolve(credentialRef(
            provider === 'ifind' ? 'QFH_IFIND_CREDENTIAL' : 'QFH_RQDATA_LICENSE'))
          if (!credential) throw new Error(`Configure ${provider} in DSH Settings → Research data`)
          try {
            payload = provider === 'rqdata' ? { license: credential.value } : JSON.parse(credential.value)
            if (provider === 'ifind' && (Object.keys(payload).length !== 1 ||
              !['access_token', 'refresh_token'].includes(Object.keys(payload)[0]) ||
              typeof Object.values(payload)[0] !== 'string' || !Object.values(payload)[0].trim())) throw new Error()
          } catch { throw new Error('Data credential is invalid; save it again in Research data settings') }
        }
        return runBackend(config, { provider, kind, run_id: exec.agent.session.id,
          query: { symbols: args.symbols, start: args.start, end: args.end },
          fiscal_year: args.fiscal_year, credentials: payload }, exec.signal)
      },
      presentCall: args => ({ card: 'generic', title: description, kind: 'other', rawInput: args }),
    })))
  }
  ctx.effect(() => ctx.tools.register(defineTool({
    name: 'read_research_evidence',
    description: 'Read an immutable result already fetched by THIS research session. First call market_daily_bars and await success, even when another agent supplied the evidence ID. Do not batch this read before that access step completes.',
    parameters: {
      evidence_id: { type: 'string', required: true, description: 'Evidence hash from a source tool' },
      offset: { type: 'integer', description: 'First row, default 0' },
      limit: { type: 'integer', description: 'Rows to return, 1..20, default 20' },
    },
    output: { schema: { type: 'json' }, render: (_args, value) => [{ type: 'text', text: JSON.stringify(value) }] },
    async execute(args, exec) {
      if (!exec.agent) throw new Error('Research data requires an owning session')
      if (config.researchConfig) return runResearch(config, { op: 'data',
        session_id: exec.agent.session.id, selected_provider: config.activeProvider.get(),
        args: { kind: 'read', ...args } }, exec.signal)
      return runBackend(config, { provider: config.activeProvider.get(), kind: 'read',
        run_id: exec.agent.session.id, ...args }, exec.signal)
    },
  })))
}
