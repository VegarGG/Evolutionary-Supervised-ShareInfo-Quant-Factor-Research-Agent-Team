/** Bounded QFH roles on DSH's native subagent lifecycle and Agent Teams board. */
import { isAbsolute } from 'node:path'
import Schema from '@deepseek-ai/schemastery'
import { defineTool } from '@deepseek-ai/dsh-tools'
import { catalogModelInfo, registerDeepSeekProvider, resolveAdapterOptions } from '@deepseek-ai/dsh-llm-deepseek'
import { runResearch } from './index.js'
import { guardNativeModels } from './native-models.js'

export const name = 'qfh-research'
export const inject = ['llm', 'tools', 'subagents', 'agentTeams', 'credentials']
export const Config = Schema.object({
  python: Schema.string().required(),
  sourceRoot: Schema.string().required(),
  researchConfig: Schema.string().required(),
  researchPrivateRoot: Schema.string().required(),
  relayURL: Schema.string().required(),
  relayCredential: Schema.string().required(),
  model: Schema.string().required(),
  providerId: Schema.union(['qfh-deepseek', 'zai-coding-cn']).default('qfh-deepseek'),
  modelProvider: Schema.union(['deepseek', 'glm_coding']).default('deepseek'),
  routeLabel: Schema.string().default('DeepSeek · guarded research'),
  maxTokens: Schema.number().required(),
  reasoningEffort: Schema.union(['low', 'high', 'max']).required(),
  requestTimeoutMs: Schema.number().default(90000),
})

export async function apply(ctx, config) {
  for (const field of ['python', 'sourceRoot', 'researchConfig', 'researchPrivateRoot']) {
    if (!isAbsolute(config[field])) throw new Error(`qfh-research ${field} must be absolute`)
  }
  const endpoint = new URL(config.relayURL)
  if (endpoint.hostname !== '127.0.0.1' || endpoint.protocol !== 'http:') {
    throw new Error('QFH model transport must use the local budget guard')
  }
  if (config.modelProvider === 'glm_coding') {
    await guardNativeModels(ctx, config)
  } else {
    const model = { id: config.model, name: config.routeLabel, maxTokens: config.maxTokens,
      inputModalities: ['text'] }
    const connection = resolveAdapterOptions({ baseURL: config.relayURL,
      models: [model], maxTokens: config.maxTokens, reasoningEffort: config.reasoningEffort,
      retryPolicy: { mode: 'normal', maxRetries: 0 } })
    registerDeepSeekProvider(ctx, config.providerId, {
      providerName: config.routeLabel, options: () => connection,
      resolveAuth: async () => {
        const headers = { 'x-api-key': config.relayCredential }
        return { headers }
      },
      discoverModels: async provider => [catalogModelInfo(provider, model)],
      admit: (_connection, requested) => {
        if (requested !== config.model) throw new Error('Only the authorized trial model is enabled')
      },
    })
  }
  const output = { schema: { type: 'json' },
    render: (_args, value) => [{ type: 'text', text: JSON.stringify(value) }] }
  const operation = (op, args, exec, signal = exec.signal) => {
    if (!exec.agent) throw new Error('An owning research session is required')
    return runResearch(config, { op, session_id: exec.agent.session.id, args }, signal ?? undefined)
  }
  const register = tool => ctx.effect(() => ctx.tools.register(defineTool({ output, ...tool })))
  register({ name: 'research_scope',
    description: 'Read the fixed research sample, budget, worker status and required draft/report schemas. Supervisor: call first. Workers already receive scope and schema in their assignment; use this only for a needed status check.',
    parameters: {}, execute: (_args, exec) => operation('scope', {}, exec) })
  register({ name: 'research_metrics',
    description: 'Compute deterministic daily returns, moments and lookback/next-close alignment on granted closes. Copy measurement_id and fact keys into worker measurement_refs; never recalculate observations in prose. This is not a strategy backtest or evaluation.',
    parameters: { evidence_id: { type: 'string', required: true } },
    execute: (args, exec) => operation('metrics', args, exec) })
  register({ name: 'submit_worker_report',
    description: 'Worker only: validate and freeze your own cited report before ending. Rejection returns precise schema/provenance issues to correct within this same active turn and request allowance. On acceptance end with a brief acknowledgment; never rewrite the accepted report.',
    parameters: { report_json: { type: 'string', required: true,
      description: 'JSON object matching worker_output_schema; respect all array limits and measurement references.' } },
    isConcurrencySafe: () => false,
    execute: (args, exec) => operation('submit_report', args, exec) })
  register({ name: 'research_specification',
    description: 'Execute one fully resolved close-return contrast specification on your own evidence. Returns canonical formula, tie/support counts, exact label overlap geometry and a host-derived inference outcome. Tiny samples return insufficient_data, never confirmation or disproof. This is development analysis, not a strategy backtest or official evaluation.',
    parameters: { evidence_id: { type: 'string', required: true },
      specification_json: { type: 'string', required: true,
        description: 'One concrete JSON object matching specification_schema; every parameter required, no alternative methods or unresolved symbols.' } },
    execute: (args, exec) => operation('specification', args, exec) })
  register({ name: 'research_worker',
    description: 'Supervisor only: run one named worker once and receive its cited report. First use researcher to propose; then reviewer to independently check the proposal. Each uses native DSH sessions and the Agent Teams task board. Workers cannot delegate.',
    parameters: {
      role: { type: 'string', enum: ['researcher', 'reviewer'], required: true },
      task: { type: 'string', required: true,
        description: 'Self-contained research assignment. Include earlier findings when requesting review.' },
    },
    isConcurrencySafe: () => false,
    presentCall: args => ({ card: 'generic', title: `Research team · ${args.role}`, kind: 'other', rawInput: args }),
    async execute(args, exec) {
      if (!exec.agent || ctx.subagents.rootOf(exec.agent) !== exec.agent) {
        throw new Error('Only the root supervisor can delegate research')
      }
      if (!ctx.agentTeams.isEnabled(exec.agent)) {
        throw new Error('Enable Use Agent Teams in the session model menu before running workers')
      }
      const admitted = await operation('begin_worker', args, exec)
      let activation
      let settlementAttempted = false
      try {
        let task = await ctx.agentTeams.createTask(exec.agent,
          { subject: `${args.role}: bounded A-share research`, description: args.task }, exec.signal)
        activation = await ctx.subagents.startActivation({
          provider: 'spawn', parent: exec.agent, childId: admitted.child_id,
          name: args.role, label: `${args.role} · BaoStock evidence`,
          agentPreset: 'qfh-worker', maxDepth: 1, delivery: 'caller', signal: exec.signal,
          prompt: [{ type: 'text', text: admitted.prompt }],
          agentOptions: { provider: config.providerId, model: admitted.route.model,
            reasoningEffort: admitted.route.reasoning_effort, maxTokens: config.maxTokens },
        })
        task = await ctx.agentTeams.updateTask(exec.agent, { taskId: task.id,
          expectedRevision: task.revision, action: 'reassign', owner: activation.childId }, exec.signal)
        const result = await activation.result
        // A failed or uncertain settlement must not be submitted a second time.
        // The backend retains the actual result, including rejected reports.
        settlementAttempted = true
        const report = await operation('finish_worker', { child_id: admitted.child_id, result }, exec, null)
        task = await ctx.agentTeams.updateTask(exec.agent, { taskId: task.id,
          expectedRevision: task.revision, action: 'complete' }, exec.signal)
        return { ...report, team_task: task }
      } catch (error) {
        if (!settlementAttempted) {
          try { await operation('finish_worker', { child_id: admitted.child_id,
            result: { stopReason: 'error', output: [], diagnostic: 'Native worker or report validation failed; inspect retained logs.' } }, exec, null) }
          catch { /* The original worker settlement or active marker remains durable. */ }
        }
        throw error
      } finally { await activation?.dispose() }
    },
  })
  register({ name: 'submit_research_draft',
    description: 'Supervisor only: record one immutable draft after both workers complete. Validates citations and contribution decisions. Does not evaluate, publish, trade, or promote.',
    parameters: { draft_json: { type: 'string', required: true,
      description: 'JSON object matching draft_schema returned by research_scope.' } },
    execute: (args, exec) => operation('draft', JSON.parse(args.draft_json), exec),
  })
}
