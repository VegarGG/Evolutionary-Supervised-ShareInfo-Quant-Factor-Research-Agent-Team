/** Open research case on native DSH Agent Teams and subagent inference. */
import { defineTool } from '@deepseek-ai/dsh-tools'
import { runResearch } from './index.js'

export function registerCaseResearch(ctx, config) {
  const operation = (op, args, exec, signal = exec.signal) => {
    if (!exec.agent) throw new Error('An owning native DSH session is required')
    return runResearch(config, { op, session_id: exec.agent.session.id, args }, signal ?? undefined)
  }
  const output = { schema: { type: 'json' }, render: (_args, value) => [{ type: 'text', text: JSON.stringify(value) }] }
  const register = tool => ctx.effect(() => ctx.tools.register(defineTool({ output, ...tool })))
  register({ name: 'case_board', description: 'Read the frozen case, exact candidate, sources, tasks, findings, reviews and role submission schema. Supervisor calls first.',
    parameters: {}, execute: (_args, exec) => operation('scope', {}, exec) })
  register({ name: 'case_read', description: 'Read one page of an immutable source or event named by case_board. Concatenate all text pages before interpreting a non-inline artifact; page numbering starts at zero.',
    parameters: { resource_id: { type: 'string', required: true }, page: { type: 'integer', required: true } },
    execute: (args, exec) => operation('read', args, exec) })
  register({ name: 'inspect_case_factor', description: 'Compute descriptive scores/coverage on frozen BaoStock rows. Designer must inspect its chosen spec before submission. No backtest or provider request.',
    parameters: { spec_json: { type: 'string', required: true } }, isConcurrencySafe: () => false,
    execute: (args, exec) => operation('inspect', { json: args.spec_json }, exec) })
  for (const [name, op] of [['submit_case_findings', 'findings'], ['revise_case_factor', 'revise'], ['review_case_factor', 'review']]) {
    register({ name, description: `Submit assigned ${op}: payload_json must match submission_schema. Quote frozen sources exactly. Repair rejected JSON in this task; after acceptance end briefly.`,
      parameters: { payload_json: { type: 'string', required: true } }, isConcurrencySafe: () => false,
      execute: (args, exec) => operation(op, { json: args.payload_json }, exec) })
  }
  register({ name: 'case_task', description: 'Supervisor delegates a native stage. Fixed: locked analyze/design/review sequence and assignments. Adaptive: choose assignments from observed findings/reviews; cite their IDs in basis_ids after first task. Stop on failed worker or caps.',
    parameters: { stage: { type: 'string', enum: ['analyze', 'design', 'review'], required: true },
      task: { type: 'string', required: true }, basis_ids: { type: 'array', items: { type: 'string' }, required: true } },
    isConcurrencySafe: () => false,
    async execute(args, exec) {
      if (!exec.agent || ctx.subagents.rootOf(exec.agent) !== exec.agent) throw new Error('Only native root may delegate')
      if (!ctx.agentTeams.isEnabled(exec.agent)) throw new Error('Enable Use Agent Teams')
      const admitted = await operation('begin', args, exec)
      let activation
      let settled = false
      try {
        let task = await ctx.agentTeams.createTask(exec.agent, { subject: `${admitted.actor}: ${args.stage}`,
          description: admitted.assignment }, exec.signal)
        activation = await ctx.subagents.startActivation({ provider: 'spawn', parent: exec.agent,
          childId: admitted.child_id, name: admitted.actor, label: admitted.actor,
          agentPreset: 'qfh-worker', maxDepth: 1, delivery: 'caller', signal: exec.signal,
          prompt: [{ type: 'text', text: admitted.prompt }],
          agentOptions: { provider: config.providerId, model: admitted.route.model,
            reasoningEffort: admitted.route.reasoning_effort, maxTokens: config.maxTokens } })
        task = await ctx.agentTeams.updateTask(exec.agent, { taskId: task.id,
          expectedRevision: task.revision, action: 'reassign', owner: activation.childId }, exec.signal)
        const result = await activation.result
        settled = true
        const report = await operation('finish', { child_id: admitted.child_id, result }, exec, null)
        if (report.task.body.status === 'completed') task = await ctx.agentTeams.updateTask(exec.agent,
          { taskId: task.id, expectedRevision: task.revision, action: 'complete' }, exec.signal)
        return { ...report, team_task: task }
      } catch (error) {
        if (!settled) {
          try { await operation('finish', { child_id: admitted.child_id,
            result: { stopReason: 'error', diagnostic: 'Native task failed; retain trace.' } }, exec, null) }
          catch { /* Keep uncertain state; never automatically replay. */ }
        }
        throw error
      } finally { await activation?.dispose() }
    } })
  register({ name: 'finalize_case', description: 'Freeze exact clean-reviewed candidate after native tasks complete. Pending independent audit; no official evaluation/publication. End with ID only.',
    parameters: { output_id: { type: 'string', required: true }, review_id: { type: 'string', required: true } },
    isConcurrencySafe: () => false, execute: (args, exec) => operation('finalize', args, exec) })
}
