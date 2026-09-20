export async function saveThenPublish({ api, name, chapter, content, isCurrent, onSaved }) {
  if (!content.trim()) throw new Error('正文不能为空')
  await api.savePendingChapter(name, chapter, content)
  if (!isCurrent()) return null
  onSaved()
  return api.runTask(name, 'publish', { chapter })
}
