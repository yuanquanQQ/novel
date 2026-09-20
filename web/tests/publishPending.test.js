import test from 'node:test'
import assert from 'node:assert/strict'
import { saveThenPublish } from '../src/lib/publishPending.js'

function options(overrides = {}) {
  return {
    name: 'test', chapter: 3, content: '最新正文',
    isCurrent: () => true, onSaved: () => {}, ...overrides,
  }
}

test('saves the latest body before starting publication', async () => {
  const calls = []
  const result = await saveThenPublish(options({
    api: {
      async savePendingChapter(...args) { calls.push(['save', ...args]) },
      async runTask(...args) { calls.push(['publish', ...args]); return { task_id: '1' } },
    },
    onSaved: () => calls.push(['saved']),
  }))
  assert.deepEqual(calls, [
    ['save', 'test', 3, '最新正文'], ['saved'], ['publish', 'test', 'publish', { chapter: 3 }],
  ])
  assert.equal(result.task_id, '1')
})

test('save failure preserves the draft and prevents publication', async () => {
  await assert.rejects(saveThenPublish(options({
    api: {
      async savePendingChapter() { throw new Error('save failed') },
      runTask() { assert.fail('must not publish') },
    },
    onSaved: () => assert.fail('must not mark saved'),
  })), /save failed/)
})

test('switching context during save prevents a stale publication', async () => {
  let current = true
  const result = await saveThenPublish(options({
    api: {
      async savePendingChapter() { current = false },
      runTask() { assert.fail('must not publish') },
    },
    isCurrent: () => current,
    onSaved: () => assert.fail('must not update the new context'),
  }))
  assert.equal(result, null)
})

test('empty text makes no API calls', async () => {
  await assert.rejects(saveThenPublish(options({ content: ' \n ', api: {} })), /正文不能为空/)
})
