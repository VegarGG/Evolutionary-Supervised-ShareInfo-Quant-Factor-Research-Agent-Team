/** Versioned final-output repair on native DSH subagents and Agent Teams tasks. */
import { defineTool } from '@deepseek-ai/dsh-tools'
import { runResearch } from './index.js'

export function registerAdaptiveResearch(ctx, config) {
  const operation = (op, args, exec, signal = exec.signal) => {
    if (!exec.agent) throw new Error('An owning native DSH session is required')
    return runResearch(config, { op, session_id: exec.agent.session.id, args }, signal ?? undefined)
  }
  const output = { schema: { type: 'json' },
    render: (_args, value) => [{ type: 'text', text: JSON.stringify(value) }] }
  const register = tool => ctx.effect(() => ctx.tools.register(defineTool({ output, ...tool })))
  register({ name: 'research_board', description: 'Read the exact current completed output, sources, unit proof, reviews, native task history and submission schemas. Supervisor calls first. No market-data requests.',
    parameters: {}, execute: (_args, exec) => operation('scope', {}, exec) })
  for (const [name, op, field] of [['submit_final_review', 'review', 'review_json'],
    ['amend_final_output', 'amend', 'amendment_json']]) {
    register({ name, description: op === 'review'
      ? 'Reviewer only: submit a version-pinned review of the ENTIRE completed output including all explanations and decision reasons. Use review_schema. On rejection correct the JSON in this same task; on acceptance end briefly.'
      : 'Author only: submit an explanation-only output amendment addressing every issue in the cited review. Use amendment_schema. Preserve computational definition and decision identities. On acceptance end briefly.',
    parameters: { [field]: { type: 'string', required: true } }, isConcurrencySafe: () => false,
    execute: (args, exec) => operation(op, { json: args[field] }, exec) })
  }
  for (const followup of [false, true]) register({
    name: followup ? 'research_followup' : 'research_delegate',
    description: followup
      ? 'Supervisor: adapt to the latest review. Delegate a targeted author correction for needs_revision, then a reviewer check of the amended version. Cite the review_id observed on the board. Each follow-up is a fresh, bounded native DSH task.'
      : 'Supervisor: delegate the initial independent review of the imported completed output. Native DSH Agent Teams required. First role must be reviewer.',
    parameters: {
      role: { type: 'string', enum: followup ? ['author', 'reviewer'] : ['reviewer'], required: true },
      task: { type: 'string', required: true },
      ...(followup ? { review_id: { type: 'string', required: true } } : {}),
    },
    isConcurrencySafe: () => false,
    presentCall: args => ({ card: 'generic', title: `${followup ? 'Follow-up' : 'Final review'} · ${args.role}`,
      kind: 'other', rawInput: args }),
    async execute(args, exec) {
      if (!exec.agent || ctx.subagents.rootOf(exec.agent) !== exec.agent) throw new Error('Only the native root supervisor can delegate')
      if (!ctx.agentTeams.isEnabled(exec.agent)) throw new Error('Enable Use Agent Teams in the model menu')
      const admitted = await operation('begin', args, exec)
      let activation
      let settled = false
      try {
        let task = await ctx.agentTeams.createTask(exec.agent, {
          subject: `${admitted.actor}: ${followup ? 'targeted follow-up' : 'completed-output review'}`,
          description: args.task,
        }, exec.signal)
        activation = await ctx.subagents.startActivation({ provider: 'spawn', parent: exec.agent,
          childId: admitted.child_id, name: admitted.actor, label: admitted.actor,
          agentPreset: 'qfh-worker', maxDepth: 1, delivery: 'caller', signal: exec.signal,
          prompt: [{ type: 'text', text: admitted.prompt }],
          agentOptions: { provider: config.providerId, model: admitted.route.model,
            reasoningEffort: admitted.route.reasoning_effort, maxTokens: config.maxTokens },
        })
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
            result: { stopReason: 'error', diagnostic: 'Native task failed; inspect retained trace.' } }, exec, null) }
          catch { /* Keep any uncertain active marker; never replay automatically. */ }
        }
        throw error
      } finally { await activation?.dispose() }
    },
  })
  register({ name: 'finalize_research_output',
    description: 'Supervisor only: freeze the current completed output after its clean independent review and completed native tasks. No new prose is accepted here. This is diagnostic review, not evaluation or publication. End with the returned output ID.',
    parameters: { output_id: { type: 'string', required: true }, review_id: { type: 'string', required: true } },
    isConcurrencySafe: () => false, execute: (args, exec) => operation('finalize', args, exec) })
}
